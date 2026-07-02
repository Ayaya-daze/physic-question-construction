"""Enhanced OCR service — uses CnOcr (PP-OCRv5) for superior Chinese + formula text.

CnOcr is the Chinese OCR engine that powers Pix2Text.  It uses:
* PP-OCRv5 detection model (via OnnxRuntime / RapidOCR)
* densenet_lite_136-gru recognition model
* Optimised for Chinese + English mixed text with mathematical notation

This module provides a drop-in replacement for the Tesseract-based ``ocr_page()``
— the rest of the pipeline needs no changes thanks to the shared OCRBlock/OCRPageResult
interface.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.ocr import OCRBlock, OCRPageResult

logger = logging.getLogger(__name__)

try:
    import cnocr
    _CNOCR_AVAILABLE = True
except ImportError:
    _CNOCR_AVAILABLE = False
    cnocr = None  # type: ignore[no-redef]

# Global CnOcr instance (lazy init — models are ~50 MB loaded once)
_cnocr_instance = None


def _get_cnocr():
    """Return the shared CnOcr instance, creating it on first call."""
    global _cnocr_instance
    if not _CNOCR_AVAILABLE:
        raise RuntimeError("cnocr not installed. Run: pip install cnocr cnstd onnxruntime")
    if _cnocr_instance is None:
        _cnocr_instance = cnocr.CnOcr(
            det_model_name="ch_PP-OCRv5_det",
            rec_model_name="densenet_lite_136-gru",
        )
    return _cnocr_instance


def ocr_image_cnocr(image_path: Path) -> list[OCRBlock]:
    """Run CnOcr on a single image, returning standard OCRBlock objects."""
    ocr = _get_cnocr()
    results = ocr.ocr(str(image_path))
    if not results:
        return []

    blocks: list[OCRBlock] = []
    for item in results:
        text = (item.get("text") or "").strip()
        if not text:
            continue

        line_boxes = item.get("position")  # numpy ndarray — DO NOT use "or []": bool(ndarray) raises
        if line_boxes is not None and hasattr(line_boxes, '__len__') and len(line_boxes) >= 4:
            # position is a numpy ndarray of shape (4,2) — quadrilateral
            # DON'T use "if line_boxes" — numpy bool() on multi-element arrays raises
            try:
                xs = [float(p[0]) for p in line_boxes]
                ys = [float(p[1]) for p in line_boxes]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
            except (TypeError, ValueError, IndexError):
                bbox = [0.0, 0.0, 100.0, 100.0]
        else:
            bbox = [0.0, 0.0, 100.0, 100.0]

        confidence = float(item.get("score", 0.8))

        blocks.append(OCRBlock(
            text=text,
            bbox=bbox,
            confidence=confidence,
            block_type="text",
        ))

    return blocks


def ocr_page_cnocr(image_path: Path, page_num: int = 1, lang: str = "") -> OCRPageResult:
    """Run CnOcr on a single page image.  ``lang`` is ignored (CnOcr auto-detects zh+en)."""
    blocks = ocr_image_cnocr(image_path)
    full_text = "\n".join(b.text for b in blocks)
    return OCRPageResult(
        page=page_num,
        blocks=blocks,
        full_text=full_text,
        image_path=image_path,
    )


def ocr_page(image_path: Path, page_num: int = 1, lang: str = "chi_sim+eng+equ") -> OCRPageResult:
    """Run the best available OCR engine on a single page image.

    Tries CnOcr first (PP-OCRv5 — stronger for Chinese + math), falls back
    to Tesseract if CnOcr is unavailable or fails.
    """
    if _CNOCR_AVAILABLE:
        try:
            return ocr_page_cnocr(image_path, page_num, lang)
        except Exception as exc:
            logger.warning("CnOcr failed on %s (page %d), falling back to Tesseract: %s",
                           image_path, page_num, exc)

    from app.services.ocr import ocr_page as _ocr_tesseract
    return _ocr_tesseract(image_path, page_num, lang)
