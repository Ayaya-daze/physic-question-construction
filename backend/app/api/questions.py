"""API routes for question CRUD and search."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Union
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import settings
from app.models import (
    Answer,
    ChoiceOption,
    KnowledgePoint,
    KnowledgePointCandidate,
    Question,
    QuestionKnowledgeCandidate,
    QuestionKnowledgePoint,
    SolutionStep,
    Tag,
)
from app.models.question import question_tags
from app.schemas.question import (
    KnowledgePointRef,
    PaginatedResponse,
    QuestionCreate,
    QuestionList,
    QuestionRead,
    QuestionSearchParams,
    QuestionUpdate,
    StatusUpdate,
)

router = APIRouter()


# Status transition map
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_review"},
    "pending_review": {"approved", "rejected"},
    "approved": {"archived"},
    "archived": {"approved"},
}


def _can_transition(current: str, target: str) -> bool:
    """Check if a status transition from `current` to `target` is allowed."""
    return target in STATUS_TRANSITIONS.get(current, set())


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


async def _resolve_question(
    db: AsyncSession, question_id: Union[int, str]
) -> Question | None:
    """Look up a question by database id (int) or canonical_id (str)."""
    try:
        numeric_id = int(question_id)
    except (ValueError, TypeError):
        numeric_id = None

    stmt = select(Question).options(
        selectinload(Question.choice_options),
        selectinload(Question.answers),
        selectinload(Question.solution_steps),
        selectinload(Question.question_knowledge_points).selectinload(QuestionKnowledgePoint.knowledge_point),
        selectinload(Question.tags),
    )

    if numeric_id is not None:
        stmt = stmt.where(Question.id == numeric_id)
    else:
        stmt = stmt.where(Question.canonical_id == str(question_id))

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _sync_knowledge_points(
    db: AsyncSession,
    question: Question,
    kp_refs: list[KnowledgePointRef],
    mode: str = "strict",
) -> None:
    """Remove existing knowledge-point links and create new ones.

    Three modes control behavior when a knowledge point path is not found:

    - ``strict`` (default): Raise HTTPException 400, suggesting 'candidate' mode.
    - ``candidate``: Create a KnowledgePointCandidate with status='pending' and
      a QuestionKnowledgeCandidate link. Do NOT block question creation.
    - ``force_create``: Directly create a new KnowledgePoint with
      status='approved' and bind it normally.
    """
    # Delete existing bridge records
    existing = await db.execute(
        select(QuestionKnowledgePoint).where(QuestionKnowledgePoint.question_id == question.id)
    )
    for row in existing.scalars().all():
        await db.delete(row)

    # Also clear existing candidate links
    existing_candidates = await db.execute(
        select(QuestionKnowledgeCandidate).where(
            QuestionKnowledgeCandidate.question_id == question.id
        )
    )
    for row in existing_candidates.scalars().all():
        await db.delete(row)

    # Create new bridge records
    for ref in kp_refs:
        kp_result = await db.execute(
            select(KnowledgePoint).where(KnowledgePoint.path == ref.path)
        )
        kp = kp_result.scalar_one_or_none()
        if kp is not None:
            qkp = QuestionKnowledgePoint(
                question_id=question.id,
                knowledge_point_id=kp.id,
                weight=ref.weight,
                is_primary=ref.is_primary,
            )
            db.add(qkp)
        elif mode == "force_create":
            # Directly create the knowledge point and bind it
            new_kp = KnowledgePoint(
                path=ref.path,
                name=ref.path.rsplit("/", 1)[-1],
                level=ref.path.count("/") + 1,
            )
            db.add(new_kp)
            await db.flush()
            qkp = QuestionKnowledgePoint(
                question_id=question.id,
                knowledge_point_id=new_kp.id,
                weight=ref.weight,
                is_primary=ref.is_primary,
                source="user_created",
            )
            db.add(qkp)
        elif mode == "candidate":
            # Create a pending candidate instead of blocking
            candidate_id = f"kpc_{uuid4().hex[:8]}"
            confidence = getattr(ref, "confidence", 0.5) or 0.5
            kpc = KnowledgePointCandidate(
                candidate_id=candidate_id,
                canonical_name=ref.path.rsplit("/", 1)[-1],
                suggested_parent_path="/".join(ref.path.rsplit("/", 1)[:-1]) or None,
                confidence=confidence,
                status="pending",
                source="user_created",
                source_question_id=question.id,
            )
            db.add(kpc)
            await db.flush()
            qkc = QuestionKnowledgeCandidate(
                question_id=question.id,
                knowledge_point_candidate_id=kpc.id,
                weight=ref.weight,
                is_primary=ref.is_primary,
            )
            db.add(qkc)
        else:
            # strict mode — return 400 with suggestion
            raise HTTPException(
                status_code=400,
                detail=f"Knowledge point not found: {ref.path}. "
                f"Use knowledge_point_mode='candidate' to create a pending candidate, "
                f"or knowledge_point_mode='force_create' to auto-create the knowledge point.",
            )


async def _sync_tags(
    db: AsyncSession, question: Question, tag_names: list[str]
) -> None:
    """Remove existing tag links, find or create tags, and link them."""
    # Remove existing associations via the association table
    from sqlalchemy import delete as sa_delete

    await db.execute(
        sa_delete(question_tags).where(question_tags.c.question_id == question.id)
    )

    for name in tag_names:
        tag_result = await db.execute(select(Tag).where(Tag.name == name))
        tag = tag_result.scalar_one_or_none()
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            await db.flush()
        # Direct insert into association table — avoids lazy-load on new Questions
        await db.execute(
            question_tags.insert().values(question_id=question.id, tag_id=tag.id)
        )


def _apply_question_scalars(question: Question, data: QuestionCreate | QuestionUpdate) -> None:
    """Apply scalar fields from a schema object to the Question ORM object."""
    scalar_fields = (
        "stem", "question_type", "normalized_stem", "difficulty", "grade",
        "semester", "textbook_version", "chapter", "score",
        "estimated_time_seconds", "source_document_id", "source_page",
        "source_region", "source_crop_asset_id", "metadata_json",
    )
    for field in scalar_fields:
        if hasattr(data, field):
            value = getattr(data, field)
            if value is not None:
                setattr(question, field, value)
    # Update timestamp
    question.updated_at = datetime.now(timezone.utc)


# ──────────────────────────────────────────────
# GET / — List and search questions
# ──────────────────────────────────────────────


@router.get("", response_model=PaginatedResponse, include_in_schema=False)
@router.get("/", response_model=PaginatedResponse)
async def list_questions(
    q: str | None = Query(None, description="Search term for stem/normalized_stem"),
    question_type: str | None = Query(None),
    difficulty_min: int | None = Query(None),
    difficulty_max: int | None = Query(None),
    grade: str | None = Query(None),
    status: str | None = Query(None),
    knowledge_point_id: int | None = Query(None),
    tag_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List and search questions with optional filters.

    Supports full-text search on stem, filtering by type/difficulty/grade/status,
    and filtering by knowledge point or tag.
    """
    # Build base query with eager-loading options
    query = select(Question).options(
        selectinload(Question.question_knowledge_points).selectinload(QuestionKnowledgePoint.knowledge_point),
        selectinload(Question.tags),
    )

    # Optional joins for knowledge_point / tag filters
    if knowledge_point_id is not None:
        query = query.join(
            QuestionKnowledgePoint,
            Question.id == QuestionKnowledgePoint.question_id,
        ).where(QuestionKnowledgePoint.knowledge_point_id == knowledge_point_id)

    if tag_id is not None:
        query = query.join(question_tags, Question.id == question_tags.c.question_id).where(
            question_tags.c.tag_id == tag_id
        )

    # Text search on stem and normalized_stem
    if q:
        like_pattern = f"%{q}%"
        query = query.where(
            or_(
                Question.stem.ilike(like_pattern),
                Question.normalized_stem.ilike(like_pattern),
            )
        )

    # Equality filters
    if question_type:
        query = query.where(Question.question_type == question_type)
    if grade:
        query = query.where(Question.grade == grade)
    if status:
        query = query.where(Question.status == status)

    # Difficulty range
    if difficulty_min is not None:
        query = query.where(Question.difficulty >= difficulty_min)
    if difficulty_max is not None:
        query = query.where(Question.difficulty <= difficulty_max)

    # Order by updated_at descending
    query = query.order_by(Question.updated_at.desc())

    # Count total — build a separate count query from the filtered base without options
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    questions = result.unique().scalars().all()

    items = [QuestionList.from_orm(q) for q in questions]

    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


# ──────────────────────────────────────────────
# POST / — Create a question
# ──────────────────────────────────────────────


@router.post("", response_model=QuestionRead, status_code=201, include_in_schema=False)
@router.post("/", response_model=QuestionRead, status_code=201)
async def create_question(
    data: QuestionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new question with options, answers, solution steps,
    knowledge points, and tags."""
    canonical_id = f"q_{uuid4().hex[:8]}"

    question = Question(
        canonical_id=canonical_id,
        status="draft",
        stem=data.stem,
        question_type=data.question_type,
        normalized_stem=data.normalized_stem,
        difficulty=data.difficulty,
        grade=data.grade,
        semester=data.semester,
        textbook_version=data.textbook_version,
        chapter=data.chapter,
        score=data.score,
        estimated_time_seconds=data.estimated_time_seconds,
        source_document_id=data.source_document_id,
        source_page=data.source_page,
        source_region=data.source_region,
        source_crop_asset_id=data.source_crop_asset_id,
        metadata_json=data.metadata_json,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(question)
    await db.flush()  # Get question.id

    # Create choice options
    for opt_data in data.options:
        option = ChoiceOption(
            question_id=question.id,
            option_label=opt_data.option_label,
            content=opt_data.content,
            is_correct=opt_data.is_correct,
            order_index=opt_data.order_index,
        )
        db.add(option)

    # Create answers
    for ans_data in data.answers:
        answer = Answer(
            question_id=question.id,
            answer_type=ans_data.answer_type,
            content=ans_data.content,
            normalized_content=ans_data.normalized_content,
            unit=ans_data.unit,
            significant_figures=ans_data.significant_figures,
        )
        db.add(answer)

    # Create solution steps
    for step_data in data.solution_steps:
        step = SolutionStep(
            question_id=question.id,
            step_order=step_data.step_order,
            content=step_data.content,
            formula=step_data.formula,
            explanation=step_data.explanation,
        )
        db.add(step)

    await db.flush()

    # Sync knowledge points with the requested mode
    mode = getattr(data, "knowledge_point_mode", "candidate") or "candidate"
    await _sync_knowledge_points(db, question, data.knowledge_points, mode=mode)

    # Sync tags
    await _sync_tags(db, question, data.tags)

    await db.flush()
    await db.refresh(question)

    # Reload with all relationships
    full = await _resolve_question(db, question.id)
    return QuestionRead.from_orm(full)


# ──────────────────────────────────────────────
# Path helpers
# ──────────────────────────────────────────────

_QUESTIONS_DIR = settings.questions_dir


def _question_dir(canonical_id: str) -> Path:
    """Return the directory path for a question's canonical_id."""
    return _QUESTIONS_DIR / canonical_id


# ──────────────────────────────────────────────
# GET /{question_id}/content — File content serving
# ──────────────────────────────────────────────


@router.get("/{question_id}/content")
async def get_question_content(
    question_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve question content from its file or assemble from DB.

    Reads ../questions/{canonical_id}/content.md if it exists;
    otherwise assembles content from database fields.
    """
    question = await _resolve_question(db, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    content_file = _question_dir(question.canonical_id) / "content.md"

    if content_file.exists():
        content = content_file.read_text(encoding="utf-8")
        return {"canonical_id": question.canonical_id, "content": content, "source": "file"}

    # Assemble content from DB fields
    parts: list[str] = []
    parts.append(f"# {question.stem}")
    if question.question_type:
        parts.append(f"\n**Type:** {question.question_type}")
    if question.difficulty:
        parts.append(f"**Difficulty:** {question.difficulty}/10")
    if question.grade:
        parts.append(f"**Grade:** {question.grade}")
    if question.chapter:
        parts.append(f"**Chapter:** {question.chapter}")

    if question.choice_options:
        parts.append("\n## Options")
        for opt in sorted(question.choice_options, key=lambda o: o.order_index or 0):
            prefix = "  [x]" if opt.is_correct else "  [ ]"
            parts.append(f"{prefix} **{opt.option_label}**: {opt.content}")

    if question.answers:
        parts.append("\n## Answers")
        for ans in question.answers:
            parts.append(f"- **{ans.answer_type}**: {ans.content}")
            if ans.unit:
                parts.append(f"  Unit: {ans.unit}")

    if question.solution_steps:
        parts.append("\n## Solution")
        for step in sorted(question.solution_steps, key=lambda s: s.step_order):
            parts.append(f"\n### Step {step.step_order}")
            parts.append(step.content)
            if step.formula:
                parts.append(f"\n$${step.formula}$$")
            if step.explanation:
                parts.append(f"\n{step.explanation}")

    content = "\n".join(parts)
    return {"canonical_id": question.canonical_id, "content": content, "source": "database"}

# ──────────────────────────────────────────────


@router.get("/{question_id}", response_model=QuestionRead)
async def get_question(
    question_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a question by its numeric ID or canonical_id."""
    question = await _resolve_question(db, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return QuestionRead.from_orm(question)


# ──────────────────────────────────────────────
# PUT /{question_id} — Update question
# ──────────────────────────────────────────────


@router.put("/{question_id}", response_model=QuestionRead)
async def update_question(
    question_id: str,
    data: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a question. Provided nested collections replace existing ones."""
    question = await _resolve_question(db, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    # Apply scalar field updates
    _apply_question_scalars(question, data)

    if data.status is not None:
        if not _can_transition(question.status, data.status):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from '{question.status}' to '{data.status}'",
            )
        question.status = data.status

    # Replace choice options if provided
    if data.options is not None:
        # Delete existing
        existing_opts = await db.execute(
            select(ChoiceOption).where(ChoiceOption.question_id == question.id)
        )
        for opt in existing_opts.scalars().all():
            await db.delete(opt)
        # Create new
        for opt_data in data.options:
            option = ChoiceOption(
                question_id=question.id,
                option_label=opt_data.option_label,
                content=opt_data.content,
                is_correct=opt_data.is_correct,
                order_index=opt_data.order_index,
            )
            db.add(option)

    # Replace answers if provided
    if data.answers is not None:
        existing_ans = await db.execute(
            select(Answer).where(Answer.question_id == question.id)
        )
        for ans in existing_ans.scalars().all():
            await db.delete(ans)
        for ans_data in data.answers:
            answer = Answer(
                question_id=question.id,
                answer_type=ans_data.answer_type,
                content=ans_data.content,
                normalized_content=ans_data.normalized_content,
                unit=ans_data.unit,
                significant_figures=ans_data.significant_figures,
            )
            db.add(answer)

    # Replace solution steps if provided
    if data.solution_steps is not None:
        existing_steps = await db.execute(
            select(SolutionStep).where(SolutionStep.question_id == question.id)
        )
        for step in existing_steps.scalars().all():
            await db.delete(step)
        for step_data in data.solution_steps:
            step = SolutionStep(
                question_id=question.id,
                step_order=step_data.step_order,
                content=step_data.content,
                formula=step_data.formula,
                explanation=step_data.explanation,
            )
            db.add(step)

    await db.flush()

    # Sync knowledge points if provided
    if data.knowledge_points is not None:
        mode = getattr(data, "knowledge_point_mode", "candidate") or "candidate"
        await _sync_knowledge_points(db, question, data.knowledge_points, mode=mode)

    # Sync tags if provided
    if data.tags is not None:
        await _sync_tags(db, question, data.tags)

    await db.flush()
    await db.refresh(question)

    # Reload with relationships
    full = await _resolve_question(db, question.id)
    return QuestionRead.from_orm(full)


# ──────────────────────────────────────────────
# DELETE /{question_id} — Delete question
# ──────────────────────────────────────────────


@router.delete("/{question_id}")
async def delete_question(
    question_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a question and all associated entities (cascade)."""
    # Resolve the question without eager-loading everything
    try:
        numeric_id = int(question_id)
    except (ValueError, TypeError):
        numeric_id = None

    stmt = select(Question)
    if numeric_id is not None:
        stmt = stmt.where(Question.id == numeric_id)
    else:
        stmt = stmt.where(Question.canonical_id == str(question_id))

    result = await db.execute(stmt)
    question = result.scalar_one_or_none()

    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    qid = question.id
    await db.delete(question)
    await db.flush()

    return {"deleted": True, "id": qid}


# ──────────────────────────────────────────────
# PATCH /{question_id}/status — Status transition
# ──────────────────────────────────────────────


@router.patch("/{question_id}/status", response_model=QuestionRead)
async def update_question_status(
    question_id: str,
    data: StatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Transition a question to a new status following allowed transitions."""
    question = await _resolve_question(db, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    if not _can_transition(question.status, data.status):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{question.status}' to '{data.status}'. "
            f"Allowed transitions: {STATUS_TRANSITIONS.get(question.status, set())}",
        )

    question.status = data.status
    question.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(question)

    return QuestionRead.from_orm(question)


# ──────────────────────────────────────────────
# POST /export-all — Bulk export all approved questions
# ──────────────────────────────────────────────
