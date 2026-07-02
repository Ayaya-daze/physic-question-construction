"""LaTeX parser — extracts questions from structured TeX documents.

Handles common Chinese exam patterns: \\begin{question}...\\end{question},
\\section, and inline math environments.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from app.services.parsers import (
    MediaRef,
    PageContent,
    ParsedDocument,
    TextBlock,
    register_parser,
)

# Common LaTeX question environments
QUESTION_ENVS = [
    r"\\begin\{question\}",
    r"\\begin\{problem\}",
    r"\\begin\{exercise\}",
    r"\\begin\{prob\}",
    r"\\begin\{wenti\}",
]

# Section commands
SECTION_CMDS = [
    r"\\section",
    r"\\subsection",
    r"\\subsubsection",
    r"\\chapter",
]


def _extract_questions_from_latex(text: str) -> list[dict]:
    """Try to extract individual questions from LaTeX source.

    Returns a list of question dicts suitable for QuestionCreate.
    """
    questions: list[dict] = []

    # Try to find question environments
    for env_pat in QUESTION_ENVS:
        env_name = env_pat.replace("\\begin{", "").replace("}", "")
        pattern = rf"\\begin\{{{env_name}\}}(.*?)\\end\{{{env_name}\}}"
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            for match in matches:
                questions.append({
                    "stem": match.strip(),
                    "question_type": "calculation",
                    "difficulty": 3,
                    "options": [],
                    "answers": [],
                    "solution_steps": [],
                    "knowledge_points": [],
                    "tags": [],
                })
            break

    # If no question environments found, treat the whole document as one source
    if not questions:
        # Split by section as potential question boundaries
        sections = re.split(r"\\section\*?\{[^}]*\}", text)
        for section in sections:
            section = section.strip()
            if len(section) > 50:  # Non-trivial content
                questions.append({
                    "stem": section,
                    "question_type": "calculation",
                    "difficulty": 3,
                    "options": [],
                    "answers": [],
                    "solution_steps": [],
                    "knowledge_points": [],
                    "tags": [],
                })

    return questions


def _extract_sections(text: str) -> list[tuple[str, str]]:
    """Extract section titles and content from LaTeX."""
    sections: list[tuple[str, str]] = []
    pattern = r"\\(?:sub)?section\*?\{([^}]*)\}"
    matches = list(re.finditer(pattern, text))

    for i, match in enumerate(matches):
        title = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections.append((title, content))

    if not sections:
        sections.append(("Document", text.strip()))

    return sections


@register_parser("tex")
def parse_tex(file_path: Path) -> ParsedDocument:
    """Parse a LaTeX file, extracting text content and detecting question structures."""
    text = file_path.read_text(encoding="utf-8", errors="replace")

    # Extract metadata from preamble
    metadata: dict = {"format": "tex"}
    title_match = re.search(r"\\title\{([^}]*)\}", text)
    if title_match:
        metadata["title"] = title_match.group(1)
    author_match = re.search(r"\\author\{([^}]*)\}", text)
    if author_match:
        metadata["author"] = author_match.group(1)

    # Extract sections into page-like blocks
    sections = _extract_sections(text)
    pages: list[PageContent] = []

    for i, (title, content) in enumerate(sections):
        blocks: list[TextBlock] = []

        # Heading
        blocks.append(TextBlock(text=title, block_type="heading"))

        # Process content: keep LaTeX formulas intact but separate into blocks
        # Split on display math $$...$$ as formula blocks
        parts = re.split(r"(\$\$[^$]+\$\$)", content)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part.startswith("$$") and part.endswith("$$"):
                blocks.append(TextBlock(text=part, block_type="formula"))
            else:
                # Split paragraphs
                for para in part.split("\n\n"):
                    para = para.strip()
                    if para:
                        blocks.append(TextBlock(text=para, block_type="paragraph"))

        pages.append(PageContent(
            page_number=i + 1,
            blocks=blocks,
            raw_text=content,
        ))

    # Try to extract questions
    questions = _extract_questions_from_latex(text)
    if questions:
        metadata["parsed_questions"] = questions

    return ParsedDocument(
        pages=pages,
        raw_text=text,
        metadata=metadata,
    )
