"""SQLAlchemy models for extraction pipeline: SourceDocument, ExtractionJob, MediaAsset."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SourceDocument(Base):
    """An original source document uploaded by the user (PDF, image, DOCX, etc.)."""

    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # source_type: pdf, image, docx, tex, markdown, manual, generated
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    book_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    publisher: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    copyright_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    # Relationships
    extraction_jobs: Mapped[list["ExtractionJob"]] = relationship(
        "ExtractionJob", back_populates="source_document", cascade="all, delete-orphan", lazy="selectin"
    )
    media_assets: Mapped[list["MediaAsset"]] = relationship(
        "MediaAsset", back_populates="source_document", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<SourceDocument(id={self.id}, doc_id={self.document_id!r}, type={self.source_type!r})>"


class ExtractionJob(Base):
    """A single extraction/processing run on a source document."""

    __tablename__ = "extraction_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # job_type: parse, ocr, llm_structure, embedding
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # status: pending, running, completed, failed
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    input_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    source_document: Mapped[Optional["SourceDocument"]] = relationship(
        "SourceDocument", back_populates="extraction_jobs"
    )

    def __repr__(self) -> str:
        return f"<ExtractionJob(id={self.id}, job_id={self.job_id!r}, type={self.job_type!r}, status={self.status!r})>"


class MediaAsset(Base):
    """A binary asset (page image, cropped region, figure, formula image) extracted during processing."""

    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # asset_type: original_page, question_crop, figure, formula_image, table_image
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    region: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # [x1, y1, x2, y2]
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    # Relationships
    source_document: Mapped[Optional["SourceDocument"]] = relationship(
        "SourceDocument", back_populates="media_assets"
    )

    def __repr__(self) -> str:
        return f"<MediaAsset(id={self.id}, asset_id={self.asset_id!r}, type={self.asset_type!r})>"
