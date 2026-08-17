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
            return QwenVLBackend(base_url, model=cfg.get("model", "qwen2-vl-7b"))
        return MockUnderstand()
    return MockUnderstand()
