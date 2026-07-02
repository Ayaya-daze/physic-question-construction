#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
from pathlib import Path

import yaml


def safe_id() -> str:
    return f"qf_{uuid.uuid4().hex[:10]}"


def load_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("Top-level value must be a JSON array.")
    return data


def referenced_asset_names(*bodies: str) -> set[str]:
    names: set[str] = set()
    for body in bodies:
        names.update(Path(match).name for match in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body))
        names.update(Path(match).name for match in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", body))
    return {name for name in names if name}


def looks_like_rendered_pdf_page(name: str) -> bool:
    stem = Path(name).stem.lower()
    suffix = Path(name).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".webp"} and bool(
        re.fullmatch(r"(?:page|p)[_-]?\d{1,4}", stem)
    )


def copy_referenced_assets(
    *,
    assets_root: Path,
    asset_dir: Path,
    question_body: str,
    answer_body: str,
) -> None:
    """Copy only independent assets explicitly referenced by the body files.

    ``metadata.source_pages`` is audit metadata for rendered whole-page PDF
    images. It must not trigger asset copying.
    """
    for name in sorted(referenced_asset_names(question_body, answer_body)):
        if looks_like_rendered_pdf_page(name):
            raise SystemExit(
                f"Refusing to materialize rendered PDF page image as a question asset: {name}"
            )
        src = assets_root / name
        if not src.exists() or not src.is_file():
            raise SystemExit(f"Referenced asset not found under {assets_root}: {name}")
        asset_dir.mkdir(exist_ok=True)
        shutil.copy2(src, asset_dir / src.name)


def materialize(records: list[dict], questions_dir: Path, source_name: str | None, assets_root: Path | None) -> list[Path]:
    questions_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for item in records:
        qid = safe_id()
        qdir = questions_dir / qid
        while qdir.exists():
            qid = safe_id()
            qdir = questions_dir / qid
        qdir.mkdir()

        question_body = str(item.get("question_body", "")).strip()
        answer_body = str(item.get("answer_body", "")).strip()
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if source_name:
            metadata.setdefault("source_filename", source_name)
        metadata.setdefault("import_method", "codex_skill")

        (qdir / "question.md").write_text(question_body + "\n", encoding="utf-8")
        if answer_body:
            (qdir / "answer.md").write_text(answer_body + "\n", encoding="utf-8")
        (qdir / "metadata.yaml").write_text(
            yaml.dump(metadata, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        if assets_root and assets_root.exists():
            copy_referenced_assets(
                assets_root=assets_root,
                asset_dir=qdir / "assets",
                question_body=question_body,
                answer_body=answer_body,
            )
        created.append(qdir)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize validated records into question-bank directories.")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--questions-dir", type=Path, default=Path("questions"))
    parser.add_argument("--source-name", default=None)
    parser.add_argument("--assets-root", type=Path, default=None)
    args = parser.parse_args()

    records = load_records(args.json_path)
    created = materialize(records, args.questions_dir, args.source_name, args.assets_root)
    for path in created:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
