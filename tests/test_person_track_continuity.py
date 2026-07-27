"""Continuidade estável de person_track_id (independente de face/identidade)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.vision.person_track_continuity import StablePersonTrackManager
from app.vision.person_tracker import BboxPersonTrackerAdapter, create_person_tracker
from app.vision.tracking_types import PersonTrack


def _raw(tid: str, bbox, conf=0.8):
    n = datetime.now(timezone.utc)
    return PersonTrack(
        track_id=tid,
        camera_id="cam-web",
        first_seen_at=n,
        last_seen_at=n,
        bounding_box=bbox,
        tracking_confidence=conf,
        visible=True,
        raw_tracker_id=tid,
    )


def test_short_detection_gap_keeps_same_id():
    mgr = StablePersonTrackManager("cam-web", max_time_lost_seconds=8.0)
    t0 = mgr.update([_raw("bt-1", (100, 100, 120, 240))], now=1000.0)
    assert t0[0].track_id == "cam-web-person-001"
    # 1 ciclo sem detecção
    lost = mgr.update([], now=1000.5)
    assert len(lost) == 1
    assert lost[0].track_id == "cam-web-person-001"
    assert lost[0].tracking_state == "temporarily_lost"
    # volta com ID bruto diferente
    back = mgr.update([_raw("bt-9", (105, 102, 118, 238))], now=1001.0)
    assert len(back) == 1
    assert back[0].track_id == "cam-web-person-001"
    assert back[0].tracking_state == "reassociated"
    ev = [e["event_type"] for e in mgr.drain_events()]
    assert "track_lost" in ev
    assert "track_reassociated" in ev


def test_bbox_oscillation_same_id():
    mgr = StablePersonTrackManager("cam-web", max_time_lost_seconds=8.0)
    mgr.update([_raw("bt-1", (100, 100, 120, 240))], now=1.0)
    for i, bbox in enumerate(
        [
            (108, 95, 115, 245),
            (95, 110, 125, 235),
            (102, 98, 118, 242),
        ]
    ):
        out = mgr.update([_raw(f"bt-{i+2}", bbox)], now=2.0 + i)
        assert out[0].track_id == "cam-web-person-001"


def test_reassociation_by_iou():
    mgr = StablePersonTrackManager(
        "cam-web", max_time_lost_seconds=8.0, minimum_reassociation_iou=0.30
    )
    mgr.update([_raw("bt-1", (0, 0, 100, 200))], now=1.0)
    mgr.update([], now=1.5)
    out = mgr.update([_raw("bt-2", (10, 10, 100, 200))], now=2.0)  # IoU alto
    assert out[0].track_id == "cam-web-person-001"
    assert out[0].reassociation_score is not None


def test_reassociation_by_center_distance():
    mgr = StablePersonTrackManager(
        "cam-web",
        max_time_lost_seconds=8.0,
        minimum_reassociation_iou=0.90,  # IoU exigente
        maximum_center_distance_ratio=0.35,
    )
    mgr.update([_raw("bt-1", (100, 100, 120, 240))], now=1.0)
    mgr.update([], now=1.4)
    # deslocamento pequeno do centro, tamanho similar
    out = mgr.update([_raw("bt-2", (115, 105, 118, 235))], now=1.8)
    assert out[0].track_id == "cam-web-person-001"


def test_do_not_reassociate_different_person():
    mgr = StablePersonTrackManager("cam-web", max_time_lost_seconds=8.0)
    mgr.update([_raw("bt-1", (0, 0, 100, 200))], now=1.0)
    # pessoa longe no quadro
    out = mgr.update([_raw("bt-2", (500, 100, 100, 200))], now=1.2)
    ids = {t.track_id for t in out}
    assert "cam-web-person-001" in ids
    assert "cam-web-person-002" in ids


def test_no_parallel_track_while_lost_same_region():
    """Evidência manual pessoas:2 — não criar 002 se 001 ainda reclaimável."""
    mgr = StablePersonTrackManager("cam-web", max_time_lost_seconds=8.0)
    mgr.update([_raw("bt-1", (200, 100, 150, 300))], now=1000.0)
    lost = mgr.update([], now=1000.5)
    assert lost[0].tracking_state == "temporarily_lost"
    # detecção nova com ID bruto diferente e bbox deslocada (mão no rosto)
    out = mgr.update([_raw("bt-99", (230, 80, 140, 320))], now=1001.0)
    assert len(out) == 1
    assert out[0].track_id == "cam-web-person-001"
    assert out[0].tracking_state == "reassociated"
    assert not any(t.track_id.endswith("002") for t in out)


def test_occlusion_oscillation_no_second_id():
    """Simula oclusão longa: gaps + bbox muda, ID estável."""
    mgr = StablePersonTrackManager("cam-web", max_time_lost_seconds=8.0)
    mgr.update([_raw("bt-1", (300, 150, 200, 400))], now=1.0)
    bboxes = [
        (310, 140, 190, 410),
        (280, 160, 210, 390),
        (320, 130, 180, 420),
        (295, 155, 205, 395),
    ]
    t = 1.0
    for i, bb in enumerate(bboxes):
        t += 0.6
        if i % 2 == 0:
            mgr.update([], now=t)  # gap
            t += 0.4
        out = mgr.update([_raw(f"bt-{i+10}", bb)], now=t)
        assert len([x for x in out if x.tracking_state != "temporarily_lost"]) == 1
        assert out[0].track_id == "cam-web-person-001" or all(
            x.track_id == "cam-web-person-001" for x in out
        )


def test_expire_after_real_exit():
    mgr = StablePersonTrackManager("cam-web", max_time_lost_seconds=8.0)
    mgr.update([_raw("bt-1", (100, 100, 120, 240))], now=1000.0)
    still = mgr.update([], now=1004.0)
    assert still[0].tracking_state == "temporarily_lost"
    gone = mgr.update([], now=1009.0)
    assert gone == []
    ev = mgr.drain_events()
    assert any(e["event_type"] == "track_expired" for e in ev)
    # retorno após expiração → novo ID
    again = mgr.update([_raw("bt-3", (100, 100, 120, 240))], now=1010.0)
    assert again[0].track_id == "cam-web-person-002"


def test_identity_ttl_independent_of_person_track(monkeypatch):
    """Identidade expira; person_track_id permanece (engine + continuity)."""
    from app.vision.identity_binding import IdentityBindingEngine
    from app.vision.tracking_types import FaceTrack

    eng = IdentityBindingEngine(face_missing_ttl_seconds=12.0, minimum_new_identity_confidence=0.7)
    n = datetime.now(timezone.utc)
    person = PersonTrack("cam-web-person-001", "cam-web", n, n, (100, 100, 120, 240))
    face = FaceTrack("face-000", "cam-web", n, n, (120, 110, 40, 50))
    eng.update_continuity(
        now=1000.0,
        person_tracks=[person],
        face_tracks=[face],
        face_identities={"face-000": {"student_id": "p01", "confidence": 0.9, "margin": 0.2}},
    )
    # 20s sem face — identidade unknown; person track id inalterado
    st = eng.update_continuity(
        now=1020.0, person_tracks=[person], face_tracks=[], face_identities={}
    )["cam-web-person-001"]
    assert st.student_id is None
    assert st.source == "unknown"
    assert person.track_id == "cam-web-person-001"


def test_buffers_preserved_while_temporarily_lost():
    from app.pipeline.analytics_track import RealtimeAnalyticsEngine

    class S:
        module_expression_mode = "disabled"
        module_face_landmarks_mode = "disabled"
        module_pose_mode = "disabled"
        module_temporal_fusion_mode = "disabled"
        module_phone_mode = "disabled"
        phone_yolo_enabled = False
        pose_body_enabled = False
        analytics_quality_interval_seconds = 0.0
        analytics_landmarks_interval_seconds = 0.0
        expression_interval_seconds = 0.0
        visual_attention_interval_seconds = 0.0
        identity_face_missing_ttl_seconds = 12.0
        identity_minimum_new_confidence = 0.75
        identity_minimum_margin = 0.10
        identity_confirmations_before_switch = 3
        identity_switch_cooldown_seconds = 10.0
        identity_confidence_decay_per_second = 0.04

    eng = RealtimeAnalyticsEngine(S())
    import numpy as np

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    n = datetime.now(timezone.utc)
    p = PersonTrack(
        "cam-web-person-001",
        "cam-web",
        n,
        n,
        (200, 80, 120, 200),
        tracking_state="active",
        tracking_confidence=0.9,
    )
    eng.process_camera(
        camera_id="cam-web",
        frame=frame,
        matches=[],
        boxes=[],
        person_tracks=[p],
        now=100.0,
    )
    assert "cam-web-person-001" in eng._cache
    # temporarily_lost ainda presente na lista → buffer permanece
    p2 = PersonTrack(
        "cam-web-person-001",
        "cam-web",
        n,
        n,
        (200, 80, 120, 200),
        tracking_state="temporarily_lost",
        seconds_since_person_detection=2.0,
        tracking_confidence=0.9,
        visible=False,
    )
    eng.process_camera(
        camera_id="cam-web",
        frame=frame,
        matches=[],
        boxes=[],
        person_tracks=[p2],
        now=102.0,
    )
    assert "cam-web-person-001" in eng._cache


def test_bbox_fallback_empty_detections_no_tracks():
    ad = BboxPersonTrackerAdapter("cam")
    assert ad.update([], None, 0.0) == []


def test_facade_exposes_continuity_debug():
    fac = create_person_tracker("cam-web", prefer_bytetrack=False, ttl_seconds=8.0)
    # sem frame/dets → vazio
    assert fac.update([], None, 0.0) == []
    assert "tracker_backend" in fac.last_debug
