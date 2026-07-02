"""Services package — OCR, LLM, parsers, paper generation, and LaTeX rendering."""

from app.services.parsers import (
    MediaRef,
    PageContent,
    ParsedDocument,
    TextBlock,
    get_parser,
    register_parser,
)

__all__ = [
    "ParsedDocument",
    "PageContent",
    "TextBlock",
    "MediaRef",
    "get_parser",
    "register_parser",
]
