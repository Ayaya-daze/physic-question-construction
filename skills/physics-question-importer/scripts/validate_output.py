#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def referenced_asset_names(text: str) -> set[str]:
    names = {Path(match).name for match in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)}
    names.update(Path(match).name for match in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text))
    return {name for name in names if name}


def looks_like_rendered_pdf_page(name: str) -> bool:
    stem = Path(name).stem.lower()
    suffix = Path(name).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".webp"} and bool(
        re.fullmatch(r"(?:page|p)[_-]?\d{1,4}", stem)
    )


def load_records(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Invalid JSON: {exc}")
    if not isinstance(data, list):
        raise SystemExit("Top-level value must be a JSON array.")
    return data


def validate_assets(records: list[dict], json_path: Path) -> list[str]:
    errors: list[str] = []
    assets_root = json_path.parent / "assets"
    for idx, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            continue
        body_text = "\n".join(
            value
            for value in (item.get("question_body"), item.get("answer_body"))
            if isinstance(value, str)
        )
        for name in referenced_asset_names(body_text):
            if looks_like_rendered_pdf_page(name):
                continue
            if not (assets_root / name).is_file():
                errors.append(f"item {idx}: referenced asset not found under {assets_root}: {name}")
    return errors


def validate(records: list[dict]) -> list[str]:
    errors: list[str] = []
    for idx, item in enumerate(records, start=1):
        prefix = f"item {idx}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        question_body = item.get("question_body")
        answer_body = item.get("answer_body")
        metadata = item.get("metadata")
        if not isinstance(question_body, str) or not question_body.strip():
            errors.append(f"{prefix}: question_body must be a non-empty string")
        if not isinstance(answer_body, str):
            errors.append(f"{prefix}: answer_body must be a string")
        if not isinstance(metadata, dict):
            errors.append(f"{prefix}: metadata must be an object")
            continue
        title = metadata.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{prefix}: metadata.title must be a non-empty string")
        kps = metadata.get("knowledge_points")
        if not isinstance(kps, list) or not all(isinstance(v, str) and v.strip() for v in kps):
            errors.append(f"{prefix}: metadata.knowledge_points must be a list of strings")
        question_type = metadata.get("question_type")
        if question_type is not None and (not isinstance(question_type, str) or not question_type.strip()):
            errors.append(f"{prefix}: metadata.question_type must be a non-empty string when present")
        tags = metadata.get("tags")
        if tags is not None and (
            not isinstance(tags, list) or not all(isinstance(v, str) and v.strip() for v in tags)
        ):
            errors.append(f"{prefix}: metadata.tags must be a list of strings when present")
        pages = metadata.get("source_pages")
        if pages is not None and (
            not isinstance(pages, list) or not all(isinstance(v, int) and v > 0 for v in pages)
        ):
            errors.append(f"{prefix}: metadata.source_pages must be a list of positive integers")
        review_needed = metadata.get("human_review_needed")
        if review_needed is not None and not isinstance(review_needed, bool):
            errors.append(f"{prefix}: metadata.human_review_needed must be a boolean when present")
        if isinstance(question_body, str) and re.search(r"\\frac|\\theta|\\omega|\\alpha|\\Delta", question_body):
            if "$" not in question_body and r"\[" not in question_body:
                errors.append(f"{prefix}: LaTeX-like content appears without math delimiters")
        body_text = "\n".join(
            value for value in (question_body, answer_body) if isinstance(value, str)
        )
        for name in referenced_asset_names(body_text):
            if looks_like_rendered_pdf_page(name):
                errors.append(
                    f"{prefix}: rendered PDF page image must not be referenced as a question asset: {name}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate physics question importer JSON output.")
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args()

    records = load_records(args.json_path)
    errors = validate(records)
    errors.extend(validate_assets(records, args.json_path))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"OK: {len(records)} question record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
