"""Review API — list, approve, and reject questions in the review queue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.question import (
    ChoiceOption,
    Question,
    QuestionKnowledgePoint,
    SolutionStep,
    Answer,
)

router = APIRouter()

# Valid status transitions
VALID_TRANSITIONS = {
    "pending_review": {"approved", "rejected"},
}

STATUS_LABELS = {
    "draft": "草稿",
    "pending_review": "待审核",
    "approved": "已通过",
    "rejected": "已驳回",
    "archived": "已归档",
}


@router.get("/pending")
async def list_pending(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    q: str = Query("", description="Search query"),
    db: AsyncSession = Depends(get_db),
):
    """List all questions with pending_review status."""
    # Build base query
    query = select(Question).where(Question.status == "pending_review")

    if q:
        query = query.where(Question.stem.ilike(f"%{q}%"))

    # Get total
    count_query = select(func.count()).select_from(Question).where(Question.status == "pending_review")
    if q:
        count_query = count_query.where(Question.stem.ilike(f"%{q}%"))
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get items with relationships
    query = (
        query
        .options(
            selectinload(Question.question_knowledge_points).selectinload(QuestionKnowledgePoint.knowledge_point),
            selectinload(Question.tags),
        )
        .order_by(Question.created_at.desc())
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(query)
    questions = result.scalars().all()

    # Build items
    items = []
    for q_obj in questions:
        items.append({
            "id": q_obj.id,
            "canonical_id": q_obj.canonical_id,
            "question_type": q_obj.question_type,
            "stem": q_obj.stem,
            "difficulty": q_obj.difficulty,
            "grade": q_obj.grade,
            "status": q_obj.status,
            "knowledge_points": [
                qkp.knowledge_point.path
                for qkp in q_obj.question_knowledge_points
                if qkp.knowledge_point
            ],
            "tags": [t.name for t in q_obj.tags],
            "created_at": q_obj.created_at.isoformat() if q_obj.created_at else None,
            "updated_at": q_obj.updated_at.isoformat() if q_obj.updated_at else None,
        })

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/pending/count")
async def count_pending(db: AsyncSession = Depends(get_db)):
    """Get the count of pending_review questions."""
    result = await db.execute(
        select(func.count()).select_from(Question).where(Question.status == "pending_review")
    )
    count = result.scalar() or 0
    return {"count": count}


@router.post("/{question_id}/approve")
async def approve_question(question_id: int, db: AsyncSession = Depends(get_db)):
    """Approve a question: pending_review → approved."""
    question = await db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if question.status != "pending_review":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve question with status '{question.status}'. "
                   f"Only 'pending_review' questions can be approved.",
        )

    question.status = "approved"
    await db.commit()
    await db.refresh(question)

    return {"id": question.id, "canonical_id": question.canonical_id, "status": question.status}


@router.post("/{question_id}/reject")
async def reject_question(
    question_id: int,
    reason: str = Query("", description="Rejection reason"),
    db: AsyncSession = Depends(get_db),
):
    """Reject a question: pending_review → rejected."""
    question = await db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if question.status != "pending_review":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject question with status '{question.status}'. "
                   f"Only 'pending_review' questions can be rejected.",
        )

    question.status = "rejected"
    await db.commit()
    await db.refresh(question)

    return {
        "id": question.id,
        "canonical_id": question.canonical_id,
        "status": question.status,
        "reason": reason or "No reason provided",
    }
