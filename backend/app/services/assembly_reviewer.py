"""LLM review of assembled paper — checks completeness, balance, and quality.

Runs non-blocking after assembly: the paper is saved regardless of review.
Review results are stored in paper.metadata_json for the user to see.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class AssemblyReview:
    """Structured review output."""

    overall_score: int = 0  # 0-100
    summary: str = ""
    completeness_issues: list[str] = field(default_factory=list)
    balance_issues: list[str] = field(default_factory=list)
    quality_issues: list[str] = field(default_factory=list)
    layout_warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


# ── Rule-based layout checks (fast, no LLM cost) ───────────────

def _check_stem_length(stem: str, question_num: int) -> list[str]:
    """Check for stems that are too short or too long for paper layout."""
    issues: list[str] = []
    stripped = (stem or "").strip()
    if not stripped:
        issues.append(f"第{question_num}题：题目正文为空")
    elif len(stripped) < 15:
        issues.append(f"第{question_num}题：题目正文过短（{len(stripped)}字），可能不完整")
    elif len(stripped) > 2000:
        issues.append(f"第{question_num}题：题目正文过长（{len(stripped)}字），可能溢出页面")
    return issues


def _check_math_width(stem: str, question_num: int) -> list[str]:
    """Detect display math that may overflow page margins."""
    issues: list[str] = []
    # Find $$...$$ or \[...\] blocks
    for match in re.finditer(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", stem, re.DOTALL):
        formula = match.group(1) or match.group(2)
        if len(formula) > 120:
            issues.append(
                f"第{question_num}题：公式过长（{len(formula)}字符），" +
                f"可能在PDF中超出页面宽度"
            )
    return issues




def rule_based_review(
    paper_questions: list[dict],
    sections: list[dict],
) -> AssemblyReview:
    """Fast rule-based checks before LLM review.

    Args:
        paper_questions: list of {num, stem, question_type, difficulty, score, is_locked, section_name}
        sections: list of {name, question_type, count, score_each}
    """
    review = AssemblyReview()
    issues: list[str] = []
    layout_warnings: list[str] = []

    # ── Layout checks per question ──
    for pq in paper_questions:
        num = pq.get("num", 0)
        stem = pq.get("stem", "")
        assets = pq.get("assets_count", 0)
        layout_warnings.extend(_check_stem_length(stem, num))
        layout_warnings.extend(_check_math_width(stem, num))

    # ── Section balance check ──
    if sections:
        counts = [s.get("filled_count", 0) for s in sections]
        if len(counts) >= 2:
            min_c, max_c = min(counts), max(counts)
            if max_c > 0 and max_c - min_c > 5:
                issues.append(
                    f"题目分布不均匀：最少{min_c}题 vs 最多{max_c}题，建议调整"
                )

    # ── Difficulty balance check ──
    difficulties = [pq.get("difficulty", 0) for pq in paper_questions if pq.get("difficulty")]
    if difficulties:
        avg_diff = sum(difficulties) / len(difficulties)
        if avg_diff < 2:
            issues.append(f"整体难度偏低（平均 {avg_diff:.1f}/10），建议增加难题")
        elif avg_diff > 8:
            issues.append(f"整体难度偏高（平均 {avg_diff:.1f}/10），建议增加基础题")

    # ── Empty answer check ──
    empty_answers = [pq["num"] for pq in paper_questions if not pq.get("has_answers")]
    if empty_answers:
        issues.append(f"{len(empty_answers)} 道题目缺少答案：第 {', '.join(map(str, empty_answers[:5]))} 等")

    review.layout_warnings = layout_warnings
    review.completeness_issues = [i for i in issues if "缺少" in i or "空" in i]
    review.balance_issues = [i for i in issues if "不均匀" in i or "难" in i or "分布" in i]
    review.quality_issues = [i for i in issues if i not in review.completeness_issues and i not in review.balance_issues]

    return review


# ── LLM review prompt ─────────────────────────────────────────

REVIEW_SYSTEM_PROMPT = """You are reviewing a physics exam paper that was auto-assembled by a rule-based engine.

The paper has been assembled — questions are selected and placed into sections.
Your job is to review the ASSEMBLED RESULT for quality, not to create the paper.

Rate each dimension 0-100 and provide specific, actionable feedback in Chinese."""

REVIEW_USER_PROMPT = """Review this assembled physics exam paper.

## Paper Structure
{sections_summary}

## Assembled Questions
{questions_summary}

## Layout Warnings (from rule-based check)
{layout_warnings}

## Please evaluate:

### 1. 完整性 (Completeness)
- Are all sections filled to their target count?
- Do any questions have missing stems, missing answers, missing images?
- Score 0-100.

### 2. 难度平衡 (Difficulty Balance)
- Is the difficulty distribution appropriate for the paper's grade level?
- Are there too many easy or too many hard questions?
- Score 0-100.

### 3. 知识点覆盖 (Topic Coverage)
- Do the questions cover a reasonable range of the intended knowledge points?
- Are there topic gaps or over-representation?
- Score 0-100.

### 4. 排版适配 (Layout Fit)
- Are any question stems too long for a printed page (more than ~2000 Chinese characters)?
- Do any display math formulas exceed ~120 characters (may overflow page width)?
- Are images appropriately referenced?
- Score 0-100.

### 5. 整体评价 (Overall)
- Overall quality score 0-100.
- A one-sentence summary in Chinese.
- 2-3 specific suggestions for improvement.

Return ONLY a valid JSON object:
{{
  "overall_score": 85,
  "summary": "试卷整体质量良好...",
  "completeness_score": 90,
  "completeness_note": "第3题缺少答案",
  "difficulty_score": 80,
  "difficulty_note": "偏简单，可加一道竞赛级题目",
  "coverage_score": 75,
  "coverage_note": "热力学部分占比过高",
  "layout_score": 85,
  "layout_note": "第7题公式过长可能溢出",
  "suggestions": ["建议1", "建议2", "建议3"]
}}"""


async def llm_review_assembly(
    paper_questions: list[dict],
    sections: list[dict],
    layout_warnings: list[str],
    provider=None,
) -> dict | None:
    """Run LLM review on the assembled paper.  Returns review dict or None."""
    if provider is None:
        try:
            from app.services.llm import get_llm_provider
            provider = get_llm_provider()
        except Exception:
            return None  # LLM not configured — skip review

    # Summarize sections for the prompt
    section_lines = []
    for s in sections:
        section_lines.append(
            f"  - {s.get('name', '?')}：题型={s.get('question_type', '?')}，"
            f"需要{s.get('target_count', 0)}题，已填{s.get('filled_count', 0)}题，"
            f"每题{s.get('score_each', 0)}分"
        )
    sections_text = "\n".join(section_lines) if section_lines else "无分区"

    # Summarize questions (limited to avoid token overflow)
    q_lines = []
    for pq in paper_questions[:50]:  # cap at 50 questions
        stem_preview = (pq.get("stem", "") or "")[:120].replace("\n", " ")
        q_lines.append(
            f"  {pq.get('num', '?')}. [{pq.get('question_type', '?')}] "
            f"难度={pq.get('difficulty', '?')} 分数={pq.get('score', '?')} "
            f"分区={pq.get('section_name', '无')} "
            f"锁定={'是' if pq.get('is_locked') else '否'}\n"
            f"    题干: {stem_preview}..."
        )
    questions_text = "\n".join(q_lines) if q_lines else "无题目"
    if len(paper_questions) > 50:
        questions_text += f"\n  ... 共 {len(paper_questions)} 题，以上展示前 50 题"

    lw_text = "\n".join(f"  - {w}" for w in layout_warnings) if layout_warnings else "无排版警告"

    prompt = REVIEW_USER_PROMPT.format(
        sections_summary=sections_text,
        questions_summary=questions_text,
        layout_warnings=lw_text,
    )

    try:
        response = await provider.complete(
            prompt=prompt,
            system_prompt=REVIEW_SYSTEM_PROMPT,
            max_tokens=1024,
            temperature=0.0,
        )
        # Parse JSON from response
        content = response.content.strip()

        # Try markdown code fence
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try bare JSON object
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[0]
        except json.JSONDecodeError:
            pass
    except Exception:
        pass  # Review is optional — don't break assembly

    return None
