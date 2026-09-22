#!/usr/bin/env python3
"""Servidor UI do POC M2 — Enrollment Guiado A.

Isolado: nao escreve face_embeddings de producao, nao altera app/vision.

  cd experiments/smoke_e2e_sentimentos/modulo2_poc
  ..\\..\\..\\venv\\Scripts\\python.exe scripts\\ui_server.py --port 8765

Abrir: http://127.0.0.1:8765/
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
ROOT = _SCRIPTS.parent
UI_DIR = ROOT / "ui"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from poc_common import (  # noqa: E402
    ALIGNMENT_MODE_PRODUCT,
    CAM_WEB,
    CROPS_ACTIVE,
    GALLERY_ACTIVE,
    RESULTS,
    AlignmentError,
    aligned_crop,
    detect_faces_yunet,
    embed_crop,
    ensure_dirs,
    estimate_face_yaw,
    load_gallery_facenet,
    match_gallery,
    open_webcam,
    pose_for_phase,
    quality_of_crop,
    select_primary_face,
)

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
except ImportError as e:
    print(json.dumps({"error": "fastapi/uvicorn necessarios no venv do projeto", "detail": str(e)}))
    sys.exit(1)

ensure_dirs()

app = FastAPI(title="M2 POC Enrollment", docs_url=None, redoc_url=None)
if UI_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


class Session:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cap = None
        self.webcam = int(CAM_WEB["index"])
        self.student_id = "lab01"
        self.student_name = "Pessoa de teste"
        self.min_quality = 0.55
        self.stable_needed = 18  # ~0.5–0.7s: hold tipo app de banco
        self.stable = 0
        self.phase = "idle"  # idle|front|lateral_right|lateral_left|validate|done|recognize|unknown|distance
        self.instruction = "Informe a pessoa e inicie a captura."
        self.status_human = "Aguardando"
        self.quality_label = "none"  # none|no_face|adjust|good|pose
        self.quality_score: Optional[float] = None
        self.face_px: Optional[list] = None
        self.frame_shape: Optional[list] = None
        self.camera_ok = False
        self.camera_error: Optional[str] = None
        self.samples: list[dict] = []
        self.last_match: Optional[dict] = None
        self.distance_m: Optional[float] = None
        self.distance_log: list[dict] = []
        self.overlay_box: Optional[list] = None
        self._frame: Optional[np.ndarray] = None
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self.force_third = False
        self.model_name = "FaceNet (POC)"
        self.gallery_path = str(GALLERY_ACTIVE)
        self.alignment_mode: Optional[str] = None
        self.alignment_error: Optional[str] = None
        self.threshold_exp = 0.70
        self.margin_exp = 0.10
        self.capture_flash_until = 0.0
        # Pose gate (yaw)
        self.yaw: Optional[float] = None
        self.pose_ok = False
        self.pose_hint = ""
        self.pose_bucket = ""
        self.pose_guide = "none"  # none|center|left|right
        self.turn_unlocked = False  # precisa sair da pose anterior antes da proxima
        self.validate_unlocked = False
        self._last_face: Optional[dict] = None
        self.n_faces_raw = 0
        self.face_score: Optional[float] = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            progress = [
                {"id": "front", "label": "Frente", "state": self._step_state("front")},
                {"id": "lateral_right", "label": "Direita", "state": self._step_state("lateral_right")},
                {"id": "lateral_left", "label": "Esquerda", "state": self._step_state("lateral_left")},
                {"id": "validate", "label": "Validação", "state": self._step_state("validate")},
            ]
            return {
                "phase": self.phase,
                "instruction": self.instruction,
                "status_human": self.status_human,
                "quality_label": self.quality_label,
                "quality_score": self.quality_score,
                "face_px": self.face_px,
                "frame_shape": self.frame_shape,
                "camera_ok": self.camera_ok,
                "camera_error": self.camera_error,
                "student_id": self.student_id,
                "student_name": self.student_name,
                "progress": progress,
                "samples": list(self.samples),
                "last_match": self.last_match,
                "distance_m": self.distance_m,
                "distance_log": list(self.distance_log),
                "gallery_temp": True,
                "gallery_path": self.gallery_path,
                "gallery_version": "facenet_aligned_v2",
                "alignment_mode": self.alignment_mode,
                "alignment_error": self.alignment_error,
                "model_name": self.model_name,
                "threshold_exp": self.threshold_exp,
                "margin_exp": self.margin_exp,
                "overlay_box": self.overlay_box,
                "capturing": time.time() < self.capture_flash_until,
                "n_ok_samples": len(self.samples),
                "product_db_written": False,
                "yaw": None if self.yaw is None else round(float(self.yaw), 3),
                "pose_ok": self.pose_ok,
                "pose_hint": self.pose_hint,
                "pose_bucket": self.pose_bucket,
                "pose_guide": self.pose_guide,
                "stable": self.stable,
                "stable_needed": self.stable_needed,
                "stable_pct": int(100 * min(1.0, self.stable / max(1, self.stable_needed))),
                "turn_unlocked": self.turn_unlocked,
                "n_faces_raw": self.n_faces_raw,
                "face_score": self.face_score,
            }

    def _step_state(self, step: str) -> str:
        done_ids = {s["step"] for s in self.samples}
        order = ["front", "lateral_right", "lateral_left", "validate"]
        if step not in order:
            return "pending"
        if step in done_ids or (step == "validate" and self.phase == "done"):
            return "done"
        if self.phase == step:
            return "active"
        # pending se etapas anteriores incompletas
        idx = order.index(step)
        for prev in order[:idx]:
            if prev not in done_ids:
                return "pending"
        return "pending"

    def set_phase(self, phase: str, instruction: str, status: str) -> None:
        self.phase = phase
        self.instruction = instruction
        self.status_human = status
        self.stable = 0
        if phase in ("lateral_right", "lateral_left", "validate"):
            self.turn_unlocked = False
        if phase == "validate":
            self.validate_unlocked = False
        if phase == "front":
            self.pose_guide = "center"
        elif phase == "lateral_right":
            self.pose_guide = "right"
        elif phase == "lateral_left":
            self.pose_guide = "left"
        elif phase == "validate":
            self.pose_guide = "center"
        else:
            self.pose_guide = "none"


S = Session()


def _save_sample(
    step: str,
    crop: np.ndarray,
    face: dict,
    q: float,
    label: str,
    align_meta: dict[str, Any],
    yaw: Optional[float] = None,
) -> None:
    import cv2

    mode = align_meta.get("alignment_mode")
    if mode != ALIGNMENT_MODE_PRODUCT:
        raise AlignmentError("not_product_alignment", f"got={mode}")

    out_dir = GALLERY_ACTIVE / S.student_id
    out_dir.mkdir(parents=True, exist_ok=True)
    crop_dir = CROPS_ACTIVE / S.student_id
    crop_dir.mkdir(parents=True, exist_ok=True)
    emb = embed_crop(crop)
    npy = out_dir / f"{step}.npy"
    jpg = crop_dir / f"{step}.jpg"
    np.save(npy, emb)
    cv2.imwrite(str(jpg), crop)
    sample = {
        "step": step,
        "quality": round(float(q), 4),
        "quality_label": label,
        "bbox_w": round(float(face["w"]), 1),
        "bbox_h": round(float(face["h"]), 1),
        "yaw": None if yaw is None else round(float(yaw), 4),
        "alignment_mode": mode,
        "align_bbox": align_meta.get("bbox"),
        "landmarks_ok": bool(align_meta.get("landmarks_ok")),
        "npy": str(npy),
        "crop": str(jpg),
        "ts": datetime.now(timezone.utc).isoformat(),
        "valid_for_product_fidelity": True,
    }
    S.samples.append(sample)
    S.capture_flash_until = time.time() + 1.2
    # persist session json (v2 — não sobrescreve enroll legado sem sufixo se já existir como evidência antiga)
    (RESULTS / f"enroll_ui_{S.student_id}_aligned_v2.json").write_text(
        json.dumps(
            {
                "student_id": S.student_id,
                "student_name": S.student_name,
                "gallery_version": "facenet_aligned_v2",
                "gallery_path": str(out_dir),
                "crops_path": str(crop_dir),
                "alignment_mode": ALIGNMENT_MODE_PRODUCT,
                "samples": S.samples,
                "n_captures": len(S.samples),
                "product_db_written": False,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _loop() -> None:
    import cv2

    while not S._stop:
        with S.lock:
            cap = S.cap
            phase = S.phase
        if cap is None or phase in ("idle", "done"):
            time.sleep(0.05)
            continue
        ok, frame = cap.read()
        if not ok or frame is None:
            with S.lock:
                S.camera_ok = False
                S.camera_error = "Falha ao ler frame"
            time.sleep(0.05)
            continue
        h, w = frame.shape[:2]
        try:
            faces = detect_faces_yunet(frame, score_th=0.72)
        except Exception as e:
            with S.lock:
                S.camera_error = str(e)
            time.sleep(0.1)
            continue

        with S.lock:
            S.camera_ok = True
            S.camera_error = None
            S.frame_shape = [h, w]
            S._frame = frame.copy()
            S.n_faces_raw = len(faces)
            prev = S._last_face

            def _pick(fs):
                return select_primary_face(fs, min_face_score=0.55, frame_shape=(h, w), prev=prev)

            if phase in ("recognize", "unknown", "distance"):
                f0 = _pick(faces) if faces else None
                if f0 is None:
                    S.overlay_box = None
                    S.quality_label = "no_face"
                    S.quality_score = None
                    S.face_px = None
                    S.yaw = None
                    S.face_score = None
                    S.alignment_mode = None
                    S.alignment_error = None
                    # nao limpa _last_face imediatamente — hysteresis curta
                else:
                    S._last_face = {k: f0[k] for k in ("x", "y", "w", "h", "face_score", "det_score") if k in f0}
                    S.overlay_box = [f0["x"], f0["y"], f0["w"], f0["h"]]
                    S.face_score = round(float(f0.get("face_score") or 0), 3)
                    try:
                        crop, align_meta = aligned_crop(frame, f0)
                        S.alignment_mode = align_meta.get("alignment_mode")
                        S.alignment_error = None
                        lab, q = quality_of_crop(crop)
                        S.quality_score = float(q)
                        S.quality_label = "good" if q >= S.min_quality and lab != "poor" else "adjust"
                    except AlignmentError as e:
                        S.alignment_mode = None
                        S.alignment_error = str(e)
                        S.quality_score = None
                        S.quality_label = "alignment_error"
                        S.status_human = f"Alignment falhou: {e.reason}"
                    S.face_px = [round(f0["w"], 1), round(f0["h"], 1)]
                    S.yaw = estimate_face_yaw(f0.get("landmarks") or [])
                continue

            if phase not in ("front", "lateral_right", "lateral_left", "validate"):
                continue

            face = _pick(faces) if faces else None
            if face is None:
                S.overlay_box = None
                S.quality_label = "no_face"
                S.quality_score = None
                S.face_px = None
                S.yaw = None
                S.face_score = None
                S.alignment_mode = None
                S.alignment_error = None
                S.pose_ok = False
                S.pose_hint = "Centralize o rosto na camera"
                S.stable = 0
                S.status_human = "Procurando rosto"
                continue
            S._last_face = {k: face[k] for k in ("x", "y", "w", "h", "face_score", "det_score") if k in face}
            S.face_score = round(float(face.get("face_score") or 0), 3)
            S.overlay_box = [face["x"], face["y"], face["w"], face["h"]]
            try:
                crop, align_meta = aligned_crop(frame, face)
                S.alignment_mode = align_meta.get("alignment_mode")
                S.alignment_error = None
            except AlignmentError as e:
                S.alignment_mode = None
                S.alignment_error = str(e)
                S.quality_label = "alignment_error"
                S.quality_score = None
                S.stable = 0
                S.status_human = f"Alignment falhou — captura rejeitada ({e.reason})"
                S.pose_ok = False
                continue
            lab, q = quality_of_crop(crop)
            S.quality_score = float(q)
            S.face_px = [round(face["w"], 1), round(face["h"], 1)]
            yaw = estimate_face_yaw(face.get("landmarks") or [])
            S.yaw = yaw
            pose = pose_for_phase(phase, yaw)
            S.pose_ok = bool(pose["ok"])
            S.pose_hint = str(pose["hint"])
            S.pose_bucket = str(pose["bucket"])
            S.pose_guide = str(pose.get("guide") or "none")

            # Transicao: precisa sair da pose anterior antes de aceitar a proxima
            if phase == "lateral_right" and not S.turn_unlocked:
                if yaw is not None and abs(float(yaw)) >= 0.22:
                    S.turn_unlocked = True
                    S.status_human = "Detectei a virada — continue ate ~45°"
                else:
                    S.quality_label = "pose"
                    S.stable = 0
                    S.status_human = "Siga a seta → vire para a SUA direita"
                    S.pose_hint = "Aguardando voce virar de verdade"
                    continue

            if phase == "lateral_left" and not S.turn_unlocked:
                # Depois da direita, volte perto do centro e depois vire a esquerda
                if yaw is not None and float(yaw) <= -0.22:
                    S.turn_unlocked = True
                    S.status_human = "Detectei a virada à esquerda — continue"
                elif yaw is not None and abs(float(yaw)) <= 0.20:
                    S.status_human = "Bom. Agora vire para a ESQUERDA"
                    S.quality_label = "pose"
                    S.stable = 0
                    continue
                else:
                    S.quality_label = "pose"
                    S.stable = 0
                    S.status_human = "Volte um pouco ao centro e depois vire à esquerda"
                    continue

            if phase == "validate" and not S.validate_unlocked:
                if yaw is not None and abs(float(yaw)) <= 0.22:
                    S.validate_unlocked = True
                else:
                    S.quality_label = "pose"
                    S.stable = 0
                    S.status_human = "Agora volte a olhar de frente"
                    continue

            quality_ok = q >= S.min_quality and lab != "poor"
            if not quality_ok:
                S.quality_label = "adjust"
                S.stable = 0
                S.status_human = "Aproxime-se / melhore a iluminacao"
                continue

            if not pose["ok"]:
                S.quality_label = "pose"
                S.stable = 0
                S.status_human = pose["hint"]
                continue

            if align_meta.get("alignment_mode") != ALIGNMENT_MODE_PRODUCT:
                S.quality_label = "alignment_error"
                S.stable = 0
                S.status_human = "Alignment não-produto — captura rejeitada"
                continue

            S.quality_label = "good"
            S.stable += 1
            S.status_human = f"{pose['hint']} ({S.stable}/{S.stable_needed})"
            if S.stable < S.stable_needed:
                continue

            step = phase
            S.status_human = "Capturando..."
            try:
                _save_sample(step, crop, face, q, lab, align_meta, yaw=yaw)
            except Exception as e:
                S.camera_error = f"Falha ao gerar embedding: {e}"
                S.stable = 0
                continue

            S.stable = 0
            if phase == "front":
                S.set_phase(
                    "lateral_right",
                    "Vire ~45° para a SUA direita e segure.",
                    "Aguardando virada à direita",
                )
            elif phase == "lateral_right":
                S.set_phase(
                    "lateral_left",
                    "Agora vire ~45° para a SUA esquerda e segure.",
                    "Aguardando virada à esquerda",
                )
            elif phase == "lateral_left":
                S.set_phase(
                    "validate",
                    "Otimo. Olhe de frente outra vez para validar.",
                    "Aguardando frente",
                )
            else:
                S.set_phase("done", "Cadastro de teste concluido.", "Concluido")
        time.sleep(0.03)


def _ensure_camera(webcam: int) -> None:
    if S.cap is not None:
        try:
            S.cap.release()
        except Exception:
            pass
        S.cap = None
    try:
        S.cap = open_webcam(int(webcam))
        S.webcam = int(webcam)
        S.camera_ok = True
        S.camera_error = None
    except Exception as e:
        S.camera_ok = False
        S.camera_error = str(e)
        S.cap = None
        raise


@app.get("/api/cameras")
def api_cameras(refresh: int = 0):
    """Lista cameras. Libera a sessao temporariamente para nao conflitar; nao troca o indice da UI."""
    from poc_common import list_webcam_indices

    force = bool(int(refresh or 0))
    held_index: Optional[int] = None
    was_ok = False
    with S.lock:
        if S.cap is not None:
            held_index = int(S.webcam)
            was_ok = bool(S.camera_ok)
            try:
                S.cap.release()
            except Exception:
                pass
            S.cap = None
            S.camera_ok = False

    try:
        cams = list_webcam_indices(force=force)
    finally:
        # Reabre a camera da sessao se havia uma ativa (evita LED apagar e ficar sem preview)
        if held_index is not None and was_ok and S.phase not in ("idle",):
            try:
                _ensure_camera(held_index)
            except Exception as e:
                S.camera_error = str(e)
                S.camera_ok = False

    # Preferir SEMPRE o indice do cam-web (USB XWF no config.yaml), nao a webcam do notebook
    from poc_common import CAM_WEB

    cfg_idx = int(CAM_WEB["index"])
    usable = [c for c in cams if c.get("has_image")]
    recommended = cfg_idx
    if not any(c["index"] == cfg_idx for c in cams):
        # fallback: maior resolucao com imagem
        usable_sorted = sorted(
            usable,
            key=lambda c: ((c.get("w") or 0) * (c.get("h") or 0), float(c.get("mean") or 0)),
            reverse=True,
        )
        recommended = usable_sorted[0]["index"] if usable_sorted else None
    hint = (
        f"USB cam-web (Debug Vision) = #{cfg_idx} @ {CAM_WEB['width']}x{CAM_WEB['height']}. "
        f"Nao use notebook (#0) nem Iriun (#1)."
        if recommended is not None
        else "Nenhuma camera com imagem util. Reconecte o USB e feche Zoom/Teams/OBS/Debug Vision."
    )
    return {
        "cameras": cams,
        "recommended": recommended,
        "cam_web": CAM_WEB,
        "active_session_webcam": held_index,
        "cached": not force,
        "hint": hint,
    }

@app.get("/")
def index():
    path = UI_DIR / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>UI ausente</h1>", status_code=500)
    return FileResponse(path)


@app.get("/api/state")
def api_state():
    return JSONResponse(S.snapshot())


@app.post("/api/session/start")
async def api_start(request: Request):
    body = await request.json()
    sid = str(body.get("student_id") or "lab01").strip() or "lab01"
    name = str(body.get("student_name") or "Pessoa de teste").strip()
    webcam = int(body.get("webcam", CAM_WEB["index"]))
    min_q = float(body.get("min_quality", 0.55))
    force_third = bool(body.get("force_third", False))
    with S.lock:
        S.student_id = sid
        S.student_name = name
        S.min_quality = min_q
        S.force_third = force_third
        S.samples = []
        S.last_match = None
        S.distance_log = []
        S.lateral_unlocked = False
        S.turn_unlocked = False
        S.validate_unlocked = False
        S.stable = 0
        S.yaw = None
        S.pose_ok = False
        S.pose_hint = ""
        S.pose_guide = "center"
        try:
            _ensure_camera(webcam)
        except Exception as e:
            S.set_phase("idle", "Camera indisponivel.", "Sem camera")
            return JSONResponse({"ok": False, "error": str(e), "state": S.snapshot()}, status_code=503)
        S.set_phase("front", "Olhe diretamente para a camera e segure ~1 segundo.", "Procurando rosto")
        if S._thread is None or not S._thread.is_alive():
            S._stop = False
            S._thread = threading.Thread(target=_loop, daemon=True)
            S._thread.start()
    return {"ok": True, "state": S.snapshot()}


@app.post("/api/session/stop")
async def api_stop():
    with S.lock:
        S.set_phase("idle", "Sessao encerrada.", "Aguardando")
        if S.cap is not None:
            try:
                S.cap.release()
            except Exception:
                pass
            S.cap = None
        S.camera_ok = False
    return {"ok": True, "state": S.snapshot()}


@app.post("/api/mode/{mode}")
async def api_mode(mode: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    with S.lock:
        if mode == "recognize":
            S.set_phase("recognize", "Posicione-se para o reconhecimento.", "Reconhecimento")
            S.distance_m = body.get("distance_m")
        elif mode == "unknown":
            S.set_phase("unknown", "Pessoa nao cadastrada: posicione-se na camera.", "Teste UNKNOWN")
        elif mode == "distance":
            S.distance_m = float(body.get("distance_m", 2))
            S.set_phase("distance", f"Teste de distancia: {S.distance_m} m", "Distancia")
        else:
            raise HTTPException(400, "mode invalido")
        if S.cap is None:
            try:
                _ensure_camera(int(body.get("webcam", S.webcam)))
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=503)
            if S._thread is None or not S._thread.is_alive():
                S._stop = False
                S._thread = threading.Thread(target=_loop, daemon=True)
                S._thread.start()
    return {"ok": True, "state": S.snapshot()}


@app.post("/api/match")
async def api_match(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    thr = float(body.get("threshold", S.threshold_exp))
    mar = float(body.get("margin", S.margin_exp))
    expected = str(body.get("expected") or "")
    with S.lock:
        frame = None if S._frame is None else S._frame.copy()
        distance_m = S.distance_m
        phase = S.phase
    if frame is None:
        return JSONResponse({"ok": False, "error": "Sem frame — inicie a camera"}, status_code=400)
    faces = detect_faces_yunet(frame, score_th=0.72)
    with S.lock:
        prev = S._last_face
        fh, fw = (S.frame_shape or [frame.shape[0], frame.shape[1]])[:2]
    face = select_primary_face(faces, min_face_score=0.55, frame_shape=(int(fh), int(fw)), prev=prev)
    if face is None:
        result = {
            "ok": True,
            "decision": "UNKNOWN",
            "reason": "no_face",
            "human": "Rosto nao detectado",
            "fail_test": False,
            "candidates": [],
            "n_faces_raw": len(faces),
        }
        with S.lock:
            S.last_match = result
        return result
    with S.lock:
        S._last_face = {k: face[k] for k in ("x", "y", "w", "h", "face_score", "det_score") if k in face}
    try:
        crop, align_meta = aligned_crop(frame, face)
    except AlignmentError as e:
        result = {
            "ok": False,
            "decision": "UNKNOWN",
            "reason": "alignment_error",
            "alignment_mode": None,
            "alignment_error": str(e),
            "human": f"Alignment falhou — match rejeitado ({e.reason})",
            "fail_test": False,
            "candidates": [],
            "n_faces_raw": len(faces),
        }
        with S.lock:
            S.last_match = result
            S.alignment_error = str(e)
            S.alignment_mode = None
        return result
    lab, q = quality_of_crop(crop)
    gallery = load_gallery_facenet()
    emb = embed_crop(crop)
    m = match_gallery(emb, gallery, thr, mar)
    decision = m["decision"]
    human = "IDENTIFICADO" if decision != "UNKNOWN" else "Pessoa nao cadastrada"
    fail = False
    if phase == "unknown" or expected.upper() == "UNKNOWN":
        fail = decision != "UNKNOWN"
        human = "UNKNOWN" if decision == "UNKNOWN" else "FALHA NO TESTE — identidade incorreta"
    elif expected and decision not in (expected, "UNKNOWN"):
        fail = True
        human = "FALHA NO TESTE — identidade incorreta"
    elif expected and decision == expected:
        human = f"Identidade reconhecida: {decision}"
    result = {
        "ok": True,
        "decision": decision,
        "human": human,
        "fail_test": fail,
        "quality": round(float(q), 4),
        "quality_label": lab,
        "bbox_w": round(face["w"], 1),
        "bbox_h": round(face["h"], 1),
        "face_score": round(float(face.get("face_score") or 0), 3),
        "det_score": round(float(face.get("det_score") or 0), 3),
        "n_faces_raw": len(faces),
        "top1_id": m.get("top1_id"),
        "top1_score": m.get("top1_score"),
        "margin": m.get("margin"),
        "distance_m": distance_m,
        "gallery_size": len(gallery),
        "gallery_path": str(GALLERY_ACTIVE),
        "alignment_mode": align_meta.get("alignment_mode"),
        "threshold_exp": thr,
        "margin_exp": mar,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with S.lock:
        S.last_match = result
        S.alignment_mode = align_meta.get("alignment_mode")
        S.alignment_error = None
        if phase == "distance" and distance_m is not None:
            row = {
                "distance_m": distance_m,
                "quality": result["quality"],
                "top1_score": result["top1_score"],
                "margin": result["margin"],
                "decision": decision,
                "alignment_mode": result["alignment_mode"],
                "ts": result["ts"],
            }
            S.distance_log.append(row)
            log_path = RESULTS / "ui_distance_log_aligned_v2.json"
            log_path.write_text(json.dumps(S.distance_log, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


@app.post("/api/match_all")
async def api_match_all(request: Request):
    """Match 1:N para TODAS as faces detectadas no frame (multi-pessoa POC)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    thr = float(body.get("threshold", S.threshold_exp))
    mar = float(body.get("margin", S.margin_exp))
    min_face_score = float(body.get("min_face_score", 0.55))
    with S.lock:
        frame = None if S._frame is None else S._frame.copy()
        distance_m = S.distance_m
        fh, fw = (S.frame_shape or [0, 0])[:2]
    if frame is None:
        return JSONResponse({"ok": False, "error": "Sem frame — inicie a camera"}, status_code=400)
    if not fh:
        fh, fw = frame.shape[:2]
    faces = detect_faces_yunet(frame, score_th=0.65)
    gallery = load_gallery_facenet()
    faces_out: list[dict[str, Any]] = []
    for i, face in enumerate(faces):
        entry: dict[str, Any] = {
            "idx": i,
            "bbox_w": round(float(face["w"]), 1),
            "bbox_h": round(float(face["h"]), 1),
            "x": round(float(face["x"]), 1),
            "y": round(float(face["y"]), 1),
            "face_score": round(float(face.get("face_score") or 0), 3),
            "det_score": round(float(face.get("det_score") or 0), 3),
        }
        if float(face.get("face_score") or 0) < min_face_score:
            entry["skipped"] = "low_face_score"
            entry["decision"] = None
            faces_out.append(entry)
            continue
        try:
            crop, align_meta = aligned_crop(frame, face)
        except AlignmentError as e:
            entry["alignment_error"] = str(e)
            entry["decision"] = "UNKNOWN"
            entry["valid_for_product_fidelity"] = False
            faces_out.append(entry)
            continue
        lab, q = quality_of_crop(crop)
        emb = embed_crop(crop)
        m = match_gallery(emb, gallery, thr, mar)
        entry.update(
            {
                "alignment_mode": align_meta.get("alignment_mode"),
                "quality": round(float(q), 4),
                "quality_label": lab,
                "top1_id": m.get("top1_id"),
                "top1_score": m.get("top1_score"),
                "margin": m.get("margin"),
                "decision": m.get("decision"),
                "raw": m.get("raw"),
                "valid_for_product_fidelity": True,
            }
        )
        faces_out.append(entry)

    ids = sorted({f["decision"] for f in faces_out if f.get("decision") and f["decision"] != "UNKNOWN"})
    result = {
        "ok": True,
        "n_faces_raw": len(faces),
        "n_faces_matched": sum(1 for f in faces_out if f.get("decision") is not None and not f.get("skipped")),
        "gallery_size": len(gallery),
        "gallery_students": sorted({sid for sid, _ in gallery}),
        "threshold_exp": thr,
        "margin_exp": mar,
        "distance_m": distance_m,
        "identified_ids": ids,
        "faces": faces_out,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with S.lock:
        S.last_match = {"mode": "match_all", **result}
    return result


def _mjpeg_generator():
    import cv2

    while True:
        with S.lock:
            frame = None if S._frame is None else S._frame.copy()
            box = S.overlay_box
            qlabel = S.quality_label
            capturing = time.time() < S.capture_flash_until
            camera_error = S.camera_error
            camera_ok = S.camera_ok
        if frame is None:
            # placeholder
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            msg = camera_error or ("Aguardando camera..." if not camera_ok else "Sem frame")
            cv2.putText(frame, msg[:80], (40, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        else:
            if box:
                x, y, w, h = map(int, box)
                color = (80, 200, 120) if qlabel == "good" else ((40, 160, 255) if qlabel == "adjust" else (80, 80, 220))
                if capturing:
                    color = (255, 255, 255)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 3)
            # soft guide oval center
            H, W = frame.shape[:2]
            cv2.ellipse(frame, (W // 2, H // 2), (W // 6, H // 3), 0, 0, 360, (255, 255, 255), 1)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            time.sleep(0.05)
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        time.sleep(0.05)


@app.get("/api/mjpeg")
def api_mjpeg():
    return StreamingResponse(_mjpeg_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    print(f"M2 POC UI: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
