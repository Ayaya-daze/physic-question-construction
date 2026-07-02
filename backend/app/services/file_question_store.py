"""File-first question store.

The production source of truth for the simple question bank is:

    questions/<question_id>/question.md|tex|txt
    questions/<question_id>/answer.md|tex|txt       (optional)
    questions/<question_id>/assets/*
    questions/<question_id>/metadata.yaml  (optional)

Database tables may still exist for legacy structured workflows, but this
module reads and indexes question files directly.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from io import BytesIO
from threading import RLock
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from app.config import settings

QUESTIONS_DIR = settings.questions_dir
INDEX_DIR = QUESTIONS_DIR / ".index"
INDEX_PATH = INDEX_DIR / "vector-index.json"
ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".pdf",
}
RASTER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
LOCAL_VECTOR_MODEL = "local-file-hash-vector-v1"
LOCAL_VECTOR_DIMENSION = 384
MIN_VECTOR_SEARCH_SCORE = 0.18
EXACT_KEYWORD_BONUS = 0.75
_STORE_LOCK = RLock()


@dataclass
class FileAsset:
    filename: str
    path: str
    url: str
    mime_hint: str


@dataclass
class FileQuestion:
    question_id: str
    title: str
    question_body: str
    answer_body: str
    question_format: str
    answer_format: str | None
    preview: str
    content_hash: str
    metadata: dict = field(default_factory=dict)
    assets: list[FileAsset] = field(default_factory=list)
    updated_at: str = ""
    size_bytes: int = 0
    indexed: bool = False
    score: float | None = None


def ensure_store() -> None:
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)


def validate_question_id(question_id: str) -> str:
    candidate = question_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", candidate):
        raise ValueError("question_id may only contain letters, numbers, _, -, and .")
    if candidate.startswith("."):
        raise ValueError("question_id may not start with .")
    return candidate


def new_question_id() -> str:
    return f"qf_{uuid4().hex[:10]}"


def question_dir(question_id: str) -> Path:
    return QUESTIONS_DIR / validate_question_id(question_id)


def asset_path(question_id: str, asset_name: str) -> Path:
    safe_name = Path(asset_name).name
    if not safe_name or safe_name != asset_name:
        raise ValueError("Invalid asset filename")
    path = question_dir(question_id) / "assets" / safe_name
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(asset_name)
    return path


def _metadata_path(directory: Path) -> Path:
    yaml_path = directory / "metadata.yaml"
    yml_path = directory / "metadata.yml"
    return yaml_path if yaml_path.exists() else yml_path


def _question_body_path(directory: Path) -> Path:
    for name in ("question.md", "question.tex", "question.txt", "content.md", "content.tex", "content.txt"):
        path = directory / name
        if path.exists():
            return path
    return directory / "question.md"


def _answer_body_path(directory: Path) -> Path:
    for name in ("answer.md", "answer.tex", "answer.txt", "answers.md", "answers.tex", "answers.txt"):
        path = directory / name
        if path.exists():
            return path
    return directory / "answer.md"


def _format_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".tex", ".latex"}:
        return "latex"
    return "text"


def _load_metadata(directory: Path) -> dict:
    path = _metadata_path(directory)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}  # corrupted metadata file — treat as empty
    return data if isinstance(data, dict) else {}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _extract_title(question_id: str, content: str, metadata: dict) -> str:
    if isinstance(metadata.get("title"), str) and metadata["title"].strip():
        return metadata["title"].strip()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    text = _plain_text(content).strip()
    return text[:60] if text else question_id


def _plain_text(content: str) -> str:
    without_images = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", content)
    without_links = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", without_images)
    without_headings = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", without_links)
    without_quotes = re.sub(r"(?m)^\s{0,3}>\s?", "", without_headings)
    without_markup = without_quotes.replace("`", "")
    return re.sub(r"\s+", " ", without_markup).strip()


def _question_search_text(question: FileQuestion) -> str:
    return "\n".join(
        [
            question.title,
            _plain_text(question.question_body),
            _plain_text(question.answer_body),
            yaml.dump(question.metadata, allow_unicode=True),
        ]
    )


def _asset_mime_hint(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def validate_asset_payload(filename: str, payload: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in RASTER_IMAGE_EXTENSIONS:
        return
    try:
        from PIL import Image, UnidentifiedImageError
    except Exception:
        return

    try:
        with Image.open(BytesIO(payload)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"Invalid image asset: {filename}") from exc


def _list_assets(question_id: str, directory: Path) -> list[FileAsset]:
    assets_dir = directory / "assets"
    if not assets_dir.exists():
        return []
    assets: list[FileAsset] = []
    for path in sorted(assets_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in ASSET_EXTENSIONS:
            continue
        assets.append(
            FileAsset(
                filename=path.name,
                path=f"assets/{path.name}",
                url=f"/api/file-questions/{question_id}/assets/{path.name}",
                mime_hint=_asset_mime_hint(path),
            )
        )
    return assets


def _load_index_map() -> dict[str, dict]:
    if not INDEX_PATH.exists():
        return {}
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    items = data.get("items", [])
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("question_id")): item
        for item in items
        if item.get("question_id")
    }


def read_question(question_id: str, index_map: dict[str, dict] | None = None) -> FileQuestion:
    qid = validate_question_id(question_id)
    if index_map is None:
        index_map = _load_index_map()
    directory = question_dir(qid)
    content_path = _question_body_path(directory)
    if not content_path.exists() or not content_path.is_file():
        raise FileNotFoundError(qid)

    question_body = content_path.read_text(encoding="utf-8")
    answer_path = _answer_body_path(directory)
    answer_body = answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""
    metadata = _load_metadata(directory)
    plain = _plain_text(question_body)
    hash_value = _content_hash(question_body + "\n---ANSWER---\n" + answer_body)
    stat = content_path.stat()
    index_item = (index_map or {}).get(qid)

    return FileQuestion(
        question_id=qid,
        title=_extract_title(qid, question_body, metadata),
        question_body=question_body,
        answer_body=answer_body,
        question_format=_format_from_path(content_path),
        answer_format=_format_from_path(answer_path) if answer_path.exists() else None,
        preview=plain[:220],
        content_hash=hash_value,
        metadata=metadata,
        assets=_list_assets(qid, directory),
        updated_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        size_bytes=stat.st_size,
        indexed=bool(index_item and index_item.get("content_hash") == hash_value),
    )


def list_questions() -> list[FileQuestion]:
    ensure_store()
    index_map = _load_index_map()
    questions: list[FileQuestion] = []
    for directory in sorted(QUESTIONS_DIR.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        if not _question_body_path(directory).exists():
            continue
        try:
            questions.append(read_question(directory.name, index_map=index_map))
        except Exception:
            continue
    questions.sort(key=lambda item: item.updated_at, reverse=True)
    return questions


def _tokenize(text: str) -> list[str]:
    normalized = text.lower()
    words = re.findall(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]", normalized)
    compact = re.sub(r"\s+", "", normalized)
    ngrams = [compact[i : i + 2] for i in range(max(len(compact) - 1, 0))]
    return words + ngrams


def _strict_ascii_terms(query: str) -> list[str]:
    """Long ASCII identifiers/tags must match literally; hash vectors over-recall them."""
    return re.findall(r"[a-z0-9_.-]{4,}", query.lower())


def embed_text(text: str, dimension: int = LOCAL_VECTOR_DIMENSION) -> list[float]:
    vector = [0.0] * dimension
    for token in _tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    if size == 0:
        return 0.0
    dot = sum(float(left[i]) * float(right[i]) for i in range(size))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left[:size]))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right[:size]))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def rebuild_index() -> dict:
    with _STORE_LOCK:
        ensure_store()
        items = []
        for question in list_questions():
            search_text = _question_search_text(question)
            items.append(
                {
                    "question_id": question.question_id,
                    "title": question.title,
                    "preview": question.preview,
                    "content_hash": question.content_hash,
                    "updated_at": question.updated_at,
                    "search_text": search_text,
                    "vector": embed_text(search_text),
                }
            )

        payload = {
            "version": 1,
            "model": LOCAL_VECTOR_MODEL,
            "dimension": LOCAL_VECTOR_DIMENSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=INDEX_DIR,
            prefix=".vector-index.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(encoded)
            temp_path = Path(handle.name)
        temp_path.replace(INDEX_PATH)
        return payload


def load_or_rebuild_index() -> dict:
    ensure_store()
    if not INDEX_PATH.exists():
        return rebuild_index()
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return rebuild_index()


def search_questions(query: str, limit: int = 20) -> list[FileQuestion]:
    normalized_query = query.strip()
    if not normalized_query:
        return list_questions()[:limit]

    index = load_or_rebuild_index()
    query_vector = embed_text(normalized_query)
    strict_terms = _strict_ascii_terms(normalized_query)
    indexed_items = index.get("items", [])
    scored: list[tuple[float, str]] = []

    for item in indexed_items:
        qid = item.get("question_id")
        vector = item.get("vector")
        if not qid or not isinstance(vector, list):
            continue
        score = cosine_similarity(query_vector, vector)
        haystack = str(
            item.get("search_text")
            or f"{item.get('title', '')}\n{item.get('preview', '')}"
        ).lower()
        if strict_terms and not all(term in haystack for term in strict_terms):
            continue
        keyword_bonus = EXACT_KEYWORD_BONUS if normalized_query.lower() in haystack else 0.0
        final_score = score + keyword_bonus
        if keyword_bonus > 0 or score >= MIN_VECTOR_SEARCH_SCORE:
            scored.append((final_score, str(qid)))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    results: list[FileQuestion] = []
    index_map = _load_index_map()
    for score, qid in scored[:limit]:
        try:
            question = read_question(qid, index_map=index_map)
            question.score = round(score, 6)
            results.append(question)
        except FileNotFoundError:
            continue
    return results


def write_question(
    *,
    question_body: str,
    answer_body: str = "",
    question_format: str = "markdown",
    answer_format: str | None = None,
    question_id: str | None = None,
    metadata: dict | None = None,
    assets: list[tuple[str, bytes]] | None = None,
    overwrite: bool = False,
) -> FileQuestion:
    with _STORE_LOCK:
        ensure_store()
        qid = validate_question_id(question_id) if question_id else new_question_id()
        directory = question_dir(qid)
        if directory.exists() and not overwrite:
            raise FileExistsError(qid)
        validated_assets: list[tuple[str, bytes]] = []
        if assets:
            for filename, payload in assets:
                safe_name = Path(filename).name
                if not safe_name:
                    continue
                validate_asset_payload(safe_name, payload)
                validated_assets.append((safe_name, payload))

        directory.mkdir(parents=True, exist_ok=True)
        format_to_ext = {"markdown": "md", "latex": "tex", "text": "txt"}
        q_ext = format_to_ext.get(question_format, "md")
        a_ext = format_to_ext.get(answer_format or question_format, "md")

        if overwrite:
            for stale_name in ("question.md", "question.tex", "question.txt", "content.md", "content.tex", "content.txt"):
                stale_path = directory / stale_name
                if stale_path.exists() and stale_path.name != f"question.{q_ext}":
                    stale_path.unlink()
            for stale_name in ("answer.md", "answer.tex", "answer.txt", "answers.md", "answers.tex", "answers.txt"):
                stale_path = directory / stale_name
                if stale_path.exists() and (not answer_body.strip() or stale_path.name != f"answer.{a_ext}"):
                    stale_path.unlink()
            if metadata is not None:
                for stale_name in ("metadata.yaml", "metadata.yml"):
                    stale_path = directory / stale_name
                    if stale_path.exists():
                        stale_path.unlink()
            if assets is not None:
                assets_dir = directory / "assets"
                if assets_dir.exists():
                    for stale_asset in assets_dir.iterdir():
                        if stale_asset.is_file():
                            stale_asset.unlink()

        (directory / f"question.{q_ext}").write_text(question_body, encoding="utf-8")
        if answer_body.strip():
            (directory / f"answer.{a_ext}").write_text(answer_body, encoding="utf-8")

        if metadata:
            (directory / "metadata.yaml").write_text(
                yaml.dump(metadata, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

        if validated_assets:
            assets_dir = directory / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            for safe_name, payload in validated_assets:
                (assets_dir / safe_name).write_bytes(payload)

        return read_question(qid)
