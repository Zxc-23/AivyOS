"""图像内容理解（文档 §3.3：Qwen2-VL 可选 + mock 回退）。

v2 改进：动态加载/释放 —— 需要时（首次视觉调用）才加载视觉模型，
空闲自动释放（Ollama keep_alive=0），避免长期占用显存。
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class UnderstandUnavailable(RuntimeError):
    pass


class UnderstandBackend(ABC):
    name: str = "base"

    @abstractmethod
    def describe(self, image: bytes) -> str:
        raise NotImplementedError

    # ---- 动态加载/释放钩子（默认无操作）----
    def ensure_loaded(self) -> None:
        """确保模型已加载（首次调用前触发；失败不抛出，交由 describe 兜底）。"""
        return

    def release(self) -> None:
        """空闲释放模型（Ollama keep_alive=0）。"""
        return


class MockUnderstand(UnderstandBackend):
    """mock 回退：诚实标注，不伪装视觉理解。"""

    name = "mock-vision"

    def describe(self, image: bytes) -> str:
        if not image:
            return ""
        return "（mock 视觉理解）图像内容描述占位，接入 Qwen2-VL/本地多模态模型后返回真实描述"


class QwenVLBackend(UnderstandBackend):
    """Qwen2-VL 本地视觉理解（通过 OpenAI 兼容多模态端点，可选配置）。

    动态加载策略（Ollama）：
    - ensure_loaded()：首次调用前用原生 /api/generate 空请求触发加载，
      并设置 keep_alive 驻留秒数（默认 600s，Ollama 侧自动释放兜底）；
    - release()：调用 /api/generate keep_alive=0 立即释放显存；
    - 空闲守护线程：本进程内超过 idle_unload_s 未使用 → 自动 release。
    非 Ollama 端点（vLLM 等）无 keep_alive 语义 → 静默跳过加载管理。
    """

    name = "qwen2-vl"

    # 空闲守护：所有实例共享（全局单线程，低频率扫描）
    _registry: List["QwenVLBackend"] = []
    _registry_lock = threading.Lock()
    _watcher_started = False

    def __init__(
        self,
        base_url: str,
        model: str = "qwen2-vl-7b",
        api_key: Optional[str] = None,
        keep_alive_s: int = 600,
        idle_unload_s: int = 300,
        load_timeout_s: int = 300,
    ) -> None:
        import base64

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._b64 = base64
        self._last_used = time.monotonic()
        self._keep_alive_s = int(keep_alive_s or 600)
        self._idle_unload_s = int(idle_unload_s or 300)
        self._load_timeout_s = int(load_timeout_s or 300)
        self._ollama_base = self._detect_ollama_base(self.base_url)
        self._registered = False
        self._register()

    # ------------------------------------------------------------------
    # Ollama 原生端点探测（keep_alive 语义仅在 Ollama 可用）
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_ollama_base(base_url: str) -> Optional[str]:
        """从 OpenAI 兼容 base_url 推导 Ollama 原生根（http://host:11434）。

        仅当端点明显指向本地 Ollama（localhost/127.0.0.1/::1 且端口 11434，
        或 URL 含 /v1 且主机为本地回环）时识别；远程端点（vLLM 等）返回 None，
        加载管理静默跳过。
        """
        import re

        url = base_url.rstrip("/")
        host_match = re.match(r"^https?://([^/:]+)(?::(\d+))?", url)
        host = host_match.group(1) if host_match else ""
        port = host_match.group(2) if host_match and host_match.group(2) else ""
        is_loopback = host in ("localhost", "127.0.0.1", "::1", "[::1]") or host.startswith("127.")
        if port == "11434":
            # http://127.0.0.1:11434/v1 → http://127.0.0.1:11434
            for suffix in ("/v1", "/openai", "/api"):
                if url.endswith(suffix):
                    return url[: -len(suffix)]
            return url
        # 无端口但主机回环 + /v1（极少见）→ 按 Ollama 处理
        if is_loopback and any(url.endswith(s) for s in ("/v1", "/openai", "/api")):
            for suffix in ("/v1", "/openai", "/api"):
                if url.endswith(suffix):
                    return url[: -len(suffix)]
        return None

    def _ollama_request(self, body: dict, timeout: float = 10.0) -> bool:
        """POST Ollama 原生端点（/api/generate），失败静默返回 False。"""
        if not self._ollama_base:
            return False
        import json
        import urllib.request

        try:
            req = urllib.request.Request(
                self._ollama_base + "/api/generate",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read()
            return True
        except Exception as e:
            log.debug("Ollama 加载管理请求失败（忽略）: %s", e)
            return False

    def _register(self) -> None:
        with self._registry_lock:
            if self._registered:
                return
            self._registered = True
            self._registry.append(self)
            if not self._watcher_started:
                self._watcher_started = True
                t = threading.Thread(target=self._idle_watcher, daemon=True, name="qwen2vl-idle")
                t.start()

    @classmethod
    def _idle_watcher(cls) -> None:
        """空闲自动释放守护线程：低频率扫描（30s 间隔）。"""
        while True:
            time.sleep(30)
            now = time.monotonic()
            with cls._registry_lock:
                stale = [b for b in cls._registry if b._idle_unload_s > 0 and now - b._last_used > b._idle_unload_s]
            for b in stale:
                log.info("视觉模型 %s 空闲 %ds，自动释放显存", b.model, b._idle_unload_s)
                b.release()

    # ------------------------------------------------------------------
    # 动态加载/释放接口
    # ------------------------------------------------------------------
    def ensure_loaded(self) -> None:
        """首次调用前触发模型加载（空请求 + keep_alive 驻留）。

        Ollama：POST /api/generate {model, prompt:"", keep_alive} → 触发加载。
        非 Ollama / 已加载：静默跳过。失败不抛出 —— describe 真实请求兜底。
        """
        self._last_used = time.monotonic()
        if not self._ollama_base:
            return
        body = {"model": self.model, "prompt": "", "keep_alive": self._keep_alive_s, "stream": False}
        self._ollama_request(body, timeout=min(30.0, max(10.0, float(self._load_timeout_s))))

    def release(self) -> None:
        """立即释放模型显存（Ollama keep_alive=0）。"""
        if not self._ollama_base:
            return
        self._ollama_request({"model": self.model, "prompt": "", "keep_alive": 0, "stream": False}, timeout=10.0)

    def touch(self) -> None:
        self._last_used = time.monotonic()

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def describe(self, image: bytes) -> str:
        import json
        import urllib.request

        self.ensure_loaded()
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode())
        self.touch()
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
                return QwenVLBackend(
                    base_url,
                    model=real_model,
                    keep_alive_s=int(cfg.get("keep_alive_s", 600)),
                    idle_unload_s=int(cfg.get("idle_unload_s", 300)),
                    load_timeout_s=int(cfg.get("load_timeout_s", 300)),
                )
            log.warning("视觉理解模型 %s 不可用（端点 %s），回退 mock", model, base_url)
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
