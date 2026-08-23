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
  /claude <需求>  Claude 实现    /codex <提示>  调用 Codex
  /review        Codex 审查      /compare <问题> 双模型对比   /vscode <路径> VS Code 打开
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
  /memfs              查看 MemFS 记忆文件（§8.1）
  /recover            启动上下文重建（§8.2 三重恢复）
  /routes             查看 LLM 路由状态
  /sessions           列出会话
  /status             系统状态
  /claude <需求>       调用 Claude Code 实现（双模型工作台）
  /codex <提示>        调用 Codex / ChatGPT
  /review             用 Codex 审查最近一次 Claude 输出
  /compare <问题>      并行调用双模型并对比
  /vscode <路径>       在 VS Code 打开文件/目录
  /help               显示帮助
  /quit               退出"""


def _get_workbench(engine: ChatEngine):
    """惰性创建 WorkbenchService（挂在 engine 上复用内存态）。"""
    wb = getattr(engine, "_workbench", None)
    if wb is None:
        from aivyos_core.workbench.service import WorkbenchService

        wb = WorkbenchService(engine.config)
        engine._workbench = wb
    return wb


def _print_agent_result(res) -> None:
    if res.ok:
        print(res.output or "（无输出）")
        print(f"  [{res.agent}] 退出码 {res.exit_code}  耗时 {res.elapsed_s:.1f}s")
    else:
        print(f"  [{res.agent}] 失败: {res.error}")


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
    elif cmd == "/memfs":
        files = engine.memfs.list()
        print(f"MemFS 文件（{len(files)} 个）:")
        for rel in files:
            content = engine.memfs.read(rel)
            lines = [l for l in content.splitlines() if l.startswith("- [")]
            print(f"  {rel}  ({len(lines)} 条记忆 / {len(content)} 字符)")
        if args:
            rel = args[0]
            print(f"\n--- {rel} ---")
            print(engine.memfs.read(rel)[:800])
    elif cmd == "/recover":
        summary = await engine.restore_on_boot()
        print(summary.summary_text)
        if summary.workflow_checkpoint:
            print(f"  可续传: {summary.workflow_checkpoint['node']} @ {summary.workflow_checkpoint['thread_id']}")
    elif cmd == "/routes":
        for r in engine.router.backends_status():
            print(f"  {r['mode']:6s} {r['model']:20s} 可用={r['available']}")
        print(f"  路由模式: {engine.config['llm'].get('mode', 'auto')}")
    elif cmd == "/sessions":
        for s in engine.list_sessions()[:10]:
            print(f"  {s['session_id']}  msgs={s['messages']}  更新={s['updated_at']}")
    elif cmd == "/status":
        print(json.dumps(engine.status(), ensure_ascii=False, indent=2))
    elif cmd == "/claude":
        if not args:
            print("用法：/claude <需求>")
            return
        wb = _get_workbench(engine)
        print("Claude Code 执行中（可能耗时较长）...")
        _print_agent_result(await wb.run_claude(" ".join(args)))
        if wb.last_notice:
            print(f"  提示: {wb.last_notice}")
    elif cmd == "/codex":
        if not args:
            print("用法：/codex <提示>")
            return
        wb = _get_workbench(engine)
        print("Codex 执行中（可能耗时较长）...")
        _print_agent_result(await wb.run_codex(" ".join(args)))
        if wb.last_notice:
            print(f"  提示: {wb.last_notice}")
    elif cmd == "/review":
        wb = _get_workbench(engine)
        print("Codex 审查中...")
        _print_agent_result(await wb.review())
    elif cmd == "/compare":
        if not args:
            print("用法：/compare <问题>")
            return
        wb = _get_workbench(engine)
        print("双模型并行执行中...")
        results = await wb.compare(" ".join(args))
        for agent in ("claude", "codex"):
            r = results[agent]
            print(f"\n--- {agent} ({'成功' if r['ok'] else '失败'}) ---")
            print(r["output"] if r["ok"] else r["error"])
    elif cmd == "/vscode":
        if not args:
            print("用法：/vscode <路径>")
            return
        _print_agent_result(await _get_workbench(engine).open_vscode(args[0]))
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
