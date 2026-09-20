"""
Stage 11 backend configuration.

All secrets/connection strings come from environment variables - nothing is
hardcoded, and this file never prints or logs a secret value. CONTENT_AGENT_API_SECRET
in particular gates every write endpoint (see app/security.py); if it is not set,
writes are refused rather than silently allowed (fail closed).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[0]=backend/app, parents[1]=backend, parents[2]=repo root.
# __file__ is always absolute, so this anchor is independent of the process's CWD.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/content_agent"
    cors_origins: str = "http://localhost:3000"
    content_agent_api_secret: str | None = None
    # Stage 10's own QA-gated export - the ONLY file this backend's importer ever reads.
    stage10_export_path: str = "data/instagram/exports/flyingfish_publish_ready.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def stage10_export_abs_path(self) -> Path:
        """stage10_export_path resolved against the repo root, not the process CWD."""
        path = Path(self.stage10_export_path)
        return path if path.is_absolute() else REPO_ROOT / path


settings = Settings()
