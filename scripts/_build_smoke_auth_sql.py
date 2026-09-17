"""Gera SQL de provisionamento Auth a partir de .env.smoke.local."""
from __future__ import annotations

import json
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env.smoke.local"
OUT = ROOT / "scripts" / "_smoke_provision_auth.sql"


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            data[k] = v
    return data


def bh(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=10)).decode()


def main() -> None:
    d = load_env(ENV)
    users = [
        ("GESTOR", "SMOKE_GESTOR_EMAIL", "SMOKE_GESTOR_PASSWORD", "Gestor Demo"),
        ("PROFESSOR", "SMOKE_PROFESSOR_EMAIL", "SMOKE_PROFESSOR_PASSWORD", "Professor Demo"),
        ("MONITOR", "SMOKE_MONITOR_EMAIL", "SMOKE_MONITOR_PASSWORD", "Monitor Demo"),
    ]
    parts: list[str] = []
    for role, ek, pk, name in users:
        uid = d[f"{role}_UID"]
        email = d[ek]
        pw_hash = bh(d[pk])
        meta = json.dumps({"full_name": name})
        app = json.dumps({"provider": "email", "providers": ["email"]})
        parts.append(
            f"""
INSERT INTO auth.users (
  instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
  created_at, updated_at, confirmation_token, recovery_token,
  email_change_token_new, email_change
) VALUES (
  '00000000-0000-0000-0000-000000000000',
  '{uid}'::uuid,
  'authenticated', 'authenticated', '{email}', '{pw_hash}',
  now(),
  '{app}'::jsonb,
  '{meta}'::jsonb,
  now(), now(), '', '', '', ''
) ON CONFLICT (id) DO UPDATE SET
  encrypted_password = EXCLUDED.encrypted_password,
  email_confirmed_at = COALESCE(auth.users.email_confirmed_at, now()),
  updated_at = now();

INSERT INTO auth.identities (
  id, user_id, identity_data, provider, provider_id, last_sign_in_at, created_at, updated_at, email
)
SELECT gen_random_uuid(), '{uid}'::uuid,
  jsonb_build_object('sub', '{uid}', 'email', '{email}', 'email_verified', true),
  'email', '{uid}', now(), now(), now(), '{email}'
WHERE NOT EXISTS (
  SELECT 1 FROM auth.identities WHERE provider = 'email' AND provider_id = '{uid}'
);
"""
        )
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print("wrote", OUT, "bytes", OUT.stat().st_size)
    print("emails", d["SMOKE_GESTOR_EMAIL"], d["SMOKE_PROFESSOR_EMAIL"], d["SMOKE_MONITOR_EMAIL"])


if __name__ == "__main__":
    main()
