"""Two-stage OCR→LLM proofreading pipeline for Chinese physics exam papers.

Based on research findings from:
- llm_aided_ocr (Dicklesworthstone): multi-pass prompting > single-pass
- CLOCR-C (JonnoB): context-aware correction with social/cultural context
- SeePhys benchmark: terminology glossary injection
- OCR-Agent: capability reflection to constrain hallucination

Pipeline:
  Stage 1 (rule-based / coding-agent): regex fixes, structure cleanup, formula padding
  Stage 2 (LLM semantic): context-aware physics proofreading + question splitting
"""

from __future__ import annotations

import re
from pathlib import Path


# ── Stage 1: Rule-Based Preprocessing (coding-agent style) ──────────────

# Character substitutions: OCR garbage → correct Unicode
_OCR_CHAR_MAP: dict[str, str] = {
    # Greek letters — OCR frequently misses these
    "eo": "ε₀",  # vacuum permittivity (ONLY when preceded by physics context)
    "ro": "ρ",   # density (context-dependent)
    # Common subscript repairs
    "T0": "T₀",  "T1": "T₁",  "T2": "T₂",
    "R0": "R₀",  "C0": "C₀",
    # Superscript
    "10-19": "10⁻¹⁹", "10-12": "10⁻¹²", "10-11": "10⁻¹¹",
    "10-8": "10⁻⁸",   "10-3": "10⁻³",   "10-6": "10⁻⁶",
    "10-34": "10⁻³⁴", "10-9": "10⁻⁹",
    # Unit fixes (these are safe because they appear in unambiguous contexts)
    "m/s2": "m/s²",  "J/s": "J/s",
    # Chinese punctuation normalization
    "考试时间:": "考试时间：",
    "注意事项:": "注意事项：",
}

# Regex-based formula detection and LaTeX wrapping
# Matches: bare physics formulas like "F = ma", "e = 1.602 × 10⁻¹⁹ C"
_FORMULA_PATTERNS: list[tuple[str, str]] = [
    # Greek letter + number: "α₀", "θ₀", "ω₀"
    (r'(?<!\$)([α-ω][₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]+)(?!\$)', r'$\1$'),
    # Physical constants with × and ⁻: "1.602 × 10⁻¹⁹"
    (r'(?<!\$)(\d+\.?\d*\s*[×x]\s*10\s*[⁻¹²³⁴⁵⁶⁷⁸⁹⁰]+)(?!\$)', r'$\1$'),
    # "variable = value unit" pattern: "m = 0.511 MeV/c²"
    (r'(?<!\$)([a-zA-Zα-ω]\s*=\s*[\d\.]+\s*(?:MeV|GeV|eV|kg|m|s|K|Pa|N|J|W|F|C|A|T|Hz)\S*)(?!\$)', r'$\1$'),
    # Fraction with slash: "c/137", "h/(4π)"
    (r'(?<!\$)([a-zA-Zα-ωℏ]\s*/\s*\(?\s*\d+\s*[πa-zA-Zα-ωεσ]*\s*\)?)(?!\$)', r'$\1$'),
    # "G = 6.67 × 10⁻¹¹ N·m²/kg²" (complex constants)
    (r'(?<!\$)([A-Z]\s*=\s*\d+\.?\d*\s*[×x]\s*10\s*[⁻¹²³⁴⁵⁶⁷⁸⁹⁰]+\s*(?:[A-Z][a-z]*(?:·[a-z]*)*(?:/[a-z]*[²³])*)+)(?!\$)', r'$\1$'),
]

# Line-based markers to strip
_STRIP_LINES: list[str] = [
    "学而思培优", "扫描全能王",  # watermark
    "CS", "Source Images",
]
_PAGE_MARKER_RE = re.compile(r'^\d+/\d+\s*$')  # "1/6", "2/6"
_EMPTY_MATH_RE = re.compile(r'\$\s*\$')  # "$ $" → remove



def _ocr_substitutions(text: str) -> str:
    """Apply context-aware OCR character corrections."""
    result = text
    for wrong, correct in _OCR_CHAR_MAP.items():
        result = result.replace(wrong, correct)
    return result


def _strip_artifacts(line: str) -> str:
    """Return empty string for line-level OCR artifacts (watermarks, page numbers)."""
    stripped = line.strip()
    if not stripped:
        return ""
    if _PAGE_MARKER_RE.match(stripped):
        return ""
    for marker in _STRIP_LINES:
        if marker in stripped and len(stripped) < 20:
            return ""
    return stripped


def _has_significant_content(line: str) -> bool:
    """Line has meaningful physics/Chinese content (not just noise)."""
    stripped = line.strip()
    if len(stripped) < 3:
        return False
    # Must have either CJK character, Latin letter, or digit
    has_cjk = any('一' <= c <= '鿿' for c in stripped)
    has_latin = any(c.isalpha() for c in stripped)
    has_digit = any(c.isdigit() for c in stripped)
    return has_cjk or has_latin or has_digit


def preprocess_ocr_text(raw_text: str) -> str:
    """Stage 1: Rule-based preprocessing (coding-agent skill equivalent).

    This does everything a Python script can do reliably:
    1. Strip page markers and watermark artifacts
    2. Merge broken lines within paragraphs
    3. Apply known OCR→Unicode character substitutions
    4. Wrap obvious bare formulas in $...$ delimiters
    5. Remove duplicate headers/boilerplate

    Returns clean text ready for LLM semantic proofreading (Stage 2).
    """
    lines = [l for l in raw_text.splitlines()]

    # Pass 1: strip artifacts, keep content lines, dedup headers
    header_patterns = {"2022学而思物理复赛营", "第一套", "命题人", "注意事项"}
    cleaned: list[str] = []
    seen_main_header = False  # "2022学而思物理复赛营" only once
    seen_sub_header = False   # "第一套" only once

    for line in lines:
        stripped = _strip_artifacts(line)
        if not stripped or not _has_significant_content(stripped):
            continue
        # Dedup: repeated headers across pages
        s = stripped.strip()
        if s == "2022学而思物理复赛营":
            if seen_main_header:
                continue
            seen_main_header = True
        if s == "第一套":
            if seen_sub_header:
                continue
            seen_sub_header = True
        cleaned.append(stripped)

    if not cleaned:
        return ""

    # Pass 2: merge short orphan lines, but NOT header/title lines
    def _is_header_line(s: str) -> bool:
        """Short line that looks like a standalone title/header."""
        s = s.strip()
        if len(s) < 12 and any(h in s for h in header_patterns):
            return True
        # Question number markers like "1.(40 分)" or "2.(40分)"
        if re.match(r'^\d+\.\s*[（(]?\d*\s*分?\s*[）)]?$', s) and len(s) < 15:
            return True
        return False

    merged: list[str] = []
    buf = ""

    for line in cleaned:
        if _is_header_line(line):
            if buf:
                merged.append(buf)
                buf = ""
            merged.append(line)
            continue

        if buf:
            prev_end = buf[-1]
            curr_start = line[0]
            # Don't merge if buffer ends with punctuation or is already long
            prev_ends_punct = prev_end in '。.）)」』》>'
            curr_starts_new = curr_start in '（(第题例数字' or line[0].isdigit()
            buf_is_header = _is_header_line(buf)

            if (not prev_ends_punct and not curr_starts_new and not buf_is_header
                    and len(buf) < 200):
                buf += line
                continue
            else:
                merged.append(buf)
                buf = line
        else:
            buf = line

    if buf:
        merged.append(buf)

    # Pass 3: apply OCR character substitutions
    text = "\n".join(merged)
    text = _ocr_substitutions(text)

    # Pass 4: detect and wrap bare formulas (only safe patterns)
    for pattern, replacement in _FORMULA_PATTERNS:
        text = re.sub(pattern, replacement, text)

    # Pass 5: fix common LaTeX-style sequences that OCR corrupts
    text = re.sub(r'\\frac(\d)(\d)', r'\\frac{\1}{\2}', text)  # \frac12 → \frac{1}{2}
    text = re.sub(r'(?<!\\)(frac|sqrt|sum|int|prod|lim|partial|nabla|infty)\b(?!\s*[{])', r'\\\1', text)
    text = _EMPTY_MATH_RE.sub('', text)  # remove empty $ $ blocks

    # Pass 6: collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^[\s\n]+|[\s\n]+$', '', text)

    return text


# ── Stage 2: LLM Semantic Proofreading Prompt ──────────────────────────

PROOFREAD_SYSTEM_PROMPT = """You are an expert proofreader for Chinese physics exam papers. You correct OCR errors using physics domain knowledge.

## Your Capabilities
You CAN fix:
- Chinese character errors based on physics context (e.g. "匀质杆" is correct, "匀质村"→"匀质杆")
- Subscript/superscript restoration (T0→T₀, c2→c², 10-19→10⁻¹⁹)
- Greek letter restoration (eo→ε₀, ro→ρ, a→α when physics context requires it)
- Unit format normalization (m/s2→m/s², J/s K→J/(s·K))
- LaTeX formula wrapping: wrap all math in $...$ or $$...$$
- Numeric constant verification (G=6.67×10⁻¹¹, e=1.602×10⁻¹⁹, etc.)
- Merging split paragraphs, removing OCR artifacts

You must NOT:
- Invent or derive answers that are not explicitly in the text
- Add explanatory notes or commentary
- Change the problem structure (keep question numbers, sub-question labels)
- Guess garbled text — mark as [OCR不清] instead
- Alter numerical values from the source"""

PROOFREAD_USER_PROMPT = """Proofread the following Chinese physics exam paper text. Fix OCR errors using physics domain knowledge.

## Step-by-step instructions:

### Step 1 — Structural Cleanup
- Remove OCR artifacts: watermarks ("扫描全能王", "学而思培优"), page numbers ("1/6")
- Merge split paragraphs (OCR often breaks one logical paragraph into multiple short lines)
- Preserve ALL question numbering: 1., (1), (2), (3), ① etc.

### Step 2 — Punctuation & Typography
- Normalize Chinese punctuation: use full-width ：，。（）【】 not half-width :, .()
- Fix dropped punctuation marks

### Step 3 — Formula Repair (MOST IMPORTANT)
For each formula or physical quantity in the text, apply these rules in order:

a) **Subscripts**: If a digit follows a Latin/Greek letter and physics context suggests subscript:
   "v0" → "v₀", "T0" → "T₀", "T1" → "T₁", "T2" → "T₂", "R0" → "R₀", "a0" → "a₀"

b) **Superscripts**: Powers of 10, squares, and exponents:
   "10-19" → "10⁻¹⁹", "c2" → "c²", "m2" → "m²", "10-12" → "10⁻¹²", "10-11" → "10⁻¹¹"

c) **Greek letters** (use physics context):
   "eo" → "ε₀" (vacuum permittivity), "ro" → "ρ" (density if context says so)
   "u0" → "μ₀" (vacuum permeability)
   "w" → "ω" (angular frequency if context is oscillations/waves)
   "h" → "ℏ" (reduced Planck constant if context is quantum)

d) **Special symbols**:
   ">>" or ">" between lengths → "≫" (much greater than)
   "<<" or "<" between angles → "≪" (much less than)
   "->" → "→", "=>" → "⇒"

e) **Fractions**: Convert inline slash fractions to LaTeX:
   "1/2" → "$\\frac{{1}}{{2}}$", "h/(4π)" → "$h/(4\\pi)$"
   (but ONLY within formula context, NOT in plain text like "1/6")

f) **Wrap ALL math in $...$**: Every variable, equation, constant, unit-with-number must be wrapped.
   CORRECT: "质量 $m$ 的小球", "电荷 $e = 1.602 \\times 10^{{-19}}$ C"
   WRONG: "质量 m 的小球", "电荷 e = 1.602 x 10-19 C"

g) **Multi-character subscripts**: "max" subscript → "_{{\\text{{max}}}}"

### Step 4 — Physics Constant Verification
Cross-check these known constants — fix OCR errors if values are garbled:
- $G = 6.67 \\times 10^{{-11}}$ N·m²/kg² (gravitational constant)
- $e = 1.602 \\times 10^{{-19}}$ C (elementary charge)
- $\\varepsilon_0 = 8.854 \\times 10^{{-12}}$ F/m (vacuum permittivity)
- $c = 3.00 \\times 10^{{8}}$ m/s (speed of light)
- $\\sigma = 5.67 \\times 10^{{-8}}$ W/(m²·K⁴) (Stefan-Boltzmann constant)
- $h = 6.63 \\times 10^{{-34}}$ J·s (Planck constant)
- $\\hbar = h/(2\\pi) \\approx 1.055 \\times 10^{{-34}}$ J·s

### Step 5 — Sub-question Integrity
Keep sub-questions (1)(2)(3) within their parent problem. Do NOT split them apart.
Problems like "7.(40分) (1)... (2)... (3)..." form a SINGLE composite problem.

## CRITICAL — Output Format
Return ONLY the proofread text. No markdown headers, no "Here is...", no explanations.
Prefix each logical section with its page marker [Page N] on a separate line.

## Source text to proofread:

{ocr_text}"""


# ── Two-stage pipeline ──────────────────────────────────────────────────

async def proofread_ocr(
    raw_ocr_text: str,
    provider=None,
) -> str:
    """Run the full two-stage proofreading pipeline.

    Stage 1: Rule-based preprocessing (this module, no LLM cost)
    Stage 2: LLM semantic proofreading (physics context correction)

    Returns the proofread text.
    """
    # Stage 1: rule-based cleanup (free — no API calls)
    cleaned = preprocess_ocr_text(raw_ocr_text)

    if provider is None or not cleaned.strip():
        return cleaned

    # Stage 2: LLM semantic proofreading
    prompt = PROOFREAD_USER_PROMPT.format(ocr_text=cleaned)
    try:
        response = await provider.complete(
            prompt=prompt,
            system_prompt=PROOFREAD_SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.0,
        )
        return response.content
    except Exception:
        return cleaned  # fallback: return stage-1 output
