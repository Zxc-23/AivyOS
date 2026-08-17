"""声纹认证（文档 §9：专属认证 — AI 只认主人）。

- SimpleExtractor：零依赖频谱嵌入（Goertzel 频带能量 + ZCR + RMS → 10 维，L2 归一化）
- SpeechBrainExtractor：ECAPA-TDNN 192 维（speechbrain 可选；缺失自动降级 simple）
- VoiceprintAuth：注册（3-10s 纯净语音，多模板）/ 比对（余弦相似度，阈值 0.75，§9.2）
- 多用户：每个用户独立模板集 + 独立人格配置（T6.7）
"""

from __future__ import annotations

import json
import math
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 频带中心频率（Hz，对数间隔 100-4200；20 带提升区分度、降低音色碰撞）
BAND_HZ = [100, 122, 148, 180, 220, 267, 325, 396, 482, 587, 714, 870, 1059,
           1289, 1569, 1910, 2325, 2831, 3447, 4196]
EMBEDDING_DIM = len(BAND_HZ) + 2  # 20 频带 + ZCR + RMS


class AuthUnavailable(RuntimeError):
    """认证后端不可用（依赖缺失）。"""


def goertzel_mag(samples, sample_rate: int, freq: float) -> float:
    """Goertzel 算法计算指定频率幅度（零依赖 DFT 片段）。"""
    n = len(samples)
    if n == 0:
        return 0.0
    k = 0.5 + int(n * freq / sample_rate)
    omega = 2 * math.pi * k / n
    coeff = 2 * math.cos(omega)
    s0 = s1 = 0.0
    for x in samples:
        s2 = s1
        s1 = s0
        s0 = x + coeff * s1 - s2
    return math.sqrt(s1 * s1 + s2 * s2 - coeff * s1 * s2)


def extract_embedding(pcm: bytes, sample_rate: int = 16000, frame_ms: int = 30) -> List[float]:
    """零依赖声纹嵌入：逐帧（30ms）12 频带原始幅度 + ZCR + RMS 的帧平均。

    注意：不做帧级归一化/对数压缩（会洗平谱形差异），保留频带能量相对关系，
    使不同音色的嵌入方向明显分离；最后整体 L2 归一化。
    """
    frame = max(1, sample_rate * frame_ms // 1000)
    dim = EMBEDDING_DIM
    acc = [0.0] * dim
    count = 0
    for i in range(0, len(pcm) // 2 - frame + 1, frame):
        samples = struct.unpack(f"<{frame}h", pcm[i * 2 : (i + frame) * 2])
        for k, f in enumerate(BAND_HZ):
            acc[k] += goertzel_mag(samples, sample_rate, f)
        zcr = sum(1 for j in range(1, len(samples)) if (samples[j] >= 0) != (samples[j - 1] >= 0)) / frame
        acc[-2] += zcr
        acc[-1] += math.sqrt(sum(s * s for s in samples) / frame)
        count += 1
    if count == 0:
        return [0.0] * dim
    emb = [a / count for a in acc]
    norm = math.sqrt(sum(v * v for v in emb)) or 1.0
    return [v / norm for v in emb]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class SpeechBrainExtractor:
    """ECAPA-TDNN 192 维声纹（§9.2，speechbrain 可选）。"""

    name = "speechbrain-ecapa"
    dim = 192

    def __init__(self) -> None:
        try:
            from speechbrain.inference.speaker import EncoderClassifier  # type: ignore
            import torchaudio  # type: ignore
        except ImportError as e:
            raise AuthUnavailable(
                "speechbrain 未安装：pip install speechbrain torchaudio（见 requirements-ml.txt）。"
                "已降级到零依赖频谱声纹。"
            ) from e
        self.model = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cpu"})
        self.torchaudio = torchaudio

    def embed(self, pcm: bytes, sample_rate: int = 16000) -> List[float]:
        import numpy as np  # type: ignore
        import torch  # type: ignore

        audio = np.frombuffer(pcm, dtype="int16").astype("float32") / 32768.0
        emb = self.model.encode_batch(torch.from_numpy(audio).unsqueeze(0))
        return emb.squeeze().tolist()


@dataclass
class UserProfile:
    user_id: str
    name: str
    templates: List[List[float]] = field(default_factory=list)
    persona: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "templates": self.templates,
            "persona": self.persona,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UserProfile":
        return cls(
            user_id=d["user_id"], name=d["name"],
            templates=d.get("templates", []),
            persona=d.get("persona", {}),
            created_at=d.get("created_at", ""),
        )


class VoiceprintAuth:
    """声纹注册与比对（多用户、多模板）。"""

    def __init__(
        self,
        users_dir: str | Path,
        threshold: float = 0.75,
        extractor: str = "auto",
        min_enroll_seconds: float = 3.0,
    ) -> None:
        self.dir = Path(users_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.threshold = threshold
        self.min_enroll_seconds = min_enroll_seconds
        self.extractor_name = "simple-spectral"
        if extractor in ("speechbrain", "auto"):
            try:
                self._sb = SpeechBrainExtractor()
                self.extractor_name = "speechbrain-ecapa(192)"
            except AuthUnavailable:
                self._sb = None
        else:
            self._sb = None

    # ---- 嵌入 ----

    def embed(self, pcm: bytes, sample_rate: int = 16000) -> List[float]:
        if self._sb is not None:
            return self._sb.embed(pcm, sample_rate)
        return extract_embedding(pcm, sample_rate)

    # ---- 用户存储 ----

    def _path(self, user_id: str) -> Path:
        return self.dir / f"{user_id}.json"

    def _load(self, user_id: str) -> Optional[UserProfile]:
        p = self._path(user_id)
        if not p.exists():
            return None
        return UserProfile.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def _find_by_name(self, name: str) -> Optional[UserProfile]:
        """按名字查找已有用户（同名注册 → 追加模板，多模板语义）。"""
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if d.get("name") == name:
                return UserProfile.from_dict(d)
        return None

    def _save(self, profile: UserProfile) -> None:
        self._path(profile.user_id).write_text(
            json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_users(self) -> List[Dict[str, Any]]:
        out = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({"user_id": d["user_id"], "name": d["name"], "templates": len(d.get("templates", []))})
            except Exception:
                continue
        return out

    # ---- 注册（§9.1 步骤 2-3：采集样本 → 提取模板）----

    def register(
        self,
        name: str,
        pcm: bytes,
        sample_rate: int = 16000,
        persona: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> UserProfile:
        duration = len(pcm) / 2 / sample_rate
        if duration < self.min_enroll_seconds:
            raise ValueError(f"注册样本过短: {duration:.1f}s < {self.min_enroll_seconds}s（需 3-10 秒纯净语音）")
        uid = user_id
        if uid is None:
            existing = self._find_by_name(name)
            uid = existing.user_id if existing else ("user_" + uuid.uuid4().hex[:8])
        profile = self._load(uid) or UserProfile(user_id=uid, name=name)
        profile.name = name
        if persona:
            profile.persona = {**profile.persona, **persona}
        profile.templates.append(self.embed(pcm, sample_rate))
        self._save(profile)
        return profile

    # ---- 比对（§9.1 步骤 4：余弦相似度，阈值 0.75）----

    def verify(self, pcm: bytes, sample_rate: int = 16000) -> Tuple[Optional[str], float]:
        """返回 (最佳匹配 user_id 或 None, 最高相似度)。"""
        emb = self.embed(pcm, sample_rate)
        best_user: Optional[str] = None
        best_score = -1.0
        for p in self.dir.glob("*.json"):
            try:
                profile = UserProfile.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
            for tpl in profile.templates:
                score = cosine_similarity(emb, tpl)
                if score > best_score:
                    best_score = score
                    best_user = profile.user_id
        if best_score >= self.threshold:
            return best_user, best_score
        return None, best_score

    def clear_users(self) -> None:
        for p in self.dir.glob("*.json"):
            p.unlink()
