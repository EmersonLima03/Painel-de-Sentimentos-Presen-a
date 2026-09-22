#!/usr/bin/env python3
"""Lista indices de webcam disponiveis (POC). Nao altera produto."""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        import cv2
    except Exception as e:
        print(json.dumps({"status": "NAO_TESTADO", "reason": str(e)}))
        return 0
    found = []
    for i in range(0, 8):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ok, frame = cap.read()
            w = h = None
            if ok and frame is not None:
                h, w = frame.shape[:2]
            found.append({"index": i, "opened": True, "frame_ok": bool(ok), "w": w, "h": h})
            cap.release()
        else:
            cap.release()
    print(json.dumps({"cameras": found, "hint": "XWF-1080P frequentemente index 2 no lab (ver config.yaml cam-web)"}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
