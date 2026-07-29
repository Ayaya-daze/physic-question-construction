"""FastAPI application entry point for the Physics Question Bank API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text, update

from app.api import (
    file_questions,
    imports,
    knowledge_point_candidates,
    knowledge_points,
    papers,
    questions,
    review,
    tags,
    uploads,
)
from app.config import settings
from app.database import async_session_factory, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize database tables and recover stuck jobs."""
    await init_db()

    try:
        from app.services.file_question_store import recover_interrupted_writes

        recover_interrupted_writes()
    except Exception:
        pass

    try:
        from app.services.file_import_jobs import recover_and_start_jobs

        recover_and_start_jobs()
    except Exception:
        pass

    # Recover extraction jobs left in pending/running state by a previous crash
    try:
        from app.models.extraction import ExtractionJob

        async with async_session_factory() as session:
            result = await session.execute(
                update(ExtractionJob)
                .where(ExtractionJob.status.in_(["pending", "running"]))
                .values(
                    status="failed",
                    error_message="Server restarted — job was interrupted.",
                    finished_at=datetime.now(timezone.utc),
                )
            )
            count = result.rowcount
            if count:
                print(f"  Recovered {count} stuck extraction job(s) from previous session.")
            await session.commit()
    except Exception:
        pass  # Non-critical — table may not exist on first run

    yield


app = FastAPI(
    title="Physics Question Bank API",
    version="0.1.0",
    description="REST API for managing physics questions, knowledge points, and tags.",
    lifespan=lifespan,
)

# ──────────────────────────────────────────────
# CORS middleware
# ──────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Include routers
# ──────────────────────────────────────────────

app.include_router(questions.router, prefix="/api/questions")
app.include_router(knowledge_points.router, prefix="/api/knowledge-points")
app.include_router(tags.router, prefix="/api/tags")
app.include_router(imports.router, prefix="/api/imports")
app.include_router(file_questions.router, prefix="/api/file-questions", tags=["file-questions"])
app.include_router(uploads.router, prefix="/api/uploads")
app.include_router(review.router, prefix="/api/review")
app.include_router(papers.router, prefix="/api/papers")
app.include_router(knowledge_point_candidates.router, prefix="/api/knowledge-point-candidates")

# Serve uploaded page images as static files
uploads_pages_dir = settings.upload_dir / "pages"
uploads_pages_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media/pages", StaticFiles(directory=str(uploads_pages_dir)), name="media_pages")


# ──────────────────────────────────────────────
# Root and health endpoints
# ──────────────────────────────────────────────


@app.get("/")
async def root():
    """Root endpoint returning API metadata."""
    return {
        "message": "Physics Question Bank API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint — verifies database connectivity."""
    db_connected = False
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            db_connected = True
    except Exception:
        db_connected = False

    status_code = 200 if db_connected else 503
    return {
        "status": "ok" if db_connected else "degraded",
        "database": "connected" if db_connected else "disconnected",
    }
