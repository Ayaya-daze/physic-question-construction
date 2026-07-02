"""Rule-based paper assembly engine.

Consumes a Paper + AssemblyConstraints and produces a list of PaperQuestion
records by scoring candidate questions against the constraints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Paper,
    PaperQuestion,
    PaperSection,
    Question,
    QuestionKnowledgePoint,
)
from app.models.question import question_tags

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Dataclasses for algorithm inputs / outputs
# ──────────────────────────────────────────────


@dataclass
class AssemblyConstraints:
    """Constraints that drive the paper assembly algorithm.

    Mirrors ``app.schemas.paper.AssemblyConstraints`` but stays a plain
    dataclass so the service does not couple to the API layer.
    """

    selected_question_ids: list[str] = field(default_factory=list)
    lock_selected_questions: bool = True
    knowledge_point_paths: list[str] = field(default_factory=list)
    use_llm_assist: bool = False  # reserved — not implemented
    use_semantic_search: bool = False  # reserved — not implemented
    natural_language_requirement: Optional[str] = None  # reserved
    difficulty_min: Optional[int] = None
    difficulty_max: Optional[int] = None
    exclude_recent_days: Optional[int] = None
    similarity_threshold: float = 0.86
    tag_filter: Optional[list[str]] = None
    include_answers: bool = True


@dataclass
class AssemblyResult:
    """Output of the paper assembly process."""

    paper_questions: list[PaperQuestion] = field(default_factory=list)
    unfilled_sections: list[dict] = field(default_factory=list)
    candidate_pool_size: int = 0
    selection_log: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# Scoring helpers
# ──────────────────────────────────────────────


def score_candidate(
    question: Question,
    kp_paths: list[str],
    target_difficulty: Optional[int] = None,
    tag_names: Optional[list[str]] = None,
) -> float:
    """Score a candidate question from 0 to 1 against the constraints.

    Scoring breakdown:

    * Knowledge-point match: +0.3 per matching path, capped at 0.6
    * Difficulty proximity: ``1 - abs(q.difficulty - target) / 4``, capped at 0.3
    * Tag overlap: +0.1 if any tag matches
    """
    score = 0.0

    # ── Knowledge point overlap (max +0.6) ──
    question_kp_paths: set[str] = {
        qkp.knowledge_point.path
        for qkp in (question.question_knowledge_points or [])
        if qkp.knowledge_point
    }
    kp_set = set(kp_paths)
    if kp_set and question_kp_paths:
        matches = kp_set & question_kp_paths
        score += min(len(matches) * 0.3, 0.6)

    # ── Difficulty proximity (max +0.3) ──
    if target_difficulty is not None:
        diff_proximity = 1.0 - abs(question.difficulty - target_difficulty) / 4.0
        if diff_proximity > 0:
            score += diff_proximity * 0.3

    # ── Tag overlap (+0.1) ──
    if tag_names:
        q_tags = {t.name for t in (question.tags or [])}
        tag_set = set(tag_names)
        if q_tags & tag_set:
            score += 0.1

    return min(score, 1.0)


def _check_pair_similarity(stem1: str, stem2: str, threshold: float = 0.86) -> bool:
    """Compare two stem strings by character-bigram overlap ratio."""
    if not stem1 or not stem2:
        return False

    s1, s2 = stem1.strip(), stem2.strip()

    def _bigrams(s: str) -> set[str]:
        return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

    b1, b2 = _bigrams(s1), _bigrams(s2)
    if not b2:
        return False

    intersection = b1 & b2
    ratio = len(intersection) / len(b2) if b2 else 0.0
    return ratio > threshold


# ──────────────────────────────────────────────
# Candidate fetching
# ──────────────────────────────────────────────


async def _fetch_approved_questions(
    db: AsyncSession,
    question_type: str,
    kp_paths: list[str],
    difficulty_min: Optional[int],
    difficulty_max: Optional[int],
) -> list[Question]:
    """Fetch approved questions matching the section type and optional filters.

    Filters are applied in order:
    1. Status = 'approved'
    2. question_type match
    3. Knowledge-point path match (via join if kp_paths provided)
    4. Difficulty range
    """
    stmt = select(Question).where(Question.status == "approved")

    if question_type:
        stmt = stmt.where(Question.question_type == question_type)

    if kp_paths:
        from app.models.knowledge_point import KnowledgePoint

        stmt = (
            stmt.join(
                QuestionKnowledgePoint,
                Question.id == QuestionKnowledgePoint.question_id,
            )
            .join(
                KnowledgePoint,
                QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
            )
            .where(KnowledgePoint.path.in_(kp_paths))
            .distinct()
        )

    if difficulty_min is not None:
        stmt = stmt.where(Question.difficulty >= difficulty_min)
    if difficulty_max is not None:
        stmt = stmt.where(Question.difficulty <= difficulty_max)

    stmt = stmt.options(
        selectinload(Question.question_knowledge_points).selectinload(QuestionKnowledgePoint.knowledge_point),
        selectinload(Question.tags),
        selectinload(Question.choice_options),
        selectinload(Question.answers),
        selectinload(Question.solution_steps),
    )

    result = await db.execute(stmt)
    questions = list(result.unique().scalars().all())
    return questions


# ──────────────────────────────────────────────
# Main assembly algorithm
# ──────────────────────────────────────────────


async def assemble_paper(
    db: AsyncSession,
    paper: Paper,
    constraints: AssemblyConstraints,
) -> AssemblyResult:
    """Rule-based paper assembly engine.

    Algorithm (10 steps from design doc):

    1. Lock manually selected questions into the paper
    2. For each section, calculate remaining slots
    3. Fetch approved candidates matching question_type + filters
    4. Exclude already-assigned questions
    5. Exclude questions used recently (if exclude_recent_days)
    6. Score each candidate by KP match, difficulty, tag overlap
    7. Greedy select highest-scoring candidates per section
    8. Mark any unfilled sections
    9. Assign sequential order_index across all sections
    10. Return AssemblyResult

    Parameters
    ----------
    db : AsyncSession
        An open async database session.
    paper : Paper
        The Paper ORM object (must have ``sections`` loaded).
    constraints : AssemblyConstraints
        The constraints that drive selection.

    Returns
    -------
    AssemblyResult
        The list of PaperQuestion objects, unfilled sections, and metadata.
    """
    selection_log: list[str] = []
    seen_question_ids: set[int] = set()
    locked_question_ids: set[int] = set()
    all_paper_questions: list[PaperQuestion] = []

    # Sort sections by order_index
    sections = sorted(paper.sections or [], key=lambda s: s.order_index or 0)

    def _section_used_count(section_id: int) -> int:
        return sum(
            1 for pq in all_paper_questions
            if pq.paper_section_id == section_id
        )

    def _choose_section_for_question(question: Question) -> PaperSection | None:
        """Pick the first matching section that still has room for this question.
        Returns None when no matching section exists or all are full."""
        matching = [s for s in sections if s.question_type == question.question_type]
        for section in matching:
            used = _section_used_count(section.id)
            if used < section.count:
                return section
        return None  # No section with room — don't overfill

    # Preserve already locked/manual questions on the draft.
    for pq in sorted(paper.questions or [], key=lambda item: item.order_index or 0):
        if pq.is_locked:
            if pq.question is not None:
                section = None
                if pq.paper_section_id is not None:
                    section = next((s for s in sections if s.id == pq.paper_section_id), None)
                if section is None:
                    section = _choose_section_for_question(pq.question)
                    if section is not None:
                        pq.paper_section_id = section.id
                if pq.score is None and section is not None:
                    pq.score = section.score_each
            seen_question_ids.add(pq.question_id)
            locked_question_ids.add(pq.question_id)
            all_paper_questions.append(pq)
            cid = pq.question.canonical_id if pq.question else pq.question_id
            selection_log.append(f"KEEP LOCKED: {cid}")

    # ── Step 1: Lock manually selected questions ──────────────────────────
    if constraints.selected_question_ids:
        for cid in constraints.selected_question_ids:
            q_result = await db.execute(
                select(Question)
                .where(Question.canonical_id == cid, Question.status == "approved")
                .options(
                    selectinload(Question.question_knowledge_points).selectinload(QuestionKnowledgePoint.knowledge_point),
                    selectinload(Question.tags),
                )
            )
            question = q_result.scalar_one_or_none()
            if question is None:
                selection_log.append(
                    f"SKIP locked q: {cid} not found or not approved"
                )
                continue

            if question.id in seen_question_ids:
                selection_log.append(f"KEEP SELECTED: {cid} already in paper")
                continue

            locked_question_ids.add(question.id)
            seen_question_ids.add(question.id)
            section = _choose_section_for_question(question)

            pq = PaperQuestion(
                paper_id=paper.id,
                question_id=question.id,
                paper_section_id=section.id if section else None,
                is_locked=constraints.lock_selected_questions,
                source_mode="manual",
                selection_reason="manual",
                order_index=len(all_paper_questions),
                score=section.score_each if section else question.score,
            )
            all_paper_questions.append(pq)
            selection_log.append(f"LOCKED: {cid} (id={question.id})")

    # ── Step 2-8: Fill each section ───────────────────────────────────────
    unfilled_sections: list[dict] = []

    for section in sections:
        # Count already-assigned questions in this section (any source mode)
        already_assigned = sum(
            1 for pq in all_paper_questions
            if pq.paper_section_id == section.id
        )
        needed = section.count - already_assigned
        if needed <= 0:
            selection_log.append(
                f"SECTION '{section.name}': already full "
                f"({already_assigned}/{section.count})"
            )
            continue

        selection_log.append(
            f"SECTION '{section.name}': need {needed} more question(s)"
        )

        # ── Step 3: Fetch candidates ──
        candidates = await _fetch_approved_questions(
            db,
            question_type=section.question_type,
            kp_paths=constraints.knowledge_point_paths,
            difficulty_min=constraints.difficulty_min,
            difficulty_max=constraints.difficulty_max,
        )

        selection_log.append(
            f"  candidate pool: {len(candidates)} questions"
        )

        # ── Step 4: Exclude already-assigned ──
        eligible = [q for q in candidates if q.id not in seen_question_ids]
        selection_log.append(
            f"  after dedup: {len(eligible)} eligible"
        )

        # ── Step 5: Exclude recently used ──
        if constraints.exclude_recent_days:
            cutoff = datetime.now(timezone.utc) - timedelta(
                days=constraints.exclude_recent_days
            )
            eligible = [
                q for q in eligible
                if q.updated_at is None or q.updated_at < cutoff
            ]
            selection_log.append(
                f"  after recency filter ({constraints.exclude_recent_days}d): "
                f"{len(eligible)} eligible"
            )

        # ── Step 6: Score candidates ──
        target_difficulty: Optional[int] = None
        if paper.difficulty_target is not None:
            target_difficulty = round(paper.difficulty_target)

        scored = [
            (
                score_candidate(
                    q,
                    constraints.knowledge_point_paths,
                    target_difficulty,
                    constraints.tag_filter,
                ),
                q,
            )
            for q in eligible
        ]
        # Sort descending by score
        scored.sort(key=lambda pair: pair[0], reverse=True)

        # ── Step 7: Greedy select ──
        selected: list[Question] = []
        for score_val, q in scored:
            if len(selected) >= needed:
                break

            # Skip zero-score candidates when constraints are active
            if score_val < 0.01 and (constraints.knowledge_point_paths or target_difficulty or constraints.tag_filter):
                selection_log.append(
                    f"  SKIP q{q.id} (score={score_val:.2f}): below minimum threshold"
                )
                continue

            # Step 7b: similarity check against already-selected questions
            too_similar = False
            for existing_q in selected:
                if _check_pair_similarity(
                    q.stem or "",
                    existing_q.stem or "",
                    constraints.similarity_threshold,
                ):
                    too_similar = True
                    selection_log.append(
                        f"  SKIP q{q.id} (score={score_val:.2f}): "
                        f"too similar to q{existing_q.id}"
                    )
                    break
            if too_similar:
                continue

            selected.append(q)
            selection_log.append(
                f"  SELECT q{q.id} (score={score_val:.2f}, "
                f"diff={q.difficulty}, type={q.question_type})"
            )

        # ── Step 8: Mark unfilled sections ──
        if len(selected) < needed:
            unfilled_sections.append({
                "section_id": section.id,
                "section_name": section.name,
                "needed": needed,
                "filled": len(selected),
                "shortfall": needed - len(selected),
            })
            selection_log.append(
                f"  UNFILLED: {section.name} got {len(selected)}/{needed}"
            )

        # Create PaperQuestion records
        for q in selected:
            seen_question_ids.add(q.id)
            pq = PaperQuestion(
                paper_id=paper.id,
                paper_section_id=section.id,
                question_id=q.id,
                is_locked=False,
                source_mode="rule_based",
                selection_reason="rule_based",
                order_index=0,  # assigned in step 9
                score=section.score_each,
            )
            all_paper_questions.append(pq)

    # ── Step 9: Assign sequential order_index ──
    for idx, pq in enumerate(all_paper_questions):
        pq.order_index = idx + 1

    # ── Step 10: Return result ──
    return AssemblyResult(
        paper_questions=all_paper_questions,
        unfilled_sections=unfilled_sections,
        candidate_pool_size=len(seen_question_ids),
        selection_log=selection_log,
    )
