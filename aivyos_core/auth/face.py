"""面部认证（文档 §9.2：InsightFace Buffalo_L，512 维嵌入，阈值 0.6）。

- InsightFaceAuth：真实推理（insightface 可选；缺失抛 FaceUnavailable）
- MockFaceAuth：零依赖回退（注册记录图片哈希，比对哈希相等则通过，诚实标注 mock）
- FaceAuth：统一入口（auto → insightface 优先，缺失降级 mock）
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class FaceUnavailable(RuntimeError):
    pass


class MockFaceAuth:
    """mock：仅做图片哈希比对（不伪装真实人脸识别）。"""

    name = "mock-face"

    def __init__(self) -> None:
        self._enrolled: Dict[str, str] = {}  # user_id -> image hash

    def _hash(self, image: bytes) -> str:
        return hashlib.sha256(image).hexdigest()

    def register(self, user_id: str, image: bytes) -> None:
        self._enrolled[user_id] = self._hash(image)

    def verify(self, image: bytes) -> Tuple[Optional[str], float]:
        h = self._hash(image)
        for uid, enrolled_hash in self._enrolled.items():
            if h == enrolled_hash:
                return uid, 1.0
        return None, 0.0


class InsightFaceAuth:
    """InsightFace（Buffalo_L，512 维嵌入，§9.2）。"""

    name = "insightface-buffalo_l"
    dim = 512

    def __init__(self) -> None:
        try:
            import insightface  # type: ignore
        except ImportError as e:
            raise FaceUnavailable(
                "insightface 未安装：pip install insightface onnxruntime（见 requirements-ml.txt）。"
                "已降级到 mock 面部认证。"
            ) from e
        self.app = insightface.app.FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=0, det_size=(640, 640))

    def embed(self, image: bytes) -> Optional[list]:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        arr = np.frombuffer(image, dtype="uint8")
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        faces = self.app.get(img)
        if not faces:
            return None
        return faces[0].normed_embedding.tolist()

    def register(self, user_id: str, image: bytes) -> None:
        pass  # 真实推理下由 FaceAuth 负责存储嵌入

    def verify(self, image: bytes) -> Tuple[Optional[str], float]:
        return None, 0.0


class FaceAuth:
    """面部认证统一入口：注册（嵌入）/ 比对（余弦，阈值 0.6）。"""

    def __init__(self, users_dir: str | Path, threshold: float = 0.6, backend: str = "auto") -> None:
        self.dir = Path(users_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.threshold = threshold
        self.backend_name = "mock-face"
        if backend in ("insightface", "auto"):
            try:
                self._real = InsightFaceAuth()
                self.backend_name = "insightface-buffalo_l(512)"
            except FaceUnavailable:
                self._real = None
        else:
            self._real = None
        self._mock = MockFaceAuth()

    def _path(self, user_id: str) -> Path:
        return self.dir / f"face_{user_id}.json"

    def register(self, user_id: str, image: bytes) -> None:
        if self._real is not None:
            emb = self._real.embed(image)
            if emb is None:
                raise ValueError("图像中未检测到人脸")
            self._path(user_id).write_text(json.dumps({"user_id": user_id, "embedding": emb}), encoding="utf-8")
        else:
            self._mock.register(user_id, image)
            self._path(user_id).write_text(json.dumps({"user_id": user_id, "mock": True}), encoding="utf-8")

    def verify(self, image: bytes) -> Tuple[Optional[str], float]:
        if self._real is not None:
            emb = self._real.embed(image)
            if emb is None:
                return None, 0.0
            best_user, best_score = None, -1.0
            for p in self.dir.glob("face_*.json"):
                d = json.loads(p.read_text(encoding="utf-8"))
                if "embedding" not in d:
                    continue
                score = sum(a * b for a, b in zip(emb, d["embedding"]))
                if score > best_score:
                    best_score, best_user = score, d["user_id"]
            if best_score >= self.threshold:
                return best_user, best_score
            return None, best_score
        return self._mock.verify(image)

    def clear(self) -> None:
        for p in self.dir.glob("face_*.json"):
            p.unlink()
        self._mock._enrolled.clear()
