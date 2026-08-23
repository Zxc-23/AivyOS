"""MCP 交互 CLI — `python -m aivyos_core.mcp`。

用法：
  python -m aivyos_core.mcp list                  # 列出工具
  python -m aivyos_core.mcp call fs_read '{"path":"config.py"}'
  python -m aivyos_core.mcp server --port 31889   # 起 TCP 服务
  python -m aivyos_core.mcp shell                  # 交互式工具控制台（含 MRTR 确认）

工具名 @ 参数示例：`call shell_run '{"command":"echo hi"}'` —— L2 工具会弹出确认。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

from aivyos_core.config import ensure_home, load_config
from aivyos_core.mcp.manager import ToolManager
from aivyos_core.mcp.server import McpServer
from aivyos_core.mcp.servers import (
    BrowserServer, CodeExecServer, FilesystemServer, MemoryServer,
    OfficeServer, ScreenshotServer, SearchServer, ShellServer, WorkbenchServer,
)
from aivyos_core.mcp.types import MRTRRequest, PermissionLevel, ToolResult

SERVERS = {
    "filesystem": lambda cfg, home: FilesystemServer(
        allowed_dirs=[home] + [Path(p).expanduser() for p in cfg.get("allowed_dirs", [])],
        scratch=home / cfg.get("scratch_dir", ".aivyos_mcp_scratch"),
    ),
    "shell": lambda cfg, home: ShellServer(
        timeout_s=cfg.get("shell_timeout_s", 30), max_output=cfg.get("shell_max_output", 8192),
    ),
    "code_exec": lambda cfg, home: CodeExecServer(
        scratch_dir=home / cfg.get("scratch_dir", ".aivyos_mcp_scratch"),
        docker_image=cfg.get("docker_image"),
    ),
    "browser": lambda cfg, home: BrowserServer(),
    "office": lambda cfg, home: OfficeServer(home / cfg.get("scratch_dir", ".aivyos_mcp_scratch") / "office"),
    "search": lambda cfg, home: SearchServer(searxng_url=cfg.get("searxng_url")),
    "screenshot": lambda cfg, home: ScreenshotServer(),
    "memory": None,  # 需要 engine.memory，由 build_manager 注入
    "workbench": lambda cfg, home: WorkbenchServer(),
}


def build_manager(cfg: dict, engine=None) -> ToolManager:
    home = ensure_home(cfg)
    mcp_cfg = cfg.get("mcp", {})
    mgr = ToolManager(
        auto_approve=bool(mcp_cfg.get("mrtr_auto_approve", False)),
        mrtr_ttl_s=float(mcp_cfg.get("mrtr_ttl_s", 60)),
    )
    enabled = mcp_cfg.get("enabled_servers", list(SERVERS.keys()))
    if "memory" in enabled and engine is None:
        from aivyos_core.chat.engine import ChatEngine

        engine = ChatEngine(cfg)
    for name in enabled:
        if name not in SERVERS:
            continue
        try:
            server = SERVERS[name](mcp_cfg, home) if name != "memory" else MemoryServer(engine.memory)
            mgr.add_server(server)
        except Exception as e:
            # 优雅降级：单个 server 构建失败（如权限/依赖缺失）不阻塞其他工具
            log.warning("MCP server %s 构建失败，已跳过: %s", name, e)
    return mgr


def _print_result(result) -> None:
    if isinstance(result, MRTRRequest):
        print(f"\n⛔ [需要确认] {result.tool}\n   影响: {result.impact}")
        print(f"    请求ID: {result.request_id}")
        return
    if isinstance(result, ToolResult):
        print(f"[{'✓' if result.ok else '✗'}] {result.content or result.error}")
        if result.data:
            print(json.dumps(result.data, ensure_ascii=False)[:500])
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def cmd_call(mgr: ToolManager, name: str, args_json: str, auto_yes: bool) -> None:
    try:
        arguments = json.loads(args_json)
    except json.JSONDecodeError:
        print("参数 JSON 解析失败")
        return
    result = await mgr.call_tool(name, arguments)
    if isinstance(result, MRTRRequest):
        approved = auto_yes
        if not auto_yes:
            print(f"影响: {result.impact}")
            approved = input("是否允许？[y/N] ").strip().lower() in ("y", "yes")
        out = await mgr.confirm(result.request_id, approved)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        _print_result(result)


async def cmd_shell(mgr: ToolManager, cfg: dict) -> None:
    print("AivyOS MCP 工具控制台（/help 查看）")
    print(f"工具数: {len(mgr.tools)} | 输入 /quit 退出")
    while True:
        try:
            line = input("\nmcp> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line == "/list":
            for t in mgr.list_tools():
                print(f"  {t['name']:18s} [{t.get('inputSchema', {}).get('type', '')}] {t['description'][:40]}")
            continue
        if line == "/pending":
            for p in mgr.pending_requests():
                print(f"  {p['request_id']}: {p['tool']} — {p['impact']}")
            continue
        if line.startswith("call "):
            parts = line[5:].split(maxsplit=1)
            if len(parts) != 2:
                print("用法: call <工具名> '<json 参数>'")
                continue
            await cmd_call(mgr, parts[0], parts[1], auto_yes=False)
            continue
        print("命令: call <name> '<json>' | /list | /pending | /quit")


async def cmd_server(mgr: ToolManager, cfg: dict, port: int) -> None:
    server = McpServer(mgr.tools, mrtr_ttl_s=float(cfg.get("mcp", {}).get("mrtr_ttl_s", 60)))
    tcp = await server.serve_tcp(port=port)
    print(f"MCP TCP 服务: 127.0.0.1:{port}（{len(server.tools)} 工具）Ctrl+C 停止")
    try:
        await asyncio.Event().wait()
    finally:
        tcp.close()
        await tcp.wait_closed()


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="AivyOS MCP 工具层")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list")
    p_call = sub.add_parser("call")
    p_call.add_argument("name")
    p_call.add_argument("args", default="{}")
    p_call.add_argument("-y", "--yes", action="store_true", help="自动确认 L2+ 工具")
    sub.add_parser("shell")
    p_srv = sub.add_parser("server")
    p_srv.add_argument("--port", type=int, default=31889)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    mgr = build_manager(cfg)

    if args.cmd == "list":
        for t in mgr.list_tools():
            print(f"  {t['name']:18s} {t['description']}")
    elif args.cmd == "call":
        asyncio.run(cmd_call(mgr, args.name, args.args, args.yes))
    elif args.cmd == "shell":
        asyncio.run(cmd_shell(mgr, cfg))
    elif args.cmd == "server":
        asyncio.run(cmd_server(mgr, cfg, args.port))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
