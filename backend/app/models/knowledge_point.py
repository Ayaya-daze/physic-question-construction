"""SQLAlchemy models for KnowledgePoint and Tag."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from app.database import Base
from app.models.question import question_tags


class KnowledgePoint(Base):
    """A hierarchical knowledge point / curriculum topic."""

    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    textbook_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    canonical_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="human", index=True)
    # source: human, llm, import, merged, seed
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(20), default="approved", index=True)
    # status: candidate, approved, rejected, merged
    created_from_question_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    definition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Self-referential relationship
    children: Mapped[list["KnowledgePoint"]] = relationship(
        "KnowledgePoint",
        backref=backref("parent", remote_side=[id]),
        lazy="selectin",
    )

    # Questions linked to this knowledge point
    question_knowledge_points: Mapped[list["QuestionKnowledgePoint"]] = relationship(
        "QuestionKnowledgePoint", back_populates="knowledge_point", cascade="all, delete-orphan", lazy="selectin"
    )

    # KnowledgePointCandidate where this KP is the suggested parent
    candidate_refs: Mapped[list["KnowledgePointCandidate"]] = relationship(
        "KnowledgePointCandidate",
        foreign_keys="KnowledgePointCandidate.suggested_parent_id",
        back_populates="suggested_parent",
        lazy="selectin",
    )

    # Aliases for this knowledge point
    aliases: Mapped[list["KnowledgePointAlias"]] = relationship(
        "KnowledgePointAlias", back_populates="knowledge_point", cascade="all, delete-orphan", lazy="selectin"
    )

    # Merge logs where this KP was merged from (source)
    merge_logs_from: Mapped[list["KnowledgePointMergeLog"]] = relationship(
        "KnowledgePointMergeLog", foreign_keys="KnowledgePointMergeLog.merged_from_id", lazy="selectin"
    )

    # Merge logs where this KP was merged to (target)
    merge_logs_to: Mapped[list["KnowledgePointMergeLog"]] = relationship(
        "KnowledgePointMergeLog", foreign_keys="KnowledgePointMergeLog.merged_to_id", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<KnowledgePoint(id={self.id}, path={self.path!r}, level={self.level})>"


class Tag(Base):
    """A flat tag for categorizing questions."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Questions with this tag
    questions: Mapped[list["Question"]] = relationship(
        "Question", secondary=question_tags, back_populates="tags", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name={self.name!r})>"
