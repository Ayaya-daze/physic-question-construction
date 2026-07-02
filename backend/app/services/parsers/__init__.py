"""Parser registry and shared dataclasses for file-format parsers.

Each parser accepts a file path and returns a ParsedDocument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# ──────────────────────────────────────────────
# Shared dataclasses
# ──────────────────────────────────────────────

@dataclass
class TextBlock:
    """A block of text with optional position and type info."""

    text: str
    bbox: Optional[list[float]] = None  # [x1, y1, x2, y2] in page coordinates
    block_type: str = "paragraph"  # paragraph, heading, formula, list_item, etc.
    confidence: float = 1.0


@dataclass
class PageContent:
    """Content of a single page (or logical page for non-paginated formats)."""

    page_number: int
    blocks: list[TextBlock] = field(default_factory=list)
    image_path: Optional[Path] = None  # rendered page image for preview
    raw_text: str = ""


@dataclass
class MediaRef:
    """Reference to an extracted media asset (image, figure, formula)."""

    asset_id: str
    asset_type: str  # figure, formula_image, table_image, question_crop
    file_path: str
    page_number: Optional[int] = None
    region: Optional[list[float]] = None  # [x1, y1, x2, y2]
    caption: Optional[str] = None


@dataclass
class ParsedDocument:
    """Unified result from any parser — pages of text blocks + metadata."""

    pages: list[PageContent] = field(default_factory=list)
    raw_text: str = ""
    metadata: dict = field(default_factory=dict)
    media_refs: list[MediaRef] = field(default_factory=list)

    def all_text(self) -> str:
        """Return concatenated text from all pages (or raw_text if no pages)."""
        if self.pages:
            return "\n\n".join(f"[Page {p.page_number}]\n{p.raw_text}" for p in self.pages)
        return self.raw_text


# ──────────────────────────────────────────────
# Parser protocol & registry
# ──────────────────────────────────────────────

ParserFunc = Callable[[Path], ParsedDocument]

_registry: dict[str, ParserFunc] = {}


def register_parser(source_type: str):
    """Decorator to register a parser function for a source_type."""

    def decorator(func: ParserFunc) -> ParserFunc:
        _registry[source_type] = func
        return func

    return decorator


def get_parser(source_type: str) -> Optional[ParserFunc]:
    """Look up a registered parser by source_type."""
    return _registry.get(source_type)
