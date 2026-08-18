"""健康检查器（文档 桌面端规格 §3.3 / Week 11）：热交换完成后验证，失败自动回滚。

检查项（§3.3 表）：llm 推理 / memory 记忆检索 / tools 工具调用 / voice ASR-TTS /
scheduler 定时任务 / frontend 前端渲染。每项独立超时；任一失败 → 整体 unhealthy + 失败项。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

# 检查项 + 默认超时（秒，§3.3 表）
DEFAULT_CHECKS = {
    "llm": 10.0,
    "memory": 5.0,
    "tools": 10.0,
    "voice": 5.0,
    "scheduler": 3.0,
    "frontend": 5.0,
}


class HealthChecker:
    def __init__(self, checks: Optional[Dict[str, Callable[[], Any]]] = None, timeouts: Optional[Dict[str, float]] = None) -> None:
        """
        checks: {name: callable} 返回真值表示健康；缺省为空（构造后 register）。
        timeouts: {name: 秒}，缺省 DEFAULT_CHECKS。
        """
        self.checks: Dict[str, Callable[[], Any]] = dict(checks or {})
        self.timeouts: Dict[str, float] = dict(timeouts or DEFAULT_CHECKS)

    def register(self, name: str, fn: Callable[[], Any], timeout: Optional[float] = None) -> None:
        self.checks[name] = fn
        if timeout is not None:
            self.timeouts[name] = timeout

    async def verify(self) -> Dict[str, Any]:
        """执行所有健康检查（§3.3）：全部通过 → healthy。任一失败/超时 → unhealthy + failed。"""
        results: Dict[str, Any] = {}

        async def _run(name: str, fn: Callable[[], Any], timeout: float) -> Any:
            async def _inner():
                r = fn()
                if asyncio.iscoroutine(r) or hasattr(r, "__await__"):
                    return await r
                return r
            return await asyncio.wait_for(_inner(), timeout=timeout)

        for name, fn in self.checks.items():
            timeout = self.timeouts.get(name, 10.0)
            try:
                result = await _run(name, fn, timeout)
                results[name] = bool(result)
                if not result:
                    return {"healthy": False, "failed": name, "results": results}
            except asyncio.TimeoutError:
                results[name] = False
                return {"healthy": False, "failed": name, "results": results, "timeout": True}
            except Exception as e:
                results[name] = False
                return {"healthy": False, "failed": name, "results": results, "error": str(e)}
        return {"healthy": True, "results": results}

    @staticmethod
    def check_llm(generate_fn) -> Callable[[], bool]:
        """§3.3 LLM 推理：发送测试 prompt 检查响应非空。"""
        def _fn():
            try:
                return bool(generate_fn("Hello", max_tokens=10))
            except Exception:
                return False
        return _fn

    @staticmethod
    def check_memory(retrieve_fn) -> Callable[[], bool]:
        """§3.3 记忆检索：能查询即正常（即使返回空）。"""
        def _fn():
            try:
                retrieve_fn("test", top_k=1)
                return True
            except Exception:
                return False
        return _fn
