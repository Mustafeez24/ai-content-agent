"""
Interim write-endpoint security gate (Stage 11).

Full user authentication is explicitly deferred. Until it exists, every write
endpoint (PATCH /api/content/{id}/status, POST /api/content/{id}/notes,
POST /api/imports/run) requires a shared secret sent as the X-API-Secret header,
matched against the CONTENT_AGENT_API_SECRET environment variable. The secret is
never hardcoded here or anywhere else - it is read from the environment only, via
app.config.settings. Read endpoints remain open for initial internal testing.
"""

from fastapi import Header, HTTPException, status

from app.config import settings


def require_api_secret(x_api_secret: str | None = Header(default=None)) -> None:
    configured = settings.content_agent_api_secret
    if not configured:
        # Fail closed: an unconfigured secret must never be treated as "no secret
        # required" - that would silently open every write endpoint.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Write access is not configured on this server (CONTENT_AGENT_API_SECRET is not set).",
        )
    if not x_api_secret or x_api_secret != configured:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API secret.")
