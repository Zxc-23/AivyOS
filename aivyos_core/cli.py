"""CLI 入口（文本输入子系统之一，文档 §3.2）。

用法：
  python -m aivyos_core.cli                  # 交互式 REPL
  python -m aivyos_core.cli --once "你好"     # 单次问答（冒烟测试）
  python -m aivyos_core.cli --mode mock       # 强制 mock
  python -m aivyos_core.cli --mode local      # 强制本地（需 Ollama/vLLM）

REPL 命令：
  /new           新建会话        /persona <字段> <值>   修改人格参数
  /mem <文本>    写入记忆        /memls                 列出记忆
  /routes        查看路由状态    /sessions              列出会话
  /status        系统状态        /help /quit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config

HELP_TEXT = """可用命令：
  /new                新建会话
  /persona <字段> <值> 修改人格参数（如：/persona tone casual /persona openness 0.9）
  /mem <文本>          写入一条记忆
  /memls              列出记忆
  /routes             查看 LLM 路由状态
  /sessions           列出会话
  /status             系统状态
  /help               显示帮助
  /quit               退出"""


async def run_once(engine: ChatEngine, text: str, session_id: str | None = None) -> str:
    """单次问答，返回会话 id（供 REPL 记住当前会话）。"""
    reply = await engine.send(text, session_id=session_id)
    route = reply.route
    tag = f"[{route.mode.value}{'/fallback' if route.fallback else ''}]"
    print(f"\nAivy {tag} ({reply.model})  {reply.latency_ms:.0f}ms")
    print(f"{reply.text}\n")
    print(f"  会话: {reply.session_id}  记忆命中: {len(reply.memory_hits)}  上下文: {reply.context_stats.get('messages', 0)} msgs")
    return reply.session_id


async def repl(engine: ChatEngine) -> None:
    print("=" * 60)
    print("  AivyOS — Phase 1 核心对话闭环（Week 1）")
    print(f"  记忆后端: {engine.memory.backend_name} | 人格: {engine.persona.name}")
    print("  输入 /help 查看命令，/quit 退出")
    print("=" * 60)
    session_id: str | None = None

    while True:
        try:
            line = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not line:
            continue
        if line.startswith("/"):
            await handle_command(engine, line, session_id)
            continue
        session_id = await run_once(engine, line, session_id=session_id)


async def handle_command(engine: ChatEngine, line: str, session_id: str | None) -> None:
    parts = line.split(maxsplit=2)
    cmd = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    if cmd == "/help":
        print(HELP_TEXT)
    elif cmd == "/new":
        from aivyos_core.models import SessionState

        s = SessionState(persona_name=engine.persona.name)
        engine.save_session(s)
        print(f"已新建会话 {s.session_id}")
    elif cmd == "/persona" and len(args) >= 2:
        ok = engine.set_persona(args[0], args[1])
        print("已更新" if ok else f"无效字段/值: {args[0]}={args[1]}（Big Five 0.0-1.0；tone 枚举见文档 §4.3）")
    elif cmd == "/mem":
        if not args:
            print("用法：/mem <文本>")
            return
        rid = await engine.memory.add(" ".join(args))
        print(f"记忆已写入: {rid}")
    elif cmd == "/memls":
        hits = await engine.memory.get_all()
        if not hits:
            print("（暂无记忆）")
        for h in hits[-20:]:
            print(f"  [{h.created_at}] {h.text[:80]}")
    elif cmd == "/routes":
        for r in engine.router.backends_status():
            print(f"  {r['mode']:6s} {r['model']:20s} 可用={r['available']}")
        print(f"  路由模式: {engine.config['llm'].get('mode', 'auto')}")
    elif cmd == "/sessions":
        for s in engine.list_sessions()[:10]:
            print(f"  {s['session_id']}  msgs={s['messages']}  更新={s['updated_at']}")
    elif cmd == "/status":
        print(json.dumps(engine.status(), ensure_ascii=False, indent=2))
    elif cmd == "/quit":
        print("再见。")
        raise SystemExit(0)
    else:
        print(f"未知命令: {cmd}（/help 查看）")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AivyOS AI 核心 CLI（Phase 1 Week 1）")
    parser.add_argument("--config", default=None, help="配置文件路径（yaml/json）")
    parser.add_argument("--mode", choices=["auto", "local", "cloud", "mock"], default=None)
    parser.add_argument("--once", default=None, help="单次问答后退出（冒烟测试）")
    parser.add_argument("--session", default=None, help="指定会话 id")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    if args.mode:
        cfg["llm"]["mode"] = args.mode

    engine = ChatEngine(cfg)
    if args.once:
        asyncio.run(run_once(engine, args.once, args.session))
    else:
        asyncio.run(repl(engine))


if __name__ == "__main__":
    main()
