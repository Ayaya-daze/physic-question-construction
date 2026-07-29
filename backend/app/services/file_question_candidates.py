"""File-backed review queue for question import candidates."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from app.config import settings
from app.services.file_question_store import (
    FileQuestion,
    validate_asset_filename,
    validate_asset_payload,
    validate_question_id,
    write_question,
)


_CANDIDATE_LOCK = RLock()
_CANDIDATE_ID_PATTERN = re.compile(r"fqc_[a-f0-9]{20}")
_VALID_STATES = {"needs_review", "approved", "committed", "rejected"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def candidates_root() -> Path:
    return settings.upload_dir / "file-question-candidates"


def ensure_candidates_root() -> Path:
    root = candidates_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / ".staging").mkdir(exist_ok=True)
    return root


def validate_candidate_id(candidate_id: str) -> str:
    candidate = candidate_id.strip()
    if not _CANDIDATE_ID_PATTERN.fullmatch(candidate):
        raise ValueError("Invalid candidate id")
    return candidate


def candidate_dir(candidate_id: str) -> Path:
    return ensure_candidates_root() / validate_candidate_id(candidate_id)


def candidate_asset_path(candidate_id: str, filename: str) -> Path:
    name = validate_asset_filename(filename)
    path = candidate_dir(candidate_id) / "assets" / name
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(name)
    return path


def _manifest_path(candidate_id: str) -> Path:
    return candidate_dir(candidate_id) / "candidate.json"


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    lifecycle_fields = {
        "candidate_id",
        "state",
        "created_at",
        "updated_at",
        "reviewed_at",
        "committed_at",
        "committed_question_id",
        "rejection_reason",
    }
    comparable = {
        key: value
        for key, value in payload.items()
        if key not in lifecycle_fields
    }
    metadata = comparable.get("metadata")
    if isinstance(metadata, dict):
        comparable["metadata"] = {
            key: value
            for key, value in metadata.items()
            if key not in {"imported_at", "reviewed_at"}
        }
    return json.dumps(
        comparable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _candidate_id(payload: dict[str, Any], assets: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256(_canonical_payload(payload))
    for filename, content in sorted(assets, key=lambda item: item[0]):
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return f"fqc_{digest.hexdigest()[:20]}"


def _write_manifest(directory: Path, payload: dict[str, Any]) -> None:
    path = directory / "candidate.json"
    temp_path = directory / f".candidate.{uuid4().hex}.tmp"
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def read_candidate(candidate_id: str) -> dict[str, Any]:
    path = _manifest_path(candidate_id)
    if not path.is_file():
        raise FileNotFoundError(candidate_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupted candidate manifest: {candidate_id}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid candidate manifest: {candidate_id}")
    return payload


def list_candidates(
    *,
    state: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    root = ensure_candidates_root()
    if state is not None and state not in _VALID_STATES:
        raise ValueError(f"Invalid candidate state: {state}")
    candidates: list[dict[str, Any]] = []
    for directory in root.iterdir():
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        try:
            payload = read_candidate(directory.name)
        except Exception:
            continue
        if state is None or payload.get("state") == state:
            candidates.append(payload)
    candidates.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return candidates[: max(1, min(limit, 100_000))]


def create_candidate(
    *,
    question_body: str,
    answer_body: str,
    question_format: str,
    answer_format: str | None,
    metadata: dict[str, Any],
    assets: list[tuple[str, bytes]],
    proposed_question_id: str,
    source_filename: str,
    source_type: str,
    source_document_hash: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    if not question_body.strip():
        raise ValueError("question_body must be non-empty")
    qid = validate_question_id(proposed_question_id)

    validated_assets: list[tuple[str, bytes]] = []
    seen_names: set[str] = set()
    asset_entries: list[dict[str, Any]] = []
    for raw_name, content in assets:
        name = validate_asset_filename(raw_name)
        if name in seen_names:
            raise ValueError(f"Duplicate asset filename: {name}")
        seen_names.add(name)
        validate_asset_payload(name, content)
        validated_assets.append((name, content))
        asset_entries.append(
            {
                "filename": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )

    now = utc_now()
    payload: dict[str, Any] = {
        "state": "needs_review",
        "question_body": question_body,
        "answer_body": answer_body,
        "question_format": question_format,
        "answer_format": answer_format,
        "metadata": dict(metadata),
        "assets": asset_entries,
        "proposed_question_id": qid,
        "source_filename": source_filename,
        "source_type": source_type,
        "source_document_hash": source_document_hash,
        "warnings": list(warnings or []),
    }
    candidate_id = _candidate_id(payload, validated_assets)
    payload.update(
        {
            "candidate_id": candidate_id,
            "created_at": now,
            "updated_at": now,
        }
    )

    with _CANDIDATE_LOCK:
        root = ensure_candidates_root()
        destination = root / candidate_id
        if destination.exists():
            existing = read_candidate(candidate_id)
            same_source = (
                existing.get("source_document_hash") == source_document_hash
                and existing.get("proposed_question_id") == qid
            )
            if not same_source:
                raise FileExistsError(f"Candidate id conflict: {candidate_id}")
            return existing

        staged = root / ".staging" / f"{candidate_id}.{uuid4().hex}.tmp"
        staged.mkdir()
        try:
            assets_dir = staged / "assets"
            if validated_assets:
                assets_dir.mkdir()
                for name, content in validated_assets:
                    (assets_dir / name).write_bytes(content)
            _write_manifest(staged, payload)
            staged.replace(destination)
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
    return payload


def _candidate_assets(payload: dict[str, Any]) -> list[tuple[str, bytes]]:
    directory = candidate_dir(str(payload["candidate_id"]))
    result: list[tuple[str, bytes]] = []
    for item in payload.get("assets", []):
        if not isinstance(item, dict):
            continue
        name = validate_asset_filename(str(item.get("filename") or ""))
        path = directory / "assets" / name
        if not path.is_file():
            raise ValueError(f"Candidate asset is missing: {name}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item.get("sha256"):
            raise ValueError(f"Candidate asset hash mismatch: {name}")
        validate_asset_payload(name, content)
        result.append((name, content))
    return result


def approve_candidate(
    candidate_id: str,
    *,
    question_body: str | None = None,
    answer_body: str | None = None,
    metadata: dict[str, Any] | None = None,
    acknowledge_warnings: bool = False,
) -> tuple[dict[str, Any], FileQuestion]:
    with _CANDIDATE_LOCK:
        payload = read_candidate(candidate_id)
        if payload.get("state") == "rejected":
            raise ValueError("Rejected candidate cannot be approved")
        if payload.get("state") == "committed":
            question = write_question(
                question_id=str(payload["committed_question_id"]),
                question_body=str(payload["question_body"]),
                answer_body=str(payload.get("answer_body") or ""),
                question_format=str(payload.get("question_format") or "markdown"),
                answer_format=payload.get("answer_format"),
                metadata=dict(payload.get("metadata") or {}),
                assets=_candidate_assets(payload),
                idempotent=True,
            )
            return payload, question

        warnings = [str(item) for item in payload.get("warnings", []) if item]
        if warnings and not acknowledge_warnings:
            raise ValueError("Candidate has warnings; acknowledge them before approval")

        payload["question_body"] = (
            question_body if question_body is not None else str(payload["question_body"])
        )
        payload["answer_body"] = (
            answer_body if answer_body is not None else str(payload.get("answer_body") or "")
        )
        merged_metadata = dict(payload.get("metadata") or {})
        if metadata is not None:
            merged_metadata.update(metadata)
        merged_metadata["human_review_needed"] = False
        merged_metadata["reviewed_at"] = utc_now()
        payload["metadata"] = merged_metadata
        payload["state"] = "approved"
        payload["reviewed_at"] = utc_now()
        payload["updated_at"] = utc_now()

        question = write_question(
            question_id=str(payload["proposed_question_id"]),
            question_body=str(payload["question_body"]),
            answer_body=str(payload.get("answer_body") or ""),
            question_format=str(payload.get("question_format") or "markdown"),
            answer_format=payload.get("answer_format"),
            metadata=merged_metadata,
            assets=_candidate_assets(payload),
            idempotent=True,
        )
        payload["state"] = "committed"
        payload["committed_question_id"] = question.question_id
        payload["committed_at"] = utc_now()
        payload["updated_at"] = utc_now()
        _write_manifest(candidate_dir(candidate_id), payload)
        return payload, question


def reject_candidate(candidate_id: str, reason: str = "") -> dict[str, Any]:
    with _CANDIDATE_LOCK:
        payload = read_candidate(candidate_id)
        if payload.get("state") == "committed":
            raise ValueError("Committed candidate cannot be rejected")
        payload["state"] = "rejected"
        payload["rejection_reason"] = reason.strip()
        payload["reviewed_at"] = utc_now()
        payload["updated_at"] = utc_now()
        _write_manifest(candidate_dir(candidate_id), payload)
        return payload
