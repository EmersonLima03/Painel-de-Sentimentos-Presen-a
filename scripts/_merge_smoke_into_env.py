"""Atualiza .env principal com vars de smoke (sem logar secrets)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / ".env.smoke.local"
ENV = ROOT / ".env"

KEYS = [
    "DEVICE_ID",
    "DEVICE_TOKEN",
    "CLOUD_ORGANIZATION_ID",
    "CLOUD_SCHOOL_ID",
    "SUPABASE_INGEST_URL",
    "SUPABASE_ANON_KEY",
]


def load(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def main() -> None:
    smoke = load(SMOKE)
    env = load(ENV)
    for k in KEYS:
        if k in smoke:
            env[k] = smoke[k]
    # keep existing keys; rewrite file preserving comments roughly as flat kv
    lines = [f"{k}={v}" for k, v in env.items()]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("updated .env keys:", ", ".join(KEYS))
    print("DEVICE_ID set=", bool(env.get("DEVICE_ID")))
    print("DEVICE_TOKEN set=", bool(env.get("DEVICE_TOKEN")))
    print("INGEST set=", bool(env.get("SUPABASE_INGEST_URL")))


if __name__ == "__main__":
    main()
