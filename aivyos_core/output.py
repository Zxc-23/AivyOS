"""多模态输出策略（文档 §6.3）：语音/文本/通知/文件 路由。

规则（§6.3）：
- 语音交互场景 → 语音输出（全双工）
- 文本交互场景 → 文本输出，复杂结果辅以可视化
- 主动通知场景 → 低紧急度文本通知 / 高紧急度语音播报
- 代码/文档场景 → 文本 + 文件写入（IDE/文件管理器展示）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class OutputChannel(str, Enum):
    TEXT = "text"
    VOICE = "voice"
    NOTIFICATION = "notification"
    FILE = "file"


@dataclass
class OutputPlan:
    channel: OutputChannel
    payload: str
    level: str = "normal"
    path: Optional[str] = None


class OutputRouter:
    """§6.3 多模态输出路由。"""

    def __init__(self, config: Dict[str, Any], tts=None, notifier=None) -> None:
        self.config = config
        self.default_channel = OutputChannel(config.get("default_channel", "text"))
        self.tts = tts
        self.notifier = notifier
        self._code_pattern = re.compile(r"```|\b(?:def|class|function|import|from|const)\b")

    def decide(self, reply_text: str, modality_hint: str = "text") -> OutputPlan:
        """按输入模态 + 内容类型选择输出通道（§6.3）。"""
        hint = (modality_hint or "text").lower()
        if hint == "voice":
            return OutputPlan(OutputChannel.VOICE, reply_text)
        if hint == "notification":
            level = self._urgency(reply_text)
            if level == "urgent":
                return OutputPlan(OutputChannel.VOICE, reply_text, level=level)
            return OutputPlan(OutputChannel.NOTIFICATION, reply_text, level=level)
        if hint == "file":
            return OutputPlan(OutputChannel.FILE, reply_text)
        # text 场景：代码/文档内容 → 文本 + 文件落盘提示
        if self._code_pattern.search(reply_text):
            return OutputPlan(OutputChannel.FILE, reply_text)
        return OutputPlan(self.default_channel, reply_text)

    def deliver(self, plan: OutputPlan) -> Dict[str, Any]:
        """执行输出（§6.3 各通道）。"""
        result = {"channel": plan.channel.value, "length": len(plan.payload)}
        if plan.channel == OutputChannel.VOICE and self.tts is not None:
            audio = self.tts.synthesize(plan.payload)
            result["tts_backend"] = audio.backend
            result["wav_len"] = len(audio.pcm)
        elif plan.channel == OutputChannel.NOTIFICATION and self.notifier is not None:
            result["notification"] = self.notifier.notify("AivyOS", plan.payload, level=plan.level)
        elif plan.channel == OutputChannel.FILE:
            path = self._write_text_file(plan.payload)
            result["path"] = path
        return result

    @staticmethod
    def _urgency(text: str) -> str:
        if any(k in text for k in ("异常", "错误", "警告", "失败", "紧急", "安全")):
            return "urgent"
        if any(k in text for k in ("提醒", "注意", "别忘了")):
            return "important"
        return "normal"

    def _write_text_file(self, content: str) -> str:
        import time as _t

        out_dir = Path(self.config.get("output_dir", ".aivyos_out"))
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"reply_{_t.strftime('%Y%m%d_%H%M%S')}.md"
        path.write_text(content, encoding="utf-8")
        return str(path)
