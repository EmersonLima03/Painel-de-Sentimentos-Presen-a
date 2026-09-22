#!/usr/bin/env python3
"""Servidor Enrollment Escalavel A — F1 gestor + F2 aluno (sem camera).

Somente POC em modulo2_poc/. Nao toca pipeline facial nem producao.

  cd experiments/smoke_e2e_sentimentos/modulo2_poc
  python scripts/enrollment_gestor_server.py --port 8766

  Gestor: http://127.0.0.1:8766/gestor/
  Aluno:  http://127.0.0.1:8766/a/<campaign_token>
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

_SCRIPTS = Path(__file__).resolve().parent
ROOT = _SCRIPTS.parent
UI_GESTOR = ROOT / "ui_gestor"
UI_ALUNO = ROOT / "ui_aluno"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from enrollment_store import (  # noqa: E402
    CLAIM_GENERIC_ERROR,
    DEFAULT_DB_PATH,
    ClaimFailure,
    ClaimSuccess,
    EnrollmentStore,
)
from enrollment_tokens import qr_path_for_campaign_token  # noqa: E402
from enrollment_pipeline import (  # noqa: E402
    CAPTURE_STORE,
    ack_glasses,
    decode_jpeg_bytes,
    force_advance_for_tests,
    process_frame_bgr,
)

import os  # noqa: E402

try:
    import enrollment_ops_sync as _ops_sync_mod  # noqa: E402
except ImportError:  # pragma: no cover
    _ops_sync_mod = None  # type: ignore


def _load_dotenv_files() -> None:
    """Load backend .env without printing values. Never used by frontend."""
    candidates = [
        ROOT / ".env",
        ROOT.parents[2] / ".env",  # _integrate_m2_ux or repo root depending on layout
        ROOT.parents[2].parent / "Presenca" / ".env",
        Path.cwd() / ".env",
    ]
    for path in candidates:
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            continue


_load_dotenv_files()

TEST_HOOKS = os.environ.get("M2_POC_TEST_HOOKS", "").strip() in ("1", "true", "yes")
# URL pública HTTPS (ex.: https://enrollment.exemplo.com/) — obrigatória atrás de proxy/Cloudflare.
# Sem este valor, share_link/QR usam request.base_url (ok em lab local).
PUBLIC_BASE_URL = os.environ.get("M2_PUBLIC_BASE_URL", "").strip().rstrip("/")

try:
    import qrcode
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, Response
    from fastapi.staticfiles import StaticFiles
    import uvicorn
except ImportError as e:
    print(json.dumps({"error": "fastapi/uvicorn/qrcode necessarios", "detail": str(e)}))
    sys.exit(1)

try:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
except ImportError:  # pragma: no cover
    try:
        from starlette.middleware.proxy_headers import ProxyHeadersMiddleware  # type: ignore
    except ImportError:
        ProxyHeadersMiddleware = None  # type: ignore


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "0.0.0.0"


def _public_base(request: Request) -> str:
    """Base URL para QR/share_link. Prefere M2_PUBLIC_BASE_URL em produção."""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL + "/"
    return str(request.base_url)


def build_app(store: EnrollmentStore) -> FastAPI:
    app = FastAPI(title="M2 Enrollment Escalavel", docs_url=None, redoc_url=None)
    # Confia em X-Forwarded-* quando atrás de Cloudflare/nginx (1 hop).
    if ProxyHeadersMiddleware is not None:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    app.state.store = store

    if UI_GESTOR.is_dir():
        app.mount("/gestor-static", StaticFiles(directory=str(UI_GESTOR)), name="gestor_static")
    if UI_ALUNO.is_dir():
        app.mount("/aluno-static", StaticFiles(directory=str(UI_ALUNO)), name="aluno_static")

    @app.get("/")
    def root() -> Response:
        return Response(status_code=307, headers={"Location": "/gestor/"})

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        """Healthcheck de produção — sem dados sensíveis."""
        roster_mode = "unknown"
        try:
            roster_mode = store.roster_source_mode()
        except Exception:
            roster_mode = "error"
        ops_ok = False
        if _ops_sync_mod is not None:
            ops_ok = bool(_ops_sync_mod.configured())
        yunet_ok = False
        try:
            from poc_common import YUNET

            yunet_ok = bool(YUNET.exists())
        except Exception:
            yunet_ok = False
        return {
            "ok": True,
            "service": "m2-enrollment",
            "camera": True,
            "test_hooks": TEST_HOOKS,
            "public_base_configured": bool(PUBLIC_BASE_URL),
            "roster_source": roster_mode,
            "ops_sync_configured": ops_ok,
            "yunet_model_present": yunet_ok,
        }

    # ------------------------------------------------------------------ gestor
    @app.get("/gestor/")
    @app.get("/gestor")
    def gestor_page() -> FileResponse:
        index = UI_GESTOR / "index.html"
        if not index.is_file():
            raise HTTPException(500, "ui_gestor/index.html ausente")
        return FileResponse(index, media_type="text/html; charset=utf-8")

    @app.get("/api/gestor/schools")
    def api_schools() -> dict[str, Any]:
        schools = store.list_schools()
        safe = []
        for s in schools:
            safe.append(
                {
                    "id": s["id"],
                    "name": s["name"],
                    "class_groups": [
                        {
                            "id": cg["id"],
                            "label": cg["label"],
                            "shift": cg.get("shift"),
                            "student_count": len(cg.get("students", [])),
                            "students": [
                                {
                                    "display_name": st["display_name"],
                                    "student_id": st.get("student_id"),
                                    "edge_student_key": st.get("edge_student_key")
                                    or st.get("fixture_key"),
                                }
                                for st in cg.get("students", [])
                            ],
                        }
                        for cg in s["class_groups"]
                    ],
                }
            )
        return {
            "schools": safe,
            "roster_source": store.roster_source_mode(),
        }

    @app.get("/api/gestor/class-facial-status")
    def api_class_facial_status(school_id: str, class_group_id: str) -> dict[str, Any]:
        if not school_id or not class_group_id:
            raise HTTPException(400, "school_id e class_group_id obrigatorios")
        try:
            return store.list_class_facial_status(school_id, class_group_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/gestor/students/enroll")
    def api_start_student_enroll(body: dict[str, Any], request: Request) -> dict[str, Any]:
        school_id = body.get("school_id")
        class_group_id = body.get("class_group_id")
        student_id = body.get("student_id")
        replace = bool(body.get("replace") or body.get("recadastrar"))
        if not school_id or not class_group_id or not student_id:
            raise HTTPException(400, "school_id, class_group_id e student_id obrigatorios")
        try:
            created = store.start_student_enrollment(
                school_id=str(school_id),
                class_group_id=str(class_group_id),
                student_id=str(student_id),
                replace=replace,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

        base = _public_base(request)
        link = urljoin(base, created["qr_path"].lstrip("/"))
        return {
            "ok": True,
            **created,
            "share_link": link,
            "qr_image_url": f"/api/gestor/students/enroll/qr.png?token={created['invite_token']}",
            # Never echo secrets beyond the invite token needed for QR
        }

    @app.get("/api/gestor/students/enroll/qr.png")
    def api_student_enroll_qr(token: str, request: Request) -> Response:
        if not token or len(token) < 16:
            raise HTTPException(400, "token invalido")
        base = _public_base(request)
        link = urljoin(base, f"/e/{token}")
        lowered = link.lower()
        for forbidden in ("embedding", "claim_code", "hmac", "student_id="):
            if forbidden in lowered:
                raise HTTPException(500, "qr payload inseguro")
        img = qrcode.make(link, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    @app.post("/api/gestor/students/revoke")
    def api_revoke_student(body: dict[str, Any]) -> dict[str, Any]:
        student_id = body.get("student_id")
        campaign_id = body.get("campaign_id")
        if not student_id:
            raise HTTPException(400, "student_id obrigatorio")
        return store.revoke_student_invite(
            student_id=str(student_id),
            campaign_id=str(campaign_id) if campaign_id else None,
        )

    @app.post("/api/gestor/campaigns")
    def api_create_campaign(body: dict[str, Any], request: Request) -> dict[str, Any]:
        """Compat: campanha em lote (lab/testes). UX de produto usa /students/enroll."""
        school_id = body.get("school_id")
        class_group_id = body.get("class_group_id")
        if not school_id or not class_group_id:
            raise HTTPException(400, "school_id e class_group_id obrigatorios")
        try:
            created = store.create_campaign(
                school_id=school_id, class_group_id=class_group_id
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        base = _public_base(request)
        link = urljoin(base, created["qr_path"].lstrip("/"))
        return {
            "ok": True,
            "campaign_id": created["campaign_id"],
            "campaign_token": created["campaign_token"],
            "qr_path": created["qr_path"],
            "share_link": link,
            "school_name": created["school_name"],
            "class_label": created["class_label"],
            "status": created["status"],
            "expires_at": created["expires_at"],
            "roster_count": created["roster_count"],
            "claim_sheet": created["claim_sheet"],
            "roster_source": created.get("roster_source"),
        }

    @app.get("/api/gestor/campaigns/{campaign_id}")
    def api_get_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
        camp = store.get_campaign(campaign_id)
        if camp is None:
            raise HTTPException(404, "campanha nao encontrada")
        base = _public_base(request)
        link = urljoin(base, camp["qr_path"].lstrip("/"))
        return {
            "ok": True,
            **camp,
            "share_link": link,
            "qr_image_url": f"/api/gestor/campaigns/{campaign_id}/qr.png",
        }

    @app.get("/api/gestor/campaigns/{campaign_id}/progress")
    def api_progress(campaign_id: str) -> dict[str, Any]:
        camp = store.get_campaign(campaign_id)
        if camp is None:
            raise HTTPException(404, "campanha nao encontrada")
        pct = 0.0 if camp["total"] == 0 else (100.0 * camp["completed"] / camp["total"])
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "status": camp["status"],
            "total": camp["total"],
            "completed": camp["completed"],
            "percent": round(pct, 1),
            "items": camp["items"],
            "class_label": camp["class_label"],
            "school_name": camp["school_name"],
        }

    @app.post("/api/gestor/campaigns/{campaign_id}/revoke")
    def api_revoke(campaign_id: str) -> dict[str, Any]:
        camp = store.get_campaign(campaign_id)
        if camp is None:
            raise HTTPException(404, "campanha nao encontrada")
        result = store.revoke_campaign(campaign_id)
        return {"ok": True, **result}

    @app.get("/api/gestor/campaigns/{campaign_id}/qr.png")
    def api_qr_png(campaign_id: str, request: Request) -> Response:
        camp = store.get_campaign(campaign_id)
        if camp is None:
            raise HTTPException(404, "campanha nao encontrada")
        base = _public_base(request)
        link = urljoin(base, camp["qr_path"].lstrip("/"))
        path = qr_path_for_campaign_token(camp["campaign_token"])
        if path not in link or camp["campaign_token"] not in link:
            raise HTTPException(500, "qr link invalido")
        lowered = link.lower()
        for forbidden in ("embedding", "claim_code", "session_token", "hmac"):
            if forbidden in lowered:
                raise HTTPException(500, "qr payload inseguro")

        img = qrcode.make(link, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    # ------------------------------------------------------------------- aluno
    @app.get("/a/{campaign_token}", response_model=None)
    def aluno_page(campaign_token: str) -> FileResponse:
        index = UI_ALUNO / "index.html"
        if not index.is_file():
            raise HTTPException(500, "ui_aluno/index.html ausente")
        _ = campaign_token
        return FileResponse(index, media_type="text/html; charset=utf-8")

    @app.get("/e/{invite_token}", response_model=None)
    def aluno_invite_page(invite_token: str) -> FileResponse:
        """Individual enrollment invite — opaque token only in path."""
        index = UI_ALUNO / "index.html"
        if not index.is_file():
            raise HTTPException(500, "ui_aluno/index.html ausente")
        _ = invite_token
        return FileResponse(index, media_type="text/html; charset=utf-8")

    @app.get("/api/aluno/invite/{invite_token}")
    def api_aluno_invite(invite_token: str):
        from fastapi.responses import JSONResponse

        try:
            info = store.resolve_invite_token(str(invite_token))
        except PermissionError:
            return JSONResponse(
                {"ok": False, "error": "convite invalido ou expirado"},
                status_code=400,
            )
        return {
            "ok": True,
            "display_name": info["display_name"],
            "class_label": info["class_label"],
            "school_name": info["school_name"],
            "session_token": info["session_token"],
            "session_expires_at": info["expires_at"],
            "roster_status": info["roster_status"],
            "message": f"Confirme se você é {info['display_name']}",
            "mode": "invite",
        }

    @app.get("/api/aluno/campaign/{campaign_token}")
    def api_aluno_campaign(campaign_token: str) -> dict[str, Any]:
        public = store.get_campaign_public_by_token(campaign_token)
        if public is None:
            return {"ok": False, "error": "campanha nao encontrada"}
        return {
            "ok": True,
            "school_name": public["school_name"],
            "class_label": public["class_label"],
            "status": public["status"],
            "expires_at": public["expires_at"],
            # Explicitly no roster / names / claim codes
        }

    @app.post("/api/aluno/claim")
    def api_aluno_claim(body: dict[str, Any], request: Request):
        from fastapi.responses import JSONResponse

        campaign_token = body.get("campaign_token")
        claim_code = body.get("claim_code")
        if not campaign_token:
            return JSONResponse(
                {"ok": False, "error": CLAIM_GENERIC_ERROR},
                status_code=400,
            )
        result = store.claim(
            campaign_token=str(campaign_token),
            claim_code=claim_code,
            client_ip=_client_ip(request),
        )
        if isinstance(result, ClaimFailure):
            return JSONResponse(
                {"ok": False, "error": result.error},
                status_code=result.http_status,
            )
        assert isinstance(result, ClaimSuccess)
        ui = result.ui_safe()
        return {
            "ok": True,
            "display_name": ui["display_name"],
            "class_label": ui["class_label"],
            "school_name": ui["school_name"],
            "session_token": ui["session_token"],
            "session_expires_at": ui["session_expires_at"],
            "roster_status": ui["roster_status"],
            "message": ui["message"],
        }

    @app.post("/api/aluno/session/decline")
    def api_aluno_decline(body: dict[str, Any]):
        from fastapi.responses import JSONResponse

        token = body.get("session_token")
        if not token:
            return JSONResponse(
                {"ok": False, "error": "session_token obrigatorio"},
                status_code=400,
            )
        try:
            store.decline_identity(str(token))
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        return {"ok": True, "roster_status": "pending"}

    @app.post("/api/aluno/session/start")
    def api_aluno_start(body: dict[str, Any]):
        """Ativa enrollment (claimed → in_progress) e cria CaptureSession F3."""
        from fastapi.responses import JSONResponse

        token = body.get("session_token")
        if not token:
            return JSONResponse(
                {"ok": False, "error": "session_token obrigatorio"},
                status_code=400,
            )
        try:
            info = store.mark_in_progress(str(token))
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        camp = store.get_campaign(info["campaign_id"])
        class_label = camp["class_label"] if camp else ""
        # Recreate capture session for this enrollment session_id
        CAPTURE_STORE.create(
            session_id=info["session_id"],
            campaign_id=info["campaign_id"],
            roster_student_id=info["roster_student_id"],
            display_name=info["display_name"],
            class_label=class_label or "",
        )
        return {
            "ok": True,
            "display_name": info["display_name"],
            "class_label": class_label,
            "roster_status": info["roster_status"],
            "session_status": info["session_status"],
            "ready_for_facial": True,
            "camera_enabled": True,
            "capture": CAPTURE_STORE.get(info["session_id"]).ui_safe(),
        }

    @app.get("/api/aluno/session/state")
    def api_aluno_state(session_token: str, require_roster_id: str | None = None):
        from fastapi.responses import JSONResponse

        try:
            info = store.validate_session_token(
                session_token, require_roster_id=require_roster_id
            )
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        cs = CAPTURE_STORE.get(info["session_id"])
        out = {"ok": True, **info, "camera_enabled": True}
        if cs is not None:
            out["capture"] = cs.ui_safe()
        return out

    @app.post("/api/aluno/session/frame")
    async def api_aluno_frame(request: Request):
        """Recebe JPEG (multipart file 'frame' ou raw body) + session_token."""
        from fastapi.responses import JSONResponse

        content_type = (request.headers.get("content-type") or "").lower()
        session_token = None
        jpeg: bytes | None = None

        if "multipart/form-data" in content_type:
            form = await request.form()
            session_token = form.get("session_token")
            upload = form.get("frame")
            if upload is not None and hasattr(upload, "read"):
                jpeg = await upload.read()
        else:
            # JSON with base64 optional, or header token + raw jpeg
            session_token = request.headers.get("x-session-token")
            jpeg = await request.body()

        if not session_token:
            return JSONResponse(
                {"ok": False, "error": "session_token obrigatorio"}, status_code=400
            )
        try:
            info = store.validate_session_token(str(session_token))
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)

        camp = store.get_campaign(info["campaign_id"])
        if camp is None or camp["status"] != "active":
            return JSONResponse(
                {"ok": False, "error": "campanha nao ativa"}, status_code=403
            )

        cs = CAPTURE_STORE.get(info["session_id"])
        if cs is None:
            return JSONResponse(
                {"ok": False, "error": "capture session ausente — chame /start"},
                status_code=400,
            )
        if cs.roster_student_id != info["roster_student_id"]:
            return JSONResponse(
                {"ok": False, "error": "sessao nao pertence a este aluno"},
                status_code=403,
            )
        if not jpeg:
            return JSONResponse({"ok": False, "error": "frame ausente"}, status_code=400)
        try:
            frame = decode_jpeg_bytes(jpeg)
        except ValueError:
            return JSONResponse({"ok": False, "error": "jpeg invalido"}, status_code=400)

        ui = process_frame_bgr(cs, frame)
        if ui.get("completed"):
            try:
                store.complete_enrollment(str(session_token))
            except PermissionError:
                pass
        return {"ok": True, "capture": ui}

    @app.post("/api/aluno/session/glasses")
    def api_aluno_glasses(body: dict[str, Any]):
        from fastapi.responses import JSONResponse

        token = body.get("session_token")
        if token is None or "uses_glasses" not in body:
            return JSONResponse(
                {"ok": False, "error": "session_token e uses_glasses obrigatorios"},
                status_code=400,
            )
        try:
            info = store.validate_session_token(str(token))
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        cs = CAPTURE_STORE.get(info["session_id"])
        if cs is None:
            return JSONResponse({"ok": False, "error": "capture session ausente"}, status_code=400)
        ui = ack_glasses(cs, bool(body["uses_glasses"]))
        if ui.get("completed"):
            try:
                store.complete_enrollment(str(token))
            except PermissionError:
                pass
        return {"ok": True, "capture": ui}

    @app.post("/api/aluno/session/complete")
    def api_aluno_complete(body: dict[str, Any]):
        """Conclui somente se CaptureSession completed (ou hook legado de teste)."""
        from fastapi.responses import JSONResponse

        token = body.get("session_token")
        if not token:
            return JSONResponse(
                {"ok": False, "error": "session_token obrigatorio"},
                status_code=400,
            )
        try:
            info = store.validate_session_token(str(token))
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        cs = CAPTURE_STORE.get(info["session_id"])
        if cs is not None and not cs.completed and not TEST_HOOKS:
            return JSONResponse(
                {"ok": False, "error": "enrollment facial incompleto"},
                status_code=400,
            )
        try:
            done = store.complete_enrollment(str(token))
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        return {"ok": True, **done}

    @app.post("/api/aluno/session/test/force-step")
    def api_test_force_step(body: dict[str, Any]):
        """Avança fase com embedding sintético. Só com M2_POC_TEST_HOOKS=1."""
        from fastapi.responses import JSONResponse

        if not TEST_HOOKS:
            return JSONResponse({"ok": False, "error": "hooks desabilitados"}, status_code=404)
        token = body.get("session_token")
        step = body.get("step")
        if not token or not step:
            return JSONResponse({"ok": False, "error": "session_token e step obrigatorios"}, status_code=400)
        try:
            info = store.validate_session_token(str(token))
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        cs = CAPTURE_STORE.get(info["session_id"])
        if cs is None:
            return JSONResponse({"ok": False, "error": "capture session ausente"}, status_code=400)
        ui = force_advance_for_tests(cs, str(step))
        if ui.get("completed"):
            store.complete_enrollment(str(token))
        return {"ok": True, "capture": ui}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="M2 POC Enrollment Escalavel F1+F2+F3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    store = EnrollmentStore(args.db)
    app = build_app(store)
    print(
        json.dumps(
            {
                "server": "enrollment_escalavel_f1_f2_f3",
                "gestor": f"http://{args.host}:{args.port}/gestor/",
                "aluno_path": f"http://{args.host}:{args.port}/a/<campaign_token>",
                "db": str(args.db),
                "camera": True,
                "test_hooks": TEST_HOOKS,
            },
            ensure_ascii=False,
        )
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
