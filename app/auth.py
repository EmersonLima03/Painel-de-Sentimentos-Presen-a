"""Autenticação mínima por token (API_AUTH_TOKEN)."""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, Request

from app.config import get_settings


def _extract_token(
    request: Request,
    x_api_token: Optional[str],
    authorization: Optional[str],
) -> Optional[str]:
    token = x_api_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        token = request.query_params.get("api_token")
    return token


async def require_api_token(
    request: Request,
    x_api_token: Optional[str] = Header(default=None, alias="X-API-Token"),
    authorization: Optional[str] = Header(default=None),
) -> None:
    """
    Se API_AUTH_TOKEN estiver vazio → modo aberto (dev).
    Se definido → exige X-API-Token, Bearer ou ?api_token=.
    """
    settings = get_settings()
    expected = (settings.api_auth_token or "").strip()
    if not expected:
        return

    token = _extract_token(request, x_api_token, authorization)
    if token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized — provide X-API-Token")
