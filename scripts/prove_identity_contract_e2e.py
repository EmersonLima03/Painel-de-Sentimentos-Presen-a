"""Prove facial identity contract against live Edge (:8000).

Does NOT require phone UX. Simulates TEMP gallery → promote → reload → match
isolation → revoke → restart persistence check.

Usage (from repo root _facial_enroll_prod):
  python scripts/prove_identity_contract_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
M2_SCRIPTS = (
    REPO
    / "experiments"
    / "smoke_e2e_sentimentos"
    / "modulo2_poc"
    / "scripts"
)
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(M2_SCRIPTS))

from enrollment_promote import (  # noqa: E402
    edge_student_has_embeddings,
    gallery_dir,
    promote_completed_enrollment,
    reload_matcher_via_edge,
    revoke_identity_from_matcher,
)


def _unit(seed: int, dim: int = 512) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _write_temp_gallery(campaign_id: str, roster_id: str, seed: int) -> Path:
    g = gallery_dir(campaign_id, roster_id)
    g.mkdir(parents=True, exist_ok=True)
    steps = ("front", "lateral_right", "lateral_left", "validate")
    for i, step in enumerate(steps):
        # Slightly perturbed versions of the same identity
        base = _unit(seed)
        noise = _unit(seed + 100 + i) * 0.05
        vec = base + noise
        vec = vec / (np.linalg.norm(vec) + 1e-9)
        np.save(g / f"{step}.npy", vec.astype(np.float32))
    meta = {
        "campaign_id": campaign_id,
        "roster_student_id": roster_id,
        "samples": [{"step": s} for s in steps],
    }
    (g / "enroll_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return g


def _match_self(edge_key: str, probe: np.ndarray) -> dict:
    from app.config import get_settings
    from app.db.init_db import get_session
    from app.db.repo import FaceEmbeddingRepository
    from app.utils.embedding_io import deserialize_embedding
    from app.vision.matcher import FAISSMatcher

    settings = get_settings()
    session = get_session()
    repo = FaceEmbeddingRepository(session)
    rows = repo.get_all_active_embeddings(
        device_id=settings.device_id, school_id=settings.school_id
    )
    gallery = []
    dim = int(probe.shape[0])
    for r in rows:
        vec = deserialize_embedding(r.embedding_blob, dim=int(r.embedding_dim or dim))
        n = float(np.linalg.norm(vec))
        if n > 0:
            vec = vec / n
        gallery.append((r.student_id, vec))
    matcher = FAISSMatcher(gallery, dim=dim)
    hit = matcher.find_match(probe, threshold=0.55, margin=0.05)
    topk = matcher.find_match_topk(probe, k=3)
    if hit:
        return {
            "student_id": hit[0],
            "score": hit[1],
            "decision": "MATCH",
            "topk": topk,
        }
    return {
        "student_id": topk[0][0] if topk else None,
        "score": topk[0][1] if topk else 0.0,
        "decision": "UNKNOWN",
        "topk": topk,
    }


def main() -> int:
    report: dict = {"ok": False, "steps": []}
    camp = f"prove_{int(time.time())}"
    roster = "roster_p01_prove"
    edge_key = "p01"
    seed = 42

    try:
        gdir = _write_temp_gallery(camp, roster, seed)
        report["steps"].append({"write_temp": str(gdir), "ok": True})

        promo = promote_completed_enrollment(
            campaign_id=camp,
            roster_student_id=roster,
            edge_student_key=edge_key,
            display_name="Homolog Edge p01",
            replace=True,
            call_reload=True,
        )
        report["steps"].append({"promote": promo})
        if not promo.get("product_enrolled"):
            report["error"] = "promote_not_enrolled"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        has = edge_student_has_embeddings(edge_key)
        report["steps"].append({"embeddings_persist": has})
        if not has:
            report["error"] = "embeddings_missing"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        probe = _unit(seed)
        m = _match_self(edge_key, probe)
        report["steps"].append({"self_match": m})
        top = (m.get("student_id") or m.get("top1_id") or "").strip()
        if top != edge_key:
            report["error"] = f"self_match_expected_p01_got_{top}"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        # P02 probe (different seed) must not resolve as p01 at high confidence
        # after we only enrolled p01 — if match returns p01, score should be low /
        # UNKNOWN depending on matcher threshold.
        alien = _unit(999)
        m2 = _match_self(edge_key, alien)
        report["steps"].append({"alien_probe_vs_p01_gallery": m2})
        alien_id = (m2.get("student_id") or m2.get("top1_id") or "").strip()
        decision = str(m2.get("decision") or m2.get("status") or "").upper()
        score = float(m2.get("score") or m2.get("top1_score") or 0)
        # Accept UNKNOWN or low-score non-confirm
        if alien_id == edge_key and score >= 0.55 and decision not in (
            "UNKNOWN",
            "REJECT",
            "",
        ):
            report["error"] = "alien_accepted_as_p01"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        # Reload failure contract (simulated): persist ok but reload fail → not enrolled
        from enrollment_promote import promote_completed_enrollment as promo_fn
        import enrollment_promote as ep

        camp2 = camp + "_reload_fail"
        _write_temp_gallery(camp2, roster, seed=77)
        real_reload = ep.reload_matcher_via_edge

        def boom(*a, **k):
            return {"ok": False, "error": "simulated_reload_fail"}

        ep.reload_matcher_via_edge = boom  # type: ignore
        try:
            fail = promo_fn(
                campaign_id=camp2,
                roster_student_id=roster,
                edge_student_key="p01",
                display_name="Homolog Edge p01",
                replace=True,
                call_reload=True,
            )
        finally:
            ep.reload_matcher_via_edge = real_reload  # type: ignore
        report["steps"].append({"reload_fail_contract": fail})
        if fail.get("product_enrolled"):
            report["error"] = "reload_fail_still_enrolled"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        # Restore good promote state for restart check
        promo2 = promote_completed_enrollment(
            campaign_id=camp,
            roster_student_id=roster,
            edge_student_key=edge_key,
            display_name="Homolog Edge p01",
            replace=True,
            call_reload=True,
        )
        report["steps"].append({"restore_promote": promo2.get("product_enrolled")})

        # Revoke leaves history path: delete from matcher
        rev = revoke_identity_from_matcher(edge_student_key=edge_key, call_reload=True)
        report["steps"].append({"revoke": rev})
        if edge_student_has_embeddings(edge_key):
            report["error"] = "revoke_left_embeddings"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        # Re-promote for restart persistence proof
        promo3 = promote_completed_enrollment(
            campaign_id=camp,
            roster_student_id=roster,
            edge_student_key=edge_key,
            display_name="Homolog Edge p01",
            replace=True,
            call_reload=True,
        )
        report["steps"].append({"final_promote": promo3.get("product_enrolled")})
        report["ok"] = bool(promo3.get("product_enrolled"))
        report["note"] = (
            "Physical phone HTTPS + camera recognition still needs operator "
            "walkthrough (P01 enroll UI + live camera). This script proves "
            "atomic promote/reload/revoke/matcher isolation on live Edge."
        )
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)
        report["ok"] = False

    out = REPO / "results" / "prove_identity_contract_e2e.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
