"""Derived, user-governed knowledge points for the file-first question bank."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import settings


_LOCK = RLock()
_ID_PATTERN = re.compile(r"kp_[a-f0-9]{12}")


def index_path() -> Path:
    return settings.questions_dir / ".index" / "knowledge-points.json"


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _knowledge_point_id(name: str) -> str:
    return f"kp_{hashlib.sha1(name.casefold().encode('utf-8')).hexdigest()[:12]}"


def _empty_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": [],
    }


def load_knowledge_points() -> dict[str, Any]:
    path = index_path()
    if not path.exists():
        return _empty_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty_payload()
    return payload if isinstance(payload, dict) and isinstance(payload.get("items"), list) else _empty_payload()


def _write_payload(payload: dict[str, Any]) -> dict[str, Any]:
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".knowledge-points.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)
    return payload


def rebuild_knowledge_points() -> dict[str, Any]:
    from app.services.file_question_store import list_questions

    with _LOCK:
        current = load_knowledge_points()
        existing = {
            str(item.get("knowledge_point_id")): item
            for item in current.get("items", [])
            if isinstance(item, dict) and item.get("knowledge_point_id")
        }
        alias_to_id: dict[str, str] = {}
        for knowledge_point_id, item in existing.items():
            names = [item.get("name"), *(item.get("aliases") or [])]
            for name in names:
                if isinstance(name, str) and _normalize_name(name):
                    alias_to_id[_normalize_name(name).casefold()] = knowledge_point_id

        aggregate: dict[str, dict[str, Any]] = {}
        for question in list_questions():
            raw_values = question.metadata.get("knowledge_points")
            if isinstance(raw_values, str):
                raw_values = [raw_values]
            if not isinstance(raw_values, list):
                continue
            for raw_name in raw_values:
                if not isinstance(raw_name, str):
                    continue
                name = _normalize_name(raw_name)
                if not name:
                    continue
                knowledge_point_id = alias_to_id.get(name.casefold()) or _knowledge_point_id(name)
                existing_item = existing.get(knowledge_point_id, {})
                item = aggregate.setdefault(
                    knowledge_point_id,
                    {
                        "knowledge_point_id": knowledge_point_id,
                        "name": existing_item.get("name") or name,
                        "aliases": list(existing_item.get("aliases") or []),
                        "question_ids": [],
                        "count": 0,
                    },
                )
                if question.question_id not in item["question_ids"]:
                    item["question_ids"].append(question.question_id)
                    item["count"] += 1

        for knowledge_point_id, item in existing.items():
            if knowledge_point_id in aggregate:
                continue
            if item.get("aliases"):
                aggregate[knowledge_point_id] = {
                    "knowledge_point_id": knowledge_point_id,
                    "name": item.get("name"),
                    "aliases": list(item.get("aliases") or []),
                    "question_ids": [],
                    "count": 0,
                }

        payload = {
            "version": 1,
            "items": sorted(
                aggregate.values(),
                key=lambda item: (-int(item["count"]), str(item["name"]).casefold()),
            ),
        }
        return _write_payload(payload)


def list_knowledge_points() -> list[dict[str, Any]]:
    payload = load_knowledge_points()
    if not index_path().exists():
        payload = rebuild_knowledge_points()
    return list(payload.get("items", []))


def _validated_id(knowledge_point_id: str) -> str:
    candidate = knowledge_point_id.strip()
    if not _ID_PATTERN.fullmatch(candidate):
        raise ValueError("Invalid knowledge point id")
    return candidate


def rename_knowledge_point(knowledge_point_id: str, name: str) -> dict[str, Any]:
    knowledge_point_id = _validated_id(knowledge_point_id)
    new_name = _normalize_name(name)
    if not new_name:
        raise ValueError("Knowledge point name cannot be empty")
    with _LOCK:
        payload = load_knowledge_points()
        for item in payload.get("items", []):
            if item.get("knowledge_point_id") != knowledge_point_id:
                continue
            old_name = _normalize_name(str(item.get("name") or ""))
            aliases = {
                _normalize_name(str(alias))
                for alias in item.get("aliases", [])
                if _normalize_name(str(alias))
            }
            if old_name and old_name.casefold() != new_name.casefold():
                aliases.add(old_name)
            aliases.discard(new_name)
            item["name"] = new_name
            item["aliases"] = sorted(aliases)
            _write_payload(payload)
            return item
    raise FileNotFoundError(knowledge_point_id)


def merge_knowledge_points(source_id: str, target_id: str) -> dict[str, Any]:
    source_id = _validated_id(source_id)
    target_id = _validated_id(target_id)
    if source_id == target_id:
        raise ValueError("Source and target knowledge points must differ")
    with _LOCK:
        payload = load_knowledge_points()
        items = {
            str(item.get("knowledge_point_id")): item
            for item in payload.get("items", [])
            if isinstance(item, dict)
        }
        source = items.get(source_id)
        target = items.get(target_id)
        if source is None or target is None:
            raise FileNotFoundError(source_id if source is None else target_id)
        aliases = {
            _normalize_name(str(alias))
            for alias in target.get("aliases", [])
            if _normalize_name(str(alias))
        }
        aliases.add(_normalize_name(str(source.get("name") or "")))
        aliases.update(
            _normalize_name(str(alias))
            for alias in source.get("aliases", [])
            if _normalize_name(str(alias))
        )
        aliases.discard(_normalize_name(str(target.get("name") or "")))
        target["aliases"] = sorted(alias for alias in aliases if alias)
        payload["items"] = [
            item for item in payload.get("items", []) if item.get("knowledge_point_id") != source_id
        ]
        _write_payload(payload)
        return rebuild_knowledge_points()


def question_ids_for_knowledge_point(knowledge_point_id: str) -> set[str]:
    knowledge_point_id = _validated_id(knowledge_point_id)
    for item in list_knowledge_points():
        if item.get("knowledge_point_id") == knowledge_point_id:
            return {str(value) for value in item.get("question_ids", []) if value}
    raise FileNotFoundError(knowledge_point_id)
