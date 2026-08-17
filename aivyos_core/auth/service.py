"""认证服务编排（文档 §9 专属认证：声纹 + 面部 + 活体 + 状态机）。

流程（§9.1）：待机监听 → 声纹采集 → 声纹比对(>0.75) → 面部验证(>0.6，可选)
→ 活体检测 → 认证通过/拒绝（失败静默忽略，不暴露系统存在）。
多用户（T6.7）：每个用户独立声纹模板 + 人格配置。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from aivyos_core.auth.face import FaceAuth
from aivyos_core.auth.liveness import LivenessChecker
from aivyos_core.auth.state_machine import AuthState, AuthStateMachine
from aivyos_core.auth.voiceprint import VoiceprintAuth
from aivyos_core.config import ensure_home

log = logging.getLogger(__name__)


@dataclass
class AuthResult:
    accepted: bool
    user_id: Optional[str] = None
    voice_score: float = 0.0
    face_score: float = 0.0
    liveness_ok: bool = False
    state: str = "dormant"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "user_id": self.user_id,
            "voice_score": round(self.voice_score, 3),
            "face_score": round(self.face_score, 3),
            "liveness_ok": self.liveness_ok,
            "state": self.state,
            "reason": self.reason,
        }


class AuthService:
    def __init__(self, config: Dict[str, Any], home: Optional[Path] = None) -> None:
        self.config = config.get("auth", {})
        self.home = ensure_home(config) if home is None else home
        users_dir = self.home / self.config.get("users_dir", "users")

        self.voice = VoiceprintAuth(
            users_dir=users_dir,
            threshold=float(self.config.get("voice_threshold", 0.75)),
            extractor=self.config.get("voice_backend", "auto"),
            min_enroll_seconds=float(self.config.get("min_enroll_seconds", 3.0)),
        )
        self.face = FaceAuth(
            users_dir=users_dir,
            threshold=float(self.config.get("face_threshold", 0.6)),
            backend=self.config.get("face_backend", "auto"),
        )
        self.liveness = LivenessChecker()
        self.sm = AuthStateMachine(
            silent_reject=bool(self.config.get("silent_reject", True)),
        )
        self.enabled = bool(self.config.get("enabled", False))
        self.liveness_enabled = bool(self.config.get("liveness_enabled", True))

    # ---- 注册（T6.7 多用户：独立模板 + 人格）----

    def register(
        self,
        name: str,
        pcm: Optional[bytes] = None,
        image: Optional[bytes] = None,
        persona: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if pcm is None and image is None:
            raise ValueError("至少提供 pcm（声纹）或 image（面部）之一")
        profile = None
        if pcm is not None:
            profile = self.voice.register(name, pcm, persona=persona)
        if image is not None:
            uid = profile.user_id if profile else f"user_{len(self.voice.list_users())}"
            self.face.register(uid, image)
        return {
            "user_id": profile.user_id if profile else uid,
            "name": name,
            "voice_templates": len(profile.templates) if profile else 0,
            "face_backend": self.face.backend_name,
        }

    # ---- 认证（§9.1 六步流程）----

    async def authenticate(self, pcm: Optional[bytes] = None, image: Optional[bytes] = None) -> AuthResult:
        self.sm.wake()          # 1) 待机监听
        self.sm.start_verify()  # 2) 进入认证中

        # 3-4) 声纹比对（阈值 0.75）
        voice_user, voice_score = None, 0.0
        if pcm is not None:
            voice_user, voice_score = self.voice.verify(pcm)

        # 活体检测（§9.1 步骤 5）
        liveness_ok = True
        if self.liveness_enabled and pcm is not None:
            liveness_ok, _ = self.liveness.check_audio(pcm)

        # 面部验证（可选，§9.1 步骤 4）
        face_user, face_score = None, 0.0
        if image is not None:
            face_user, face_score = self.face.verify(image)

        # 判定：声纹为主，面部为辅助确认
        if voice_user is None:
            self.sm.reject(score=voice_score, reason="声纹未匹配")
            return AuthResult(False, state=self.sm.state.value, voice_score=voice_score,
                              face_score=face_score, liveness_ok=liveness_ok, reason="声纹未匹配")
        if image is not None and face_user is not None and face_user != voice_user:
            self.sm.reject(score=voice_score, reason="声纹与面部用户不一致")
            return AuthResult(False, state=self.sm.state.value, voice_score=voice_score,
                              face_score=face_score, liveness_ok=liveness_ok, reason="声纹与面部用户不一致")
        if not liveness_ok:
            self.sm.reject(score=voice_score, reason="活体检测未通过")
            return AuthResult(False, state=self.sm.state.value, voice_score=voice_score,
                              face_score=face_score, liveness_ok=False, reason="活体检测未通过")

        self.sm.accept(voice_user, voice_score)
        return AuthResult(True, user_id=voice_user, voice_score=voice_score,
                          face_score=face_score, liveness_ok=True, state=self.sm.state.value)

    def get_user_persona(self, user_id: str) -> Dict[str, Any]:
        """按用户返回人格配置（T6.7：不同用户不同人格）。"""
        from aivyos_core.auth.voiceprint import UserProfile

        p = self.home / self.config.get("users_dir", "users") / f"{user_id}.json"
        if p.exists():
            import json

            return UserProfile.from_dict(json.loads(p.read_text(encoding="utf-8"))).persona
        return {}

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "voice_backend": self.voice.extractor_name,
            "face_backend": self.face.backend_name,
            "voice_threshold": self.voice.threshold,
            "face_threshold": self.face.threshold,
            "users": self.voice.list_users(),
            "state_machine": self.sm.status(),
        }
