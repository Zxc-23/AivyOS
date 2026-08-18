"""MCP filesystem Server（文档 §5.1.2 / T3.2）：路径白名单文件读写。

- 路径安全：所有相对路径在允许目录内解析，禁止逃逸（同 MemFS 策略）
- 权限：读 L0（自动）/ 写与删除 L2（MRTR 确认）
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool


class FilesystemServer:
    def __init__(self, allowed_dirs: List[Path], scratch: Optional[Path] = None) -> None:
        self.allowed = [Path(p).resolve() for p in allowed_dirs]
        if scratch is not None:
            s = Path(scratch).resolve()
            s.mkdir(parents=True, exist_ok=True)
            self.allowed.append(s)
        self.allowed = list(dict.fromkeys(self.allowed))

    def resolve(self, rel: str) -> Path:
        p = (self.allowed[0] / rel).resolve() if self.allowed else Path(rel).resolve()
        if not any(p.is_relative_to(base) for base in self.allowed):
            raise ValueError(f"路径越界（不在白名单内）: {rel}")
        return p

    # ---- 工具处理器 ----

    async def _read(self, args: Dict[str, Any]) -> ToolResult:
        try:
            p = self.resolve(args["path"])
            if not p.is_file():
                return ToolResult(False, error=f"不是文件: {args['path']}")
            content = p.read_text(encoding="utf-8", errors="replace")
            return ToolResult(True, content=content[: 1 << 16], data={"size": len(content)})
        except Exception as e:
            return ToolResult(False, error=str(e))

    async def _write(self, args: Dict[str, Any]) -> ToolResult:
        try:
            p = self.resolve(args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if args.get("append") else "w"
            with p.open(mode, encoding="utf-8") as f:
                f.write(args["content"])
            return ToolResult(True, content=f"已写入: {args['path']}")
        except Exception as e:
            return ToolResult(False, error=str(e))

    async def _list(self, args: Dict[str, Any]) -> ToolResult:
        try:
            p = self.resolve(args.get("path", "."))
            if not p.is_dir():
                return ToolResult(False, error=f"不是目录: {args.get('path')}")
            files = sorted(str(x.relative_to(p)).replace("\\", "/") for x in p.rglob("*") if x.is_file())
            return ToolResult(True, data={"files": files[:500], "count": len(files)})
        except Exception as e:
            return ToolResult(False, error=str(e))

    async def _mkdir(self, args: Dict[str, Any]) -> ToolResult:
        try:
            p = self.resolve(args["path"])
            p.mkdir(parents=True, exist_ok=True)
            return ToolResult(True, content=f"已创建目录: {args['path']}")
        except Exception as e:
            return ToolResult(False, error=str(e))

    async def _rm(self, args: Dict[str, Any]) -> ToolResult:
        try:
            p = self.resolve(args["path"])
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
            else:
                return ToolResult(False, error=f"不存在: {args['path']}")
            return ToolResult(True, content=f"已删除: {args['path']}")
        except Exception as e:
            return ToolResult(False, error=str(e))

    # ---- 工具列表 ----

    def tools(self) -> list[Tool]:
        return [
            make_tool(
                "fs_read", "读取白名单内文件", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                self._read, PermissionLevel.L0, server="filesystem",
            ),
            make_tool(
                "fs_write", "写入文件（L2，需确认）", {"type": "object", "properties": {
                    "path": {"type": "string"}, "content": {"type": "string"}, "append": {"type": "boolean"}},
                    "required": ["path", "content"]},
                self._write, PermissionLevel.L2,
                impact=lambda a: f"写入文件 {a.get('path')}（{'追加' if a.get('append') else '覆盖'}）",
                server="filesystem",
            ),
            make_tool(
                "fs_list", "列出目录文件", {"type": "object", "properties": {"path": {"type": "string"}}},
                self._list, PermissionLevel.L0, server="filesystem",
            ),
            make_tool(
                "fs_mkdir", "创建目录（L2，需确认）", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                self._mkdir, PermissionLevel.L2,
                impact=lambda a: f"创建目录 {a.get('path')}", server="filesystem",
            ),
            make_tool(
                "fs_rm", "删除文件/目录（L3，危险操作）", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                self._rm, PermissionLevel.L3,
                impact=lambda a: f"永久删除 {a.get('path')}",
                server="filesystem",
            ),
        ]
