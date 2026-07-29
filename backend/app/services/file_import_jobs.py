"""Single-user background import jobs for the file-first question bank.

This is intentionally a lightweight file-backed queue. It is meant for one
operator importing large batches without keeping the browser request open.
"""

from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.config import settings
from app.services.file_question_importer import (
    import_source_file,
    source_type_from_filename,
)
from app.services.file_question_store import rebuild_index


_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="file-import-job")
_WORKER_LOCK = Lock()
_WORKER_RUNNING = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jobs_root() -> Path:
    return settings.upload_dir / "file-import-jobs"


def ensure_jobs_root() -> Path:
    root = jobs_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_job_id(job_id: str) -> str:
    candidate = job_id.strip()
    if not re.fullmatch(r"fij_[A-Za-z0-9_]{8,80}", candidate):
        raise ValueError("Invalid import job id")
    return candidate


def new_job_id() -> str:
    return datetime.now(timezone.utc).strftime("fij_%Y%m%d_%H%M%S_") + uuid4().hex[:8]


def job_dir(job_id: str) -> Path:
    return ensure_jobs_root() / validate_job_id(job_id)


def manifest_path(job_id: str) -> Path:
    return job_dir(job_id) / "manifest.json"


def read_job(job_id: str) -> dict:
    path = manifest_path(job_id)
    if not path.exists():
        raise FileNotFoundError(job_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupted import job manifest: {job_id}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid import job manifest: {job_id}")
    return data


def _write_job(manifest: dict) -> dict:
    job_id = validate_job_id(str(manifest["job_id"]))
    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = manifest_path(job_id)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
    return manifest


def list_jobs(limit: int = 50) -> list[dict]:
    root = ensure_jobs_root()
    jobs: list[dict] = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        manifest = path / "manifest.json"
        if not manifest.exists():
            continue
        try:
            jobs.append(read_job(path.name))
        except Exception:
            continue
    return jobs[:limit]


def create_job(*, use_llm_assist: bool, overwrite: bool) -> dict:
    job_id = new_job_id()
    directory = job_dir(job_id)
    (directory / "source").mkdir(parents=True, exist_ok=True)
    manifest = {
        "job_id": job_id,
        "status": "draft",
        "created_at": utc_now(),
        "started_at": None,
        "finished_at": None,
        "use_llm_assist": bool(use_llm_assist),
        "overwrite": bool(overwrite),
        "source_files": [],
        "total_files": 0,
        "processed_files": 0,
        "current_file": None,
        "created_question_ids": [],
        "candidate_ids": [],
        "resolved_candidate_ids": [],
        "rejected_candidate_ids": [],
        "imported_count": 0,
        "review_count": 0,
        "errors": [],
        "warnings": [],
        "llm_used": False,
        "index_rebuilt": False,
    }
    return _write_job(manifest)


def source_dir_for(job_id: str) -> Path:
    return job_dir(job_id) / "source"


def _safe_upload_name(filename: str) -> str:
    return Path(filename).name or f"upload_{uuid4().hex[:8]}"


def add_source_file(
    manifest: dict,
    *,
    original_filename: str,
    payload: bytes,
    source_type: str,
    structured_json_batch: bool,
) -> dict:
    job_id = validate_job_id(str(manifest["job_id"]))
    safe_name = _safe_upload_name(original_filename)
    source_root = source_dir_for(job_id)
    if structured_json_batch and source_type == "image":
        target_dir = source_root / "assets"
        process = False
    else:
        target_dir = source_root
        process = True
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name
    if target.exists():
        target = target_dir / f"{uuid4().hex[:8]}_{safe_name}"
    target.write_bytes(payload)

    entry = {
        "filename": original_filename,
        "source_type": source_type,
        "relative_path": str(target.relative_to(job_dir(job_id))),
        "size_bytes": len(payload),
        "process": process,
        "status": "queued" if process else "asset",
    }
    manifest.setdefault("source_files", []).append(entry)
    manifest["total_files"] = sum(1 for item in manifest["source_files"] if item.get("process"))
    return _write_job(manifest)


def mark_job_queued(manifest: dict) -> dict:
    if manifest.get("total_files", 0) <= 0:
        manifest["status"] = "failed"
        manifest["finished_at"] = utc_now()
        manifest.setdefault("errors", []).append(
            {"filename": None, "error": "No supported source files were provided."}
        )
    else:
        manifest["status"] = "queued"
    return _write_job(manifest)


def append_job_error(manifest: dict, *, filename: str | None, error: str) -> dict:
    manifest.setdefault("errors", []).append({"filename": filename, "error": error})
    return _write_job(manifest)


def _queued_jobs() -> list[dict]:
    return [
        job
        for job in reversed(list_jobs(limit=10_000))
        if job.get("status") == "queued"
    ]


def _set_worker_running(value: bool) -> None:
    global _WORKER_RUNNING
    with _WORKER_LOCK:
        _WORKER_RUNNING = value


def kick_worker() -> None:
    global _WORKER_RUNNING
    with _WORKER_LOCK:
        if _WORKER_RUNNING:
            return
        _WORKER_RUNNING = True
    _EXECUTOR.submit(_process_queue)


def recover_and_start_jobs() -> None:
    for manifest in list_jobs(limit=10_000):
        if manifest.get("status") == "running":
            manifest["status"] = "queued"
            manifest["current_file"] = None
            manifest.setdefault("warnings", []).append("Recovered interrupted running job after server restart.")
            _write_job(manifest)
    if _queued_jobs():
        kick_worker()


def _update_source_status(manifest: dict, relative_path: str, status: str, error: str | None = None) -> None:
    for item in manifest.get("source_files", []):
        if item.get("relative_path") == relative_path:
            item["status"] = status
            if error:
                item["error"] = error
            break


def _process_queue() -> None:
    try:
        while True:
            queued = _queued_jobs()
            if not queued:
                return
            job_id = str(queued[0]["job_id"])
            try:
                _process_job(job_id)
            except Exception as exc:
                try:
                    manifest = read_job(job_id)
                    manifest["status"] = "failed"
                    manifest["finished_at"] = utc_now()
                    manifest["current_file"] = None
                    manifest.setdefault("errors", []).append(
                        {"filename": None, "error": f"Job worker failed: {exc}"}
                    )
                    _write_job(manifest)
                except Exception:
                    pass
    finally:
        _set_worker_running(False)
        if _queued_jobs():
            kick_worker()


def _process_job(job_id: str) -> None:
    manifest = read_job(job_id)
    manifest["status"] = "running"
    manifest["started_at"] = manifest.get("started_at") or utc_now()
    manifest["current_file"] = None
    _write_job(manifest)

    source_root = job_dir(job_id)
    processed = int(manifest.get("processed_files") or 0)
    imported_count = int(manifest.get("imported_count") or 0)
    created_ids = list(manifest.get("created_question_ids") or [])
    candidate_ids = list(manifest.get("candidate_ids") or [])
    review_count = int(manifest.get("review_count") or 0)
    errors = list(manifest.get("errors") or [])
    warnings = list(manifest.get("warnings") or [])
    llm_used = bool(manifest.get("llm_used"))

    for item in manifest.get("source_files", []):
        if not item.get("process"):
            continue
        if item.get("status") in {"done", "failed"}:
            continue

        filename = str(item.get("filename") or Path(str(item.get("relative_path"))).name)
        relative_path = str(item.get("relative_path"))
        path = source_root / relative_path
        manifest["current_file"] = filename
        _update_source_status(manifest, relative_path, "running")
        _write_job(manifest)

        try:
            result = asyncio.run(
                import_source_file(
                    source_path=path,
                    original_filename=filename,
                    use_llm_assist=bool(manifest.get("use_llm_assist")),
                    overwrite=bool(manifest.get("overwrite")),
                    rebuild_after=False,
                )
            )
            llm_used = llm_used or result.llm_used
            for question in result.questions:
                if question.question_id not in created_ids:
                    created_ids.append(question.question_id)
                imported_count += 1
            for candidate in result.candidates:
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate_id and candidate_id not in candidate_ids:
                    candidate_ids.append(candidate_id)
                    review_count += 1
            warnings.extend(f"{filename}: {warning}" for warning in result.warnings)
            _update_source_status(
                manifest,
                relative_path,
                "needs_review" if result.candidates else "done",
            )
        except Exception as exc:
            error = str(exc)
            errors.append({"filename": filename, "error": error})
            _update_source_status(manifest, relative_path, "failed", error)

        processed += 1
        manifest.update(
            {
                "processed_files": processed,
                "imported_count": imported_count,
                "created_question_ids": created_ids,
                "candidate_ids": candidate_ids,
                "review_count": review_count,
                "errors": errors,
                "warnings": warnings,
                "llm_used": llm_used,
            }
        )
        _write_job(manifest)

    if imported_count > 0:
        try:
            rebuild_index()
            manifest["index_rebuilt"] = True
        except Exception as exc:
            errors.append({"filename": None, "error": f"Index rebuild failed: {exc}"})

    manifest["current_file"] = None
    manifest["finished_at"] = utc_now()
    manifest["errors"] = errors
    if review_count > 0:
        manifest["status"] = "needs_review"
    elif imported_count > 0 and errors:
        manifest["status"] = "partial"
    elif imported_count > 0:
        manifest["status"] = "succeeded"
    else:
        manifest["status"] = "failed"
    _write_job(manifest)


def source_type_or_error(filename: str) -> str:
    source_type = source_type_from_filename(filename)
    if not source_type:
        raise ValueError(f"Unsupported file type: {Path(filename).suffix or filename}")
    return source_type


def record_candidate_resolution(
    candidate_id: str,
    *,
    question_id: str | None = None,
    rejected: bool = False,
) -> None:
    """Update any import job that owns a resolved review candidate."""
    for manifest in list_jobs(limit=10_000):
        candidate_ids = [str(item) for item in manifest.get("candidate_ids", []) if item]
        if candidate_id not in candidate_ids:
            continue

        resolved = [str(item) for item in manifest.get("resolved_candidate_ids", []) if item]
        rejected_ids = [str(item) for item in manifest.get("rejected_candidate_ids", []) if item]
        if candidate_id not in resolved:
            resolved.append(candidate_id)
        if rejected and candidate_id not in rejected_ids:
            rejected_ids.append(candidate_id)

        created_ids = [str(item) for item in manifest.get("created_question_ids", []) if item]
        if question_id and question_id not in created_ids:
            created_ids.append(question_id)
            manifest["imported_count"] = int(manifest.get("imported_count") or 0) + 1

        pending = [item for item in candidate_ids if item not in resolved]
        manifest["resolved_candidate_ids"] = resolved
        manifest["rejected_candidate_ids"] = rejected_ids
        manifest["created_question_ids"] = created_ids
        manifest["review_count"] = len(pending)
        if not pending and manifest.get("status") == "needs_review":
            if manifest.get("errors") or rejected_ids:
                manifest["status"] = "partial" if manifest.get("imported_count") else "failed"
            else:
                manifest["status"] = "succeeded"
            manifest["finished_at"] = utc_now()
        _write_job(manifest)
