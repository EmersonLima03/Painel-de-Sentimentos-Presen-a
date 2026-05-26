"""Pipeline de analytics de engajamento."""

import json
import time
from typing import List, Dict, Optional
import numpy as np
import cv2

from app.vision.detector import FaceDetector
from app.vision.engagement import calculate_engagement_state, aggregate_engagement_window
from app.db.repo import EventRepository
from app.utils.ids import generate_event_id
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


class EngagementAnalytics:
    """Pipeline para cálculo de engajamento agregado."""
    
    def __init__(
        self,
        detector: FaceDetector,
        event_repo: EventRepository,
        camera_id: str,
        room_id: str,
        device_id: str,
        school_id: str,
        window_seconds: int = 10
    ):
        self.detector = detector
        self.event_repo = event_repo
        self.camera_id = camera_id
        self.room_id = room_id
        self.device_id = device_id
        self.school_id = school_id
        self.window_seconds = window_seconds
        
        # Buffer de estados e movimento para agregação
        self.state_buffer: List[str] = []
        self.motion_buffer: List[float] = []
        self._prev_gray: Optional[np.ndarray] = None
        self.window_start_time: Optional[float] = None
        self._window_frame_count: int = 0

    def _frame_motion(self, frame: np.ndarray) -> float:
        """Diferença absoluta média entre frame atual e anterior (aprox. movimento)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        if gray.size == 0:
            return 0.0
        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray.copy()
            return 0.0
        diff = np.abs(gray.astype(np.float32) - self._prev_gray.astype(np.float32))
        self._prev_gray = gray.copy()
        return float(np.mean(diff))

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        face_count: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Processa frame para analytics de engajamento.

        Se face_count vier do orchestrator (cache YuNet), evita segunda detecção no mesmo frame.
        """
        current_time = time.time()

        if self.window_start_time is None:
            self.window_start_time = current_time

        motion = self._frame_motion(frame)
        self.motion_buffer.append(motion)

        if face_count is not None:
            n = max(0, int(face_count))
            if n > 0:
                self.state_buffer.extend(["neutral"] * n)
        else:
            faces = self.detector.detect(frame)
            states = []
            for (x, y, w, h) in faces:
                face_roi = frame[y : y + h, x : x + w]
                state = calculate_engagement_state(face_roi, (x, y, w, h))
                states.append(state)
            self.state_buffer.extend(states)

        self._window_frame_count += 1
        elapsed = current_time - self.window_start_time
        if elapsed >= self.window_seconds:
            num_frames = max(1, self._window_frame_count)
            num_faces_avg = len(self.state_buffer) / num_frames
            aggregated = aggregate_engagement_window(self.state_buffer, self.motion_buffer)
            aggregated["faces_detected_avg"] = num_faces_avg

            event = self._create_engagement_event(
                ts_start=int(self.window_start_time),
                ts_end=int(current_time),
                num_faces_avg=num_faces_avg,
                aggregated=aggregated
            )
            event_json = json.dumps(event)
            self.event_repo.create_event(
                event_id=event["event_id"],
                event_type="engagement_window",
                payload_json=event_json
            )
            activity_level = aggregated.get("activity_level", "low")
            engagement_index_avg = aggregated.get("engagement_index", 0.0)
            logger.info(
                "engagement_window",
                room_id=self.room_id,
                faces_avg=num_faces_avg,
                activity_level=activity_level,
                engagement_index_avg=engagement_index_avg,
            )
            self.state_buffer = []
            self.motion_buffer = []
            self._window_frame_count = 0
            self.window_start_time = current_time
            return event
        
        return None
    
    def _create_engagement_event(self, ts_start: int, ts_end: int, num_faces_avg: float, aggregated: Dict) -> dict:
        """Cria evento de janela de engajamento. engagement_index_avg é agregado (não emoção individual)."""
        return {
            "event_id": generate_event_id(),
            "event_type": "engagement_window",
            "school_id": self.school_id,
            "room_id": self.room_id,
            "device_id": self.device_id,
            "ts_start": ts_start,
            "ts_end": ts_end,
            "faces_detected_avg": round(num_faces_avg, 2),
            "engagement_index_avg": round(aggregated.get("engagement_index", 0.0), 2),
            "activity_level": aggregated.get("activity_level", "low"),
            "states_distribution": {
                "attentive": round(aggregated.get("attentive", 0.0), 2),
                "neutral": round(aggregated.get("neutral", 0.0), 2),
                "distracted": round(aggregated.get("distracted", 0.0), 2)
            },
            "model_version": "eng-v0"
        }
