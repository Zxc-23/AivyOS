"""工作流演示：`python -m aivyos_core.workflow --demo "天气网页" [--resume]`。

- 首次运行：VibeCoding 图（§4.5.2）从 understand 跑到 save_memory，节点轨迹 + 检查点落库
- --resume：从最后检查点续传（模拟中断后恢复）
- 请求含"失败"可观察 build→generate 条件回环（上限 2 次）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from aivyos_core.config import ensure_home, load_config
from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.workflows import build_vibe_coding_graph, stop_preview_server


async def run(request: str, resume: bool, cfg: dict, executor: str = "demo") -> None:
    home = ensure_home(cfg)
    ckpt = SqliteCheckpointer(home / cfg["workflow"]["checkpoint_db"])
    graph = build_vibe_coding_graph(ckpt).compile(checkpointer=ckpt)
    thread = cfg["workflow"]["thread_prefix"] + "vibe"

    wf_cfg = cfg["workflow"]
    ctx = {
        "executor": executor,
        "workspace": home / wf_cfg.get("workspace", ".aivyos_workspace"),
        "build_command": wf_cfg.get("build_command"),
        "preview": wf_cfg.get("preview", True),
    }

    print(f"用户需求: {request}  [执行器: {executor}]")
    if resume:
        print("== 从检查点续传 ==")
        state = await graph.resume(thread, ctx=ctx)
    else:
        print("== 首次执行 ==")
        state = await graph.invoke({"user_request": request}, thread_id=thread, ctx=ctx)

    print("节点轨迹:", " → ".join(graph.last_trace))
    print("最终状态:")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    print(f"\n检查点线程: {thread} | 库: {ckpt.path}")
    stop_preview_server(state)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AivyOS VibeCoding 工作流演示")
    parser.add_argument("--demo", default="做一个天气网页", help="用户需求文本")
    parser.add_argument("--resume", action="store_true", help="从检查点续传")
    parser.add_argument("--executor", choices=["demo", "local"], default=None, help="执行器（默认取配置）")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    executor = args.executor or cfg["workflow"].get("executor", "demo")
    asyncio.run(run(args.demo, args.resume, cfg, executor))


if __name__ == "__main__":
    main()
