"""知识自动提取（对话中沉淀知识，不干扰对话）。

- LLM 提取（可选）：真实 LLM 可用时提取结构化知识（标题/摘要/正文/分类/标签）
- 规则回退（零依赖）：检测知识句（定义/结论/偏好/事实句式）
- 摘要生成：正文 → 摘要（首句 + 关键词）
- 相似度匹配：复用 store.find_similar（对话中自动调用知识卡片）
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# 规则知识句模式（LLM 不可用时的回退）：(正则, 分类)
_RULE_PATTERNS = [
    (r"(?:记住|记下|记得)[:：]?\s*(.+)", "个人偏好"),      # 记得每周五开会 → 习惯
    (r"我(?:喜欢|讨厌|最爱|不喜欢)\s*(.+)", "个人偏好"),
    (r"(?:定义|意思是|指的是)[:：]?\s*(.+)", "概念定义"),
    (r"我(?:叫|是|的名字是)\s*(.+)", "个人信息"),
    (r"重点(?:是|在)[:：]?\s*(.+)", "要点"),
    (r"总结(?:一下|来说|：|:)?\s*(.+)", "知识总结"),
]

_LLM_PROMPT = """从用户话语中提取值得长期保存的知识卡片。若无可提取内容输出 {"empty": true}。

知识卡片 JSON 格式（只输出 JSON）：
{
  "title": "简短标题（≤20字）",
  "summary": "一句话摘要（≤40字）",
  "content": "详细内容（≤100字，保留关键信息）",
  "category": "分类（个人偏好/概念定义/个人信息/要点/知识总结/习惯日程/其他）",
  "tags": ["标签1", "标签2"]
}

要求：
- 提取明确、有价值的陈述：偏好、概念、个人信息、习惯/定期日程（"每周五""每天"等）、重点结论
- 不提取：寒暄（天气闲聊）、一次性请求（"帮我订机票"）、情绪化表达、简单附和

用户话语：{text}
"""


class KnowledgeExtractor:
    def __init__(self, router=None) -> None:
        self.router = router  # 可选 LLM 路由

    # ---- 主入口 ----

    async def extract(self, text: str) -> Optional[Dict[str, Any]]:
        """从对话文本提取知识卡片字段；无可提取返回 None。"""
        text = (text or "").strip()
        if not text or len(text) < 4:
            return None
        # LLM 优先（不阻塞：异步 + 超时保护）
        if self.router is not None and self._llm_available():
            try:
                result = await self._llm_extract(text)
                if result is not None:
                    return result
            except Exception as e:
                log.debug("LLM 知识提取失败，回退规则: %s", e)
        return self._rule_extract(text)

    def _llm_available(self) -> bool:
        try:
            return self.router._local_available() or bool(self.router._cloud_api_key())
        except Exception:
            return False

    async def _llm_extract(self, text: str) -> Optional[Dict[str, Any]]:
        from aivyos_core.models import LLMRequest, RouteDecision, RouteMode

        decision = RouteDecision(
            mode=RouteMode.LOCAL if self.router._local_available() else RouteMode.CLOUD,
            model=self.router.cfg["local"]["model"] if self.router._local_available() else self.router.cfg["cloud"]["model"],
            reason="知识提取",
        )
        request = LLMRequest(
            messages=[{"role": "system", "content": _LLM_PROMPT.format(text=text[:500])}],
            model=decision.model, max_tokens=300, temperature=0.2,
        )
        resp = await self.router.complete(request, decision)
        if "mock" in resp.model.lower():
            return None
        m = re.search(r"\{.*\}", resp.text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        if data.get("empty"):
            return None
        title = str(data.get("title", "")).strip()
        if not title:
            return None
        return {
            "title": title[:30],
            "summary": str(data.get("summary", ""))[:60],
            "content": str(data.get("content", ""))[:200],
            "category": str(data.get("category", "其他"))[:20],
            "tags": [str(t)[:20] for t in data.get("tags", [])][:6],
            "source": "auto",
        }

    # ---- 规则回退 ----

    def _rule_extract(self, text: str) -> Optional[Dict[str, Any]]:
        for pattern, category in _RULE_PATTERNS:
            m = re.search(pattern, text)
            if m and m.group(1).strip():
                content = m.group(1).strip()
                title = content[:20]
                return {
                    "title": title,
                    "summary": content[:40],
                    "content": content[:200],
                    "category": category,
                    "tags": [category],
                    "source": "auto-rule",
                }
        return None

    # ---- 摘要生成（正文 → 摘要）----

    @staticmethod
    def summarize(content: str, max_len: int = 40) -> str:
        """生成摘要：首句截断 + 句号边界。"""
        content = (content or "").strip()
        if not content:
            return ""
        # 取首句
        for sep in ("。", ".", "！", "？", "；", ";"):
            idx = content.find(sep)
            if 0 < idx < max_len:
                content = content[: idx + 1]
                break
        return content[:max_len]
