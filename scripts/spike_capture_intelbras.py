"""
Captura configurável para spike Intelbras.
Corpora: expression_samples | tracking_clips | phone_scenarios | quality_samples
Não grava continuamente — só duração + sample FPS.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import yaml


CORPORA = ("expression_samples", "tracking_clips", "phone_scenarios", "quality_samples")


def _load_camera(config_path: str, camera_id: str):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for cam in cfg.get("cameras") or []:
        if cam.get("camera_id") == camera_id and cam.get("enabled", True):
            return cam
    raise SystemExit(f"Camera not found or disabled: {camera_id}")


def _open_capture(rtsp_url: str):
    url = str(rtsp_url)
    if url.isdigit():
        cap = cv2.VideoCapture(int(url), cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
    if not cap.isOpened():
        raise SystemExit("Failed to open camera/stream")
    return cap


def main():
    p = argparse.ArgumentParser(description="Spike capture Intelbras")
    p.add_argument("--camera", default="cam-vip-5440-01")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--duration-seconds", type=float, default=60.0)
    p.add_argument("--sample-fps", type=float, default=2.0)
    p.add_argument("--corpus", choices=CORPORA, required=True)
    p.add_argument("--out", required=True, help="Session output dir")
    args = p.parse_args()

    cam = _load_camera(args.config, args.camera)
    out_dir = Path(args.out) / args.corpus
    out_dir.mkdir(parents=True, exist_ok=True)

    # Não logar URL completa com credenciais
    print(f"camera_id={args.camera} corpus={args.corpus} duration={args.duration_seconds}s fps={args.sample_fps}")

    cap = _open_capture(cam["rtsp_url"])
    interval = 1.0 / max(0.1, args.sample_fps)
    t_end = time.time() + args.duration_seconds
    next_t = time.time()
    saved = 0
    meta = {
        "camera_id": args.camera,
        "corpus": args.corpus,
        "duration_seconds": args.duration_seconds,
        "sample_fps": args.sample_fps,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "frames": [],
    }

    try:
        while time.time() < t_end:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            now = time.time()
            if now < next_t:
                continue
            next_t = now + interval
            name = f"frame_{saved:05d}.jpg"
            path = out_dir / name
            cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            meta["frames"].append({"file": name, "ts": datetime.now(timezone.utc).isoformat()})
            saved += 1
            print(f"saved {saved}", end="\r")
    finally:
        cap.release()

    meta["ended_at"] = datetime.now(timezone.utc).isoformat()
    meta["n_frames"] = saved
    (out_dir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nDone: {saved} frames -> {out_dir}")


if __name__ == "__main__":
    main()
