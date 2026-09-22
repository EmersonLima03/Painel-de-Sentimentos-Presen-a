"""Abre /debug/vision headed (USB cam-web) e fica aberto para teste ao vivo."""
from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "results" / "live_debug_vision"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000/debug/vision"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-web-security"],
        )
        context = browser.new_context(viewport={"width": 1400, "height": 900}, no_viewport=False)
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "01_opened.png"), full_page=True)

        # Force MJPEG on cam-web if preview exists
        try:
            page.evaluate(
                """() => {
                  const img = document.getElementById('preview');
                  if (img) {
                    img.src = '/debug/mjpeg?camera_id=cam-web&overlay=1&fps=15&v=' + Date.now();
                  }
                  const cam = document.getElementById('val-camera');
                  if (cam) cam.value = 'cam-web';
                }"""
            )
        except Exception:
            pass

        print("OPENED", URL)
        print("Posicione o rosto na USB (cam-web). Janela Playwright fica aberta.")
        print("Coletando matches por ~90s...")

        samples = []
        for i in range(18):  # ~90s
            time.sleep(5)
            try:
                body = page.evaluate(
                    """async () => {
                      const r = await fetch('/debug/overlay_matches?camera_id=cam-web');
                      return await r.json();
                    }"""
                )
            except Exception as e:
                body = {"error": str(e)}
            matches = body.get("current_matches") if isinstance(body, dict) else None
            samples.append({"t": i * 5, "matches": matches, "raw_keys": list(body.keys()) if isinstance(body, dict) else None})
            print(f"t={i*5}s matches={matches}")
            if i in (0, 5, 11, 17):
                page.screenshot(path=str(OUT / f"live_{i:02d}.png"), full_page=True)

        (OUT / "samples.json").write_text(json.dumps(samples, indent=2, ensure_ascii=True), encoding="utf-8")
        print("DONE samples ->", OUT / "samples.json")
        print("Mantendo browser aberto 5 min para voce validar visualmente...")
        page.wait_for_timeout(300_000)
        browser.close()


if __name__ == "__main__":
    main()
