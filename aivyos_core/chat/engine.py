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
from aivyos_core.emotion import EmotionTagger
from aivyos_core.llm.router import ModelRouter
from aivyos_core.memfs import MemFS
from aivyos_core.memory.manager import MemoryManager
from aivyos_core.models import (
    AssistantReply,
    LLMRequest,
    RouteDecision,
    SessionState,
)
from aivyos_core.multimodal import MultimodalFusion
from aivyos_core.notification import Notifier, create_notifier
from aivyos_core.output import OutputRouter
from aivyos_core.persona import Persona
from aivyos_core.recovery import BootRecovery, RecoverySummary
from aivyos_core.summary import LLMSummarizer
from aivyos_core.vision.service import VisionService

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
        self.memory.router = self.router  # 事实抽取 LLM 通道（A2）
        # §4.4.2 中期摘要：真实 LLM 可用则 LLM，否则朴素回退（A1 清理）
        self.summarizer = LLMSummarizer(self.router, backend=config.get("chat", {}).get("summarize_backend", "auto"))
        # Week 3：Agent 记忆文件系统（§8.1 MemFS，跨重启存活）
        memfs_cfg = config.get("memfs", {})
        self.memfs = MemFS(self.home / memfs_cfg.get("root", "memfs"))
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
        self.recovery = BootRecovery(self)

        # ---- Phase 1 收尾：视觉 / 多模态 / 输出（§3.3 / §3.4 / §6.3）----
        self.vision = VisionService(config.get("vision", {}))
        mm_cfg = config.get("multimodal", {})
        self.fusion = MultimodalFusion(
            self.vision,
            strategy=mm_cfg.get("fusion_strategy", "late"),
            max_vision_tokens=int(mm_cfg.get("max_vision_tokens", 2048)),
        )
        self.emotion = EmotionTagger(enabled=bool(config.get("emotion", {}).get("tags_enabled", True)))
        self.notifier: Notifier = create_notifier(config.get("output", {}))
        self.output = OutputRouter(config.get("output", {}), tts=None, notifier=self.notifier)

    # ---- 启动恢复（§8.2）----

    async def restore_on_boot(self) -> RecoverySummary:
        """重启后三重恢复：记忆 + MemFS + 工作流检查点。"""
        return await self.recovery.restore_on_boot()

    # ---- 会话生命周期 ----

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def load_session(self, session_id: Optional[str] = None) -> SessionState:
        if session_id and self._session_path(session_id).exists():
            data = json.loads(self._session_path(session_id).read_text(encoding="utf-8"))
            state = SessionState.from_snapshot(data)
        elif session_id:
            # 用户显式指定了 session_id 但文件不存在 → 用该 id 创建新会话（实现续接/命名会话）
            state = SessionState(persona_name=self.persona.name, session_id=session_id)
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

    async def send(self, text: str, session_id: Optional[str] = None, extra_blocks: Optional[List[str]] = None) -> AssistantReply:
        return await self._send(text, session_id=session_id, extra_blocks=extra_blocks)

    async def send_multimodal(
        self,
        text: str = "",
        image: Optional[bytes] = None,
        audio_text: str = "",
        session_id: Optional[str] = None,
        extra_blocks: Optional[List[str]] = None,
    ) -> AssistantReply:
        """多模态输入（§3.4 晚期融合，T1.8）：文本/图像/语音文本 → 统一上下文 → LLM。

        extra_blocks：附加上下文块（如技能提示词），追加到融合块之后。
        """
        fused = await self.fusion.fuse(text=text, audio_text=audio_text, image=image)
        main_text = fused.text or (audio_text or text)
        blocks = fused.system_blocks()
        if extra_blocks:
            blocks = blocks + list(extra_blocks)
        reply = await self._send(main_text, session_id=session_id, extra_blocks=blocks)
        return reply

    async def _send(
        self,
        text: str,
        session_id: Optional[str] = None,
        extra_blocks: Optional[List[str]] = None,
    ) -> AssistantReply:
        start = time.perf_counter()

        # 1) 自动记忆抽取（朴素规则，§4.2）+ MemFS 事实归档（§8.1）
        extracted = None
        if self.config.get("memory", {}).get("auto_extract", True):
            extracted = await self.memory.try_extract(text, {"session": session_id or ""})
            if extracted:
                self.memfs.remember(text, category="facts.md")

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

        # 5) 上下文组装（§4.4 + §3.4 多模态块）
        messages, ctx_stats = self.context.build_messages(
            persona_prompt=self.persona.render_system_prompt(),
            memory_hits=hit_dicts,
            history=history,
            current_input=text,
            archive_callback=lambda old: self._archive_turns(old, state.session_id),
            extra_blocks=extra_blocks,
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
        """远期归档（§4.4.2）：旧轮次 LLM 摘要 → 写入记忆（真实后端不可用则朴素摘要）。"""
        import asyncio

        async def _do():
            summary = await self.summarizer.summarize(list(old_turns))
            await self.memory.add(f"[会话归档 {session_id}] {summary}", {"kind": "archive"})

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_do())

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
            "memfs": self.memfs.summary(),
            "vision": self.vision.status(),
            "output_channel": self.output.default_channel.value,
            "emotion_tags": self.emotion.enabled,
        }
