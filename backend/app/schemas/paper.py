"""Pydantic v2 schemas for Paper, PaperSection, PaperQuestion, and related models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

VALID_GENERATION_MODES = {"manual", "rule_based", "llm_assisted"}
VALID_PAPER_STATUSES = {"draft", "assembled", "exported", "archived"}
VALID_SOURCE_MODES = {"manual", "rule_based", "semantic_search", "llm_assisted"}
VALID_QUESTION_TYPES = {
    "single_choice", "multiple_choice", "fill_blank",
    "calculation", "experiment", "essay", "composite",
}
VALID_EXPORT_FORMATS = {"tex_pdf", "tex_only", "pdf_only"}
VALID_EXPORT_VARIANTS = {
    "paper_with_answers", "student_paper", "teacher_paper", "answer_only",
}
VALID_EXPORT_STATUSES = {"pending", "running", "succeeded", "partial", "failed"}


# ──────────────────────────────────────────────
# PaperSection schemas
# ──────────────────────────────────────────────


class PaperSectionCreate(BaseModel):
    """Schema for creating a paper section."""

    name: str = Field(..., max_length=100)
    question_type: str = Field(..., max_length=20)
    count: int = Field(..., ge=1, le=100)
    score_each: float = Field(..., gt=0)
    order_index: int = 0
    constraints_json: Optional[dict] = None

    @field_validator("question_type")
    @classmethod
    def check_question_type(cls, v: str) -> str:
        if v not in VALID_QUESTION_TYPES:
            raise ValueError(
                f"Invalid question_type '{v}'. Must be one of: {', '.join(sorted(VALID_QUESTION_TYPES))}"
            )
        return v


class PaperSectionRead(BaseModel):
    """Schema for reading a paper section."""

    id: int
    paper_id: int
    name: str
    question_type: str
    count: int
    score_each: float
    order_index: int
    constraints_json: Optional[dict] = None
    question_count: int = 0

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# PaperQuestion schemas
# ──────────────────────────────────────────────


class QuestionSummary(BaseModel):
    """Lightweight question reference embedded in PaperQuestionRead."""

    id: int
    canonical_id: str
    question_type: str
    stem: str
    difficulty: int
    grade: Optional[str] = None

    model_config = {"from_attributes": True}


class PaperQuestionRead(BaseModel):
    """Schema for reading a paper question with nested question info."""

    id: int
    paper_id: int
    paper_section_id: Optional[int] = None
    order_index: int
    score: Optional[float] = None
    is_locked: bool
    selection_reason: Optional[str] = None
    source_mode: str
    question: Optional[QuestionSummary] = None

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# AssemblyConstraints
# ──────────────────────────────────────────────


class AssemblyConstraints(BaseModel):
    """Constraints for paper assembly. This mirrors the Python dataclass
    described in the paper generator service but as a Pydantic model so it
    can be received via the API."""

    selected_question_ids: list[str] = []
    lock_selected_questions: bool = True
    knowledge_point_paths: list[str] = []
    use_llm_assist: bool = False
    use_semantic_search: bool = False
    natural_language_requirement: Optional[str] = None
    difficulty_min: Optional[int] = Field(None, ge=1, le=10)
    difficulty_max: Optional[int] = Field(None, ge=1, le=10)
    exclude_recent_days: Optional[int] = Field(None, ge=1)
    similarity_threshold: float = Field(default=0.86, ge=0.0, le=1.0)
    tag_filter: Optional[list[str]] = None
    include_answers: bool = True

    @field_validator("difficulty_max")
    @classmethod
    def check_difficulty_range(cls, v: Optional[int], info) -> Optional[int]:
        if v is not None and info.data.get("difficulty_min") is not None:
            if v < info.data["difficulty_min"]:
                raise ValueError("difficulty_max must be >= difficulty_min")
        return v


# ──────────────────────────────────────────────
# ValidationReport
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# AssemblyResult
# ──────────────────────────────────────────────


class AssemblyResult(BaseModel):
    """Result of the paper assembly process."""

    paper_questions: list[PaperQuestionRead] = []
    unfilled_sections: list[dict] = []
    candidate_pool_size: int = 0
    selection_log: list[str] = []
    validation_report: Optional[dict] = None  # reserved for future validation logic
    # Direct fields from API endpoint return
    job_id: str = ""
    paper_id: str = ""
    status: str = ""
    total_questions: int = 0
    total_score: float = 0.0
    sections_filled: int = 0
    errors: list[str] = []


# ──────────────────────────────────────────────
# Paper schemas
# ──────────────────────────────────────────────


class PaperCreate(BaseModel):
    """Schema for creating a paper."""

    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    total_score: Optional[float] = None
    duration_minutes: Optional[int] = Field(None, ge=1)
    grade: Optional[str] = Field(None, max_length=50)
    difficulty_target: Optional[float] = Field(None, ge=1.0, le=5.0)
    generation_mode: str = "rule_based"
    include_answers: bool = True
    constraints: Optional[AssemblyConstraints] = None
    sections: list[PaperSectionCreate] = []

    @field_validator("generation_mode")
    @classmethod
    def check_generation_mode(cls, v: str) -> str:
        if v not in VALID_GENERATION_MODES:
            raise ValueError(
                f"Invalid generation_mode '{v}'. Must be one of: {', '.join(sorted(VALID_GENERATION_MODES))}"
            )
        return v


class PaperUpdate(BaseModel):
    """Schema for updating a paper — all fields optional."""

    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    total_score: Optional[float] = None
    duration_minutes: Optional[int] = Field(None, ge=1)
    grade: Optional[str] = Field(None, max_length=50)
    difficulty_target: Optional[float] = Field(None, ge=1.0, le=5.0)
    generation_mode: Optional[str] = None
    status: Optional[str] = None
    include_answers: Optional[bool] = None
    constraints: Optional[AssemblyConstraints] = None
    validation_result_json: Optional[dict] = None
    sections: Optional[list[PaperSectionCreate]] = None


class PaperRead(BaseModel):
    """Schema for reading a paper in list views."""

    id: int
    paper_id: str
    title: str
    description: Optional[str] = None
    total_score: Optional[float] = None
    duration_minutes: Optional[int] = None
    grade: Optional[str] = None
    difficulty_target: Optional[float] = None
    generation_mode: str
    status: str
    include_answers: bool
    constraints_json: Optional[dict] = None
    validation_result_json: Optional[dict] = None
    sections: list[PaperSectionRead] = []
    section_count: int = 0
    question_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaperDetail(BaseModel):
    """Schema for reading a full paper with all nested data."""

    id: int
    paper_id: str
    title: str
    description: Optional[str] = None
    total_score: Optional[float] = None
    duration_minutes: Optional[int] = None
    grade: Optional[str] = None
    difficulty_target: Optional[float] = None
    generation_mode: str
    status: str
    include_answers: bool
    constraints_json: Optional[dict] = None
    validation_result_json: Optional[dict] = None
    sections: list[PaperSectionRead] = []
    questions: list[PaperQuestionRead] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# Pagination
# ──────────────────────────────────────────────


class PaginatedPaperResponse(BaseModel):
    """Paginated response for paper listing."""

    items: list[PaperRead]
    total: int
    skip: int
    limit: int


# ──────────────────────────────────────────────
# PaperQuestion update / replace schemas
# ──────────────────────────────────────────────


class AddQuestionRequest(BaseModel):
    """Schema for adding a question to a paper (API-alias for PaperQuestionCreate)."""

    question_id: Optional[int] = None
    canonical_id: Optional[str] = None
    section_id: Optional[int] = None
    order_index: Optional[int] = None
    score: Optional[float] = None
    is_locked: bool = True
    selection_reason: Optional[str] = None
    source_mode: str = "manual"


class UpdatePaperQuestionRequest(BaseModel):
    """Schema for updating a question's placement in a paper."""

    is_locked: Optional[bool] = None
    score: Optional[float] = None
    section_id: Optional[int] = None
    order_index: Optional[int] = None


class ReplaceQuestionRequest(BaseModel):
    """Schema for replacing a question in a paper (API-alias for PaperQuestionReplace)."""

    new_question_id: Optional[int] = None
    canonical_id: Optional[str] = None
    selection_reason: Optional[str] = "manual"


# ──────────────────────────────────────────────
# Export schemas
# ──────────────────────────────────────────────


class ExportRequest(BaseModel):
    """Schema for requesting a paper export."""

    format: str = "tex_pdf"
    variant: str = "paper_with_answers"
    template_id: str = "default_general_physics"
    latex_engine: str = "xelatex"

    @field_validator("format")
    @classmethod
    def check_format(cls, v: str) -> str:
        if v not in VALID_EXPORT_FORMATS:
            raise ValueError(
                f"Invalid format '{v}'. Must be one of: {', '.join(sorted(VALID_EXPORT_FORMATS))}"
            )
        return v

    @field_validator("variant")
    @classmethod
    def check_variant(cls, v: str) -> str:
        if v not in VALID_EXPORT_VARIANTS:
            raise ValueError(
                f"Invalid variant '{v}'. Must be one of: {', '.join(sorted(VALID_EXPORT_VARIANTS))}"
            )
        return v

    @field_validator("latex_engine")
    @classmethod
    def check_latex_engine(cls, v: str) -> str:
        if v not in ("xelatex", "lualatex", "pdflatex"):
            raise ValueError(f"Invalid latex_engine '{v}'. Must be one of: xelatex, lualatex, pdflatex")
        return v


class ExportJobRead(BaseModel):
    """Schema for reading an export job — separate question and answer outputs."""

    id: int
    export_id: str
    paper_id: str = ""  # paper_id string for external API
    format: str
    variant: str
    template_id: str
    latex_engine: str
    status: str

    # ── Questions paper outputs ──
    questions_tex_path: Optional[str] = None
    questions_pdf_path: Optional[str] = None
    questions_build_log_preview: Optional[str] = None

    # ── Answers paper outputs ──
    answers_tex_path: Optional[str] = None
    answers_pdf_path: Optional[str] = None
    answers_build_log_preview: Optional[str] = None

    # ── Legacy compat fields ──
    tex_path: Optional[str] = None
    pdf_path: Optional[str] = None
    build_log_preview: Optional[str] = None

    assets_dir: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# Generation job schemas
# ──────────────────────────────────────────────

