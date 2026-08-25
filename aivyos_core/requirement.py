"""需求解析引擎（文档 §10.1 阶段1 / T5.2）：自然语言 → 结构化项目规格 JSON。

- 规则解析（零依赖保底）：模板关键词匹配（§10.2 触发词）、标题提取、特性拆分
- LLM 增强（可选）：真实 LLM 可用时补全规格字段
"""

from __future__ import annotations

import logging
log = logging.getLogger(__name__)

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 模板触发词（§10.2）
TEMPLATE_KEYWORDS: Dict[str, List[str]] = {
    "react-web-app": ["react", "网页", "前端", "网站"],
    "vue-web-app": ["vue", "vite"],
    "nextjs-app": ["全栈", "ssr", "next", "next.js"],
    "python-cli": ["命令行", "cli", "脚本", "工具"],
    "python-api": ["api", "后端", "服务", "接口"],
    "static-site": ["静态", "简单页面", "html"],
    "tauri-desktop-app": ["桌面", "桌面应用", "托盘", "desktop"],
}

TITLE_PATTERNS = [
    r"(?:帮我做|帮我写|做一个|写一个|做个|写个|开发)\s*([\u4e00-\u9fff\w]+)",
    r"^([\u4e00-\u9fff\w]+)(?:应用|程序|网页|网站|工具|项目)",
]

# 标题清洗：去掉"一个/这个"前缀与"的/应用/网页..."等类别后缀
TITLE_STRIP_PREFIXES = ("一个", "这个", "那个", "个")
TITLE_STRIP_SUFFIXES = ("的", "应用", "程序", "网页", "网站", "工具", "项目", "桌面应用", "后端", "服务", "接口", "系统")


def _clean_title(raw: str) -> str:
    t = raw.strip()
    for p in TITLE_STRIP_PREFIXES:
        if t.startswith(p) and len(t) > len(p):
            t = t[len(p):]
            break
    while t:
        hit = False
        for s in TITLE_STRIP_SUFFIXES:
            if t.endswith(s) and len(t) > len(s):
                t = t[: -len(s)]
                hit = True
                break
        if not hit:
            break
    return t[:30] or "AivyApp"


@dataclass
class ProjectSpec:
    type: str = "static-site"
    title: str = "AivyApp"
    features: List[str] = field(default_factory=list)
    tech: List[str] = field(default_factory=list)
    target_dir: str = ""
    source: str = "rule"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "title": self.title,
            "features": self.features,
            "tech": self.tech,
            "target_dir": self.target_dir,
            "source": self.source,
        }


def _safe_dir(title: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]", "", title) or "app"
    return name[:40]


class RequirementParser:
    def __init__(self, router=None) -> None:
        self.router = router  # 可选 LLM 路由（增强解析）

    def parse(self, text: str) -> ProjectSpec:
        """规则解析（保底）。"""
        lowered = text.lower()
        # 模板匹配
        ptype = "static-site"
        best = 0
        for t, kws in TEMPLATE_KEYWORDS.items():
            hits = sum(1 for k in kws if k in lowered)
            if hits > best:
                best, ptype = hits, t
        # 标题提取
        title = "AivyApp"
        for pat in TITLE_PATTERNS:
            m = re.search(pat, text)
            if m and m.group(1):
                title = _clean_title(m.group(1))
                break
        # 特性拆分（和/、/，/以及）
        features = [f.strip() for f in re.split(r"[和、，,。;；]", text) if len(f.strip()) > 1][:5]
        spec = ProjectSpec(
            type=ptype,
            title=title,
            features=features,
            tech=[ptype.split("-")[0]],
            target_dir=_safe_dir(title),
        )
        return spec

    async def parse_enhanced(self, text: str) -> ProjectSpec:
        """规则 + LLM 增强（真实后端可用时）。"""
        spec = self.parse(text)
        if self.router is None or not self._real_llm():
            return spec
        try:
            enhanced = await self._llm_parse(text)
            if enhanced:
                spec.features = enhanced.get("features") or spec.features
                spec.tech = enhanced.get("tech") or spec.tech
                spec.source = "rule+llm"
        except Exception as e:
            log.debug("忽略预期内异常: %s", e, exc_info=True)
        return spec

    def _real_llm(self) -> bool:
        try:
            return self.router._local_available() or bool(self.router._cloud_api_key())
        except Exception:
            return False

    async def _llm_parse(self, text: str) -> Optional[Dict[str, Any]]:
        from aivyos_core.models import LLMRequest, RouteDecision, RouteMode

        decision = RouteDecision(
            mode=RouteMode.LOCAL if self.router._local_available() else RouteMode.CLOUD,
            model=self.router.cfg["local"]["model"] if self.router._local_available() else self.router.cfg["cloud"]["model"],
            reason="需求解析",
        )
        prompt = (
            "把以下用户需求解析为项目规格，只输出 JSON："
            '{"title": "...", "features": ["..."], "tech": ["..."]}\n需求：' + text[:400]
        )
        request = LLMRequest(
            messages=[{"role": "system", "content": prompt}],
            model=decision.model, max_tokens=200, temperature=0.2,
        )
        resp = await self.router.complete(request, decision)
        if "mock" in resp.model.lower():
            return None
        import json
        import re

        m = re.search(r"\{.*\}", resp.text, re.S)
        if not m:
            return None
        return json.loads(m.group(0))
