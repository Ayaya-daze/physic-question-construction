"""Manage the agent-assisted import inbox.

Humans drop source files or source bundles into ``imports/inbox``. This script
turns them into stable jobs and finalizes completed skill outputs into the
file-first question bank.

The script deliberately does not pretend that local OCR can solve scanned
papers. Scanned PDFs/images are prepared as agent jobs. A Codex agent using the
``physics-question-importer`` skill writes ``output/questions.json`` and
optional ``output/assets/*``; this script validates and materializes that output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_DIR = Path(os.environ.get("PHYSICS_IMPORTER_SKILL_DIR", SKILL_DIR))

SOURCE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".md",
    ".markdown",
    ".txt",
    ".tex",
    ".latex",
    ".docx",
    ".doc",
    ".json",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    stem = Path(value).stem if Path(value).suffix else value
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-").lower()
    return slug[:60] or "source"


def source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(str(child.relative_to(path)).encode("utf-8", errors="ignore"))
            digest.update(str(child.stat().st_size).encode("ascii"))
            with child.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def ensure_layout(imports_dir: Path) -> dict[str, Path]:
    paths = {
        "imports": imports_dir,
        "inbox": imports_dir / "inbox",
        "jobs": imports_dir / "jobs",
        "done": imports_dir / "done",
        "failed": imports_dir / "failed",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def read_manifest(job_dir: Path) -> dict[str, Any]:
    path = job_dir / "manifest.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(job_dir: Path, manifest: dict[str, Any]) -> None:
    (job_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def skill_script(skill_dir: Path, name: str) -> Path:
    path = skill_dir / "scripts" / name
    if not path.exists():
        raise FileNotFoundError(f"Missing skill script: {path}")
    return path


def run_cmd(
    args: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def validate_questions_json(json_path: Path, skill_dir: Path) -> tuple[bool, str]:
    proc = run_cmd([sys.executable, str(skill_script(skill_dir, "validate_output.py")), str(json_path)])
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def source_entries(source_root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(source_root.rglob("*")):
        if path.is_file():
            entries.append(
                {
                    "path": str(path.relative_to(source_root)),
                    "size_bytes": str(path.stat().st_size),
                }
            )
    return entries


def source_names(manifest: dict[str, Any]) -> str:
    names = []
    for item in manifest.get("sources", []):
        if isinstance(item, dict) and item.get("path"):
            names.append(Path(str(item["path"])).name)
    return ", ".join(names[:5]) or manifest.get("job_id") or "agent-inbox"


def copytree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)
        elif child.is_file():
            shutil.copy2(child, target)


def prepare_ready_output_from_json(job_dir: Path, skill_dir: Path) -> tuple[bool, str]:
    """Detect already structured JSON bundles and copy them to output/."""
    source_root = job_dir / "source"
    output_dir = job_dir / "output"
    output_json = output_dir / "questions.json"
    candidates = []
    preferred_names = {"questions.json", "output.json", "import.json"}
    for path in sorted(source_root.rglob("*.json")):
        if path.name in preferred_names:
            candidates.insert(0, path)
        else:
            candidates.append(path)

    errors: list[str] = []
    for candidate in candidates:
        ok, message = validate_questions_json(candidate, skill_dir)
        if not ok:
            errors.append(f"{candidate.relative_to(source_root)}: {message}")
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, output_json)
        assets_dir = candidate.parent / "assets"
        if assets_dir.exists() and assets_dir.is_dir():
            copytree_contents(assets_dir, output_dir / "assets")
        return True, f"Structured JSON detected: {candidate.relative_to(source_root)}"

    return False, "\n".join(errors[:3])


def write_agent_task(job_dir: Path, manifest: dict[str, Any]) -> None:
    source_lines = "\n".join(
        f"- `{item['path']}` ({item['size_bytes']} bytes)"
        for item in manifest.get("sources", [])
        if isinstance(item, dict)
    )
    task = f"""# Agent Import Task: {manifest["job_id"]}

Use the `physics-question-importer` skill to convert the source files in this job into the project file-first question format.

## Source Files

{source_lines or "- No source files listed; inspect `source/` manually."}

## Required Output

Write:

```text
{job_dir}/output/questions.json
{job_dir}/output/assets/        # optional independent cropped figures only
```

`questions.json` must be a JSON array of records:

```json
[
  {{
    "question_body": "Markdown/LaTeX question text",
    "answer_body": "explicit source answer only, or empty string",
    "metadata": {{
      "title": "short title",
      "knowledge_points": ["concepts discovered from the source"],
      "source_pages": [1],
      "human_review_needed": true
    }}
  }}
]
```

## Rules

- Keep the core model simple: question body, answer body, loose metadata, independent assets.
- For scanned PDFs/images, read page images as source of truth; OCR is only a hint.
- Split only visible major problem numbers such as `1.`, `2.`, `7.(40分)`.
- Keep subparts `(1)(2)(3)` and `①②③` inside the parent problem.
- Do not force the output count to match a declared count.
- Use Markdown with LaTeX math delimiters `$...$` or `$$...$$`.
- Do not solve questions. Fill `answer_body` only when the source explicitly contains an answer.
- Do not reference rendered whole PDF pages as assets. Crop or attach only independent question figures.
- Mark uncertain records with `human_review_needed: true`.

## Validate

After writing output:

```bash
python3 {SKILL_DIR}/scripts/validate_output.py {job_dir}/output/questions.json
```

Then run:

```bash
python3 {SKILL_DIR}/scripts/agent_inbox.py --project-root {manifest["project_root"]} finalize
```
"""
    (job_dir / "AGENT_TASK.md").write_text(task, encoding="utf-8")


def make_job(
    item: Path,
    paths: dict[str, Path],
    *,
    copy: bool,
    skill_dir: Path,
    project_root: Path,
) -> tuple[Path, dict[str, Any]]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    digest = source_digest(item)
    job_id = f"{timestamp}_{slugify(item.name)}_{digest[:12]}"
    job_dir = paths["jobs"] / job_id
    counter = 2
    while job_dir.exists():
        job_dir = paths["jobs"] / f"{job_id}_{counter}"
        counter += 1

    source_root = job_dir / "source"
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "assets").mkdir(exist_ok=True)
    source_root.mkdir(parents=True)

    target = source_root / item.name
    if copy:
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    else:
        shutil.move(str(item), str(target))

    manifest = {
        "job_id": job_dir.name,
        "status": "needs_agent",
        "created_at": utc_now(),
        "project_root": str(project_root),
        "source_root": "source",
        "output_json": "output/questions.json",
        "output_assets": "output/assets",
        "source_document_hash": digest,
        "sources": source_entries(source_root),
        "notes": [],
    }

    ready, message = prepare_ready_output_from_json(job_dir, skill_dir)
    if ready:
        manifest["status"] = "ready_to_finalize"
        manifest["notes"].append(message)
    elif message:
        manifest["notes"].append("Structured JSON auto-detection failed; agent processing required.")
        manifest["notes"].append(message)

    write_manifest(job_dir, manifest)
    write_agent_task(job_dir, manifest)
    return job_dir, manifest


def discover(args: argparse.Namespace) -> int:
    paths = ensure_layout(args.imports_dir)
    inbox = paths["inbox"]
    candidates = [
        item
        for item in sorted(inbox.iterdir())
        if not item.name.startswith(".") and item.name != "README.md"
    ]
    candidates = [
        item
        for item in candidates
        if not (item.is_dir() and item.name.lower() == "assets")
    ]

    created = 0
    skipped: list[str] = []
    for item in candidates:
        if item.is_file() and item.suffix.lower() not in SOURCE_EXTENSIONS:
            skipped.append(f"{item.name}: unsupported extension")
            continue
        if item.is_dir() and not any(child.is_file() for child in item.rglob("*")):
            skipped.append(f"{item.name}: empty directory")
            continue
        job_dir, manifest = make_job(
            item,
            paths,
            copy=args.copy,
            skill_dir=args.skill_dir,
            project_root=args.project_root,
        )
        created += 1
        print(f"created {manifest['status']}: {job_dir}")

    for message in skipped:
        print(f"skipped {message}", file=sys.stderr)
    if created == 0:
        print(f"No new inbox items under {inbox}")
    return 0


def iter_job_dirs(imports_dir: Path) -> list[Path]:
    jobs_dir = ensure_layout(imports_dir)["jobs"]
    return sorted(path for path in jobs_dir.iterdir() if path.is_dir())


def status(args: argparse.Namespace) -> int:
    paths = ensure_layout(args.imports_dir)
    for label in ("jobs", "done", "failed"):
        root = paths[label]
        print(f"{label}:")
        dirs = sorted(path for path in root.iterdir() if path.is_dir())
        if not dirs:
            print("  (empty)")
            continue
        for job_dir in dirs:
            manifest = read_manifest(job_dir)
            status_value = manifest.get("status", "unknown")
            output_ready = (job_dir / "output/questions.json").exists()
            print(f"  {job_dir.name}  status={status_value}  output={'yes' if output_ready else 'no'}")
    return 0


def materialize_job(job_dir: Path, args: argparse.Namespace) -> tuple[bool, str]:
    manifest = read_manifest(job_dir)
    output_json = job_dir / "output/questions.json"
    assets_root = job_dir / "output/assets"
    if not output_json.exists():
        return False, "missing output/questions.json"

    ok, validation_message = validate_questions_json(output_json, args.skill_dir)
    if not ok:
        return False, validation_message

    materialize_script = skill_script(args.skill_dir, "materialize_questions.py")
    proc_args = [
        sys.executable,
        str(materialize_script),
        str(output_json),
        "--questions-dir",
        str(args.questions_dir),
        "--source-name",
        source_names(manifest),
    ]
    source_hash = manifest.get("source_document_hash")
    if source_hash:
        proc_args.extend(["--source-hash", str(source_hash)])
    if assets_root.exists():
        proc_args.extend(["--assets-root", str(assets_root)])
    if getattr(args, "approve_review", False):
        proc_args.append("--approve-review")

    proc = run_cmd(proc_args, cwd=args.project_root)
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        return False, output

    created_paths = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    manifest.update(
        {
            "status": "done",
            "finalized_at": utc_now(),
            "created_questions": created_paths,
            "validation": validation_message,
        }
    )
    write_manifest(job_dir, manifest)
    return True, output


def reindex_project(args: argparse.Namespace) -> tuple[bool, str]:
    """Best-effort reindex for this project's FastAPI file-question store.

    The skill remains generic: materialization is handled by bundled scripts.
    Reindexing is optional and only runs when the target project exposes the
    expected backend module.
    """
    backend_dir = args.project_root / "backend"
    store_module = backend_dir / "app/services/file_question_store.py"
    if not store_module.exists():
        return False, "reindex skipped: backend/app/services/file_question_store.py not found"

    python_bin = backend_dir / "venv/bin/python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir)
    code = (
        "from app.services.file_question_store import rebuild_index; "
        "idx=rebuild_index(); "
        "print(f\"reindexed {len(idx.get('items', []))} question(s)\")"
    )
    proc = run_cmd([str(python_bin), "-c", code], cwd=args.project_root, env=env)
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def move_job(job_dir: Path, destination_root: Path) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    target = destination_root / job_dir.name
    counter = 2
    while target.exists():
        target = destination_root / f"{job_dir.name}_{counter}"
        counter += 1
    shutil.move(str(job_dir), str(target))
    return target


def finalize(args: argparse.Namespace) -> int:
    paths = ensure_layout(args.imports_dir)
    successes = 0
    failures = 0
    review_pending = 0
    for job_dir in iter_job_dirs(args.imports_dir):
        output_json = job_dir / "output/questions.json"
        if args.only_ready and not output_json.exists():
            continue
        if not output_json.exists():
            print(f"needs agent: {job_dir} (no output/questions.json)")
            continue

        ok, message = materialize_job(job_dir, args)
        if ok:
            successes += 1
            if not args.no_reindex:
                reindex_ok, reindex_message = reindex_project(args)
                if reindex_message:
                    print(reindex_message)
                if not reindex_ok:
                    print(reindex_message, file=sys.stderr)
            destination = move_job(job_dir, paths["done"]) if not args.keep_jobs else job_dir
            print(f"done: {destination}")
            if message:
                print(message)
        else:
            if "human_review_needed=true" in message:
                review_pending += 1
                manifest = read_manifest(job_dir)
                manifest.update(
                    {
                        "status": "needs_review",
                        "review_requested_at": utc_now(),
                        "review_message": message,
                    }
                )
                write_manifest(job_dir, manifest)
                print(f"needs review: {job_dir}", file=sys.stderr)
                print(message, file=sys.stderr)
                continue
            failures += 1
            manifest = read_manifest(job_dir)
            manifest.update({"status": "failed", "failed_at": utc_now(), "error": message})
            write_manifest(job_dir, manifest)
            (job_dir / "error.log").write_text(message + "\n", encoding="utf-8")
            destination = move_job(job_dir, paths["failed"]) if args.move_failed else job_dir
            print(f"failed: {destination}", file=sys.stderr)
            print(message, file=sys.stderr)

    print(
        f"finalize summary: {successes} done, "
        f"{review_pending} needs review, {failures} failed"
    )
    return 1 if failures else 0


def run(args: argparse.Namespace) -> int:
    discover(args)
    return finalize(args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent-assisted import inbox manager.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--imports-dir", type=Path, default=None)
    parser.add_argument("--questions-dir", type=Path, default=None)
    parser.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR)
    parser.add_argument("--copy", action="store_true", help="Copy inbox files instead of moving them into jobs.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Create imports/inbox, jobs, done, failed directories.")
    subparsers.add_parser("discover", help="Create jobs for new inbox files.")
    subparsers.add_parser("status", help="Show inbox job status.")

    finalize_parser = subparsers.add_parser("finalize", help="Validate and materialize completed job outputs.")
    finalize_parser.add_argument("--keep-jobs", action="store_true", help="Do not move finalized jobs to imports/done.")
    finalize_parser.add_argument("--move-failed", action="store_true", help="Move failed jobs to imports/failed.")
    finalize_parser.add_argument("--only-ready", action="store_true", help="Skip jobs that do not have output/questions.json.")
    finalize_parser.add_argument("--no-reindex", action="store_true", help="Do not rebuild the file-question index.")
    finalize_parser.add_argument(
        "--approve-review",
        action="store_true",
        help="Commit records marked human_review_needed after explicit human approval.",
    )

    run_parser = subparsers.add_parser("run", help="Discover inbox items and finalize completed outputs.")
    run_parser.add_argument("--keep-jobs", action="store_true")
    run_parser.add_argument("--move-failed", action="store_true")
    run_parser.add_argument("--only-ready", action="store_true")
    run_parser.add_argument("--no-reindex", action="store_true")
    run_parser.add_argument("--approve-review", action="store_true")

    args = parser.parse_args()
    args.project_root = args.project_root.resolve()
    args.imports_dir = (args.imports_dir or (args.project_root / "imports")).resolve()
    args.questions_dir = (args.questions_dir or (args.project_root / "questions")).resolve()
    args.skill_dir = args.skill_dir.resolve()

    if args.command == "init":
        ensure_layout(args.imports_dir)
        print(f"initialized {args.imports_dir}")
        return 0
    if args.command == "discover":
        return discover(args)
    if args.command == "status":
        return status(args)
    if args.command == "finalize":
        return finalize(args)
    if args.command == "run":
        return run(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
