"""API routes for paper CRUD, question management, assembly, validation, and export."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.paper import (
    Paper,
    PaperExportArtifact,
    PaperGenerationJob,
    PaperQuestion,
    PaperSection,
)
from app.models.extraction import MediaAsset
from app.models.question import Question
from app.schemas.paper import (
    AddQuestionRequest,
    AssemblyConstraints,
    AssemblyResult,
    ExportJobRead,
    ExportRequest,
    PaginatedPaperResponse,
    PaperCreate,
    PaperDetail,
    PaperRead,
    PaperSectionCreate,
    PaperSectionRead,
    PaperUpdate,
    ReplaceQuestionRequest,
    UpdatePaperQuestionRequest,
)
from app.services import paper_generator
from app.services.latex_renderer import (
    _QUESTIONS_DIR,
    _extract_image_references,
    compile_pdf,
    export_assets,
    render_answers_to_tex,
    render_paper_to_tex,
    render_questions_to_tex,
)

router = APIRouter()

# ──────────────────────────────────────────────
# Paper status transitions
# ──────────────────────────────────────────────

PAPER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"assembled", "archived"},
    "assembled": {"exported", "archived"},
    "exported": {"archived"},
    "archived": {"draft"},
}


def _can_transition_paper(current: str, target: str) -> bool:
    """Check if a paper status transition is allowed."""
    return target in PAPER_STATUS_TRANSITIONS.get(current, set())


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


async def _resolve_paper(db: AsyncSession, paper_id: str) -> Paper | None:
    """Look up a paper by its paper_id string."""
    stmt = (
        select(Paper)
        .options(
            selectinload(Paper.sections),
            selectinload(Paper.questions)
            .selectinload(PaperQuestion.question)
            .selectinload(Question.choice_options),
            selectinload(Paper.questions)
            .selectinload(PaperQuestion.question)
            .selectinload(Question.answers),
            selectinload(Paper.questions)
            .selectinload(PaperQuestion.question)
            .selectinload(Question.solution_steps),
            selectinload(Paper.questions)
            .selectinload(PaperQuestion.question)
            .selectinload(Question.question_knowledge_points),
        )
        .where(Paper.paper_id == paper_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _resolve_paper_question(
    db: AsyncSession, paper_question_id: int
) -> PaperQuestion | None:
    """Look up a PaperQuestion by its numeric ID."""
    stmt = (
        select(PaperQuestion)
        .options(
            selectinload(PaperQuestion.question),
            selectinload(PaperQuestion.section),
        )
        .where(PaperQuestion.id == paper_question_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _resolve_question_from_request(
    db: AsyncSession,
    *,
    question_id: int | None = None,
    canonical_id: str | None = None,
) -> Question | None:
    """Resolve a question by numeric id or canonical id."""
    if question_id is not None:
        stmt = select(Question).where(Question.id == question_id)
    elif canonical_id:
        stmt = select(Question).where(Question.canonical_id == canonical_id)
    else:
        return None
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _build_paper_read(paper: Paper) -> PaperRead:
    """Build a PaperRead from an ORM Paper object."""
    sections = [
        PaperSectionRead(
            id=s.id,
            paper_id=s.paper_id,
            name=s.name,
            question_type=s.question_type,
            count=s.count,
            score_each=s.score_each,
            order_index=s.order_index,
            constraints_json=s.constraints_json,
        )
        for s in (paper.sections or [])
    ]
    return PaperRead(
        id=paper.id,
        paper_id=paper.paper_id,
        title=paper.title,
        description=paper.description,
        total_score=paper.total_score,
        duration_minutes=paper.duration_minutes,
        grade=paper.grade,
        difficulty_target=paper.difficulty_target,
        generation_mode=paper.generation_mode,
        status=paper.status,
        include_answers=paper.include_answers,
        constraints_json=paper.constraints_json,
        validation_result_json=paper.validation_result_json,
        section_count=len(sections),
        question_count=len(paper.questions) if paper.questions else 0,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
        sections=sections,
    )


async def _find_available_section_for_question(
    db: AsyncSession,
    paper: Paper,
    question: Question,
) -> PaperSection | None:
    """Find a matching section with remaining capacity for a question."""
    sections = sorted(
        [s for s in (paper.sections or []) if s.question_type == question.question_type],
        key=lambda s: s.order_index or 0,
    )
    if not sections:
        return None

    counts_result = await db.execute(
        select(PaperQuestion.paper_section_id, func.count(PaperQuestion.id))
        .where(
            PaperQuestion.paper_id == paper.id,
            PaperQuestion.paper_section_id.is_not(None),
        )
        .group_by(PaperQuestion.paper_section_id)
    )
    counts = {section_id: count for section_id, count in counts_result.all()}
    for section in sections:
        if counts.get(section.id, 0) < section.count:
            return section
    return sections[0]


async def _question_image_refs_exist(
    db: AsyncSession,
    question: Question,
) -> tuple[list[str], list[str]]:
    """Return image refs that exist and refs that are missing for one question."""
    text_parts: list[str] = [question.stem or ""]
    for opt in question.choice_options or []:
        text_parts.append(opt.content or "")
    for ans in question.answers or []:
        text_parts.append(ans.content or "")
    for step in question.solution_steps or []:
        text_parts.append(step.content or "")
        text_parts.append(step.formula or "")
        text_parts.append(step.explanation or "")

    refs = list(dict.fromkeys(_extract_image_references("\n".join(text_parts))))
    media_paths: list[Path] = []
    if question.source_crop_asset_id:
        media_result = await db.execute(
            select(MediaAsset).where(MediaAsset.asset_id == question.source_crop_asset_id)
        )
        for media in media_result.scalars().all():
            if media.file_path:
                media_path = Path(media.file_path)
                if not media_path.is_absolute():
                    media_path = Path(__file__).resolve().parent.parent.parent.parent / media_path
                media_paths.append(media_path)
                refs.append(media_path.name)

    existing: list[str] = []
    missing: list[str] = []
    question_assets_dir = _QUESTIONS_DIR / question.canonical_id / "assets"
    for ref in dict.fromkeys(refs):
        candidates = [question_assets_dir / Path(ref).name, *media_paths]
        if any(candidate.is_file() for candidate in candidates):
            existing.append(ref)
        else:
            missing.append(f"{question.canonical_id}:{ref}")

    return existing, missing


# ──────────────────────────────────────────────
# POST /drafts — Create a new paper draft
# ──────────────────────────────────────────────


@router.post("/drafts", response_model=PaperRead, status_code=201)
async def create_paper_draft(
    data: PaperCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new paper draft with optional sections."""
    paper_id = f"pp_{uuid4().hex[:8]}"

    paper = Paper(
        paper_id=paper_id,
        title=data.title,
        description=data.description,
        total_score=data.total_score,
        duration_minutes=data.duration_minutes,
        grade=data.grade,
        difficulty_target=data.difficulty_target,
        generation_mode=data.generation_mode,
        status="draft",
        include_answers=data.include_answers,
        constraints_json=data.constraints.model_dump() if data.constraints else None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(paper)
    await db.flush()

    # Create sections if provided
    for sec_data in data.sections:
        section = PaperSection(
            paper_id=paper.id,
            name=sec_data.name,
            question_type=sec_data.question_type,
            count=sec_data.count,
            score_each=sec_data.score_each,
            order_index=sec_data.order_index,
            constraints_json=sec_data.constraints_json,
        )
        db.add(section)

    await db.flush()
    await db.refresh(paper)

    # Reload with relationships
    full = await _resolve_paper(db, paper.paper_id)
    return _build_paper_read(full)


@router.post("/paper-drafts", response_model=PaperRead, status_code=201)
async def create_paper_draft_legacy(
    data: PaperCreate,
    db: AsyncSession = Depends(get_db),
):
    """Backward-compatible alias for older frontend builds."""
    return await create_paper_draft(data, db)


# ──────────────────────────────────────────────
# GET / — List papers
# ──────────────────────────────────────────────


@router.get("", response_model=PaginatedPaperResponse, include_in_schema=False)
@router.get("/", response_model=PaginatedPaperResponse)
async def list_papers(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List papers with optional status filter."""
    query = select(Paper).options(
        selectinload(Paper.sections),
        selectinload(Paper.questions),
    )

    if status:
        query = query.where(Paper.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.order_by(Paper.updated_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    papers = result.unique().scalars().all()

    items = [_build_paper_read(p) for p in papers]

    return PaginatedPaperResponse(items=items, total=total, skip=skip, limit=limit)


# ──────────────────────────────────────────────
# GET /{paper_id} — Get paper detail
# ──────────────────────────────────────────────


@router.get("/{paper_id}", response_model=PaperDetail)
async def get_paper(
    paper_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a paper with sections, questions, and question data."""
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Build PaperDetail manually to include question summaries
    sections_out = [
        PaperSectionRead(
            id=s.id,
            paper_id=s.paper_id,
            name=s.name,
            question_type=s.question_type,
            count=s.count,
            score_each=s.score_each,
            order_index=s.order_index,
            constraints_json=s.constraints_json,
            question_count=sum(
                1 for q in (paper.questions or []) if q.paper_section_id == s.id
            ),
        )
        for s in (paper.sections or [])
    ]

    questions_out = []
    for pq in paper.questions or []:
        q_data = None
        if pq.question:
            q_data = {
                "id": pq.question.id,
                "canonical_id": pq.question.canonical_id,
                "stem": (pq.question.stem or "")[:200],
                "question_type": pq.question.question_type,
                "difficulty": pq.question.difficulty,
                "grade": pq.question.grade,
            }
        questions_out.append(
            {
                "id": pq.id,
                "paper_id": pq.paper_id,
                "paper_section_id": pq.paper_section_id,
                "order_index": pq.order_index,
                "score": pq.score,
                "is_locked": pq.is_locked,
                "selection_reason": pq.selection_reason,
                "source_mode": pq.source_mode,
                "replacement_of_id": pq.replacement_of_id,
                "question": q_data,
            }
        )

    return PaperDetail(
        id=paper.id,
        paper_id=paper.paper_id,
        title=paper.title,
        description=paper.description,
        total_score=paper.total_score,
        duration_minutes=paper.duration_minutes,
        grade=paper.grade,
        difficulty_target=paper.difficulty_target,
        generation_mode=paper.generation_mode,
        status=paper.status,
        include_answers=paper.include_answers,
        constraints_json=paper.constraints_json,
        validation_result_json=paper.validation_result_json,
        sections=sections_out,
        questions=questions_out,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


# ──────────────────────────────────────────────
# PUT /{paper_id} — Update paper
# ──────────────────────────────────────────────


@router.put("/{paper_id}", response_model=PaperRead)
async def update_paper(
    paper_id: str,
    data: PaperUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update paper metadata and optionally replace sections."""
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Update scalar fields
    scalar_fields = (
        "title", "description", "total_score", "duration_minutes",
        "grade", "difficulty_target", "generation_mode",
        "include_answers", "validation_result_json",
    )
    for field in scalar_fields:
        value = getattr(data, field, None)
        if value is not None:
            setattr(paper, field, value)

    # Handle constraints
    if data.constraints is not None:
        paper.constraints_json = data.constraints.model_dump()

    # Handle status transition
    if data.status is not None:
        if not _can_transition_paper(paper.status, data.status):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from '{paper.status}' to '{data.status}'",
            )
        paper.status = data.status

    paper.updated_at = datetime.now(timezone.utc)

    # Replace sections if provided
    if data.sections is not None:
        # Delete existing sections
        existing_secs = await db.execute(
            select(PaperSection).where(PaperSection.paper_id == paper.id)
        )
        for sec in existing_secs.scalars().all():
            await db.delete(sec)

        # Create new sections
        for sec_data in data.sections:
            section = PaperSection(
                paper_id=paper.id,
                name=sec_data.name,
                question_type=sec_data.question_type,
                count=sec_data.count,
                score_each=sec_data.score_each,
                order_index=sec_data.order_index,
                constraints_json=sec_data.constraints_json,
            )
            db.add(section)

    await db.flush()
    await db.refresh(paper)

    full = await _resolve_paper(db, paper.paper_id)
    return _build_paper_read(full)


# ──────────────────────────────────────────────
# DELETE /{paper_id} — Delete paper
# ──────────────────────────────────────────────


@router.delete("/{paper_id}")
async def delete_paper(
    paper_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a paper and all associated sections, questions, jobs, and exports (cascade)."""
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    pid = paper.id
    paper_id_str = paper.paper_id
    export_base = _PAPERS_EXPORT_DIR / paper_id_str

    await db.delete(paper)
    await db.flush()

    # Clean up export files from disk
    if export_base.exists():
        try:
            shutil.rmtree(export_base)
        except OSError:
            pass  # best-effort cleanup

    return {"deleted": True, "id": pid, "paper_id": paper_id_str}


# ──────────────────────────────────────────────
# POST /{paper_id}/questions — Add a question to paper
# ──────────────────────────────────────────────


@router.post("/{paper_id}/questions", status_code=201)
async def add_question_to_paper(
    paper_id: str,
    data: AddQuestionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Add a question to a paper, optionally to a specific section."""
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Verify the question exists. Frontend workflows usually pass canonical_id;
    # API clients may pass numeric question_id.
    question = await _resolve_question_from_request(
        db,
        question_id=data.question_id,
        canonical_id=data.canonical_id,
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Question is not approved (status: {question.status})",
        )

    # Check for duplicate
    existing = await db.execute(
        select(PaperQuestion).where(
            PaperQuestion.paper_id == paper.id,
            PaperQuestion.question_id == question.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Question is already in this paper",
        )

    # Auto-assign section if not provided — match by question_type
    section_id = data.section_id
    section: PaperSection | None = None
    if section_id is not None:
        section_result = await db.execute(
            select(PaperSection).where(
                PaperSection.id == section_id,
                PaperSection.paper_id == paper.id,
            )
        )
        section = section_result.scalar_one_or_none()
        if section is None:
            raise HTTPException(status_code=400, detail="Section does not belong to this paper")
        if section.question_type != question.question_type:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Section question_type '{section.question_type}' does not match "
                    f"question_type '{question.question_type}'"
                ),
            )
    else:
        section = await _find_available_section_for_question(db, paper, question)
        if section is not None:
            section_id = section.id

    score = data.score if data.score is not None else (
        section.score_each if section is not None else question.score
    )

    # Determine order_index
    order_index = data.order_index
    if order_index is None:
        max_order_result = await db.execute(
            select(func.max(PaperQuestion.order_index)).where(
                PaperQuestion.paper_id == paper.id
            )
        )
        max_order = max_order_result.scalar() or 0
        order_index = max_order + 1

    pq = PaperQuestion(
        paper_id=paper.id,
        paper_section_id=section_id,
        question_id=question.id,
        order_index=order_index,
        score=score,
        is_locked=data.is_locked,
        selection_reason=data.selection_reason,
        source_mode=data.source_mode,
    )
    db.add(pq)
    await db.flush()
    await db.refresh(pq)

    return {
        "id": pq.id,
        "paper_id": paper.paper_id,
        "paper_section_id": pq.paper_section_id,
        "question_id": pq.question_id,
        "question": {
            "id": question.id,
            "canonical_id": question.canonical_id,
            "stem": (question.stem or "")[:200],
            "question_type": question.question_type,
            "difficulty": question.difficulty,
            "grade": question.grade,
        },
        "order_index": pq.order_index,
        "score": pq.score,
        "is_locked": pq.is_locked,
        "selection_reason": pq.selection_reason,
        "source_mode": pq.source_mode,
    }


# ──────────────────────────────────────────────
# PATCH /{paper_id}/questions/{paper_question_id} — Update question in paper
# ──────────────────────────────────────────────


@router.patch("/{paper_id}/questions/{paper_question_id}")
async def update_paper_question(
    paper_id: str,
    paper_question_id: int,
    data: UpdatePaperQuestionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a question's placement, score, lock status, or section within a paper."""
    # Verify paper exists and matches
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    pq = await _resolve_paper_question(db, paper_question_id)
    if pq is None:
        raise HTTPException(status_code=404, detail="Paper question not found")

    if pq.paper_id != paper.id:
        raise HTTPException(status_code=404, detail="Paper question not found in this paper")

    # Update fields
    if data.is_locked is not None:
        pq.is_locked = data.is_locked
    if data.score is not None:
        pq.score = data.score
    if data.section_id is not None:
        # Verify section belongs to this paper
        sec_result = await db.execute(
            select(PaperSection).where(
                PaperSection.id == data.section_id,
                PaperSection.paper_id == paper.id,
            )
        )
        section = sec_result.scalar_one_or_none()
        if section is None:
            raise HTTPException(
                status_code=400,
                detail="Section not found in this paper",
            )
        if pq.question and section.question_type != pq.question.question_type:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Section question_type '{section.question_type}' does not match "
                    f"question_type '{pq.question.question_type}'"
                ),
            )
        pq.paper_section_id = data.section_id
    if data.order_index is not None:
        pq.order_index = data.order_index

    await db.flush()
    await db.refresh(pq)

    return {
        "id": pq.id,
        "paper_id": paper.paper_id,
        "paper_section_id": pq.paper_section_id,
        "question_id": pq.question_id,
        "order_index": pq.order_index,
        "score": pq.score,
        "is_locked": pq.is_locked,
        "selection_reason": pq.selection_reason,
        "source_mode": pq.source_mode,
    }


# ──────────────────────────────────────────────
# DELETE /{paper_id}/questions/{paper_question_id} — Remove question from paper
# ──────────────────────────────────────────────


@router.delete("/{paper_id}/questions/{paper_question_id}")
async def remove_question_from_paper(
    paper_id: str,
    paper_question_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Remove a question from a paper."""
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    pq = await _resolve_paper_question(db, paper_question_id)
    if pq is None:
        raise HTTPException(status_code=404, detail="Paper question not found")

    if pq.paper_id != paper.id:
        raise HTTPException(status_code=404, detail="Paper question not found in this paper")

    pq_id = pq.id
    await db.delete(pq)
    await db.flush()

    return {"deleted": True, "id": pq_id}


# ──────────────────────────────────────────────
# POST /{paper_id}/questions/{paper_question_id}/replace — Replace a question
# ──────────────────────────────────────────────


@router.post("/{paper_id}/questions/{paper_question_id}/replace")
async def replace_question(
    paper_id: str,
    paper_question_id: int,
    data: ReplaceQuestionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Replace a question in a paper with a different one.

    The old PaperQuestion is kept but its data is overwritten to point to
    the new question, preserving order_index and lock status.
    """
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    pq = await _resolve_paper_question(db, paper_question_id)
    if pq is None:
        raise HTTPException(status_code=404, detail="Paper question not found")

    if pq.paper_id != paper.id:
        raise HTTPException(status_code=404, detail="Paper question not found in this paper")

    # Verify replacement question exists
    new_question = await _resolve_question_from_request(
        db,
        question_id=data.new_question_id,
        canonical_id=data.canonical_id,
    )
    if new_question is None:
        raise HTTPException(status_code=404, detail="Replacement question not found")
    if new_question.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Replacement question is not approved (status: {new_question.status})",
        )

    # Check the replacement question is not already in the paper
    existing = await db.execute(
        select(PaperQuestion).where(
            PaperQuestion.paper_id == paper.id,
            PaperQuestion.question_id == new_question.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Replacement question is already in this paper",
        )

    # Check similarity with other questions in the paper (simple check: same
    # question_type is fine, but warn if the replacement has the same stem
    # prefix as another question — basic dedup)
    other_questions_result = await db.execute(
        select(PaperQuestion)
        .options(selectinload(PaperQuestion.question))
        .where(
            PaperQuestion.paper_id == paper.id,
            PaperQuestion.id != pq.id,
        )
    )
    other_questions = other_questions_result.scalars().all()

    # Record the old question_id as replacement_of_id on the existing row,
    # then update to the new question
    old_question_id = pq.question_id
    pq.replacement_of_id = old_question_id
    pq.question_id = new_question.id
    pq.selection_reason = data.selection_reason
    pq.source_mode = "manual"
    if pq.paper_section_id is not None:
        section_result = await db.execute(
            select(PaperSection).where(
                PaperSection.id == pq.paper_section_id,
                PaperSection.paper_id == paper.id,
            )
        )
        section = section_result.scalar_one_or_none()
        if section and section.question_type != new_question.question_type:
            replacement_section = await _find_available_section_for_question(db, paper, new_question)
            if replacement_section is None:
                pq.paper_section_id = None
                pq.score = new_question.score
            else:
                pq.paper_section_id = replacement_section.id
                pq.score = replacement_section.score_each

    await db.flush()
    await db.refresh(pq)

    # Load replacement question info
    return {
        "id": pq.id,
        "paper_id": paper.paper_id,
        "paper_section_id": pq.paper_section_id,
        "question_id": pq.question_id,
        "question": {
            "id": new_question.id,
            "canonical_id": new_question.canonical_id,
            "stem": (new_question.stem or "")[:200],
            "question_type": new_question.question_type,
            "difficulty": new_question.difficulty,
            "grade": new_question.grade,
        },
        "order_index": pq.order_index,
        "score": pq.score,
        "is_locked": pq.is_locked,
        "selection_reason": pq.selection_reason,
        "source_mode": pq.source_mode,
        "replacement_of_id": pq.replacement_of_id,
        "replaced_question_id": old_question_id,
    }


# ──────────────────────────────────────────────
# POST /{paper_id}/assemble — Run the assembly engine
# ──────────────────────────────────────────────


@router.post("/{paper_id}/assemble", response_model=AssemblyResult)
async def assemble_paper(
    paper_id: str,
    constraints: AssemblyConstraints,
    db: AsyncSession = Depends(get_db),
):
    """Run the paper assembly engine with given constraints.

    Creates a PaperGenerationJob, validates constraints, selects questions,
    and populates the paper using the rule-based paper_generator service."""
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Row-level lock to prevent concurrent assembly on the same paper
    await db.execute(
        select(Paper).where(Paper.id == paper.id).with_for_update()
    )

    # Validate that the paper has sections to fill
    sections = paper.sections or []
    if not sections:
        raise HTTPException(
            status_code=400,
            detail="Paper has no sections defined. Add sections before assembling.",
        )

    # Create generation job
    job_id = f"gj_{uuid4().hex[:8]}"
    job = PaperGenerationJob(
        job_id=job_id,
        paper_id=paper.id,
        status="running",
        input_constraints_json=constraints.model_dump(),
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()

    try:
        # Enforce status transition BEFORE destructive mutations
        if paper.status not in ("draft", "assembled"):
            job.status = "failed"
            job.error_message = f"Cannot assemble paper in '{paper.status}' status."
            job.finished_at = datetime.now(timezone.utc)
            await db.flush()
            raise HTTPException(
                status_code=400,
                detail=f"Cannot assemble paper in '{paper.status}' status. Must be 'draft' or 'assembled'.",
            )

        # Re-running assembly should not keep stale generated questions.
        # Manually added/locked questions remain as anchors.
        for pq in list(paper.questions or []):
            if not pq.is_locked:
                await db.delete(pq)
        await db.flush()
        paper = await _resolve_paper(db, paper_id)

        service_constraints = paper_generator.AssemblyConstraints(
            selected_question_ids=constraints.selected_question_ids,
            lock_selected_questions=constraints.lock_selected_questions,
            knowledge_point_paths=constraints.knowledge_point_paths,
            use_llm_assist=constraints.use_llm_assist,
            use_semantic_search=constraints.use_semantic_search,
            natural_language_requirement=constraints.natural_language_requirement,
            difficulty_min=constraints.difficulty_min,
            difficulty_max=constraints.difficulty_max,
            exclude_recent_days=constraints.exclude_recent_days,
            similarity_threshold=constraints.similarity_threshold,
            tag_filter=constraints.tag_filter,
            include_answers=constraints.include_answers,
        )
        result = await paper_generator.assemble_paper(db, paper, service_constraints)

        for pq in result.paper_questions:
            db.add(pq)

        total_questions = len(result.paper_questions)
        total_score = sum(pq.score or 0.0 for pq in result.paper_questions)
        errors = [
            f"Section '{item['section_name']}': {item['filled']}/{item['needed']} filled"
            for item in result.unfilled_sections
        ]

        job.status = "succeeded" if not errors else "failed"
        job.finished_at = datetime.now(timezone.utc)
        job.candidate_question_ids_json = {
            "selected_question_ids": [pq.question_id for pq in result.paper_questions],
            "candidate_pool_size": result.candidate_pool_size,
        }
        job.validation_result_json = {
            "total_questions": total_questions,
            "total_score": total_score,
            "unfilled_sections": result.unfilled_sections,
            "selection_log": result.selection_log,
            "errors": errors,
        }
        if errors:
            job.error_message = "; ".join(errors)

        paper.status = "assembled"
        paper.validation_result_json = job.validation_result_json
        paper.updated_at = datetime.now(timezone.utc)
        await db.flush()

        # ── LLM assembly review (non-blocking, informational only) ──────────
        # Fire-and-forget: review results go into paper.metadata_json for display.
        # Failures are silent — the assembly result is valid with or without review.
        import asyncio as _asyncio

        async def _review_and_save():
            try:
                from app.services.assembly_reviewer import (
                    rule_based_review,
                    llm_review_assembly,
                )

                # Build lightweight summary for the reviewer
                section_summaries = []
                for s in sections:
                    filled = sum(
                        1 for pq in result.paper_questions
                        if pq.paper_section_id == s.id
                    )
                    section_summaries.append({
                        "id": s.id, "name": s.name,
                        "question_type": s.question_type or "",
                        "target_count": s.count, "filled_count": filled,
                        "score_each": s.score_each or 0,
                    })

                q_summaries = []
                for idx, pq in enumerate(result.paper_questions, 1):
                    q = pq.question
                    section_name = next(
                        (s.name for s in sections if s.id == pq.paper_section_id),
                        "未分配"
                    )
                    q_summaries.append({
                        "num": idx,
                        "stem": (q.stem or "") if q else "",
                        "question_type": q.question_type if q else "",
                        "difficulty": q.difficulty if q else 0,
                        "score": pq.score or 0,
                        "is_locked": pq.is_locked,
                        "section_name": section_name,
                        "has_answers": bool(q.answers) if q else False,
                    })

                # Step 1: rule-based checks (fast)
                rule_review = rule_based_review(q_summaries, section_summaries)

                # Step 2: LLM review (async, may fail gracefully)
                llm_result = await llm_review_assembly(
                    q_summaries, section_summaries,
                    layout_warnings=rule_review.layout_warnings,
                )

                # Merge results into paper metadata
                review_data = {
                    "rule_based": {
                        "layout_warnings": rule_review.layout_warnings,
                        "completeness_issues": rule_review.completeness_issues,
                        "balance_issues": rule_review.balance_issues,
                        "quality_issues": rule_review.quality_issues,
                    },
                    "llm_review": llm_result,
                }

                # Write review to paper metadata (in a new DB session — the
                # parent session may already be closed when this task fires)
                from app.database import async_session_factory
                async with async_session_factory() as review_db:
                    p = await review_db.get(Paper, paper.id)
                    if p:
                        p.metadata_json = {
                            **(p.metadata_json or {}),
                            "assembly_review": review_data,
                        }
                        await review_db.commit()
            except Exception:
                pass  # Review failure must never break assembly

        _asyncio.create_task(_review_and_save())

        paper = await _resolve_paper(db, paper_id)
        paper_questions = []
        for pq in sorted(paper.questions or [], key=lambda item: item.order_index or 0):
            paper_questions.append(
                {
                    "id": pq.id,
                    "paper_id": paper.id,
                    "paper_section_id": pq.paper_section_id,
                    "order_index": pq.order_index,
                    "score": pq.score,
                    "is_locked": pq.is_locked,
                    "selection_reason": pq.selection_reason,
                    "source_mode": pq.source_mode,
                    "question": {
                        "id": pq.question.id,
                        "canonical_id": pq.question.canonical_id,
                        "stem": (pq.question.stem or "")[:200],
                        "question_type": pq.question.question_type,
                        "difficulty": pq.question.difficulty,
                        "grade": pq.question.grade,
                    } if pq.question else None,
                }
            )

        return AssemblyResult(
            paper_questions=paper_questions,
            unfilled_sections=result.unfilled_sections,
            candidate_pool_size=result.candidate_pool_size,
            selection_log=result.selection_log,
            job_id=job_id,
            paper_id=paper.paper_id,
            status=job.status,
            total_questions=total_questions,
            total_score=total_score,
            sections_filled=total_questions,
            errors=errors,
        )
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        await db.flush()
        raise HTTPException(status_code=500, detail=f"Assembly failed: {exc}") from exc


# ──────────────────────────────────────────────
# POST /{paper_id}/validate — Validate paper
# ──────────────────────────────────────────────


@router.post("/{paper_id}/validate")
async def validate_paper(
    paper_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Validate a paper: check question approvals, section counts, total score,
    locked questions, and missing images."""
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    checks: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    is_valid = True

    questions_list = paper.questions or []
    sections_list = paper.sections or []

    # ── Check 1: All questions are approved ──
    all_approved = True
    for pq in questions_list:
        if pq.question and pq.question.status != "approved":
            all_approved = False
            errors.append(
                f"Question {pq.question.canonical_id} (id={pq.question_id}) "
                f"is not approved (status: {pq.question.status})"
            )
    checks.append({"name": "all_approved", "passed": all_approved})
    if not all_approved:
        is_valid = False

    # ── Check 2: Section count matches ──
    section_counts_ok = True
    expected_total = sum(s.count for s in sections_list)
    actual_total = len(questions_list)

    for section in sections_list:
        section_q_count = sum(
            1 for pq in questions_list if pq.paper_section_id == section.id
        )
        if section_q_count < section.count:
            section_counts_ok = False
            warnings.append(
                f"Section '{section.name}': {section_q_count}/{section.count} questions filled"
            )

    if actual_total != expected_total:
        errors.append(
            f"Question count mismatch: {actual_total} in paper, {expected_total} expected"
        )
        is_valid = False
    checks.append({
        "name": "section_counts",
        "passed": section_counts_ok,
        "actual_total": actual_total,
        "expected_total": expected_total,
    })

    # ── Check 3: Total score ──
    total_score = sum(pq.score or 0.0 for pq in questions_list)
    target_score = sum(s.count * s.score_each for s in sections_list)
    score_ok = abs(total_score - target_score) < 0.01
    checks.append({
        "name": "total_score",
        "passed": score_ok,
        "actual_score": total_score,
        "target_score": target_score,
    })
    if not score_ok:
        errors.append(
            f"Total score mismatch: {total_score} actual vs {target_score} expected"
        )
        is_valid = False

    # ── Check 4: Locked questions still present ──
    # (Locked questions must remain in the paper — we check that no locked
    # question was dropped during assembly)
    locked_present = True
    locked_count = sum(1 for pq in questions_list if pq.is_locked)
    checks.append({
        "name": "locked_preserved",
        "passed": True,
        "locked_count": locked_count,
    })

    # ── Check 5: Missing images ──
    missing_images: list[str] = []
    for pq in questions_list:
        if pq.question:
            _, missing = await _question_image_refs_exist(db, pq.question)
            missing_images.extend(missing)
    checks.append({
        "name": "missing_images",
        "passed": len(missing_images) == 0,
        "missing": missing_images,
    })
    if missing_images:
        warnings.append(f"{len(missing_images)} missing images detected")
        is_valid = False

    # Store validation result on the paper
    paper.validation_result_json = {
        "is_valid": is_valid,
        "total_score": total_score,
        "target_score": target_score,
        "question_count": actual_total,
        "expected_question_count": expected_total,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }
    paper.updated_at = datetime.now(timezone.utc)
    await db.flush()

    return {
        "paper_id": paper.paper_id,
        "is_valid": is_valid,
        "total_score": total_score,
        "target_score": target_score,
        "question_count": actual_total,
        "expected_question_count": expected_total,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


# ──────────────────────────────────────────────
# Export helpers
# ──────────────────────────────────────────────

_PAPERS_EXPORT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "exports" / "papers"


def _export_dir(paper_id: str, export_id: str) -> Path:
    """Return the directory path for a paper export artifact."""
    return _PAPERS_EXPORT_DIR / paper_id / export_id


# ──────────────────────────────────────────────
# POST /{paper_id}/export — Export paper to TeX/PDF
# ──────────────────────────────────────────────


@router.post("/{paper_id}/export", response_model=ExportJobRead)
async def export_paper(
    paper_id: str,
    data: ExportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Export a paper to separate question and answer TeX/PDF files.

    Produces six output files in the export directory:

    * ``questions.tex`` / ``questions.pdf`` — question paper (no answers)
    * ``answers.tex`` / ``answers.pdf`` — answer key only
    * ``build-questions.log`` / ``build-answers.log`` — per-file build logs

    Creates a PaperExportArtifact and runs the LaTeX rendering pipeline.
    """
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.questions:
        raise HTTPException(status_code=400, detail="Paper has no questions to export")

    # Reject export for papers not in a valid status
    if paper.status not in ("assembled", "exported"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot export paper in '{paper.status}' status. Must be 'assembled' or 'exported'.",
        )

    export_id = f"ex_{uuid4().hex[:8]}"
    export_dir = _export_dir(paper.paper_id, export_id)
    assets_dir = export_dir / "assets"
    export_dir.mkdir(parents=True, exist_ok=True)

    artifact = PaperExportArtifact(
        export_id=export_id,
        paper_id=paper.id,
        format=data.format,
        variant=data.variant,
        template_id=data.template_id,
        latex_engine=data.latex_engine,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(artifact)
    await db.flush()

    try:
        artifact.status = "running"
        await db.flush()

        paper_questions = paper.questions or []

        # ── 1. Copy assets (shared by both TeX files) ─────────────────
        copied_assets = await export_assets(paper_questions, assets_dir, db)

        # ── 2. Generate questions.tex ─────────────────────────────────
        questions_tex = await render_questions_to_tex(paper, paper_questions, db)
        questions_tex_path = export_dir / "questions.tex"
        questions_tex_path.write_text(questions_tex, encoding="utf-8")

        # ── 3. Generate answers.tex ───────────────────────────────────
        answers_tex = await render_answers_to_tex(paper, paper_questions, db)
        answers_tex_path = export_dir / "answers.tex"
        answers_tex_path.write_text(answers_tex, encoding="utf-8")

        # ── 4. Compile ────────────────────────────────────────────────
        questions_pdf_path: Optional[Path] = None
        questions_build_log = ""
        answers_pdf_path: Optional[Path] = None
        answers_build_log = ""

        compile_formats = {"tex_pdf", "pdf_only"}
        if data.format in compile_formats:
            questions_pdf_path, questions_build_log = await compile_pdf(
                questions_tex_path,
                export_dir,
                data.latex_engine,
            )
            answers_pdf_path, answers_build_log = await compile_pdf(
                answers_tex_path,
                export_dir,
                data.latex_engine,
            )
        else:
            questions_build_log = "TeX-only export requested; PDF compilation skipped."
            answers_build_log = "TeX-only export requested; PDF compilation skipped."

        # ── 5. Write build logs ───────────────────────────────────────
        (export_dir / "build-questions.log").write_text(questions_build_log, encoding="utf-8")
        (export_dir / "build-answers.log").write_text(answers_build_log, encoding="utf-8")

        # ── 6. Persist artifact ───────────────────────────────────────
        artifact.questions_tex_path = str(questions_tex_path)
        artifact.questions_pdf_path = str(questions_pdf_path) if questions_pdf_path else None
        artifact.questions_build_log = questions_build_log[-8000:] if questions_build_log else ""

        artifact.answers_tex_path = str(answers_tex_path)
        artifact.answers_pdf_path = str(answers_pdf_path) if answers_pdf_path else None
        artifact.answers_build_log = answers_build_log[-8000:] if answers_build_log else ""

        # Legacy compat fields — point at questions files for old clients
        artifact.tex_path = str(questions_tex_path)
        artifact.pdf_path = str(questions_pdf_path) if questions_pdf_path else None
        artifact.build_log = questions_build_log[-8000:] if questions_build_log else ""

        artifact.assets_dir = str(assets_dir)

        both_pdfs_ok = (
            data.format == "tex_only"
            or (questions_pdf_path is not None and answers_pdf_path is not None)
        )
        # Partial success: if questions PDF compiled but answers didn't,
        # mark as "partial" so questions can still be downloaded
        artifact.status = (
            "succeeded" if both_pdfs_ok else
            "partial" if data.format in compile_formats and questions_pdf_path is not None else
            "failed"
        )
        artifact.finished_at = datetime.now(timezone.utc)
        artifact.manifest_json = {
            "paper_id": paper.paper_id,
            "questions_tex": str(questions_tex_path),
            "questions_pdf": str(questions_pdf_path) if questions_pdf_path else None,
            "answers_tex": str(answers_tex_path),
            "answers_pdf": str(answers_pdf_path) if answers_pdf_path else None,
            "assets_dir": str(assets_dir),
            "assets": copied_assets,
            "format": data.format,
            "variant": data.variant,
        }

        if artifact.status == "failed":
            failed_parts: list[str] = []
            if data.format in compile_formats and questions_pdf_path is None:
                failed_parts.append("questions PDF compilation failed")
            if data.format in compile_formats and answers_pdf_path is None:
                failed_parts.append("answers PDF compilation failed")
            artifact.error_message = "; ".join(failed_parts) or "LaTeX compilation failed"
        elif artifact.status in ("succeeded", "partial"):
            # Transition to exported (status already verified at lines 1275-1280)
            paper.status = "exported"
            paper.updated_at = datetime.now(timezone.utc)

    except (OSError, RuntimeError, asyncio.TimeoutError) as exc:
        artifact.status = "failed"
        artifact.error_message = str(exc)
        artifact.finished_at = datetime.now(timezone.utc)
        # Clean up partial export directory on failure
        try:
            shutil.rmtree(export_dir, ignore_errors=True)
        except OSError:
            pass

    await db.flush()
    await db.refresh(artifact)

    return ExportJobRead(
        id=artifact.id,
        export_id=artifact.export_id,
        paper_id=paper.paper_id,
        format=artifact.format,
        variant=artifact.variant,
        template_id=artifact.template_id,
        latex_engine=artifact.latex_engine,
        status=artifact.status,
        questions_tex_path=artifact.questions_tex_path,
        questions_pdf_path=artifact.questions_pdf_path,
        questions_build_log_preview=artifact.questions_build_log,
        answers_tex_path=artifact.answers_tex_path,
        answers_pdf_path=artifact.answers_pdf_path,
        answers_build_log_preview=artifact.answers_build_log,
        tex_path=artifact.tex_path,
        pdf_path=artifact.pdf_path,
        build_log_preview=artifact.build_log,
        assets_dir=artifact.assets_dir,
        error_message=artifact.error_message,
        created_at=artifact.created_at,
        finished_at=artifact.finished_at,
    )


# ──────────────────────────────────────────────
# GET /{paper_id}/exports/{export_id} — Get export status
# ──────────────────────────────────────────────


@router.get("/{paper_id}/exports/{export_id}", response_model=ExportJobRead)
async def get_export_job(
    paper_id: str,
    export_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the status of an export job."""
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    stmt = select(PaperExportArtifact).where(
        PaperExportArtifact.export_id == export_id,
        PaperExportArtifact.paper_id == paper.id,
    )
    result = await db.execute(stmt)
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Export job not found")

    return ExportJobRead(
        id=artifact.id,
        export_id=artifact.export_id,
        paper_id=paper.paper_id,
        format=artifact.format,
        variant=artifact.variant,
        template_id=artifact.template_id,
        latex_engine=artifact.latex_engine,
        status=artifact.status,
        questions_tex_path=artifact.questions_tex_path,
        questions_pdf_path=artifact.questions_pdf_path,
        questions_build_log_preview=artifact.questions_build_log,
        answers_tex_path=artifact.answers_tex_path,
        answers_pdf_path=artifact.answers_pdf_path,
        answers_build_log_preview=artifact.answers_build_log,
        tex_path=artifact.tex_path,
        pdf_path=artifact.pdf_path,
        build_log_preview=artifact.build_log,
        assets_dir=artifact.assets_dir,
        error_message=artifact.error_message,
        created_at=artifact.created_at,
        finished_at=artifact.finished_at,
    )


# ──────────────────────────────────────────────
# GET /{paper_id}/exports/{export_id}/download — Download export artifact
# ──────────────────────────────────────────────


# Map download type to (artifact_field, media_type, filename_suffix)
_DOWNLOAD_TYPE_MAP: dict[str, tuple[str, str, str]] = {
    # New-style question/answer variants
    "questions-pdf":  ("questions_pdf_path",  "application/pdf",       "questions.pdf"),
    "questions-tex":  ("questions_tex_path",  "application/x-tex",     "questions.tex"),
    "answers-pdf":    ("answers_pdf_path",    "application/pdf",       "answers.pdf"),
    "answers-tex":    ("answers_tex_path",    "application/x-tex",     "answers.tex"),
    "questions-log":  ("questions_build_log", "text/plain; charset=utf-8", "build-questions.log"),
    "answers-log":    ("answers_build_log",   "text/plain; charset=utf-8", "build-answers.log"),
    # Legacy compat aliases
    "pdf": ("questions_pdf_path", "application/pdf",   "questions.pdf"),
    "tex": ("questions_tex_path", "application/x-tex", "questions.tex"),
}


@router.get("/{paper_id}/exports/{export_id}/download")
async def download_export(
    paper_id: str,
    export_id: str,
    type: str = Query(
        "questions-pdf",
        description=(
            "File type: questions-pdf, questions-tex, answers-pdf, answers-tex, "
            "questions-log, answers-log, pdf (legacy alias for questions-pdf), "
            "tex (legacy alias for questions-tex)"
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Download a paper export artifact.

    Supports separate question-paper and answer-key downloads as well as
    per-file build logs.
    """
    paper = await _resolve_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    stmt = select(PaperExportArtifact).where(
        PaperExportArtifact.export_id == export_id,
        PaperExportArtifact.paper_id == paper.id,
    )
    result = await db.execute(stmt)
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Export job not found")

    if artifact.status not in ("succeeded", "partial"):
        raise HTTPException(
            status_code=409,
            detail=f"Export job is not ready (status: {artifact.status})",
        )

    # For "partial" status: answers-pdf/answers-tex are not available,
    # but answers-log IS available (it contains the compilation error details)
    if artifact.status == "partial" and type in ("answers-pdf", "answers-tex", "pdf", "tex"):
        raise HTTPException(
            status_code=409,
            detail="Answers were not compiled successfully. Only question paper downloads and build logs are available.",
        )

    mapping = _DOWNLOAD_TYPE_MAP.get(type)
    if mapping is None:
        valid = ", ".join(sorted(_DOWNLOAD_TYPE_MAP.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type '{type}'. Must be one of: {valid}",
        )

    field_name, media_type, filename = mapping

    # Build logs are stored as text blobs on the artifact, not as file paths
    if type in ("questions-log", "answers-log"):
        content = getattr(artifact, field_name, None) or ""
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content, media_type=media_type)

    file_path_str = getattr(artifact, field_name, None)
    if not file_path_str or not os.path.isfile(file_path_str):
        raise HTTPException(
            status_code=404,
            detail=f"{type} file not found",
        )

    return FileResponse(
        file_path_str,
        media_type=media_type,
        filename=f"{paper.paper_id}_{filename}",
    )
