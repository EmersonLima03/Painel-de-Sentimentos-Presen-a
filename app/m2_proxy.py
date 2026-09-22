"""Reverse proxy Edge (:8000) → M2 enrollment (:8766) for selected paths only.

Proxied prefixes (no catch-all):
  /gestor, /gestor/*, /gestor-static/*
  /a/*, /aluno-static/*
  /api/gestor/*, /api/aluno/*
  /m2/healthz → M2 /healthz

Gestor HTML/API require auth gate (API_AUTH_TOKEN or m2_gestor cookie).
Aluno paths remain public after QR.
"""
from __future__ import annotations

import os
import secrets
from typing import Optional, Set
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["m2-proxy"])

# Paths that must reach M2 (static assets required by gestor/aluno UIs).
_PROXY_PREFIXES = (
    "/gestor",
    "/gestor-static",
    "/a/",
    "/e/",
    "/aluno-static",
    "/api/gestor",
    "/api/aluno",
)

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

_GESTOR_COOKIE = "m2_gestor_gate"
_GESTOR_COOKIE_MAX_AGE = 8 * 3600


def m2_upstream() -> str:
    settings = get_settings()
    return (getattr(settings, "m2_upstream_url", None) or "http://127.0.0.1:8766").rstrip("/")


def is_m2_proxy_path(path: str) -> bool:
    if path == "/m2/healthz":
        return True
    for p in _PROXY_PREFIXES:
        if p.endswith("/"):
            if path.startswith(p):
                return True
        elif path == p or path.startswith(p + "/"):
            return True
    return False


def _is_gestor_protected(path: str) -> bool:
    return (
        path == "/gestor"
        or path.startswith("/gestor/")
        or path.startswith("/gestor-static")
        or path.startswith("/api/gestor")
    )


async def require_gestor_gate(request: Request) -> None:
    """Block unauthenticated gestor access.

    Accepts (in order): m2_gestor_gate cookie, API_AUTH_TOKEN, M2_GESTOR_OPEN=1.
    Aluno paths are not protected by this dependency.
    """
    if not _is_gestor_protected(request.url.path):
        return
    settings = get_settings()
    cookie = request.cookies.get(_GESTOR_COOKIE)
    expected = (getattr(settings, "m2_gestor_gate_secret", None) or "").strip()
    ephemeral = getattr(settings, "_m2_gate_ephemeral", None)
    if cookie:
        if expected and secrets.compare_digest(cookie, expected):
            return
        if ephemeral and secrets.compare_digest(cookie, str(ephemeral)):
            return

    expected_api = (settings.api_auth_token or "").strip()
    if expected_api:
        from app.auth import _extract_token

        tok = _extract_token(
            request,
            request.headers.get("x-api-token"),
            request.headers.get("authorization"),
        )
        if tok == expected_api:
            return
        raise HTTPException(status_code=401, detail="Unauthorized — provide X-API-Token or open via Dashboard")

    if getattr(settings, "m2_gestor_open", False):
        env_name = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
        if env_name not in ("prod", "production"):
            return

    if expected:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized — open Cadastro facial from Dashboard",
        )
    # Lab: no gate secret / API token → allow (document in runbook)
    return


def _filter_request_headers(request: Request) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in request.headers.items():
        if k.lower() in _HOP_BY_HOP:
            continue
        out[k] = v
    # Preserve client IP for M2 claim rate-limit
    client = request.client.host if request.client else "0.0.0.0"
    out["X-Forwarded-For"] = request.headers.get("x-forwarded-for", client)
    out["X-Forwarded-Proto"] = request.headers.get("x-forwarded-proto", request.url.scheme)
    out["X-Forwarded-Host"] = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    return out


async def _proxy(request: Request, upstream_path: str) -> Response:
    upstream = m2_upstream()
    url = urljoin(upstream + "/", upstream_path.lstrip("/"))
    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body()
    headers = _filter_request_headers(request)

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            upstream_resp = await client.request(
                request.method,
                url,
                content=body if body else None,
                headers=headers,
            )
    except httpx.ConnectError:
        logger.warning("m2_proxy_upstream_down", upstream=upstream, path=upstream_path)
        raise HTTPException(
            status_code=503,
            detail="Cadastro facial temporariamente indisponível (M2 offline)",
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="M2 timeout")

    resp_headers = {
        k: v
        for k, v in upstream_resp.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "content-encoding"
    }
    # Avoid Cloudflare/browser stale M2 UI (schools dropdown empty with old app.js).
    path_l = (upstream_path or "").lower()
    if path_l.startswith("/gestor") or path_l.startswith("/gestor-static"):
        resp_headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        resp_headers.pop("ETag", None)
        resp_headers.pop("etag", None)

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


@router.api_route("/gestor", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@router.api_route("/gestor/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_gestor(request: Request, path: str = ""):
    await require_gestor_gate(request)
    if request.url.path.rstrip("/") == "/gestor":
        suffix = "/gestor/" if request.url.path.endswith("/") else "/gestor"
    else:
        suffix = f"/gestor/{path}" if path else "/gestor"
    return await _proxy(request, suffix)


@router.api_route(
    "/gestor-static/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def proxy_gestor_static(request: Request, path: str):
    await require_gestor_gate(request)
    return await _proxy(request, f"/gestor-static/{path}")


@router.api_route("/a/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_aluno_page(request: Request, path: str):
    return await _proxy(request, f"/a/{path}")


@router.api_route("/e/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_aluno_invite(request: Request, path: str):
    """Individual enrollment invite QR path (opaque token only)."""
    return await _proxy(request, f"/e/{path}")


@router.api_route(
    "/aluno-static/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def proxy_aluno_static(request: Request, path: str):
    return await _proxy(request, f"/aluno-static/{path}")


@router.api_route(
    "/api/gestor/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_api_gestor(request: Request, path: str):
    await require_gestor_gate(request)
    return await _proxy(request, f"/api/gestor/{path}")


@router.api_route(
    "/api/aluno/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_api_aluno(request: Request, path: str):
    return await _proxy(request, f"/api/aluno/{path}")


@router.get("/m2/healthz")
async def m2_healthz(request: Request):
    """Independent M2 health — Edge stays up even if this returns 503."""
    try:
        return await _proxy(request, "/healthz")
    except HTTPException as exc:
        return Response(
            content=f'{{"ok":false,"service":"m2-enrollment","error":"{exc.detail}"}}',
            status_code=503,
            media_type="application/json",
        )


@router.post("/dashboard/api/m2-gestor-gate")
async def issue_gestor_gate(request: Request):
    """Issue HttpOnly cookie after Dashboard auth so iframe /gestor works same-origin.

    Body: { "access_token": "<supabase jwt>", "school_id": "<optional uuid>" }.
    When Supabase is configured, requires JWT of root / admin_rede / gestor / coordenador.
    API_AUTH_TOKEN remains break-glass for ops.
    Production: M2_GESTOR_OPEN is ignored (fail-closed).
    """
    settings = get_settings()
    secret = (getattr(settings, "m2_gestor_gate_secret", None) or "").strip()
    if not secret:
        secret = (settings.device_token or settings.api_auth_token or "").strip()
        if not secret:
            if not getattr(settings, "_m2_gate_ephemeral", None):
                settings._m2_gate_ephemeral = secrets.token_urlsafe(32)  # type: ignore[attr-defined]
            secret = settings._m2_gate_ephemeral  # type: ignore[attr-defined]
        settings.m2_gestor_gate_secret = secret  # type: ignore[attr-defined]

    authorized = False
    auth_mode = "none"

    expected_api = (settings.api_auth_token or "").strip()
    if expected_api:
        from app.auth import _extract_token

        tok = _extract_token(
            request,
            request.headers.get("x-api-token"),
            request.headers.get("authorization"),
        )
        if tok == expected_api:
            authorized = True
            auth_mode = "api_token"

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    access_token = (body.get("access_token") or "").strip()
    school_id = (body.get("school_id") or "").strip()
    supabase_url = (settings.supabase_url or "").strip()
    anon_key = (settings.supabase_anon_key or "").strip()

    if not authorized and access_token and supabase_url and anon_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                user_r = await client.get(
                    f"{supabase_url.rstrip('/')}/auth/v1/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "apikey": anon_key,
                    },
                )
                if user_r.status_code != 200:
                    raise HTTPException(401, "Unauthorized")
                user = user_r.json() or {}
                uid = (user.get("id") or "").strip()
                if not uid:
                    raise HTTPException(401, "Unauthorized")

                # Role check via PostgREST with caller's JWT (RLS applies).
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "apikey": anon_key,
                }
                prof_r = await client.get(
                    f"{supabase_url.rstrip('/')}/rest/v1/profiles"
                    f"?id=eq.{uid}&select=is_platform_admin,status",
                    headers=headers,
                )
                prof_rows = prof_r.json() if prof_r.status_code == 200 else []
                prof = prof_rows[0] if isinstance(prof_rows, list) and prof_rows else {}
                if (prof.get("status") or "active") == "disabled":
                    raise HTTPException(403, "forbidden_disabled")

                if prof.get("is_platform_admin") is True:
                    authorized = True
                    auth_mode = "root"
                else:
                    org_r = await client.get(
                        f"{supabase_url.rstrip('/')}/rest/v1/organization_memberships"
                        f"?profile_id=eq.{uid}&select=role,organization_id",
                        headers=headers,
                    )
                    org_rows = org_r.json() if org_r.status_code == 200 else []
                    if any(
                        isinstance(r, dict) and r.get("role") == "admin_rede"
                        for r in (org_rows or [])
                    ):
                        authorized = True
                        auth_mode = "admin_rede"
                    else:
                        mem_q = (
                            f"{supabase_url.rstrip('/')}/rest/v1/memberships"
                            f"?profile_id=eq.{uid}&select=role,school_id"
                        )
                        if school_id:
                            mem_q += f"&school_id=eq.{school_id}"
                        mem_r = await client.get(mem_q, headers=headers)
                        mem_rows = mem_r.json() if mem_r.status_code == 200 else []
                        allowed_roles = {"gestor", "coordenador"}
                        for r in mem_rows or []:
                            if isinstance(r, dict) and r.get("role") in allowed_roles:
                                authorized = True
                                auth_mode = str(r.get("role"))
                                break

                if not authorized:
                    raise HTTPException(403, "forbidden_role")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("m2_gestor_gate_jwt_check_failed", error=str(exc))
            raise HTTPException(401, "Unauthorized") from exc

    # Lab open only when explicitly enabled AND Supabase not in fail-closed prod mode
    env_name = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    prod_like = env_name in ("prod", "production")
    if not authorized:
        if (
            getattr(settings, "m2_gestor_open", False)
            and not prod_like
            and not supabase_url
        ):
            authorized = True
            auth_mode = "lab_open"
        elif not expected_api and not supabase_url:
            # Pure local smoke without cloud
            authorized = True
            auth_mode = "lab_no_cloud"
        else:
            raise HTTPException(401, "Unauthorized")

    logger.info("m2_gestor_gate_ok", mode=auth_mode, school_id=school_id or None)
    resp = Response(content='{"ok":true,"mode":"%s"}' % auth_mode, media_type="application/json")
    # Named Tunnel terminates TLS at Cloudflare; Edge often sees http:// — honor X-Forwarded-Proto.
    fwd = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    cookie_secure = request.url.scheme == "https" or fwd == "https"
    resp.set_cookie(
        key=_GESTOR_COOKIE,
        value=secret,
        max_age=_GESTOR_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=cookie_secure,
        path="/",
    )
    return resp
