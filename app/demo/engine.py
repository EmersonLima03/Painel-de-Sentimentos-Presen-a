"""Motor de demonstração determinístico (seed fixa) — 8 alunos fictícios."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime_mode import DEMO_BANNER, DEMO_STUDENTS, DISCLAIMER


def _seeded(seed: str) -> float:
    """Pseudo-aleatório determinístico 0..1 a partir de string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


@dataclass
class DemoControl:
    playing: bool = True
    speed: float = 1.0  # 1 | 2 | 5
    t_seconds: float = 0.0  # tempo de cenário 0..900 (15 min)
    session_id: str = ""
    started_at: str = ""


class DemoEngine:
    """
    Cenário de 15 minutos (900s) acelerável.
    Alimenta estado live, banco demo, revisão e outbox LXP mock.
    """

    SCENARIO_DURATION = 900.0

    def __init__(self, demo_db_path: str = "./data/demo/dulino_edge_demo.db"):
        self.demo_db_path = demo_db_path
        self.control = DemoControl(session_id=str(uuid.uuid4()))
        self.control.started_at = datetime.now(timezone.utc).isoformat()
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._review_queue: List[Dict[str, Any]] = []
        self._timeline: List[Dict[str, Any]] = []
        self._lxp_outbox: List[Dict[str, Any]] = []
        self._lxp_dead_letter: List[Dict[str, Any]] = []
        self._attendance: Dict[str, Dict[str, Any]] = {}
        self._last_tick_wall = time.time()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ws_broadcast = None  # async callback set by app
        self._init_demo_db()
        self._seed_students()

    def set_broadcast(self, fn) -> None:
        self._ws_broadcast = fn

    def _init_demo_db(self) -> None:
        Path(self.demo_db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.demo_db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS demo_sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT,
                    ended_at TEXT,
                    status TEXT,
                    metadata_json TEXT
                );
                CREATE TABLE IF NOT EXISTS demo_behavioral_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT,
                    student_id TEXT,
                    track_id TEXT,
                    severity TEXT,
                    status TEXT,
                    confidence REAL,
                    observation_quality REAL,
                    evidence_json TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    provenance_json TEXT
                );
                CREATE TABLE IF NOT EXISTS demo_observation_windows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    track_id TEXT,
                    student_id TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    state TEXT,
                    visual_attention_score REAL,
                    observation_quality REAL,
                    provenance_json TEXT
                );
                CREATE TABLE IF NOT EXISTS demo_climate_windows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    dominant_state TEXT,
                    provenance_json TEXT
                );
                CREATE TABLE IF NOT EXISTS demo_lxp_outbox (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT,
                    payload_json TEXT,
                    status TEXT,
                    retries INTEGER DEFAULT 0,
                    last_error TEXT
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _seed_students(self) -> None:
        for i, st in enumerate(DEMO_STUDENTS):
            self._attendance[st["student_id"]] = {
                **st,
                "present": False,
                "first_seen_at": None,
                "track_id": f"demo-p{i+1}",
            }

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._persist_session_start()
        self._thread = threading.Thread(target=self._loop, name="demo-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def control_update(self, *, playing: Optional[bool] = None, speed: Optional[float] = None, reset: bool = False, seek: Optional[float] = None) -> DemoControl:
        with self._lock:
            if reset:
                self.control.t_seconds = 0.0
                self.control.playing = True
                self._events.clear()
                self._review_queue.clear()
                self._timeline.clear()
                self._lxp_outbox.clear()
                self._seed_students()
            if seek is not None:
                self.control.t_seconds = max(0.0, min(self.SCENARIO_DURATION, float(seek)))
                self._advance_scenario(self.control.t_seconds)
            if playing is not None:
                self.control.playing = playing
            if speed is not None and speed in (1.0, 2.0, 5.0, 1, 2, 5):
                self.control.speed = float(speed)
            return self.control

    def _loop(self) -> None:
        while self._running:
            wall = time.time()
            dt = wall - self._last_tick_wall
            self._last_tick_wall = wall
            with self._lock:
                if self.control.playing:
                    self.control.t_seconds = min(
                        self.SCENARIO_DURATION,
                        self.control.t_seconds + dt * self.control.speed,
                    )
                    self._advance_scenario(self.control.t_seconds)
            time.sleep(0.2)

    def _advance_scenario(self, t: float) -> None:
        # Entrada escalonada 0–60s
        for i, st in enumerate(DEMO_STUDENTS):
            enter_at = 5.0 + i * 6.0
            sid = st["student_id"]
            if t >= enter_at and not self._attendance[sid]["present"]:
                self._attendance[sid]["present"] = True
                self._attendance[sid]["first_seen_at"] = datetime.now(timezone.utc).isoformat()
                self._timeline.append(
                    {
                        "t": t,
                        "type": "attendance_checkin",
                        "student_id": sid,
                        "label": f"Check-in {st['full_name']}",
                    }
                )
                self._enqueue_lxp(
                    "attendance_checkin",
                    {
                        "student_id": sid,
                        "full_name": st["full_name"],
                        "identity_confidence": 0.92,
                        "is_simulated": True,
                    },
                )

        # Eventos comportamentais em momentos fixos
        self._ensure_event(
            t,
            trigger=180.0,
            event_id="demo-phone-visible",
            event_type="phone_visible",
            student_id="demo-felipe",
            severity="possible",
            confidence=0.4,
            quality=0.8,
            reasons=["phone_on_desk"],
            duration=40.0,
            auto_review=None,
        )
        self._ensure_event(
            t,
            trigger=260.0,
            event_id="demo-phone-possible",
            event_type="possible_phone_interaction",
            student_id="demo-bruno",
            severity="possible",
            confidence=0.62,
            quality=0.75,
            reasons=["phone_near_person", "duration>=5s"],
            duration=25.0,
            auto_review=None,
        )
        self._ensure_event(
            t,
            trigger=360.0,
            event_id="demo-phone-probable",
            event_type="probable_phone_interaction",
            student_id="demo-carla",
            severity="probable",
            confidence=0.78,
            quality=0.7,
            reasons=["persistent_near_phone", "head_oriented"],
            duration=50.0,
            auto_review="pending",
        )
        self._ensure_event(
            t,
            trigger=420.0,
            event_id="demo-blink-short",
            event_type="eyes_closed_brief",
            student_id="demo-ana",
            severity="none",
            confidence=0.5,
            quality=0.85,
            reasons=["eyes_closed_2s"],
            duration=2.0,
            auto_review=None,
            emit_review=False,
        )
        self._ensure_event(
            t,
            trigger=480.0,
            event_id="demo-drowsiness",
            event_type="apparent_drowsiness",
            student_id="demo-daniel",
            severity="probable",
            confidence=0.74,
            quality=0.72,
            reasons=["eyes_closed", "head_down", "duration>=12s"],
            duration=45.0,
            auto_review="pending",
        )
        self._ensure_event(
            t,
            trigger=600.0,
            event_id="demo-occluded",
            event_type="prolonged_visual_absence",
            student_id="demo-eduarda",
            severity="inconclusive",
            confidence=0.3,
            quality=0.25,
            reasons=["occluded", "low_observation_quality"],
            duration=30.0,
            auto_review="inconclusive",
        )

        if t >= 880 and self.control.session_id:
            # fim aproximado
            pass

    def _ensure_event(
        self,
        t: float,
        *,
        trigger: float,
        event_id: str,
        event_type: str,
        student_id: str,
        severity: str,
        confidence: float,
        quality: float,
        reasons: List[str],
        duration: float,
        auto_review: Optional[str],
        emit_review: bool = True,
    ) -> None:
        if t < trigger:
            return
        if any(e["event_id"] == event_id for e in self._events):
            # atualizar closed
            for e in self._events:
                if e["event_id"] == event_id and t >= trigger + duration and e.get("status") == "open":
                    e["status"] = "closed"
                    e["ended_at"] = datetime.now(timezone.utc).isoformat()
                    self._persist_event(e)
            return
        if severity == "none" and not emit_review:
            # piscar curto — registra timeline sem review
            self._timeline.append({"t": t, "type": event_type, "student_id": student_id, "label": "Olhos fechados breve (sem alerta)"})
            self._events.append(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "student_id": student_id,
                    "track_id": self._attendance[student_id]["track_id"],
                    "severity": severity,
                    "status": "closed",
                    "confidence": confidence,
                    "observation_quality": quality,
                    "reasons": reasons,
                    "review_status": "n/a",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "is_simulated": True,
                    "runtime_mode": "demo",
                }
            )
            return

        ev = {
            "event_id": event_id,
            "event_type": event_type,
            "student_id": student_id,
            "track_id": self._attendance[student_id]["track_id"],
            "severity": severity,
            "status": "open",
            "confidence": confidence,
            "observation_quality": quality,
            "reasons": reasons,
            "review_status": auto_review or "pending",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": None,
            "is_simulated": True,
            "runtime_mode": "demo",
            "provider": "demo_mock",
            "model_name": "demo-scenario-v1",
            "model_version": "v1",
            "rule_engine_version": "rules-v0-baseline",
            "threshold_profile": "presence-yaml-2026-07-23",
            "camera_calibration_version": "demo-uncalibrated",
        }
        self._events.append(ev)
        self._timeline.append({"t": t, "type": event_type, "student_id": student_id, "label": event_type})
        if emit_review and severity in ("possible", "probable", "inconclusive"):
            self._review_queue.append(dict(ev))
        self._persist_event(ev)
        if event_type.startswith("possible_phone") or event_type.startswith("probable_phone") or event_type == "apparent_drowsiness":
            self._enqueue_lxp(
                "student_observation_window",
                {
                    "student_id": student_id,
                    "state": severity,
                    "event_type": event_type,
                    "is_simulated": True,
                },
            )

    def _provenance(self) -> Dict[str, Any]:
        return {
            "provider": "demo_mock",
            "model_name": "demo-scenario-v1",
            "model_version": "v1",
            "rule_engine_version": "rules-v0-baseline",
            "threshold_profile": "presence-yaml-2026-07-23",
            "camera_calibration_version": "demo-uncalibrated",
            "runtime_mode": "demo",
            "is_simulated": True,
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            t = self.control.t_seconds
            tracks = []
            present = 0
            observable = 0
            inconclusive = 0
            for i, st in enumerate(DEMO_STUDENTS):
                att = self._attendance[st["student_id"]]
                if not att["present"]:
                    continue
                present += 1
                # atenção: alta no início, queda 200–400, recuperação depois
                if t < 200:
                    attn, state = 0.85, "high"
                elif t < 400:
                    attn, state = 0.45, "moderate"
                elif t < 550:
                    attn, state = 0.32, "low"
                else:
                    attn, state = 0.70, "high"
                # oclusão eduarda
                quality = 0.25 if st["student_id"] == "demo-eduarda" and 600 <= t < 630 else 0.8
                if quality < 0.5:
                    state = "inconclusive"
                    attn = None
                    inconclusive += 1
                else:
                    observable += 1
                # expressão agregada
                if t < 300:
                    expr = "predominantly_positive"
                elif t < 500:
                    expr = "predominantly_neutral"
                else:
                    expr = "mixed"
                col = i % 4
                row = i // 4
                tracks.append(
                    {
                        "track_id": att["track_id"],
                        "person_track_id": att["track_id"],
                        "face_track_id": f"demo-f{i+1}",
                        "student_id": st["student_id"],
                        "full_name": st["full_name"],
                        "bbox": [80 + col * 160, 60 + row * 180, 100, 120],
                        "identity_confidence": 0.9,
                        "binding_confidence": 0.88,
                        "visual_attention_score": attn,
                        "attention_state": state,
                        "expression_window": expr,
                        "observation_quality": quality,
                        "eyes_openness": 0.15 if st["student_id"] == "demo-daniel" and 480 <= t < 525 else 0.75,
                        "yaw": 0.0,
                        "pitch": 0.35 if st["student_id"] == "demo-daniel" and 480 <= t < 525 else 0.05,
                        "phone": self._phone_state(st["student_id"], t),
                        "is_simulated": True,
                    }
                )

            # clima
            if t < 300:
                climate = "predominantly_positive"
            elif t < 500:
                climate = "predominantly_neutral"
            else:
                climate = "mixed"

            active_events = [e for e in self._events if e.get("status") == "open"]
            return {
                "runtime_mode": "demo",
                "is_simulated": True,
                "banner": DEMO_BANNER,
                "disclaimer": DISCLAIMER,
                "updated_at": time.time(),
                "session": {
                    "session_id": self.control.session_id,
                    "started_at": self.control.started_at,
                    "t_seconds": round(t, 1),
                    "duration_target": self.SCENARIO_DURATION,
                    "playing": self.control.playing,
                    "speed": self.control.speed,
                },
                "kpis": {
                    "present": present,
                    "visible": len(tracks),
                    "observable": observable,
                    "inconclusive": inconclusive,
                    "attention_index": None
                    if observable == 0
                    else round(
                        sum(tr["visual_attention_score"] or 0 for tr in tracks if tr["attention_state"] != "inconclusive")
                        / max(1, observable),
                        3,
                    ),
                    "climate": climate,
                    "active_events": len(active_events),
                    "camera_status": "demo_source",
                    "lxp_status": "mock",
                },
                "tracks": tracks,
                "bindings": [
                    {
                        "person_track_id": tr["person_track_id"],
                        "face_track_id": tr["face_track_id"],
                        "student_id": tr["student_id"],
                        "binding_confidence": tr["binding_confidence"],
                        "identity_confidence": tr["identity_confidence"],
                    }
                    for tr in tracks
                ],
                "events": list(self._events),
                "review_queue": [e for e in self._review_queue if e.get("review_status") == "pending"],
                "timeline": list(self._timeline)[-50:],
                "attendance": list(self._attendance.values()),
                "phones": [tr["phone"] for tr in tracks if tr["phone"].get("level") != "none"],
                "latencies_ms": {"demo_tick": 2.0, "api": 1.0},
                "performance": {"fps": 5.0 * self.control.speed, "queue_depth": 1, "dropped_frames": 0},
                "provenance": self._provenance(),
                "module_modes": {
                    "expression": "demo",
                    "face_landmarks": "demo",
                    "person_tracking": "demo",
                    "phone": "demo",
                    "pose": "demo",
                    "temporal_fusion": "demo",
                    "educational_dashboard": "production",
                    "lxp": "demo",
                },
            }

    def _phone_state(self, student_id: str, t: float) -> Dict[str, Any]:
        if student_id == "demo-felipe" and 180 <= t < 220:
            return {"level": "phone_visible", "label": "Celular visível (mesa)"}
        if student_id == "demo-bruno" and 260 <= t < 285:
            return {"level": "possible_phone_interaction", "label": "Possível interação com celular"}
        if student_id == "demo-carla" and 360 <= t < 410:
            return {"level": "probable_phone_interaction", "label": "Provável interação com celular"}
        return {"level": "none", "label": None}

    def review_event(self, event_id: str, status: str, notes: str = "") -> Optional[Dict[str, Any]]:
        if status not in ("confirmed", "rejected", "inconclusive", "pending"):
            return None
        with self._lock:
            for e in self._events:
                if e["event_id"] == event_id:
                    e["review_status"] = status
                    e["review_notes"] = notes
                    e["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                    self._persist_event(e)
                    for r in self._review_queue:
                        if r["event_id"] == event_id:
                            r["review_status"] = status
                    return e
        return None

    def report(self) -> Dict[str, Any]:
        snap = self.snapshot()
        return {
            "session_id": self.control.session_id,
            "runtime_mode": "demo",
            "is_simulated": True,
            "banner": DEMO_BANNER,
            "disclaimer": DISCLAIMER,
            "duration_seconds": snap["session"]["t_seconds"],
            "students_present": snap["kpis"]["present"],
            "attention_index": snap["kpis"]["attention_index"],
            "climate": snap["kpis"]["climate"],
            "events_total": len(self._events),
            "events_reviewed": sum(1 for e in self._events if e.get("review_status") in ("confirmed", "rejected", "inconclusive")),
            "limitations": [
                "Sessão 100% simulada — não constitui validação de campo.",
                "Providers reais de expressão não foram avaliados nesta sessão.",
                "RTSP/Intelbras não utilizado.",
            ],
            "timeline": self._timeline,
            "provenance": self._provenance(),
        }

    def _persist_session_start(self) -> None:
        conn = sqlite3.connect(self.demo_db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO demo_sessions(session_id, started_at, status, metadata_json) VALUES (?,?,?,?)",
                (
                    self.control.session_id,
                    self.control.started_at,
                    "active",
                    json.dumps({"is_simulated": True}),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _persist_event(self, ev: Dict[str, Any]) -> None:
        conn = sqlite3.connect(self.demo_db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO demo_behavioral_events(
                    event_id, event_type, student_id, track_id, severity, status,
                    confidence, observation_quality, evidence_json, started_at, ended_at, provenance_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ev["event_id"],
                    ev["event_type"],
                    ev.get("student_id"),
                    ev.get("track_id"),
                    ev.get("severity"),
                    ev.get("review_status") or ev.get("status"),
                    ev.get("confidence"),
                    ev.get("observation_quality"),
                    json.dumps({"reasons": ev.get("reasons", [])}),
                    ev.get("started_at"),
                    ev.get("ended_at"),
                    json.dumps(self._provenance()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _enqueue_lxp(self, event_type: str, payload: Dict[str, Any]) -> None:
        eid = str(uuid.uuid4())
        row = {
            "event_id": eid,
            "event_type": event_type,
            "payload": payload,
            "status": "pending",
            "retries": 0,
        }
        # idempotência simples por conteúdo+tipo em memória
        self._lxp_outbox.append(row)
        conn = sqlite3.connect(self.demo_db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO demo_lxp_outbox(event_id, event_type, payload_json, status, retries) VALUES (?,?,?,?,0)",
                (eid, event_type, json.dumps(payload), "pending"),
            )
            conn.commit()
        finally:
            conn.close()

    def process_lxp_outbox(self, *, fail_once: bool = False) -> Dict[str, Any]:
        """Mock LXP com retry e dead-letter após 3 falhas (100% síncrono)."""
        from app.integrations.lxp import MockLXPClient, LXPEvent

        client = MockLXPClient(fail_until=1 if fail_once else 0)
        sent = 0
        dead = 0
        for row in list(self._lxp_outbox):
            if row["status"] in ("sent", "dead"):
                continue
            # até 3 tentativas com backoff lógico
            while int(row.get("retries") or 0) < 3 and row["status"] != "sent":
                result = client.send_event_sync(
                    LXPEvent(
                        event_type=row["event_type"],
                        event_id=row["event_id"],
                        class_session_id=self.control.session_id,
                        payload=row["payload"],
                    )
                )
                if result.ok:
                    row["status"] = "sent"
                    sent += 1
                    break
                row["retries"] = int(row.get("retries") or 0) + 1
                row["status"] = "failed"
                row["last_error"] = result.detail
            if row["status"] != "sent" and int(row.get("retries") or 0) >= 3:
                row["status"] = "dead"
                self._lxp_dead_letter.append(dict(row))
                dead += 1
        return {
            "sent": sent,
            "dead": dead,
            "outbox": len(self._lxp_outbox),
            "dead_letter": len(self._lxp_dead_letter),
            "is_simulated": True,
        }

_demo_engine: Optional[DemoEngine] = None


def get_demo_engine() -> DemoEngine:
    global _demo_engine
    if _demo_engine is None:
        try:
            from app.config import get_settings

            path = getattr(get_settings(), "demo_db_path", "./data/demo/dulino_edge_demo.db")
        except Exception:
            path = "./data/demo/dulino_edge_demo.db"
        # Nunca usar banco de produção
        if Path(path).resolve().name == "dulino_edge.db":
            path = "./data/demo/dulino_edge_demo.db"
        _demo_engine = DemoEngine(demo_db_path=path)
    return _demo_engine


def reset_demo_engine_for_tests() -> None:
    global _demo_engine
    if _demo_engine is not None:
        _demo_engine.stop()
    _demo_engine = None
