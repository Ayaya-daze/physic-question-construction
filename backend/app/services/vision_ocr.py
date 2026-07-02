"""Vision-based page reading — uses a multimodal LLM to read page images directly.

For Chinese physics PDFs with non-standard font mappings, traditional OCR
(Tesseract, CnOcr) frequently produces garbled output because custom font glyphs
don't map to standard Unicode.  A multimodal LLM reads the rendered page image
directly — no glyph-to-Unicode step, no garbled characters.

This is the PRIMARY page-reading path when a vision-capable model is configured.
When vision is unavailable, it falls back to CnOcr → Tesseract.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from app.services.ocr import OCRBlock, OCRPageResult

logger = logging.getLogger(__name__)


def _encode_image_base64(image_path: Path) -> str:
    """Read an image file and return a base64-encoded data URI string."""
    data = image_path.read_bytes()
    ext = image_path.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/png")
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


VISION_PAGE_PROMPT = """Read ALL text and mathematical formulas from this Chinese physics exam page.

Return the complete text, preserving:
- Chinese characters exactly as they appear
- ALL mathematical formulas in LaTeX format wrapped in $...$ (inline) or $$...$$ (display)
- Question numbers, sub-question labels (1)(2)(3), and section markers
- Numerical values with their units
- Greek letters as LaTeX: $\\alpha$, $\\beta$, $\\theta$, $\\omega$, etc.
- Subscripts/superscripts: $v_0$, $x^2$, $T_0$
- Fractions: $\\frac{1}{2}$, $\\frac{dV}{dx}$
- Do NOT add any commentary or markdown outside the page content.

If parts of the text are unreadable, write [unreadable] for that portion.
Do NOT guess or fabricate text."""


async def read_page_with_vision(
    image_path: Path,
    page_num: int = 1,
) -> OCRPageResult | None:
    """Use a multimodal LLM to read a page image.  Returns None if no vision
    model is configured or the call fails."""
    try:
        from app.services.llm import get_llm_provider
        provider = get_llm_provider()
    except Exception:
        return None

    if not provider.supports_vision:
        return None

    try:
        data_uri = _encode_image_base64(image_path)
        content = await provider.complete_with_image(
            image_data=data_uri,
            prompt=VISION_PAGE_PROMPT,
            max_tokens=4096,
            temperature=0.0,
        )
        text = content.content.strip()
    except Exception as exc:
        logger.warning("Vision LLM failed on page %d: %s", page_num, exc)
        return None

    if not text:
        return None

    return OCRPageResult(
        page=page_num,
        blocks=[OCRBlock(text=text, bbox=[0, 0, 100, 100], confidence=0.95, block_type="text")],
        full_text=text,
        image_path=image_path,
    )


def _has_vision_provider() -> bool:
    """Check quickly whether a vision-capable LLM is configured."""
    try:
        from app.services.llm import get_llm_provider
        provider = get_llm_provider()
        return getattr(provider, "supports_vision", False)
    except Exception:
        return False


def read_page(
    image_path: Path,
    page_num: int = 1,
    lang: str = "chi_sim+eng+equ",
) -> OCRPageResult:
    """Read a single page image using the best available method.

    1. Multimodal LLM (if configured and supports vision)
    2. CnOcr (PP-OCRv5 — strong for Chinese + English)
    3. Tesseract (fallback)
    """
    # Try vision LLM first (auto-detect async context)
    if _has_vision_provider():
        import asyncio
        try:
            # Check if we're already in an async context
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # We're inside an async function — can't use run_until_complete.
            # The caller should use read_page_async() instead.
            logger.warning(
                "Vision LLM is configured but read_page() was called from an "
                "async context.  Use read_page_async() to avoid nested event loop.  "
                "Falling back to CnOcr for page %d.",
                page_num,
            )
        else:
            # Sync context — run the async vision call
            try:
                result = asyncio.run(read_page_with_vision(image_path, page_num))
                if result is not None and result.full_text.strip():
                    return result
            except Exception:
                pass

    # Fall back to CnOcr → Tesseract
    from app.services.ocr_p2t import ocr_page as _ocr_page
    return _ocr_page(image_path, page_num, lang)


async def read_page_async(
    image_path: Path,
    page_num: int = 1,
    lang: str = "chi_sim+eng+equ",
) -> OCRPageResult:
    """Async version — use this from async callers like file_question_importer."""
    if _has_vision_provider():
        try:
            result = await read_page_with_vision(image_path, page_num)
            if result is not None and result.full_text.strip():
                return result
        except Exception:
            pass

    # Fall back to CnOcr → Tesseract (blocking call — run in thread)
    import asyncio as _asyncio
    from app.services.ocr_p2t import ocr_page as _ocr_page
    return await _asyncio.to_thread(_ocr_page, image_path, page_num, lang)
