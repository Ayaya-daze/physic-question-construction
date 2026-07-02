"""API routes for knowledge point CRUD and hierarchy management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import KnowledgePoint, QuestionKnowledgePoint

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


class KnowledgePointCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    path: str = Field(..., min_length=1, max_length=500)
    parent_id: int | None = None
    description: str | None = None
    grade: str | None = None
    textbook_version: str | None = None


class KnowledgePointRead(BaseModel):
    id: int
    parent_id: int | None = None
    path: str
    name: str
    level: int = 1
    description: str | None = None
    grade: str | None = None
    textbook_version: str | None = None
    question_count: int = 0

    model_config = {"from_attributes": True}


class KnowledgePointTreeRead(KnowledgePointRead):
    children: list[KnowledgePointTreeRead] = []

    model_config = {"from_attributes": True}


# ── Tree helpers ─────────────────────────────────────────────────────


def _build_tree(
    nodes: list[KnowledgePoint],
    parent_id: int | None = None,
    level: int = 1,
) -> list[KnowledgePointTreeRead]:
    children = [n for n in nodes if n.parent_id == parent_id]
    result: list[KnowledgePointTreeRead] = []
    for child in sorted(children, key=lambda n: n.path or ""):
        sub = _build_tree(nodes, child.id, level + 1)
        result.append(KnowledgePointTreeRead(
            id=child.id,
            parent_id=child.parent_id,
            path=child.path or "",
            name=child.name or "",
            level=level,
            description=child.description,
            grade=child.grade,
            textbook_version=child.textbook_version,
            question_count=len(child.question_kps) if child.question_kps else 0,
            children=sub,
        ))
    return result


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/tree", response_model=list[KnowledgePointTreeRead])
async def get_knowledge_point_tree(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KnowledgePoint).order_by(KnowledgePoint.path))
    return _build_tree(list(result.scalars().all()))


@router.get("", response_model=list[KnowledgePointRead])
@router.get("/", response_model=list[KnowledgePointRead])
async def list_knowledge_points(
    parent_id: int | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(KnowledgePoint)
    if parent_id is not None:
        stmt = stmt.where(KnowledgePoint.parent_id == parent_id)
    if search:
        stmt = stmt.where(
            KnowledgePoint.path.ilike(f"%{search}%") |
            KnowledgePoint.name.ilike(f"%{search}%")
        )
    stmt = stmt.order_by(KnowledgePoint.path)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=KnowledgePointRead, status_code=201)
@router.post("/", response_model=KnowledgePointRead, status_code=201)
async def create_knowledge_point(
    data: KnowledgePointCreate,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.path == data.path)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="知识点路径已存在")
    kp = KnowledgePoint(
        name=data.name, path=data.path, parent_id=data.parent_id,
        description=data.description, grade=data.grade,
        textbook_version=data.textbook_version,
    )
    db.add(kp)
    await db.commit()
    await db.refresh(kp)
    return kp
