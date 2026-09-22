"""Promote M2 TEMP gallery templates into Edge product face_embeddings.

Official bridge (atomic product contract):
  gallery_temp/*.npy
    → validate templates
    → face_embeddings (SQLite Edge, student_id = edge_student_key)
    → confirm persistence
    → POST /internal/matcher/reload (loopback)
    → confirm reload
    → only then caller may set status=enrolled

Uses edge_student_key (e.g. p01) as matcher student_id — never UUID.
Never writes biometrics to Supabase.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import numpy as np

# Edge app package lives at repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger("m2.enrollment_promote")


def _ensure_edge_sqlite_path() -> Path:
    """Pin SQLITE_PATH to repo data/ so M2 (cwd=modulo2_poc) shares Edge DB.

    Relative ./data/dulino_edge.db from M2 working directory points at an empty
    file without students/face_embeddings — promote then fails and gestor stays
    in_progress while the phone shows Cadastro concluido.
    """
    db = (_REPO_ROOT / "data" / "dulino_edge.db").resolve()
    db.parent.mkdir(parents=True, exist_ok=True)
    cur = (os.environ.get("SQLITE_PATH") or "").strip()
    need_pin = False
    if not cur:
        need_pin = True
    else:
        try:
            cur_path = Path(cur)
            # Relative or missing → wrong cwd risk
            if not cur_path.is_absolute() or not cur_path.is_file():
                need_pin = True
        except Exception:
            need_pin = True
    if need_pin:
        os.environ["SQLITE_PATH"] = str(db)
    try:
        from app.db.init_db import reset_db_singleton

        reset_db_singleton()
    except Exception:
        pass
    try:
        from app.config import get_settings

        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    return Path(os.environ["SQLITE_PATH"]).resolve()

_STEPS = ("front", "lateral_right", "lateral_left", "validate", "glasses_on", "glasses")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def looks_like_uuid(value: str) -> bool:
    raw = (value or "").strip()
    if not raw or not _UUID_RE.match(raw):
        return False
    try:
        UUID(raw)
        return True
    except ValueError:
        return False


def derive_edge_student_key(student_id: str) -> str:
    """Stable matcher key derived from students.id (never the raw UUID).

    Format: e_<uuid-hex-without-hyphens>
    - unique 1:1 with students.id
    - immutable once chosen for that id
    - does not look like a UUID (prefix e_) so FAISS/matcher contract holds
    """
    sid = (student_id or "").strip().lower()
    if not sid:
        raise ValueError("student_id obrigatorio para derivar edge_student_key")
    if not looks_like_uuid(sid):
        # Already a non-UUID technical id — do not invent another form.
        # Callers should only pass official students.id UUIDs here.
        raise ValueError(
            "derive_edge_student_key espera students.id (UUID); "
            f"recebido: {sid[:48]}"
        )
    return "e_" + sid.replace("-", "")


def require_edge_student_key(student: dict[str, Any]) -> str:
    """Official matcher key. Never silently use raw students.id UUID as key.

    Resolution order:
      1) edge_student_key explicito (nao-UUID)
      2) fixture_key de lab (nao-UUID)
      3) derivar de student_id / id (UUID) via derive_edge_student_key
    """
    explicit = (student.get("edge_student_key") or "").strip()
    fixture = (student.get("fixture_key") or "").strip()

    if explicit:
        if looks_like_uuid(explicit):
            raise ValueError(
                "edge_student_key invalido: UUID nao e permitido como chave do matcher. "
                "Configure students.edge_student_key (ex.: p01 ou e_<hex>) no Supabase A."
            )
        return explicit

    # Lab fixtures: fixture_key like aluno_dulin is acceptable if not a UUID.
    if fixture and not looks_like_uuid(fixture):
        return fixture

    sid = (student.get("student_id") or student.get("id") or "").strip()
    if sid and looks_like_uuid(sid):
        return derive_edge_student_key(sid)

    raise ValueError(
        "edge_student_key obrigatorio — aluno sem id UUID para derivar chave. "
        "Cadastro recusado."
    )


def gallery_dir(campaign_id: str, roster_student_id: str) -> Path:
    from poc_common import GALLERY

    return (
        GALLERY
        / "enrollment_campaigns"
        / str(campaign_id)
        / str(roster_student_id)
    )


def load_templates(campaign_id: str, roster_student_id: str) -> list[tuple[str, np.ndarray]]:
    g = gallery_dir(campaign_id, roster_student_id)
    out: list[tuple[str, np.ndarray]] = []
    if not g.is_dir():
        return out
    for step in _STEPS:
        p = g / f"{step}.npy"
        if not p.is_file():
            continue
        arr = np.load(str(p))
        arr = np.asarray(arr, dtype=np.float32).reshape(-1)
        n = float(np.linalg.norm(arr))
        if n > 0:
            arr = arr / n
        out.append((step, arr))
    return out


def update_enroll_meta_flags(
    campaign_id: str,
    roster_student_id: str,
    *,
    product_db_written: bool,
    reload_matcher_called: bool,
) -> None:
    import json

    meta_path = gallery_dir(campaign_id, roster_student_id) / "enroll_meta.json"
    if not meta_path.is_file():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return
    meta["product_db_written"] = bool(product_db_written)
    meta["reload_matcher_called"] = bool(reload_matcher_called)
    for s in meta.get("samples") or []:
        if isinstance(s, dict):
            s["product_db_written"] = bool(product_db_written)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def write_face_embeddings(
    *,
    edge_student_key: str,
    display_name: str,
    templates: list[tuple[str, np.ndarray]],
    replace: bool = True,
) -> dict[str, Any]:
    """Persist templates into Edge SQLite face_embeddings. Returns summary."""
    if not edge_student_key or looks_like_uuid(edge_student_key):
        return {"ok": False, "error": "invalid_edge_student_key", "n_written": 0}
    if not templates:
        return {"ok": False, "error": "missing_templates", "n_written": 0}

    from app.config import get_settings
    from app.db.init_db import get_session, init_database
    from app.db.repo import FaceEmbeddingRepository, StudentRepository

    _ensure_edge_sqlite_path()
    settings = get_settings()
    init_database()
    session = get_session()
    student_repo = StudentRepository(session)
    emb_repo = FaceEmbeddingRepository(session)

    student_repo.create_student(
        student_id=str(edge_student_key),
        school_id=settings.school_id,
        room_id=None,
        full_name=display_name or str(edge_student_key),
        is_active=True,
    )
    if replace:
        emb_repo.delete_embeddings_for_student(
            str(edge_student_key),
            device_id=settings.device_id,
            school_id=settings.school_id,
        )

    written = 0
    for step, vec in templates:
        emb_repo.create_embedding(
            student_id=str(edge_student_key),
            device_id=settings.device_id,
            school_id=settings.school_id,
            embedding_vector=vec,
            room_id=None,
            embedding_dim=int(vec.shape[0]),
            model_name="facenet",
            model_version="m2-enrollment-promote-v1",
            quality_score=None,
        )
        written += 1
        logger.info(
            "m2_promote_embedding_written edge_key=%s step=%s dim=%s",
            edge_student_key,
            step,
            int(vec.shape[0]),
        )

    # Confirm persistence before caller may mark enrolled.
    confirmed = int(
        emb_repo.count_templates_for_student(
            str(edge_student_key),
            device_id=settings.device_id,
            school_id=settings.school_id,
        )
    )
    if confirmed < 1:
        return {
            "ok": False,
            "error": "persist_confirm_failed",
            "n_written": written,
            "n_confirmed": confirmed,
        }

    return {
        "ok": True,
        "edge_student_key": str(edge_student_key),
        "n_written": written,
        "n_confirmed": confirmed,
        "replaced": bool(replace),
    }


def delete_face_embeddings(edge_student_key: str) -> dict[str, Any]:
    """Remove active templates for a revoked identity."""
    if not edge_student_key or looks_like_uuid(edge_student_key):
        return {"ok": False, "error": "invalid_edge_student_key", "n_deleted": 0}
    try:
        from app.config import get_settings
        from app.db.init_db import get_session, init_database
        from app.db.repo import FaceEmbeddingRepository

        _ensure_edge_sqlite_path()
        settings = get_settings()
        init_database()
        session = get_session()
        n = FaceEmbeddingRepository(session).delete_embeddings_for_student(
            str(edge_student_key),
            device_id=settings.device_id,
            school_id=settings.school_id,
        )
        return {"ok": True, "edge_student_key": str(edge_student_key), "n_deleted": int(n)}
    except Exception as exc:  # noqa: BLE001
        logger.error("m2_revoke_delete_FAIL key=%s err=%s", edge_student_key, exc)
        return {"ok": False, "error": str(exc), "n_deleted": 0}


def reload_matcher_via_edge(base_url: Optional[str] = None) -> dict[str, Any]:
    """Ask Edge (loopback) to rebuild FAISS from face_embeddings."""
    import json
    import urllib.request

    base = (
        (base_url or os.environ.get("M2_EDGE_RELOAD_URL") or "http://127.0.0.1:8000")
        .strip()
        .rstrip("/")
    )
    url = f"{base}/internal/matcher/reload"
    try:
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            code = int(getattr(resp, "status", 200) or 200)
            body = resp.read().decode("utf-8", errors="replace")
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}
        ok = code == 200 and bool(payload.get("ok", True))
        logger.info(
            "m2_promote_reload url=%s code=%s ok=%s body=%s",
            url,
            code,
            ok,
            body[:200],
        )
        return {
            "ok": ok,
            "http_status": code,
            "pipelines_reloaded": payload.get("pipelines_reloaded"),
            "body": body[:500],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("m2_promote_reload_fail url=%s err=%s", url, exc)
        return {"ok": False, "error": str(exc)}


def edge_student_has_embeddings(edge_student_key: str) -> bool:
    if not edge_student_key or looks_like_uuid(edge_student_key):
        return False
    try:
        from app.db.init_db import get_session, init_database
        from app.db.repo import FaceEmbeddingRepository

        _ensure_edge_sqlite_path()
        init_database()
        session = get_session()
        n = FaceEmbeddingRepository(session).count_templates_for_student(
            str(edge_student_key)
        )
        return int(n) > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("m2_promote_status_check_fail key=%s err=%s", edge_student_key, exc)
        return False


def promote_completed_enrollment(
    *,
    campaign_id: str,
    roster_student_id: str,
    edge_student_key: str,
    display_name: str,
    replace: bool = True,
    call_reload: bool = True,
) -> dict[str, Any]:
    """Atomic promote. ok=True only after persist confirmed (+ reload if required)."""
    try:
        if not edge_student_key or looks_like_uuid(str(edge_student_key)):
            return {
                "ok": False,
                "error": "missing_or_invalid_edge_student_key",
                "n_written": 0,
                "product_enrolled": False,
            }

        templates = load_templates(campaign_id, roster_student_id)
        if not templates:
            return {
                "ok": False,
                "error": "no_templates",
                "n_written": 0,
                "product_enrolled": False,
            }

        written = write_face_embeddings(
            edge_student_key=edge_student_key,
            display_name=display_name,
            templates=templates,
            replace=replace,
        )
        if not written.get("ok"):
            return {**written, "product_enrolled": False, "reload_matcher_called": False}

        reload_info: dict[str, Any] = {"ok": True, "skipped": True}
        if call_reload:
            reload_info = reload_matcher_via_edge()
            if not reload_info.get("ok"):
                # Persist happened but matcher not updated — NOT enrolled.
                update_enroll_meta_flags(
                    campaign_id,
                    roster_student_id,
                    product_db_written=True,
                    reload_matcher_called=False,
                )
                return {
                    **written,
                    "ok": False,
                    "error": "reload_matcher_failed",
                    "reload": reload_info,
                    "reload_matcher_called": False,
                    "product_enrolled": False,
                    "n_templates_loaded": len(templates),
                }

        update_enroll_meta_flags(
            campaign_id,
            roster_student_id,
            product_db_written=True,
            reload_matcher_called=bool(call_reload),
        )
        return {
            **written,
            "ok": True,
            "reload": reload_info,
            "reload_matcher_called": bool(call_reload),
            "product_enrolled": True,
            "n_templates_loaded": len(templates),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "m2_promote_FAIL campaign=%s roster=%s err=%s",
            campaign_id,
            roster_student_id,
            exc,
        )
        return {
            "ok": False,
            "error": str(exc),
            "n_written": 0,
            "product_enrolled": False,
        }


def revoke_identity_from_matcher(
    *,
    edge_student_key: str,
    call_reload: bool = True,
) -> dict[str, Any]:
    """Remove templates and reload so identity is no longer matchable."""
    deleted = delete_face_embeddings(edge_student_key)
    if not deleted.get("ok"):
        return {**deleted, "revoked_from_matcher": False}
    reload_info: dict[str, Any] = {"ok": True, "skipped": True}
    if call_reload:
        reload_info = reload_matcher_via_edge()
        if not reload_info.get("ok"):
            return {
                **deleted,
                "ok": False,
                "error": "reload_matcher_failed_after_revoke",
                "reload": reload_info,
                "revoked_from_matcher": False,
            }
    still = edge_student_has_embeddings(edge_student_key)
    return {
        **deleted,
        "ok": True,
        "reload": reload_info,
        "revoked_from_matcher": not still,
        "embeddings_remain": still,
    }
