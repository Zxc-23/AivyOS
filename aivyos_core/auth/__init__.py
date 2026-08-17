"""专属认证层（文档 §9）：声纹 / 面部 / 活体 / 状态机 / 多用户。"""

from aivyos_core.auth.face import FaceAuth, FaceUnavailable
from aivyos_core.auth.liveness import LivenessChecker
from aivyos_core.auth.service import AuthResult, AuthService
from aivyos_core.auth.state_machine import AuthState, AuthStateMachine
from aivyos_core.auth.voiceprint import (
    AuthUnavailable,
    UserProfile,
    VoiceprintAuth,
    cosine_similarity,
    extract_embedding,
)

__all__ = [
    "AuthService",
    "AuthResult",
    "AuthState",
    "AuthStateMachine",
    "VoiceprintAuth",
    "UserProfile",
    "FaceAuth",
    "FaceUnavailable",
    "LivenessChecker",
    "AuthUnavailable",
    "extract_embedding",
    "cosine_similarity",
]
