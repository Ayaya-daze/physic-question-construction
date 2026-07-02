"""Upload API — file upload, document management, extraction jobs, and candidate handling."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.extraction import ExtractionJob, MediaAsset, SourceDocument
from app.models.knowledge_point import KnowledgePoint
from app.models.knowledge_point_candidate import (
    KnowledgePointCandidate,
    QuestionKnowledgeCandidate,
)
from app.models.question import Question
from app.schemas.question import QuestionCreate
from app.schemas.upload import (
    CandidateBatchApprove,
    CandidateQuestion,
    ExtractionJobDetail,
    ExtractionJobRead,
    MediaAssetRead,
    MultiUploadResponse,
    SourceDocumentDetail,
    UploadError,
    UploadResponse,
)

router = APIRouter()


# ──────────────────────────────────────────────
# Job endpoints
# ──────────────────────────────────────────────

@router.get("/jobs/{job_id}", response_model=ExtractionJobDetail)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get extraction job status and details."""
    result = await db.execute(
        select(ExtractionJob).where(ExtractionJob.job_id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Read candidates from output_snapshot for candidate_count
    candidate_count = 0
    if job.output_snapshot and "candidates" in job.output_snapshot:
        candidate_count = len(job.output_snapshot["candidates"])

    return ExtractionJobDetail(
        job_id=job.job_id,
        job_type=job.job_type,
        status=job.status,
        tool_name=job.tool_name,
        model_name=job.model_name,
        error_message=job.error_message,
        candidate_count=candidate_count,
        created_at=job.created_at,
        finished_at=job.finished_at,
        input_snapshot=job.input_snapshot,
        output_snapshot=job.output_snapshot,
    )


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateQuestion])
async def get_job_candidates(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get structured question candidates from a completed extraction job."""
    result = await db.execute(
        select(ExtractionJob).where(ExtractionJob.job_id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.output_snapshot and "candidates" in job.output_snapshot:
        candidates = job.output_snapshot["candidates"]
        # Patch any candidate missing the required `index` field (legacy data)
        for i, c in enumerate(candidates):
            if "index" not in c:
                c["index"] = i
        return candidates

    return []


# ── Shared helper: create a Question from a candidate dict ─────────────

async def _create_question_from_candidate(
    candidate: dict,
    job: ExtractionJob,
    db: AsyncSession,
) -> dict:
    """Create a Question (with options/answers/solution/kp-bindings + candidate KPs)
    from a single candidate dict.  Returns ``{id, canonical_id, status}``.
    """
    from app.models.question import (
        Answer,
        ChoiceOption,
        Question,
        QuestionKnowledgePoint,
        SolutionStep,
        question_tags,
    )
    from app.models.knowledge_point import KnowledgePoint, Tag
    from app.models.knowledge_point_candidate import (
        KnowledgePointCandidate as KPCandidate,
        QuestionKnowledgeCandidate,
    )

    question_data = candidate.get("question", {})
    qc = QuestionCreate(**question_data)

    q_uuid = uuid.uuid4().hex[:8]
    canonical_id = f"q_{q_uuid}"

    question = Question(
        canonical_id=canonical_id,
        status="pending_review",
        question_type=qc.question_type,
        stem=qc.stem,
        difficulty=qc.difficulty,
        grade=qc.grade,
        semester=qc.semester,
        textbook_version=qc.textbook_version,
        chapter=qc.chapter,
        score=qc.score,
        estimated_time_seconds=qc.estimated_time_seconds,
        source_document_id=(
            job.source_document.document_id if job.source_document else None
        ),
        source_page=candidate.get("source_page"),
        source_region=candidate.get("source_region"),
    )
    db.add(question)
    await db.flush()

    # Options
    for opt in (qc.options or []):
        db.add(ChoiceOption(
            question_id=question.id,
            option_label=opt.option_label,
            content=opt.content,
            is_correct=opt.is_correct,
            order_index=opt.order_index,
        ))

    # Answers
    for ans in (qc.answers or []):
        db.add(Answer(
            question_id=question.id,
            answer_type=ans.answer_type,
            content=ans.content,
            normalized_content=ans.normalized_content,
            unit=ans.unit,
            significant_figures=ans.significant_figures,
        ))

    # Solution steps
    for step in (qc.solution_steps or []):
        db.add(SolutionStep(
            question_id=question.id,
            step_order=step.step_order,
            content=step.content,
            formula=step.formula,
            explanation=step.explanation,
        ))

    # Knowledge points — bind existing, create candidates for unknown
    kpc_ids: list[str] = []
    metadata_updates: dict = {}

    for kp_ref in (qc.knowledge_points or []):
        kp_result = await db.execute(
            select(KnowledgePoint).where(KnowledgePoint.path == kp_ref.path)
        )
        kp = kp_result.scalar_one_or_none()
        if kp:
            db.add(QuestionKnowledgePoint(
                question_id=question.id,
                knowledge_point_id=kp.id,
                weight=kp_ref.weight,
                is_primary=kp_ref.is_primary,
                source="llm" if settings.LLM_ENABLED else "human",
            ))
        else:
            kpc_id_str = f"kpc_{uuid.uuid4().hex[:8]}"
            conf = getattr(kp_ref, "confidence", 0.5) or 0.5
            kpc = KPCandidate(
                candidate_id=kpc_id_str,
                canonical_name=kp_ref.path.rsplit("/", 1)[-1],
                suggested_parent_path=(
                    "/".join(kp_ref.path.rsplit("/", 1)[:-1]) or None
                ),
                confidence=conf,
                status="pending",
                source="llm" if settings.LLM_ENABLED else "import",
                source_question_id=question.id,
                source_document_id=job.source_document_id,
            )
            db.add(kpc)
            await db.flush()
            db.add(QuestionKnowledgeCandidate(
                question_id=question.id,
                knowledge_point_candidate_id=kpc.id,
                weight=kp_ref.weight,
                is_primary=kp_ref.is_primary,
            ))
            kpc_ids.append(kpc_id_str)

    # Process LLM-suggested concept definitions (candidate-level "concepts" field)
    for concept in candidate.get("concepts") or []:
        concept_name = concept.get("name", "").strip()
        if not concept_name:
            continue
        concept_parent = concept.get("suggested_parent_path") or None
        kpc_result = await db.execute(
            select(KPCandidate).where(
                KPCandidate.canonical_name == concept_name,
                KPCandidate.source_question_id == question.id,
            )
        )
        if kpc_result.scalar_one_or_none() is not None:
            continue  # already created above or in a previous approval
        kpc_id_str = f"kpc_{uuid.uuid4().hex[:8]}"
        kpc2 = KPCandidate(
            candidate_id=kpc_id_str,
            canonical_name=concept_name,
            suggested_parent_path=concept_parent,
            definition=concept.get("definition"),
            confidence=concept.get("confidence", 0.5) or 0.5,
            status="pending",
            source="llm" if settings.LLM_ENABLED else "import",
            source_question_id=question.id,
            source_document_id=job.source_document_id,
        )
        db.add(kpc2)
        await db.flush()
        db.add(QuestionKnowledgeCandidate(
            question_id=question.id,
            knowledge_point_candidate_id=kpc2.id,
            weight=0.5,
            is_primary=False,
        ))
        kpc_ids.append(kpc_id_str)

    # Preserve candidate metadata for audit trail
    if kpc_ids:
        metadata_updates["knowledge_point_candidate_ids"] = kpc_ids
    if candidate.get("confidence") is not None:
        metadata_updates["llm_confidence"] = candidate["confidence"]
    if candidate.get("warnings"):
        metadata_updates["llm_warnings"] = candidate["warnings"]
    if candidate.get("needs_review"):
        metadata_updates["llm_needs_review"] = candidate["needs_review"]
    if metadata_updates:
        question.metadata_json = {**(question.metadata_json or {}), **metadata_updates}

    # Tags — use association table directly (lazy-load on async SQLite breaks without greenlet)
    for tag_name in (qc.tags or []):
        tag_result = await db.execute(select(Tag).where(Tag.name == tag_name))
        tag = tag_result.scalar_one_or_none()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
            await db.flush()
        await db.execute(
            question_tags.insert().values(question_id=question.id, tag_id=tag.id)
        )

    await db.commit()
    await db.refresh(question)
    return {"id": question.id, "canonical_id": question.canonical_id, "status": question.status}


@router.post("/jobs/{job_id}/candidates/{index}/approve")
async def approve_candidate(
    job_id: str,
    index: int,
    db: AsyncSession = Depends(get_db),
):
    """Approve a candidate question — creates a Question with pending_review status."""
    result = await db.execute(
        select(ExtractionJob)
        .options(selectinload(ExtractionJob.source_document))
        .where(ExtractionJob.job_id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    candidates = (job.output_snapshot or {}).get("candidates", [])
    if index < 0 or index >= len(candidates):
        raise HTTPException(status_code=404, detail="Candidate index out of range")

    return await _create_question_from_candidate(candidates[index], job, db)


@router.delete("/jobs/{job_id}/candidates/{index}")
async def reject_candidate(
    job_id: str,
    index: int,
    db: AsyncSession = Depends(get_db),
):
    """Reject a candidate question — removes it from the candidate list."""
    result = await db.execute(
        select(ExtractionJob).where(ExtractionJob.job_id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    candidates = (job.output_snapshot or {}).get("candidates", [])
    if index < 0 or index >= len(candidates):
        raise HTTPException(status_code=404, detail="Candidate index out of range")

    rejected = candidates.pop(index)
    job.output_snapshot = {**(job.output_snapshot or {}), "candidates": candidates}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(job, "output_snapshot")
    await db.commit()

    return {"detail": "Candidate rejected", "removed_index": index}


@router.post("/jobs/{job_id}/candidates/batch-approve")
async def batch_approve_candidates(
    job_id: str,
    batch: CandidateBatchApprove,
    db: AsyncSession = Depends(get_db),
):
    """Batch approve multiple candidates — delegates to the shared helper."""
    results = []
    errors = []

    for index in batch.indices:
        try:
            result = await db.execute(
                select(ExtractionJob)
                .options(selectinload(ExtractionJob.source_document))
                .where(ExtractionJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                errors.append({"index": index, "error": "Job not found"})
                continue

            candidates = (job.output_snapshot or {}).get("candidates", [])
            if index < 0 or index >= len(candidates):
                errors.append({"index": index, "error": "Index out of range"})
                continue

            outcome = await _create_question_from_candidate(candidates[index], job, db)
            results.append({"index": index, "canonical_id": outcome["canonical_id"]})

        except Exception as e:
            errors.append({"index": index, "error": str(e)})

    return {"approved": results, "errors": errors}


# ──────────────────────────────────────────────
# Page image serving
# ──────────────────────────────────────────────

@router.get("/documents/{doc_id}/pages/{page}", response_model=dict)
async def get_page_image(doc_id: str, page: int):
    """Get info about a rendered page image. The image itself is served via static files."""
    pages_dir = _pages_dir(doc_id)
    page_path = pages_dir / f"page_{page:03d}.png"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="Page image not found")
    return {
        "document_id": doc_id,
        "page": page,
        "path": str(page_path),
        "exists": True,
    }
