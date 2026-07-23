"""LXP — contratos, mock, fila e idempotência. Sem HttpLXPClient sem spec."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
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
    status: str  # sent | duplicate | failed | disabled
    detail: str = ""


class LXPClient(Protocol):
    async def send_event(self, event: LXPEvent) -> SyncResult:
        ...


class DisabledLXPClient:
    async def send_event(self, event: LXPEvent) -> SyncResult:
        return SyncResult(ok=True, event_id=event.event_id, status="disabled", detail="lxp_mode_disabled")


class MockLXPClient:
    def __init__(self):
        self.received: List[Dict[str, Any]] = []
        self._seen: set[str] = set()

    async def send_event(self, event: LXPEvent) -> SyncResult:
        if event.event_id in self._seen:
            return SyncResult(ok=True, event_id=event.event_id, status="duplicate")
        self._seen.add(event.event_id)
        self.received.append(event.to_dict())
        return SyncResult(ok=True, event_id=event.event_id, status="sent")


class LXPOutbox:
    """Fila persistente JSON com idempotência por event_id."""

    def __init__(self, path: str = "./data/shadow/lxp_outbox.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    eid = row.get("event_id")
                    if eid:
                        self._seen.add(eid)
                except Exception:
                    continue

    def enqueue(self, event: LXPEvent) -> bool:
        if event.event_id in self._seen:
            return False
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        self._seen.add(event.event_id)
        return True

    def pending(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return rows


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
