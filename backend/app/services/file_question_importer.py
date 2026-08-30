"""Import arbitrary source files into the file-first question store.

The importer deliberately writes the production source of truth as simple files:

    questions/<id>/question.md
    questions/<id>/answer.md
    questions/<id>/assets/*
    questions/<id>/metadata.yaml

LLM assistance is optional. When enabled it may split a source into multiple
simple question/answer file pairs, but it must not introduce a rigid question
schema.
"""

from __future__ import annotations

import json
import base64
import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.file_question_store import (
    FileQuestion,
    question_dir,
    read_question,
    rebuild_index,
    validate_asset_payload,
    validate_question_id,
    write_question,
)
from app.services.file_question_candidates import create_candidate
from app.services.llm import LLMNotConfiguredError, get_llm_provider
from app.services.parsers import ParsedDocument, get_parser


EXT_TO_SOURCE_TYPE = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".docx": "docx",
    ".doc": "docx",
    ".json": "json",
    ".tex": "tex",
    ".latex": "tex",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".tif": "image",
    ".bmp": "image",
    ".webp": "image",
}

SUPPORTED_EXTENSIONS = set(EXT_TO_SOURCE_TYPE.keys())
MAX_LLM_SOURCE_CHARS = 24_000
VISION_PAGE_BATCH_SIZE = 2


@dataclass
class SourceAsset:
    filename: str
    payload: bytes
    page_number: int | None = None
    markdown_ref: str | None = None
    local_path: Path | None = None


@dataclass
class ImportResult:
    questions: list[FileQuestion] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    llm_used: bool = False


def source_type_from_filename(filename: str) -> str | None:
    return EXT_TO_SOURCE_TYPE.get(Path(filename).suffix.lower())


def llm_import_config() -> dict[str, Any]:
    enabled = bool(settings.LLM_ENABLED)
    configured = bool(settings.LLM_ENABLED and settings.LLM_API_KEY)
    supports_vision = False
    vision_configured = False
    if configured:
        try:
            provider = get_llm_provider()
            supports_vision = bool(getattr(provider, "supports_vision", False))
            vision_configured = supports_vision
        except Exception:
            supports_vision = False
            vision_configured = False
    return {
        "enabled": enabled,
        "configured": configured,
        "provider": settings.LLM_PROVIDER,
        "model": settings.LLM_MODEL,
        "supports_vision": supports_vision,
        "vision_configured": vision_configured,
    }


def _safe_asset_name(name: str, fallback: str) -> str:
    suffix = Path(name).suffix.lower()
    stem = Path(name).stem or Path(fallback).stem
    clean_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-")
    clean_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix) or Path(fallback).suffix
    return f"{clean_stem or Path(fallback).stem}{clean_suffix}"


def _load_parser_modules() -> None:
    import app.services.parsers.docx  # noqa: F401
    import app.services.parsers.markdown  # noqa: F401
    import app.services.parsers.pdf  # noqa: F401
    import app.services.parsers.tex  # noqa: F401


def _title_from_filename(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip() or filename


def _metadata(
    *,
    original_filename: str,
    source_type: str,
    import_method: str,
    source_document_hash: str,
    extra: dict | None = None,
) -> dict:
    payload = {
        "title": _title_from_filename(original_filename),
        "source_filename": original_filename,
        "source_type": source_type,
        "source_document_hash": source_document_hash,
        "import_method": import_method,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_question_id(
    *,
    source_document_hash: str,
    original_filename: str,
    item: dict[str, Any] | None,
    item_index: int,
) -> str:
    explicit = item.get("question_id") if item else None
    if isinstance(explicit, str) and explicit.strip():
        return validate_question_id(explicit)

    metadata = item.get("metadata") if item and isinstance(item.get("metadata"), dict) else {}
    logical_key = next(
        (
            str(metadata[key]).strip()
            for key in ("original_problem_number", "question_number", "problem_number")
            if metadata.get(key) not in (None, "")
        ),
        "",
    )
    if not logical_key:
        pages = metadata.get("source_pages")
        page_key = ",".join(str(page) for page in pages) if isinstance(pages, list) else ""
        title = str(metadata.get("title") or "").strip()
        logical_key = (
            f"item-{item_index}|{page_key}|{title}"
            if page_key or title
            else f"item-{item_index}"
        )
    digest = hashlib.sha256(
        f"{source_document_hash}\0{Path(original_filename).name}\0{logical_key}".encode("utf-8")
    ).hexdigest()[:16]
    return f"qf_{digest}"


def _page_markdown(page_number: int, text: str, image_filename: str | None) -> str:
    parts: list[str] = [f"## Page {page_number}"]
    if text.strip():
        parts.append(text.strip())
    if image_filename:
        parts.append(f"![Page {page_number}](assets/{image_filename})")
    return "\n\n".join(parts)


def _parsed_document_to_markdown(
    parsed: ParsedDocument,
    page_assets: list[SourceAsset],
) -> str:
    page_asset_map = {
        asset.page_number: asset.filename
        for asset in page_assets
        if asset.page_number is not None
    }
    if parsed.pages:
        parts = [
            _page_markdown(page.page_number, page.raw_text or "", page_asset_map.get(page.page_number))
            for page in parsed.pages
        ]
        return "\n\n".join(part for part in parts if part.strip()).strip()

    body = parsed.raw_text.strip()
    if page_assets:
        body = "\n\n".join(
            [body] + [asset.markdown_ref or f"![{asset.filename}](assets/{asset.filename})" for asset in page_assets]
        )
    return body.strip()


def _page_images_to_markdown(original_filename: str, page_assets: list[SourceAsset]) -> str:
    """Represent standalone image files as Markdown image pages.

    Do not use this for PDF page renders. Rendered PDF pages are whole-paper
    source material for OCR/vision review, not per-question assets.
    """
    title = _title_from_filename(original_filename)
    parts: list[str] = [f"# {title}"]
    image_assets = [asset for asset in page_assets if asset.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    for asset in image_assets:
        label = f"Page {asset.page_number}" if asset.page_number else Path(asset.filename).stem
        parts.append(f"![{label}](assets/{asset.filename})")
    return "\n\n".join(parts).strip()


def _is_page_image_asset(asset: SourceAsset) -> bool:
    return asset.page_number is not None and asset.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))


def _asset_data_uri(asset: SourceAsset) -> str:
    suffix = Path(asset.filename).suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    encoded = base64.b64encode(asset.payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _markdown_asset_names(text: str) -> set[str]:
    names = {Path(match).name for match in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)}
    names.update(Path(match).name for match in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text))
    return {name for name in names if name}


def _looks_like_rendered_pdf_page(filename: str) -> bool:
    stem = Path(filename).stem.lower()
    suffix = Path(filename).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".webp"} and bool(
        re.fullmatch(r"(?:page|p)[_-]?\d{1,4}", stem)
    )


def _strip_rendered_page_image_refs(body: str) -> tuple[str, list[str]]:
    """Remove whole-page PDF render references from model output.

    Page renders are recognition evidence for OCR/vision models. They are not
    per-question image assets and must not survive into ``question.md``.
    """
    removed: list[str] = []

    def markdown_repl(match: re.Match) -> str:
        alt = match.group(1) or ""
        raw_path = match.group(2) or ""
        filename = Path(raw_path).name
        if not _looks_like_rendered_pdf_page(filename):
            return match.group(0)
        removed.append(filename)
        label = alt.strip() or filename
        return f"[{label} 需人工裁剪为独立题图]"

    def latex_repl(match: re.Match) -> str:
        raw_path = match.group(2) or ""
        filename = Path(raw_path).name
        if not _looks_like_rendered_pdf_page(filename):
            return match.group(0)
        removed.append(filename)
        return r"\textit{[题图需人工裁剪为独立图片资产]}"

    cleaned = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", markdown_repl, body)
    cleaned = re.sub(r"\\includegraphics(\[[^\]]*\])?\{([^}]+)\}", latex_repl, cleaned)
    return cleaned.strip(), sorted(set(removed))


def _text_file_to_markdown(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix in {".tex", ".latex"}:
        return text, "latex"
    if suffix == ".txt":
        return text, "text"
    return text, "markdown"


def _structured_json_items(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid structured question JSON: {exc}") from exc
    items = _normalize_llm_items(raw)
    if not items:
        raise ValueError("Structured JSON must be a non-empty array of question_body/answer_body/metadata records.")
    return items


def _structured_json_assets(item: dict, source_path: Path) -> list[SourceAsset]:
    """Load independent assets referenced by a structured JSON item.

    Assets are resolved from ``<json-dir>/assets`` and only when explicitly
    referenced by Markdown/LaTeX image syntax in the body fields.
    """
    asset_names = _markdown_asset_names(item.get("question_body", "")) | _markdown_asset_names(item.get("answer_body", ""))
    if not asset_names:
        return []
    assets_dir = source_path.parent / "assets"
    loaded: list[SourceAsset] = []
    for name in sorted(asset_names):
        if _looks_like_rendered_pdf_page(name):
            raise ValueError(f"Structured JSON may not reference rendered PDF page image as an asset: {name}")
        path = assets_dir / name
        if not path.exists() or not path.is_file():
            raise ValueError(f"Referenced asset not found: {path}")
        payload = path.read_bytes()
        validate_asset_payload(name, payload)
        loaded.append(SourceAsset(filename=name, payload=payload, local_path=path))
    return loaded


def _preflight_structured_json_items(
    items: list[dict],
    source_path: Path,
) -> dict[int, list[SourceAsset]]:
    """Validate structured JSON before writing any question directories."""
    seen_ids: set[str] = set()
    assets_by_index: dict[int, list[SourceAsset]] = {}

    for index, item in enumerate(items):
        raw_qid = item.get("question_id")
        if raw_qid:
            qid = validate_question_id(str(raw_qid))
            if qid in seen_ids:
                raise ValueError(f"Duplicate question_id in structured JSON: {qid}")
            seen_ids.add(qid)
        assets_by_index[index] = _structured_json_assets(item, source_path)

    return assets_by_index


def _render_pdf_page_assets(source_path: Path, work_dir: Path) -> list[SourceAsset]:
    from app.services.parsers.pdf import render_pdf_pages

    rendered_dir = work_dir / "rendered-pages"
    page_paths = render_pdf_pages(source_path, rendered_dir, dpi=250)
    return [
        SourceAsset(
            filename=f"page_{index:03d}.png",
            payload=path.read_bytes(),
            page_number=index,
            local_path=path,
        )
        for index, path in enumerate(page_paths, start=1)
    ]


def _image_to_markdown(path: Path, original_filename: str) -> tuple[str, list[SourceAsset], list[str]]:
    asset_name = _safe_asset_name(original_filename, f"image{path.suffix.lower() or '.png'}")
    asset = SourceAsset(
        filename=asset_name,
        payload=path.read_bytes(),
        page_number=1,
        markdown_ref=f"![Page 1](assets/{asset_name})",
        local_path=path,
    )
    body = _page_images_to_markdown(original_filename, [asset])
    warnings = ["Standalone image import kept the image as the question asset. Use a vision-capable LLM or manual edit for Markdown/LaTeX text."]
    return (body, [asset], warnings)


def _extract_docx_images(path: Path) -> list[SourceAsset]:
    assets: list[SourceAsset] = []
    try:
        with zipfile.ZipFile(path) as archive:
            media_names = [
                name
                for name in archive.namelist()
                if name.startswith("word/media/") and Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            ]
            for index, name in enumerate(media_names, start=1):
                suffix = Path(name).suffix.lower()
                filename = f"media_{index:03d}{suffix}"
                assets.append(
                    SourceAsset(
                        filename=filename,
                        payload=archive.read(name),
                        markdown_ref=f"![Media {index}](assets/{filename})",
                    )
                )
    except Exception:
        return []
    return assets


def _append_asset_refs(body: str, assets: list[SourceAsset]) -> str:
    refs = [asset.markdown_ref for asset in assets if asset.markdown_ref]
    if not refs:
        return body.strip()
    existing = body
    missing_refs = [ref for ref in refs if ref and ref not in existing]
    if not missing_refs:
        return body.strip()
    return "\n\n".join([body.strip(), "## Source Images", *missing_refs]).strip()


def _normalize_llm_items(raw_items: Any) -> list[dict]:
    if not isinstance(raw_items, list):
        return []
    items: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        body = str(raw.get("question_body") or raw.get("question") or "").strip()
        if len(body) < 10:
            continue
        answer = str(raw.get("answer_body") or raw.get("answer") or "").strip()
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        source_pages = raw.get("source_pages")
        if not isinstance(source_pages, list):
            source_pages = metadata.get("source_pages") if isinstance(metadata.get("source_pages"), list) else []
        clean_source_pages = []
        for page in source_pages:
            try:
                clean_source_pages.append(int(page))
            except (TypeError, ValueError):
                continue
        concepts = raw.get("knowledge_points") or raw.get("concepts") or metadata.get("knowledge_points")
        if concepts and "knowledge_points" not in metadata:
            metadata["knowledge_points"] = concepts
        if clean_source_pages:
            metadata["source_pages"] = clean_source_pages
        if raw.get("human_review_needed") is not None and "human_review_needed" not in metadata:
            metadata["human_review_needed"] = bool(raw.get("human_review_needed"))
        items.append(
            {
                "question_id": raw.get("question_id") if isinstance(raw.get("question_id"), str) else None,
                "question_body": body,
                "answer_body": answer,
                "metadata": metadata,
                "source_pages": clean_source_pages,
            }
        )
    return items


def _parse_llm_json(content: str) -> list[dict]:
    def decode(candidate: str) -> Any:
        # Start with strict JSON, then tolerate two common model-output defects:
        # unnecessary apostrophe escapes and literal newlines inside strings.
        variants = (candidate, candidate.replace("\\'", "'"))
        for strict in (True, False):
            for variant in dict.fromkeys(variants):
                try:
                    return json.loads(variant, strict=strict)
                except json.JSONDecodeError:
                    continue
        return None

    # Parse the entire fenced payload. Matching the array itself with a
    # non-greedy regex truncates valid JSON at nested arrays such as
    # knowledge_points or source_pages.
    fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
    for block in fenced_blocks:
        raw_items = decode(block.strip())
        if raw_items is not None:
            return _normalize_llm_items(raw_items)

    # For an unfenced response, find the first array and let JSONDecoder locate
    # its real closing bracket, including nested arrays and brackets in strings.
    for match in re.finditer(r"\[", content):
        candidate = content[match.start():]
        variants = (candidate, candidate.replace("\\'", "'"))
        for strict in (True, False):
            decoder = json.JSONDecoder(strict=strict)
            for variant in dict.fromkeys(variants):
                try:
                    raw_items, _ = decoder.raw_decode(variant)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw_items, list):
                    return _normalize_llm_items(raw_items)

    # Not JSON at all — LLM refused or replied with text
    return []


def _has_vision_provider() -> bool:
    config = llm_import_config()
    return bool(config["configured"] and config["supports_vision"])


async def _ocr_page_hints(page_assets: list[SourceAsset]) -> list[tuple[str, int, str]]:
    """Best-effort OCR hints grouped by page.

    These hints are never treated as source of truth for scanned PDFs. They are
    only sent alongside page images to reduce vision model effort and aid search.
    """
    hints: list[tuple[str, int, str]] = []
    if not page_assets:
        return hints

    try:
        from app.services.ocr_p2t import ocr_page
        import asyncio as _asyncio
    except Exception:
        return hints

    for asset in sorted(page_assets, key=lambda a: a.page_number or 0):
        page_path = asset.local_path
        if not page_path or not page_path.exists():
            continue
        try:
            result = await _asyncio.to_thread(
                ocr_page,
                page_path,
                asset.page_number or 1,
                settings.OCR_LANG,
            )
        except Exception:
            continue
        text = result.full_text.strip()
        if text:
            hints.append((text, asset.page_number or 1, asset.filename))
    return hints


def _problem_number_hints(ocr_page_texts: list[tuple[str, int, str]]) -> list[int]:
    numbers: list[int] = []
    seen: set[int] = set()
    for text, _, _ in ocr_page_texts:
        for match in re.finditer(r"(?:^|\n)\s*(\d{1,2})\s*[.．]\s*(?:[（(]\s*\d+\s*分\s*[）)])?", text):
            num = int(match.group(1))
            if num not in seen:
                numbers.append(num)
                seen.add(num)
    return numbers


def _paper_metadata_from_text(original_filename: str, ocr_page_texts: list[tuple[str, int, str]]) -> dict[str, Any]:
    text = "\n".join(page_text for page_text, _, _ in ocr_page_texts)
    total_problems = None
    total_score = None
    problem_match = re.search(r"共\s*(\d+)\s*题", text)
    score_match = re.search(r"(?:满分|总分)\s*(\d+)\s*分", text)
    if problem_match:
        total_problems = int(problem_match.group(1))
    if score_match:
        total_score = int(score_match.group(1))
    return {
        "title": _title_from_filename(original_filename),
        "total_problems": total_problems,
        "total_score": total_score,
        "possible_problem_numbers": _problem_number_hints(ocr_page_texts),
    }


async def _vision_split_into_file_questions(
    *,
    page_assets: list[SourceAsset],
    ocr_page_texts: list[tuple[str, int, str]],
    original_filename: str,
) -> list[dict]:
    config = llm_import_config()
    if not config["enabled"]:
        raise LLMNotConfiguredError("LLM assisted import is disabled. Set LLM_ENABLED=true in backend .env.")
    if not config["configured"]:
        raise LLMNotConfiguredError("LLM assisted import needs LLM_API_KEY in backend .env.")
    if not config["supports_vision"]:
        raise LLMNotConfiguredError(
            "Scanned PDF/image LLM import requires a vision-capable model. "
            "Use provider=anthropic or set LLM_VISION_ENABLED=true for a compatible OpenAI-style vision model."
        )

    provider = get_llm_provider()
    sorted_assets = [asset for asset in sorted(page_assets, key=lambda a: a.page_number or 0) if _is_page_image_asset(asset)]
    if not sorted_assets:
        return []

    paper_metadata = _paper_metadata_from_text(original_filename, ocr_page_texts)

    async def import_page_batch(batch_assets: list[SourceAsset]) -> list[dict]:
        batch_pages = [asset.page_number or 1 for asset in batch_assets]
        batch_page_set = set(batch_pages)
        batch_hints = [
            hint for hint in ocr_page_texts
            if hint[1] in batch_page_set
        ]
        ocr_hint_text = "\n\n".join(
            f"## Page {page_num} OCR hint\n{text}"
            for text, page_num, _ in batch_hints
        )
        if len(ocr_hint_text) > MAX_LLM_SOURCE_CHARS:
            ocr_hint_text = ocr_hint_text[:MAX_LLM_SOURCE_CHARS] + "\n[OCR hint truncated]"

        page_list = ", ".join(
            f"{asset.page_number}:{asset.filename}" for asset in batch_assets
        )
        prompt = f"""Import this page batch from a scanned physics paper into simple question files.

Source: {original_filename}
Hints: title={paper_metadata.get("title")}; total_problems={paper_metadata.get("total_problems")}; total_score={paper_metadata.get("total_score")}; OCR_numbers={paper_metadata.get("possible_problem_numbers")}; pages={page_list}

Rules:
- Page images are authoritative; OCR is only a hint.
- Only pages listed above are available in this batch. Never invent content from other pages.
- Split only visible major problems like 1. / 2. / 7.(40分). Keep subparts (1)(2)(3), ①②③ inside the parent problem.
- Merge continuations across the supplied pages. If a visible problem is incomplete because it continues outside this batch, keep the visible text and set human_review_needed=true.
- Recover visible problem numbers missed by OCR; ignore isolated OCR number noise with no problem body.
- Write Markdown with LaTeX math delimiters $...$ or $$...$$.
- Fill answer_body only for explicit source answers; never solve.
- Do not reference/copy rendered full-page images as assets. If a figure is needed but not cropped, write [图见原 PDF 第 x 页，需人工裁剪] and set human_review_needed=true.
- metadata must include title, knowledge_points, source_pages, human_review_needed.

Return ONLY a JSON array:
[{{"question_body":"...","answer_body":"","metadata":{{"title":"...","knowledge_points":["..."],"source_pages":[1],"human_review_needed":false}}}}]

OCR hints:
{ocr_hint_text or "[no OCR hints available]"}"""

        response = await provider.complete_with_images(
            image_data=[_asset_data_uri(asset) for asset in batch_assets],
            prompt=prompt,
            system_prompt=(
                "Vision-first physics question importer. Page images are authoritative. Return strict JSON only."
            ),
            max_tokens=settings.LLM_MAX_TOKENS,
            temperature=0.0,
        )
        items = _parse_llm_json(response.content)
        for item in items:
            if item.get("source_pages"):
                continue
            item["source_pages"] = list(batch_pages)
            metadata = dict(item.get("metadata") or {})
            metadata["source_pages"] = list(batch_pages)
            item["metadata"] = metadata
        return items

    async def import_single_page_as_markdown(asset: SourceAsset) -> dict | None:
        page_number = asset.page_number or 1
        page_hints = [text for text, page, _ in ocr_page_texts if page == page_number]
        ocr_hint = "\n\n".join(page_hints)[:MAX_LLM_SOURCE_CHARS]
        prompt = f"""Transcribe the visible physics question content on this scanned page as Markdown.

Source: {original_filename}; page: {page_number}

Rules:
- Preserve every visible major problem number, subpart, symbol, formula, and condition in reading order.
- Use $...$ or $$...$$ for LaTeX math.
- Do not solve, summarize, or invent missing content.
- For an uncropped figure, write [图见原 PDF 第 {page_number} 页，需人工裁剪].
- Return Markdown text only, without JSON or a code fence.

OCR hint (may be inaccurate):
{ocr_hint or "[no OCR hint available]"}"""
        response = await provider.complete_with_images(
            image_data=[_asset_data_uri(asset)],
            prompt=prompt,
            system_prompt=(
                "Physics page transcriber. The image is authoritative. Return Markdown only."
            ),
            max_tokens=settings.LLM_MAX_TOKENS,
            temperature=0.0,
        )
        body = (response.content or "").strip()
        fenced = re.fullmatch(
            r"```(?:markdown|md)?\s*(.*?)\s*```",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if fenced:
            body = fenced.group(1).strip()
        if len(body) < 10:
            return None
        return {
            "question_id": None,
            "question_body": body,
            "answer_body": "",
            "metadata": {
                "title": paper_metadata.get("title"),
                "knowledge_points": [],
                "source_pages": [page_number],
                "human_review_needed": True,
                "vision_fallback": "page_markdown_transcription",
            },
            "source_pages": [page_number],
        }

    async def recover_single_page(asset: SourceAsset) -> list[dict]:
        page_items = await import_page_batch([asset])
        if page_items:
            return page_items
        markdown_item = await import_single_page_as_markdown(asset)
        return [markdown_item] if markdown_item else []

    all_items: list[dict] = []
    failed_pages: list[int] = []
    for offset in range(0, len(sorted_assets), VISION_PAGE_BATCH_SIZE):
        batch = sorted_assets[offset:offset + VISION_PAGE_BATCH_SIZE]
        batch_items = await import_page_batch(batch)
        if batch_items:
            all_items.extend(batch_items)
            continue

        # A two-page response may still be truncated or malformed. Retrying
        # page-by-page keeps one bad batch from discarding the whole document.
        if len(batch) > 1:
            for asset in batch:
                page_items = await recover_single_page(asset)
                if page_items:
                    all_items.extend(page_items)
                else:
                    failed_pages.append(asset.page_number or 1)
        else:
            page_items = await import_single_page_as_markdown(batch[0])
            if page_items:
                all_items.append(page_items)
            else:
                failed_pages.append(batch[0].page_number or 1)

    if failed_pages:
        page_text = ", ".join(str(page) for page in failed_pages)
        raise ValueError(
            f"Vision model returned no usable question records for PDF page(s): {page_text}. "
            "Other page batches were not imported so the document can be retried safely."
        )
    return all_items


async def _llm_split_into_file_questions(source_text: str, original_filename: str) -> list[dict]:
    config = llm_import_config()
    if not config["enabled"]:
        raise LLMNotConfiguredError("LLM assisted import is disabled. Set LLM_ENABLED=true in backend .env.")
    if not config["configured"]:
        raise LLMNotConfiguredError("LLM assisted import needs LLM_API_KEY in backend .env.")

    provider = get_llm_provider()
    clipped = source_text[:MAX_LLM_SOURCE_CHARS]
    # Pass 1: LLM proofreads only. Pass 2 below splits deterministically by
    # major problem numbers so the model cannot invent a question structure.
    proofread_prompt = f"""Clean OCR text from a physics paper for Markdown/TeX storage.

Source: {original_filename}

Keep the original order and all major problem numbers. Remove paper headers, watermarks, page numbers, and isolated OCR noise. Fix only obvious OCR substitutions from context. Add blank lines before subparts like (1), (2), (3). Wrap math in $...$ or $$...$$. Do not split, reorder, summarize, delete problem numbers, add explanations, or derive answers.

Return cleaned text only.

Source text:
{clipped}"""

    response = await provider.complete(
        prompt=proofread_prompt,
        system_prompt="Physics OCR proofreader. Preserve structure and problem numbers. Return cleaned text only.",
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=0.0,
    )
    proofread_text = response.content

    # Pass 2: Regex-based problem splitting for text-like sources only.
    # Scanned PDFs/images are handled by the vision-first path above; do not
    # use this text-only splitter for OCR page text.
    import re as _split_re

    # Split by major problem boundaries: "N.(分数)" at line start
    _PROBLEM_BOUNDARY = _split_re.compile(
        r'(?:^|\n)(\d+)\.\s*(?:[（(]\s*\d+\s*分\s*[）)])',
        _split_re.MULTILINE,
    )
    problem_parts = _PROBLEM_BOUNDARY.split(proofread_text)

    if len(problem_parts) <= 2:
        # No clear problem boundaries — treat as single question
        llm_items = [{
            "question_body": proofread_text.strip(),
            "answer_body": "",
            "metadata": {
                "title": _title_from_filename(original_filename),
                "knowledge_points": [],
                "human_review_needed": True,
            },
            "source_pages": [1],
        }]
    else:
        # Reconstruct: splits = [preamble, num1, content1, num2, content2, ...]
        llm_items = []
        for i in range(1, len(problem_parts) - 1, 2):
            num = problem_parts[i]
            content = problem_parts[i + 1] if i + 1 < len(problem_parts) else ""
            body = f"{num}.{content.strip()}"
            if len(body) < 20:
                continue
            llm_items.append({
                "question_body": body,
                "answer_body": "",
                "metadata": {
                    "title": f"问题{num}",
                    "knowledge_points": [],
                    "human_review_needed": True,
                },
                "source_pages": [1],
            })
    return llm_items


def _ensure_math_delimiters(text: str) -> str:
    """Post-process LLM output: strip erroneous outermost $...$ wrapping and
    ensure internal formulas have proper $...$ delimiters.

    DeepSeek sometimes wraps the ENTIRE question body in a single $...$ block
    (e.g. ``$1. 中文题干 $m$ 公式...$``), which makes xelatex treat Chinese
    text as math mode → ``￿`` garbage characters.
    """
    text = text.strip()

    # Strip leading/trailing $ if they wrap Chinese text (DeepSeek bug)
    if text.startswith("$") and text.endswith("$"):
        # Count inner $ to check if this is a wrapper or intentional
        inner = text[1:-1]
        has_cjk = any('一' <= c <= '鿿' for c in inner)
        if has_cjk:
            # This is a wrapper — strip it
            text = inner

    # Remove "## Source Images" section if present (page image refs are noise)
    import re as _re
    text = _re.sub(r'\n*##\s*Source\s*Images\s*\n!\[[^\]]*\]\([^)]+\)\s*', '', text)

    # NOTE: do NOT use schemas/question.py's _ensure_math_delimiters here.
    # That function wraps the ENTIRE text in $...$ if it contains ANY LaTeX
    # command (e.g. \theta), which turns Chinese text into TeX math mode.
    # The DeepSeek output already has proper inline $...$ wrapping.
    return text


def _assets_for_llm_item(item: dict, all_assets: list[SourceAsset]) -> list[SourceAsset]:
    """Return explicitly referenced real question assets for an LLM-split item.

    ``source_pages`` points back to rendered whole-page PDF images for audit, but
    those page renders are not question assets and must not be copied into
    question directories. Only assets explicitly referenced by Markdown/LaTeX
    image syntax are included.
    """
    referenced_names = _markdown_asset_names(item.get("question_body", "")) | _markdown_asset_names(item.get("answer_body", ""))
    selected: list[SourceAsset] = []
    for asset in all_assets:
        if _looks_like_rendered_pdf_page(asset.filename):
            continue
        if asset.filename in referenced_names:
            selected.append(asset)
    return selected


def _write_single_question(
    *,
    question_body: str,
    answer_body: str,
    original_filename: str,
    source_type: str,
    source_document_hash: str,
    import_method: str,
    body_format: str,
    assets: list[SourceAsset],
    question_id: str | None = None,
    metadata_extra: dict | None = None,
    overwrite: bool = False,
) -> FileQuestion:
    metadata = _metadata(
        original_filename=original_filename,
        source_type=source_type,
        source_document_hash=source_document_hash,
        import_method=import_method,
        extra=metadata_extra,
    )
    if question_id and question_dir(question_id).exists():
        existing = read_question(question_id)
        if existing.metadata.get("source_document_hash") == source_document_hash:
            metadata["imported_at"] = existing.metadata.get("imported_at", metadata["imported_at"])
    return write_question(
        question_id=question_id,
        question_body=question_body,
        answer_body=answer_body,
        question_format=body_format,
        answer_format="markdown",
        metadata=metadata,
        assets=[(asset.filename, asset.payload) for asset in assets],
        overwrite=overwrite,
        idempotent=not overwrite,
    )


def _queue_candidate(
    *,
    question_body: str,
    answer_body: str,
    original_filename: str,
    source_type: str,
    source_document_hash: str,
    import_method: str,
    body_format: str,
    assets: list[SourceAsset],
    question_id: str,
    metadata_extra: dict | None,
    warnings: list[str],
) -> dict[str, Any]:
    metadata = _metadata(
        original_filename=original_filename,
        source_type=source_type,
        source_document_hash=source_document_hash,
        import_method=import_method,
        extra=metadata_extra,
    )
    metadata["human_review_needed"] = True
    return create_candidate(
        question_body=question_body,
        answer_body=answer_body,
        question_format=body_format,
        answer_format="markdown",
        metadata=metadata,
        assets=[(asset.filename, asset.payload) for asset in assets],
        proposed_question_id=question_id,
        source_filename=original_filename,
        source_type=source_type,
        source_document_hash=source_document_hash,
        warnings=warnings,
    )


def _collect_candidate_result(
    candidate: dict[str, Any],
    *,
    questions: list[FileQuestion],
    candidates: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    """Classify a deterministic reimport using its persisted review state."""
    state = str(candidate.get("state") or "")
    if state == "needs_review":
        candidates.append(candidate)
        return
    if state == "committed":
        committed_question_id = str(candidate.get("committed_question_id") or "")
        if not committed_question_id:
            raise ValueError("Committed candidate is missing committed_question_id")
        questions.append(read_question(committed_question_id))
        return
    if state == "rejected":
        warnings.append(
            "A matching candidate was previously rejected and was not queued again: "
            + str(candidate.get("candidate_id") or "")
        )
        return
    raise ValueError(f"Unsupported candidate state: {state or '(empty)'}")


def _requires_review(
    *,
    source_type: str,
    import_method: str,
    metadata: dict[str, Any],
    warnings: list[str],
    skip_llm_review: bool = False,
) -> bool:
    if bool(metadata.get("human_review_needed")) or warnings:
        return True
    if import_method == "llm_assisted":
        return not skip_llm_review
    return source_type in {"pdf", "image", "docx"}


async def import_source_file(
    *,
    source_path: Path,
    original_filename: str,
    use_llm_assist: bool = False,
    overwrite: bool = False,
    rebuild_after: bool = True,
) -> ImportResult:
    source_type = source_type_from_filename(original_filename)
    if not source_type:
        raise ValueError(f"Unsupported file type: {Path(original_filename).suffix or original_filename}")
    source_document_hash = _file_sha256(source_path)

    _load_parser_modules()
    warnings: list[str] = []
    body = ""
    body_format = "markdown"
    assets: list[SourceAsset] = []
    page_assets: list[SourceAsset] = []
    ocr_page_texts: list[tuple[str, int, str]] = []
    parsed: ParsedDocument | None = None

    if source_type == "json":
        llm_items = _structured_json_items(source_path)
    elif source_type in {"markdown", "tex", "text"}:
        body, body_format = _text_file_to_markdown(source_path)
    elif source_type == "image":
        if use_llm_assist:
            page_assets = [
                SourceAsset(
                    filename=_safe_asset_name(original_filename, f"image{source_path.suffix.lower() or '.png'}"),
                    payload=source_path.read_bytes(),
                    page_number=1,
                    local_path=source_path,
                )
            ]
            body = ""
        else:
            body, assets, image_warnings = _image_to_markdown(source_path, original_filename)
            warnings.extend(image_warnings)
    else:
        parser = get_parser(source_type)
        if not parser:
            raise ValueError(f"No parser registered for source type: {source_type}")
        parsed = parser(source_path)
        if source_type == "pdf":
            text_body = _parsed_document_to_markdown(parsed, [])
            extracted_text = parsed.all_text().strip() if parsed else ""
            is_scanned_or_weak_text = not extracted_text or len(extracted_text) <= 100
            if is_scanned_or_weak_text:
                # Whole-page renders are OCR/vision source material only. They
                # are deliberately not copied into question assets or embedded in
                # question.md.
                page_assets = _render_pdf_page_assets(source_path, source_path.parent)
                body = ""
            else:
                body = _append_asset_refs(text_body, assets)
        elif source_type == "docx":
            docx_assets = _extract_docx_images(source_path)
            assets.extend(docx_assets)
            body = _parsed_document_to_markdown(parsed, assets)
            body = _append_asset_refs(body, assets)

    if source_type != "json" and not body.strip() and not assets and not page_assets:
        raise ValueError("No readable question content was found in the source file.")

    llm_items: list[dict] = llm_items if source_type == "json" else []
    if use_llm_assist and source_type != "json":
        if page_assets:
            ocr_page_texts = await _ocr_page_hints(page_assets)
            llm_items = await _vision_split_into_file_questions(
                page_assets=page_assets,
                ocr_page_texts=ocr_page_texts,
                original_filename=original_filename,
            )
        else:
            # Text-like sources may use a text-only LLM. Scanned PDFs/images must
            # not use this path because text-only models cannot recover missed
            # page content or problem boundaries.
            from app.services.ocr_proofreader import preprocess_ocr_text

            source_text = body
            if parsed and parsed.all_text().strip() and len(parsed.all_text().strip()) > len(body.strip()):
                source_text = parsed.all_text()
            # Strip image markdown — noise for the LLM
            import re as _strip_re
            source_text = _strip_re.sub(r'!\[[^\]]*\]\([^)]+\)', '', source_text)
            source_text = _strip_re.sub(r'## Source Images', '', source_text)
            source_text = source_text.strip()
            source_text = preprocess_ocr_text(source_text)
            if source_text.strip():
                llm_items = await _llm_split_into_file_questions(source_text, original_filename)
        if not llm_items:
            warnings.append("LLM returned no usable question records.")

    questions: list[FileQuestion] = []
    candidates: list[dict[str, Any]] = []
    multi_page_vision_import = bool(
        use_llm_assist and page_assets and len(page_assets) > 1
    )
    if llm_items:
        structured_assets_by_index = (
            _preflight_structured_json_items(llm_items, source_path)
            if source_type == "json"
            else {}
        )
        for item_index, item in enumerate(llm_items):
            generated_question_id = _stable_question_id(
                source_document_hash=source_document_hash,
                original_filename=original_filename,
                item=item,
                item_index=item_index + 1,
            )
            item_assets = (
                structured_assets_by_index[item_index]
                if source_type == "json"
                else _assets_for_llm_item(item, assets)
            )
            item_metadata = dict(item.get("metadata") or {})
            item_warnings: list[str] = []
            # Post-process LLM output to ensure formulas have $...$ delimiters
            q_body = _ensure_math_delimiters(item["question_body"])
            a_body = _ensure_math_delimiters(item.get("answer_body", ""))
            q_body, removed_question_pages = _strip_rendered_page_image_refs(q_body)
            a_body, removed_answer_pages = _strip_rendered_page_image_refs(a_body)
            removed_page_refs = sorted(set(removed_question_pages + removed_answer_pages))
            if removed_page_refs:
                removed_warning = (
                    "Removed rendered PDF page image references from LLM output: "
                    + ", ".join(removed_page_refs)
                )
                warnings.append(removed_warning)
                item_warnings.append(removed_warning)
                item_metadata["human_review_needed"] = True
                item_metadata["asset_review_note"] = (
                    "LLM referenced whole-page PDF renders. These were not imported as question assets; "
                    "crop the actual figure region into assets/ if the problem needs an image."
                )
            item_body = _append_asset_refs(q_body, item_assets)
            import_method = "structured_json" if source_type == "json" else "llm_assisted"
            if _requires_review(
                source_type=source_type,
                import_method=import_method,
                metadata=item_metadata,
                warnings=item_warnings,
                skip_llm_review=multi_page_vision_import,
            ):
                candidate = _queue_candidate(
                    question_body=item_body,
                    answer_body=a_body,
                    original_filename=original_filename,
                    source_type=source_type,
                    source_document_hash=source_document_hash,
                    import_method=import_method,
                    body_format="markdown",
                    assets=item_assets,
                    question_id=generated_question_id,
                    metadata_extra=item_metadata,
                    warnings=item_warnings,
                )
                _collect_candidate_result(
                    candidate,
                    questions=questions,
                    candidates=candidates,
                    warnings=warnings,
                )
            else:
                questions.append(
                    _write_single_question(
                        question_body=item_body,
                        answer_body=a_body,
                        original_filename=original_filename,
                        source_type=source_type,
                        source_document_hash=source_document_hash,
                        import_method=import_method,
                        body_format="markdown",
                        assets=item_assets,
                        question_id=generated_question_id,
                        metadata_extra=item_metadata,
                        overwrite=overwrite,
                    )
                )
    else:
        if page_assets and not body.strip():
            raise ValueError(
                "Scanned PDF import requires a vision-capable LLM to produce Markdown/LaTeX question text. "
                "Rendered PDF pages are whole-page source material and were not imported as question assets."
            )
        metadata_extra: dict[str, Any] = {}
        if parsed:
            metadata_extra["page_count"] = len(parsed.pages)
            if parsed.metadata.get("title"):
                metadata_extra["title"] = parsed.metadata.get("title")
        generated_question_id = _stable_question_id(
            source_document_hash=source_document_hash,
            original_filename=original_filename,
            item={"metadata": metadata_extra},
            item_index=1,
        )
        if _requires_review(
            source_type=source_type,
            import_method="direct",
            metadata=metadata_extra,
            warnings=warnings,
        ):
            candidate = _queue_candidate(
                question_body=body,
                answer_body="",
                original_filename=original_filename,
                source_type=source_type,
                source_document_hash=source_document_hash,
                import_method="direct",
                body_format=body_format,
                assets=assets,
                question_id=generated_question_id,
                metadata_extra=metadata_extra,
                warnings=warnings,
            )
            _collect_candidate_result(
                candidate,
                questions=questions,
                candidates=candidates,
                warnings=warnings,
            )
        else:
            questions.append(
                _write_single_question(
                    question_body=body,
                    answer_body="",
                    original_filename=original_filename,
                    source_type=source_type,
                    source_document_hash=source_document_hash,
                    import_method="direct",
                    body_format=body_format,
                    assets=assets,
                    question_id=generated_question_id,
                    metadata_extra=metadata_extra,
                    overwrite=overwrite,
                )
            )

    if rebuild_after and questions:
        rebuild_index()
    return ImportResult(
        questions=questions,
        candidates=candidates,
        warnings=warnings,
        llm_used=bool(llm_items) and source_type != "json",
    )
