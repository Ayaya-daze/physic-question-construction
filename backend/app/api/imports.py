"""API routes for batch imports of questions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
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
from app.schemas.question import KnowledgePointRef, QuestionCreate

router = APIRouter()


class BatchImportResponse(BaseModel):
    """Response model for batch import operations."""

    total: int
    succeeded: int
    failed: int
    errors: list[dict] = []


@router.post("/json-v2", response_model=BatchImportResponse)
async def import_questions_json_v2(
    questions: list[dict],
    db: AsyncSession = Depends(get_db),
):
    """Batch import questions from a JSON array with proper transactional handling.

    Validates all items first, then inserts only the valid ones in a single
    transaction. Invalid items are reported with index and error message.
    """
    total = len(questions)
    valid_items: list[tuple[int, QuestionCreate]] = []
    errors: list[dict] = []

    # Phase 1: validate all
    for index, raw in enumerate(questions):
        try:
            data = QuestionCreate.model_validate(raw)
            valid_items.append((index, data))
        except Exception as e:
            errors.append({"index": index, "message": f"Validation error: {str(e)}"})

    if not valid_items:
        return BatchImportResponse(
            total=total,
            succeeded=0,
            failed=len(errors),
            errors=errors,
        )

    # Phase 2: insert each valid item in its own savepoint so one
    # failure does not roll back previously committed items.
    succeeded = 0
    for index, data in valid_items:
        savepoint = await db.begin_nested()
        try:
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
            await db.flush()

            # Choice options
            for opt_data in data.options:
                option = ChoiceOption(
                    question_id=question.id,
                    option_label=opt_data.option_label,
                    content=opt_data.content,
                    is_correct=opt_data.is_correct,
                    order_index=opt_data.order_index,
                )
                db.add(option)

            # Answers
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

            # Solution steps
            for step_data in data.solution_steps:
                step = SolutionStep(
                    question_id=question.id,
                    step_order=step_data.step_order,
                    content=step_data.content,
                    formula=step_data.formula,
                    explanation=step_data.explanation,
                )
                db.add(step)

            # Knowledge points — create candidates for unknown paths
            for ref in data.knowledge_points:
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
                else:
                    kpc = KnowledgePointCandidate(
                        candidate_id=f"kpc_{uuid4().hex[:8]}",
                        canonical_name=ref.path.rsplit("/", 1)[-1],
                        suggested_parent_path=(
                            "/".join(ref.path.rsplit("/", 1)[:-1]) or None
                        ),
                        confidence=getattr(ref, "confidence", 0.7) or 0.7,
                        status="pending",
                        source="import",
                        source_question_id=question.id,
                    )
                    db.add(kpc)
                    await db.flush()
                    db.add(QuestionKnowledgeCandidate(
                        question_id=question.id,
                        knowledge_point_candidate_id=kpc.id,
                        weight=ref.weight,
                        is_primary=ref.is_primary,
                    ))

            # Tags
            for tag_name in data.tags:
                tag_result = await db.execute(select(Tag).where(Tag.name == tag_name))
                tag = tag_result.scalar_one_or_none()
                if tag is None:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    await db.flush()
                await db.execute(
                    question_tags.insert().values(question_id=question.id, tag_id=tag.id)
                )

            succeeded += 1

        except Exception as e:
            errors.append({"index": index, "message": f"Database error: {str(e)}"})
            await savepoint.rollback()
            continue

    return BatchImportResponse(
        total=total,
        succeeded=succeeded,
        failed=len(errors),
        errors=errors,
    )
