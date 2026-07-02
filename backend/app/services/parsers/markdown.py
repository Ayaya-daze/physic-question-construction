"""Markdown parser — maps structured markdown to ParsedDocument and QuestionCreate candidates.

Supports:
1. The app's own content.md format (## 题干, ## 选项, ## 答案, ## 解析, ## 知识点, ## 标签)
2. Free-form physics markdown with LaTeX
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.services.parsers import (
    PageContent,
    ParsedDocument,
    TextBlock,
    register_parser,
)


def _detect_content_md_format(text: str) -> bool:
    """Check if text follows the app's content.md structure."""
    markers = ["## 题干", "## 选项", "## 答案", "## 解析"]
    return sum(1 for m in markers if m in text) >= 2


def _parse_content_md(text: str) -> dict:
    """Parse a file in the app's content.md format into a question dict.

    Returns a dict compatible with QuestionCreate schema.
    """
    import re

    result: dict = {
        "stem": "",
        "question_type": "single_choice",
        "difficulty": 3,
        "options": [],
        "answers": [],
        "solution_steps": [],
        "knowledge_points": [],
        "tags": [],
        "grade": None,
        "score": None,
    }

    # Extract sections by heading
    sections: dict[str, str] = {}
    current_section = "_preamble"
    current_content: list[str] = []

    for line in text.split("\n"):
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            if current_content:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = m.group(1)
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        sections[current_section] = "\n".join(current_content).strip()

    # ── Parse preamble (metadata line) ──
    preamble = sections.get("_preamble", "")
    # Extract difficulty from stars
    star_match = re.search(r"难度[：:]\s*(★+)", preamble)
    if star_match:
        result["difficulty"] = len(star_match.group(1))
    # Extract question type
    type_match = re.search(r"类型[：:]\s*(\S+)", preamble)
    if type_match:
        type_label = type_match.group(1)
        type_map = {
            "单选题": "single_choice",
            "多选题": "multiple_choice",
            "填空题": "fill_blank",
            "计算题": "calculation",
            "实验题": "experiment",
            "简答题": "essay",
            "综合题": "composite",
        }
        result["question_type"] = type_map.get(type_label, "single_choice")
    # Extract grade
    grade_match = re.search(r"年级[：:]\s*(\S+)", preamble)
    if grade_match:
        result["grade"] = grade_match.group(1)

    # ── 题干 ──
    if "题干" in sections:
        result["stem"] = sections["题干"].strip()

    # ── 选项 ──
    if "选项" in sections:
        options_text = sections["选项"]
        # Pattern: - A. content or - **A**. content or ✅ **A** content
        option_pattern = re.findall(
            r"[-*]\s*(?:✅\s*)?\*?\*?([A-H])\*?\*?[.、\s]+(.+?)(?=\n[-*]\s*(?:✅\s*)?\*?\*?[A-H]|$)",
            options_text,
            re.DOTALL,
        )
        if not option_pattern:
            # Try simpler pattern: lines starting with label
            for line in options_text.split("\n"):
                m = re.match(r"[-*]\s*(?:✅\s*)?\*?\*?([A-H])\*?\*?[.、\s]+(.+)", line)
                if m:
                    option_pattern.append((m.group(1), m.group(2).strip()))

        for label, content in option_pattern:
            is_correct = "✅" in options_text.split(f"**{label}**")[0] if f"**{label}**" in options_text else False
            # Check if ✅ appears near this option
            opt_start = options_text.find(f"{label}.")
            if opt_start == -1:
                opt_start = options_text.find(f"**{label}**")
            preceding = options_text[max(0, opt_start - 10):opt_start] if opt_start >= 0 else ""
            is_correct = "✅" in preceding

            result["options"].append({
                "option_label": label,
                "content": content.strip(),
                "is_correct": is_correct,
                "order_index": ord(label) - ord("A"),
            })

        # Determine correct answers
        correct_labels = [o["option_label"] for o in result["options"] if o["is_correct"]]
        if correct_labels:
            if result["question_type"] in ("single_choice",):
                result["answers"] = [{
                    "answer_type": "choice",
                    "content": correct_labels[0],
                }]
            elif result["question_type"] == "multiple_choice":
                result["answers"] = [{
                    "answer_type": "choice",
                    "content": "".join(correct_labels),
                }]

    # ── 答案 ──
    if "答案" in sections:
        answer_text = sections["答案"].strip()
        # Extract bolded answer key
        answer_label_match = re.search(r"\*\*([A-H]+)\*\*", answer_text)
        if answer_label_match:
            answer_key = answer_label_match.group(1)
            if not result.get("answers"):
                result["answers"] = [{
                    "answer_type": "choice" if result["question_type"] in ("single_choice", "multiple_choice") else "text",
                    "content": answer_key,
                }]
        elif not result.get("answers"):
            # Non-choice answer
            result["answers"] = [{
                "answer_type": "text",
                "content": answer_text,
            }]

    # ── 解析 ──
    if "解析" in sections:
        solution_text = sections["解析"]
        # Split by numbered steps
        steps = re.split(r"\n(?=\d+[.、)])", solution_text.strip())
        if len(steps) == 1 and steps[0].strip():
            # Maybe single step or unnumbered
            result["solution_steps"] = [{
                "step_order": 1,
                "content": steps[0].strip(),
            }]
        else:
            for i, step in enumerate(steps):
                step = step.strip()
                if not step:
                    continue
                # Extract formula if present ($...$ or $$...$$)
                formula_match = re.search(r"(\$\$?[^$]+\$\$?)", step)
                formula = formula_match.group(1) if formula_match else None
                result["solution_steps"].append({
                    "step_order": i + 1,
                    "content": step,
                    "formula": formula,
                })

    # ── 知识点 ──
    if "知识点" in sections:
        kp_text = sections["知识点"]
        # Parse paths like "力学/运动学/匀变速直线运动"
        paths = re.findall(r"([一-鿿\w]+/[一-鿿\w/]+)", kp_text)
        if not paths:
            # Try comma/semicolon separated
            paths = [p.strip() for p in re.split(r"[,;，；]", kp_text) if "/" in p]
        result["knowledge_points"] = [
            {"path": p.strip(), "is_primary": i == 0, "weight": 1.0}
            for i, p in enumerate(paths)
        ]

    # ── 标签 ──
    if "标签" in sections:
        tags_text = sections["标签"]
        tags = re.findall(r"[一-鿿\w\s-]+", tags_text)
        # Clean up comma/semicolon separated
        result["tags"] = [
            t.strip() for tag_group in tags
            for t in re.split(r"[,;，；]", tag_group)
            if t.strip()
        ]

    return result


def _parse_freeform_md(text: str) -> ParsedDocument:
    """Parse free-form markdown into a ParsedDocument with text blocks."""
    import re

    blocks: list[TextBlock] = []
    current_type = "paragraph"
    current_text: list[str] = []

    def flush():
        nonlocal current_text
        if current_text:
            content = "\n".join(current_text).strip()
            if content:
                blocks.append(TextBlock(text=content, block_type=current_type))
            current_text = []

    for line in text.split("\n"):
        # Headings
        if re.match(r"^#{1,3}\s+", line):
            flush()
            current_type = "heading"
            current_text.append(re.sub(r"^#{1,3}\s+", "", line))
            flush()
            current_type = "paragraph"
            continue

        # LaTeX display math
        if re.match(r"^\$\$", line):
            flush()
            current_type = "formula"
            current_text.append(line)
            continue
        if current_type == "formula" and line.strip().endswith("$$"):
            current_text.append(line)
            flush()
            current_type = "paragraph"
            continue

        # Inline LaTeX — keep as paragraph
        current_text.append(line)

    flush()

    return ParsedDocument(
        pages=[PageContent(page_number=1, blocks=blocks, raw_text=text)],
        raw_text=text,
    )


@register_parser("markdown")
def parse_markdown(file_path: Path) -> ParsedDocument:
    """Parse a markdown file and detect the format."""
    text = file_path.read_text(encoding="utf-8")

    if _detect_content_md_format(text):
        # This is an app-native content.md — parse structured question
        question = _parse_content_md(text)
        # Store the parsed question in metadata for direct candidate creation
        return ParsedDocument(
            pages=[PageContent(page_number=1, raw_text=text)],
            raw_text=text,
            metadata={"format": "content_md", "parsed_questions": [question]},
        )

    # Free-form markdown
    return _parse_freeform_md(text)
