#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


QUESTION_ID_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,120}")
RENDERED_PAGE_PATTERN = re.compile(r"(?:page|p)[_-]?\d{1,4}", re.IGNORECASE)
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
LATEX_IMAGE_PATTERN = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")


class MaterializationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedRecord:
    question_id: str
    question_body: str
    answer_body: str
    metadata: dict[str, Any]
    assets: tuple[tuple[str, Path], ...]


def load_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise MaterializationError("Top-level value must be a non-empty JSON array.")
    if not all(isinstance(item, dict) for item in data):
        raise MaterializationError("Every question record must be a JSON object.")
    return data


def validate_question_id(question_id: str) -> str:
    candidate = question_id.strip()
    if not QUESTION_ID_PATTERN.fullmatch(candidate) or candidate.startswith("."):
        raise MaterializationError(f"Invalid question_id: {question_id!r}")
    return candidate


def referenced_asset_paths(*bodies: str) -> set[str]:
    paths: set[str] = set()
    for body in bodies:
        paths.update(match.strip() for match in MARKDOWN_IMAGE_PATTERN.findall(body))
        paths.update(match.strip() for match in LATEX_IMAGE_PATTERN.findall(body))
    return {path for path in paths if path}


def looks_like_rendered_pdf_page(name: str) -> bool:
    path = Path(name)
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and bool(
        RENDERED_PAGE_PATTERN.fullmatch(path.stem)
    )


def resolve_asset(assets_root: Path, raw_path: str) -> tuple[str, Path]:
    if re.match(r"^[a-z]+://", raw_path, re.IGNORECASE):
        raise MaterializationError(f"Remote assets are not supported: {raw_path}")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise MaterializationError(f"Asset path escapes the import root: {raw_path}")
    name = relative.name
    if not name or looks_like_rendered_pdf_page(name):
        raise MaterializationError(
            f"Rendered PDF page images cannot be question assets: {raw_path}"
        )

    root = assets_root.resolve()
    candidates = [root / relative]
    if relative.parts and relative.parts[0] == "assets":
        candidates.append(root.joinpath(*relative.parts[1:]))
    candidates.append(root / name)

    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise MaterializationError(f"Asset path escapes the import root: {raw_path}") from exc
        if resolved.is_file():
            return name, resolved
    raise MaterializationError(f"Referenced asset not found under {root}: {raw_path}")


def stable_question_id(
    item: dict,
    *,
    index: int,
    source_name: str | None,
    source_hash: str | None,
) -> str:
    explicit = item.get("question_id")
    if isinstance(explicit, str) and explicit.strip():
        return validate_question_id(explicit)

    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
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
            f"item-{index}|{page_key}|{title}"
            if page_key or title
            else f"item-{index}"
        )

    identity = source_hash or source_name or "agent-import"
    if not source_hash and not source_name:
        identity = hashlib.sha256(
            str(item.get("question_body") or "").strip().encode("utf-8")
        ).hexdigest()
    digest = hashlib.sha256(f"{identity}\0{logical_key}".encode("utf-8")).hexdigest()[:16]
    return f"qf_{digest}"


def prepare_records(
    records: list[dict],
    *,
    source_name: str | None,
    source_hash: str | None,
    assets_root: Path | None,
    approve_review: bool,
) -> list[PreparedRecord]:
    prepared: list[PreparedRecord] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(records, start=1):
        question_body = str(item.get("question_body") or "").strip()
        answer_body = str(item.get("answer_body") or "").strip()
        if not question_body:
            raise MaterializationError(f"item {index}: question_body is empty")

        metadata = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
        review_needed = bool(
            item.get("human_review_needed")
            if item.get("human_review_needed") is not None
            else metadata.get("human_review_needed")
        )
        if review_needed and not approve_review:
            raise MaterializationError(
                f"item {index}: human_review_needed=true; review and rerun with --approve-review"
            )

        question_id = stable_question_id(
            item,
            index=index,
            source_name=source_name,
            source_hash=source_hash,
        )
        if question_id in seen_ids:
            raise MaterializationError(f"Duplicate resolved question_id: {question_id}")
        seen_ids.add(question_id)

        metadata["human_review_needed"] = False
        metadata.setdefault("import_method", "codex_skill")
        if source_name:
            metadata.setdefault("source_filename", source_name)
        if source_hash:
            metadata.setdefault("source_document_hash", source_hash)

        asset_entries: list[tuple[str, Path]] = []
        raw_asset_paths = referenced_asset_paths(question_body, answer_body)
        if raw_asset_paths and assets_root is None:
            raise MaterializationError(
                f"item {index}: body references assets but --assets-root was not provided"
            )
        if assets_root is not None:
            seen_asset_names: set[str] = set()
            for raw_path in sorted(raw_asset_paths):
                name, source_path = resolve_asset(assets_root, raw_path)
                if name in seen_asset_names:
                    raise MaterializationError(
                        f"item {index}: multiple asset paths resolve to the same filename: {name}"
                    )
                seen_asset_names.add(name)
                asset_entries.append((name, source_path))

        prepared.append(
            PreparedRecord(
                question_id=question_id,
                question_body=question_body,
                answer_body=answer_body,
                metadata=metadata,
                assets=tuple(asset_entries),
            )
        )
    return prepared


def tree_fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(directory)).encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def write_prepared_record(record: PreparedRecord, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "question.md").write_text(record.question_body + "\n", encoding="utf-8")
    if record.answer_body:
        (directory / "answer.md").write_text(record.answer_body + "\n", encoding="utf-8")
    (directory / "metadata.yaml").write_text(
        yaml.safe_dump(record.metadata, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    if record.assets:
        asset_dir = directory / "assets"
        asset_dir.mkdir()
        for name, source_path in record.assets:
            shutil.copy2(source_path, asset_dir / name)


def materialize(
    records: list[dict],
    questions_dir: Path,
    source_name: str | None,
    assets_root: Path | None,
    *,
    source_hash: str | None = None,
    approve_review: bool = False,
) -> list[Path]:
    questions_dir = questions_dir.resolve()
    questions_dir.mkdir(parents=True, exist_ok=True)
    staging_root = questions_dir / ".staging"
    staging_root.mkdir(exist_ok=True)
    batch_dir = staging_root / f"materialize-{uuid.uuid4().hex}"
    batch_dir.mkdir()

    prepared = prepare_records(
        records,
        source_name=source_name,
        source_hash=source_hash,
        assets_root=assets_root.resolve() if assets_root else None,
        approve_review=approve_review,
    )

    result_paths: list[Path] = []
    staged_paths: dict[str, Path] = {}
    try:
        for record in prepared:
            staged = batch_dir / record.question_id
            write_prepared_record(record, staged)
            staged_paths[record.question_id] = staged

        for record in prepared:
            destination = questions_dir / record.question_id
            staged = staged_paths[record.question_id]
            if destination.exists():
                if tree_fingerprint(destination) != tree_fingerprint(staged):
                    raise MaterializationError(
                        f"Question id conflict with different content: {record.question_id}"
                    )
                result_paths.append(destination)

        committed: list[Path] = []
        try:
            for record in prepared:
                destination = questions_dir / record.question_id
                if destination.exists():
                    continue
                staged_paths[record.question_id].replace(destination)
                committed.append(destination)
                result_paths.append(destination)
        except Exception:
            for destination in reversed(committed):
                if destination.exists():
                    destination.replace(batch_dir / destination.name)
            raise
    finally:
        shutil.rmtree(batch_dir, ignore_errors=True)

    return result_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely materialize validated records into question-bank directories."
    )
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--questions-dir", type=Path, default=Path("questions"))
    parser.add_argument("--source-name", default=None)
    parser.add_argument("--source-hash", default=None)
    parser.add_argument("--assets-root", type=Path, default=None)
    parser.add_argument(
        "--approve-review",
        action="store_true",
        help="Commit records explicitly marked human_review_needed after human approval.",
    )
    args = parser.parse_args()

    try:
        created = materialize(
            load_records(args.json_path),
            args.questions_dir,
            args.source_name,
            args.assets_root,
            source_hash=args.source_hash,
            approve_review=args.approve_review,
        )
    except (MaterializationError, OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(str(exc)) from exc

    for path in created:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
