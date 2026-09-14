"""Worker assíncrono de emoção (HSEmotion VGAF — default 2026-09-09).

Arquitetura:
  loop principal → enqueue(crop) → worker thread → HSEmotion → cache por track
  loop principal lê último resultado sem bloquear.

Cadência padrão: 2.0s por track (cache_stale).
Evita duplicar jobs inflight. Round-robin se muitos tracks vencidos.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EmotionCacheEntry:
    track_id: str
    last_emotion: Optional[str] = None  # normalized: positive|neutral|negative|inconclusive
    raw_label: Optional[str] = None
    confidence: float = 0.0
    last_update: float = -1e9
    inflight: bool = False
    inference_ms: float = 0.0
    error: Optional[str] = None
    history: Deque[str] = field(default_factory=lambda: deque(maxlen=8))


@dataclass
class _Job:
    track_id: str
    crop: np.ndarray
    enqueued_at: float


class AsyncEmotionWorker:
    def __init__(
        self,
        provider,
        *,
        interval_seconds: float = 2.0,
        max_batch: int = 5,
        queue_size: int = 64,
    ) -> None:
        self.provider = provider
        self.interval_seconds = float(interval_seconds)
        self.max_batch = max(1, int(max_batch))
        self._q: queue.Queue = queue.Queue(maxsize=queue_size)
        self._cache: Dict[str, EmotionCacheEntry] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stats = {
            "enqueued": 0,
            "dropped_inflight": 0,
            "dropped_fresh": 0,
            "dropped_full": 0,
            "completed": 0,
            "errors": 0,
            "queue_peak": 0,
            "latency_ms": deque(maxlen=200),
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="emotion-async-worker", daemon=True
        )
        self._thread.start()
        logger.info(
            "emotion_async_worker_started",
            interval_s=self.interval_seconds,
            provider=getattr(self.provider, "provider_name", None),
            model=getattr(self.provider, "model_name", None),
        )

    def shutdown(self, timeout: float = 2.0) -> None:
        self._stop.set()
        try:
            self._q.put_nowait(None)  # type: ignore
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("emotion_async_worker_stopped", stats=self.stats_snapshot())

    def stats_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            lat = list(self._stats["latency_ms"])
            return {
                "enqueued": self._stats["enqueued"],
                "dropped_inflight": self._stats["dropped_inflight"],
                "dropped_fresh": self._stats["dropped_fresh"],
                "dropped_full": self._stats["dropped_full"],
                "completed": self._stats["completed"],
                "errors": self._stats["errors"],
                "queue_size": self._q.qsize(),
                "queue_peak": self._stats["queue_peak"],
                "latency_ms_mean": round(float(np.mean(lat)), 2) if lat else None,
                "latency_ms_max": round(float(np.max(lat)), 2) if lat else None,
                "tracks": len(self._cache),
            }

    def _entry(self, track_id: str) -> EmotionCacheEntry:
        if track_id not in self._cache:
            self._cache[track_id] = EmotionCacheEntry(track_id=track_id)
        return self._cache[track_id]

    def maybe_submit(self, track_id: str, crop: Optional[np.ndarray], now: float) -> bool:
        """Enfileira se cache vencido e sem inflight. Nunca bloqueia."""
        if crop is None or getattr(crop, "size", 0) == 0:
            return False
        with self._lock:
            st = self._entry(track_id)
            if st.inflight:
                self._stats["dropped_inflight"] += 1
                return False
            # Relógio do pipeline pode reiniciar (vídeo offline) — trata rewind como stale.
            age = now - st.last_update
            fresh = (
                st.last_emotion is not None
                and age >= 0.0
                and age < self.interval_seconds
            )
            if fresh:
                self._stats["dropped_fresh"] += 1
                return False
            st.inflight = True
            try:
                # cópia para o worker (evita race com frame buffer)
                job = _Job(track_id=track_id, crop=np.copy(crop), enqueued_at=now)
                self._q.put_nowait(job)
                self._stats["enqueued"] += 1
                self._stats["queue_peak"] = max(self._stats["queue_peak"], self._q.qsize())
                return True
            except queue.Full:
                st.inflight = False
                self._stats["dropped_full"] += 1
                logger.warning("emotion_async_queue_full", track_id=track_id)
                return False

    def clear_track(self, track_id: str) -> None:
        """Remove cache de um track (útil em testes / troca de fonte offline)."""
        with self._lock:
            self._cache.pop(track_id, None)

    def reset_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def peek(self, track_id: str) -> EmotionCacheEntry:
        with self._lock:
            return self._entry(track_id)

    def _smooth_from_history(self, history: Deque[str]) -> Tuple[str, int]:
        """
        VGAF async: cada inferência ~2s. NÃO espelhar raw→smoothed 1:1 (gera flicker
        neutral↔negative ao vivo com cara estável).

        - positive: promove com 1 amostra (sorriso deve aparecer rápido)
        - negative: exige ~3 amostras seguidas (~6s @ 2s) — alinha EX− / negative_min_seconds
        - senão: maioria recente → predominantly_*; default neutro se misto
        """
        labs = [x for x in history if x in ("positive", "neutral", "negative")]
        n = len(labs)
        if n == 0:
            return "inconclusive", 0
        if labs[-1] == "positive":
            return "predominantly_positive", n
        trailing_neg = 0
        for lab in reversed(labs):
            if lab == "negative":
                trailing_neg += 1
            else:
                break
        # ~6s com interval 2.0s → 3 amostras negativas sustentadas
        need_neg = max(3, int(round(6.0 / max(self.interval_seconds, 0.5))))
        if trailing_neg >= need_neg:
            return "predominantly_negative", n
        window = labs[-min(4, n) :]
        from collections import Counter

        counts = Counter(window)
        # Empate / misto sem negativa sustentada → neutro (cara séria ≠ EX−)
        if counts.get("negative", 0) and counts["negative"] < need_neg:
            if counts.get("neutral", 0) >= counts.get("negative", 0) or trailing_neg < need_neg:
                if counts.get("positive", 0) > counts.get("neutral", 0):
                    return "predominantly_positive", n
                return "predominantly_neutral", n
        best, _ = counts.most_common(1)[0]
        return f"predominantly_{best}", n

    def build_expression_dict(self, track_id: str, now: float) -> Dict[str, Any]:
        """Resultado compatível com analytics (sem smile/frown boost; smooth via history)."""
        from app.vision.expressions.normalization import display_expression_pt

        with self._lock:
            st = self._entry(track_id)
            label = st.last_emotion
            conf = float(st.confidence)
            raw = st.raw_label
            age = now - st.last_update if st.last_update > 0 else None
            inflight = st.inflight
            err = st.error
            infer_ms = st.inference_ms
            hist = deque(st.history)

        if label is None:
            return {
                "provider": "hsemotion_vgaf",
                "model_name": getattr(self.provider, "model_name", "enet_b0_8_best_vgaf"),
                "backend": "hsemotion_vgaf",
                "raw_label": None,
                "normalized_state": "inconclusive",
                "confidence": 0.0,
                "smoothed_state": "inconclusive",
                "smoothed_display_pt": "inconclusivo",
                "is_conclusive": False,
                "status": "pending" if inflight else "waiting_first_inference",
                "inference_ms": 0.0,
                "sample_count": 0,
                "reason": "async_cache_empty",
                "emotion_cache_age_s": age,
                "inflight": inflight,
                "smile_boost": "none",
                "frown_boost": "none",
            }

        smoothed, sample_count = self._smooth_from_history(hist)
        # normalized_state = bucket atual (raw path); smoothed = janela
        norm = label if label in ("positive", "neutral", "negative") else "inconclusive"

        return {
            "provider": "hsemotion_vgaf",
            "model_name": getattr(self.provider, "model_name", "enet_b0_8_best_vgaf"),
            "backend": "hsemotion_vgaf",
            "raw_label": raw,
            "normalized_state": norm,
            "confidence": conf,
            "smoothed_state": smoothed,
            "smoothed_display_pt": display_expression_pt(smoothed),
            "is_conclusive": smoothed != "inconclusive",
            "status": "available" if not err else "degraded",
            "inference_ms": infer_ms,
            "sample_count": sample_count,
            "reason": err,
            "emotion_cache_age_s": None if age is None else round(age, 3),
            "inflight": inflight,
            "smile_boost": "none",
            "frown_boost": "none",
            "async_worker": True,
        }

    def _run(self) -> None:
        pending: List[_Job] = []
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.05)
            except queue.Empty:
                item = None
            if item is None and not pending:
                continue
            if item is None and self._stop.is_set():
                break
            if item is not None:
                pending.append(item)
            # drain até max_batch (round-robin / cache_stale controlado)
            while len(pending) < self.max_batch:
                try:
                    nxt = self._q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    self._stop.set()
                    break
                pending.append(nxt)
            if not pending:
                continue
            batch = pending[: self.max_batch]
            pending = pending[self.max_batch :]
            self._process_batch(batch)

    def _process_batch(self, jobs: List[_Job]) -> None:
        crops = [j.crop for j in jobs]
        t0 = time.perf_counter()
        try:
            preds = self.provider.predict_batch(crops)
        except Exception as e:
            logger.error("emotion_async_batch_failed", error=str(e))
            with self._lock:
                self._stats["errors"] += len(jobs)
                for j in jobs:
                    st = self._entry(j.track_id)
                    st.inflight = False
                    st.error = f"predict_failed:{e}"
            return
        elapsed = (time.perf_counter() - t0) * 1000.0
        per = elapsed / max(len(jobs), 1)
        with self._lock:
            for j, pred in zip(jobs, preds):
                st = self._entry(j.track_id)
                st.inflight = False
                st.inference_ms = float(getattr(pred, "inference_ms", per) or per)
                if pred is None or not getattr(pred, "is_conclusive", False):
                    # mantém último bom se existir
                    st.error = "inconclusive_prediction"
                    self._stats["errors"] += 1
                else:
                    label = str(getattr(pred, "label", "inconclusive") or "inconclusive")
                    st.last_emotion = label
                    st.raw_label = getattr(pred, "raw_label", None)
                    st.confidence = float(getattr(pred, "confidence", 0.0) or 0.0)
                    # usa o relógio do pipeline (pode ser tempo de vídeo offline)
                    st.last_update = float(j.enqueued_at)
                    st.history.append(label)
                    st.error = None
                    self._stats["completed"] += 1
                self._stats["latency_ms"].append(st.inference_ms)
