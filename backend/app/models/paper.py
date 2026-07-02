"""SQLAlchemy models for paper generation: Paper, PaperSection, PaperQuestion,
PaperGenerationJob, PaperExportArtifact."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Paper(Base):
    """A generated exam paper composed of sections and questions."""

    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    difficulty_target: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    generation_mode: Mapped[str] = mapped_column(String(20), default="rule_based")
    # generation_mode: manual, rule_based, llm_assisted
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # status: draft, assembled, exported, archived
    include_answers: Mapped[bool] = mapped_column(Boolean, default=True)
    constraints_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
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
    sections: Mapped[list["PaperSection"]] = relationship(
        "PaperSection", back_populates="paper", cascade="all, delete-orphan", lazy="selectin"
    )
    questions: Mapped[list["PaperQuestion"]] = relationship(
        "PaperQuestion", back_populates="paper", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Paper(id={self.id}, paper_id={self.paper_id!r}, title={self.title!r}, status={self.status!r})>"


class PaperSection(Base):
    """A section within a paper (e.g. multiple-choice, calculation, experiment)."""

    __tablename__ = "paper_sections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    question_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # question_type: single_choice, multiple_choice, fill_blank, calculation, experiment, essay, composite
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    score_each: Mapped[float] = mapped_column(Float, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    constraints_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    paper: Mapped["Paper"] = relationship("Paper", back_populates="sections")
    questions: Mapped[list["PaperQuestion"]] = relationship(
        "PaperQuestion", back_populates="section", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<PaperSection(id={self.id}, name={self.name!r}, type={self.question_type!r}, count={self.count})>"


class PaperQuestion(Base):
    """A question assigned to a paper, with ordering and scoring metadata."""

    __tablename__ = "paper_questions"
    __table_args__ = (
        UniqueConstraint("paper_id", "question_id", name="uq_paper_question"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    paper_section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("paper_sections.id", ondelete="SET NULL"), nullable=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    selection_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # selection_reason: manual, rule_based, semantic_search, llm_assisted
    source_mode: Mapped[str] = mapped_column(String(20), default="rule_based")
    # source_mode: manual, rule_based, semantic_search, llm_assisted
    replacement_of_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("paper_questions.id"), nullable=True
    )

    # Relationships
    paper: Mapped["Paper"] = relationship("Paper", back_populates="questions")
    section: Mapped[Optional["PaperSection"]] = relationship("PaperSection", back_populates="questions")
    question: Mapped["Question"] = relationship("Question")

    def __repr__(self) -> str:
        return (
            f"<PaperQuestion(id={self.id}, paper_id={self.paper_id}, "
            f"question_id={self.question_id}, order={self.order_index})>"
        )


class PaperGenerationJob(Base):
    """Tracks a paper generation job: constraint solving, candidate selection, LLM parsing."""

    __tablename__ = "paper_generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # status: pending, running, succeeded, failed
    input_constraints_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    candidate_question_ids_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    llm_parse_result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    paper: Mapped["Paper"] = relationship("Paper")

    def __repr__(self) -> str:
        return f"<PaperGenerationJob(id={self.id}, job_id={self.job_id!r}, status={self.status!r})>"


class PaperExportArtifact(Base):
    """A generated export artifact (TeX/PDF) for a paper."""

    __tablename__ = "paper_export_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    export_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    format: Mapped[str] = mapped_column(String(20), default="tex_pdf")
    # format: tex_pdf, tex_only, pdf_only
    variant: Mapped[str] = mapped_column(String(50), default="paper_with_answers")
    # variant: paper_with_answers, student_paper, teacher_paper, answer_only
    template_id: Mapped[str] = mapped_column(String(50), default="default_general_physics")
    latex_engine: Mapped[str] = mapped_column(String(20), default="xelatex")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # status: pending, running, succeeded, failed

    # ── Questions paper outputs ──
    questions_tex_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    questions_pdf_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    questions_build_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Answers paper outputs ──
    answers_tex_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    answers_pdf_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    answers_build_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Legacy single-file fields (kept for backward compat) ──
    tex_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    build_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    assets_dir: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    manifest_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    paper: Mapped["Paper"] = relationship("Paper")

    def __repr__(self) -> str:
        return (
            f"<PaperExportArtifact(id={self.id}, export_id={self.export_id!r}, "
            f"format={self.format!r}, status={self.status!r})>"
        )
