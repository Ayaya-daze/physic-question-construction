"""Application configuration using pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        case_sensitive=False,
    )

    # Database — defaults to SQLite for zero-dependency local dev.
    # Set DATABASE_URL to a postgresql+asyncpg://… URI to switch to PostgreSQL.
    DATABASE_URL: str = "sqlite+aiosqlite:///./physics_questions.db"
    DATABASE_URL_SYNC: str = "sqlite:///./physics_questions.db"

    # Redis (reserved for future caching)
    REDIS_URL: str = "redis://localhost:6379/0"

    # API
    API_PREFIX: str = "/api"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Server
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = False

    # ── Upload / File Storage ──────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"  # relative to backend/ or absolute
    MAX_UPLOAD_SIZE_MB: int = 100

    @property
    def upload_dir(self) -> Path:
        p = Path(self.UPLOAD_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / p
        return p

    # ── File-first Question Store ─────────────────────────────────────
    # Default resolves to <project-root>/questions for local development.
    QUESTIONS_DIR: str = "../questions"

    @property
    def questions_dir(self) -> Path:
        p = Path(self.QUESTIONS_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / p
        return p.resolve()

    # ── OCR ────────────────────────────────────────────────────────────
    OCR_LANG: str = "chi_sim+eng+equ"
    OCR_DPI: int = 300

    # ── LLM ────────────────────────────────────────────────────────────
    LLM_PROVIDER: str = "anthropic"  # "anthropic" or "openai_compatible"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-4-20250514"
    LLM_BASE_URL: str = ""  # custom endpoint for openai_compatible mode
    LLM_MAX_TOKENS: int = 4096
    LLM_ENABLED: bool = False  # gate: set True to activate LLM structuring
    # Anthropic provider is vision-capable by default. OpenAI-compatible
    # endpoints vary, so require an explicit opt-in before sending images.
    LLM_VISION_ENABLED: bool = False

    # ── Embedding API / Local Retrieval ───────────────────────────────
    EMBEDDING_ENABLED: bool = False
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://api.openai.com/v1"
    EMBEDDING_MODEL: str = ""
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_TIMEOUT_SECONDS: int = 60

    # ── Paper Generation / Export ───────────────────────────────────────
    EXPORTS_DIR: str = "./exports"
    LATEX_ENGINE: str = "xelatex"  # xelatex or lualatex
    LATEX_COMPILE_TIMEOUT_SECONDS: int = 90
    FILE_EXPORT_MAX_WORKERS: int = 1
    EXPORT_RETENTION_DAYS: int = 30
    UPLOAD_RETENTION_DAYS: int = 14

    @property
    def exports_dir(self) -> Path:
        p = Path(self.EXPORTS_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / p
        return p


settings = Settings()
