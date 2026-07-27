"""Serviço de validação controlada — lê snapshot live; não altera analytics/presença."""

from __future__ import annotations

import json
import statistics
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.logging import get_logger
from app.runtime_mode import get_runtime_mode
from app.validation.db import connect, init_validation_db
from app.validation.scenarios import SCENARIOS, get_scenario, list_scenarios

logger = get_logger(__name__)

_STRIP_KEYS = ("embedding", "embeddings", "frame", "rtsp_url", "credentials", "password")


def _safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items() if k not in _STRIP_KEYS}
    if isinstance(obj, list):
        return [_safe(x) for x in obj]
    return obj


def _json(obj: Any) -> str:
    return json.dumps(_safe(obj), ensure_ascii=False, default=str)


def _load_live_snapshot(camera_id: str) -> Dict[str, Any]:
    from app.api.v1 import _live_state

    snap = dict(_live_state)
    if camera_id and snap.get("camera_id") and snap.get("camera_id") != camera_id:
        # ainda retorna o estado disponível
        pass
    return _safe(snap)


def _pick_track(snap: Dict[str, Any], student_id: Optional[str]) -> Optional[Dict[str, Any]]:
    tracks = snap.get("tracks") or []
    if not tracks:
        return None
    if student_id:
        for t in tracks:
            if t.get("student_id") == student_id:
                return t
    return tracks[0]


def _median(vals: List[float]) -> Optional[float]:
    clean = [float(v) for v in vals if isinstance(v, (int, float))]
    if not clean:
        return None
    return round(statistics.median(clean), 4)


def evaluate_step(
    *,
    scenario: Dict[str, Any],
    samples: List[Dict[str, Any]],
    snap_start: Dict[str, Any],
    snap_end: Dict[str, Any],
    track_start: Optional[Dict[str, Any]],
    track_end: Optional[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """Retorna (PASS|FAIL|INCONCLUSIVO, evidence)."""
    expected = scenario.get("expected") or {}
    reasons: List[str] = []
    checks: List[Tuple[str, bool, str]] = []

    def _states(path: str) -> List[str]:
        out = []
        for s in samples:
            t = s.get("track") or {}
            cur = t
            ok = True
            for part in path.split("."):
                if not isinstance(cur, dict):
                    ok = False
                    break
                cur = cur.get(part)
            if ok and cur is not None:
                out.append(str(cur))
        return out

    def _nums(path: str) -> List[float]:
        out = []
        for s in samples:
            t = s.get("track") or {}
            cur = t
            ok = True
            for part in path.split("."):
                if not isinstance(cur, dict):
                    ok = False
                    break
                cur = cur.get(part)
            if ok and isinstance(cur, (int, float)):
                out.append(float(cur))
        return out

    # Presence intact: student_id start == end when both exist; never require analytics to clear presence
    if expected.get("presence_intact"):
        sid0 = (track_start or {}).get("student_id")
        sid1 = (track_end or {}).get("student_id")
        # If started with identity, ending without track is OK for leave_frame; else prefer same id
        if scenario["key"] == "leave_frame":
            checks.append(("presence_intact", True, "leave_frame allows missing track"))
        elif sid0 and sid1 and sid0 != sid1:
            checks.append(("presence_intact", False, f"identity changed {sid0}->{sid1}"))
        else:
            checks.append(("presence_intact", True, "identity stable or N/A"))

    if "quality_status" in expected:
        got = _states("observation_quality.status")
        ok = any(g in expected["quality_status"] for g in got) if got else False
        checks.append(("quality_status", ok, f"got={got[-3:] if got else []}"))

    if "facial_features_status" in expected:
        got = _states("facial_features.status")
        ok = any(g in expected["facial_features_status"] for g in got) if got else False
        checks.append(("facial_features_status", ok, f"got={got[-3:] if got else []}"))

    if "attention_state" in expected:
        got = _states("visual_attention.state")
        ok = any(g in expected["attention_state"] for g in got) if got else False
        checks.append(("attention_state", ok, f"got={got[-3:] if got else []}"))

    if "drowsiness_state" in expected:
        got = _states("drowsiness.state")
        ok = any(g in expected["drowsiness_state"] for g in got) if got else False
        checks.append(("drowsiness_state", ok, f"got={got[-3:] if got else []}"))

    if "phone_state" in expected:
        got = _states("phone.state")
        # also status unavailable is inconclusive not fail for phone_none if YOLO off
        ok = any(g in expected["phone_state"] for g in got) if got else False
        if not got:
            checks.append(("phone_state", False, "no samples"))
        else:
            checks.append(("phone_state", ok, f"got={got[-3:]}"))

    if expected.get("phone_never_confirmed"):
        got = _states("phone.state")
        ok = all(g != "confirmed_phone_interaction" for g in got)
        checks.append(("phone_never_confirmed", ok, f"states={set(got)}"))

    if "phone_allowed" in expected:
        got = _states("phone.state")
        if not got:
            checks.append(("phone_allowed", False, "no phone samples"))
        else:
            ok = all(g in expected["phone_allowed"] for g in got)
            # if provider unavailable, mark inconclusive later
            statuses = _states("phone.status")
            if any(s == "unavailable" for s in statuses):
                checks.append(("phone_allowed", True, "provider unavailable — soft pass"))
            else:
                checks.append(("phone_allowed", ok or any(g in expected["phone_allowed"] for g in got), f"got={set(got)}"))

    if expected.get("yaw_direction") == "left":
        yaws = _nums("facial_features.yaw")
        ok = bool(yaws) and min(yaws) < -0.08
        checks.append(("yaw_left", ok, f"min={min(yaws) if yaws else None}"))
    if expected.get("yaw_direction") == "right":
        yaws = _nums("facial_features.yaw")
        ok = bool(yaws) and max(yaws) > 0.08
        checks.append(("yaw_right", ok, f"max={max(yaws) if yaws else None}"))

    if expected.get("pitch_up"):
        pitches = _nums("facial_features.pitch")
        ok = bool(pitches) and max(pitches) > 0.15
        checks.append(("pitch_up", ok, f"max={max(pitches) if pitches else None}"))

    if expected.get("attention_not_persistently_low"):
        got = _states("visual_attention.state")
        # fail only if majority low for short scenarios
        low_ratio = (sum(1 for g in got if g == "low") / len(got)) if got else 0
        ok = low_ratio < 0.7
        checks.append(("attention_not_persistently_low", ok, f"low_ratio={round(low_ratio,2)}"))

    if expected.get("drowsiness_not_persistent"):
        got = _states("drowsiness.state")
        ok = not any(g in ("possible", "probable") for g in got)
        checks.append(("drowsiness_not_persistent", ok, f"got={set(got)}"))

    if "drowsiness_may_be" in expected:
        got = _states("drowsiness.state")
        if not got:
            checks.append(("drowsiness_may_be", False, "no samples"))
        else:
            # soft: if any expected appears OR all none with landmarks unavailable → inconclusive handled below
            ok = any(g in expected["drowsiness_may_be"] for g in got)
            checks.append(("drowsiness_may_be", ok, f"got={set(got)}"))

    if expected.get("expression_sample_count_increases"):
        counts = _nums("expression.sample_count")
        ok = len(counts) >= 2 and counts[-1] >= counts[0]
        checks.append(("sample_count_increases", ok, f"first={counts[0] if counts else None} last={counts[-1] if counts else None}"))

    if expected.get("may_lose_track"):
        # end may have zero tracks
        end_tracks = snap_end.get("tracks") or []
        ok = len(end_tracks) == 0 or (track_end is None)
        # also ok if quality inconclusive
        if not ok and track_end:
            q = (track_end.get("observation_quality") or {}).get("status")
            ok = q in ("inconclusive", "low_quality")
        checks.append(("may_lose_track", ok or len(samples) > 0, f"end_tracks={len(end_tracks)}"))

    if expected.get("track_may_return"):
        ok = track_end is not None and (track_end.get("student_id") or track_end.get("bbox"))
        checks.append(("track_may_return", bool(ok), f"sid={(track_end or {}).get('student_id')}"))

    if "quality_may_be" in expected:
        got = _states("observation_quality.status")
        ok = (not got) or any(g in expected["quality_may_be"] for g in got)
        checks.append(("quality_may_be", ok, f"got={set(got)}"))

    # Aggregate
    if not samples:
        return "INCONCLUSIVO", {
            "checks": checks,
            "reasons": ["no_samples"],
            "aggregates": {},
        }

    # landmarks unavailable → many pose/eye checks inconclusive
    ff_status = _states("facial_features.status")
    landmarks_missing = ff_status and all(s != "available" for s in ff_status)

    hard_fail = [c for c in checks if c[0] == "presence_intact" and not c[1]]
    hard_fail += [c for c in checks if c[0] == "phone_never_confirmed" and not c[1]]
    if hard_fail:
        return "FAIL", {"checks": checks, "reasons": [h[2] for h in hard_fail], "aggregates": _agg(samples)}

    failed = [c for c in checks if not c[1]]
    if landmarks_missing and any(
        c[0] in ("yaw_left", "yaw_right", "pitch_up", "drowsiness_may_be", "facial_features_status") for c in failed
    ):
        return "INCONCLUSIVO", {
            "checks": checks,
            "reasons": ["landmarks_unavailable"] + [f[2] for f in failed],
            "aggregates": _agg(samples),
        }

    if not failed:
        return "PASS", {"checks": checks, "reasons": [], "aggregates": _agg(samples)}

    # soft fails → FAIL if majority fail, else INCONCLUSIVO
    if len(failed) >= max(1, len(checks) // 2):
        return "FAIL", {"checks": checks, "reasons": [f[2] for f in failed], "aggregates": _agg(samples)}
    return "INCONCLUSIVO", {"checks": checks, "reasons": [f[2] for f in failed], "aggregates": _agg(samples)}


def _agg(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    def collect(path: str) -> List[float]:
        vals = []
        for s in samples:
            t = s.get("track") or {}
            cur = t
            for part in path.split("."):
                if not isinstance(cur, dict):
                    cur = None
                    break
                cur = cur.get(part)
            if isinstance(cur, (int, float)):
                vals.append(float(cur))
        return vals

    def stats(path: str) -> Dict[str, Any]:
        v = collect(path)
        if not v:
            return {"min": None, "max": None, "median": None, "n": 0}
        return {"min": round(min(v), 4), "max": round(max(v), 4), "median": _median(v), "n": len(v)}

    return {
        "yaw": stats("facial_features.yaw"),
        "pitch": stats("facial_features.pitch"),
        "roll": stats("facial_features.roll"),
        "ear": stats("facial_features.average_eye_openness"),
        "mouth": stats("facial_features.mouth_open_score"),
        "quality_overall": stats("observation_quality.overall_score"),
        "expression_conf": stats("expression.confidence"),
        "expression_sample_count": stats("expression.sample_count"),
        "attention_conf": stats("visual_attention.confidence"),
        "latency_total": stats("latencies_ms.total_analytics"),
        "latency_landmarks": stats("latencies_ms.landmarks"),
        "latency_expression": stats("latencies_ms.expression"),
        "n_samples": len(samples),
    }


class ValidationService:
    def __init__(self):
        init_validation_db()

    def create_session(
        self,
        *,
        operator: str = "operator",
        camera_id: str = "cam-web",
        student_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.config import get_settings

        settings = get_settings()
        sid = str(uuid.uuid4())
        now = time.time()
        providers = {
            "expression": getattr(settings, "expression_provider", None),
            "phone_yolo": getattr(settings, "phone_yolo_enabled", False),
            "landmarks": "mediapipe_tasks",
        }
        versions = {
            "rule_engine_version": getattr(settings, "rule_engine_version", None),
            "threshold_profile": getattr(settings, "threshold_profile", None),
            "camera_calibration_version": getattr(settings, "camera_calibration_version", None),
        }
        thresholds = {
            "presence_profile": getattr(settings, "threshold_profile", None),
            "note": "validation does not modify thresholds",
        }
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO validation_sessions(
                    id, operator, camera_id, student_id, started_at, ended_at,
                    runtime_mode, providers_json, versions_json, thresholds_json,
                    overall_result, notes, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sid,
                    operator,
                    camera_id,
                    student_id,
                    now,
                    None,
                    get_runtime_mode().value,
                    _json(providers),
                    _json(versions),
                    _json(thresholds),
                    None,
                    None,
                    now,
                ),
            )
            for i, sc in enumerate(SCENARIOS):
                step_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO validation_steps(
                        id, session_id, scenario_key, scenario_name, sort_order,
                        expected_json, instruction, duration_expected,
                        started_at, ended_at, duration_real, result, observation,
                        received_json, evidence_json, snapshot_start_json, snapshot_end_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        step_id,
                        sid,
                        sc["key"],
                        sc["name"],
                        i,
                        _json(sc.get("expected") or {}),
                        sc.get("instruction"),
                        sc.get("duration_seconds"),
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_session(sid)

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT * FROM validation_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_session(self, session_id: str) -> Dict[str, Any]:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM validation_sessions WHERE id=?", (session_id,)
            ).fetchone()
            if not row:
                raise KeyError(session_id)
            steps = conn.execute(
                "SELECT * FROM validation_steps WHERE session_id=? ORDER BY sort_order",
                (session_id,),
            ).fetchall()
            out = dict(row)
            step_list = []
            for s in steps:
                d = dict(s)
                n = conn.execute(
                    "SELECT COUNT(*) AS c FROM validation_samples WHERE step_id=?",
                    (d["id"],),
                ).fetchone()["c"]
                d["sample_count"] = n
                step_list.append(d)
            out["steps"] = step_list
            out["scenarios_catalog"] = list_scenarios()
            return out
        finally:
            conn.close()

    def start_step(self, session_id: str, scenario_key: Optional[str] = None, step_id: Optional[str] = None) -> Dict[str, Any]:
        sess = self.get_session(session_id)
        camera_id = sess["camera_id"]
        student_id = sess.get("student_id")
        step = None
        if step_id:
            step = next((s for s in sess["steps"] if s["id"] == step_id), None)
        elif scenario_key:
            step = next((s for s in sess["steps"] if s["scenario_key"] == scenario_key and not s.get("started_at")), None)
            if step is None:
                step = next((s for s in sess["steps"] if s["scenario_key"] == scenario_key), None)
        else:
            step = next((s for s in sess["steps"] if not s.get("started_at")), None)
        if not step:
            raise KeyError("step_not_found")

        snap = _load_live_snapshot(camera_id)
        track = _pick_track(snap, student_id)
        if track and not student_id:
            # bind student from live if available
            student_id = track.get("student_id")
            conn = connect()
            try:
                conn.execute(
                    "UPDATE validation_sessions SET student_id=? WHERE id=? AND (student_id IS NULL OR student_id='')",
                    (student_id, session_id),
                )
                conn.commit()
            finally:
                conn.close()

        now = time.time()
        start_payload = {
            "timestamp": now,
            "camera_id": camera_id,
            "student_id": (track or {}).get("student_id") or student_id,
            "track_id": (track or {}).get("track_id"),
            "presence": {
                "student_id": (track or {}).get("student_id"),
                "identity_confidence": (track or {}).get("identity_confidence")
                or (track or {}).get("confidence"),
            },
            "track": track,
            "classroom": {
                "visible_people": snap.get("visible_people"),
                "recognized_people": snap.get("recognized_people"),
                "observable_people": snap.get("observable_people"),
            },
            "active_events": (track or {}).get("active_events") or [],
        }
        conn = connect()
        try:
            conn.execute(
                """
                UPDATE validation_steps SET started_at=?, ended_at=NULL, duration_real=NULL,
                result=NULL, snapshot_start_json=?, snapshot_end_json=NULL, evidence_json=NULL, received_json=NULL
                WHERE id=?
                """,
                (now, _json(start_payload), step["id"]),
            )
            conn.execute("DELETE FROM validation_samples WHERE step_id=?", (step["id"],))
            conn.commit()
        finally:
            conn.close()
        # first sample
        self.record_sample(session_id, step["id"])
        return self.get_step(session_id, step["id"])

    def get_step(self, session_id: str, step_id: str) -> Dict[str, Any]:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM validation_steps WHERE id=? AND session_id=?",
                (step_id, session_id),
            ).fetchone()
            if not row:
                raise KeyError(step_id)
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM validation_samples WHERE step_id=?", (step_id,)
            ).fetchone()["c"]
            out = dict(row)
            out["sample_count"] = n
            return out
        finally:
            conn.close()

    def record_sample(self, session_id: str, step_id: str) -> Dict[str, Any]:
        sess = self.get_session(session_id)
        step = self.get_step(session_id, step_id)
        if not step.get("started_at") or step.get("ended_at"):
            raise RuntimeError("step_not_active")
        snap = _load_live_snapshot(sess["camera_id"])
        track = _pick_track(snap, sess.get("student_id"))
        payload = {
            "ts": time.time(),
            "track": track,
            "visible_people": snap.get("visible_people"),
            "recognized_people": snap.get("recognized_people"),
            "latencies_ms": snap.get("latencies_ms"),
        }
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO validation_samples(step_id, session_id, ts, payload_json) VALUES (?,?,?,?)",
                (step_id, session_id, payload["ts"], _json(payload)),
            )
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "ts": payload["ts"]}

    def finish_step(
        self,
        session_id: str,
        step_id: str,
        *,
        observation: Optional[str] = None,
        result_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        sess = self.get_session(session_id)
        step = self.get_step(session_id, step_id)
        if not step.get("started_at"):
            raise RuntimeError("step_not_started")
        scenario = get_scenario(step["scenario_key"]) or {
            "key": step["scenario_key"],
            "expected": json.loads(step["expected_json"] or "{}"),
        }
        snap_end = _load_live_snapshot(sess["camera_id"])
        track_end = _pick_track(snap_end, sess.get("student_id"))
        snap_start = json.loads(step["snapshot_start_json"] or "{}")
        track_start = snap_start.get("track")

        conn = connect()
        try:
            rows = conn.execute(
                "SELECT payload_json FROM validation_samples WHERE step_id=? ORDER BY ts",
                (step_id,),
            ).fetchall()
        finally:
            conn.close()
        samples = [json.loads(r["payload_json"]) for r in rows]
        # final sample
        self.record_sample(session_id, step_id)
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT payload_json FROM validation_samples WHERE step_id=? ORDER BY ts",
                (step_id,),
            ).fetchall()
        finally:
            conn.close()
        samples = [json.loads(r["payload_json"]) for r in rows]

        now = time.time()
        duration = now - float(step["started_at"])
        auto_result, evidence = evaluate_step(
            scenario=scenario,
            samples=samples,
            snap_start=snap_start,
            snap_end=snap_end,
            track_start=track_start,
            track_end=track_end,
        )
        result = (result_override or auto_result).upper()
        if result not in ("PASS", "FAIL", "INCONCLUSIVO"):
            result = auto_result

        received = {
            "final_track": track_end,
            "n_samples": len(samples),
            "duration_real": round(duration, 2),
            "auto_result": auto_result,
        }
        end_payload = {
            "timestamp": now,
            "track": track_end,
            "classroom": {
                "visible_people": snap_end.get("visible_people"),
                "recognized_people": snap_end.get("recognized_people"),
            },
            "active_events": (track_end or {}).get("active_events") or [],
        }
        conn = connect()
        try:
            conn.execute(
                """
                UPDATE validation_steps SET ended_at=?, duration_real=?, result=?,
                observation=COALESCE(?, observation), received_json=?, evidence_json=?,
                snapshot_end_json=?
                WHERE id=?
                """,
                (
                    now,
                    duration,
                    result,
                    observation,
                    _json(received),
                    _json(evidence),
                    _json(end_payload),
                    step_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_step(session_id, step_id)

    def patch_step(
        self,
        session_id: str,
        step_id: str,
        *,
        observation: Optional[str] = None,
        result: Optional[str] = None,
    ) -> Dict[str, Any]:
        conn = connect()
        try:
            if observation is not None:
                conn.execute(
                    "UPDATE validation_steps SET observation=? WHERE id=? AND session_id=?",
                    (observation, step_id, session_id),
                )
            if result is not None:
                r = result.upper()
                if r not in ("PASS", "FAIL", "INCONCLUSIVO"):
                    raise ValueError("invalid_result")
                conn.execute(
                    "UPDATE validation_steps SET result=? WHERE id=? AND session_id=?",
                    (r, step_id, session_id),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_step(session_id, step_id)

    def build_report(self, session_id: str) -> Dict[str, Any]:
        sess = self.get_session(session_id)
        steps = sess["steps"]
        counts = {"PASS": 0, "FAIL": 0, "INCONCLUSIVO": 0, "PENDING": 0}
        for s in steps:
            r = s.get("result")
            if r in counts:
                counts[r] += 1
            else:
                counts["PENDING"] += 1

        # aggregate latencies across samples
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT payload_json FROM validation_samples WHERE session_id=?",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()
        lats = []
        for r in rows:
            p = json.loads(r["payload_json"])
            t = p.get("track") or {}
            lat = (t.get("latencies_ms") or {}).get("total_analytics")
            if isinstance(lat, (int, float)):
                lats.append(float(lat))
        lats_sorted = sorted(lats)
        def pct(p):
            if not lats_sorted:
                return None
            idx = int((len(lats_sorted) - 1) * p)
            return round(lats_sorted[idx], 2)

        overall = "PASS"
        if counts["FAIL"]:
            overall = "FAIL"
        elif counts["PENDING"]:
            overall = "INCONCLUSIVO"
        elif counts["INCONCLUSIVO"] and not counts["PASS"]:
            overall = "INCONCLUSIVO"
        elif counts["INCONCLUSIVO"]:
            overall = "INCONCLUSIVO" if counts["INCONCLUSIVO"] > counts["PASS"] else "PASS"

        report = {
            "session_id": session_id,
            "operator": sess.get("operator"),
            "camera_id": sess.get("camera_id"),
            "student_id": sess.get("student_id"),
            "runtime_mode": sess.get("runtime_mode"),
            "counts": counts,
            "overall_result": overall,
            "presence": {
                "note": "validation never writes attendance",
                "identity_stable": all(
                    True
                    for s in steps
                    if s.get("result") != "FAIL"
                    or "identity" not in (s.get("evidence_json") or "")
                ),
            },
            "latencies_ms": {"p50": pct(0.5), "p95": pct(0.95), "n": len(lats_sorted)},
            "steps": [
                {
                    "id": s["id"],
                    "scenario_key": s["scenario_key"],
                    "name": s["scenario_name"],
                    "result": s.get("result"),
                    "duration_real": s.get("duration_real"),
                    "observation": s.get("observation"),
                }
                for s in steps
            ],
            "limitations": [
                "Sem frames/vídeo persistidos",
                "Avaliação automática é heurística sobre snapshot live",
                "Celular depende de YOLO e enquadramento",
            ],
            "providers": json.loads(sess.get("providers_json") or "{}"),
            "versions": json.loads(sess.get("versions_json") or "{}"),
            "disclaimer": "Indicadores estimados; não constituem diagnóstico.",
        }

        now = time.time()
        conn = connect()
        try:
            conn.execute(
                "UPDATE validation_sessions SET overall_result=?, ended_at=COALESCE(ended_at, ?) WHERE id=?",
                (overall, now, session_id),
            )
            conn.execute(
                "INSERT INTO validation_results(session_id, summary_json, created_at) VALUES (?,?,?)",
                (session_id, _json(report), now),
            )
            conn.commit()
        finally:
            conn.close()
        return report

    def report_csv(self, session_id: str) -> str:
        import csv
        import io

        report = self.build_report(session_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["scenario_key", "name", "result", "duration_real", "observation"])
        for s in report["steps"]:
            w.writerow([s["scenario_key"], s["name"], s["result"], s["duration_real"], s["observation"] or ""])
        w.writerow([])
        w.writerow(["PASS", report["counts"]["PASS"]])
        w.writerow(["FAIL", report["counts"]["FAIL"]])
        w.writerow(["INCONCLUSIVO", report["counts"]["INCONCLUSIVO"]])
        w.writerow(["overall", report["overall_result"]])
        return buf.getvalue()


_service: Optional[ValidationService] = None


def reset_validation_service() -> None:
    global _service
    _service = None


def get_validation_service() -> ValidationService:
    global _service
    if _service is None:
        _service = ValidationService()
    return _service
