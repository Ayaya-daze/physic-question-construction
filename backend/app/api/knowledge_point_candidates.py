"""Knowledge Point Candidate API — list, review, approve, reject, merge, and edit candidates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.knowledge_point import KnowledgePoint
from app.models.knowledge_point_candidate import (
    KnowledgePointAlias,
    KnowledgePointCandidate,
    KnowledgePointMergeLog,
    QuestionKnowledgeCandidate,
)
from app.models.question import QuestionKnowledgePoint
from app.schemas.knowledge_point_candidate import (
    CandidateUpdateRequest,
    KnowledgePointCandidateListResponse,
    KnowledgePointCandidateRead,
    MergeRequest,
)

router = APIRouter()


def _candidate_to_read(candidate: KnowledgePointCandidate) -> dict:
    """Convert a KnowledgePointCandidate ORM object to a read dict."""
    source_question = None
    if candidate.source_question:
        source_question = {
            "id": candidate.source_question.id,
            "canonical_id": candidate.source_question.canonical_id,
            "stem": (candidate.source_question.stem or "")[:200],
            "question_type": candidate.source_question.question_type,
        }

    return {
        "id": candidate.id,
        "candidate_id": candidate.candidate_id,
        "canonical_name": candidate.canonical_name,
        "definition": candidate.definition,
        "suggested_parent_path": candidate.suggested_parent_path,
        "suggested_parent_id": candidate.suggested_parent_id,
        "confidence": candidate.confidence,
        "source": candidate.source,
        "status": candidate.status,
        "source_question_id": candidate.source_question_id,
        "source_document_id": candidate.source_document_id,
        "source_text_snippet": candidate.source_text_snippet,
        "reviewer": candidate.reviewer,
        "review_note": candidate.review_note,
        "merged_into_kp_id": candidate.merged_into_kp_id,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "updated_at": candidate.updated_at.isoformat() if candidate.updated_at else None,
        "source_question": source_question,
    }


# ──────────────────────────────────────────────
# GET / — List knowledge point candidates
# ──────────────────────────────────────────────


@router.get("", response_model=KnowledgePointCandidateListResponse, include_in_schema=False)
@router.get("/", response_model=KnowledgePointCandidateListResponse)
async def list_candidates(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str = Query("pending"),
    db: AsyncSession = Depends(get_db),
):
    """List knowledge point candidates with optional status filter."""
    # Build count query
    count_query = select(func.count()).select_from(KnowledgePointCandidate)
    if status:
        count_query = count_query.where(KnowledgePointCandidate.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Build items query with relationships
    items_query = (
        select(KnowledgePointCandidate)
        .options(
            selectinload(KnowledgePointCandidate.source_question),
        )
        .order_by(KnowledgePointCandidate.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if status:
        items_query = items_query.where(KnowledgePointCandidate.status == status)

    result = await db.execute(items_query)
    candidates = result.scalars().all()

    items = [_candidate_to_read(c) for c in candidates]

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# ──────────────────────────────────────────────
# GET /{candidate_id} — Get single candidate detail
# ──────────────────────────────────────────────


@router.get("/{candidate_id}")
async def get_candidate(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single knowledge point candidate by candidate_id."""
    query = (
        select(KnowledgePointCandidate)
        .options(
            selectinload(KnowledgePointCandidate.source_question),
            selectinload(KnowledgePointCandidate.source_document),
            selectinload(KnowledgePointCandidate.suggested_parent),
        )
        .where(KnowledgePointCandidate.candidate_id == candidate_id)
    )
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Knowledge point candidate not found")

    return _candidate_to_read(candidate)


# ──────────────────────────────────────────────
# POST /{candidate_id}/approve — Approve and create real KP
# ──────────────────────────────────────────────


@router.post("/{candidate_id}/approve")
async def approve_candidate(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Approve a candidate and create a real KnowledgePoint."""
    query = (
        select(KnowledgePointCandidate)
        .options(
            selectinload(KnowledgePointCandidate.source_question),
            selectinload(KnowledgePointCandidate.question_links),
        )
        .where(KnowledgePointCandidate.candidate_id == candidate_id)
    )
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Knowledge point candidate not found")

    if candidate.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve candidate with status '{candidate.status}'. Only 'pending' candidates can be approved.",
        )

    # Build path
    if candidate.suggested_parent_path:
        kp_path = candidate.suggested_parent_path.rstrip("/") + "/" + candidate.canonical_name
    else:
        kp_path = candidate.canonical_name

    # ── Dedup: path-based ──
    dup_path = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.path == kp_path)
    )
    if dup_path.scalar_one_or_none():
        raise HTTPException(status_code=409,
            detail=f"Knowledge point with path '{kp_path}' already exists. Use merge instead.")

    # Dedup: same name at the SAME path is already caught above (path check).
    # Same name at a different path is allowed — it's a different context.
    # Only reject if same name exists with no parent (top-level collision)
    # or if an alias for the exact full path already exists.
    alias_dup = await db.execute(
        select(KnowledgePointAlias).where(KnowledgePointAlias.alias == kp_path)
    )
    alias_row = alias_dup.scalar_one_or_none()
    if alias_row:
        raise HTTPException(status_code=409,
            detail=f"Path '{kp_path}' is already an alias of KP id={alias_row.knowledge_point_id}. Use merge.")

    # ── Auto-create missing parent chain ──
    parent_id = candidate.suggested_parent_id
    if not parent_id and candidate.suggested_parent_path:
        parent_paths = candidate.suggested_parent_path.strip("/").split("/")

        # Walk from root, creating any missing ancestor nodes
        cumulative = ""
        for segment in parent_paths:
            cumulative = (cumulative + "/" + segment) if cumulative else segment
            p = await db.execute(
                select(KnowledgePoint).where(KnowledgePoint.path == cumulative)
            )
            existing_parent = p.scalar_one_or_none()
            if existing_parent:
                parent_id = existing_parent.id
            else:
                # Find its own parent
                grandparent_id = None
                if "/" in cumulative:
                    grandparent_path = cumulative.rsplit("/", 1)[0]
                    gp = await db.execute(
                        select(KnowledgePoint).where(KnowledgePoint.path == grandparent_path)
                    )
                    gp_row = gp.scalar_one_or_none()
                    if gp_row:
                        grandparent_id = gp_row.id

                ancestor_kp = KnowledgePoint(
                    name=segment,
                    canonical_name=segment,
                    path=cumulative,
                    level=cumulative.count("/") + 1,
                    source="auto",
                    confidence=1.0,
                    status="approved",
                )
                if grandparent_id:
                    ancestor_kp.parent_id = grandparent_id
                db.add(ancestor_kp)
                await db.flush()
                parent_id = ancestor_kp.id

    # level: number of /-separated segments
    level = kp_path.count("/") + 1

    kp = KnowledgePoint(
        name=candidate.canonical_name,
        canonical_name=candidate.canonical_name,
        path=kp_path,
        level=level,
        description=candidate.definition,
        source=candidate.source,
        confidence=candidate.confidence,
        status="approved",
        created_from_question_id=candidate.source_question_id,
    )
    if parent_id:
        kp.parent_id = parent_id

    db.add(kp)
    await db.flush()

    # Transfer QuestionKnowledgeCandidate links → QuestionKnowledgePoint
    for link in candidate.question_links:
        ex = await db.execute(select(QuestionKnowledgePoint).where(
            QuestionKnowledgePoint.question_id == link.question_id,
            QuestionKnowledgePoint.knowledge_point_id == kp.id))
        if not ex.scalar_one_or_none():
            db.add(QuestionKnowledgePoint(
                question_id=link.question_id,
                knowledge_point_id=kp.id,
                weight=link.weight,
                is_primary=link.is_primary,
                source="candidate"))
        # Remove the old candidate link — transfer is complete
        await db.delete(link)

    candidate.status = "approved"
    await db.commit()
    await db.refresh(kp)
    return {"id": kp.id, "name": kp.name, "path": kp.path, "status": kp.status, "candidate_id": candidate.candidate_id}


# ──────────────────────────────────────────────
# POST /{candidate_id}/reject — Reject candidate
# ──────────────────────────────────────────────


@router.post("/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str,
    reason: str = Query("", description="Rejection reason"),
    db: AsyncSession = Depends(get_db),
):
    """Reject a knowledge point candidate."""
    query = select(KnowledgePointCandidate).where(
        KnowledgePointCandidate.candidate_id == candidate_id
    )
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Knowledge point candidate not found")

    if candidate.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject candidate with status '{candidate.status}'. Only 'pending' candidates can be rejected.",
        )

    candidate.status = "rejected"
    candidate.review_note = reason or None

    # Delete QuestionKnowledgeCandidate links — rejected candidates don't bind to questions
    qkc_del = await db.execute(
        select(QuestionKnowledgeCandidate).where(
            QuestionKnowledgeCandidate.knowledge_point_candidate_id == candidate.id
        )
    )
    for link in qkc_del.scalars().all():
        await db.delete(link)

    await db.commit()
    await db.refresh(candidate)

    return {
        "candidate_id": candidate.candidate_id,
        "status": candidate.status,
        "reason": reason or "No reason provided",
    }


# ──────────────────────────────────────────────
# POST /{candidate_id}/merge — Merge into existing KP
# ──────────────────────────────────────────────


@router.post("/{candidate_id}/merge")
async def merge_candidate(
    candidate_id: str,
    target: MergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Merge a candidate into an existing knowledge point as an alias."""
    query = select(KnowledgePointCandidate).where(
        KnowledgePointCandidate.candidate_id == candidate_id
    )
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Knowledge point candidate not found")

    if candidate.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot merge candidate with status '{candidate.status}'. Only 'pending' candidates can be merged.",
        )

    # Find target knowledge point
    target_kp = await db.get(KnowledgePoint, target.target_kp_id)
    if not target_kp:
        raise HTTPException(status_code=404, detail="Target knowledge point not found")

    # Create alias
    alias = KnowledgePointAlias(
        knowledge_point_id=target_kp.id,
        alias=candidate.canonical_name,
        source=candidate.source,
    )
    db.add(alias)

    # Transfer QuestionKnowledgeCandidate links → QuestionKnowledgePoint on target
    for link in candidate.question_links:
        ex = await db.execute(select(QuestionKnowledgePoint).where(
            QuestionKnowledgePoint.question_id == link.question_id,
            QuestionKnowledgePoint.knowledge_point_id == target_kp.id))
        if not ex.scalar_one_or_none():
            db.add(QuestionKnowledgePoint(
                question_id=link.question_id,
                knowledge_point_id=target_kp.id,
                weight=link.weight,
                is_primary=link.is_primary,
                source="merged"))
        # Remove the old candidate link — transfer is complete
        await db.delete(link)

    # Update candidate status
    candidate.status = "merged"
    candidate.merged_into_kp_id = target_kp.id

    await db.commit()

    return {
        "candidate_id": candidate.candidate_id,
        "status": "merged",
        "merged_into_kp_id": target_kp.id,
        "merged_into_kp_name": target_kp.name,
        "alias_created": candidate.canonical_name,
    }


# ──────────────────────────────────────────────
# PUT /{candidate_id} — Edit candidate
# ──────────────────────────────────────────────


@router.put("/{candidate_id}")
async def update_candidate(
    candidate_id: str,
    update: CandidateUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update editable fields on a knowledge point candidate."""
    query = (
        select(KnowledgePointCandidate)
        .options(selectinload(KnowledgePointCandidate.source_question))
        .where(KnowledgePointCandidate.candidate_id == candidate_id)
    )
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Knowledge point candidate not found")

    if update.canonical_name is not None:
        candidate.canonical_name = update.canonical_name
    if update.definition is not None:
        candidate.definition = update.definition
    if update.suggested_parent_path is not None:
        candidate.suggested_parent_path = update.suggested_parent_path

    await db.commit()
    await db.refresh(candidate)

    return _candidate_to_read(candidate)
