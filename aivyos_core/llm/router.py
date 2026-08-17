"""LLM 路由策略（文档 §4.1.3）。

- 复杂度估计：简单闲聊 / 复杂推理 / 编程 / 视觉
- 模式选择：auto（简单→本地；复杂/编程→云端优先；均不可达→mock 回退）
         / local / cloud / mock（强制）
- 与 §18.1 硬件约束对齐：8GB 显存本地跑 7B INT4；72B 需多卡（Week 3+ 支持）
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from aivyos_core.llm.base import LLMBackend, LLMBackendError
from aivyos_core.llm.mock import MockLLM
from aivyos_core.llm.openai_compat import OpenAICompatLLM
from aivyos_core.models import LLMRequest, RouteDecision, RouteMode

CODING_KEYWORDS = (
    "代码", "写个", "实现", "函数", "脚本", "重构", "bug", "修复", "程序",
    "计算器", "网页", "项目", "接口", "api", "数据库", "算法",
)
COMPLEX_KEYWORDS = (
    "为什么", "分析", "对比", "方案", "规划", "评估", "权衡", "设计",
    "架构", "原因", "影响", "总结", "深度",
)
VISION_KEYWORDS = ("图片", "截图", "这张图", "识别图中", "看下这张")


class ModelRouter:
    """按复杂度与配置将请求路由到本地 / 云端 / mock 后端。"""

    def __init__(self, llm_cfg: Dict) -> None:
        self.cfg = llm_cfg
        self._backends: Dict[str, LLMBackend] = {}
        self._cloud_key: Optional[str] = None

    # ---- 复杂度估计（§4.1.3 estimate_complexity）----

    @staticmethod
    def estimate_complexity(text: str, context_len: int = 0) -> str:
        t = text.lower()
        if any(k in t for k in VISION_KEYWORDS):
            return "vision"
        if any(k in t for k in CODING_KEYWORDS):
            return "coding"
        if any(k in t for k in COMPLEX_KEYWORDS) or context_len > 400:
            return "complex_reasoning"
        return "simple_chat"

    # ---- 路由决策（§4.1.3 route_model）----

    def route(self, text: str, context_len: int = 0) -> RouteDecision:
        mode = self.cfg.get("mode", "auto")
        complexity = self.estimate_complexity(text, context_len)

        if mode == "mock":
            return RouteDecision(RouteMode.MOCK, self._mock_cfg()["model"], "强制 mock 模式")

        if mode == "local":
            return RouteDecision(
                RouteMode.LOCAL, self.cfg["local"]["model"], "强制本地模式",
                fallback=not self._local_available(),
            )

        if mode == "cloud":
            if self._cloud_api_key():
                return RouteDecision(RouteMode.CLOUD, self.cfg["cloud"]["model"], "强制云端模式")
            return RouteDecision(
                RouteMode.MOCK, self._mock_cfg()["model"],
                "云端模式但缺少 AIVYOS_CLOUD_API_KEY，回退 mock", fallback=True,
            )

        # ---- auto：按 §4.1.3 路由逻辑 ----
        if complexity in ("simple_chat", "vision"):
            return RouteDecision(RouteMode.LOCAL, self.cfg["local"]["model"], f"auto→本地（{complexity}）",
                                 fallback=not self._local_available())
        # complex_reasoning / coding：云端优先（文档：编程优先云端）
        if self._cloud_api_key():
            return RouteDecision(RouteMode.CLOUD, self.cfg["cloud"]["model"], f"auto→云端（{complexity}）")
        if self._local_available():
            return RouteDecision(RouteMode.LOCAL, self.cfg["local"]["model"],
                                 f"auto→云端无密钥，降级本地（{complexity}）", fallback=True)
        return RouteDecision(RouteMode.MOCK, self._mock_cfg()["model"],
                             f"auto→本地不可达，回退 mock（{complexity}）", fallback=True)

    # ---- 后端实例化 ----

    async def complete(self, request: LLMRequest, decision: RouteDecision) -> "object":
        backend = self._get_backend(decision.mode)
        try:
            return await backend.complete(request)
        except LLMBackendError:
            if decision.mode != RouteMode.MOCK:
                # 真实后端失败 → 自动降级 mock，保证链路不断；同步更新决策报告
                mock = self._get_backend(RouteMode.MOCK)
                decision.mode = RouteMode.MOCK
                decision.model = mock.name
                decision.fallback = True
                decision.reason += "（调用失败已降级 mock）"
                return await mock.complete(request)
            raise

    def _get_backend(self, mode: RouteMode) -> LLMBackend:
        if mode == RouteMode.MOCK:
            if "mock" not in self._backends:
                self._backends["mock"] = MockLLM(self._mock_cfg()["model"])
            return self._backends["mock"]

        if mode == RouteMode.LOCAL:
            if "local" not in self._backends:
                c = self.cfg["local"]
                self._backends["local"] = OpenAICompatLLM(
                    base_url=c["base_url"], model=c["model"],
                    api_key=c.get("api_key"), timeout_s=c.get("timeout_s", 60),
                )
            return self._backends["local"]

        if mode == RouteMode.CLOUD:
            if "cloud" not in self._backends:
                c = self.cfg["cloud"]
                self._backends["cloud"] = OpenAICompatLLM(
                    base_url=c["base_url"], model=c["model"],
                    api_key=self._cloud_api_key(), timeout_s=c.get("timeout_s", 120),
                )
            return self._backends["cloud"]
        raise LLMBackendError(f"未知路由模式: {mode}")

    # ---- 可用性探测 ----

    def _local_available(self) -> bool:
        """Week 1 探测：环境变量显式禁用则不可用；真实探测（连接测试）留待后续。"""
        if os.environ.get("AIVYOS_DISABLE_LOCAL") == "1":
            return False
        return True  # 乐观可用；调用失败时由 complete() 降级 mock

    def _cloud_api_key(self) -> Optional[str]:
        if self._cloud_key is None:
            env_name = self.cfg["cloud"].get("api_key_env", "AIVYOS_CLOUD_API_KEY")
            self._cloud_key = os.environ.get(env_name) or self.cfg["cloud"].get("api_key")
        return self._cloud_key

    def _mock_cfg(self) -> Dict:
        return self.cfg.get("mock", {"model": "mock-echo"})

    # ---- 调试辅助 ----

    def backends_status(self) -> List[Dict]:
        return [
            {"mode": "local", "model": self.cfg["local"]["model"],
             "available": self._local_available()},
            {"mode": "cloud", "model": self.cfg["cloud"]["model"],
             "available": bool(self._cloud_api_key())},
            {"mode": "mock", "model": self._mock_cfg()["model"], "available": True},
        ]
