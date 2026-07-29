"""File-first question bank API.

This is the production-oriented minimal question model:

- question.md|tex|txt: question body
- answer.md|tex|txt: answer
- assets/: images or PDFs referenced by the body files
- metadata.yaml: optional loose metadata, never the core structure
"""

from __future__ import annotations

import re
import shutil
import subprocess
import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.services.file_question_store import (
    INDEX_PATH,
    LOCAL_VECTOR_MODEL,
    FileQuestion,
    asset_path,
    load_or_rebuild_index,
    list_questions,
    read_question,
    rebuild_index,
    search_questions,
    validate_question_id,
    write_question,
)
from app.services.file_question_candidates import (
    approve_candidate,
    candidate_asset_path,
    list_candidates,
    read_candidate,
    reject_candidate,
    validate_candidate_id,
)
from app.services.file_knowledge_points import (
    list_knowledge_points,
    merge_knowledge_points,
    question_ids_for_knowledge_point,
    rebuild_knowledge_points,
    rename_knowledge_point,
)
from app.services.file_question_importer import (
    SUPPORTED_EXTENSIONS,
    import_source_file,
    llm_import_config,
    source_type_from_filename,
)
from app.services.file_import_jobs import (
    add_source_file,
    append_job_error,
    create_job,
    kick_worker,
    list_jobs as list_import_jobs,
    mark_job_queued,
    record_candidate_resolution,
    read_job,
    source_type_or_error,
    validate_job_id,
)
from app.services.llm import LLMNotConfiguredError

router = APIRouter()


STRUCTURED_JSON_ASSET_SOURCE_TYPES = {"image"}
_FILE_EXPORT_MAX_WORKERS = max(1, int(settings.FILE_EXPORT_MAX_WORKERS or 1))
_TEX_COMPILE_EXECUTOR = ThreadPoolExecutor(
    max_workers=_FILE_EXPORT_MAX_WORKERS,
    thread_name_prefix="file-paper-tex",
)
_TEX_COMPILE_GATE = BoundedSemaphore(_FILE_EXPORT_MAX_WORKERS)


class FileAssetRead(BaseModel):
    filename: str
    path: str
    url: str
    mime_hint: str


class FileQuestionSummary(BaseModel):
    question_id: str
    title: str
    preview: str
    metadata: dict = Field(default_factory=dict)
    assets: list[FileAssetRead] = Field(default_factory=list)
    updated_at: str
    size_bytes: int
    indexed: bool
    score: float | None = None


class FileQuestionRead(FileQuestionSummary):
    question_body: str
    answer_body: str
    question_format: str
    answer_format: str | None
    content_hash: str


class FileQuestionCreate(BaseModel):
    question_id: str | None = None
    question_body: str = Field(..., min_length=1)
    answer_body: str = ""
    question_format: str = Field("markdown", pattern="^(markdown|latex|text)$")
    answer_format: str | None = Field(None, pattern="^(markdown|latex|text)$")
    metadata: dict = Field(default_factory=dict)
    overwrite: bool = False


class PaginatedFileQuestions(BaseModel):
    items: list[FileQuestionSummary]
    total: int
    skip: int
    limit: int


class ReindexFileQuestionsResponse(BaseModel):
    status: str
    model: str
    question_count: int
    index_path: str
    created_at: str


class FileImportConfig(BaseModel):
    enabled: bool
    configured: bool
    provider: str
    model: str
    supports_vision: bool
    vision_configured: bool
    supported_extensions: list[str]


class FileQuestionStats(BaseModel):
    total: int
    indexed: int
    with_assets: int
    human_review_needed: int
    pending_review: int


class FileKnowledgePointRead(BaseModel):
    knowledge_point_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    count: int


class FileKnowledgePointRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)


class FileKnowledgePointMerge(BaseModel):
    source_id: str
    target_id: str


class FileQuestionImportItem(FileQuestionSummary):
    source_filename: str


class FileQuestionImportError(BaseModel):
    filename: str
    error: str


class FileQuestionImportResponse(BaseModel):
    imported: list[FileQuestionImportItem] = Field(default_factory=list)
    pending_review: list["FileQuestionCandidateRead"] = Field(default_factory=list)
    errors: list[FileQuestionImportError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    llm_assist_requested: bool
    llm_assist_used: bool
    question_count: int
    review_count: int


class FileImportJobSource(BaseModel):
    filename: str | None = None
    source_type: str | None = None
    relative_path: str | None = None
    size_bytes: int | None = None
    process: bool = True
    status: str = "queued"
    error: str | None = None


class FileImportJobRead(BaseModel):
    job_id: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    use_llm_assist: bool
    overwrite: bool
    source_files: list[FileImportJobSource] = Field(default_factory=list)
    total_files: int
    processed_files: int
    current_file: str | None = None
    created_question_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    imported_count: int
    review_count: int = 0
    errors: list[FileQuestionImportError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    llm_used: bool = False
    index_rebuilt: bool = False


class FileQuestionUpdate(BaseModel):
    """Schema for updating a file-backed question's body/answer."""
    question_body: str | None = None
    answer_body: str | None = None


class FileQuestionCandidateRead(BaseModel):
    candidate_id: str
    state: str
    question_body: str
    answer_body: str = ""
    question_format: str = "markdown"
    answer_format: str | None = None
    metadata: dict = Field(default_factory=dict)
    assets: list[dict] = Field(default_factory=list)
    proposed_question_id: str
    source_filename: str
    source_type: str
    source_document_hash: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    reviewed_at: str | None = None
    committed_at: str | None = None
    committed_question_id: str | None = None
    rejection_reason: str | None = None


class FileQuestionCandidateApprove(BaseModel):
    question_body: str | None = None
    answer_body: str | None = None
    metadata: dict | None = None
    acknowledge_warnings: bool = False


class FileQuestionCandidateReject(BaseModel):
    reason: str = ""


class FileQuestionCandidateCommitResponse(BaseModel):
    candidate: FileQuestionCandidateRead
    question: FileQuestionRead


FileQuestionImportResponse.model_rebuild()


def _job_read(manifest: dict) -> FileImportJobRead:
    return FileImportJobRead(
        job_id=str(manifest.get("job_id", "")),
        status=str(manifest.get("status", "unknown")),
        created_at=str(manifest.get("created_at", "")),
        started_at=manifest.get("started_at"),
        finished_at=manifest.get("finished_at"),
        use_llm_assist=bool(manifest.get("use_llm_assist")),
        overwrite=bool(manifest.get("overwrite")),
        source_files=[
            FileImportJobSource(**item)
            for item in manifest.get("source_files", [])
            if isinstance(item, dict)
        ],
        total_files=int(manifest.get("total_files") or 0),
        processed_files=int(manifest.get("processed_files") or 0),
        current_file=manifest.get("current_file"),
        created_question_ids=[
            str(item)
            for item in manifest.get("created_question_ids", [])
            if item
        ],
        candidate_ids=[
            str(item)
            for item in manifest.get("candidate_ids", [])
            if item
        ],
        imported_count=int(manifest.get("imported_count") or 0),
        review_count=int(manifest.get("review_count") or 0),
        errors=[
            FileQuestionImportError(
                filename=str(item.get("filename") or ""),
                error=str(item.get("error") or ""),
            )
            for item in manifest.get("errors", [])
            if isinstance(item, dict)
        ],
        warnings=[
            str(item)
            for item in manifest.get("warnings", [])
            if item
        ],
        llm_used=bool(manifest.get("llm_used")),
        index_rebuilt=bool(manifest.get("index_rebuilt")),
    )


class FilePaperRequest(BaseModel):
    title: str = "Physics Paper"
    question_ids: list[str] = Field(default_factory=list)
    search_query: str | None = None
    question_count: int | None = Field(None, ge=1, le=200)
    include_answers: bool = Field(
        True,
        description="Deprecated compatibility flag. File-question export always writes a separate answers.tex/pdf.",
    )


class FilePaperResponse(BaseModel):
    status: str
    export_id: str
    title: str
    question_count: int
    question_ids: list[str]

    # ── Question paper outputs ──
    question_tex_url: str
    question_pdf_url: str | None = None
    question_build_log_url: str | None = None

    # ── Answer paper outputs ──
    answer_tex_url: str
    answer_pdf_url: str | None = None
    answer_build_log_url: str | None = None
    manifest_url: str
    question_compile_error_id: str | None = None
    answer_compile_error_id: str | None = None

    # ── Legacy compat fields ──
    tex_path: str = ""
    tex_url: str = ""
    pdf_path: str | None = None
    pdf_url: str | None = None
    build_log_path: str | None = None
    build_log_url: str | None = None


def _summary(question: FileQuestion) -> FileQuestionSummary:
    return FileQuestionSummary(
        question_id=question.question_id,
        title=question.title,
        preview=question.preview,
        metadata=question.metadata,
        assets=[FileAssetRead(**asset.__dict__) for asset in question.assets],
        updated_at=question.updated_at,
        size_bytes=question.size_bytes,
        indexed=question.indexed,
        score=question.score,
    )


def _detail(question: FileQuestion) -> FileQuestionRead:
    return FileQuestionRead(
        **_summary(question).model_dump(),
        question_body=question.question_body,
        answer_body=question.answer_body,
        question_format=question.question_format,
        answer_format=question.answer_format,
        content_hash=question.content_hash,
    )


def _candidate_read(payload: dict) -> FileQuestionCandidateRead:
    return FileQuestionCandidateRead.model_validate(payload)


def _format_from_filename(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".tex", ".latex"}:
        return "latex"
    if suffix in {".txt"}:
        return "text"
    return "markdown"


def _import_item(source_filename: str, question: FileQuestion) -> FileQuestionImportItem:
    return FileQuestionImportItem(
        source_filename=source_filename,
        **_summary(question).model_dump(),
    )


@router.get("", response_model=PaginatedFileQuestions)
@router.get("/", response_model=PaginatedFileQuestions)
async def list_file_questions(
    q: str | None = Query(None, description="Search text"),
    knowledge_point_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
):
    """List or search file-backed questions."""
    items = search_questions(q or "", limit=10_000)
    if knowledge_point_id:
        try:
            allowed_ids = question_ids_for_knowledge_point(knowledge_point_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Knowledge point not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items = [item for item in items if item.question_id in allowed_ids]
    page = items[skip : skip + limit]
    return PaginatedFileQuestions(
        items=[_summary(item) for item in page],
        total=len(items),
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=FileQuestionRead, status_code=201)
@router.post("/", response_model=FileQuestionRead, status_code=201)
async def create_file_question(payload: FileQuestionCreate):
    """Create a question from plain body/answer files."""
    try:
        question = write_question(
            question_id=payload.question_id,
            question_body=payload.question_body,
            answer_body=payload.answer_body,
            question_format=payload.question_format,
            answer_format=payload.answer_format,
            metadata=payload.metadata,
            overwrite=payload.overwrite,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Question already exists: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rebuild_index()
    question = read_question(question.question_id)
    return _detail(question)


@router.post("/upload", response_model=FileQuestionRead, status_code=201)
async def upload_file_question(
    question_id: str | None = Form(None),
    question_file: UploadFile = File(...),
    answer_file: UploadFile | None = File(None),
    assets: list[UploadFile] | None = File(None),
    overwrite: bool = Form(False),
):
    """Upload question body, optional answer body, and optional assets."""
    if not question_file.filename:
        raise HTTPException(status_code=400, detail="question_file is required")

    question_body = (await question_file.read()).decode("utf-8")
    answer_body = ""
    if answer_file is not None:
        answer_body = (await answer_file.read()).decode("utf-8")

    asset_payloads: list[tuple[str, bytes]] = []
    for asset in assets or []:
        if asset.filename:
            asset_payloads.append((Path(asset.filename).name, await asset.read()))

    try:
        question = write_question(
            question_id=question_id,
            question_body=question_body,
            answer_body=answer_body,
            question_format=_format_from_filename(question_file.filename),
            answer_format=_format_from_filename(answer_file.filename if answer_file else None),
            assets=asset_payloads,
            overwrite=overwrite,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Question already exists: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rebuild_index()
    question = read_question(question.question_id)
    return _detail(question)


@router.get("/stats", response_model=FileQuestionStats)
async def get_file_question_stats():
    """Return lightweight stats for the file-backed question bank."""
    questions = list_questions()
    return FileQuestionStats(
        total=len(questions),
        indexed=sum(1 for question in questions if question.indexed),
        with_assets=sum(1 for question in questions if question.assets),
        human_review_needed=sum(
            1
            for question in questions
            if bool(question.metadata.get("human_review_needed"))
        ),
        pending_review=len(list_candidates(state="needs_review", limit=100_000)),
    )


@router.get("/knowledge-points", response_model=list[FileKnowledgePointRead])
async def get_file_knowledge_points():
    return [
        FileKnowledgePointRead.model_validate(item)
        for item in list_knowledge_points()
    ]


@router.post("/knowledge-points/rebuild", response_model=list[FileKnowledgePointRead])
async def rebuild_file_knowledge_points():
    payload = rebuild_knowledge_points()
    return [
        FileKnowledgePointRead.model_validate(item)
        for item in payload.get("items", [])
    ]


@router.patch(
    "/knowledge-points/{knowledge_point_id}",
    response_model=FileKnowledgePointRead,
)
async def rename_file_knowledge_point(
    knowledge_point_id: str,
    payload: FileKnowledgePointRename,
):
    try:
        return FileKnowledgePointRead.model_validate(
            rename_knowledge_point(knowledge_point_id, payload.name)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Knowledge point not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/knowledge-points/merge", response_model=list[FileKnowledgePointRead])
async def merge_file_knowledge_points(payload: FileKnowledgePointMerge):
    try:
        result = merge_knowledge_points(payload.source_id, payload.target_id)
        return [
            FileKnowledgePointRead.model_validate(item)
            for item in result.get("items", [])
        ]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Knowledge point not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/import/config", response_model=FileImportConfig)
async def get_file_import_config():
    """Return import capabilities without exposing secrets."""
    return FileImportConfig(
        **llm_import_config(),
        supported_extensions=sorted(SUPPORTED_EXTENSIONS),
    )


@router.post("/import", response_model=FileQuestionImportResponse)
async def import_file_questions(
    files: list[UploadFile] = File(...),
    use_llm_assist: bool = Form(False),
    overwrite: bool = Form(False),
):
    """Import source files directly into the file-backed question bank."""
    imported: list[FileQuestionImportItem] = []
    errors: list[FileQuestionImportError] = []
    warnings: list[str] = []
    pending_review: list[FileQuestionCandidateRead] = []
    llm_used = False

    batch_dir = settings.upload_dir / "file-imports" / (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8])
    batch_dir.mkdir(parents=True, exist_ok=True)
    has_structured_json = any(Path(upload.filename or "").suffix.lower() == ".json" for upload in files)
    stored_uploads: list[tuple[str, str, Path]] = []

    for upload in files:
        filename = upload.filename or "(unknown)"
        if not upload.filename:
            errors.append(FileQuestionImportError(filename=filename, error="Missing filename"))
            continue
        source_type = source_type_from_filename(upload.filename)
        if not source_type:
            errors.append(
                FileQuestionImportError(
                    filename=filename,
                    error=f"Unsupported file type. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
                )
            )
            continue

        content = await upload.read()
        size_mb = len(content) / (1024 * 1024)
        if size_mb > settings.MAX_UPLOAD_SIZE_MB:
            errors.append(
                FileQuestionImportError(
                    filename=filename,
                    error=f"File too large ({size_mb:.1f} MB). Maximum: {settings.MAX_UPLOAD_SIZE_MB} MB",
                )
            )
            continue

        safe_filename = Path(upload.filename).name
        if has_structured_json and source_type in STRUCTURED_JSON_ASSET_SOURCE_TYPES:
            assets_dir = batch_dir / "assets"
            assets_dir.mkdir(exist_ok=True)
            stored_path = assets_dir / safe_filename
            if stored_path.exists():
                errors.append(FileQuestionImportError(filename=filename, error="Duplicate asset filename in structured import batch"))
                continue
        elif source_type == "json":
            stored_path = batch_dir / safe_filename
        else:
            stored_path = batch_dir / f"{uuid4().hex[:8]}_{safe_filename}"
        stored_path.write_bytes(content)
        stored_uploads.append((filename, source_type, stored_path))

    for filename, source_type, stored_path in stored_uploads:
        if has_structured_json and source_type in STRUCTURED_JSON_ASSET_SOURCE_TYPES:
            continue
        try:
            result = await import_source_file(
                source_path=stored_path,
                original_filename=filename,
                use_llm_assist=use_llm_assist,
                overwrite=overwrite,
                rebuild_after=False,
            )
            llm_used = llm_used or result.llm_used
            imported.extend(
                _import_item(filename, read_question(question.question_id))
                for question in result.questions
            )
            pending_review.extend(_candidate_read(item) for item in result.candidates)
            warnings.extend(f"{filename}: {warning}" for warning in result.warnings)
        except LLMNotConfiguredError as exc:
            errors.append(FileQuestionImportError(filename=filename, error=str(exc)))
        except Exception as exc:
            errors.append(FileQuestionImportError(filename=filename, error=str(exc)))

    if imported:
        rebuild_index()

    return FileQuestionImportResponse(
        imported=imported,
        pending_review=pending_review,
        errors=errors,
        warnings=warnings,
        llm_assist_requested=use_llm_assist,
        llm_assist_used=llm_used,
        question_count=len(imported),
        review_count=len(pending_review),
    )


@router.post("/import/jobs", response_model=FileImportJobRead, status_code=202)
async def create_file_import_job(
    files: list[UploadFile] = File(...),
    use_llm_assist: bool = Form(False),
    overwrite: bool = Form(False),
):
    """Create a background import job for large single-user batches."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    manifest = create_job(use_llm_assist=use_llm_assist, overwrite=overwrite)
    has_structured_json = any(Path(upload.filename or "").suffix.lower() == ".json" for upload in files)

    for upload in files:
        filename = upload.filename or "(unknown)"
        if not upload.filename:
            manifest = append_job_error(manifest, filename=filename, error="Missing filename")
            continue
        try:
            source_type = source_type_or_error(upload.filename)
        except ValueError as exc:
            manifest = append_job_error(manifest, filename=filename, error=str(exc))
            continue

        content = await upload.read()
        size_mb = len(content) / (1024 * 1024)
        if size_mb > settings.MAX_UPLOAD_SIZE_MB:
            manifest = append_job_error(
                manifest,
                filename=filename,
                error=f"File too large ({size_mb:.1f} MB). Maximum: {settings.MAX_UPLOAD_SIZE_MB} MB",
            )
            continue

        manifest = add_source_file(
            manifest,
            original_filename=filename,
            payload=content,
            source_type=source_type,
            structured_json_batch=has_structured_json,
        )

    manifest = mark_job_queued(manifest)
    if manifest.get("status") == "queued":
        kick_worker()
    return _job_read(manifest)


@router.get("/import/jobs", response_model=list[FileImportJobRead])
async def list_file_import_jobs(limit: int = Query(20, ge=1, le=200)):
    """List recent background file import jobs."""
    return [_job_read(item) for item in list_import_jobs(limit=limit)]


@router.get("/import/jobs/{job_id}", response_model=FileImportJobRead)
async def get_file_import_job(job_id: str):
    """Read one background file import job manifest."""
    try:
        validate_job_id(job_id)
        return _job_read(read_job(job_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Import job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/import/candidates", response_model=list[FileQuestionCandidateRead])
async def get_file_question_candidates(
    state: str | None = Query("needs_review"),
    limit: int = Query(100, ge=1, le=1000),
):
    """List file-question import candidates waiting for explicit review."""
    try:
        return [_candidate_read(item) for item in list_candidates(state=state, limit=limit)]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/import/candidates/{candidate_id}",
    response_model=FileQuestionCandidateRead,
)
async def get_file_question_candidate(candidate_id: str):
    try:
        validate_candidate_id(candidate_id)
        return _candidate_read(read_candidate(candidate_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Import candidate not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/import/candidates/{candidate_id}/assets/{asset_name}")
async def get_file_question_candidate_asset(candidate_id: str, asset_name: str):
    try:
        return FileResponse(candidate_asset_path(candidate_id, asset_name))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Candidate asset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/import/candidates/{candidate_id}/approve",
    response_model=FileQuestionCandidateCommitResponse,
)
async def approve_file_question_candidate(
    candidate_id: str,
    payload: FileQuestionCandidateApprove,
):
    try:
        candidate, question = approve_candidate(
            candidate_id,
            question_body=payload.question_body,
            answer_body=payload.answer_body,
            metadata=payload.metadata,
            acknowledge_warnings=payload.acknowledge_warnings,
        )
        rebuild_index()
        record_candidate_resolution(
            candidate_id,
            question_id=question.question_id,
        )
        return FileQuestionCandidateCommitResponse(
            candidate=_candidate_read(candidate),
            question=_detail(read_question(question.question_id)),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Import candidate not found") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/import/candidates/{candidate_id}/reject",
    response_model=FileQuestionCandidateRead,
)
async def reject_file_question_candidate(
    candidate_id: str,
    payload: FileQuestionCandidateReject,
):
    try:
        candidate = reject_candidate(candidate_id, payload.reason)
        record_candidate_resolution(candidate_id, rejected=True)
        return _candidate_read(candidate)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Import candidate not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reindex", response_model=ReindexFileQuestionsResponse)
async def reindex_file_questions():
    """Rebuild the local vector index directly from question files."""
    index = rebuild_index()
    return ReindexFileQuestionsResponse(
        status="ok",
        model=index.get("model", LOCAL_VECTOR_MODEL),
        question_count=len(index.get("items", [])),
        index_path=str(INDEX_PATH),
        created_at=index.get("created_at", datetime.now(timezone.utc).isoformat()),
    )


@router.get("/{question_id}", response_model=FileQuestionRead)
async def get_file_question(question_id: str):
    """Read one file-backed question."""
    try:
        return _detail(read_question(question_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Question file not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{question_id}", response_model=FileQuestionRead)
async def update_file_question(question_id: str, data: FileQuestionUpdate):
    """Update a file-backed question's body or answer."""
    try:
        qid = validate_question_id(question_id)
        question = read_question(qid)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Question file not found") from exc

    if data.question_body is not None:
        question.question_body = data.question_body
    if data.answer_body is not None:
        question.answer_body = data.answer_body

    existing_assets: list[tuple[str, bytes]] = []
    for asset in question.assets:
        try:
            existing_assets.append((asset.filename, asset_path(qid, asset.filename).read_bytes()))
        except FileNotFoundError:
            continue

    updated = write_question(
        question_id=qid,
        question_body=question.question_body,
        answer_body=question.answer_body,
        question_format=question.question_format,
        answer_format=question.answer_format,
        metadata=question.metadata,
        assets=existing_assets,
        overwrite=True,
    )
    rebuild_index()
    return _detail(read_question(updated.question_id))


@router.get("/{question_id}/assets/{asset_name}")
async def get_file_question_asset(question_id: str, asset_name: str):
    """Serve an asset stored next to a question."""
    try:
        path = asset_path(question_id, asset_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Asset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path)


def _paper_template(title: str, body: str) -> str:
    return rf"""\documentclass[12pt]{{ctexart}}
\usepackage[a4paper,margin=2.2cm]{{geometry}}
\usepackage{{amsmath,amssymb}}
\usepackage{{graphicx}}
\usepackage{{enumitem}}
\usepackage{{float}}
\graphicspath{{{{assets/}}}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0.8em}}
\title{{{_escape_text_preserving_math(title)}}}
\date{{}}
\begin{{document}}
\maketitle
{body}
\end{{document}}
"""


_TEX_SPECIALS = str.maketrans({
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
})


def _escape_text_preserving_math(text: str) -> str:
    """Escape plain text while preserving common LaTeX math delimiters.

    Normalises Markdown ``\\(...\\)`` → ``$...$`` and ``\\[...\\]`` → ``$$...$$``.
    """
    # Normalise Markdown math delimiters first
    text = re.sub(r"(?<!\\)\\\((.+?)(?<!\\)\\\)", r"$\1$", text)
    text = re.sub(r"(?<!\\)\\\[(.+?)(?<!\\)\\\]", r"$$\1$$", text, flags=re.DOTALL)

    pieces = re.split(
        r"(\$\$.*?\$\$|\$.*?\$)",
        text,
        flags=re.DOTALL,
    )
    out: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if (piece.startswith("$") and piece.endswith("$")) or (piece.startswith("$$") and piece.endswith("$$")):
            out.append(piece)
        else:
            out.append(piece.translate(_TEX_SPECIALS))
    return "".join(out)


def _looks_like_rendered_pdf_page(filename: str) -> bool:
    stem = Path(filename).stem.lower()
    suffix = Path(filename).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".webp"} and bool(
        re.fullmatch(r"(?:page|p)[_-]?\d{1,4}", stem)
    )


_QUESTION_IMAGE_OPTIONS = r"width=0.65\linewidth,height=0.26\textheight,keepaspectratio"


def _markdown_image_to_tex(alt: str, raw_path: str, question_id: str) -> str:
    filename = Path(raw_path).name
    if _looks_like_rendered_pdf_page(filename):
        label = alt.strip() if alt else filename
        return rf"\textit{{[{_escape_text_preserving_math(label)} 需人工裁剪为独立题图]}}"
    caption = rf"\par\small{{{_escape_text_preserving_math(alt)}}}" if alt else ""
    return rf"\begin{{center}}\includegraphics[{_QUESTION_IMAGE_OPTIONS}]{{{question_id}/{filename}}}{caption}\end{{center}}"


def _body_to_tex(body: str, body_format: str | None, question_id: str) -> str:
    """Convert markdown/text bodies to a small TeX subset; pass LaTeX through."""
    if (body_format or "markdown") == "latex":
        return _rewrite_latex_asset_paths(body, question_id)

    # Normalise Markdown-flavoured math delimiters to LaTeX equivalents.
    # XeLaTeX / ctexart does NOT recognise \(...\) — only $...$ and \[...\].
    body = re.sub(r"(?<!\\)\\\((.+?)(?<!\\)\\\)", r"$\1$", body)
    body = re.sub(r"(?<!\\)\\\[(.+?)(?<!\\)\\\]", r"$$\1$$", body, flags=re.DOTALL)

    lines: list[str] = []
    in_math_block = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "$$":
            lines.append(stripped)
            in_math_block = not in_math_block
            continue
        if stripped == r"\[":
            lines.append(stripped)
            in_math_block = True
            continue
        if stripped == r"\]":
            lines.append(stripped)
            in_math_block = False
            continue
        if in_math_block:
            lines.append(line)
            continue
        image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            lines.append(_markdown_image_to_tex(image_match.group(1) or "", image_match.group(2) or "", question_id))
            continue
        elif r"\includegraphics" in stripped:
            lines.append(_rewrite_latex_asset_paths(stripped, question_id))
            continue
        if stripped.startswith("### "):
            lines.append(r"\paragraph{" + _escape_text_preserving_math(stripped[4:]) + "}")
        elif stripped.startswith("## "):
            lines.append(r"\subsubsection*{" + _escape_text_preserving_math(stripped[3:]) + "}")
        elif stripped.startswith("# "):
            lines.append(r"\subsubsection*{" + _escape_text_preserving_math(stripped[2:]) + "}")
        elif stripped.startswith("- "):
            lines.append(r"\quad $\bullet$ " + _escape_text_preserving_math(stripped[2:]) + r"\\")
        else:
            lines.append(_escape_text_preserving_math(line))
    return "\n".join(lines)


def _rewrite_latex_asset_paths(body: str, question_id: str) -> str:
    r"""Point relative \includegraphics paths at the copied per-question asset dir."""
    def repl(match: re.Match) -> str:
        options = match.group(1) or f"[{_QUESTION_IMAGE_OPTIONS}]"
        raw_path = match.group(2) or ""
        if re.match(r"^(https?:|/)", raw_path):
            return match.group(0)
        filename = Path(raw_path).name
        if _looks_like_rendered_pdf_page(filename):
            return r"\textit{[题图需人工裁剪为独立图片资产]}"
        return rf"\includegraphics{options}{{{question_id}/{filename}}}"

    return re.sub(r"\\includegraphics(\[[^\]]*\])?\{([^}]+)\}", repl, body)


def _referenced_export_assets(question: FileQuestion) -> set[str]:
    raw_paths = set(
        re.findall(
            r"!\[[^\]]*\]\(([^)]+)\)|\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}",
            f"{question.question_body}\n{question.answer_body}",
        )
    )
    names: set[str] = set()
    for markdown_path, latex_path in raw_paths:
        raw_path = (markdown_path or latex_path).strip()
        if not raw_path:
            continue
        if re.match(r"^[a-z]+://", raw_path, re.IGNORECASE) or Path(raw_path).is_absolute():
            raise HTTPException(
                status_code=422,
                detail=f"Question {question.question_id} references a non-local image: {raw_path}",
            )
        relative = Path(raw_path)
        if ".." in relative.parts:
            raise HTTPException(
                status_code=422,
                detail=f"Question {question.question_id} contains an unsafe image path: {raw_path}",
            )
        filename = relative.name
        if _looks_like_rendered_pdf_page(filename):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Question {question.question_id} references a rendered whole PDF page: "
                    f"{filename}"
                ),
            )
        names.add(filename)

    available = {asset.filename for asset in question.assets}
    missing = sorted(names - available)
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Question {question.question_id} is missing referenced assets: "
                + ", ".join(missing)
            ),
        )
    return names


def _resolve_export_questions(payload: FilePaperRequest) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    for raw_id in payload.question_ids:
        qid = validate_question_id(raw_id)
        if qid not in seen:
            selected.append(qid)
            seen.add(qid)

    target_count = payload.question_count or len(selected)
    if payload.search_query and (not selected or len(selected) < target_count):
        for question in search_questions(payload.search_query, limit=max(target_count, 20)):
            if question.question_id not in seen:
                selected.append(question.question_id)
                seen.add(question.question_id)
            if len(selected) >= target_count:
                break

    if payload.question_count:
        selected = selected[:payload.question_count]
    if not selected:
        raise HTTPException(status_code=400, detail="Provide question_ids or search_query with question_count.")
    return selected


def _original_problem_number(question: FileQuestion) -> str | None:
    """Prefer a source problem number when a file-backed question preserves one."""
    original_number = question.metadata.get("original_problem_number")
    if isinstance(original_number, (str, int)) and str(original_number).strip():
        return str(original_number).strip()
    return None


def _paper_question_heading(question: FileQuestion, fallback_index: int, duplicate_original_number: bool = False) -> str:
    """Build a paper heading that stays unambiguous for mixed-source papers."""
    original_number = _original_problem_number(question)
    if original_number:
        if duplicate_original_number:
            source = question.metadata.get("paper_set") or question.metadata.get("source_filename")
            source_label = f"{source}原第 {original_number} 题" if source else f"原第 {original_number} 题"
            return f"第 {fallback_index} 题（{source_label}）"
        return f"第 {original_number} 题"
    return f"第 {fallback_index} 题"


@router.post("/papers/export", response_model=FilePaperResponse)
async def export_file_paper(payload: FilePaperRequest):
    """Create separate question-paper and answer-paper TeX/PDF files.

    Produces:
    * ``questions.tex`` / ``questions.pdf`` — question-only paper
    * ``answers.tex`` / ``answers.pdf`` — answer key
    * ``build-questions.log`` / ``build-answers.log`` — per-file build logs
    """
    load_or_rebuild_index()
    resolved_question_ids = _resolve_export_questions(payload)
    resolved_questions: list[tuple[str, FileQuestion, set[str]]] = []
    original_number_counts: dict[str, int] = {}

    for question_id in resolved_question_ids:
        try:
            qid = validate_question_id(question_id)
            question = read_question(qid)
            referenced_assets = _referenced_export_assets(question)
            for filename in referenced_assets:
                asset_path(qid, filename)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Question or referenced asset not found: {question_id}",
            ) from exc
        resolved_questions.append((qid, question, referenced_assets))
        original_number = _original_problem_number(question)
        if original_number:
            original_number_counts[original_number] = (
                original_number_counts.get(original_number, 0) + 1
            )

    export_id = (
        datetime.now(timezone.utc).strftime("filepaper_%Y%m%d_%H%M%S_")
        + uuid4().hex[:8]
    )
    exports_root = settings.exports_dir / "file-papers"
    staging_root = exports_root / ".staging"
    exports_root.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(exist_ok=True)
    out_dir = exports_root / export_id
    work_dir = staging_root / f"{export_id}.{uuid4().hex}.tmp"
    assets_out = work_dir / "assets"
    work_dir.mkdir()
    assets_out.mkdir()

    try:
        question_parts: list[str] = [r"\section*{题目}"]
        answer_parts: list[str] = [r"\section*{答案}"]
        manifest_questions: list[dict] = []

        for index, (qid, question, referenced_assets) in enumerate(
            resolved_questions,
            start=1,
        ):
            asset_manifest: list[dict] = []
            if referenced_assets:
                question_assets_out = assets_out / qid
                question_assets_out.mkdir()
                for filename in sorted(referenced_assets):
                    src = asset_path(qid, filename)
                    destination = question_assets_out / filename
                    shutil.copy2(src, destination)
                    asset_manifest.append(
                        {
                            "filename": filename,
                            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                            "size_bytes": destination.stat().st_size,
                        }
                    )

            original_number = _original_problem_number(question)
            heading = _paper_question_heading(
                question,
                index,
                duplicate_original_number=bool(
                    original_number
                    and original_number_counts.get(original_number, 0) > 1
                ),
            )
            marker = rf"\typeout{{PHYSBANK_QUESTION_ID={qid}}}"
            question_parts.extend(
                [
                    marker,
                    r"\subsection*{" + _escape_text_preserving_math(heading) + "}",
                    _body_to_tex(question.question_body, question.question_format, qid),
                ]
            )
            answer_parts.extend(
                [
                    marker,
                    r"\subsection*{" + _escape_text_preserving_math(heading) + "}",
                    (
                        _body_to_tex(
                            question.answer_body,
                            question.answer_format,
                            qid,
                        )
                        if question.answer_body
                        else r"\textit{未提供答案。}"
                    ),
                ]
            )
            manifest_questions.append(
                {
                    "order": index,
                    "question_id": qid,
                    "content_hash": question.content_hash,
                    "source_filename": question.metadata.get("source_filename"),
                    "source_document_hash": question.metadata.get(
                        "source_document_hash"
                    ),
                    "assets": asset_manifest,
                }
            )

        questions_tex_path = work_dir / "questions.tex"
        questions_tex_path.write_text(
            _paper_template(payload.title, "\n\n".join(question_parts)),
            encoding="utf-8",
        )
        answers_tex_path = work_dir / "answers.tex"
        answers_tex_path.write_text(
            _paper_template(payload.title + " - 参考答案", "\n\n".join(answer_parts)),
            encoding="utf-8",
        )

        engine = settings.LATEX_ENGINE or "xelatex"

        def _compile(tex_path: Path, log_name: str) -> tuple[bool, str | None]:
            log_path = work_dir / log_name
            try:
                with _TEX_COMPILE_GATE:
                    proc = subprocess.run(
                        [
                            engine,
                            "-interaction=nonstopmode",
                            "-halt-on-error",
                            tex_path.name,
                        ],
                        cwd=work_dir,
                        capture_output=True,
                        text=True,
                        timeout=max(
                            1,
                            int(settings.LATEX_COMPILE_TIMEOUT_SECONDS or 90),
                        ),
                        check=False,
                    )
                build_log = proc.stdout + "\n" + proc.stderr
                log_path.write_text(build_log, encoding="utf-8")
                markers = re.findall(
                    r"PHYSBANK_QUESTION_ID=([A-Za-z0-9_.-]+)",
                    build_log,
                )
                pdf_candidate = work_dir / tex_path.with_suffix(".pdf").name
                success = proc.returncode == 0 and pdf_candidate.exists()
                return success, None if success or not markers else markers[-1]
            except Exception as exc:
                log_path.write_text(str(exc), encoding="utf-8")
                return False, None

        async def _compile_async(
            tex_path: Path,
            log_name: str,
        ) -> tuple[bool, str | None]:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                _TEX_COMPILE_EXECUTOR,
                _compile,
                tex_path,
                log_name,
            )

        question_build, answer_build = await asyncio.gather(
            _compile_async(questions_tex_path, "build-questions.log"),
            _compile_async(answers_tex_path, "build-answers.log"),
        )
        question_succeeded, question_error_id = question_build
        answer_succeeded, answer_error_id = answer_build
        both_succeeded = question_succeeded and answer_succeeded

        manifest = {
            "version": 1,
            "template_version": "file-paper-v2",
            "export_id": export_id,
            "title": payload.title,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "question_count": len(resolved_questions),
            "questions": manifest_questions,
            "artifacts": {
                "questions_tex": "questions.tex",
                "questions_pdf": "questions.pdf" if question_succeeded else None,
                "answers_tex": "answers.tex",
                "answers_pdf": "answers.pdf" if answer_succeeded else None,
                "question_build_log": "build-questions.log",
                "answer_build_log": "build-answers.log",
            },
            "compile": {
                "engine": engine,
                "questions_succeeded": question_succeeded,
                "answers_succeeded": answer_succeeded,
                "question_error_id": question_error_id,
                "answer_error_id": answer_error_id,
            },
        }
        (work_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        work_dir.replace(out_dir)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    questions_pdf_path = out_dir / "questions.pdf" if question_succeeded else None
    answers_pdf_path = out_dir / "answers.pdf" if answer_succeeded else None
    question_tex_path = out_dir / "questions.tex"

    return FilePaperResponse(
        status="succeeded" if both_succeeded else "tex_only",
        export_id=export_id,
        title=payload.title,
        question_count=len(resolved_question_ids),
        question_ids=resolved_question_ids,
        question_tex_url=f"/api/file-questions/papers/exports/{export_id}/questions.tex",
        question_pdf_url=(
            f"/api/file-questions/papers/exports/{export_id}/questions.pdf"
            if questions_pdf_path
            else None
        ),
        question_build_log_url=(
            f"/api/file-questions/papers/exports/{export_id}/build-questions.log"
        ),
        answer_tex_url=f"/api/file-questions/papers/exports/{export_id}/answers.tex",
        answer_pdf_url=(
            f"/api/file-questions/papers/exports/{export_id}/answers.pdf"
            if answers_pdf_path
            else None
        ),
        answer_build_log_url=(
            f"/api/file-questions/papers/exports/{export_id}/build-answers.log"
        ),
        manifest_url=f"/api/file-questions/papers/exports/{export_id}/manifest.json",
        question_compile_error_id=question_error_id,
        answer_compile_error_id=answer_error_id,
        tex_path=str(question_tex_path),
        tex_url=f"/api/file-questions/papers/exports/{export_id}/questions.tex",
        pdf_path=str(questions_pdf_path) if questions_pdf_path else None,
        pdf_url=(
            f"/api/file-questions/papers/exports/{export_id}/questions.pdf"
            if questions_pdf_path
            else None
        ),
        build_log_path=str(out_dir / "build-questions.log"),
        build_log_url=(
            f"/api/file-questions/papers/exports/{export_id}/build-questions.log"
        ),
    )


@router.get("/papers/exports/{export_id}/{filename}")
async def get_file_paper_export(export_id: str, filename: str):
    """Download a generated file-question paper artifact.

    Supports question/answer TeX, PDFs, build logs, and ``manifest.json``.
    """
    if not re.fullmatch(r"filepaper_[A-Za-z0-9_]+", export_id):
        raise HTTPException(status_code=400, detail="Invalid export id")
    if filename not in {
        "questions.tex", "questions.pdf", "build-questions.log",
        "answers.tex", "answers.pdf", "build-answers.log",
        "manifest.json",
        "paper.tex", "paper.pdf", "build.log",  # legacy compat
    }:
        raise HTTPException(status_code=400, detail="Invalid export filename")
    path = settings.exports_dir / "file-papers" / export_id / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Export artifact not found")
    if filename.endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.endswith(".json"):
        media_type = "application/json"
    else:
        media_type = "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media_type, filename=filename)
