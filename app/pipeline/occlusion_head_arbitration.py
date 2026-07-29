"""
Arbitragem oclusão facial vs cabeça baixa.

Fundamento (não tuning aleatório):
- MediaPipe Face Landmarker NÃO expõe visibility/presence confiável para oclusão
  (issues google-ai-edge/mediapipe #3972, #4484, #5450).
- DMS / DashSentinel: visibility gates — se olhos/landmarks não são observáveis,
  NÃO emitir drowsiness/head-down; marcar inconclusivo.
- Fusão por confiança: modalidade oclusão (punho perto do rosto) tem prioridade
  sobre pitch facial quando o rosto está tampado; pitch só vale com qualidade
  mínima de landmarks.
- "Rosto sumiu" sozinho NÃO é proxy de cabeça baixa (pode ser mão, objeto,
  saída de enquadramento, yaw extremo).

Prioridade:
  1) oclusão por punho confirmada → suppress head_down
  2) face não observável sem evidência geométrica → inconclusivo
  3) cabeça baixa só com pitch confiável OU geometria corporal (nariz+ombros)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


OCCLUDED_STATES = (
    "possible_face_occlusion_by_hand",
    "persistent_possible_face_occlusion",
)
HEAD_DOWN_STATES = (
    "head_down_short",
    "head_down_persistent",
    "head_supported",
)


@dataclass
class ArbitrationResult:
    head_state: Dict[str, Any]
    face_occlusion: Dict[str, Any]
    suppressed_head_down: bool = False
    decision: str = "unchanged"
    reasons: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []


def _occ_has_wrist(face_occlusion: Dict[str, Any]) -> bool:
    reasons = list((face_occlusion or {}).get("reasons") or [])
    state = str((face_occlusion or {}).get("state") or "none")
    if any("wrist" in str(r) for r in reasons):
        return True
    # Estado de oclusão com mãos near_face sem reason explícita ainda conta
    return state in OCCLUDED_STATES and any("occlus" in str(r) for r in reasons)


def _landmarks_trustworthy(
    facial_features: Dict[str, Any],
    *,
    min_quality: float,
) -> bool:
    ff = facial_features or {}
    if ff.get("status") != "available":
        return False
    lq = float(ff.get("landmarks_quality") or 0.0)
    return lq >= float(min_quality)


def resolve_occlusion_vs_head_down(
    *,
    face_visible: bool,
    head_state: Dict[str, Any],
    face_occlusion: Dict[str, Any],
    facial_features: Optional[Dict[str, Any]] = None,
    hands: Optional[Dict[str, Any]] = None,
    body_head_geom: bool = False,
    now: float,
    head_down_since: Optional[float] = None,
    head_down_accum_seconds: float = 0.0,
    short_to_persistent_seconds: float = 8.0,
    require_landmarks_quality: float = 0.45,
    suppress_when_occlusion: bool = True,
    allow_face_missing_proxy: bool = False,
) -> ArbitrationResult:
    """
    Única porta de decisão entre oclusão e cabeça baixa.

    body_head_geom: True se pose corporal (nariz+ombros) indica look-down
    no frame atual — não confundir com face mesh ausente.
    """
    hs = dict(head_state or {})
    occ = dict(face_occlusion or {})
    hands_d = dict(hands or {})
    ff = facial_features or {}
    reasons: List[str] = []

    occ_state = str(occ.get("state") or "none")
    hand_near = str(hands_d.get("state") or "") == "hand_near_face"
    wrist_occ = _occ_has_wrist(occ) or (hand_near and occ_state in OCCLUDED_STATES)
    # Punho perto + face sumiu: tratar como oclusão mesmo se state ainda pending
    if hand_near and not face_visible:
        wrist_occ = True
        if occ_state not in OCCLUDED_STATES:
            occ = {
                "state": "possible_face_occlusion_by_hand",
                "confidence": max(0.4, float(occ.get("confidence") or 0.0)),
                "reasons": list(occ.get("reasons") or []) + ["wrist_near_while_face_missing"],
                "duration_seconds": occ.get("duration_seconds"),
                "note": "occlusion_priority_over_head_down",
            }
            occ_state = occ["state"]

    # --- 1) Oclusão por punho ganha ---
    if suppress_when_occlusion and wrist_occ and occ_state in OCCLUDED_STATES:
        reasons.append("priority_occlusion_over_head_down")
        # head_supported com mão na cara ≈ oclusão, não evento de cabeça baixa
        prev = str(hs.get("state") or "")
        if prev in HEAD_DOWN_STATES or prev == "pose_inconclusive":
            hs = {
                **hs,
                "state": "pose_inconclusive",
                "confidence": min(float(hs.get("confidence") or 0.0), 0.35),
                "reasons": list(hs.get("reasons") or [])
                + ["suppressed_by_face_occlusion"],
                "note": "occlusion_priority",
            }
        return ArbitrationResult(
            head_state=hs,
            face_occlusion=occ,
            suppressed_head_down=True,
            decision="occlusion_wins",
            reasons=reasons,
        )

    # --- 2) Face não observável sem punho ---
    if not face_visible and not wrist_occ:
        # Sem proxy: só mantém head_down se geometria corporal confirma
        if body_head_geom:
            since = head_down_since if head_down_since is not None else now
            dur = max(float(head_down_accum_seconds or 0.0), now - float(since))
            new_state = (
                "head_down_persistent"
                if dur >= float(short_to_persistent_seconds)
                else "head_down_short"
            )
            prev_reasons = list(hs.get("reasons") or [])
            if "body_geom_look_down" not in prev_reasons:
                prev_reasons = prev_reasons + ["body_geom_look_down"]
            hs = {
                **hs,
                "state": new_state,
                "confidence": max(0.55, float(hs.get("confidence") or 0.0)),
                "reasons": prev_reasons,
                "duration_seconds": round(dur, 2),
                "note": "head_down_from_body_geom",
            }
            # Limpa oclusão genérica sem punho
            if occ_state in OCCLUDED_STATES and not _occ_has_wrist(occ):
                occ = {
                    "state": "none",
                    "confidence": 0.0,
                    "reasons": ["cleared_prefer_body_head_down"],
                }
            return ArbitrationResult(
                head_state=hs,
                face_occlusion=occ,
                suppressed_head_down=False,
                decision="head_down_body_geom",
                reasons=reasons + ["body_geom_while_face_missing"],
            )

        if allow_face_missing_proxy:
            # Legado / opt-in — desligado por padrão (gera FP com mão na cara)
            since = head_down_since if head_down_since is not None else now
            dur = max(float(head_down_accum_seconds or 0.0), now - float(since))
            new_state = (
                "head_down_persistent"
                if dur >= float(short_to_persistent_seconds)
                else "head_down_short"
            )
            prev_reasons = list(hs.get("reasons") or [])
            if "face_missing_look_down_proxy" not in prev_reasons:
                prev_reasons = prev_reasons + ["face_missing_look_down_proxy"]
            hs = {
                **hs,
                "state": new_state,
                "confidence": max(0.45, float(hs.get("confidence") or 0.0)),
                "reasons": prev_reasons,
                "duration_seconds": round(dur, 2),
                "note": "legacy_face_missing_proxy",
            }
            return ArbitrationResult(
                head_state=hs,
                face_occlusion=occ if _occ_has_wrist(occ) else {
                    "state": "none",
                    "confidence": 0.0,
                    "reasons": ["cleared_prefer_head_down_proxy"],
                },
                decision="legacy_face_missing_proxy",
                reasons=reasons,
            )

        # Default: inconclusivo — não inventar cabeça baixa
        if occ_state in OCCLUDED_STATES and not _occ_has_wrist(occ):
            occ = {
                "state": "none",
                "confidence": 0.0,
                "reasons": ["cleared_face_missing_without_wrist"],
                "note": "observation_inconclusive",
            }
        prev = str(hs.get("state") or "")
        if prev in HEAD_DOWN_STATES and "body_geom_look_down" not in list(hs.get("reasons") or []):
            # Só limpa se veio de proxy / pitch sem geom
            if any(
                x in list(hs.get("reasons") or [])
                for x in ("face_missing_look_down_proxy", "facial_pitch=")
            ) or prev.startswith("head_down"):
                # Mantém se já tinha body geom; senão demote
                if "body_geom_look_down" not in list(hs.get("reasons") or []) and not any(
                    str(r).startswith("nose_shoulder") for r in (hs.get("reasons") or [])
                ):
                    hs = {
                        **hs,
                        "state": "pose_inconclusive",
                        "confidence": 0.25,
                        "reasons": list(hs.get("reasons") or [])
                        + ["face_missing_inconclusive_not_head_down"],
                        "note": "visibility_gate",
                    }
        elif prev not in HEAD_DOWN_STATES:
            hs = {
                **hs,
                "state": "pose_inconclusive",
                "confidence": min(float(hs.get("confidence") or 0.3), 0.3),
                "reasons": list(hs.get("reasons") or []) + ["face_not_observable"],
                "note": "visibility_gate",
            }
        return ArbitrationResult(
            head_state=hs,
            face_occlusion=occ,
            suppressed_head_down=False,
            decision="inconclusive_face_missing",
            reasons=reasons + ["visibility_gate_no_proxy"],
        )

    # --- 3) Face visível: pitch só com landmarks confiáveis ---
    if face_visible:
        pitch = ff.get("pitch")
        if pitch is not None and _landmarks_trustworthy(
            ff, min_quality=require_landmarks_quality
        ):
            # Caller aplica threshold; aqui só valida confiança
            reasons.append("pitch_landmarks_ok")
        elif pitch is not None:
            reasons.append("pitch_gated_low_landmarks_quality")
            # Se head_down veio só de pitch ruim, demote
            prev_reasons = list(hs.get("reasons") or [])
            if any(str(r).startswith("facial_pitch=") for r in prev_reasons) and not body_head_geom:
                if str(hs.get("state") or "") in HEAD_DOWN_STATES:
                    hs = {
                        **hs,
                        "state": "pose_inconclusive",
                        "confidence": 0.3,
                        "reasons": prev_reasons + ["pitch_untrusted_landmarks"],
                    }
                    return ArbitrationResult(
                        head_state=hs,
                        face_occlusion=occ,
                        suppressed_head_down=True,
                        decision="pitch_gated",
                        reasons=reasons,
                    )

    return ArbitrationResult(
        head_state=hs,
        face_occlusion=occ,
        suppressed_head_down=False,
        decision="unchanged",
        reasons=reasons,
    )


def pitch_may_promote_head_down(
    facial_features: Dict[str, Any],
    *,
    pitch_threshold: float,
    require_landmarks_quality: float,
) -> bool:
    """True se pitch facial é confiável e acima do limiar."""
    ff = facial_features or {}
    if not _landmarks_trustworthy(ff, min_quality=require_landmarks_quality):
        return False
    pitch = ff.get("pitch")
    if pitch is None:
        return False
    return float(pitch) > float(pitch_threshold)
