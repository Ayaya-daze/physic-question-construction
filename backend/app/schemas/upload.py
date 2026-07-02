"""Pydantic schemas for file upload, extraction jobs, and candidate questions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Source Document
# ──────────────────────────────────────────────

class SourceDocumentRead(BaseModel):
    document_id: str
    title: Optional[str] = None
    source_type: str
    original_filename: Optional[str] = None
    book_title: Optional[str] = None
    publisher: Optional[str] = None
    author: Optional[str] = None
    year: Optional[int] = None
    page_count: Optional[int] = None
    copyright_note: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceDocumentDetail(SourceDocumentRead):
    """Document detail including related jobs and assets."""
    extraction_jobs: list["ExtractionJobRead"] = []
    media_assets: list["MediaAssetRead"] = []


# ──────────────────────────────────────────────
# Extraction Job
# ──────────────────────────────────────────────

class ExtractionJobRead(BaseModel):
    job_id: str
    job_type: str
    status: str
    tool_name: Optional[str] = None
    model_name: Optional[str] = None
    error_message: Optional[str] = None
    candidate_count: int = 0
    created_at: datetime
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class ExtractionJobDetail(ExtractionJobRead):
    """Job detail including input/output snapshots."""
    input_snapshot: Optional[dict] = None
    output_snapshot: Optional[dict] = None


# ──────────────────────────────────────────────
# Media Asset
# ──────────────────────────────────────────────

class MediaAssetRead(BaseModel):
    asset_id: str
    asset_type: str
    file_path: str
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    page_number: Optional[int] = None
    region: Optional[list] = None

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# Candidate Question (extraction result)
# ──────────────────────────────────────────────

class CandidateQuestion(BaseModel):
    """A structured question candidate produced by parsing/OCR/LLM."""
    index: int = 0  # Default 0 for backward compat with LLM outputs missing this field
    question: dict  # QuestionCreate-compatible dict
    confidence: float = 1.0
    warnings: list[str] = []
    needs_review: list[str] = []
    source_page: Optional[int] = None
    source_region: Optional[list] = None  # [x1, y1, x2, y2]
    asset_refs: list[str] = []  # asset_ids for associated images


class CandidateUpdate(BaseModel):
    """Editable fields for a candidate question."""
    question: dict  # Updated QuestionCreate-compatible dict


class CandidateBatchApprove(BaseModel):
    """Batch approve request."""
    indices: list[int] = Field(min_length=1)


# ──────────────────────────────────────────────
# Upload Response
# ──────────────────────────────────────────────

class UploadResponse(BaseModel):
    document_id: str
    original_filename: str
    source_type: str
    jobs: list[ExtractionJobRead] = []


class UploadError(BaseModel):
    filename: str
    error: str


class MultiUploadResponse(BaseModel):
    documents: list[UploadResponse] = []
    errors: list[UploadError] = []
