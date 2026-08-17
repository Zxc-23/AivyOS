"""对话引擎：编排人格 / 记忆 / 上下文 / 路由 / 会话持久化。

对应文档：§4.2 记忆检索 → §4.3 人格 → §4.4 上下文组装 → §4.1 路由推理 →
§14.3 会话快照（JSON 序列化，可恢复）。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aivyos_core.config import ensure_home
from aivyos_core.context import ContextManager
from aivyos_core.llm.router import ModelRouter
from aivyos_core.memory.manager import MemoryManager
from aivyos_core.models import (
    AssistantReply,
    LLMRequest,
    RouteDecision,
    SessionState,
)
from aivyos_core.persona import Persona

log = logging.getLogger(__name__)


class ChatEngine:
    """Phase 1 核心对话闭环。"""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.home = ensure_home(config)
        self.sessions_dir = self.home / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self.persona = Persona.from_config(config.get("persona", {}))
        self.memory = MemoryManager(config.get("memory", {}), self.home)
        self.router = ModelRouter(config.get("llm", {}))
        chat_cfg = config.get("chat", {})
        self.context = ContextManager(
            context_window=chat_cfg.get("context_window", 32768),
            history_turns=chat_cfg.get("history_turns", 12),
            summarize_from_turn=chat_cfg.get("summarize_from_turn", 12),
            system_prompt_tokens=chat_cfg.get("system_prompt_tokens", 2048),
            memory_tokens=chat_cfg.get("memory_tokens", 8192),
            max_input_tokens=chat_cfg.get("max_input_tokens", 4096),
            output_reserve_tokens=chat_cfg.get("output_reserve_tokens", 8192),
        )

    # ---- 会话生命周期 ----

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def load_session(self, session_id: Optional[str] = None) -> SessionState:
        if session_id and self._session_path(session_id).exists():
            data = json.loads(self._session_path(session_id).read_text(encoding="utf-8"))
            state = SessionState.from_snapshot(data)
        else:
            state = SessionState(persona_name=self.persona.name)
        return state

    def save_session(self, state: SessionState) -> None:
        """原子写（临时文件 + rename），对应 §14.3 快照可恢复。"""
        path = self._session_path(state.session_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def list_sessions(self) -> List[Dict[str, Any]]:
        out = []
        for p in sorted(self.sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                out.append(
                    {
                        "session_id": data.get("session_id"),
                        "messages": len(data.get("messages", [])),
                        "updated_at": data.get("updated_at"),
                    }
                )
            except Exception:
                continue
        return out

    def reset_session(self, session_id: str) -> None:
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()

    # ---- 核心对话 ----

    async def send(self, text: str, session_id: Optional[str] = None) -> AssistantReply:
        start = time.perf_counter()

        # 1) 自动记忆抽取（朴素规则，§4.2）
        extracted = None
        if self.config.get("memory", {}).get("auto_extract", True):
            extracted = await self.memory.try_extract(text, {"session": session_id or ""})

        # 2) 会话加载 + 历史
        state = self.load_session(session_id)
        history = state.recent(max(0, len(state.messages)))

        # 3) 记忆检索（§4.4.1 检索记忆块）
        hits = await self.memory.search(text, top_k=self.context.memory_tokens and 5)
        hit_dicts = [h.to_dict() for h in hits]

        # 4) 路由决策（§4.1.3）
        decision = self.router.route(text, context_len=sum(len(m.content) for m in history))
        if extracted:
            decision = RouteDecision(
                mode=decision.mode, model=decision.model,
                reason=decision.reason + "；本次触发了记忆抽取",
                fallback=decision.fallback,
            )

        # 5) 上下文组装（§4.4）
        messages, ctx_stats = self.context.build_messages(
            persona_prompt=self.persona.render_system_prompt(),
            memory_hits=hit_dicts,
            history=history,
            current_input=text,
            archive_callback=lambda old: self._archive_turns(old, state.session_id),
        )

        # 6) 推理（真实后端失败自动降级 mock）
        request = LLMRequest(
            messages=messages,
            model=decision.model,
            max_tokens=self.context.output_reserve_tokens,
            temperature=0.7,
        )
        response = await self.router.complete(request, decision)

        # 7) 写回会话 + 持久化
        state.add("user", text)
        state.add("assistant", response.text)
        self.save_session(state)

        latency_ms = (time.perf_counter() - start) * 1000
        return AssistantReply(
            text=response.text,
            session_id=state.session_id,
            model=response.model,
            route=decision,
            latency_ms=latency_ms,
            memory_hits=hit_dicts[:3],
            context_stats=ctx_stats,
        )

    def _archive_turns(self, old_turns, session_id: str) -> None:
        """远期归档：旧轮次写入记忆（§4.4.2 远期归档）。"""
        summary = "；".join(f"{m.role}: {m.content[:60]}" for m in old_turns[-4:])
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.memory.add(f"[会话归档 {session_id}] {summary}", {"kind": "archive"}))

    # ---- 人格调整（CLI/托盘入口）----

    def set_persona(self, field: str, value: Any) -> bool:
        return self.persona.update(field, value)

    def status(self) -> Dict[str, Any]:
        return {
            "backend": self.memory.backend_name,
            "routes": self.router.backends_status(),
            "persona": self.persona.to_dict(),
            "home": str(self.home),
            "sessions": len(self.list_sessions()),
        }
