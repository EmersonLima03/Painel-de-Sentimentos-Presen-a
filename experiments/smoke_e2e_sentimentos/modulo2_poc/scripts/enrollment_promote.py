"""Promote M2 TEMP gallery templates into Edge product face_embeddings.

Official bridge:
  gallery_temp/*.npy  →  students + face_embeddings (SQLite Edge)
                      →  optional HTTP reload_matcher on Edge :8000

Uses edge_student_key (e.g. p01) as matcher student_id — never the roster UUID.
Never writes biometrics to Supabase.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

# Edge app package lives at repo root (…/_facial_enroll_prod or Presenca).
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger("m2.enrollment_promote")

_STEPS = ("front", "lateral_right", "lateral_left", "validate", "glasses_on", "glasses")


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
    if not edge_student_key or not templates:
        return {"ok": False, "error": "missing_edge_key_or_templates", "n_written": 0}

    from app.config import get_settings
    from app.db.init_db import get_session
    from app.db.repo import FaceEmbeddingRepository, StudentRepository

    settings = get_settings()
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

    return {
        "ok": True,
        "edge_student_key": str(edge_student_key),
        "n_written": written,
        "replaced": bool(replace),
    }


def reload_matcher_via_edge(base_url: Optional[str] = None) -> bool:
    """Ask Edge (loopback) to rebuild FAISS from face_embeddings."""
    import json
    import urllib.error
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
            body = resp.read().decode("utf-8", errors="replace")
        logger.info("m2_promote_reload_ok url=%s body=%s", url, body[:200])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("m2_promote_reload_fail url=%s err=%s", url, exc)
        return False


def edge_student_has_embeddings(edge_student_key: str) -> bool:
    if not edge_student_key:
        return False
    try:
        from app.db.init_db import get_session
        from app.db.repo import FaceEmbeddingRepository

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
    """Full promote path. Never raises to caller of enrollment complete."""
    try:
        templates = load_templates(campaign_id, roster_student_id)
        if not templates:
            return {"ok": False, "error": "no_templates", "n_written": 0}
        if not edge_student_key:
            return {"ok": False, "error": "missing_edge_student_key", "n_written": 0}

        written = write_face_embeddings(
            edge_student_key=edge_student_key,
            display_name=display_name,
            templates=templates,
            replace=replace,
        )
        reloaded = False
        if written.get("ok") and call_reload:
            reloaded = reload_matcher_via_edge()
        if written.get("ok"):
            update_enroll_meta_flags(
                campaign_id,
                roster_student_id,
                product_db_written=True,
                reload_matcher_called=reloaded,
            )
        return {
            **written,
            "reload_matcher_called": reloaded,
            "n_templates_loaded": len(templates),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "m2_promote_FAIL campaign=%s roster=%s err=%s",
            campaign_id,
            roster_student_id,
            exc,
        )
        return {"ok": False, "error": str(exc), "n_written": 0}
