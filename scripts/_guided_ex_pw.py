"""EX+/EX= guiado: Playwright (UI+webcam) + API snapshot em paralelo."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).resolve().parents[1] / "results" / "ex_plus_pw_guided"
OUT.mkdir(parents=True, exist_ok=True)
VISION = "http://127.0.0.1:8000/debug/vision"
API = "http://127.0.0.1:8000/api/v1/live/debug-snapshot"

PHASES = [
    (0, 15, "neutral", "CARA SERIA — boca fechada, SEM sorrir"),
    (15, 35, "positive", "SORRIA AGORA COM DENTES — mantenha ate eu pedir para parar"),
    (35, 50, "neutral", "PARE DE SORRIR — cara seria / neutra"),
]


def banner(msg: str) -> None:
    print()
    print("=" * 64)
    print(msg)
    print("=" * 64)
    print(flush=True)


def safe_shot(page, path: Path) -> None:
    """Screenshot tolerante a MJPEG (full_page costuma estourar timeout)."""
    try:
        page.screenshot(
            path=str(path),
            full_page=False,
            timeout=8000,
            animations="disabled",
        )
    except Exception as e:
        print(f"  [shot skip] {path.name}: {e}", flush=True)


def expected_ok(smooth: str | None, want: str) -> bool:
    if want == "neutral":
        return smooth in ("predominantly_neutral", "inconclusive", None)
    if want == "positive":
        return smooth == "predominantly_positive"
    return False


def inject_coach(page, text: str) -> None:
    try:
        page.evaluate(
            """(text) => {
              let el = document.getElementById('ex-coach-banner');
              if (!el) {
                el = document.createElement('div');
                el.id = 'ex-coach-banner';
                el.style.cssText = 'position:fixed;top:8px;left:50%;transform:translateX(-50%);z-index:99999;background:#111;color:#fff;padding:12px 18px;font:700 16px Arial;border:3px solid #f5c542;border-radius:8px;max-width:90vw;text-align:center;';
                document.body.appendChild(el);
              }
              el.textContent = text;
            }""",
            text,
        )
    except Exception:
        pass


def read_ui_expression(page) -> str:
    try:
        return page.evaluate(
            """() => {
              const root = document.getElementById('person-sections');
              if (!root) return '';
              const t = (root.innerText || '').replace(/\\s+/g, ' ');
              const m = t.match(/express[aã]o[^\\n.]{0,80}/i);
              return m ? m[0].slice(0, 120) : t.slice(0, 160);
            }"""
        )
    except Exception:
        return ""


def api_row(elapsed: float) -> dict:
    d = httpx.get(API, timeout=10).json()
    tracks = d.get("tracks") or []
    if not tracks:
        return {"t": round(elapsed, 1), "tracks": 0}
    tr = tracks[0]
    ex = tr.get("expression") or {}
    ff = tr.get("facial_features") or {}
    return {
        "t": round(elapsed, 1),
        "sensor": ex.get("smoothed_state"),
        "boost": ex.get("smile_boost"),
        "lm": ff.get("smile_score"),
        "mouth": ff.get("mouth_open_score"),
        "raw": ex.get("raw_label"),
        "id": tr.get("student_id"),
    }


def main() -> None:
    banner("EX+/EX= com Playwright + API (baseline congelado)")
    print("Janela Chromium vai abrir /debug/vision", flush=True)
    print(f"Prints em: {OUT}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-web-security"],
        )
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()
        page.goto(VISION, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        try:
            page.evaluate(
                """() => {
                  const img = document.getElementById('preview');
                  if (img) img.src = '/debug/mjpeg?camera_id=cam-web&overlay=1&fps=15&v=' + Date.now();
                }"""
            )
        except Exception:
            pass

        inject_coach(page, "PREPARE-SE — countdown 8s — fique na frente da camera")
        for n in range(8, 0, -1):
            print(f"  ... {n}", flush=True)
            inject_coach(page, f"COMECA EM {n}s — posicione o rosto")
            page.wait_for_timeout(1000)

        safe_shot(page, OUT / "00_start.png")

        t0 = time.time()
        prev_phase = None
        prev_print = None
        last_tick = -1.0
        last_mid_shot = -1.0
        transitions: list[dict] = []
        last_smooth = None
        rows: list[dict] = []
        total = PHASES[-1][1]

        banner("COMEÇOU — siga >>> no TERMINAL e o banner amarelo na janela")

        while True:
            elapsed = time.time() - t0
            if elapsed >= total:
                break

            phase = None
            for a, b, want, instr in PHASES:
                if a <= elapsed < b:
                    phase = (a, b, want, instr)
                    break

            if phase and phase[0] != prev_phase:
                a, b, want, instr = phase
                banner(f">>> AGORA ({a:.0f}-{b:.0f}s): {instr}")
                print(
                    f"Esperado: {'NEUTRO' if want == 'neutral' else 'POSITIVO'}",
                    flush=True,
                )
                inject_coach(page, f">>> {instr}")
                safe_shot(page, OUT / f"phase_{a:02d}_start.png")
                prev_phase = phase[0]
                last_tick = elapsed
                last_mid_shot = elapsed

            if phase and elapsed - last_tick >= 5.0:
                a, b, want, instr = phase
                left = max(0, int(b - elapsed))
                print(f"  [{elapsed:4.0f}s] ainda ~{left}s — {instr[:48]}...", flush=True)
                last_tick = elapsed

            # Prints periodicos — especialmente na fase sorriso, para auditoria visual
            if phase and elapsed - last_mid_shot >= 3.0:
                a, b, want, _instr = phase
                tag = "smile" if want == "positive" else "hold"
                safe_shot(page, OUT / f"mid_{tag}_{elapsed:04.1f}s.png")
                last_mid_shot = elapsed

            try:
                row = api_row(elapsed)
            except Exception as e:
                print(f"  [{elapsed:5.1f}s] ERRO API: {e}", flush=True)
                page.wait_for_timeout(400)
                continue

            want = phase[2] if phase else "?"
            smooth = row.get("sensor")
            row["match"] = "OK" if expected_ok(smooth, want) else "DIFERE"
            row["ui"] = (read_ui_expression(page) or "")[:80]

            if last_smooth is not None and smooth != last_smooth:
                transitions.append(
                    {
                        "t": row["t"],
                        "from": last_smooth,
                        "to": smooth,
                        "boost": row.get("boost"),
                        "lm": row.get("lm"),
                        "mouth": row.get("mouth"),
                    }
                )
                safe_shot(page, OUT / f"trans_{row['t']:.0f}_{smooth or 'none'}.png")
            last_smooth = smooth

            if row != prev_print:
                print(json.dumps(row, ensure_ascii=True), flush=True)
                rows.append(row)
                prev_print = row

            page.wait_for_timeout(350)

        inject_coach(page, "FIM DO TESTE — pode relaxar")
        safe_shot(page, OUT / "99_end.png")

        banner("FIM — RESUMO")
        for tr in transitions:
            print(json.dumps(tr, ensure_ascii=True), flush=True)

        summary = []
        for a, b, want, instr in PHASES:
            chunk = [
                r
                for r in rows
                if isinstance(r.get("t"), (int, float)) and a <= r["t"] < b
            ]
            if want == "neutral":
                bad = sum(
                    1 for r in chunk if r.get("sensor") == "predominantly_positive"
                )
                line = f"Fase {a:.0f}-{b:.0f}s (serio): frames={len(chunk)} positivos_indesejados={bad}"
            else:
                good = sum(
                    1 for r in chunk if r.get("sensor") == "predominantly_positive"
                )
                first = next(
                    (
                        r["t"]
                        for r in chunk
                        if r.get("sensor") == "predominantly_positive"
                    ),
                    None,
                )
                line = (
                    f"Fase {a:.0f}-{b:.0f}s (sorriso): frames={len(chunk)} "
                    f"positivos={good} primeira_positiva={first}"
                )
            print(line, flush=True)
            summary.append(line)

        report = {
            "transitions": transitions,
            "summary": summary,
            "rows": rows[-80:],
        }
        (OUT / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        print(f"Report: {OUT / 'report.json'}", flush=True)
        print("Mantendo janela 20s para voce olhar os prints...", flush=True)
        page.wait_for_timeout(20_000)
        browser.close()


if __name__ == "__main__":
    main()
