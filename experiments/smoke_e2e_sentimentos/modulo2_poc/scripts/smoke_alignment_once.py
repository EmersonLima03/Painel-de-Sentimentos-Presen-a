#!/usr/bin/env python3
"""Smoke: 1 frame da webcam → crop_aligned_face produto (sem fallback)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from poc_common import (  # noqa: E402
    ALIGNMENT_MODE_PRODUCT,
    RESULTS,
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    ensure_dirs,
    open_webcam,
    select_primary_face,
)


def main() -> int:
    ensure_dirs()
    webcam = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "webcam": webcam,
        "alignment_mode": None,
        "ok": False,
    }
    try:
        cap = open_webcam(webcam)
    except Exception as e:
        out["error"] = str(e)
        (RESULTS / "smoke_alignment_once.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(out, ensure_ascii=False))
        return 1
    try:
        ok, frame = False, None
        for _ in range(30):
            ok, frame = cap.read()
            if ok and frame is not None:
                break
        if not ok or frame is None:
            out["error"] = "no_frame"
            return 2
        faces = detect_faces_yunet(frame, score_th=0.65)
        face = select_primary_face(faces, frame_shape=frame.shape[:2])
        out["n_faces_raw"] = len(faces)
        if face is None:
            out["error"] = "no_face"
            return 3
        crop, meta = aligned_crop(frame, face)
        out["alignment_mode"] = meta.get("alignment_mode")
        out["bbox"] = meta.get("bbox")
        out["output_size"] = [meta.get("output_w"), meta.get("output_h")]
        out["ok"] = meta.get("alignment_mode") == ALIGNMENT_MODE_PRODUCT
        out["crop_shape"] = list(crop.shape)
    except AlignmentError as e:
        out["error"] = str(e)
        out["ok"] = False
        return 4
    finally:
        try:
            cap.release()
        except Exception:
            pass
        (RESULTS / "smoke_alignment_once.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 5


if __name__ == "__main__":
    raise SystemExit(main())
