"""拖拽文件类型路由（文档 AIVY-DDD-004 §3.5 / T7.6）：文件 → 分析器路由。

六类分析器（§3.5）：
- text     .txt/.md      读取 → 总结+提取要点
- document .pdf/.docx    解析全文 → 结构化总结
- sheet    .xlsx/.csv    读取数据 → 统计+可视化建议
- code     .py/.js/.ts   代码审查 → 质量评分+改进建议
- image    .png/.jpg     视觉理解 → 描述+OCR
- other    其他          读文件头推断 → 尝试分析

零依赖：仅按扩展名/文件头路由，返回结构化路由建议（不读大文件）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

# 扩展名 → 分析器类型（§3.5 路由表）
EXT_ROUTES: Dict[str, str] = {
    ".txt": "text", ".md": "text", ".markdown": "text", ".log": "text",
    ".pdf": "document", ".docx": "document", ".doc": "document",
    ".xlsx": "sheet", ".csv": "sheet", ".xls": "sheet",
    ".py": "code", ".js": "code", ".ts": "code", ".tsx": "code",
    ".jsx": "code", ".rs": "code", ".go": "code", ".java": "code", ".c": "code",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image", ".bmp": "image",
}

# 分析器 → AI 动作 + 结果展示（§3.5）
ANALYZERS: Dict[str, Dict[str, str]] = {
    "text":     {"action": "读取内容 → 总结 + 提取要点", "result": "摘要卡片"},
    "document": {"action": "解析全文 → 结构化总结", "result": "文档大纲 + 摘要"},
    "sheet":    {"action": "读取数据 → 统计分析 + 可视化建议", "result": "数据概览 + 图表建议"},
    "code":     {"action": "代码审查 → 质量评分 + 改进建议", "result": "IDE 打开 + 问题标注"},
    "image":    {"action": "视觉理解 → 内容描述 + OCR", "result": "图片 + AI 描述"},
    "other":    {"action": "读文件头 → 推断类型 → 尝试分析", "result": "分析结果或「不支持的类型」"},
}

# 文件头魔数 → 类型（§3.5 other 分支：读文件头推断）
MAGIC_ROUTES: List[tuple] = [
    (b"%PDF", "document"),
    (b"PK\x03\x04", "document"),   # docx/xlsx/pptx（zip）
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),    # jpg
    (b"GIF8", "image"),
    (b"RIFF", "image"),            # webp
]


class FileRoute:
    def __init__(self, path: str, analyzer: str) -> None:
        self.path = path
        self.analyzer = analyzer
        self.spec = ANALYZERS[analyzer]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "name": Path(self.path).name,
            "analyzer": self.analyzer,
            "action": self.spec["action"],
            "result": self.spec["result"],
        }


def route_file(path: str, read_head=None) -> FileRoute:
    """按扩展名路由；未知扩展名读文件头推断（read_head(path) 返回 bytes，缺省读 8 字节）。"""
    p = Path(path)
    ext = p.suffix.lower()
    analyzer = EXT_ROUTES.get(ext)
    if analyzer is None and p.is_file():
        try:
            head = read_head(p) if read_head is not None else p.open("rb").read(8)
            for magic, t in MAGIC_ROUTES:
                if head.startswith(magic):
                    analyzer = t
                    break
        except OSError:
            pass
    return FileRoute(path, analyzer or "other")


def route_files(paths: List[str]) -> List[Dict[str, Any]]:
    return [route_file(p).to_dict() for p in paths]


def supported_extensions() -> List[str]:
    return sorted(EXT_ROUTES.keys())
