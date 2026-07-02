"""Models package — re-exports all ORM models for easy import."""

from app.models.question import (
    Answer,
    ChoiceOption,
    Question,
    QuestionKnowledgePoint,
    SolutionStep,
    question_tags,
)
from app.models.knowledge_point import KnowledgePoint, Tag
from app.models.knowledge_point_candidate import (
    KnowledgePointAlias,
    KnowledgePointCandidate,
    KnowledgePointMergeLog,
    QuestionKnowledgeCandidate,
)
from app.models.embedding import QuestionEmbedding
from app.models.extraction import ExtractionJob, MediaAsset, SourceDocument
from app.models.paper import (
    Paper,
    PaperExportArtifact,
    PaperGenerationJob,
    PaperQuestion,
    PaperSection,
)

__all__ = [
    "Question",
    "ChoiceOption",
    "Answer",
    "SolutionStep",
    "QuestionKnowledgePoint",
    "question_tags",
    "KnowledgePoint",
    "Tag",
    "KnowledgePointCandidate",
    "KnowledgePointAlias",
    "KnowledgePointMergeLog",
    "QuestionKnowledgeCandidate",
    "QuestionEmbedding",
    "SourceDocument",
    "ExtractionJob",
    "MediaAsset",
    "Paper",
    "PaperSection",
    "PaperQuestion",
    "PaperGenerationJob",
    "PaperExportArtifact",
]
