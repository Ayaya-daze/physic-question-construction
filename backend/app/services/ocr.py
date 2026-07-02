"""OCR service — wraps pytesseract for text recognition and PDF page rendering.

Preprocessing pipeline (in order):
1. Convert to grayscale
2. Deskew (correct 1-2° rotations that ruin subscript/superscript recognition)
3. Denoise (remove speckle noise from scanned PDFs)
4. Adaptive binarization (Otsu threshold — critical for math formula contrast)
5. Sharpen (thicken thin symbols like minus signs, fraction bars)

Tesseract is called with ``--psm 6 --oem 1``:
* PSM 6 = treat page as a single uniform text block (better for dense formula content)
* OEM 1 = LSTM neural net only (stronger at recognising math + CJK mixed text)
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class OCRBlock:
    """A single OCR-detected text block with position and confidence."""

    text: str
    bbox: list[float]  # [x1, y1, x2, y2]
    confidence: float
    block_type: str = "text"  # text, formula, table, figure, header, footer
    line_num: int = 0
    par_num: int = 0


@dataclass
class OCRPageResult:
    """OCR result for a single page."""

    page: int
    blocks: list[OCRBlock] = field(default_factory=list)
    full_text: str = ""
    image_path: Optional[Path] = None


def _check_tesseract() -> bool:
    """Check if tesseract is installed and available."""
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ──────────────────────────────────────────────────────────────────
# Math-aware OCR post-processing
# ──────────────────────────────────────────────────────────────────

# Common OCR errors for physics formulas.
# Order matters — broader patterns first may shadow narrower ones.
_MATH_SUB_FIXES: list[tuple[str, str]] = [
    # Fix missing subscripts: "x1" after a letter → "x_1"
    # Only when immediately following a Latin/Greek letter, and the digit is
    # clearly a subscript (single digit, next char is space/punct/operator).
    (r"([a-zA-Zα-ω])(\d)(?=[\s,;.+\-*/=)}\]>]|$)", r"\1_{\2}"),
    # Fix missing superscripts: e.g. "m2" → "m^2" (context: units, exponents)
    (r"([a-zA-Zα-ω])(\d)(?=[\s,;.+\-*/=)}\]>]|$)", r"\1^{\2}"),  # merge with above in apply function
    # Fix "10^{-19"C" → "10^{-19} C"
    (r"(\d})\s*([A-Z])", r"\1 \2"),
    # Fix common Greek letter OCR errors
    (r"(?<![a-zA-Zα-ω])a(?=\s*[=+\-*/])", "α"),
    (r"(?<![a-zA-Zα-ω])b(?=\s*[=+\-*/])", "β"),
    (r"(?<![a-zA-Zα-ω])y(?=\s*[=+\-*/])", "γ"),
    # Fix fraction garbling: "frac12" → "frac{1}{2}"
    (r"\\frac(\d)(\d)", r"\\frac{\1}{\2}"),
    # Fix missing backslash before LaTeX commands
    (r"(?<!\\)(frac|sqrt|sum|int|prod|lim)(?=\s*[{])", r"\\\1"),
]


def _postprocess_ocr_math(text: str) -> str:
    """Fix common OCR errors in mathematical formulas.

    Applied as a light post-processing pass; the LLM structuring step provides
    the authoritative cleanup.  This pass catches the most frequent patterns
    that confuse both Tesseract and downstream LLM processing.
    """
    for pattern, replacement in _MATH_SUB_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


# ──────────────────────────────────────────────────────────────────
# Image preprocessing
# ──────────────────────────────────────────────────────────────────


def _preprocess_for_ocr(pil_image) -> "Image.Image":
    """Apply the full preprocessing pipeline for math-heavy scanned documents.

    Uses OpenCV for the heavy lifting (deskew, denoise, adaptive threshold)
    and returns a PIL Image ready for Tesseract.
    """
    import cv2
    import numpy as np
    from PIL import Image

    # PIL → OpenCV (grayscale numpy array)
    img_cv = np.array(pil_image)

    # Ensure grayscale
    if len(img_cv.shape) == 3:
        img_cv = cv2.cvtColor(img_cv, cv2.COLOR_RGB2GRAY)

    # ── 1. Scale to optimal Tesseract input size (~300 DPI) ──
    h, w = img_cv.shape[:2]
    if w > 4000 or h > 4000:
        scale = min(4000 / w, 4000 / h)
        img_cv = cv2.resize(img_cv, (int(w * scale), int(h * scale)),
                            interpolation=cv2.INTER_LANCZOS4)

    # ── 2. Deskew — even 1-2° rotation causes subscript/superscript OCR errors ──
    coords = np.column_stack(np.where(img_cv < 250))
    if len(coords) > 100:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) > 0.3:
            h2, w2 = img_cv.shape[:2]
            center = (w2 // 2, h2 // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            img_cv = cv2.warpAffine(
                img_cv, M, (w2, h2),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )

    # ── 3. Denoise — removes speckle without blurring text edges ──
    img_cv = cv2.fastNlMeansDenoising(img_cv, h=8)

    # ── 4. Adaptive threshold — critical for math formula contrast ──
    #     blockSize=15 is a good compromise for both Chinese characters and
    #     small math symbols (subscripts, minus signs, fraction bars).
    img_cv = cv2.adaptiveThreshold(
        img_cv, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15,
        C=3,
    )

    # ── 5. Dilate slightly — thickens thin symbols (minus signs, fraction bars) ──
    kernel = np.ones((2, 2), np.uint8)
    img_cv = cv2.dilate(img_cv, kernel, iterations=1)

    return Image.fromarray(img_cv)


# ──────────────────────────────────────────────────────────────────
# Core OCR functions
# ──────────────────────────────────────────────────────────────────


def ocr_image(image_path: Path, lang: str = "chi_sim+eng+equ") -> list[OCRBlock]:
    """Run OCR on a single image and return blocks with position and confidence.

    Parameters
    ----------
    image_path : Path
        Path to the image file (PNG recommended).
    lang : str
        Tesseract language string.  Default ``chi_sim+eng+equ`` for Chinese
        simplified + English + mathematical equations.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise ImportError(
            "pytesseract is not installed. Install with: pip install pytesseract\n"
            "Also install the Tesseract engine: brew install tesseract tesseract-lang"
        )

    if not _check_tesseract():
        raise RuntimeError(
            "Tesseract OCR engine is not installed or not in PATH. "
            "Install with: brew install tesseract tesseract-lang"
        )

    # ── Load & preprocess ────────────────────────────────────────
    img = Image.open(image_path).convert("L")
    img = _preprocess_for_ocr(img)

    # ── Tesseract config ─────────────────────────────────────────
    # PSM 6 = uniform block of text (better for formula-heavy physics pages)
    # OEM 1 = LSTM only (better at recognising math + CJK mixed text)
    config = "--psm 6 --oem 1"
    data = pytesseract.image_to_data(
        img, lang=lang, config=config, output_type=pytesseract.Output.DICT,
    )

    blocks: list[OCRBlock] = []
    current_text: list[str] = []
    current_bbox: list[float] = []
    current_conf: list[float] = []
    current_block_num = -1
    current_par_num = -1

    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue

        block_num = data["block_num"][i]
        par_num = data["par_num"][i]
        conf = int(data["conf"][i]) / 100.0 if data["conf"][i] != "-1" else 0.0
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]

        # Group by paragraph
        if block_num != current_block_num or par_num != current_par_num:
            if current_text:
                joined = " ".join(current_text)
                blocks.append(OCRBlock(
                    text=_postprocess_ocr_math(joined),
                    bbox=current_bbox,
                    confidence=sum(current_conf) / len(current_conf) if current_conf else 0.0,
                    block_type="text",
                    line_num=current_block_num,
                ))
            current_text = [text]
            current_bbox = [float(x), float(y), float(x + w), float(y + h)]
            current_conf = [conf]
            current_block_num = block_num
            current_par_num = par_num
        else:
            current_text.append(text)
            # Expand bbox
            current_bbox[2] = max(current_bbox[2], float(x + w))
            current_bbox[3] = max(current_bbox[3], float(y + h))
            current_conf.append(conf)

    # Flush last block
    if current_text:
        joined = " ".join(current_text)
        blocks.append(OCRBlock(
            text=_postprocess_ocr_math(joined),
            bbox=current_bbox,
            confidence=sum(current_conf) / len(current_conf) if current_conf else 0.0,
            block_type="text",
        ))

    return blocks


def ocr_page(image_path: Path, page_num: int = 1, lang: str = "chi_sim+eng+equ") -> OCRPageResult:
    """OCR a single page image and return a page-level result."""
    blocks = ocr_image(image_path, lang=lang)
    full_text = "\n".join(b.text for b in blocks)
    return OCRPageResult(
        page=page_num,
        blocks=blocks,
        full_text=full_text,
        image_path=image_path,
    )
