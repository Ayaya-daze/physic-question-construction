"""Image parser — runs OCR on PNG/JPG/TIFF images and returns a ParsedDocument."""

from __future__ import annotations

from pathlib import Path

from app.services.ocr_p2t import ocr_page
from app.services.parsers import (
    PageContent,
    ParsedDocument,
    TextBlock,
    register_parser,
)


@register_parser("image")
def parse_image(file_path: Path) -> ParsedDocument:
    """OCR a single image file and return a ParsedDocument.

    Each OCR block becomes a TextBlock in a single page.
    """
    result = ocr_page(file_path, page_num=1)

    blocks: list[TextBlock] = []
    for b in result.blocks:
        blocks.append(TextBlock(
            text=b.text,
            bbox=b.bbox,
            block_type=b.block_type or "text",
            confidence=b.confidence,
        ))

    return ParsedDocument(
        pages=[
            PageContent(
                page_number=1,
                blocks=blocks,
                raw_text=result.full_text,
                image_path=file_path,
            )
        ],
        raw_text=result.full_text,
        metadata={
            "page_count": 1,
            "is_text_based": False,
            "ocr_needed": True,
            "ocr_source": "tesseract",
            "ocr_confidence_avg": sum(b.confidence for b in result.blocks) / max(len(result.blocks), 1),
            "ocr_blocks": len(result.blocks),
        },
    )
