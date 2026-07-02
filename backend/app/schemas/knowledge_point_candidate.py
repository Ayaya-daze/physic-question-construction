"""Pydantic v2 schemas for KnowledgePointCandidate and related models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# KnowledgePointCandidate schemas
# ──────────────────────────────────────────────


class KnowledgePointCandidateRead(BaseModel):
    """Schema for reading a knowledge point candidate."""

    id: int
    candidate_id: str
    canonical_name: str
    definition: Optional[str] = None
    suggested_parent_path: Optional[str] = None
    suggested_parent_id: Optional[int] = None
    confidence: float
    source: str
    status: str
    source_question_id: Optional[int] = None
    source_document_id: Optional[int] = None
    source_text_snippet: Optional[str] = None
    reviewer: Optional[str] = None
    review_note: Optional[str] = None
    merged_into_kp_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Nested source question info (if eager-loaded)
    source_question: Optional[dict] = None
    # {id, canonical_id, stem, question_type}

    model_config = {"from_attributes": True}


class KnowledgePointCandidateListResponse(BaseModel):
    """Paginated list response for knowledge point candidates."""

    items: list[KnowledgePointCandidateRead]
    total: int
    skip: int
    limit: int


class MergeRequest(BaseModel):
    """Request body for merging a candidate into an existing KP."""

    target_kp_id: int = Field(..., description="ID of the target KnowledgePoint to merge into")


class CandidateUpdateRequest(BaseModel):
    """Request body for updating a candidate's editable fields."""

    canonical_name: Optional[str] = Field(None, max_length=200)
    definition: Optional[str] = None
    suggested_parent_path: Optional[str] = Field(None, max_length=500)
