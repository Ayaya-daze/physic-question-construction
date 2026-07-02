"""Pydantic v2 schemas for Question and related models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TypeVar

from pydantic import AliasChoices, BaseModel, Field, field_validator

# ──────────────────────────────────────────────
# ChoiceOption schemas
# ──────────────────────────────────────────────


class ChoiceOptionBase(BaseModel):
    """Base fields for a choice option."""

    option_label: str = Field(..., max_length=50)
    content: str
    is_correct: bool = False
    order_index: int = 0


class ChoiceOptionCreate(ChoiceOptionBase):
    """Schema for creating a choice option."""
    pass


class ChoiceOptionRead(ChoiceOptionBase):
    """Schema for reading a choice option."""

    id: int
    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# Answer schemas
# ──────────────────────────────────────────────


class AnswerBase(BaseModel):
    """Base fields for an answer."""

    answer_type: str = Field(..., max_length=20)
    content: str
    normalized_content: Optional[str] = None
    unit: Optional[str] = Field(None, max_length=20)
    significant_figures: Optional[int] = None


class AnswerCreate(AnswerBase):
    """Schema for creating an answer."""
    pass


class AnswerRead(AnswerBase):
    """Schema for reading an answer."""

    id: int
    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# SolutionStep schemas
# ──────────────────────────────────────────────


import re as _re

_BARE_LATEX_RE = _re.compile(r"\\[a-zA-Z]|[a-zA-Z)\]}][_^]\d|[_^]\{")

def _ensure_math_delimiters(value: str) -> str:
    """Wrap bare LaTeX math in ``$...$`` if not already inside math delimiters."""
    stripped = value.strip()
    if not stripped:
        return stripped
    # Already inside math delimiters — skip
    if (stripped.startswith("$") and stripped.endswith("$")) or \
       (stripped.startswith("\\(") and stripped.endswith("\\)")) or \
       (stripped.startswith("\\[") and stripped.endswith("\\]")):
        return value
    if _BARE_LATEX_RE.search(stripped):
        return f"${stripped}$"
    return value


class SolutionStepBase(BaseModel):
    """Base fields for a solution step."""

    step_order: int
    content: str
    formula: Optional[str] = None
    explanation: Optional[str] = None


class SolutionStepCreate(SolutionStepBase):
    """Schema for creating a solution step — auto-wraps bare LaTeX formulas."""

    @field_validator("formula", mode="after")
    @classmethod
    def wrap_bare_formula(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _ensure_math_delimiters(v)


class SolutionStepRead(SolutionStepBase):
    """Schema for reading a solution step."""

    id: int
    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# KnowledgePoint / Tag reference schemas
# ──────────────────────────────────────────────


class KnowledgePointRef(BaseModel):
    """Reference to a knowledge point by path."""

    path: str
    weight: float = 1.0
    is_primary: bool = True


class TagRef(BaseModel):
    """Reference to a tag by name."""

    name: str


# ──────────────────────────────────────────────
# Question schemas
# ──────────────────────────────────────────────


class QuestionBase(BaseModel):
    """Base fields for a question."""

    stem: str
    question_type: str = Field(..., max_length=25)  # 25 chars fits "pending_classification"
    normalized_stem: Optional[str] = None
    difficulty: int = Field(default=3, ge=0, le=10)  # 0 = unassessed / needs human review
    grade: Optional[str] = Field(None, max_length=50)
    semester: Optional[str] = Field(None, max_length=50)
    textbook_version: Optional[str] = Field(None, max_length=50)
    chapter: Optional[str] = Field(None, max_length=100)
    score: Optional[float] = None
    estimated_time_seconds: Optional[int] = None
    source_document_id: Optional[str] = Field(None, max_length=50)
    source_page: Optional[int] = None
    source_region: Optional[list] = None
    source_crop_asset_id: Optional[str] = Field(None, max_length=50)
    metadata_json: Optional[dict] = None


class QuestionCreate(QuestionBase):
    """Schema for creating a question with nested entities."""

    options: list[ChoiceOptionCreate] = Field(
        default_factory=list,
        validation_alias=AliasChoices("options", "choice_options"),
    )
    answers: list[AnswerCreate] = []
    solution_steps: list[SolutionStepCreate] = []
    knowledge_points: list[KnowledgePointRef] = []
    tags: list[str] = []
    knowledge_point_mode: str = Field(
        default="candidate",
        description=(
            "How to handle knowledge point paths not found in the DB. "
            "'strict' — return 400 error; "
            "'candidate' — create a pending KnowledgePointCandidate (default); "
            "'force_create' — auto-create the KnowledgePoint as approved."
        ),
    )


class QuestionUpdate(BaseModel):
    """Schema for updating a question — all fields optional."""

    stem: Optional[str] = None
    question_type: Optional[str] = Field(None, max_length=20)
    normalized_stem: Optional[str] = None
    difficulty: Optional[int] = Field(None, ge=1, le=10)
    grade: Optional[str] = Field(None, max_length=50)
    semester: Optional[str] = Field(None, max_length=50)
    textbook_version: Optional[str] = Field(None, max_length=50)
    chapter: Optional[str] = Field(None, max_length=100)
    score: Optional[float] = None
    estimated_time_seconds: Optional[int] = None
    source_document_id: Optional[str] = Field(None, max_length=50)
    source_page: Optional[int] = None
    source_region: Optional[list] = None
    source_crop_asset_id: Optional[str] = Field(None, max_length=50)
    metadata_json: Optional[dict] = None
    status: Optional[str] = None
    options: Optional[list[ChoiceOptionCreate]] = Field(
        default=None,
        validation_alias=AliasChoices("options", "choice_options"),
    )
    answers: Optional[list[AnswerCreate]] = None
    solution_steps: Optional[list[SolutionStepCreate]] = None
    knowledge_points: Optional[list[KnowledgePointRef]] = None
    tags: Optional[list[str]] = None
    knowledge_point_mode: Optional[str] = Field(
        default=None,
        description=(
            "How to handle knowledge point paths not found in the DB. "
            "'strict' — return 400 error; "
            "'candidate' — create a pending KnowledgePointCandidate; "
            "'force_create' — auto-create the KnowledgePoint as approved."
        ),
    )


class QuestionRead(QuestionBase):
    """Schema for reading a full question."""

    id: int
    canonical_id: str
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    options: list[ChoiceOptionRead] = []
    choice_options: list[ChoiceOptionRead] = []
    answers: list[AnswerRead] = []
    solution_steps: list[SolutionStepRead] = []
    knowledge_points: list[KnowledgePointRef] = []
    tags: list[str] = []

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj):
        """Override to extract knowledge_point paths and tag names from ORM objects."""
        options = [
            ChoiceOptionRead.model_validate(opt) for opt in (obj.choice_options or [])
        ]
        data = {
            "id": obj.id,
            "canonical_id": obj.canonical_id,
            "status": obj.status,
            "stem": obj.stem,
            "question_type": obj.question_type,
            "normalized_stem": obj.normalized_stem,
            "difficulty": obj.difficulty,
            "grade": obj.grade,
            "semester": obj.semester,
            "textbook_version": obj.textbook_version,
            "chapter": obj.chapter,
            "score": obj.score,
            "estimated_time_seconds": obj.estimated_time_seconds,
            "source_document_id": obj.source_document_id,
            "source_page": obj.source_page,
            "source_region": obj.source_region,
            "source_crop_asset_id": obj.source_crop_asset_id,
            "created_by": obj.created_by,
            "metadata_json": obj.metadata_json,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
            "options": options,
            "choice_options": options,
            "answers": [AnswerRead.model_validate(ans) for ans in (obj.answers or [])],
            "solution_steps": [
                SolutionStepRead.model_validate(step) for step in (obj.solution_steps or [])
            ],
            "knowledge_points": [
                KnowledgePointRef(
                    path=qkp.knowledge_point.path if qkp.knowledge_point else "",
                    weight=qkp.weight,
                    is_primary=qkp.is_primary,
                )
                for qkp in (obj.question_knowledge_points or [])
            ],
            "tags": [tag.name for tag in (obj.tags or [])],
        }
        return cls(**data)


class QuestionList(BaseModel):
    """Schema for listing questions in a paginated view."""

    id: int
    canonical_id: str
    stem: str
    question_type: str
    difficulty: int
    grade: Optional[str] = None
    status: str
    knowledge_points: list[str] = []
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj):
        """Override to truncate stem and extract related data."""
        stem = obj.stem or ""
        truncated = stem[:200] + "..." if len(stem) > 200 else stem
        data = {
            "id": obj.id,
            "canonical_id": obj.canonical_id,
            "stem": truncated,
            "question_type": obj.question_type,
            "difficulty": obj.difficulty,
            "grade": obj.grade,
            "status": obj.status,
            "knowledge_points": [
                qkp.knowledge_point.path
                for qkp in (obj.question_knowledge_points or [])
                if qkp.knowledge_point
            ],
            "tags": [tag.name for tag in (obj.tags or [])],
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
        return cls(**data)


# ──────────────────────────────────────────────
# Search / Pagination schemas
# ──────────────────────────────────────────────


class QuestionSearchParams(BaseModel):
    """Query parameters for searching questions."""

    q: Optional[str] = None
    question_type: Optional[str] = None
    difficulty_min: Optional[int] = None
    difficulty_max: Optional[int] = None
    grade: Optional[str] = None
    status: Optional[str] = None
    knowledge_point_id: Optional[int] = None
    tag_id: Optional[int] = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


T = TypeVar("T")


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: list
    total: int
    skip: int
    limit: int


# ──────────────────────────────────────────────
# Status update schemas
# ──────────────────────────────────────────────

VALID_STATUSES = {"draft", "pending_review", "approved", "rejected", "archived"}


class StatusUpdate(BaseModel):
    """Schema for updating a question's status."""

    status: str

    @field_validator("status")
    @classmethod
    def check_valid_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
        return v
