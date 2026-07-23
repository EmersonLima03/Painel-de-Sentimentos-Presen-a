"""LXP — contratos, mock, outbox com retry exponencial e dead-letter. Sem HttpLXPClient."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class LXPEvent:
    event_type: str
    event_id: str
    class_session_id: str
    payload: Dict[str, Any]
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "event_id": self.event_id,
            "class_session_id": self.class_session_id,
            **self.payload,
        }


@dataclass
class SyncResult:
    ok: bool
    event_id: str
    status: str  # sent | duplicate | failed | disabled | dead
    detail: str = ""


class LXPClient(Protocol):
    async def send_event(self, event: LXPEvent) -> SyncResult:
        ...


class DisabledLXPClient:
    async def send_event(self, event: LXPEvent) -> SyncResult:
        return SyncResult(ok=True, event_id=event.event_id, status="disabled", detail="lxp_mode_disabled")


class MockLXPClient:
    def __init__(self, *, fail_until: int = 0):
        self.received: List[Dict[str, Any]] = []
        self._seen: set[str] = set()
        self._fail_until = fail_until
        self._attempts = 0

    def send_event_sync(self, event: LXPEvent) -> SyncResult:
        self._attempts += 1
        if self._attempts <= self._fail_until:
            return SyncResult(ok=False, event_id=event.event_id, status="failed", detail="simulated_unavailable")
        if event.event_id in self._seen:
            return SyncResult(ok=True, event_id=event.event_id, status="duplicate")
        self._seen.add(event.event_id)
        self.received.append(event.to_dict())
        return SyncResult(ok=True, event_id=event.event_id, status="sent")

    async def send_event(self, event: LXPEvent) -> SyncResult:
        return self.send_event_sync(event)


class LXPOutbox:
    """
    Fila JSONL com idempotência por event_id, retry exponencial e dead-letter.
    """

    def __init__(
        self,
        path: str = "./data/shadow/lxp_outbox.jsonl",
        dead_letter_path: str = "./data/shadow/lxp_dead_letter.jsonl",
        max_retries: int = 3,
        base_backoff_seconds: float = 0.5,
    ):
        self.path = Path(path)
        self.dead_letter_path = Path(dead_letter_path)
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.dead_letter_path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self._meta: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                eid = row.get("event_id")
                if eid:
                    self._seen.add(eid)
                    self._meta[eid] = row
            except Exception:
                continue

    def enqueue(self, event: LXPEvent) -> bool:
        if event.event_id in self._seen:
            return False
        row = {
            **event.to_dict(),
            "status": "pending",
            "retries": 0,
            "last_error": "",
            "next_attempt_at": time.time(),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._seen.add(event.event_id)
        self._meta[event.event_id] = row
        return True

    def pending(self) -> List[Dict[str, Any]]:
        return [r for r in self._meta.values() if r.get("status") in ("pending", "failed")]

    def dead_letters(self) -> List[Dict[str, Any]]:
        if not self.dead_letter_path.exists():
            return []
        out = []
        for line in self.dead_letter_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    def _rewrite(self) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            for row in self._meta.values():
                if row.get("status") != "dead":
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _to_dead(self, row: Dict[str, Any]) -> None:
        row["status"] = "dead"
        with self.dead_letter_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def flush(self, client: LXPClient, *, now: Optional[float] = None) -> Dict[str, int]:
        now = now if now is not None else time.time()
        sent = failed = dead = skipped = 0
        for eid, row in list(self._meta.items()):
            if row.get("status") in ("sent", "dead", "disabled"):
                continue
            if float(row.get("next_attempt_at") or 0) > now:
                skipped += 1
                continue
            event = LXPEvent(
                event_type=row["event_type"],
                event_id=row["event_id"],
                class_session_id=row.get("class_session_id", ""),
                payload={k: v for k, v in row.items() if k not in (
                    "event_type", "event_id", "class_session_id", "status", "retries",
                    "last_error", "next_attempt_at", "created_at",
                )},
            )
            result = await client.send_event(event)
            if result.status in ("sent", "duplicate", "disabled"):
                row["status"] = result.status if result.status != "duplicate" else "sent"
                sent += 1
            else:
                row["retries"] = int(row.get("retries") or 0) + 1
                row["last_error"] = result.detail or result.status
                row["status"] = "failed"
                backoff = self.base_backoff_seconds * (2 ** (row["retries"] - 1))
                row["next_attempt_at"] = now + backoff
                failed += 1
                if row["retries"] >= self.max_retries:
                    self._to_dead(row)
                    dead += 1
        self._rewrite()
        return {"sent": sent, "failed": failed, "dead": dead, "skipped": skipped}


def new_event_id() -> str:
    return str(uuid.uuid4())


def build_attendance_lxp_event(
    *,
    session_id: str,
    student_id: str,
    camera_id: str,
    observed_at: str,
    identity_confidence: float,
) -> LXPEvent:
    return LXPEvent(
        event_type="attendance_checkin",
        event_id=new_event_id(),
        class_session_id=session_id,
        payload={
            "student_id": student_id,
            "camera_id": camera_id,
            "observed_at": observed_at,
            "identity_confidence": identity_confidence,
            "source": "edge-vision",
        },
    )


def build_observation_window_event(
    *,
    session_id: str,
    student_id: str,
    state: str,
    payload: Optional[Dict[str, Any]] = None,
) -> LXPEvent:
    return LXPEvent(
        event_type="student_observation_window",
        event_id=new_event_id(),
        class_session_id=session_id,
        payload={"student_id": student_id, "state": state, **(payload or {})},
    )


def build_classroom_summary_event(*, session_id: str, summary: Dict[str, Any]) -> LXPEvent:
    return LXPEvent(
        event_type="classroom_summary_window",
        event_id=new_event_id(),
        class_session_id=session_id,
        payload=dict(summary),
    )
