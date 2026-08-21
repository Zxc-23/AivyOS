"""图像内容理解（文档 §3.3：Qwen2-VL 可选 + mock 回退）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class UnderstandUnavailable(RuntimeError):
    pass


class UnderstandBackend(ABC):
    name: str = "base"

    @abstractmethod
    def describe(self, image: bytes) -> str:
        raise NotImplementedError


class MockUnderstand(UnderstandBackend):
    """mock 回退：诚实标注，不伪装视觉理解。"""

    name = "mock-vision"

    def describe(self, image: bytes) -> str:
        if not image:
            return ""
        return "（mock 视觉理解）图像内容描述占位，接入 Qwen2-VL/本地多模态模型后返回真实描述"


class QwenVLBackend(UnderstandBackend):
    """Qwen2-VL 本地视觉理解（通过 OpenAI 兼容多模态端点，可选配置）。"""

    name = "qwen2-vl"

    def __init__(self, base_url: str, model: str = "qwen2-vl-7b", api_key: Optional[str] = None) -> None:
        import base64

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._b64 = base64

    def describe(self, image: bytes) -> str:
        import json
        import urllib.request

        data_url = f"data:image/png;base64,{self._b64.b64encode(image).decode()}"
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": "请描述这张图片的内容"},
                    ],
                }
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
        return payload["choices"][0]["message"]["content"]


def create_understand(cfg: Dict[str, Any]) -> UnderstandBackend:
    backend = cfg.get("understand_backend", "auto")
    if backend == "mock":
        return MockUnderstand()
    if backend in ("qwen2-vl", "auto"):
        base_url = cfg.get("base_url") or cfg.get("local_base_url")
        if base_url:
            model = cfg.get("model", "qwen2-vl-7b")
            # 真实可用性探测：确认端点可达且模型存在（否则回退 mock，避免假阳性）
            real_model = _probe_vision_model(base_url, model)
            if real_model:
                # 使用探测到的真实模型 id（如 qwen2.5vl:7b-q4_K_M），避免配置名不匹配导致 404
                return QwenVLBackend(base_url, model=real_model)
            import logging

            logging.getLogger(__name__).warning(
                "视觉理解模型 %s 不可用（端点 %s），回退 mock", model, base_url
            )
            return MockUnderstand()
        return MockUnderstand()
    return MockUnderstand()


def _probe_vision_model(base_url: str, model: str) -> Optional[str]:
    """探测 OpenAI 兼容端点是否可访问且模型存在（GET /models）。

    返回实际匹配的模型 id（如配置 qwen2.5vl:7b 命中 qwen2.5vl:7b-q4_K_M）；
    不可用返回 None。
    Ollama /v1/models 返回字段为 id（如 qwen2.5:3b）；标准 OpenAI 为 id。
    """
    import json
    import urllib.request

    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/models", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            payload = json.loads(resp.read().decode())
        ids = [m.get("id", "") for m in payload.get("data", [])]
        if not ids:
            return None
        # 精确匹配，或按主名段精确匹配（避免 qwen2.5:3b 误匹配 qwen2.5vl:7b）
        for mid in ids:
            if mid == model:
                return mid
            if mid.split(":")[0] == model.split(":")[0] and ":" in model:
                return mid
        return None
    except Exception:
        return None
