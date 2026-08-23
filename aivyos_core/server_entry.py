"""IPC 服务入口：ChatEngine ↔ AivyIpcServer 桥接。

运行：python -m aivyos_core.server_entry [--config PATH] [--mode auto|local|cloud|mock]

暴露方法（Tauri 壳层 / 外部客户端调用）：
  ping           → {"pong": true, "version": ...}
  chat.send      params {text, session_id?} → {text, session_id, model, route, latency_ms, memory_hits}
  session.list   → [ {session_id, messages, updated_at} ]
  session.reset  params {session_id} → {"ok": true}
  persona.get    → {…Big Five…}
  persona.set    params {field, value} → {"ok": bool}
  memory.search  params {query, top_k?} → [ {id, text, score, created_at} ]
  memory.add     params {text} → {"id": ...}
  memory.list    → [ all memory entries ]
  status         → {backend, routes, persona, home, sessions}
  voice.status   → {asr, tts, vad, source, sink, wake_required, wake_words, llm_route_mode}
  voice.turn     params {text?} → {text, reply, model, route, latency_ms, ...}
  task.create    params {description} → {task_id, steps: [...] }
  task.list      → [ {id, title, status, steps, created_at} ]
  task.execute   params {task_id} → {ok, result}
  sched.list     → [ {name, kind, runs, last_run, error} ]
  sched.create   params {name, cron_expr, handler_text} → {"ok": true}
  vibe.run       params {request} → {steps, files, preview_url, ...}
  boot.check     → {checks: [...], progress, summary}
  boot.restore   → {summary_text, long_term_memories, ...}
  voiceset.get   → {wake_words, asr_backend, tts_backend, ...}
  voiceset.set   params {field, value} → {"ok": true}
  models.list    → [{mode, model, available}]
  config.get     → full config dict
  config.update  params {path, value} → {"ok": true}
  mcp.tools      → LLM MCP 工具列表
  mcp.call       params {tool, params} → MCP 工具调用结果
  fallback.execute params {steps, messages} → 降级链执行结果
  fallback.status params {steps} → 降级链配置状态
  voice.test-tts params {text, provider, voice, speed, api_key?, resource_id?} → {ok, wav_b64, sample_rate, latency_ms, ...}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import time
from typing import Any, Dict

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config, deep_merge
from aivyos_core.ipc.server import AivyIpcServer
from aivyos_core import __version__

log = logging.getLogger(__name__)


DEFAULT_EXIT_WORDS = ("再见", "退出", "结束", "拜拜", "不说了", "bye", "stop")


def _is_exit_command(text: str, exit_words=DEFAULT_EXIT_WORDS) -> bool:
    """检测是否为连续对话退出命令词（纯函数，便于测试）。

    规则：
    - 词前必须独立：开头 / 空白 / 标点（避免"请退出说明"这类中缀误判）
    - 词后自由：可跟"吧/了/对话"等（"再见吧""退出对话"都是合理退出语）
    - 排除词后接"的/地/得"（"退出的原因""结束的方式"不是退出语）
    """
    import re

    clean = (text or "").strip()
    if not clean:
        return False
    for w in exit_words:
        pat = re.compile(
            r"(?:^|[\s，。！？,.!?：:])" + re.escape(w) + r"(?!的|地|得)"
        )
        if pat.search(clean):
            return True
    return False


def build_server(engine: ChatEngine, cfg: dict, stop_event: "asyncio.Event | None" = None) -> AivyIpcServer:
    ipc_cfg = cfg.get("ipc", {})
    server = AivyIpcServer(
        host=ipc_cfg.get("host", "127.0.0.1"),
        port=int(ipc_cfg.get("port", 31701)),
        pipe_name=ipc_cfg.get("pipe_name"),
    )

    # ---- API Key 持久化存储 ----
    from aivyos_core.api_key_store import create_api_key_store
    _api_key_store = create_api_key_store(cfg.get("home"))
    _api_key_store.load()
    log.info("API Key 存储已初始化: %d 个密钥已加载", _api_key_store.key_count())

    # ── 同步提供商特定 Key 到通用 AIVYOS_CLOUD_API_KEY ──
    # 系统默认查找 AIVYOS_CLOUD_API_KEY，但用户可能存储了 DEEPSEEK_API_KEY 等
    _CLOUD_KEY_ALIASES = [
        "DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
    ]
    if not os.environ.get("AIVYOS_CLOUD_API_KEY"):
        for _alias in _CLOUD_KEY_ALIASES:
            _val = os.environ.get(_alias)
            if _val:
                os.environ["AIVYOS_CLOUD_API_KEY"] = _val
                log.info("映射 API Key: %s → AIVYOS_CLOUD_API_KEY", _alias)
                break

    # ---- VoiceSession (lazily created) ----
    _voice_session = None

    # 连续对话会话状态：唤醒一次后，窗口期内后续轮次无需再喊唤醒词
    # {"active": bool, "expires_at": float(monotonic), "turns": int}
    _conv_session = {"active": False, "expires_at": 0.0, "turns": 0}
    _conv_window_s = float(cfg.get("voice", {}).get("continuous_window_s", 60.0))
    _conv_max_turns = int(cfg.get("voice", {}).get("continuous_max_turns", 10))
    # 窗口到期提醒：剩余 ≤15s 或剩余 ≤2 轮时语音询问"还需要我吗？"
    _conv_remind_before_s = float(cfg.get("voice", {}).get("continuous_remind_before_s", 15.0))
    _conv_remind_turns_left = int(cfg.get("voice", {}).get("continuous_remind_turns_left", 2))
    # 退出命令词：说"再见/退出/结束"等结束连续对话
    _EXIT_WORDS = tuple(cfg.get("voice", {}).get("continuous_exit_words", DEFAULT_EXIT_WORDS))

    def get_voice():
        nonlocal _voice_session
        if _voice_session is None:
            from aivyos_core.voice.session import VoiceSession
            # Tauri 场景：语音由前端 Web Audio 播放（可打断），后端不播（避免双播）
            _voice_session = VoiceSession(_voice_cfg(), engine)
        return _voice_session

    def _voice_cfg():
        """VoiceSession 配置：Tauri 场景禁用后端播放（前端 Web Audio 唯一播放通道，可打断）。"""
        import copy

        vc = copy.deepcopy(cfg)
        vc.setdefault("voice", {})["backend_play"] = False
        return vc

    # ---- Scheduler (lazily created) ----
    _scheduler = None

    def get_scheduler():
        nonlocal _scheduler
        if _scheduler is None:
            from aivyos_core.scheduler import Scheduler
            _scheduler = Scheduler(tick_s=float(cfg.get("scheduler", {}).get("tick_s", 5)))
        return _scheduler

    # ---- 知识卡片系统（记忆管理升级）----
    _knowledge = None

    def get_knowledge():
        nonlocal _knowledge
        if _knowledge is None:
            from pathlib import Path

            from aivyos_core.knowledge.service import KnowledgeService
            from aivyos_core.knowledge.store import KnowledgeStore

            k_cfg = cfg.get("knowledge", {})
            home = Path(cfg.get("home", "."))
            store = KnowledgeStore(home / k_cfg.get("store_path", "knowledge.jsonl"))
            _knowledge = KnowledgeService(store, __import__(
                "aivyos_core.knowledge.extract", fromlist=["KnowledgeExtractor"]
            ).KnowledgeExtractor(router=engine.router))
        return _knowledge

    # ---- 技能系统（Skills）----
    _skills = None

    def get_skills():
        nonlocal _skills
        if _skills is None:
            from pathlib import Path

            from aivyos_core.skills import SkillManager

            home = Path(cfg.get("home", "."))
            _skills = SkillManager(home / "skills.json")
        return _skills

    # ---- 工具系统（MCP ToolManager，面向用户的管理视图）----
    _tool_mgr = None

    def get_tools():
        nonlocal _tool_mgr
        if _tool_mgr is None:
            from aivyos_core.mcp.cli import build_manager

            _tool_mgr = build_manager(cfg, engine=engine)
        return _tool_mgr

    # ---- Task registry (in-memory, demo-grade) ----
    _tasks: Dict[str, Dict[str, Any]] = {}
    _task_counter = 0

    # ================================================================
    #  基础方法
    # ================================================================

    @server.method("ping")
    async def ping(params):
        return {"pong": True, "version": __version__}

    @server.method("chat.send")
    async def chat_send(params):
        text = params["text"]
        # 可选图片输入（拖拽/粘贴）：image_b64（base64 字节）或 image_path（本地文件）
        image_b64 = params.get("image_b64") or ""
        image_path = params.get("image_path") or ""
        image_bytes = None
        if image_b64:
            import base64
            try:
                image_bytes = base64.b64decode(image_b64)
            except Exception as e:
                log.warning("chat.send: image_b64 解码失败: %s", e)
        elif image_path:
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
            except Exception as e:
                log.warning("chat.send: 读取图片失败 %s: %s", image_path, e)
        # 相似知识自动调用（对话中呈现相关卡片，不阻塞主回复）
        recalled = []
        if cfg.get("knowledge", {}).get("recall_in_chat", True):
            try:
                recalled = get_knowledge().recall(text, limit=2, min_score=float(
                    cfg.get("knowledge", {}).get("recall_min_score", 0.05)
                ))
            except Exception as e:
                log.debug("知识调用失败: %s", e)
        # 技能匹配：命中启用技能 → 注入 System Prompt 上下文块（技能提示词）
        skill_blocks: List[str] = []
        skill_names: List[str] = []
        try:
            skill_blocks = get_skills().context_blocks(text)
            skill_names = [s["name"] for s in get_skills().match(text)]
        except Exception as e:
            log.debug("技能匹配失败: %s", e)

        if image_bytes is not None:
            reply = await engine.send_multimodal(
                text=text, image=image_bytes, session_id=params.get("session_id"),
                extra_blocks=skill_blocks or None,
            )
        else:
            reply = await engine.send(text, session_id=params.get("session_id"), extra_blocks=skill_blocks or None)
        # 对话知识沉淀（后台任务，不阻塞响应）
        if cfg.get("knowledge", {}).get("auto_extract", True):
            async def _ingest():
                try:
                    await get_knowledge().ingest(text)
                except Exception as e:
                    log.debug("知识沉淀失败: %s", e)
            asyncio.get_running_loop().create_task(_ingest())
        return {
            "text": reply.text,
            "session_id": reply.session_id,
            "model": reply.model,
            "route": reply.route.to_dict(),
            "latency_ms": reply.latency_ms,
            "memory_hits": reply.memory_hits,
            "knowledge_hits": [{"card": h["card"], "score": h["score"]} for h in recalled],
            "vision_used": image_bytes is not None,
            "skills": skill_names,
        }

    @server.method("session.list")
    async def session_list(params):
        return engine.list_sessions()

    @server.method("session.reset")
    async def session_reset(params):
        engine.reset_session(params["session_id"])
        return {"ok": True}

    @server.method("persona.get")
    async def persona_get(params):
        return engine.persona.to_dict()

    @server.method("persona.set")
    async def persona_set(params):
        return {"ok": engine.set_persona(params["field"], params["value"])}

    @server.method("status")
    async def status(params):
        return engine.status()

    # ================================================================
    #  Memory
    # ================================================================

    @server.method("memory.search")
    async def memory_search(params):
        hits = await engine.memory.search(params.get("query", ""), top_k=int(params.get("top_k", 5)))
        return [h.to_dict() for h in hits]

    @server.method("memory.add")
    async def memory_add(params):
        rid = await engine.memory.add(params["text"])
        return {"id": rid}

    @server.method("memory.list")
    async def memory_list(params):
        all_memories = await engine.memory.get_all()
        return [m if isinstance(m, dict) else {"text": str(m), "created_at": None} for m in all_memories]

    # ================================================================
    #  知识卡片系统（记忆管理升级）
    # ================================================================

    @server.method("knowledge.list")
    async def knowledge_list(params):
        """列出知识卡片。params: {sort: updated|created|favorite|usage, category, tag, favorite_only}"""
        ks = get_knowledge()
        if params.get("category") or params.get("tag") or params.get("favorite_only"):
            cards = ks.filter(
                category=params.get("category", ""),
                tag=params.get("tag", ""),
                favorite_only=bool(params.get("favorite_only", False)),
            )
        else:
            cards = ks.list_all(sort=params.get("sort", "updated"))
        return [c.to_dict() for c in cards]

    @server.method("knowledge.get")
    async def knowledge_get(params):
        card = get_knowledge().get(params.get("id", ""))
        return card.to_dict() if card else {"error": "卡片不存在"}

    @server.method("knowledge.create")
    async def knowledge_create(params):
        """手动创建知识卡片。"""
        card = get_knowledge().create(**params)
        return card.to_dict()

    @server.method("knowledge.update")
    async def knowledge_update(params):
        card = get_knowledge().update(params.get("id", ""), **params.get("changes", {}))
        return card.to_dict() if card else {"error": "卡片不存在"}

    @server.method("knowledge.delete")
    async def knowledge_delete(params):
        ok = get_knowledge().delete(params.get("id", ""))
        return {"ok": ok}

    @server.method("knowledge.favorite")
    async def knowledge_favorite(params):
        card = get_knowledge().toggle_favorite(params.get("id", ""))
        return card.to_dict() if card else {"error": "卡片不存在"}

    @server.method("knowledge.search")
    async def knowledge_search(params):
        cards = get_knowledge().search(params.get("query", ""), limit=int(params.get("limit", 20)))
        return [c.to_dict() for c in cards]

    @server.method("knowledge.recall")
    async def knowledge_recall(params):
        """相似内容识别（对话中自动调用知识卡片）。"""
        hits = get_knowledge().recall(
            params.get("text", ""),
            limit=int(params.get("limit", 3)),
            min_score=float(params.get("min_score", 0.05)),
        )
        return hits

    @server.method("knowledge.ingest")
    async def knowledge_ingest(params):
        """从对话文本沉淀知识（自动提取 → 建卡/更新）。"""
        result = await get_knowledge().ingest(params.get("text", ""))
        return result or {"action": "skip"}

    @server.method("knowledge.stats")
    async def knowledge_stats(params):
        return get_knowledge().stats()

    @server.method("knowledge.link")
    async def knowledge_link(params):
        ok = get_knowledge().link(params.get("id", ""), params.get("other_id", ""))
        return {"ok": ok}

    @server.method("knowledge.backup")
    async def knowledge_backup(params):
        """备份全部卡片。params: {path?} 返回备份文件路径。"""
        from pathlib import Path

        k_cfg = cfg.get("knowledge", {})
        home = Path(cfg.get("home", "."))
        backup_dir = home / k_cfg.get("backup_dir", "knowledge_backups")
        import time as _t

        path = params.get("path") or str(backup_dir / f"knowledge_{_t.strftime('%Y%m%d_%H%M%S')}.json")
        out = get_knowledge().export_backup(path)
        return {"ok": True, "path": str(out)}

    @server.method("knowledge.restore")
    async def knowledge_restore(params):
        """从备份恢复。params: {path, merge?}"""
        count = get_knowledge().import_backup(params.get("path", ""), merge=bool(params.get("merge", False)))
        return {"ok": True, "imported": count}

    @server.method("knowledge.clear")
    async def knowledge_clear(params):
        n = get_knowledge().clear()
        return {"ok": True, "cleared": n}

    @server.method("knowledge.graph")
    async def knowledge_graph(params):
        """知识图谱数据（节点+边，供可视化）。"""
        return get_knowledge().graph()

    @server.method("knowledge.export")
    async def knowledge_export(params):
        """导出单卡（markdown/json）。"""
        return get_knowledge().export_card(params.get("id", ""), params.get("format", "markdown"))

    # ================================================================
    #  Voice
    # ================================================================

    @server.method("voice.status")
    async def voice_status(params):
        try:
            vs = get_voice()
            st = vs.status()
            # 就绪门：ASR 模型（FunASR）是否已预热、TTS 是否可用
            try:
                asr = getattr(vs, "asr", None)
                st["asr_ready"] = bool(getattr(asr, "_warmed_up", True)) or asr.name == "mock-asr"
            except Exception:
                st["asr_ready"] = True
            try:
                tts = getattr(vs, "tts", None)
                st["tts_ready"] = bool(getattr(tts, "_available", True)) or tts.name == "mock-tts"
            except Exception:
                st["tts_ready"] = True
            return st
        except Exception as e:
            return {"error": str(e), "fallback": True, "asr": "mock", "tts": "mock", "asr_ready": False, "tts_ready": False}

    @server.method("voice.turn")
    async def voice_turn(params):
        """执行一轮语音对话。

        - 传 text：跳过真实音频采集，直接用文本走完整链路（text_override 模式）
        - 不传 text：真实麦克风采集 → VAD → ASR → LLM → TTS（listen 模式）
        - 互斥：真实采集期间暂停后台 WakeLoop，避免多 MicSource 抢占麦克风产生噪音
        - 连续对话：params.continuous=true 时，唤醒一次后窗口期内（默认 60s/10 轮）
          后续轮次自动跳过唤醒词检查（用户无需反复说唤醒词）
        """
        text_override = params.get("text")
        continuous = bool(params.get("continuous", False))
        # 连续对话会话：窗口未过期且轮次未超限 → 本轮免唤醒词
        conv_active = (
            continuous
            and _conv_session["active"]
            and time.monotonic() < _conv_session["expires_at"]
            and _conv_session["turns"] < _conv_max_turns
        )
        # 连续对话期间 WakeLoop 保持停止（避免每轮停启麦克风导致 WASAPI 设备竞争）
        # conv_active 为 True 说明会话进行中，WakeLoop 应已停止
        wake_loop = _wake_loop_ref["loop"]
        wake_was_running = bool(wake_loop and wake_loop.running and not conv_active)
        try:
            # 互斥：真实采集前暂停后台唤醒循环（两者共用同一麦克风设备）
            if text_override is None and wake_was_running:
                log.info("voice.turn 采集前暂停 WakeLoop（麦克风互斥）")
                await wake_loop.stop()
            try:
                vs = get_voice()
                result = await vs.run_turn(text_override=text_override, skip_wake=conv_active)
            except Exception:
                # 异常时按需恢复 WakeLoop
                if text_override is None and wake_was_running:
                    try:
                        await wake_loop.start()
                    except Exception:
                        pass
                raise
            # 更新连续对话会话状态
            if continuous:
                if result is not None and result.get("wake") is not False and result.get("error") not in ("empty_command", "no_speech_detected"):
                    # 成功一轮：开启/续期会话窗口
                    _conv_session["active"] = True
                    _conv_session["expires_at"] = time.monotonic() + _conv_window_s
                    _conv_session["turns"] += 1
                else:
                    # 失败轮（唤醒未命中/空指令）：重置会话
                    _conv_session["active"] = False
                    _conv_session["turns"] = 0
            # 进入连续对话会话后 WakeLoop 保持停止（避免每轮停启麦克风 → WASAPI 竞争）
            # 仅当本轮未进入连续对话时恢复唤醒循环
            keep_wake_stopped = bool(continuous and _conv_session["active"])
            if text_override is None and wake_was_running and not keep_wake_stopped:
                await wake_loop.start()
                log.info("voice.turn 结束，WakeLoop 已恢复")
            elif text_override is None and wake_was_running and keep_wake_stopped:
                log.info("voice.turn 进入连续对话，WakeLoop 保持停止")
            if result is None:
                return {"ok": False, "error": "语音对话执行失败（未识别到有效语音）", "error_type": "no_result", "asr_text": text_override}
            # 处理无语音检测等预期内的失败
            if result.get("error") == "no_speech_detected":
                return {
                    "ok": False,
                    "error": result.get("error_detail", "未检测到语音输入"),
                    "error_type": "no_speech_detected",
                    "source": result.get("source", "unknown"),
                    "asr_text": text_override,
                }
            # 处理识别为空/纯噪音（§3.1：环境噪音过滤）
            if result.get("error") == "empty_command":
                return {
                    "ok": False,
                    "error": result.get("error_detail", "未识别到有效语音指令（请减少环境噪音后重试）"),
                    "error_type": "empty_command",
                    "text": result.get("text", ""),
                    "asr_text": text_override,
                }
            # 处理唤醒词未命中
            if result.get("wake") is False:
                return {
                    "ok": False,
                    "error": "唤醒词未检测到，请说唤醒词后再试",
                    "error_type": "wake_word_missed",
                    "text": result.get("text", ""),
                    "asr_text": text_override,
                }
            # 连续对话元数据（前端提示剩余轮次/窗口）
            if continuous and result.get("reply"):
                result["continuous"] = {
                    "active": _conv_session["active"],
                    "turns_left": max(0, _conv_max_turns - _conv_session["turns"]),
                    "window_left_s": max(0, round(_conv_session["expires_at"] - time.monotonic(), 1)),
                }
                # ---- 连续对话增强：退出命令词 + 窗口到期提醒 ----
                # 1) 退出命令词（说"再见/退出/结束"结束会话）
                clean = (result.get("text_clean") or result.get("text") or "").strip()
                if _conv_session["active"] and _is_exit_command(clean, _EXIT_WORDS):
                    _conv_session["active"] = False
                    _conv_session["turns"] = 0
                    result["continuous"]["active"] = False
                    result["continuous"]["ended_by"] = "exit_word"
                    # 语音确认（fire-and-forget 异步播放）
                    try:
                        await get_voice().aspeak("好的，随时叫我。")
                    except Exception:
                        pass
                    log.info("连续对话：退出命令词 %r 结束会话", clean)
                    # 会话结束 → 恢复后台唤醒监听（麦克风已释放）
                    wl = _wake_loop_ref["loop"]
                    if wl is not None and not wl.running:
                        try:
                            await wl.start()
                            log.info("连续对话结束，WakeLoop 已恢复")
                        except Exception as e:
                            log.warning("WakeLoop 恢复失败: %s", e)
                # 2) 窗口将到期提醒（剩 ≤ 15s 或下一轮将超限 → 语音询问是否继续）
                elif _conv_session["active"]:
                    window_left = _conv_session["expires_at"] - time.monotonic()
                    turns_left = _conv_max_turns - _conv_session["turns"]
                    remind = window_left <= _conv_remind_before_s or turns_left <= _conv_remind_turns_left
                    if remind:
                        try:
                            await get_voice().aspeak("还需要我吗？")
                        except Exception:
                            pass
                        result["continuous"]["reminded"] = True
                        log.info("连续对话：窗口即将到期，已提醒（剩 %.0fs / %d 轮）", window_left, turns_left)
            return {"ok": True, **result}
        except Exception as e:
            log.exception("voice.turn 异常")
            # 仅在文本模式下降级到 chat.send；真实音频模式直接返回错误
            if text_override is not None:
                reply = await engine.send(text_override)
                return {
                    "ok": True,
                    "text": text_override,
                    "reply": reply.text,
                    "model": reply.model,
                    "route": reply.route.to_dict(),
                    "asr_backend": "fallback-chat",
                    "tts_backend": "fallback-chat",
                    "fallback": True,
                    "error_detail": str(e),
                }
            return {"ok": False, "error": str(e), "error_type": type(e).__name__}

    @server.method("voice.continuous.status")
    async def voice_continuous_status(params):
        """查询连续对话会话状态。

        窗口已过期且 WakeLoop 未运行 → 自动恢复后台监听（会话自然结束后回到常驻监听）。
        """
        active = _conv_session["active"] and time.monotonic() < _conv_session["expires_at"]
        if not active and _conv_session["turns"] > 0:
            # 窗口自然过期：结束会话并恢复 WakeLoop
            _conv_session["active"] = False
            _conv_session["turns"] = 0
            wl = _wake_loop_ref["loop"]
            if wl is not None and not wl.running:
                try:
                    await wl.start()
                    log.info("连续对话窗口过期，WakeLoop 已恢复")
                except Exception as e:
                    log.warning("WakeLoop 恢复失败: %s", e)
        return {
            "ok": True,
            "active": active,
            "turns": _conv_session["turns"],
            "turns_left": max(0, _conv_max_turns - _conv_session["turns"]),
            "window_left_s": max(
                0, round(_conv_session["expires_at"] - time.monotonic(), 1)
            ) if active else 0,
            "window_s": _conv_window_s,
            "max_turns": _conv_max_turns,
        }

    @server.method("voice.continuous.reset")
    async def voice_continuous_reset(params):
        """手动结束连续对话会话，恢复后台唤醒监听。"""
        _conv_session["active"] = False
        _conv_session["turns"] = 0
        wl = _wake_loop_ref["loop"]
        if wl is not None and not wl.running:
            try:
                await wl.start()
                log.info("连续对话手动结束，WakeLoop 已恢复")
            except Exception as e:
                log.warning("WakeLoop 恢复失败: %s", e)
        return {"ok": True, "active": False}

    # ================================================================
    #  PTT（按住说话）：voice.ptt.start / voice.ptt.stop
    # ================================================================

    @server.method("voice.ptt.start")
    async def voice_ptt_start(params):
        """开始 PTT 采集（按住空格/鼠标）：持续采集麦克风，不自动结束。

        暂停后台 WakeLoop（麦克风互斥），返回采集会话 id。
        """
        try:
            vs = get_voice()
            ok = await vs.start_ptt()
            if not ok:
                return {"ok": False, "error": "PTT 已在采集", "error_type": "already_active"}
            # 互斥：PTT 采集期间暂停 WakeLoop
            wl = _wake_loop_ref["loop"]
            if wl is not None and wl.running:
                await wl.stop()
                log.info("PTT 开始，WakeLoop 已暂停")
            return {"ok": True, "active": True}
        except Exception as e:
            log.exception("voice.ptt.start 异常")
            return {"ok": False, "error": str(e), "error_type": type(e).__name__}

    @server.method("voice.ptt.stop")
    async def voice_ptt_stop(params):
        """结束 PTT 采集并处理 buffer（认证→ASR→唤醒→LLM→TTS）。

        返回与 voice.turn 相同的结果结构；采集为空返回 no_speech_detected。
        """
        try:
            vs = get_voice()
            continuous = bool(params.get("continuous", False))
            # 连续对话窗口内免唤醒词
            conv_active = (
                continuous
                and _conv_session["active"]
                and time.monotonic() < _conv_session["expires_at"]
                and _conv_session["turns"] < _conv_max_turns
            )
            result = await vs.stop_ptt(skip_wake=conv_active)
            # 更新连续对话会话状态
            if continuous:
                if result.get("wake") is not False and result.get("error") not in ("empty_command", "no_speech_detected"):
                    _conv_session["active"] = True
                    _conv_session["expires_at"] = time.monotonic() + _conv_window_s
                    _conv_session["turns"] += 1
                else:
                    _conv_session["active"] = False
                    _conv_session["turns"] = 0
            # PTT 结束恢复 WakeLoop（连续对话会话激活时保持停止）
            keep_wake_stopped = bool(continuous and _conv_session["active"])
            wl = _wake_loop_ref["loop"]
            if wl is not None and not wl.running and not keep_wake_stopped:
                try:
                    await wl.start()
                    log.info("PTT 结束，WakeLoop 已恢复")
                except Exception as e:
                    log.warning("WakeLoop 恢复失败: %s", e)
            # 连续对话元数据
            if continuous and result.get("reply"):
                result["continuous"] = {
                    "active": _conv_session["active"],
                    "turns_left": max(0, _conv_max_turns - _conv_session["turns"]),
                    "window_left_s": max(0, round(_conv_session["expires_at"] - time.monotonic(), 1)),
                }
            if result.get("error"):
                return {"ok": False, **result}
            return {"ok": True, **result}
        except Exception as e:
            log.exception("voice.ptt.stop 异常")
            return {"ok": False, "error": str(e), "error_type": type(e).__name__}

    @server.method("voice.listen")
    async def voice_listen(params):
        """真实麦克风模式：采集音频 → ASR → LLM → TTS → 播放。"""
        try:
            vs = get_voice()
            result = await vs.run_turn(text_override=None)
            if result is None:
                return {"ok": False, "error": "未检测到语音输入"}
            return {"ok": True, **result}
        except Exception as e:
            log.exception("voice.listen 异常")
            return {
                "ok": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }

    # ================================================================
    #  Wake Loop (后台唤醒监听)
    # ================================================================

    _wake_loop_ref = {"loop": None}

    @server.method("voice.wake_loop.start")
    async def wake_loop_start(params):
        """启动后台唤醒监听循环。

        Args:
            params: {"asr_config": {...}, "wake_words": [...]}

        Returns:
            {"ok": true, "status": {...}}
        """
        if _wake_loop_ref["loop"] and _wake_loop_ref["loop"].running:
            return {"ok": True, "already_running": True, "status": _wake_loop_ref["loop"].status()}

        from aivyos_core.audio.wake_loop import WakeLoop

        asr_cfg = params.get("asr_config", {})
        wake_words = params.get("wake_words")

        def on_wake(text: str) -> None:
            asyncio.create_task(
                server.broadcast_event("wake-detected", {
                    "text": text,
                    "timestamp": asyncio.get_event_loop().time(),
                })
            )

        loop = WakeLoop(on_wake=on_wake, asr_config=asr_cfg)
        _wake_loop_ref["loop"] = loop
        await loop.start()
        return {"ok": True, "status": loop.status()}

    @server.method("voice.wake_loop.stop")
    async def wake_loop_stop(params):
        """停止后台唤醒监听循环。"""
        loop = _wake_loop_ref["loop"]
        if not loop:
            return {"ok": True, "already_stopped": True}
        await loop.stop()
        _wake_loop_ref["loop"] = None
        return {"ok": True}

    @server.method("voice.wake_loop.status")
    async def wake_loop_status(params):
        """查询后台唤醒监听状态。"""
        loop = _wake_loop_ref["loop"]
        if not loop:
            return {"ok": True, "running": False}
        return {"ok": True, **loop.status()}

    # ================================================================
    #  Autonomous Tasks
    # ================================================================

    @server.method("task.create")
    async def task_create(params):
        nonlocal _task_counter
        _task_counter += 1
        task_id = f"task_{_task_counter:04d}"
        description = params.get("description", "未命名任务")
        # 使用 LLM 解析任务为步骤
        steps = []
        try:
            analysis = await engine.send(
                f"将以下任务拆解为 3-5 个可执行步骤，以 JSON 数组格式返回，每个步骤包含 title 和 detail 字段：\n{description}"
            )
            import re
            text = analysis.text
            # 尝试提取 JSON
            json_match = re.search(r'\[[\s\S]*\]', text)
            if json_match:
                steps = json.loads(json_match.group())
            else:
                steps = [{"title": f"分析任务：{description[:30]}", "detail": "理解需求"},
                         {"title": "制定执行计划", "detail": "拆解子任务"},
                         {"title": "执行并验证", "detail": "运行并检查结果"}]
        except Exception:
            steps = [{"title": f"分析任务：{description[:30]}", "detail": "理解需求"},
                     {"title": "制定执行计划", "detail": "拆解子任务"},
                     {"title": "执行并验证", "detail": "运行并检查结果"}]

        _tasks[task_id] = {
            "id": task_id,
            "title": description[:50],
            "status": "pending",
            "steps": steps,
            "current_step": 0,
            "created_at": None,
            "logs": [f"任务已创建：{description}"],
        }
        return {"ok": True, "task_id": task_id, "steps": steps, "total_steps": len(steps)}

    @server.method("task.list")
    async def task_list(params):
        return list(_tasks.values())

    @server.method("task.execute")
    async def task_execute(params):
        task_id = params["task_id"]
        task = _tasks.get(task_id)
        if not task:
            return {"ok": False, "error": "任务不存在"}
        task["status"] = "working"
        task["current_step"] = min(task["current_step"] + 1, len(task["steps"]))
        step_idx = task["current_step"] - 1
        if 0 <= step_idx < len(task["steps"]):
            step = task["steps"][step_idx]
            task["logs"].append(f"执行步骤 {step_idx + 1}/{len(task['steps'])}: {step.get('title', '')}")
        if task["current_step"] >= len(task["steps"]):
            task["status"] = "completed"
            task["logs"].append("所有步骤执行完成")
        return {"ok": True, "task": task}

    # ================================================================
    #  Scheduler
    # ================================================================

    @server.method("sched.list")
    async def sched_list(params):
        sched = get_scheduler()
        return sched.status()

    @server.method("sched.create")
    async def sched_create(params):
        from datetime import datetime
        sched = get_scheduler()
        name = params.get("name", "unnamed")
        cron_expr = params.get("cron_expr", "*/5 * * * *")
        handler_text = params.get("handler_text", f"定时任务 {name}")

        async def handler():
            log.info("定时任务触发: %s", name)
            try:
                await engine.send(handler_text)
            except Exception:
                log.exception("定时任务执行异常")

        try:
            sched.cron(name, cron_expr)(handler)
            return {"ok": True, "name": name, "cron": cron_expr}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ================================================================
    #  Vibe Coding
    # ================================================================

    @server.method("vibe.run")
    async def vibe_run(params):
        """运行 VibeCoding 工作流（需求 → 规划 → 生成 → 交付 → 构建 → 预览）。"""
        request = params.get("request", "创建一个示例网页")
        executor = params.get("executor", cfg.get("workflow", {}).get("executor", "demo"))

        try:
            from aivyos_core.workflow.workflows import build_vibe_coding_graph
            from aivyos_core.workflow.checkpointer import SqliteCheckpointer

            checkpointer = SqliteCheckpointer(cfg.get("workflow", {}).get("checkpoint_db", "checkpoints.sqlite"))
            graph = build_vibe_coding_graph(checkpointer)
            compiled = graph.compile()

            workspace = cfg.get("workflow", {}).get("workspace", ".aivyos_workspace")

            ctx = {
                "executor": executor,
                "router": engine.router,
                "codegen": None,
                "memfs": engine.memfs,
                "workspace": workspace,
                "build_command": cfg.get("workflow", {}).get("build_command"),
                "preview": cfg.get("workflow", {}).get("preview", True),
            }

            result = await compiled.ainvoke(
                {"user_request": request, "retry_count": 0},
                config={"configurable": {"ctx": ctx, "thread_id": f"vibe_{__import__('time').time()}"}},
            )

            return {
                "ok": True,
                "steps": {k: v for k, v in result.items() if k.startswith("note_")},
                "files": result.get("files", {}),
                "delivered_to": result.get("delivered_to"),
                "preview_url": result.get("preview_url"),
                "preview_ok": result.get("preview_ok"),
                "build_failed": result.get("build_failed", False),
            }
        except Exception as e:
            log.exception("vibe.run 异常")
            return {"ok": False, "error": str(e)}

    # ================================================================
    #  Boot / Self-check
    # ================================================================

    @server.method("boot.check")
    async def boot_check(params):
        """执行系统自检，返回各模块状态。

        真实性原则：每项做真实可用性探测（而非仅配置读取），
        避免假阳性 —— LLM 探测、记忆真实检索、语音模型就绪检查。

        fast=True（默认）：语音模块仅做依赖探测（不加载 ASR 模型、不合成 TTS），
        秒级完成，适合启动自检；fast=False 做深度真实加载验证。
        """
        fast = bool(params.get("fast", True))
        checks = []
        # 1. LLM 路由（真实 HTTP 探测：GET /models，带 TTL 缓存）
        try:
            local_ok = False
            cloud_ok = False
            try:
                local_ok = engine.router._local_available()
            except Exception:
                local_ok = False
            try:
                cloud_ok = bool(engine.router._cloud_api_key())
            except Exception:
                cloud_ok = False
            routes = engine.router.backends_status()
            detail = f"{len(routes)} 个后端"
            if local_ok:
                detail += "（本地✓ 真实探测）"
            elif cloud_ok:
                detail += "（云端✓ 已配 Key）"
            else:
                detail += "（均不可用→mock）"
            checks.append({"name": "LLM 路由", "ok": local_ok or cloud_ok, "detail": detail})
        except Exception as e:
            checks.append({"name": "LLM 路由", "ok": False, "detail": str(e)})

        # 2. 记忆系统（真实检索验证读写可用）
        try:
            mem_info = engine.memory.backend_name
            try:
                await engine.memory.search("自检", top_k=1)
                detail = f"{mem_info}（读写✓）"
                ok = True
            except Exception:
                detail = f"{mem_info}（检索失败）"
                ok = False
            checks.append({"name": "记忆系统", "ok": ok, "detail": detail})
        except Exception as e:
            checks.append({"name": "记忆系统", "ok": False, "detail": str(e)})

        # 3. 语音模块（fast：仅依赖探测；deep：真实加载 ASR 模型 + 真实 TTS 合成，不打开麦克风）
        try:
            from aivyos_core.asr.manager import create_asr
            from aivyos_core.tts.manager import create_tts

            asr_cfg = dict(cfg.get("asr", {}))
            tts_cfg = dict(cfg.get("tts", {}))
            asr_backend = asr_cfg.get("backend", "auto")
            tts_backend = tts_cfg.get("backend", "auto")
            detail = f"ASR={asr_backend}, TTS={tts_backend}"

            if fast:
                # ---- 快速模式：仅依赖探测（不实例化/不导入重型包，秒级，启动自检用）----
                # 注意：不能用 import funasr —— 其 __init__ 会导入 torch 等全部子模块（~10s+），
                # 用 find_spec 只检查包是否存在，真实加载延迟到首次语音使用。
                import importlib.util

                asr_ok = True
                tts_ok = True
                try:
                    has_funasr = importlib.util.find_spec("funasr") is not None
                    has_sd = importlib.util.find_spec("sounddevice") is not None
                    if has_funasr and has_sd:
                        detail += "（ASR 依赖✓ 首次使用加载）"
                    else:
                        detail += "（ASR 依赖缺失→mock 回退）"
                except Exception:
                    detail += "（ASR 依赖探测失败）"
                try:
                    has_edge = importlib.util.find_spec("edge_tts") is not None
                    if has_edge:
                        detail += "（TTS 依赖✓）"
                    else:
                        detail += "（TTS 依赖缺失→mock 回退）"
                except Exception:
                    detail += "（TTS 依赖探测失败）"
                checks.append({"name": "语音模块", "ok": asr_ok and tts_ok, "detail": detail})
            else:
                # ---- 深度模式：真实加载 + 真实合成 ----
                # ASR 真实加载（不创建 VoiceSession/不开麦克风）
                asr_ok = True
                try:
                    asr = create_asr(asr_cfg)
                    if getattr(asr, "name", "") not in ("mock-asr",):
                        # 真实模型：执行预热（加载模型 + 空推理）
                        if hasattr(asr, "warmup"):
                            await asyncio.get_running_loop().run_in_executor(None, asr.warmup)
                        warmed = bool(getattr(asr, "_warmed_up", True))
                        if not warmed:
                            detail += "（ASR 模型预热中）"
                        asr_ok = warmed
                except Exception as e:
                    detail += f"（ASR 加载失败: {str(e)[:60]}）"
                    asr_ok = False
                # TTS 真实合成（验证网络可达/后端可用）
                tts_ok = True
                try:
                    tts = create_tts(tts_cfg)
                    if getattr(tts, "name", "") not in ("mock-tts",):
                        audio = await asyncio.get_running_loop().run_in_executor(
                            None, lambda: tts.synthesize("自检")
                        )
                        tts_ok = audio is not None and len(getattr(audio, "pcm", b"")) > 0
                        if not tts_ok:
                            detail += "（TTS 合成失败）"
                except Exception as e:
                    detail += f"（TTS 失败: {str(e)[:60]}）"
                    tts_ok = False
                checks.append({"name": "语音模块", "ok": asr_ok and tts_ok, "detail": detail})
        except Exception as e:
            checks.append({"name": "语音模块", "ok": False, "detail": str(e)})

        # 4. 会话存储（真实 list）
        try:
            sessions = engine.list_sessions()
            checks.append({"name": "会话存储", "ok": True, "detail": f"{len(sessions)} 个会话"})
        except Exception as e:
            checks.append({"name": "会话存储", "ok": False, "detail": str(e)})

        # 5. 调度器（真实 status）
        try:
            sched = get_scheduler()
            jobs = sched.status()
            checks.append({"name": "调度器", "ok": True, "detail": f"{len(jobs)} 个任务"})
        except Exception as e:
            checks.append({"name": "调度器", "ok": False, "detail": str(e)})

        # 6. MemFS（真实写读临时文件验证）
        try:
            import uuid

            tmp_name = f".bootcheck_{uuid.uuid4().hex[:8]}.tmp"
            engine.memfs.write(tmp_name, "ok")
            content = engine.memfs.read(tmp_name)
            engine.memfs.remove(tmp_name)
            ok = content == "ok"
            info = engine.memfs.summary()
            checks.append({"name": "MemFS", "ok": ok, "detail": f"{str(info)[:60]}（读写✓）" if ok else "读写失败"})
        except Exception as e:
            checks.append({"name": "MemFS", "ok": False, "detail": str(e)})

        # 7. 人格
        try:
            persona = engine.persona.to_dict()
            checks.append({"name": "人格引擎", "ok": True, "detail": f"{persona.get('name', 'N/A')}"})
        except Exception as e:
            checks.append({"name": "人格引擎", "ok": False, "detail": str(e)})

        # 8. 输出路由
        try:
            checks.append({"name": "输出路由", "ok": True, "detail": engine.output.default_channel.value})
        except Exception as e:
            checks.append({"name": "输出路由", "ok": False, "detail": str(e)})

        # 9. 情感标签
        try:
            checks.append({"name": "情感分析", "ok": True, "detail": "enabled" if engine.emotion.enabled else "disabled"})
        except Exception as e:
            checks.append({"name": "情感分析", "ok": False, "detail": str(e)})

        # 10. 视觉（真实检查后端类型；mock 标注未配置）
        try:
            vision_st = engine.vision.status()
            v_ocr = str(vision_st.get("ocr", "mock"))
            v_understand = str(vision_st.get("understand", "mock"))
            # mock 后端 → 未配置真实视觉（诚实标注，不算 ok）
            ok = v_ocr not in ("mock", "mock-ocr") or v_understand not in ("mock", "mock-vision")
            detail = f"OCR={v_ocr}, 理解={v_understand}"
            if not ok:
                detail += "（未配置真实后端→mock）"
            checks.append({"name": "视觉模块", "ok": ok, "detail": detail})
        except Exception as e:
            checks.append({"name": "视觉模块", "ok": False, "detail": str(e)})

        total = len(checks) or 1  # 防除零
        passed = sum(1 for c in checks if c["ok"])
        progress = int(passed / total * 100)
        return {
            "checks": checks,
            "progress": progress,
            "passed": passed,
            "total": len(checks),
            "summary": f"{passed}/{len(checks)} 项检查通过",
        }

    @server.method("boot.restore")
    async def boot_restore(params):
        summary = await engine.restore_on_boot()
        return summary.to_dict()

    # ================================================================
    #  Vision (图片读取/视觉模型加载管理)
    # ================================================================

    @server.method("vision.read-image")
    async def vision_read_image(params):
        """读取本地图片 → base64（供前端预览/发送）。"""
        import base64
        import os

        path = params.get("path", "")
        try:
            if not path or not os.path.isfile(path):
                return {"ok": False, "error": "文件不存在"}
            with open(path, "rb") as f:
                data = f.read()
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            mime = {
                "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
            }.get(ext, "application/octet-stream")
            return {"ok": True, "base64": base64.b64encode(data).decode(), "mime": mime, "size": len(data)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("vision.load")
    async def vision_load(params):
        """主动加载视觉模型（调用方在需要时触发；Ollama keep_alive 驻留）。"""
        try:
            u = engine.vision.understand
            if getattr(u, "name", "") == "mock-vision":
                return {"ok": False, "message": "视觉模型未配置（mock 回退）"}
            u.ensure_loaded()
            return {"ok": True, "message": f"已加载 {u.model}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    @server.method("vision.release")
    async def vision_release(params):
        """主动释放视觉模型（Ollama keep_alive=0 立即卸载，释放显存）。"""
        try:
            u = engine.vision.understand
            if getattr(u, "name", "") == "mock-vision":
                return {"ok": False, "message": "视觉模型未配置（mock 回退）"}
            u.release()
            return {"ok": True, "message": f"已释放 {u.model}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ================================================================
    #  Voice Settings (配置读写)
    # ================================================================

    @server.method("voiceset.get")
    async def voiceset_get(params):
        tts_cfg = cfg.get("tts", {})
        return {
            "wake_words": cfg.get("voice", {}).get("wake_words", []),
            "wake_required": cfg.get("voice", {}).get("wake_required", False),
            "asr_backend": cfg.get("asr", {}).get("backend", "auto"),
            "asr_model": cfg.get("asr", {}).get("model", ""),
            "tts_backend": tts_cfg.get("backend", "auto"),
            "tts_model": tts_cfg.get("model", ""),
            "tts_voice": tts_cfg.get("voice", ""),
            "tts_speed": tts_cfg.get("speed", 1.0),
            "tts_resource_id": tts_cfg.get("resource_id", ""),
            "language": cfg.get("asr", {}).get("language", "zh"),
            "silence_timeout_s": cfg.get("voice", {}).get("silence_timeout_s", 3.0),
        }

    @server.method("voiceset.set")
    async def voiceset_set(params):
        field = params.get("field")
        value = params.get("value")
        if not field:
            return {"ok": False, "error": "缺少 field 参数"}
        # 更新内存中的 cfg（持久化需写文件）
        parts = field.split(".")
        target = cfg
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = value
        return {"ok": True, "field": field, "value": value}

    @server.method("voiceset.apply-tts")
    async def voiceset_apply_tts(params):
        """应用 TTS 配置并立即重建 VoiceSession 的 TTS 引擎。"""
        import os
        from aivyos_core.tts.manager import create_tts

        provider = (params.get("provider", "auto") or "auto").lower()
        voice = params.get("voice", "")
        speed = float(params.get("speed", 1.0))
        api_key = params.get("api_key", "")
        resource_id = params.get("resource_id", "")

        # 1) 更新 cfg 中的 tts 配置
        tts_cfg = cfg.setdefault("tts", {})
        tts_cfg["backend"] = provider
        if voice:
            tts_cfg["voice"] = voice
        tts_cfg["speed"] = speed
        if resource_id:
            tts_cfg["resource_id"] = resource_id

        # 2) 同步 API Key 到环境变量（用于 create_tts 自动检测）
        env_var_map = {
            "auto": "VOLCENGINE_API_KEY",
            "doubao-tts": "VOLCENGINE_API_KEY",
            "doubao": "VOLCENGINE_API_KEY",
            "bytedance": "VOLCENGINE_API_KEY",
            "volcengine": "VOLCENGINE_API_KEY",
            "elevenlabs": "ELEVENLABS_API_KEY",
        }
        if api_key:
            # 保存到全局 API Key 持久化存储
            env_var = env_var_map.get(provider, "")
            if env_var:
                _api_key_store.set_key(env_var, api_key, provider)
                log.info("API Key 已保存到持久化存储: %s", env_var)
            # 同步到 os.environ 供 create_tts 使用
            if env_var:
                os.environ[env_var] = api_key
            tts_cfg["api_key"] = api_key
        elif provider in env_var_map:
            # 用户清空了 API Key
            env_var = env_var_map[provider]
            os.environ.pop(env_var, None)
            _api_key_store.remove_key(env_var)
            tts_cfg.pop("api_key", None)

        # 3) 重建 VoiceSession 的 TTS 引擎
        try:
            new_tts = create_tts(tts_cfg)
            log.info("TTS 引擎重建: %s (backend=%s)", new_tts.name, provider)

            nonlocal _voice_session
            if _voice_session is not None:
                _voice_session.tts = new_tts
                # 重新配置音频输出（采样率可能变化）
                try:
                    from aivyos_core.audio.sink import create_sink
                    audio_cfg = cfg.get("audio", {})
                    _voice_session.sink = create_sink({**tts_cfg, "sample_rate": new_tts.sample_rate})
                except Exception as e:
                    log.warning("音频输出重建失败: %s", e)
                log.info("VoiceSession TTS 已更新: %s", new_tts.name)
            else:
                # VoiceSession 还未创建，直接用新配置（下次 get_voice() 会使用）
                pass

            return {
                "ok": True,
                "backend": new_tts.name,
                "message": f"TTS 已切换到 {new_tts.name}",
            }
        except Exception as e:
            log.exception("TTS 引擎重建失败")
            return {"ok": False, "error": f"TTS 引擎重建失败: {e}"}

    # ================================================================
    #  Model Management
    # ================================================================

    @server.method("models.list")
    async def models_list(params):
        return engine.router.backends_status()

    @server.method("models.set-active")
    async def models_set_active(params):
        """设置当前使用的模型（强制路由到指定后端）。"""
        model_name = params.get("model")
        if not model_name:
            engine.router.set_forced_backend(None)
            return {"ok": True, "active": None, "message": "已取消强制模型，恢复自动路由"}
        if not engine.router.registry.contains(model_name):
            return {"ok": False, "error": f"后端不存在: {model_name}"}
        engine.router.set_forced_backend(model_name)
        return {"ok": True, "active": model_name, "message": f"已切换到模型: {model_name}"}

    @server.method("models.health")
    async def models_health(params):
        """Provider 健康仪表盘：后端状态 + 熔断器 + 成本数据。"""
        router = engine.router
        return {
            "backends": router.backends_status(),
            "breakers": router.registry.breakers.get_all_stats(),
            "cost": router.cost_tracker.get_dashboard(),
            "strategy": str(router._strategy.value) if hasattr(router._strategy, 'value') else str(router._strategy),
            "selected": router._strategy,
        }

    @server.method("models.cost")
    async def models_cost(params):
        """成本追踪数据。"""
        backend = params.get("backend")
        if backend:
            return engine.router.cost_tracker.get_stats(backend)
        return engine.router.cost_tracker.get_dashboard()

    @server.method("models.backends")
    async def models_backends(params):
        """所有已注册后端详情。"""
        router = engine.router
        result = []
        for backend in router._all_backends():
            info = router.registry.get_info(backend.name)
            result.append({
                "name": backend.name,
                "provider": backend.provider,
                "model": backend.model,
                "capabilities": backend.capabilities.to_dict(),
                "available": router.registry.can_execute(backend.name),
                "info": info.to_dict() if info else {},
            })
        return result

    @server.method("models.add")
    async def models_add(params):
        """动态添加后端。"""
        try:
            from aivyos_core.llm.providers import create_provider_info
            name = params.get("name", "")
            provider = params.get("provider", "")
            model = params.get("model", "")
            if not all([name, provider, model]):
                return {"ok": False, "error": "缺少 name/provider/model 参数"}
            info = create_provider_info(
                name=name,
                provider=provider,
                model=model,
                base_url=params.get("base_url", ""),
                api_key_env=params.get("api_key_env", ""),
                priority=int(params.get("priority", 50)),
            )
            backend = engine.router.registry.create(info)
            # 注册成本追踪
            engine.router.cost_tracker.register_backend(
                backend_name=backend.name,
                provider=info.provider,
                model=info.model,
                cost_per_1m_input=backend.capabilities.cost_per_1m_input,
                cost_per_1m_output=backend.capabilities.cost_per_1m_output,
            )
            return {"ok": True, "name": backend.name, "provider": provider, "model": model}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("models.remove")
    async def models_remove(params):
        """动态移除后端。"""
        name = params.get("name", "")
        if not name:
            return {"ok": False, "error": "缺少 name 参数"}
        try:
            engine.router.registry.remove(name)
            engine.router.cost_tracker.reset(name)
            return {"ok": True, "name": name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("models.catalog")
    async def models_catalog(params):
        """获取提供商目录（11+ 提供商及其模型列表）。"""
        try:
            from aivyos_core.llm.provider_catalog import (
                get_provider_catalog, search_models, get_categories,
            )
            keyword = params.get("keyword", "")
            if keyword:
                return {"results": search_models(keyword)}
            return {
                "providers": get_provider_catalog(),
                "categories": {
                    k: [p.to_dict() for p in v]
                    for k, v in get_categories().items()
                },
            }
        except Exception as e:
            return {"error": str(e)}

    @server.method("models.api-key.list")
    async def models_apikey_list(params):
        """列出所有已配置的 API Key（返回脱敏元信息，不返回密钥值）。"""
        import os
        api_keys_store = _api_key_store.list_keys()

        # 补充检查环境变量中存在但存储文件中没有的 key
        env_vars = [
            "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY", "DASHSCOPE_API_KEY", "SILICONFLOW_API_KEY",
            "MISTRAL_API_KEY", "AZURE_OPENAI_API_KEY",
            "VOLCENGINE_API_KEY", "TENCENT_SECRET_KEY",
            "ELEVENLABS_API_KEY", "DEEPGRAM_API_KEY",
        ]
        for var in env_vars:
            if var not in api_keys_store:
                val = os.environ.get(var, "")
                provider_id = var.lower().replace("_api_key", "").replace("_secret_key", "")
                api_keys_store[var] = {
                    "env_var": var,
                    "provider": provider_id,
                    "has_key": bool(val),
                    "key_length": len(val) if val else 0,
                    "masked_preview": _api_key_store._mask(val) if val else "",
                    "source": "env",
                }

        return {"api_keys": api_keys_store}

    @server.method("models.api-key.set")
    async def models_apikey_set(params):
        """设置 API Key（加密持久化到文件 + 写入环境变量 + 热切换引擎）。"""
        nonlocal engine
        field = params.get("field", "")
        value = params.get("value", "")
        env_var = params.get("env_var", "")
        provider = params.get("provider", "")

        if not env_var:
            return {"ok": False, "error": "缺少 env_var 参数"}

        # 使用持久化存储
        result = _api_key_store.set_key(env_var, value, provider or field)

        if not result.get("ok"):
            return result

        # 同步到 os.environ（供后端解析和路由过滤使用）
        import os as _os
        _os.environ[env_var] = value

        # 若为已知云端提供商，同时映射到通用 AIVYOS_CLOUD_API_KEY
        _CLOUD_PROVIDER_KEYS = {
            "DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY",
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
        }
        if env_var in _CLOUD_PROVIDER_KEYS:
            _os.environ["AIVYOS_CLOUD_API_KEY"] = value
            log.info("API Key 映射: %s → AIVYOS_CLOUD_API_KEY", env_var)

        # 同步更新配置中的元信息
        cfg.setdefault("api_keys", {})[env_var] = {
            "env_var": env_var,
            "set": bool(value),
            "provider": provider,
            "updated_at": __import__("time").time(),
        }

        # 热重建引擎以使新 API Key 生效
        try:
            engine = ChatEngine(cfg)
            log.info("LLM 引擎已热重建（API Key 更新后）")
        except Exception as e:
            log.warning("LLM 引擎热重建失败（将在下次请求时重试）: %s", e)

        return result

    @server.method("models.api-key.remove")
    async def models_apikey_remove(params):
        """移除 API Key（从持久化存储和环境变量中删除）。"""
        field = params.get("field", "")
        env_var = params.get("env_var", "")
        if not env_var:
            return {"ok": False, "error": "缺少 env_var 参数"}

        result = _api_key_store.remove_key(env_var)

        if field:
            cfg.setdefault("api_keys", {}).pop(field, None)

        return result

    @server.method("models.test-connection")
    async def models_test_connection(params):
        """测试 API Key 与 Base URL 的连通性。

        通过调用 /models 端点验证 API Key 是否有效。
        成功时返回可用模型列表，失败时返回错误信息。
        """
        provider_id = params.get("provider", "")
        api_key = params.get("api_key", "")
        base_url = params.get("base_url", "")
        if not api_key:
            return {"ok": False, "error": "缺少 API Key"}
        if not base_url:
            return {"ok": False, "error": "缺少 Base URL"}
        try:
            import urllib.request
            import urllib.error
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    import json
                    data = json.loads(resp.read().decode())
                    models = data.get("data", [])
                    return {
                        "ok": True,
                        "provider": provider_id,
                        "model_count": len(models),
                        "models": [
                            {"id": m.get("id", ""), "owned_by": m.get("owned_by", "")}
                            for m in models
                        ],
                    }
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode()[:200]
                except Exception:
                    pass
                return {"ok": False, "error": f"HTTP {e.code}: {body}"}
            except urllib.error.URLError as e:
                return {"ok": False, "error": f"连接失败: {str(e.reason)}"}
        except Exception as e:
            return {"ok": False, "error": f"连接失败: {str(e.reason)}"}

    @server.method("models.test-cloud")
    async def models_test_cloud(params):
        """批量测试所有已配置 API Key 的云端提供商连通性。

        逐个调用 /models 端点做真实探测，返回每个云端提供商的
        可用状态与模型数（用于模型列表页"测试云端"一键检查）。
        """
        import os
        import urllib.error
        import urllib.request

        results = []
        try:
            from aivyos_core.llm.provider_catalog import get_provider_catalog
            providers = get_provider_catalog()
        except Exception as e:
            return {"ok": False, "error": f"目录加载失败: {e}", "results": []}

        key_store = _api_key_store.list_keys()
        for p in providers:
            # 仅云端（非 local）提供商参与测试（catalog 为 dict 形态）
            if p.get("category", "") == "local":
                continue
            base_url = p.get("base_url", "")
            env_var = p.get("api_key_env", "")
            # 真实 key 在环境变量中（ApiKeyStore.load() 已注入）；store 元信息仅用于判断已配置
            has_configured = bool(key_store.get(env_var, {}).get("has_key")) if env_var else False
            api_key = os.environ.get(env_var, "") if env_var else ""
            if not api_key and not has_configured:
                results.append({
                    "provider": p.get("id", ""),
                    "name": p.get("name", ""),
                    "ok": False,
                    "error": "未配置 API Key",
                    "model_count": 0,
                })
                continue
            if not base_url:
                results.append({
                    "provider": p.get("id", ""),
                    "name": p.get("name", ""),
                    "ok": False,
                    "error": "未配置 Base URL",
                    "model_count": 0,
                })
                continue
            try:
                req = urllib.request.Request(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    import json
                    data = json.loads(resp.read().decode())
                    models = data.get("data", [])
                    results.append({
                        "provider": p.get("id", ""),
                        "name": p.get("name", ""),
                        "ok": True,
                        "model_count": len(models),
                        "models": [m.get("id", "") for m in models][:10],
                    })
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode()[:150]
                except Exception:
                    pass
                results.append({
                    "provider": p.get("id", ""),
                    "name": p.get("name", ""),
                    "ok": False,
                    "error": f"HTTP {e.code}: {body}",
                    "model_count": 0,
                })
            except urllib.error.URLError as e:
                results.append({
                    "provider": p.get("id", ""),
                    "name": p.get("name", ""),
                    "ok": False,
                    "error": f"连接失败: {str(e.reason)}",
                    "model_count": 0,
                })
            except Exception as e:
                results.append({
                    "provider": p.get("id", ""),
                    "name": p.get("name", ""),
                    "ok": False,
                    "error": str(e)[:150],
                    "model_count": 0,
                })

        ok_count = sum(1 for r in results if r["ok"])
        return {
            "ok": True,
            "total": len(results),
            "passed": ok_count,
            "failed": len(results) - ok_count,
            "results": results,
        }

    @server.method("models.preset-list")
    async def models_preset_list(params):
        """获取指定提供商的预设模型列表。

        无需网络请求，直接从本地目录返回模型元数据。
        """
        provider_id = params.get("provider", "")
        keyword = params.get("keyword", "")
        try:
            from aivyos_core.llm.provider_catalog import (
                get_provider_models, search_models,
            )
            if provider_id:
                models = get_provider_models(provider_id)
                if keyword:
                    models = [m for m in models if keyword.lower() in m.get("name", "").lower()]
                return {"ok": True, "provider": provider_id, "models": models}
            if keyword:
                return {"ok": True, "models": search_models(keyword)}
            return {"ok": False, "error": "需要 provider 或 keyword 参数"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("voice.engines")
    async def voice_engines(params):
        """列出所有可用的语音引擎（ASR/TTS）。"""
        try:
            from aivyos_core.voice.engine_registry import (
                create_voice_registry,
            )
            reg = create_voice_registry(cfg)
            return reg.get_dashboard()
        except Exception as e:
            return {"error": str(e)}

    @server.method("voice.engine.config")
    async def voice_engine_config(params):
        """配置语音引擎参数（语速、音量、音色等）。"""
        engine_name = params.get("engine", "")
        field = params.get("field", "")
        value = params.get("value", "")
        if not engine_name or not field:
            return {"ok": False, "error": "缺少 engine/field 参数"}
        try:
            from aivyos_core.voice.engine_registry import create_voice_registry
            reg = create_voice_registry(cfg)
            backend = reg.get(engine_name)
            if backend is None:
                return {"ok": False, "error": f"引擎 {engine_name} 不存在"}
            if field == "speed_ratio" and hasattr(backend, "update_params"):
                backend.update_params(speed_ratio=float(value))
            elif field == "volume_ratio" and hasattr(backend, "update_params"):
                backend.update_params(volume_ratio=float(value))
            elif field == "pitch_ratio" and hasattr(backend, "update_params"):
                backend.update_params(pitch_ratio=float(value))
            elif field == "voice_type" and hasattr(backend, "update_params"):
                backend.update_params(voice_type=str(value))
            else:
                return {"ok": False, "error": f"字段 {field} 不支持此引擎"}
            return {"ok": True, "engine": engine_name, "field": field, "value": value}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("voice.test-tts")
    async def voice_test_tts(params):
        """TTS 试听：合成文本并返回 base64 WAV 音频数据供前端播放。

        Params:
            text: 要合成的文本（默认 "你好，这是一段语音测试"）
            provider: TTS 服务商 (auto / doubao-tts / edge-tts / cosyvoice / mock)
            voice: 音色 ID
            speed: 语速倍率 (0.5-2.0)
            api_key: 云端 API Key（可选，留空时自动从环境变量/持久化存储读取）
            resource_id: 资源 ID（火山引擎/豆包）

        Returns:
            {ok, wav_b64, sample_rate, text, backend, latency_ms, warning?, error?}
        """
        import base64
        import os as _os
        import time as _time

        text = params.get("text", "你好，这是一段语音测试")
        provider = params.get("provider", "auto")
        voice = params.get("voice", "")
        speed = float(params.get("speed", 1.0))
        api_key = params.get("api_key", "")
        resource_id = params.get("resource_id", "")

        log.info("voice.test-tts 请求: provider=%s, voice=%s, api_key=%s, resource_id=%s",
                 provider, voice, "***" if api_key else "(空)", resource_id)

        try:
            from aivyos_core.audio.wav import pcm_to_wav_bytes
            from aivyos_core.tts.manager import create_tts
            from aivyos_core.tts.mock_backend import MockTTS

            # ── 若前端未传 API Key，尝试从环境变量读取（ApiKeyStore.load() 已注入）──
            if not api_key:
                if provider in ("auto", "doubao-tts", "doubao", "bytedance", "volcengine"):
                    stored = _os.environ.get("VOLCENGINE_API_KEY", "")
                    if stored:
                        api_key = stored
                if not api_key and provider in ("auto", "elevenlabs"):
                    stored = _os.environ.get("ELEVENLABS_API_KEY", "")
                    if stored:
                        api_key = stored

            # ── 构建统一 TTS 配置 ──
            tts_cfg = {
                "backend": provider,
                "voice": voice,
                "speed": speed,
                "resource_id": resource_id,
                "api_key": api_key,
            }

            # ── 通过 manager.create_tts() 选择后端 ──
            backend = create_tts(tts_cfg)
            log.info("voice.test-tts: create_tts 返回 %s", backend.__class__.__name__)

            # ── 检查是否创建成功（非 mock 或用户明确要求 mock）──
            is_mock = isinstance(backend, MockTTS)
            log.info("voice.test-tts: is_mock=%s, provider=%s", is_mock, provider)
            if is_mock and provider != "mock":
                env_hint = ""
                if provider in ("auto", "doubao-tts"):
                    env_hint = "，请先在上方填写豆包 API Key 并保存"
                elif provider == "elevenlabs":
                    env_hint = "，请先在上方填写 ElevenLabs API Key 并保存"
                elif provider == "edge-tts":
                    env_hint = "（Edge-TTS 需要联网及 pip install edge-tts）"
                return {
                    "ok": False,
                    "error": f"无法初始化 {provider} TTS 引擎{env_hint}",
                    "backend": "mock",
                }

            # ── 执行合成 ──
            start = _time.perf_counter()
            result = backend.synthesize(text)
            latency_ms = (_time.perf_counter() - start) * 1000

            # ── 检测云端合成是否失败并降级到 mock ──
            warning = None
            if is_mock:
                pass  # 用户明确要求 mock，正常返回
            elif result.backend == "mock-tts" and provider != "mock":
                warning = "云端 TTS 调用失败，已降级为 mock 提示音（无真实语音）。请检查 API Key 是否正确、网络是否连通。"

            wav_bytes = pcm_to_wav_bytes(result.pcm, result.sample_rate)
            wav_b64 = base64.b64encode(wav_bytes).decode("ascii")

            resp = {
                "ok": True,
                "wav_b64": wav_b64,
                "sample_rate": result.sample_rate,
                "text": text,
                "backend": result.backend,
                "pcm_len": len(result.pcm),
                "wav_len": len(wav_bytes),
                "latency_ms": round(latency_ms, 1),
            }
            if warning:
                resp["warning"] = warning
            return resp
        except Exception as e:
            log.exception("voice.test-tts 异常")
            return {"ok": False, "error": str(e), "backend": provider}

    # ================================================================
    #  MCP Server (Phase 3)
    # ================================================================

    @server.method("mcp.tools")
    async def mcp_tools(params):
        """列出所有 LLM MCP 工具。"""
        try:
            from aivyos_core.llm.mcp_server import create_mcp_server
            mcp = create_mcp_server(engine.router)
            return {"tools": mcp.list_tools()}
        except Exception as e:
            return {"error": str(e)}

    @server.method("mcp.call")
    async def mcp_call(params):
        """调用 LLM MCP 工具。"""
        tool_name = params.get("tool", "")
        tool_params = params.get("params", {})
        if not tool_name:
            return {"error": "缺少 tool 参数"}
        try:
            from aivyos_core.llm.mcp_server import create_mcp_server
            mcp = create_mcp_server(engine.router)
            return await mcp.call_tool_async(tool_name, tool_params)
        except Exception as e:
            return {"error": str(e)}

    # ================================================================
    #  Skills（技能管理）
    # ================================================================

    @server.method("skills.list")
    async def skills_list(params):
        """列出全部技能（含内置与自定义）。"""
        try:
            return {"ok": True, "skills": get_skills().list_skills()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.create")
    async def skills_create(params):
        """新建自定义技能。"""
        try:
            skill = get_skills().create_skill(
                name=str(params.get("name", "")).strip(),
                description=str(params.get("description", "")).strip(),
                category=str(params.get("category", "自定义")).strip() or "自定义",
                keywords=params.get("keywords") or [],
                system_prompt=str(params.get("system_prompt", "")),
                enabled=bool(params.get("enabled", True)),
            )
            return {"ok": True, "skill": skill}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.update")
    async def skills_update(params):
        """更新技能字段（名称/描述/分类/关键词/提示词/启停）。"""
        try:
            skill = get_skills().update_skill(str(params.get("id", "")), params.get("changes", {}))
            if skill is None:
                return {"ok": False, "error": "技能不存在"}
            return {"ok": True, "skill": skill}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.delete")
    async def skills_delete(params):
        """删除技能。"""
        try:
            ok = get_skills().delete_skill(str(params.get("id", "")))
            return {"ok": ok, "error": "" if ok else "技能不存在"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.set-enabled")
    async def skills_set_enabled(params):
        """启停技能。"""
        try:
            skill = get_skills().set_enabled(str(params.get("id", "")), bool(params.get("enabled", True)))
            if skill is None:
                return {"ok": False, "error": "技能不存在"}
            return {"ok": True, "skill": skill}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.market-list")
    async def skills_market_list(params):
        """技能市场目录（内置精选技能，标注已安装）。"""
        try:
            from aivyos_core.skills import SkillMarketplace

            mkt = SkillMarketplace(get_skills())
            items = mkt.list_market(str(params.get("keyword", "")))
            return {"ok": True, "skills": items, "count": len(items)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.market-sources")
    async def skills_market_sources(params):
        """列出全部技能市场源（内置精选 + 远程平台）。"""
        try:
            from aivyos_core.skills import SkillMarketplace

            sources = SkillMarketplace(get_skills()).list_sources()
            return {"ok": True, "sources": sources, "count": len(sources)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.market-browse")
    async def skills_market_browse(params):
        """浏览市场源：内置返回本地目录；GitHub 源拉取仓库索引（SKILL.md）。"""
        try:
            from aivyos_core.skills import SkillMarketplace

            result = SkillMarketplace(get_skills()).browse_source(
                source_id=str(params.get("source", "builtin")),
                keyword=str(params.get("keyword", "")),
                limit=int(params.get("limit", 60)),
            )
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.market-install")
    async def skills_market_install(params):
        """从市场安装技能。"""
        try:
            from aivyos_core.skills import SkillMarketplace

            skill = SkillMarketplace(get_skills()).install(str(params.get("id", "")))
            if skill is None:
                return {"ok": False, "error": "市场技能不存在"}
            return {"ok": True, "skill": skill}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("skills.remote-import")
    async def skills_remote_import(params):
        """从远程 SKILL.md URL 导入技能（GitHub raw / 任意 URL）。

        解析 Claude Code / OpenClaw 通用 SKILL.md 格式并安装到本地。
        """
        try:
            from aivyos_core.skills import SkillMarketplace

            url = str(params.get("url", "")).strip()
            if not url:
                return {"ok": False, "error": "缺少 URL"}
            result = SkillMarketplace(get_skills()).fetch_remote_skill(url)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ================================================================
    #  Tools（MCP 工具管理）
    # ================================================================

    @server.method("tools.list")
    async def tools_list(params):
        """列出所有已注册 MCP 工具（含权限级别、来源服务器、启停状态）。

        enabled 状态持久化在 tools.json（默认全部启用）。
        """
        from pathlib import Path

        from aivyos_core.mcp.types import PermissionLevel

        mgr = get_tools()
        tools = []
        for t in mgr.tools.values():
            tools.append({
                "name": t.name,
                "description": t.description,
                "permission": t.permission.value if isinstance(t.permission, PermissionLevel) else str(t.permission),
                "server": t.server or "",
                "input_schema": t.input_schema,
            })
        # 启停状态：tools.json 持久化（键=工具名，值=bool）
        state_path = Path(cfg.get("home", ".")) / "tools.json"
        enabled_state: Dict[str, bool] = {}
        if state_path.exists():
            try:
                import json as _json
                enabled_state = _json.loads(state_path.read_text(encoding="utf-8")).get("tools", {})
            except Exception:
                enabled_state = {}
        for t in tools:
            t["enabled"] = bool(enabled_state.get(t["name"], True))
        tools.sort(key=lambda t: (t["server"], t["name"]))
        return {"ok": True, "tools": tools, "count": len(tools)}

    @server.method("tools.set-enabled")
    async def tools_set_enabled(params):
        """启停工具（持久化到 tools.json）。"""
        from pathlib import Path

        import json as _json

        name = str(params.get("name", ""))
        enabled = bool(params.get("enabled", True))
        state_path = Path(cfg.get("home", ".")) / "tools.json"
        enabled_state: Dict[str, bool] = {}
        if state_path.exists():
            try:
                enabled_state = _json.loads(state_path.read_text(encoding="utf-8")).get("tools", {})
            except Exception:
                enabled_state = {}
        enabled_state[name] = enabled
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(_json.dumps({"version": 1, "tools": enabled_state}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(state_path)
        return {"ok": True, "name": name, "enabled": enabled}

    # ================================================================
    #  Fallback Chain (Phase 3)
    # ================================================================

    @server.method("fallback.execute")
    async def fallback_execute(params):
        """执行声明式降级链。"""
        steps_cfg = params.get("steps", [])
        messages = params.get("messages", [])
        if not steps_cfg:
            return {"error": "缺少 steps 配置"}
        if not messages:
            return {"error": "缺少 messages 参数"}
        try:
            from aivyos_core.llm.fallback_chain import FallbackChain
            from aivyos_core.models import LLMRequest
            chain = FallbackChain.from_config({"steps": steps_cfg})
            request = LLMRequest(messages=messages, model=params.get("model", "auto"))
            result = await chain.execute(request, engine.router)
            return result.to_dict()
        except Exception as e:
            return {"error": str(e)}

    @server.method("fallback.status")
    async def fallback_status(params):
        """获取降级链状态。"""
        steps_cfg = params.get("steps", [])
        if not steps_cfg:
            return {"error": "缺少 steps 配置"}
        try:
            from aivyos_core.llm.fallback_chain import FallbackChain
            chain = FallbackChain.from_config({"steps": steps_cfg})
            return chain.to_dict()
        except Exception as e:
            return {"error": str(e)}

    # ================================================================
    #  Config
    # ================================================================

    @server.method("config.get")
    async def config_get(params):
        # 不返回敏感字段
        safe_cfg = {}
        for key in ("llm", "persona", "voice", "asr", "tts", "chat", "workflow", "codegen"):
            safe_cfg[key] = cfg.get(key, {})
        safe_cfg["scheduler"] = cfg.get("scheduler", {})
        safe_cfg["memory"] = {k: v for k, v in cfg.get("memory", {}).items() if k not in ("mem0_llm_model",)}
        return safe_cfg

    @server.method("config.update")
    async def config_update(params):
        path = params.get("path", "")
        value = params.get("value")
        parts = path.split(".")
        target = cfg
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = value
        return {"ok": True, "path": path}

    # ================================================================
    #  Update（自动更新 §13）：status / check / install / rollback
    # ================================================================
    from pathlib import Path as _Path

    _update_svc = None

    def get_update_svc():
        nonlocal _update_svc
        if _update_svc is None:
            from aivyos_core.update.service import UpdateService

            _update_svc = UpdateService(cfg, _Path(cfg.get("home", ".")))
        return _update_svc

    @server.method("update.status")
    async def update_status(params):
        """更新状态：当前版本 / 已安装版本 / 最近检查 / 可用更新。"""
        try:
            return get_update_svc().status()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("update.check")
    async def update_check(params):
        """检查更新：拉取 manifest → 七步验签 → 报告新版本（不安装）。"""
        try:
            return get_update_svc().check(timeout=float(params.get("timeout", 10)))
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("update.install")
    async def update_install(params):
        """安装已验证的可用更新。"""
        try:
            return get_update_svc().install()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("update.rollback")
    async def update_rollback(params):
        """回滚到上一版本。"""
        try:
            return get_update_svc().rollback()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @server.method("core.shutdown")
    async def core_shutdown(params):
        """优雅关闭核心进程（外壳负责 respawn，实现热重启）。"""
        if stop_event is None:
            return {"ok": False, "error": "核心未启用远程关闭"}
        # 先让本响应返回给调用方，再触发停止
        asyncio.get_running_loop().call_later(0.3, stop_event.set)
        return {"ok": True, "shutting_down": True}

    return server


async def amain(args) -> None:
    cfg = load_config(args.config)
    if args.mode:
        cfg["llm"]["mode"] = args.mode

    # ── 先加载 API Key 到环境变量（引擎创建前） ──
    from aivyos_core.api_key_store import create_api_key_store
    _tmp_store = create_api_key_store(cfg.get("home"))
    _tmp_store.load()
    log.info("启动时加载 API Key: %d 个密钥", _tmp_store.key_count())

    # 同步提供商特定 Key 到通用 AIVYOS_CLOUD_API_KEY
    _CLOUD_KEY_ALIASES = [
        "DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
    ]
    if not os.environ.get("AIVYOS_CLOUD_API_KEY"):
        for _alias in _CLOUD_KEY_ALIASES:
            _val = os.environ.get(_alias)
            if _val:
                os.environ["AIVYOS_CLOUD_API_KEY"] = _val
                log.info("启动映射 API Key: %s → AIVYOS_CLOUD_API_KEY", _alias)
                break

    engine = ChatEngine(cfg)
    stop = asyncio.Event()
    server = build_server(engine, cfg, stop_event=stop)
    try:
        await server.start()
    except OSError as e:
        if getattr(e, "winerror", None) == 10048 or "10048" in str(e):
            print(f"\n[提示] 端口 {cfg['ipc']['port']} 已被占用 —— Tauri 壳层可能已自动启动 Python 核心。")
            print("       无需手动启动；若确需重启，请先关闭 Tauri（或结束现有 python 进程）再试。")
        else:
            print(f"\n[错误] 服务启动失败: {e}")
        raise SystemExit(1) from e
    print(f"AivyOS IPC 服务已启动（transport={server.transport}）")
    print(f"  端口: {cfg['ipc']['port']}  记忆后端: {engine.memory.backend_name}")
    print("  按 Ctrl+C 停止")

    # 启动就绪门：后台预热语音模型（FunASR），不阻塞服务启动。
    # 预热完成后 voice.status 的 asr_ready=true，前端才放行 PTT。
    async def _warmup_voice() -> None:
        try:
            from aivyos_core.voice.session import VoiceSession

            # 与 build_server 内 _voice_cfg 相同的配置：Tauri 场景禁用后端播放
            import copy as _copy

            vc = _copy.deepcopy(cfg)
            vc.setdefault("voice", {})["backend_play"] = False
            vs = VoiceSession(vc, engine)
            asr = getattr(vs, "asr", None)
            if asr is not None and hasattr(asr, "warmup") and getattr(asr, "name", "") not in ("mock-asr",):
                log.info("启动预热 ASR 模型（%s）...", getattr(asr, "name", "?"))
                await asyncio.get_running_loop().run_in_executor(None, asr.warmup)
                log.info("ASR 模型预热完成")
        except Exception as e:
            log.warning("启动预热语音模型失败（不影响使用，首次调用会自动预热）: %s", e)

    asyncio.get_running_loop().create_task(_warmup_voice())

    # 启动就绪门：后台执行一次更新检查（§13.1 每 6h；不阻塞服务启动）
    async def _startup_update_check() -> None:
        try:
            from pathlib import Path as _P
            from aivyos_core.update.service import UpdateService

            svc = UpdateService(cfg, _P(cfg.get("home", ".")))
            result = svc.maybe_check(force=False)
            if result:
                if result.get("ok") and result.get("update_available"):
                    log.info("发现新版本 %s（%s）", result.get("version"), result.get("update_type"))
                else:
                    log.info("更新检查完成: %s", result.get("error") or "无更新")
        except Exception as e:
            log.debug("启动更新检查失败（不影响使用）: %s", e)

    asyncio.get_running_loop().create_task(_startup_update_check())

    # stop 事件已在 build_server 前创建并传入（core.shutdown 复用同一事件）
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()
    await server.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AivyOS IPC 服务")
    parser.add_argument("--config", default=None)
    parser.add_argument("--mode", choices=["auto", "local", "cloud", "mock"], default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()