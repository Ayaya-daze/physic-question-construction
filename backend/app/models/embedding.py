"""SQLAlchemy model for question embeddings (vector representations for semantic search)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class QuestionEmbedding(Base):
    """A vector embedding of a specific text field from a question.

    Stored as JSON for SQLite compatibility. When running on PostgreSQL,
    replace the column type with pgvector's vector(N) for native vector
    operations.
    """

    __tablename__ = "question_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(20), nullable=False)
    vector: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    # Relationships
    question: Mapped["Question"] = relationship("Question", back_populates="embeddings")

    def __repr__(self) -> str:
        return (
            f"<QuestionEmbedding(id={self.id}, question_id={self.question_id}, "
            f"field={self.field_name!r}, model={self.embedding_model!r})>"
        )
