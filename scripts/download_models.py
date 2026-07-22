#!/usr/bin/env python3
"""Baixa modelos opcionais (emoção Mini-Xception, DNN SSD, YuNet se ausente)."""

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data" / "models"
DNN = ROOT / "data" / "opencv_models"

URLS = {
    MODELS / "_mini_XCEPTION.106-0.65.hdf5": (
        "https://github.com/abhijeet3922/FaceEmotion_ID/raw/master/"
        "models/_mini_XCEPTION.106-0.65.hdf5"
    ),
    DNN / "opencv_face_detector_uint8.pb": (
        "https://raw.githubusercontent.com/opencv/opencv_3rdparty/"
        "dnn_samples_20170818/opencv_face_detector/opencv_face_detector_uint8.pb"
    ),
    DNN / "opencv_face_detector.pbtxt": (
        "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/"
        "face_detector/opencv_face_detector.pbtxt"
    ),
}


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 5000:
        print(f"OK (ja existe): {dest.name}")
        return True
    print(f"Baixando {dest.name} ...")
    try:
        urllib.request.urlretrieve(url, dest)
        ok = dest.is_file() and dest.stat().st_size > 5000
        print("  ->", "ok" if ok else "falhou")
        return ok
    except Exception as e:
        print(f"  ERRO: {e}")
        return False


def main() -> int:
    ok_all = True
    for path, url in URLS.items():
        if not download(url, path):
            ok_all = False
    yunet = MODELS / "face_detection_yunet_2023mar.onnx"
    if not yunet.is_file():
        print("YuNet: sera baixado automaticamente no primeiro uso (OpenCV zoo).")
    print()
    print("Engajamento por emocao: pip install tf-keras")
    print("  ou: pip install -r requirements-emotion.txt")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
