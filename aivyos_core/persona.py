"""人格系统（文档 §4.3）：Big Five 参数 + 交互风格 + System Prompt 模板。

参数通过 System Prompt 注入 LLM，每次推理生效（PERSONA_TEMPLATE 对齐文档 §4.3）。
Agent 角色定位参见 `aivyos_core.roles`：
  - Agent 名 = 贾维斯（用户指定的 AI 助手名）
  - 核心职责 = 整个系统的资源调度者 + 任务执行者
  - 用户 = 任务发布者，只发意图，不直接操作底层资源
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict

from aivyos_core.roles import (
    AGENT_REPORTING_RULES,
    AGENT_ROLE_DEFINITION,
    USER_ROLE_DEFINITION,
)

VALID_TONES = ("professional", "casual", "witty", "serious")
VALID_LENGTHS = ("concise", "balanced", "detailed")

# ─────────────────────────────────────────────────────────────
# System Prompt 模板：
#   — 开头显式声明角色 = 贾维斯（资源调度 + 任务执行）
#   — 明确用户角色 = 任务发布者
#   — 末尾追加汇报行为 4 准则（杜绝口头宣称但无证据的历史问题）
# ─────────────────────────────────────────────────────────────
PERSONA_TEMPLATE = """你是 {name}（Jarvis），用户指定的 AI 助手。
你的身份：整个 AivyOS 系统的【资源调度者】与【任务执行者】。
用户的身份：【任务发布者】，只向你下达意图和约束，不直接操作底层资源。

## 角色总定义
- 你的职责（贾维斯）：{agent_role_definition}
- 用户的职责：{user_role_definition}

## 性格参数 (Big Five)
- 开放性: {openness} / 1.0
- 尽责性: {conscientiousness} / 1.0
- 外向性: {extraversion} / 1.0
- 宜人性: {agreeableness} / 1.0
- 情绪稳定性: {stability} / 1.0

## 交互风格
- 语气: {tone}
- 称呼用户为: {user_alias}
- 回复长度: {response_length}
- 语言: {language}

## 行为准则
1. 始终记住用户偏好和历史交互
2. 主动提供有帮助的建议
3. 不确定时坦诚说明，不编造信息
4. 每完成一项任务，必须向用户明确汇报：①改了哪些文件 ②关键变更点摘要 ③验证结果；绝不能只说"已完成"而不给证据链
5. 对文件级修改给出可定位的片段对比（带文件路径 + 行号范围），确保用户可核验
6. 运行结果附带证据（单元测试 exit code / 通过数 / 健康检查耗时 / 失败堆栈）
7. 遇到超出能力范围或需要用户决策的点，立即暂停并询问，绝不越权自定方案"""


@dataclass
class Persona:
    """人格参数容器。

    默认 name 使用"贾维斯"（来自 roles.py AGENT_NAME_PRIMARY 全局真源），
    避免把系统品牌"Aivy"与人格名混用导致的角色混淆。
    """
    name: str = "贾维斯"
    openness: float = 0.8
    conscientiousness: float = 0.9
    extraversion: float = 0.3
    agreeableness: float = 0.7
    stability: float = 0.8
    tone: str = "professional"
    user_alias: str = "先生"
    response_length: str = "balanced"
    language: str = "zh-CN"
    extra_rules: list[str] = field(default_factory=list)

    def render_system_prompt(self) -> str:
        """渲染完整 System Prompt，包含角色定义 + 汇报规则。"""
        # extra_rules 用户可追加；AGENT_REPORTING_RULES 作为硬性最低要求已经写入模板第 4-7 条
        extra_suffix = ""
        combined_rules: list[str] = list(self.extra_rules)
        # 将 AGENT_REPORTING_RULES 中尚未出现在模板里的额外项目，作为"附加规则"注入
        # （模板中已显式包含了汇报 4 条，这里保留列表避免未来扩展时遗漏）
        _ = AGENT_REPORTING_RULES  # noqa: F841 — 已在模板中硬编码等价表述
        prompt = PERSONA_TEMPLATE.format(
            name=self.name,
            agent_role_definition=AGENT_ROLE_DEFINITION,
            user_role_definition=USER_ROLE_DEFINITION,
            openness=self._fmt(self.openness),
            conscientiousness=self._fmt(self.conscientiousness),
            extraversion=self._fmt(self.extraversion),
            agreeableness=self._fmt(self.agreeableness),
            stability=self._fmt(self.stability),
            tone=self.tone,
            user_alias=self.user_alias,
            response_length=self.response_length,
            language=self.language,
        )
        if combined_rules:
            extra_suffix = (
                "\n\n## 附加规则\n"
                + "\n".join(f"{i+1}. {r}" for i, r in enumerate(combined_rules))
            )
        return prompt + extra_suffix

    @staticmethod
    def _fmt(v: float) -> str:
        return f"{v:.1f}"

    def update(self, field_name: str, value: Any) -> bool:
        """运行时修改人格参数（托盘/CLI 入口）。返回是否生效。"""
        if not hasattr(self, field_name):
            return False
        if field_name in ("tone",) and value not in VALID_TONES:
            return False
        if field_name in ("response_length",) and value not in VALID_LENGTHS:
            return False
        if field_name in (
            "openness", "conscientiousness", "extraversion",
            "agreeableness", "stability",
        ):
            value = float(value)
            if not (0.0 <= value <= 1.0):
                return False
        setattr(self, field_name, value)
        return True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "Persona":
        """从 config 字典构造 Persona；未设置 name 时默认用贾维斯。"""
        return cls(
            name=cfg.get("name", "贾维斯"),
            openness=cfg.get("openness", 0.8),
            conscientiousness=cfg.get("conscientiousness", 0.9),
            extraversion=cfg.get("extraversion", 0.3),
            agreeableness=cfg.get("agreeableness", 0.7),
            stability=cfg.get("stability", 0.8),
            tone=cfg.get("tone", "professional"),
            user_alias=cfg.get("user_alias", "先生"),
            response_length=cfg.get("response_length", "balanced"),
            language=cfg.get("language", "zh-CN"),
            extra_rules=list(cfg.get("extra_rules", [])),
        )
