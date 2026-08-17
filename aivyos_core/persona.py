"""人格系统（文档 §4.3）：Big Five 参数 + 交互风格 + System Prompt 模板。

参数通过 System Prompt 注入 LLM，每次推理生效（PERSONA_TEMPLATE 对齐文档 §4.3）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict

VALID_TONES = ("professional", "casual", "witty", "serious")
VALID_LENGTHS = ("concise", "balanced", "detailed")

PERSONA_TEMPLATE = """你是 {name}，用户的私人AI助理。

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
3. 不确定时坦诚说明，不编造信息"""


@dataclass
class Persona:
    name: str = "Aivy"
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
        prompt = PERSONA_TEMPLATE.format(
            name=self.name,
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
        if self.extra_rules:
            prompt += "\n\n## 附加规则\n" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(self.extra_rules))
        return prompt

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
        if field_name in ("openness", "conscientiousness", "extraversion", "agreeableness", "stability"):
            value = float(value)
            if not (0.0 <= value <= 1.0):
                return False
        setattr(self, field_name, value)
        return True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "Persona":
        return cls(
            name=cfg.get("name", "Aivy"),
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
