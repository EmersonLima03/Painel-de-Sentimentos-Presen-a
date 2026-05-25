#!/usr/bin/env python3
"""
Sessão de teste guiada para MVP 5 pessoas.
- Lista status /health e /cameras
- Orienta cadastro de p01..p05 (chama endpoint)
- Roda por X segundos e imprime resumo: check-ins por p0x, confidence média, faces_avg médio
NÃO salva fotos; usa apenas APIs existentes.
Uso: python scripts/run_test_session.py
"""
import time
import urllib.request
import json
import sys

BASE = "http://127.0.0.1:8000"


def get(path: str) -> dict:
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    print("=== Status inicial ===")
    try:
        health = get("/health")
        print("Health:", health.get("detector_backend"), health.get("embedder_backend"), "faiss=", health.get("faiss_enabled"))
        print("sqlite_path:", health.get("sqlite_path"), "supabase_enabled:", health.get("supabase_enabled"))
    except Exception as e:
        print("Erro ao obter /health:", e)
        sys.exit(1)
    try:
        cameras = get("/cameras")
        for c in cameras.get("cameras", []):
            print("Camera:", c.get("camera_id"), "connected=", c.get("is_connected"), "faces_last=", c.get("faces_detected_last"))
    except Exception as e:
        print("Erro ao obter /cameras:", e)

    print("\n=== Cadastro p01..p05 (enroll/webcam) ===")
    print("Cadastre cada pessoa quando solicitado (câmera ligada, rosto enquadrado).")
    for i in range(1, 6):
        sid = f"p{i:02d}"
        name = f"Pessoa {i:02d}"
        inp = input(f"Cadastrar {sid} ({name})? [s/n]: ").strip().lower()
        if inp != "s":
            continue
        try:
            r = post("/enroll/webcam", {"student_id": sid, "full_name": name, "camera_id": "cam-web", "num_frames": 5})
            print("  ", r.get("status"), "quality_score:", r.get("quality_score"), "frames_used:", r.get("frames_used"))
        except Exception as e:
            print("  Erro:", e)

    duration = 60
    try:
        d = input(f"\nRodar monitor por quantos segundos? [{duration}]: ").strip() or str(duration)
        duration = int(d)
    except ValueError:
        duration = 60

    print(f"\n=== Coletando eventos por {duration}s (deixe pessoas na câmera) ===")
    time.sleep(duration)

    print("\n=== Resumo ===")
    try:
        events = get("/events?event_type=attendance_checkin&limit=100")
        checkins = events.get("events", [])
        by_student = {}
        confs = []
        for ev in checkins:
            p = ev.get("payload") or {}
            sid = p.get("student_id")
            if sid and sid.startswith("p0"):
                by_student[sid] = by_student.get(sid, 0) + 1
                c = p.get("confidence")
                if c is not None:
                    confs.append(float(c))
        print("Check-ins por aluno:", by_student)
        if confs:
            print("Confidence média (check-ins):", round(sum(confs) / len(confs), 2))
    except Exception as e:
        print("Erro eventos check-in:", e)

    try:
        events = get("/events?event_type=engagement_window&limit=20")
        eng = events.get("events", [])
        faces_avgs = []
        for ev in eng:
            p = ev.get("payload") or {}
            fa = p.get("faces_detected_avg")
            if fa is not None:
                faces_avgs.append(float(fa))
        if faces_avgs:
            print("Faces_detected_avg (engagement, últimos):", round(sum(faces_avgs) / len(faces_avgs), 2))
    except Exception as e:
        print("Erro eventos engagement:", e)

    print("\nFim da sessão.")


if __name__ == "__main__":
    main()
