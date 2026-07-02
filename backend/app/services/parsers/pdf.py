"""PDF parser — uses PyMuPDF for text/position extraction and page rendering.

Distinguishes between text-based and scanned PDFs.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from app.services.parsers import (
    MediaRef,
    PageContent,
    ParsedDocument,
    TextBlock,
    register_parser,
)


def is_pdf_text_based(pdf_path: Path, min_chars: int = 50) -> bool:
    """Check if a PDF is text-based by extracting text from the first page."""
    try:
        doc = fitz.open(str(pdf_path))
        if len(doc) == 0:
            return False
        page = doc[0]
        text = page.get_text("text")
        doc.close()
        return len(text.strip()) > min_chars
    except Exception:
        return False


def render_pdf_pages(pdf_path: Path, output_dir: Path, dpi: int = 300) -> list[Path]:
    """Render each page of a PDF as a PNG image. Returns list of image paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    image_paths: list[Path] = []

    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=dpi)
        img_path = output_dir / f"page_{i + 1:03d}.png"
        pix.save(str(img_path))
        image_paths.append(img_path)

    doc.close()
    return image_paths


@register_parser("pdf")
def parse_pdf(file_path: Path) -> ParsedDocument:
    """Parse a PDF file.

    For text-based PDFs: extract text blocks with position info.
    For scanned PDFs: render pages as images (OCR is handled separately).
    """
    doc = fitz.open(str(file_path))
    pages: list[PageContent] = []
    all_media_refs: list[MediaRef] = []
    all_raw_text: list[str] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1

        # Extract text blocks with position
        blocks: list[TextBlock] = []
        page_raw_text: list[str] = []

        # Get text blocks from PyMuPDF
        text_blocks = page.get_text("blocks")
        for block in text_blocks:
            x1, y1, x2, y2, text, block_type, _block_no = block
            text = text.strip()
            if not text:
                continue

            block_type_str = "paragraph"
            if block_type == 0:
                block_type_str = "paragraph"  # Regular text
            elif block_type == 1:
                block_type_str = "image"  # Image block — skip text extraction

            if block_type_str == "paragraph" and text:
                blocks.append(TextBlock(
                    text=text,
                    bbox=[x1, y1, x2, y2],
                    block_type=block_type_str,
                ))
                page_raw_text.append(text)

        raw_text = "\n".join(page_raw_text)

        # Extract images embedded in the page
        page_media: list[MediaRef] = []
        try:
            img_list = page.get_images(full=True)
            for img_idx, img_info in enumerate(img_list):
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                if base_image:
                    asset_id = f"asset_{Path(file_path).stem}_{page_num}_{img_idx}"
                    # Save extracted image to the same directory structure
                    page_media.append(MediaRef(
                        asset_id=asset_id,
                        asset_type="figure",
                        file_path="",  # Filled in by caller
                        page_number=page_num,
                        caption=base_image.get("ext", ""),
                    ))
        except Exception:
            pass

        all_media_refs.extend(page_media)

        pages.append(PageContent(
            page_number=page_num,
            blocks=blocks,
            raw_text=raw_text,
        ))
        all_raw_text.append(f"[Page {page_num}]\n{raw_text}")

    doc.close()

    return ParsedDocument(
        pages=pages,
        raw_text="\n\n".join(all_raw_text),
        metadata={
            "page_count": len(pages),
            "is_text_based": len(all_raw_text) > 0 and len(all_raw_text[0].strip()) > 50,
        },
        media_refs=all_media_refs,
    )
