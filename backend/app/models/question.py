"""SQLAlchemy models for Question and its related entities."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Association table: questions <-> tags (many-to-many)
question_tags = Table(
    "question_tags",
    Base.metadata,
    Column("question_id", ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Question(Base):
    """A physics question with stem, metadata, and related entities."""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    question_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_stem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)
    grade: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    semester: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    textbook_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    chapter: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_time_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_document_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_region: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source_crop_asset_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    choice_options: Mapped[list["ChoiceOption"]] = relationship(
        "ChoiceOption", back_populates="question", cascade="all, delete-orphan", lazy="selectin"
    )
    answers: Mapped[list["Answer"]] = relationship(
        "Answer", back_populates="question", cascade="all, delete-orphan", lazy="selectin"
    )
    solution_steps: Mapped[list["SolutionStep"]] = relationship(
        "SolutionStep",
        back_populates="question",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SolutionStep.step_order",
    )
    question_knowledge_points: Mapped[list["QuestionKnowledgePoint"]] = relationship(
        "QuestionKnowledgePoint", back_populates="question", cascade="all, delete-orphan", lazy="selectin"
    )
    tags: Mapped[list["Tag"]] = relationship(
        "Tag", secondary=question_tags, back_populates="questions", lazy="selectin"
    )
    embeddings: Mapped[list["QuestionEmbedding"]] = relationship(
        "QuestionEmbedding", back_populates="question", cascade="all, delete-orphan", lazy="selectin"
    )
    # Entries in the bridge table QuestionKnowledgeCandidate (candidate KPs linked to this question)
    knowledge_point_candidates: Mapped[list["QuestionKnowledgeCandidate"]] = relationship(
        "QuestionKnowledgeCandidate", back_populates="question", cascade="all, delete-orphan", lazy="selectin"
    )

    # Candidate KPs that were directly spawned from this question (via source_question_id)
    spawned_kp_candidates: Mapped[list["KnowledgePointCandidate"]] = relationship(
        "KnowledgePointCandidate",
        foreign_keys="KnowledgePointCandidate.source_question_id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Question(id={self.id}, canonical_id={self.canonical_id!r}, type={self.question_type!r})>"


class ChoiceOption(Base):
    """A multiple-choice option associated with a question."""

    __tablename__ = "choice_options"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    option_label: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    # Relationship
    question: Mapped["Question"] = relationship("Question", back_populates="choice_options")


class Answer(Base):
    """An expected answer (numeric, text, or expression) for a question."""

    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    answer_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    significant_figures: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationship
    question: Mapped["Question"] = relationship("Question", back_populates="answers")


class SolutionStep(Base):
    """A single step in a solution walkthrough for a question."""

    __tablename__ = "solution_steps"
    __table_args__ = (
        UniqueConstraint("question_id", "step_order", name="uq_solution_step_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    formula: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship
    question: Mapped["Question"] = relationship("Question", back_populates="solution_steps")


class QuestionKnowledgePoint(Base):
    """Association between a question and a knowledge point with metadata."""

    __tablename__ = "question_knowledge_points"
    __table_args__ = (
        UniqueConstraint("question_id", "knowledge_point_id", name="uq_q_kp"),
    )

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(20), default="human")

    # Relationships
    question: Mapped["Question"] = relationship("Question", back_populates="question_knowledge_points")
    knowledge_point: Mapped["KnowledgePoint"] = relationship(
        "KnowledgePoint", back_populates="question_knowledge_points"
    )
