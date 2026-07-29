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
import shutil
import sqlite3
import sys
import tempfile
from array import array
from io import BytesIO
from threading import RLock
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml
import httpx

from app.config import settings

QUESTIONS_DIR = settings.questions_dir
INDEX_DIR = QUESTIONS_DIR / ".index"
INDEX_PATH = INDEX_DIR / "vector-index.json"
LEXICAL_INDEX_PATH = INDEX_DIR / "lexical.sqlite"
VECTOR_DATA_PATH = INDEX_DIR / "vectors.f32"
VECTOR_MAP_PATH = INDEX_DIR / "vector-map.json"
INDEX_MANIFEST_PATH = INDEX_DIR / "index-manifest.json"
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
LOCAL_VECTOR_MODEL = "local-file-hash-vector-v2-fallback"
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
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise FileNotFoundError(asset_name)
    return path


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path, ignore_errors=True)


def recover_interrupted_writes() -> dict[str, int]:
    """Restore or clean directory swaps interrupted by a process crash."""
    with _STORE_LOCK:
        ensure_store()
        staging_root = QUESTIONS_DIR / ".staging"
        staging_root.mkdir(exist_ok=True)
        backup_pattern = re.compile(
            r"^(?P<question_id>[A-Za-z0-9_.-]{1,120})\.[a-f0-9]{32}\.backup$"
        )
        temp_pattern = re.compile(
            r"^(?P<question_id>[A-Za-z0-9_.-]{1,120})\.[a-f0-9]{32}\.tmp$"
        )
        backups: dict[str, list[Path]] = {}
        removed = 0
        restored = 0

        for entry in staging_root.iterdir():
            backup_match = backup_pattern.fullmatch(entry.name)
            if backup_match:
                backups.setdefault(backup_match.group("question_id"), []).append(entry)
                continue
            if temp_pattern.fullmatch(entry.name):
                _remove_path(entry)
                removed += 1

        for question_id, candidates in backups.items():
            destination = QUESTIONS_DIR / validate_question_id(question_id)
            ordered = sorted(
                candidates,
                key=lambda item: item.lstat().st_mtime,
                reverse=True,
            )
            if not destination.exists():
                restore = ordered.pop(0)
                if restore.is_dir() and not restore.is_symlink():
                    restore.replace(destination)
                    restored += 1
                else:
                    _remove_path(restore)
                    removed += 1
            for stale in ordered:
                _remove_path(stale)
                removed += 1

        return {"restored": restored, "removed": removed}


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
    if not path.exists() or path.is_symlink():
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


def validate_asset_filename(filename: str) -> str:
    candidate = filename.strip()
    if not candidate or candidate != Path(candidate).name:
        raise ValueError(f"Invalid asset filename: {filename!r}")
    if Path(candidate).suffix.lower() not in ASSET_EXTENSIONS:
        raise ValueError(f"Unsupported asset type: {candidate}")
    return candidate


def _directory_fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise ValueError(f"Symlink is not allowed in a question record: {path.name}")
        digest.update(str(path.relative_to(directory)).encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def record_fingerprint(question_id: str) -> str:
    directory = question_dir(question_id)
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError(question_id)
    return _directory_fingerprint(directory)


def _list_assets(question_id: str, directory: Path) -> list[FileAsset]:
    assets_dir = directory / "assets"
    if not assets_dir.exists():
        return []
    assets: list[FileAsset] = []
    for path in sorted(assets_dir.iterdir()):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.suffix.lower() not in ASSET_EXTENSIONS
        ):
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
    path = VECTOR_MAP_PATH if VECTOR_MAP_PATH.exists() else INDEX_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError(qid)
    content_path = _question_body_path(directory)
    if (
        not content_path.exists()
        or not content_path.is_file()
        or content_path.is_symlink()
    ):
        raise FileNotFoundError(qid)

    question_body = content_path.read_text(encoding="utf-8")
    answer_path = _answer_body_path(directory)
    if answer_path.exists() and answer_path.is_symlink():
        raise ValueError(f"Symlink answer file is not allowed: {qid}")
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
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or directory.name.startswith(".")
        ):
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


def _normalize_vector(values: list[float]) -> list[float]:
    vector = [float(value) for value in values]
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def embedding_api_configured() -> bool:
    return bool(
        settings.EMBEDDING_ENABLED
        and settings.EMBEDDING_API_KEY
        and settings.EMBEDDING_MODEL
        and settings.EMBEDDING_BASE_URL
    )


def embedding_model_name() -> str:
    return settings.EMBEDDING_MODEL if embedding_api_configured() else LOCAL_VECTOR_MODEL


def _embedding_endpoint() -> str:
    base = settings.EMBEDDING_BASE_URL.rstrip("/")
    return base if base.endswith("/embeddings") else f"{base}/embeddings"


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if not embedding_api_configured():
        return [embed_text(text) for text in texts]

    batch_size = max(1, min(int(settings.EMBEDDING_BATCH_SIZE or 64), 256))
    results: list[list[float]] = []
    headers = {
        "Authorization": f"Bearer {settings.EMBEDDING_API_KEY}",
        "Content-Type": "application/json",
    }
    timeout = max(1, int(settings.EMBEDDING_TIMEOUT_SECONDS or 60))
    with httpx.Client(timeout=timeout) as client:
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = client.post(
                _embedding_endpoint(),
                headers=headers,
                json={"model": settings.EMBEDDING_MODEL, "input": batch},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or len(data) != len(batch):
                raise ValueError("Embedding API returned an invalid number of vectors")
            ordered = sorted(
                data,
                key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0,
            )
            for item in ordered:
                vector = item.get("embedding") if isinstance(item, dict) else None
                if not isinstance(vector, list) or not vector:
                    raise ValueError("Embedding API returned an invalid vector")
                results.append(_normalize_vector(vector))

    dimension = len(results[0])
    if any(len(vector) != dimension for vector in results):
        raise ValueError("Embedding API returned inconsistent vector dimensions")
    return results


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


def _write_json_atomic(path: Path, payload: dict) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _write_vectors_atomic(path: Path, vectors: list[list[float]]) -> None:
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        for vector in vectors:
            values = array("f", vector)
            if sys.byteorder != "little":
                values.byteswap()
            values.tofile(handle)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _build_lexical_index(items: list[dict], index_content_hash: str) -> None:
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=INDEX_DIR,
        prefix=".lexical.",
        suffix=".sqlite.tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
    temp_path.unlink(missing_ok=True)
    try:
        connection = sqlite3.connect(temp_path)
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE questions_fts USING "
                "fts5(question_id UNINDEXED, title, search_text, tokenize='unicode61')"
            )
            connection.execute(
                "CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO index_meta(key, value) VALUES ('index_content_hash', ?)",
                (index_content_hash,),
            )
            connection.executemany(
                "INSERT INTO questions_fts(question_id, title, search_text) VALUES (?, ?, ?)",
                [
                    (item["question_id"], item["title"], item["search_text"])
                    for item in items
                ],
            )
            connection.commit()
        finally:
            connection.close()
        temp_path.replace(LEXICAL_INDEX_PATH)
    finally:
        temp_path.unlink(missing_ok=True)


def rebuild_index() -> dict:
    with _STORE_LOCK:
        ensure_store()
        questions = list_questions()
        source_items = [
            {
                "question_id": question.question_id,
                "title": question.title,
                "preview": question.preview,
                "content_hash": question.content_hash,
                "updated_at": question.updated_at,
                "search_text": _question_search_text(question),
            }
            for question in questions
        ]
        embedding_error: str | None = None
        try:
            vectors = embed_texts([item["search_text"] for item in source_items])
            model = embedding_model_name()
            embedding_provider = (
                "openai-compatible-api"
                if embedding_api_configured()
                else "local-fallback"
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            if not embedding_api_configured():
                raise
            vectors = [embed_text(item["search_text"]) for item in source_items]
            model = LOCAL_VECTOR_MODEL
            embedding_provider = "local-fallback"
            embedding_error = f"{type(exc).__name__}: {exc}"
        dimension = len(vectors[0]) if vectors else 0
        if any(len(vector) != dimension for vector in vectors):
            raise ValueError("Cannot build index with inconsistent vector dimensions")

        vector_items = [
            {
                "question_id": item["question_id"],
                "title": item["title"],
                "preview": item["preview"],
                "content_hash": item["content_hash"],
                "updated_at": item["updated_at"],
                "offset": index * dimension,
                "dimension": dimension,
            }
            for index, item in enumerate(source_items)
        ]
        created_at = datetime.now(timezone.utc).isoformat()
        index_content_hash = hashlib.sha256(
            "\n".join(
                f"{item['question_id']}:{item['content_hash']}"
                for item in source_items
            ).encode("utf-8")
        ).hexdigest()
        vector_map = {
            "version": 2,
            "model": model,
            "dimension": dimension,
            "index_content_hash": index_content_hash,
            "items": vector_items,
        }
        manifest = {
            "version": 2,
            "created_at": created_at,
            "question_count": len(source_items),
            "lexical_index": LEXICAL_INDEX_PATH.name,
            "vector_data": VECTOR_DATA_PATH.name,
            "vector_map": VECTOR_MAP_PATH.name,
            "embedding_provider": embedding_provider,
            "embedding_model": model,
            "embedding_error": embedding_error,
            "dimension": dimension,
            "index_content_hash": index_content_hash,
        }
        compatibility_payload = {
            "version": 2,
            "model": model,
            "dimension": dimension,
            "created_at": created_at,
            "index_content_hash": index_content_hash,
            "items": vector_items,
        }

        _build_lexical_index(source_items, index_content_hash)
        _write_vectors_atomic(VECTOR_DATA_PATH, vectors)
        _write_json_atomic(VECTOR_MAP_PATH, vector_map)
        _write_json_atomic(INDEX_MANIFEST_PATH, manifest)
        _write_json_atomic(INDEX_PATH, compatibility_payload)
        from app.services.file_knowledge_points import rebuild_knowledge_points

        rebuild_knowledge_points()
        return compatibility_payload


def load_or_rebuild_index() -> dict:
    ensure_store()
    required = {
        INDEX_PATH,
        LEXICAL_INDEX_PATH,
        VECTOR_DATA_PATH,
        VECTOR_MAP_PATH,
        INDEX_MANIFEST_PATH,
    }
    if not all(path.exists() for path in required):
        return rebuild_index()
    try:
        payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        manifest = json.loads(INDEX_MANIFEST_PATH.read_text(encoding="utf-8"))
        vector_map = json.loads(VECTOR_MAP_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload.get("items"), list):
            raise ValueError("Invalid compatibility index")
        if manifest.get("question_count") != len(vector_map.get("items", [])):
            raise ValueError("Index item count mismatch")
        if manifest.get("index_content_hash") != vector_map.get("index_content_hash"):
            raise ValueError("Index content hash mismatch")
        if (
            embedding_api_configured()
            and manifest.get("embedding_model") != settings.EMBEDDING_MODEL
        ):
            raise ValueError("Configured embedding model differs from current index")
        expected_bytes = (
            int(vector_map.get("dimension") or 0)
            * len(vector_map.get("items", []))
            * 4
        )
        if VECTOR_DATA_PATH.stat().st_size != expected_bytes:
            raise ValueError("Vector data size mismatch")
        connection = sqlite3.connect(f"file:{LEXICAL_INDEX_PATH}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT value FROM index_meta WHERE key='index_content_hash'"
            ).fetchone()
        finally:
            connection.close()
        if not row or row[0] != manifest.get("index_content_hash"):
            raise ValueError("Lexical index content hash mismatch")
        return payload
    except (json.JSONDecodeError, OSError, ValueError):
        return rebuild_index()


def _fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]+", query)
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def _lexical_rankings(query: str, limit: int) -> list[str]:
    if not LEXICAL_INDEX_PATH.exists():
        return []
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    connection = sqlite3.connect(f"file:{LEXICAL_INDEX_PATH}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT question_id FROM questions_fts "
            "WHERE questions_fts MATCH ? ORDER BY bm25(questions_fts) LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return [str(row[0]) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def _load_vectors() -> tuple[dict, list[float]]:
    vector_map = json.loads(VECTOR_MAP_PATH.read_text(encoding="utf-8"))
    values = array("f")
    with VECTOR_DATA_PATH.open("rb") as handle:
        values.fromfile(handle, VECTOR_DATA_PATH.stat().st_size // values.itemsize)
    if sys.byteorder != "little":
        values.byteswap()
    return vector_map, list(values)


def _query_vector(query: str, index_model: str) -> list[float] | None:
    if index_model == LOCAL_VECTOR_MODEL:
        return embed_text(query)
    if not embedding_api_configured() or settings.EMBEDDING_MODEL != index_model:
        return None
    try:
        vectors = embed_texts([query])
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return None
    return vectors[0] if vectors else None


def _vector_rankings(query: str, limit: int) -> list[str]:
    try:
        vector_map, values = _load_vectors()
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    dimension = int(vector_map.get("dimension") or 0)
    query_vector = _query_vector(query, str(vector_map.get("model") or ""))
    if dimension <= 0 or query_vector is None or len(query_vector) != dimension:
        return []

    scored: list[tuple[float, str]] = []
    for item in vector_map.get("items", []):
        if not isinstance(item, dict) or not item.get("question_id"):
            continue
        offset = int(item.get("offset") or 0)
        item_dimension = int(item.get("dimension") or dimension)
        vector = values[offset : offset + item_dimension]
        if len(vector) != dimension:
            continue
        score = cosine_similarity(query_vector, vector)
        if score >= MIN_VECTOR_SEARCH_SCORE:
            scored.append((score, str(item["question_id"])))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [question_id for _, question_id in scored[:limit]]


def search_questions(query: str, limit: int = 20) -> list[FileQuestion]:
    normalized_query = query.strip()
    if not normalized_query:
        return list_questions()[:limit]

    load_or_rebuild_index()
    candidate_limit = max(limit * 10, 100)
    lexical = _lexical_rankings(normalized_query, candidate_limit)
    vector = _vector_rankings(normalized_query, candidate_limit)
    scores: dict[str, float] = {}
    for rank, qid in enumerate(lexical, start=1):
        scores[qid] = scores.get(qid, 0.0) + 1.0 / (60 + rank)
    for rank, qid in enumerate(vector, start=1):
        scores[qid] = scores.get(qid, 0.0) + 1.0 / (60 + rank)

    if not scores:
        lowered = normalized_query.lower()
        for question in list_questions():
            if lowered in _question_search_text(question).lower():
                scores[question.question_id] = EXACT_KEYWORD_BONUS

    strict_terms = _strict_ascii_terms(normalized_query)
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    results: list[FileQuestion] = []
    index_map = _load_index_map()
    for qid, score in ranked:
        try:
            question = read_question(qid, index_map=index_map)
        except FileNotFoundError:
            continue
        haystack = _question_search_text(question).lower()
        if strict_terms and not all(term in haystack for term in strict_terms):
            continue
        if normalized_query.lower() in haystack:
            score += EXACT_KEYWORD_BONUS
        question.score = round(score, 6)
        results.append(question)
        if len(results) >= limit:
            break
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
    idempotent: bool = False,
) -> FileQuestion:
    with _STORE_LOCK:
        ensure_store()
        if not isinstance(question_body, str) or not question_body.strip():
            raise ValueError("question_body must be a non-empty string")
        qid = validate_question_id(question_id) if question_id else new_question_id()
        directory = question_dir(qid)
        if directory.exists() and (not directory.is_dir() or directory.is_symlink()):
            raise ValueError(f"Question path is not a regular directory: {qid}")

        effective_metadata = metadata
        effective_assets = assets
        if directory.exists() and overwrite:
            if effective_metadata is None:
                effective_metadata = _load_metadata(directory)
            if effective_assets is None:
                effective_assets = [
                    (asset.filename, asset_path(qid, asset.filename).read_bytes())
                    for asset in _list_assets(qid, directory)
                ]

        validated_assets: list[tuple[str, bytes]] = []
        seen_asset_names: set[str] = set()
        if effective_assets:
            for filename, payload in effective_assets:
                safe_name = validate_asset_filename(filename)
                if safe_name in seen_asset_names:
                    raise ValueError(f"Duplicate asset filename: {safe_name}")
                seen_asset_names.add(safe_name)
                validate_asset_payload(safe_name, payload)
                validated_assets.append((safe_name, payload))

        format_to_ext = {"markdown": "md", "latex": "tex", "text": "txt"}
        if question_format not in format_to_ext:
            raise ValueError(f"Unsupported question format: {question_format}")
        resolved_answer_format = answer_format or question_format
        if resolved_answer_format not in format_to_ext:
            raise ValueError(f"Unsupported answer format: {resolved_answer_format}")
        q_ext = format_to_ext[question_format]
        a_ext = format_to_ext[resolved_answer_format]

        staging_root = INDEX_DIR.parent / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staged = staging_root / f"{qid}.{uuid4().hex}.tmp"
        backup = staging_root / f"{qid}.{uuid4().hex}.backup"
        staged.mkdir()
        try:
            (staged / f"question.{q_ext}").write_text(question_body, encoding="utf-8")
            if answer_body.strip():
                (staged / f"answer.{a_ext}").write_text(answer_body, encoding="utf-8")
            if effective_metadata:
                (staged / "metadata.yaml").write_text(
                    yaml.safe_dump(effective_metadata, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            if validated_assets:
                assets_dir = staged / "assets"
                assets_dir.mkdir()
                for safe_name, payload in validated_assets:
                    (assets_dir / safe_name).write_bytes(payload)

            staged_fingerprint = _directory_fingerprint(staged)
            if directory.exists() and not overwrite:
                if idempotent and _directory_fingerprint(directory) == staged_fingerprint:
                    return read_question(qid)
                raise FileExistsError(qid)

            if directory.exists():
                directory.replace(backup)
            try:
                staged.replace(directory)
            except Exception:
                if backup.exists() and not directory.exists():
                    backup.replace(directory)
                raise
            if backup.exists():
                shutil.rmtree(backup)
            return read_question(qid)
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
            if backup.exists() and directory.exists():
                shutil.rmtree(backup, ignore_errors=True)
