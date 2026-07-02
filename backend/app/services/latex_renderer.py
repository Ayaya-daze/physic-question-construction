"""LaTeX renderer — renders a Paper to TeX source and compiles it to PDF."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import (
    MediaAsset,
    Paper,
    PaperQuestion,
    Question,
    QuestionKnowledgePoint,
)

logger = logging.getLogger(__name__)

_STEM_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
_QUESTIONS_DIR: Path = settings.questions_dir
_QUESTION_IMAGE_OPTIONS = r"width=0.65\linewidth,height=0.26\textheight,keepaspectratio"


# ──────────────────────────────────────────────
# TeX escaping and formatting helpers
# ──────────────────────────────────────────────

_TEX_SPECIAL_CHARS: dict[int, str] = {
    ord("\\"): r"\textbackslash{}",
    ord("&"): r"\&",
    ord("%"): r"\%",
    ord("$"): r"\$",
    ord("#"): r"\#",
    ord("_"): r"\_",
    ord("{"): r"\{",
    ord("}"): r"\}",
    ord("~"): r"\textasciitilde{}",
    ord("^"): r"\textasciicircum{}",
}


def _get_value(obj, attr: str, default: str = ""):
    """Read a value from either an ORM object or a dict."""
    if isinstance(obj, dict):
        value = obj.get(attr, default)
    else:
        value = getattr(obj, attr, default)
    return default if value is None else value


def _escape_tex(text: str) -> str:
    """Escape special TeX characters in plain text.

    Preserves content inside math delimiters (``$...$``, ``$$...$$``, ``\\(...\\)``,
    ``\\[...\\]``) and math environments (``\\begin{align}...\\end{align}``, etc.).
    """

    # Math environments whose content must NOT be escaped.
    # These are multi-line display environments where & is an alignment marker
    # and \\ is a line break — both break if escaped.
    _MATH_ENV_NAMES = (
        "align", "align*", "alignat", "alignat*",
        "equation", "equation*",
        "gather", "gather*",
        "multline", "multline*",
        "flalign", "flalign*",
        "split",
        "cases",
        "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
    )
    _ENV_PATTERN = (
        r"(\\begin\{(?:" + "|".join(_MATH_ENV_NAMES) + r")\}.*?\\end\{(?:" +
        "|".join(_MATH_ENV_NAMES) + r")\})"
    )

    # Regex: match math blocks — these are preserved verbatim, not escaped.
    # Group order: $$...$$ | $...$ | \[...\] | \(...\) | \begin{align}...\end{align} | ...
    _MATH_RE = re.compile(
        r"(\$\$.*?\$\$)"               # display math $$...$$
        r"|(\$[^$]+\$)"                # inline math $...$ (single $, no nested $$)
        r"|(\\\[.*?\\\])"              # display \[...\]
        r"|(\\\(.*?\\\))"              # inline \(...\)
        r"|(" + _ENV_PATTERN + r")",   # \begin{align}...\end{align} etc.
        re.DOTALL,
    )

    parts: list[str] = []
    last_end = 0
    for match in _MATH_RE.finditer(text):
        start, end = match.span()
        # Escape the non-math text before this math block
        if start > last_end:
            parts.append(text[last_end:start].translate(_TEX_SPECIAL_CHARS))
        # Preserve the math block verbatim
        parts.append(match.group(0))
        last_end = end

    # Escape any remaining non-math text after the last math block
    if last_end < len(text):
        remainder = text[last_end:]
        # If there's an unmatched $ somewhere in the remainder, don't eat the whole text.
        # Just escape normally — the $ will become \$ which is safe.
        parts.append(remainder.translate(_TEX_SPECIAL_CHARS))

    return "".join(parts)


def _render_formula(formula: str) -> str:
    """Wrap a formula string in appropriate TeX math delimiters.

    * If the formula contains ``\\begin{...}``, wraps in ``$$...$$`` (display mode).
    * If already wrapped, returns as-is.
    * Otherwise wraps in ``$...$`` (inline mode).
    """
    f = formula.strip()
    if not f:
        return ""
    if f.startswith("$") or f.startswith(r"\("):
        return f
    if "\\begin{" in f or "\\[" in f or "\\]" in f:
        return f"$${f}$$"
    return f"${f}$"


def _render_stem(stem: str) -> str:
    """Render a question stem for TeX.

    * Strips image markup.
    * Normalises ``\\(...\\)`` → ``$...$`` and ``\\[...\\]`` → ``$$...$$``.
    * Escapes TeX specials in non-math portions.
    """
    s = stem or ""

    # ── 1. Strip image markup ──
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", s)
    s = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]+\}", "", s)
    s = re.sub(r"<img[^>]*>", "", s, flags=re.IGNORECASE)

    # ── 2. Normalise LaTeX math delimiters ──
    s = re.sub(r"(?<!\\)\\\((.+?)(?<!\\)\\\)", r"$\1$", s)
    s = re.sub(r"(?<!\\)\\\[(.+?)(?<!\\)\\\]", r"$$\1$$", s, flags=re.DOTALL)

    # ── 3. Escape TeX (preserves $...$ and $$...$$ blocks) ──
    return _escape_tex(s)


def _render_options(options: list) -> str:
    """Render multiple-choice options as A. B. C. D. blocks in TeX.

    Parameters
    ----------
    options : list
        ORM ``ChoiceOption`` objects or dicts with ``option_label`` and ``content``.
    """
    if not options:
        return ""

    lines: list[str] = []
    lines.append(r"\begin{enumerate}[label=\Alph*.]")
    for opt in options:
        content = _get_value(opt, "content", "")
        lines.append(r"\item " + _escape_tex(content))
        lines.append(r"\vspace{2pt}")
    lines.append(r"\end{enumerate}")
    return "\n".join(lines)


def _render_answer(answers: list) -> str:
    """Render answer content for TeX.

    Parameters
    ----------
    answers : list
        ORM ``Answer`` objects or dicts with ``answer_type``, ``content``, and
        optional ``unit``.
    """
    if not answers:
        return ""

    lines: list[str] = []
    lines.append(r"\textbf{答案:}")
    for ans in answers:
        content = _get_value(ans, "content", "")
        unit = _get_value(ans, "unit", "")
        rendered = _render_stem(content)
        line = rendered
        if unit:
            line += f" ({_escape_tex(unit)})"
        lines.append(line)
    return "\n".join(lines)


def _render_solution(steps: list) -> str:
    """Render solution steps as a numbered list in TeX.

    Parameters
    ----------
    steps : list
        ORM ``SolutionStep`` objects sorted by ``step_order``, or dicts.
    """
    if not steps:
        return ""

    lines: list[str] = []
    lines.append(r"\textbf{解析:}")
    lines.append(r"\begin{enumerate}[label=\arabic*.]")
    for step in steps:
        content = _get_value(step, "content", "")
        formula = _get_value(step, "formula", "")
        explanation = _get_value(step, "explanation", "")

        lines.append(r"\item " + _escape_tex(content))
        if formula:
            lines.append(r"\par\noindent" + _render_formula(formula))
        if explanation:
            lines.append(r"\par\noindent\textit{" + _escape_tex(explanation) + "}")

        lines.append(r"\vspace{4pt}")
    lines.append(r"\end{enumerate}")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Image reference detection
# ──────────────────────────────────────────────

_IMG_PATTERN = re.compile(
    r'!\[[^\]]*\]\(([^)]+)\)'
    r'|\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}'
    r'|src\s*=\s*["\']([^"\']+)["\']'
    r'|\b([\w.-]+\.(?:png|jpg|jpeg|gif|pdf|svg|eps))\b',
    re.IGNORECASE,
)


def _extract_image_references(text: str) -> list[str]:
    """Extract image filenames from text content.

    Recognises Markdown ``![](path)``, ``\\includegraphics{path}``, HTML
    ``src="..."``, and bare filenames with image extensions.
    """
    names: list[str] = []
    for m in _IMG_PATTERN.finditer(text):
        for g in m.groups():
            if g:
                # Strip down to just the filename
                basename = Path(g).name
                names.append(basename)
    return names


# ──────────────────────────────────────────────
# Asset export
# ──────────────────────────────────────────────


async def export_assets(
    paper_questions: list[PaperQuestion],
    output_assets_dir: Path,
    db: AsyncSession,
) -> list[str]:
    """Export image assets referenced by questions in the paper.

    For each PaperQuestion:

    1. Scan stem, options, answers, solutions for image references.
    2. Look in ``questions/{canonical_id}/assets/`` for matching files.
    3. Copy found images to ``output_assets_dir/``.
    4. Also check ``media_asset`` records in the database.

    Parameters
    ----------
    paper_questions : list[PaperQuestion]
        Paper questions with their ``.question`` relationship loaded.
    output_assets_dir : Path
        Destination directory for assets (created if missing).
    db : AsyncSession
        Open async database session.

    Returns
    -------
    list[str]
        Absolute paths of every copied asset file.
    """
    output_assets_dir.mkdir(parents=True, exist_ok=True)
    copied: set[str] = set()

    for pq in paper_questions:
        question = pq.question
        if question is None:
            continue

        canonical_id = getattr(question, "canonical_id", None)
        if not canonical_id:
            continue

        # Collect all text blobs from the question
        text_parts: list[str] = [question.stem or ""]

        for opt in question.choice_options or []:
            text_parts.append(getattr(opt, "content", None) or "")
        for ans in question.answers or []:
            text_parts.append(getattr(ans, "content", None) or "")
        for step in question.solution_steps or []:
            text_parts.append(getattr(step, "content", None) or "")
            text_parts.append(getattr(step, "formula", None) or "")
            text_parts.append(getattr(step, "explanation", None) or "")

        # Extract referenced image filenames
        all_text = "\n".join(text_parts)
        refs = _extract_image_references(all_text)

        # Look in the question's assets directory
        question_assets_dir = _QUESTIONS_DIR / canonical_id / "assets"
        for ref_name in refs:
            src = question_assets_dir / ref_name
            if src.is_file():
                dst = output_assets_dir / ref_name
                dst_key = str(dst)
                if dst_key not in copied:
                    shutil.copy2(src, dst)
                    copied.add(dst_key)
                    logger.debug(f"Copied asset: {src} -> {dst}")

        # Check DB media_asset record referenced by the question crop id.
        if question.source_crop_asset_id:
            media_result = await db.execute(
                select(MediaAsset).where(MediaAsset.asset_id == question.source_crop_asset_id)
            )
            for media in media_result.scalars().all():
                asset_path = media.file_path
                if asset_path:
                    src = Path(asset_path)
                    if not src.is_absolute():
                        src = _STEM_DIR / src
                    if src.is_file():
                        dst = output_assets_dir / src.name
                        dst_key = str(dst)
                        if dst_key not in copied:
                            shutil.copy2(src, dst)
                            copied.add(dst_key)
                            logger.debug(f"Copied media asset: {src} -> {dst}")

    return sorted(copied)


# ──────────────────────────────────────────────
# Shared preamble builder
# ──────────────────────────────────────────────


def _build_preamble(title: str) -> list[str]:
    """Build the shared LaTeX preamble used by both questions and answers TeX files."""
    return [
        r"\documentclass[12pt,a4paper]{ctexart}",
        r"\usepackage{geometry}",
        r"\geometry{margin=2cm}",
        r"\usepackage{amsmath,amssymb}",
        r"\usepackage{graphicx}",
        r"\usepackage{enumitem}",
        r"\usepackage{fancyhdr}",
        r"\usepackage{float}",
        r"\graphicspath{{assets/}}",  # images copied into assets/ subdir of export dir
        r"\pagestyle{fancy}",
        r"\renewcommand{\headrulewidth}{0.4pt}",
        r"\setlength{\parindent}{0pt}",
        "",
        r"\begin{document}",
        "",
        r"\begin{center}",
        r"{\LARGE \textbf{" + _escape_tex(title) + r"}}",
        r"\end{center}",
        r"\vspace{1cm}",
        "",
    ]


def _render_image_block(image_refs: list[str]) -> list[str]:
    """Render image references in order as centered includegraphics blocks."""
    lines: list[str] = []
    for img_ref in image_refs:
        lines.append(r"\begin{center}")
        lines.append(
            rf"\includegraphics[{_QUESTION_IMAGE_OPTIONS}]"
            + r"{assets/" + Path(img_ref).name + r"}"
        )
        lines.append(r"\end{center}")
    return lines


async def _collect_image_refs(
    question: Question,
    db: AsyncSession,
) -> list[str]:
    """Collect all image references from a question's text fields, preserving order."""
    # Use dict for O(1) dedup while preserving insertion order (Python 3.7+)
    seen: dict[str, None] = {}

    def _add_refs(text: str) -> None:
        for ref in _extract_image_references(text):
            seen[ref] = None

    _add_refs(question.stem or "")
    for opt in question.choice_options or []:
        _add_refs(getattr(opt, "content", "") or "")
    for ans in question.answers or []:
        _add_refs(getattr(ans, "content", "") or "")
    for step in question.solution_steps or []:
        _add_refs(getattr(step, "content", "") or "")
        _add_refs(getattr(step, "formula", "") or "")
        _add_refs(getattr(step, "explanation", "") or "")
    if question.source_crop_asset_id:
        media_result = await db.execute(
            select(MediaAsset).where(MediaAsset.asset_id == question.source_crop_asset_id)
        )
        media = media_result.scalar_one_or_none()
        if media and media.file_path:
            seen[Path(media.file_path).name] = None

    return list(seen.keys())


# ──────────────────────────────────────────────
# Questions-only TeX renderer
# ──────────────────────────────────────────────


async def render_questions_to_tex(
    paper: Paper,
    paper_questions: list[PaperQuestion],
    db: AsyncSession,
) -> str:
    """Render a question-only paper to LaTeX source.

    Produces ``questions.tex`` — contains the paper title, section headers,
    question stems, and images. **No answers or solutions are included.**

    Parameters
    ----------
    paper : Paper
        The paper ORM object with ``sections`` loaded.
    paper_questions : list[PaperQuestion]
        Paper-question links with ``.question`` (and nested relationships) loaded.
    db : AsyncSession
        Open async database session.

    Returns
    -------
    str
        Complete LaTeX document containing only questions.
    """
    sorted_pqs = sorted(paper_questions, key=lambda pq: pq.order_index or 0)

    # Build section → questions map
    section_map: dict[int, list[PaperQuestion]] = {}
    unsectioned: list[PaperQuestion] = []
    for pq in sorted_pqs:
        if pq.paper_section_id:
            section_map.setdefault(pq.paper_section_id, []).append(pq)
        else:
            unsectioned.append(pq)

    paper_sections = sorted(paper.sections or [], key=lambda s: s.order_index or 0)

    # ── Build TeX ────────────────────────────────────────────────────────
    lines: list[str] = []
    title = paper.title or "物理试卷"
    lines.extend(_build_preamble(title))

    # Optional: duration / total score
    if paper.duration_minutes or paper.total_score:
        lines.append(r"\begin{center}")
        lines.append(r"\begin{tabular}{rl}")
        if paper.duration_minutes is not None:
            lines.append(
                rf"  \textbf{{{_escape_tex('时长:')}}} & {paper.duration_minutes} 分钟 \\"
            )
        if paper.total_score is not None:
            lines.append(
                rf"  \textbf{{{_escape_tex('总分:')}}} & {paper.total_score} 分 \\"
            )
        lines.append(r"\end{tabular}")
        lines.append(r"\end{center}")
        lines.append(r"\vspace{0.5cm}")
        lines.append("")

    # ── Render each section ──────────────────────────────────────────────
    for section in paper_sections:
        lines.append(r"\section*{" + _escape_tex(section.name) + "}")
        lines.append("")

        sqs = section_map.get(section.id, [])
        if not sqs:
            lines.append(r"\textit{（本部分暂无题目）}")
            lines.append("")
            continue

        lines.append(r"\begin{enumerate}[resume]")

        for pq in sorted(sqs, key=lambda x: x.order_index or 0):
            question = pq.question
            if question is None:
                continue

            score = pq.score if pq.score else section.score_each

            # Question stem with score
            stem_text = _render_stem(question.stem or "")
            if not question.stem or not question.stem.strip():
                stem_text = r"\textit{" + _escape_tex("（题目正文缺失）") + "}"
            lines.append(
                r"\item "
                + f"({score}" + _escape_tex("分") + ") "
                + stem_text
            )

            # Choice options (if any) — NO answer marking
            if question.choice_options:
                lines.append(
                    _render_options(
                        sorted(question.choice_options, key=lambda o: o.order_index or 0)
                    )
                )

            # Images referenced in the question stem/options only
            # (answers/solutions images go in answers.tex)
            stem_refs: dict[str, None] = {}
            for ref in _extract_image_references(question.stem or ""):
                stem_refs[ref] = None
            for opt in question.choice_options or []:
                for ref in _extract_image_references(getattr(opt, "content", "") or ""):
                    stem_refs[ref] = None

            if question.source_crop_asset_id:
                media_result = await db.execute(
                    select(MediaAsset).where(MediaAsset.asset_id == question.source_crop_asset_id)
                )
                media = media_result.scalar_one_or_none()
                if media and media.file_path:
                    stem_refs[Path(media.file_path).name] = None

            lines.extend(_render_image_block(list(stem_refs.keys())))

            lines.append(r"\vspace{0.5cm}")
            lines.append("")

        lines.append(r"\end{enumerate}")
        lines.append("")

    # ── Unsectioned questions ────────────────────────────────────────────
    if unsectioned:
        lines.append(r"\section*{" + _escape_tex("其他题目") + "}")
        lines.append(r"\begin{enumerate}[resume]")
        for pq in unsectioned:
            question = pq.question
            if question is None:
                continue
            score = pq.score or 0
            lines.append(
                r"\item "
                + f"({score}" + _escape_tex("分") + ") "
                + _render_stem(question.stem or "")
            )
        lines.append(r"\end{enumerate}")

    lines.append("")
    lines.append(r"\end{document}")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# Answers-only TeX renderer
# ──────────────────────────────────────────────


async def render_answers_to_tex(
    paper: Paper,
    paper_questions: list[PaperQuestion],
    db: AsyncSession,
) -> str:
    """Render an answer-only paper to LaTeX source.

    Produces ``answers.tex`` — contains only answers and solution steps for
    each question, referenced by question number.  Questions where no answer
    is available are marked as ``未提供答案``.

    Parameters
    ----------
    paper : Paper
        The paper ORM object with ``sections`` loaded.
    paper_questions : list[PaperQuestion]
        Paper-question links with ``.question`` (and nested relationships) loaded.
    db : AsyncSession
        Open async database session.

    Returns
    -------
    str
        Complete LaTeX document containing only answers.
    """
    sorted_pqs = sorted(paper_questions, key=lambda pq: pq.order_index or 0)

    # Build section → questions map
    section_map: dict[int, list[PaperQuestion]] = {}
    unsectioned: list[PaperQuestion] = []
    for pq in sorted_pqs:
        if pq.paper_section_id:
            section_map.setdefault(pq.paper_section_id, []).append(pq)
        else:
            unsectioned.append(pq)

    paper_sections = sorted(paper.sections or [], key=lambda s: s.order_index or 0)

    # ── Build TeX ────────────────────────────────────────────────────────
    lines: list[str] = []
    answer_title = (paper.title or "物理试卷") + " — 参考答案"
    lines.extend(_build_preamble(answer_title))

    # ── Render each section ──────────────────────────────────────────────
    for section in paper_sections:
        lines.append(r"\section*{" + _escape_tex(section.name) + "}")
        lines.append("")

        sqs = section_map.get(section.id, [])
        if not sqs:
            lines.append(r"\textit{（本部分暂无题目）}")
            lines.append("")
            continue

        lines.append(r"\begin{enumerate}[resume]")

        for pq in sorted(sqs, key=lambda x: x.order_index or 0):
            question = pq.question
            if question is None:
                lines.append(r"\item " + _escape_tex("题目已删除"))
                lines.append(r"\vspace{0.3cm}")
                continue

            lines.append(r"\item ")

            has_answer = bool(question.answers)
            has_solution = bool(question.solution_steps)

            if has_answer:
                lines.append(_render_answer(question.answers))
            if has_solution:
                lines.append(
                    _render_solution(
                        sorted(question.solution_steps, key=lambda s: s.step_order or 0)
                    )
                )

            if not has_answer and not has_solution:
                lines.append(r"\textbf{" + _escape_tex("未提供答案") + "}")

            # Images from answers/solutions
            answer_refs: dict[str, None] = {}
            for ans in question.answers or []:
                for ref in _extract_image_references(getattr(ans, "content", "") or ""):
                    answer_refs[ref] = None
            for step in question.solution_steps or []:
                for ref in _extract_image_references(getattr(step, "content", "") or ""):
                    answer_refs[ref] = None
                for ref in _extract_image_references(getattr(step, "formula", "") or ""):
                    answer_refs[ref] = None
                for ref in _extract_image_references(getattr(step, "explanation", "") or ""):
                    answer_refs[ref] = None

            lines.extend(_render_image_block(list(answer_refs.keys())))
            lines.append(r"\vspace{0.5cm}")
            lines.append("")

        lines.append(r"\end{enumerate}")
        lines.append("")

    # ── Unsectioned questions ────────────────────────────────────────────
    if unsectioned:
        lines.append(r"\section*{" + _escape_tex("其他题目 — 答案") + "}")
        lines.append(r"\begin{enumerate}[resume]")
        for pq in unsectioned:
            question = pq.question
            if question is None:
                continue
            lines.append(r"\item ")
            if question.answers:
                lines.append(_render_answer(question.answers))
            elif question.solution_steps:
                lines.append(
                    _render_solution(
                        sorted(question.solution_steps, key=lambda s: s.step_order or 0)
                    )
                )
            else:
                lines.append(r"\textbf{" + _escape_tex("未提供答案") + "}")
            lines.append(r"\vspace{0.3cm}")
        lines.append(r"\end{enumerate}")

    lines.append("")
    lines.append(r"\end{document}")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# Legacy combined renderer (kept for backward compat)
# ──────────────────────────────────────────────


async def render_paper_to_tex(
    paper: Paper,
    paper_questions: list[PaperQuestion],
    db: AsyncSession,
) -> str:
    """Render a combined paper + answers LaTeX source.

    **Deprecated.**  New code should use ``render_questions_to_tex`` and
    ``render_answers_to_tex`` separately.  This function remains for backward
    compatibility only.
    """
    sorted_pqs = sorted(paper_questions, key=lambda pq: pq.order_index or 0)

    section_map: dict[int, list[PaperQuestion]] = {}
    unsectioned: list[PaperQuestion] = []
    for pq in sorted_pqs:
        if pq.paper_section_id:
            section_map.setdefault(pq.paper_section_id, []).append(pq)
        else:
            unsectioned.append(pq)

    paper_sections = sorted(paper.sections or [], key=lambda s: s.order_index or 0)

    lines: list[str] = []
    title = paper.title or "物理试卷"
    lines.extend(_build_preamble(title))

    if paper.duration_minutes or paper.total_score:
        lines.append(r"\begin{center}")
        lines.append(r"\begin{tabular}{rl}")
        if paper.duration_minutes is not None:
            lines.append(
                rf"  \textbf{{{_escape_tex('时长:')}}} & {paper.duration_minutes} 分钟 \\"
            )
        if paper.total_score is not None:
            lines.append(
                rf"  \textbf{{{_escape_tex('总分:')}}} & {paper.total_score} 分 \\"
            )
        lines.append(r"\end{tabular}")
        lines.append(r"\end{center}")
        lines.append(r"\vspace{0.5cm}")
        lines.append("")

    for section in paper_sections:
        lines.append(r"\section*{" + _escape_tex(section.name) + "}")
        lines.append("")

        sqs = section_map.get(section.id, [])
        if not sqs:
            lines.append(r"\textit{（本部分暂无题目）}")
            lines.append("")
            continue

        lines.append(r"\begin{enumerate}[resume]")

        for pq in sorted(sqs, key=lambda x: x.order_index or 0):
            question = pq.question
            if question is None:
                continue

            score = pq.score if pq.score else section.score_each

            lines.append(
                r"\item "
                + f"({score}" + _escape_tex("分") + ") "
                + _render_stem(question.stem or "")
            )

            if question.choice_options:
                lines.append(
                    _render_options(
                        sorted(question.choice_options, key=lambda o: o.order_index or 0)
                    )
                )

            if paper.include_answers and question.answers:
                lines.append(_render_answer(question.answers))

            if paper.include_answers and question.solution_steps:
                lines.append(
                    _render_solution(
                        sorted(question.solution_steps, key=lambda s: s.step_order)
                    )
                )

            image_refs = await _collect_image_refs(question, db)
            lines.extend(_render_image_block(image_refs))

            lines.append(r"\vspace{0.5cm}")
            lines.append("")

        lines.append(r"\end{enumerate}")
        lines.append("")

    if unsectioned:
        lines.append(r"\section*{" + _escape_tex("其他题目") + "}")
        lines.append(r"\begin{enumerate}[resume]")
        for pq in unsectioned:
            question = pq.question
            if question is None:
                continue
            score = pq.score or 0
            lines.append(
                r"\item "
                + f"({score}" + _escape_tex("分") + ") "
                + _render_stem(question.stem or "")
            )
        lines.append(r"\end{enumerate}")

    lines.append("")
    lines.append(r"\end{document}")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# PDF compilation
# ──────────────────────────────────────────────


async def compile_pdf(
    tex_path: Path,
    output_dir: Path,
    engine: str = "xelatex",
) -> tuple[Optional[Path], str]:
    """Compile a TeX file to PDF.

    Uses ``latexmk`` if available, falling back to a direct ``xelatex`` call.
    Both are run with ``-interaction=nonstopmode``.

    Parameters
    ----------
    tex_path : Path
        Absolute path to the ``.tex`` file.
    output_dir : Path
        Directory to place the output PDF (and auxiliary files).
    engine : str
        LaTeX engine: ``"xelatex"`` (default), ``"lualatex"``, or ``"pdflatex"``.

    Returns
    -------
    tuple[Optional[Path], str]
        ``(pdf_path, build_log)``. ``pdf_path`` is ``None`` when compilation fails.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    tex_abs = tex_path.resolve()
    output_abs = output_dir.resolve()

    build_log_parts: list[str] = []
    pdf_path: Optional[Path] = None

    # ── Try latexmk first ──────────────────────────────────────────────
    latexmk_cmd = [
        "latexmk",
        f"-{engine}",
        "-interaction=nonstopmode",
        f"-output-directory={output_abs}",
        str(tex_abs),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *latexmk_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        build_log_parts.append(f"latexmk stdout:\n{stdout.decode(errors='replace')}")
        if stderr:
            build_log_parts.append(f"latexmk stderr:\n{stderr.decode(errors='replace')}")

        if proc.returncode == 0:
            candidate = output_dir / tex_path.with_suffix(".pdf").name
            if candidate.is_file():
                pdf_path = candidate
                build_log_parts.append("latexmk succeeded.")
                return pdf_path, "\n".join(build_log_parts)
        else:
            build_log_parts.append(
                f"latexmk exited with code {proc.returncode}; falling back to {engine}."
            )
    except asyncio.TimeoutError:
        build_log_parts.append("latexmk timed out after 120s; falling back to direct call.")
        try:
            proc.kill()
        except Exception:
            pass
    except FileNotFoundError:
        build_log_parts.append("latexmk not found; falling back to direct call.")

    # ── Fallback: direct engine call ───────────────────────────────────
    engine_cmd = [
        engine,
        "-interaction=nonstopmode",
        f"-output-directory={output_abs}",
        str(tex_abs),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *engine_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        build_log_parts.append(
            f"{engine} stdout:\n{stdout.decode(errors='replace')}"
        )
        if stderr:
            build_log_parts.append(
                f"{engine} stderr:\n{stderr.decode(errors='replace')}"
            )

        if proc.returncode == 0:
            candidate = output_dir / tex_path.with_suffix(".pdf").name
            if candidate.is_file():
                pdf_path = candidate
                build_log_parts.append(f"{engine} succeeded.")
            else:
                build_log_parts.append(
                    f"{engine} exited 0 but PDF not found at {candidate}."
                )
        else:
            build_log_parts.append(
                f"{engine} exited with code {proc.returncode}."
            )
    except asyncio.TimeoutError:
        build_log_parts.append(f"{engine} timed out after 60s.")
        try:
            proc.kill()
        except Exception:
            pass
    except FileNotFoundError:
        build_log_parts.append(f"{engine} not found in PATH.")

    build_log = "\n".join(build_log_parts)
    return pdf_path, build_log
