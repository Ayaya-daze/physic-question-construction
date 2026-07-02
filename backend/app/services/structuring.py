"""LLM structuring pipeline — converts parsed text into QuestionCreate candidates.

The pipeline:
1. Segment parsed text into candidate question blocks
2. Build LLM prompt with JSON Schema + knowledge point tree
3. Call LLM (if enabled) to structure each candidate
4. Parse and validate LLM responses
5. Return CandidateQuestion list
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Optional

from app.services.llm import LLMNotConfiguredError, LLMProvider, get_llm_provider
from app.services.parsers import ParsedDocument


# ──────────────────────────────────────────────
# Question segmentation (heuristic, pre-LLM)
# ──────────────────────────────────────────────

# Chinese + English question number patterns.
# NOTE: The paren-wrapped pattern r"[（\(](\d+)[）\)]" is INTENTIONALLY OMITTED.
# In Chinese physics exams, (1)/(2)/(3) are standard sub-question markers within a
# single composite problem.  Splitting on them produces orphaned half-questions
# that the LLM then treats as independent — breaking the parent problem.
QUESTION_NUMBER_PATTERNS = [
    # "1.", "1、", "1）" (trailing-paren AFTER the number = top-level)
    r"(?:^|\n)\s*(\d+)[\.、）\)]\s*",
    # "例1", "例1：", "例1."
    r"(?:^|\n)\s*例\s*(\d+)[\.、：:]",
    # "第1题"
    r"(?:^|\n)\s*第\s*(\d+)\s*题",
]


def _segment_into_question_blocks(text: str) -> list[str]:
    """Split raw text into candidate question blocks using regex heuristics.

    Returns a list of text blocks, each potentially a single question.
    Does NOT split on sub-question markers ``(1)/(2)/(3)`` — those are part
    of a single composite parent question.
    """
    # Quick guard: if the text contains multiple (1)/(2)/(3) sub-question
    # markers but NO top-level question number, keep it as one composite block.
    _SUB_Q_RE = re.compile(r"[（\(](\d+)[）\)]")
    sub_q_matches = _SUB_Q_RE.findall(text)
    if len(sub_q_matches) >= 2:
        # Check whether the text before the first sub-question marker
        # looks like a complete problem stem (not a top-level number).
        first_pos = text.find(f"({sub_q_matches[0]})")
        if first_pos == -1:
            first_pos = text.find(f"（{sub_q_matches[0]}）")
        preamble = text[:first_pos].strip() if first_pos >= 0 else ""
        if len(preamble) > 10:
            # The preamble is a genuine stem, not a question-number prefix.
            # Keep the whole text together as one composite question.
            return [text]

    # Try each pattern and use the one that produces the most reasonable segments
    best_segments: list[str] = [text]  # Default: treat as single question

    for pattern in QUESTION_NUMBER_PATTERNS:
        splits = re.split(pattern, text)
        if len(splits) <= 2:
            continue

        # Reconstruct: splits alternates [before_match, number, content, number, content, ...]
        segments: list[str] = []
        # First element is text before first question number
        preamble = splits[0].strip()
        if len(preamble) > 20:  # Non-trivial preamble
            segments.append(preamble)

        # Walk through [number, content] pairs
        for i in range(1, len(splits) - 1, 2):
            num = splits[i]
            content = splits[i + 1] if i + 1 < len(splits) else ""
            segment = f"{num}. {content.strip()}"
            if len(segment) > 20:  # Non-trivial question
                segments.append(segment)

        if len(segments) > len(best_segments):
            best_segments = segments

    return best_segments


# ──────────────────────────────────────────────
# LLM System Prompt
# ──────────────────────────────────────────────

PHYSICS_STRUCTURING_SYSTEM_PROMPT = """You are an expert physics exam question parser for physics (any domain, any level — from middle school to graduate physics).

Your task is to extract physics questions from text and format them as structured JSON.

## Critical Anti-Hallucination Rules

1. **NEVER invent answers.** If an answer is not explicitly and clearly present in the source text, leave the `answers` array EMPTY and add "answer" to `needs_review`. Do not derive, calculate, or guess answers.

2. **Do NOT guess garbled OCR text.** If OCR text is garbled or unclear (strange characters, broken symbols, unreadable formulas), mark the question with `needs_review: ["ocr_quality"]` and preserve the garbled text as-is. NEVER try to reconstruct or "correct" garbled formulas by guessing what the original text was.

3. **Preserve formulas exactly.** Copy all formulas verbatim from the source. Do not "fix" malformed LaTeX. If a formula appears garbled, leave it garbled and flag it.

4. **If you cannot confidently determine the question type**, use `"pending_classification"`. Do not guess.

5. **If you cannot determine difficulty**, use 0 (unassessed) instead of inventing a value.

## Question Type Identification

- `single_choice` — 单选题 (one correct option from A/B/C/D)
- `multiple_choice` — 多选题 (one or more correct options)
- `fill_blank` — 填空题 (fill in the blank)
- `calculation` — 计算题 (requires numerical calculation)
- `experiment` — 实验题 (experiment-based)
- `essay` — 简答题 (short answer/essay)
- `composite` — 综合题 (multi-part question with sub-questions labeled (1), (2), (3), etc.)
- `pending_classification` — use this when the type is ambiguous; do NOT guess `calculation`.

## Composite / Multi-Part Questions — CRITICAL

Chinese physics problems FREQUENTLY contain sub-parts labeled (1), (2), (3) or (a), (b), (c) within a single parent problem. These MUST be treated as ONE question with `question_type: "composite"`, NOT split into separate entries in the output array.

BAD (wrong — splits sub-questions):
```json
[
  {"question": {"stem": "A ball is thrown... (1) Find maximum height.", "question_type": "calculation"}},
  {"question": {"stem": "(2) Find the range.", "question_type": "calculation"}},
  {"question": {"stem": "(3) Find time of flight.", "question_type": "calculation"}}
]
```

GOOD (correct — keeps sub-questions together):
```json
[
  {"question": {
    "stem": "A ball is thrown at 30° at 20 m/s. (1) Find the maximum height. (2) Find the range. (3) Find the time of flight.",
    "question_type": "composite",
    "difficulty": 3
  }}
]
```

A composite question keeps the ENTIRE original problem stem — including all sub-parts (1), (2), (3) — in a SINGLE question object. If you see consecutive sub-parts labeled (1), (2), (3) that clearly belong to the same parent problem, output exactly ONE object with `question_type: "composite"`.

## Difficulty Scale (1-5)

- 1: Basic — simple definition/concept recall
- 2: Easy — single-step application
- 3: Medium — multi-step application
- 4: Hard — complex reasoning or multi-concept
- 5: Advanced — competition/graduate level

## Knowledge Concepts

From the question content, discover knowledge concepts. For each concept, suggest: name, brief definition, suggested parent concept (if any), and confidence (0-1). Output these in a `concepts` array alongside the question.

## Flagging Uncertainty

Use `warnings[]` and `needs_review[]` fields for anything uncertain. Be liberal with these flags.

## Output Format

Return ONLY a valid JSON array (no markdown, no explanation):

```json
[
  {
    "question": {
      "question_type": "single_choice",
      "stem": "Complete question stem text...",
      "difficulty": 3,
      "grade": "大学本科",
      "options": [
        {"option_label": "A", "content": "Option content", "is_correct": false}
      ],
      "answers": [
        {"answer_type": "choice", "content": "B"}
      ],
      "solution_steps": [
        {"step_order": 1, "content": "Solution step explanation", "formula": "$F=ma$"}
      ],
      "knowledge_points": [
        {"path": "Mechanics/Kinematics/Uniformly Accelerated Linear Motion", "is_primary": true, "weight": 1.0}
      ],
      "tags": ["kinematics"],
      "score": 5
    },
    "confidence": 0.85,
    "concepts": [
      {
        "name": "Newton's Second Law",
        "definition": "The acceleration of an object is directly proportional to the net force acting on it and inversely proportional to its mass: F = ma.",
        "suggested_parent_path": "Mechanics/Newton's Laws",
        "confidence": 0.9,
        "synonyms": ["F=ma", "Newton's 2nd Law", "牛顿第二定律"]
      }
    ],
    "warnings": ["Option D may span pages"],
    "needs_review": ["difficulty", "knowledge_points"],
    "source_page": 1,
    "source_region": [100, 200, 500, 400]
  }
]
```

## Knowledge Point Tree

If a knowledge point tree is provided below, use it for reference when naming concepts, but feel free to suggest new concepts not in the tree:
{kp_tree}

## Important

- If the text contains multiple TOP-LEVEL questions, output multiple objects in the array.
- If the text contains sub-parts (1)/(2)/(3), keep them as ONE composite question — do NOT split.
- If the text is not a physics question, return an empty array [].
- Confidence < 0.5 means you are very uncertain about the extraction.
- Use `needs_review` to flag fields that need human verification.
- If the question type is ambiguous, use 'pending_classification' — do NOT guess 'calculation'."""


# ──────────────────────────────────────────────
# Main structuring function
# ──────────────────────────────────────────────

async def structure_questions(
    parsed: ParsedDocument,
    knowledge_point_paths: Optional[list[str]] = None,
    llm: Optional[LLMProvider] = None,
) -> list[dict]:
    """Convert a ParsedDocument into structured question candidates.

    Args:
        parsed: The parsed document from any format parser.
        knowledge_point_paths: Available knowledge point paths for the LLM to reference.
        llm: Optional LLM provider. If None, uses the configured provider.

    Returns:
        List of candidate dicts with keys: question (dict), confidence, warnings,
        needs_review, source_page, source_region.
    """
    text = parsed.all_text()

    # Check if the markdown parser already produced structured questions
    if parsed.metadata.get("parsed_questions"):
        candidates = []
        for i, q in enumerate(parsed.metadata["parsed_questions"]):
            candidates.append({
                "index": i,
                "question": q,
                "confidence": 0.95,
                "warnings": [],
                "needs_review": ["knowledge_points", "difficulty"] if not q.get("knowledge_points") else [],
                "source_page": 1,
                "source_region": None,
                "asset_refs": [],
            })
        return candidates

    # Segment text into candidate question blocks
    segments = _segment_into_question_blocks(text)

    # Try LLM structuring
    if llm is None:
        try:
            llm = get_llm_provider()
        except LLMNotConfiguredError:
            llm = None

    # If no LLM available, return raw segments as candidates
    if llm is None or isinstance(llm, type(None)):
        return _raw_segments_as_candidates(segments)

    try:
        # Build knowledge point tree string
        kp_tree = "\n".join(f"- {p}" for p in (knowledge_point_paths or []))
        if not kp_tree:
            kp_tree = "(No knowledge point tree loaded — suggest paths based on question content)"

        system_prompt = PHYSICS_STRUCTURING_SYSTEM_PROMPT.replace("{kp_tree}", kp_tree)

        # Process segments in batches
        all_candidates: list[dict] = []
        batch_size = 3  # Process up to 3 segments per LLM call
        batch_texts: list[str] = []
        batch_page_nums: list[Optional[int]] = []

        for i, segment in enumerate(segments):
            batch_texts.append(segment)
            # Determine page from context
            page_num = 1
            for p in parsed.pages:
                if segment[:50] in p.raw_text:
                    page_num = p.page_number
                    break
            batch_page_nums.append(page_num)

            if len(batch_texts) >= batch_size or i == len(segments) - 1:
                # Build user prompt
                user_prompt = "Extract physics questions from the following text:\n\n"
                for j, bt in enumerate(batch_texts):
                    user_prompt += f"--- Segment {j + 1} (page {batch_page_nums[j]}) ---\n{bt}\n\n"

                # Retry LLM call up to 3 times with backoff
                response = None
                for attempt in range(3):
                    try:
                        response = await llm.complete(
                            prompt=user_prompt,
                            system_prompt=system_prompt,
                            max_tokens=4096,
                            temperature=0.0,
                        )
                        break
                    except Exception:
                        if attempt < 2:
                            await asyncio.sleep(2.0 * (attempt + 1))
                        else:
                            response = None

                if response is not None:
                    # Parse JSON from response
                    candidates = _parse_llm_json_response(response.content)
                    for idx, candidate in enumerate(candidates):
                        if idx < len(batch_texts):
                            candidate["source_page"] = candidate.get("source_page") or batch_page_nums[idx]
                            candidate["index"] = len(all_candidates) + idx
                            all_candidates.append(candidate)
                        # Skip extra candidates beyond batch_texts — index is required
                else:
                    # Fall back to raw segments after all retries exhausted
                    for j, bt in enumerate(batch_texts):
                        all_candidates.append(_raw_segment_candidate(
                            bt, batch_page_nums[j], len(all_candidates)
                        ))

                batch_texts = []
                batch_page_nums = []

        return all_candidates

    except LLMNotConfiguredError:
        return _raw_segments_as_candidates(segments)
    except Exception:
        return _raw_segments_as_candidates(segments)


def _parse_llm_json_response(content: str) -> list[dict]:
    """Parse JSON from an LLM response that may contain markdown fences."""
    # Try markdown code fence first
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Try bare JSON array — but only if it looks like the whole response is JSON
    json_match = re.search(r"^\s*\[.*\]\s*$", content, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Not valid JSON — LLM refused, replied with text, or returned invalid format
    return []


def _raw_segments_as_candidates(segments: list[str]) -> list[dict]:
    """Convert raw text segments to candidate dicts without LLM structuring."""
    return [
        _raw_segment_candidate(seg, 1, i)
        for i, seg in enumerate(segments)
    ]


def _raw_segment_candidate(text: str, page: int, index: int) -> dict:
    """Create a raw candidate from unparsed text."""
    return {
        "index": index,
        "question": {
            "question_type": "pending_classification",
            "stem": text.strip(),
            "difficulty": 0,  # Unassessed — human must assign 1-5
            "options": [],
            "answers": [],
            "solution_steps": [],
            "knowledge_points": [],
            "tags": [],
        },
        "confidence": 0.3,
        "warnings": [
            "未使用LLM结构化，请人工整理",
            "Human review required for classification",
        ],
        "needs_review": ["question_type", "options", "answers", "solution_steps", "knowledge_points", "difficulty"],
        "source_page": page,
        "source_region": None,
        "asset_refs": [],
    }
