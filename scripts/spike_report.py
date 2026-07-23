"""Agrega benches JSON → markdown. Concordância ≠ acerto."""

from __future__ import annotations

import argparse
import json
from glob import glob
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bench", nargs="+", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    files = []
    for pattern in args.bench:
        files.extend(glob(pattern))
    reports = []
    for f in files:
        reports.append(json.loads(Path(f).read_text(encoding="utf-8")))

    lines = [
        "# Spike — Expressão aparente (auto)",
        "",
        "## Disclaimer",
        "Concordância entre modelos **não comprova acerto**. Macro-F1 só com labels humanos.",
        "",
        "## Providers",
        "",
        "| provider | p50 ms | p95 ms | mem MB | inconclusive | flicker | failures | macro_F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in reports:
        sup = r.get("supervised") or {}
        lines.append(
            f"| {r.get('provider')} | {r.get('latency_ms_p50', 0):.1f} | {r.get('latency_ms_p95', 0):.1f} | "
            f"{r.get('peak_memory_mb', 0):.1f} | {r.get('inconclusive_rate', 0):.2f} | "
            f"{r.get('flicker_rate', 0):.2f} | {r.get('failures', 0)} | "
            f"{sup.get('macro_f1', 'n/a')} |"
        )

    # concordância pairwise se ≥2
    if len(reports) >= 2:
        lines += ["", "## Concordância (≠ acerto)", "Comparar histogramas manualmente / debug vision.", ""]

    lines += [
        "",
        "## Decisão",
        "- provider recomendado para **shadow** (máximo): _preencher_",
        "- nunca promover direto a production",
        "",
    ]
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
