"""Clean old upload/import and export artifacts.

Default mode is dry-run. Pass ``--delete`` to remove files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _old_children(root: Path, days: int) -> list[Path]:
    if days <= 0 or not root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    old: list[Path] = []
    for path in root.iterdir():
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except FileNotFoundError:
            continue
        if modified < cutoff:
            old.append(path)
    return old


def _old_completed_import_jobs(root: Path, days: int) -> list[Path]:
    if days <= 0 or not root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    old: list[Path] = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = manifest.get("status")
            finished_at = manifest.get("finished_at")
            if status not in {"succeeded", "partial", "failed"} or not finished_at:
                continue
            finished = datetime.fromisoformat(str(finished_at))
        except Exception:
            continue
        if finished < cutoff:
            old.append(path)
    return old


def _remove(path: Path, root: Path) -> None:
    if not _is_within(path, root):
        raise RuntimeError(f"Refusing to remove outside root: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean old runtime artifacts.")
    parser.add_argument("--delete", action="store_true", help="Actually delete old artifacts.")
    parser.add_argument("--exports-days", type=int, default=settings.EXPORT_RETENTION_DAYS)
    parser.add_argument("--uploads-days", type=int, default=settings.UPLOAD_RETENTION_DAYS)
    args = parser.parse_args()

    targets = [
        ("exports", settings.exports_dir / "file-papers", args.exports_days),
        ("file-import uploads", settings.upload_dir / "file-imports", args.uploads_days),
    ]
    total = 0
    for label, root, days in targets:
        old_paths = _old_children(root, days)
        print(f"{label}: {len(old_paths)} item(s) older than {days} day(s) under {root}")
        for path in old_paths:
            total += 1
            print(f"  {'DELETE' if args.delete else 'DRY-RUN'} {path}")
            if args.delete:
                _remove(path, root)

    import_jobs_root = settings.upload_dir / "file-import-jobs"
    old_jobs = _old_completed_import_jobs(import_jobs_root, args.uploads_days)
    print(f"file-import jobs: {len(old_jobs)} completed item(s) older than {args.uploads_days} day(s) under {import_jobs_root}")
    for path in old_jobs:
        total += 1
        print(f"  {'DELETE' if args.delete else 'DRY-RUN'} {path}")
        if args.delete:
            _remove(path, import_jobs_root)

    if not args.delete:
        print("Dry run only. Re-run with --delete to remove these artifacts.")
    print(f"Total matched: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
