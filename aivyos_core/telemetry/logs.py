"""结构化 JSON 日志 + 安全审计（文档 §21.2 / T10.4）：零依赖。

- JsonlHandler：logging.Handler，每条记录序列化为 JSON 行（time/level/logger/message/fields）
- SecurityAuditLog：安全审计日志（事件类型/时间戳/详情），复用 update.security_log 通道
- 优雅降级：日志目录不可写时静默跳过（不阻断业务）
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional


class JsonlHandler(logging.Handler):
    """结构化 JSON 日志 Handler（§21.2 日志聚合：JSONL）。"""

    def __init__(self, path: Path, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.path = Path(path)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            extra = getattr(record, "fields", None)
            if isinstance(extra, dict):
                entry.update(extra)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 日志失败不阻断业务（§2 优雅降级）


def attach_json_logging(logger: logging.Logger, path: Path, level: int = logging.INFO) -> JsonlHandler:
    """给 logger 挂载 JSONL Handler，返回 handler（可 removeHandler）。"""
    handler = JsonlHandler(path, level)
    logger.addHandler(handler)
    return handler


def log_fields(logger: logging.Logger, message: str, **fields: Any) -> None:
    """带结构化字段的日志（fields 会写入 JSON 行）。"""
    logger.info(message, extra={"fields": fields})


class SecurityAuditLog:
    """安全审计日志（§21.2 / §1.6.2）：JSONL 追加，事件类型 + 时间戳 + 详情。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path

    def event(self, code: str, message: str, **details: Any) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": int(time.time()),
                "code": code,
                "message": message,
                **details,
            }
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def read(self, limit: int = 50) -> list:
        if self.path is None or not self.path.exists():
            return []
        out = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out[-limit:]
