"""Gera .env.smoke.local (não versionar). Uso: python scripts/_gen_smoke_secrets.py"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".env.smoke.local"

gestor_pw = secrets.token_urlsafe(16)
prof_pw = secrets.token_urlsafe(16)
mon_pw = secrets.token_urlsafe(16)
device_token = secrets.token_urlsafe(32)
token_hash = hashlib.sha256(device_token.encode()).hexdigest()
device_id = str(uuid.uuid4())
room_id = str(uuid.uuid4())
class_g = str(uuid.uuid4())
subject_id = str(uuid.uuid4())
school_b = "33333333-3333-3333-3333-333333333333"

uids = {
    "gestor": str(uuid.uuid5(uuid.NAMESPACE_DNS, "sentimentos.gestor.demo")),
    "professor": str(uuid.uuid5(uuid.NAMESPACE_DNS, "sentimentos.professor.demo")),
    "monitor": str(uuid.uuid5(uuid.NAMESPACE_DNS, "sentimentos.monitor.demo")),
}

anon = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJtaWFhZGxqenh5ZWh3eXVoaGdkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk2NDg0NTAsImV4cCI6MjEwNTIyNDQ1MH0."
    "1_c4gfw_g8NV6820RoE1pOBTj0lG42XZ28Oohh5PQZo"
)

lines = [
    "# LOCAL ONLY — não commit",
    "SMOKE_GESTOR_EMAIL=gestor.demo@sentimentos.test",
    f"SMOKE_GESTOR_PASSWORD={gestor_pw}",
    "SMOKE_PROFESSOR_EMAIL=professor.demo@sentimentos.test",
    f"SMOKE_PROFESSOR_PASSWORD={prof_pw}",
    "SMOKE_MONITOR_EMAIL=monitor.demo@sentimentos.test",
    f"SMOKE_MONITOR_PASSWORD={mon_pw}",
    "DEVICE_ID=edge-demo-001",
    f"DEVICE_UUID={device_id}",
    f"DEVICE_TOKEN={device_token}",
    f"DEVICE_TOKEN_HASH={token_hash}",
    f"ROOM_ID={room_id}",
    f"CLASS_GROUP_ID={class_g}",
    f"SUBJECT_ID={subject_id}",
    f"SCHOOL_B_ID={school_b}",
    f"GESTOR_UID={uids['gestor']}",
    f"PROFESSOR_UID={uids['professor']}",
    f"MONITOR_UID={uids['monitor']}",
    "CLOUD_ORGANIZATION_ID=11111111-1111-1111-1111-111111111111",
    "CLOUD_SCHOOL_ID=22222222-2222-2222-2222-222222222222",
    "SUPABASE_URL=https://rmiaadljzxyehwyuhhgd.supabase.co",
    "SUPABASE_INGEST_URL=https://rmiaadljzxyehwyuhhgd.supabase.co/functions/v1/ingest-events",
    f"SUPABASE_ANON_KEY={anon}",
    f"VITE_SUPABASE_URL=https://rmiaadljzxyehwyuhhgd.supabase.co",
    f"VITE_SUPABASE_ANON_KEY={anon}",
]
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", OUT)
print("token_hash", token_hash)
for k, v in uids.items():
    print(k, v)
print("device_uuid", device_id)
print("room_id", room_id)
