"""技能管理（Skills）：可复用能力单元 + JSON 持久化。

技能 = 命名能力单元（如"邮件处理""日程查询""周报生成"），每条技能包含：
- 名称 / 描述 / 分类
- 触发词（keywords）：对话中命中即唤起该技能提示
- 系统提示词模板（system_prompt）：注入 LLM 上下文，指导行为
- 启停开关：enabled

持久化：JSON 文件（原子写），内置技能首次初始化时写入。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---- 内置技能种子（首次运行时写入，用户可编辑/删除）----
BUILTIN_SKILLS: List[Dict[str, Any]] = [
    {
        "id": "email-handler",
        "name": "邮件处理",
        "category": "办公",
        "description": "帮我处理邮件：整理收件箱、提取要点、起草回复",
        "keywords": ["邮件", "收件箱", "发邮件", "回复邮件", "mail", "email"],
        "system_prompt": "你是邮件助手。处理邮件请求时：1) 先确认收件箱状态；2) 按优先级整理要点；3) 起草回复时保持简洁专业；4) 涉及发送前必须向用户确认。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "schedule-helper",
        "name": "日程查询",
        "category": "办公",
        "description": "查询日程安排、规划时间、设置提醒",
        "keywords": ["日程", "安排", "提醒", "日历", "schedule", "calendar"],
        "system_prompt": "你是日程助手。查询或规划日程时：1) 先明确时间范围；2) 冲突时提示并给出调整建议；3) 设置提醒需明确时间和事项。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "weekly-report",
        "name": "周报生成",
        "category": "办公",
        "description": "根据本周工作内容自动生成周报",
        "keywords": ["周报", "工作总结", "汇报", "report"],
        "system_prompt": "你是周报助手。生成周报时：1) 按「本周完成/进行中/下周计划/风险与求助」结构组织；2) 用数据说话，量化成果；3) 语言简洁正式。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "scheduler-tasks",
        "name": "定时任务",
        "category": "自动化",
        "description": "创建和管理定时任务、周期触发器",
        "keywords": ["定时", "定时任务", "每天早上", "每天", "周期性", "cron"],
        "system_prompt": "你是定时任务助手。创建定时任务时：1) 确认执行频率与具体时间；2) 明确任务内容与期望输出；3) 创建后告知用户任务编号与下次执行时间。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "image-understand",
        "name": "看图理解",
        "category": "智能",
        "description": "分析图片内容、识别物体与场景、回答图片相关问题",
        "keywords": ["图片", "看图", "照片", "识别", "image", "photo"],
        "system_prompt": "你是视觉助手。用户提供图片时：1) 先调用视觉理解能力分析内容；2) 描述关键元素与场景；3) 结合图片回答用户的具体问题。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "code-vibe",
        "name": "代码生成",
        "category": "开发",
        "description": "根据需求生成代码、解释代码、代码审查",
        "keywords": ["写代码", "代码", "开发", "实现", "bug", "code"],
        "system_prompt": "你是编程助手。处理代码请求时：1) 先确认需求与语言/框架；2) 给出可运行示例并解释关键点；3) 审查代码时指出问题并给修复建议。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "voice-chat",
        "name": "语音对话",
        "category": "智能",
        "description": "语音交互增强：语速控制、唤醒词、连续对话",
        "keywords": ["语音", "说话", "朗读", "voice", "speak"],
        "system_prompt": "你是语音助手。语音交互时：1) 回复尽量简短口语化；2) 关键信息放句首；3) 需要确认时给出明确选项。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "memory-retrieve",
        "name": "记忆检索",
        "category": "智能",
        "description": "查询历史记忆、事实档案、知识卡片",
        "keywords": ["记得", "记忆", "之前", "知识卡片", "remember", "memory"],
        "system_prompt": "你是记忆助手。检索记忆时：1) 用关键词匹配历史事实；2) 返回结果标注时间与来源；3) 未命中时诚实说明并建议补充。",
        "enabled": True,
        "builtin": True,
    },
]


class SkillManager:
    """技能管理：加载/保存/增删改/启停/匹配。"""

    def __init__(self, storage_path: Optional[str | Path] = None) -> None:
        self._path = Path(storage_path) if storage_path else Path("skills.json")
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ---- 持久化 ----
    def _load(self) -> None:
        if not self._path.exists():
            self._skills = {s["id"]: dict(s) for s in BUILTIN_SKILLS}
            try:
                self._save()
            except Exception as e:
                # 文件系统不可写（沙箱/权限）→ 内存态继续可用
                log.warning("内置技能初始化写入失败（内存态可用）: %s", e)
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._skills = data.get("skills", {})
        except Exception as e:
            log.error("技能文件加载失败，回退内置: %s", e)
            self._skills = {s["id"]: dict(s) for s in BUILTIN_SKILLS}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"version": 1, "skills": self._skills}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    # ---- 查询 ----
    def list_skills(self) -> List[Dict[str, Any]]:
        out = []
        for s in self._skills.values():
            item = dict(s)
            item.setdefault("enabled", True)
            out.append(item)
        out.sort(key=lambda s: (not s.get("enabled", True), s.get("category", ""), s.get("name", "")))
        return out

    def get_skill(self, skill_id: str) -> Optional[Dict[str, Any]]:
        return self._skills.get(skill_id)

    def match(self, text: str) -> List[Dict[str, Any]]:
        """按触发词匹配启用的技能（返回按命中数排序的列表）。"""
        text_l = text.lower()
        hits = []
        for s in self._skills.values():
            if not s.get("enabled", True):
                continue
            kws = [str(k).lower() for k in s.get("keywords", [])]
            n = sum(1 for k in kws if k in text_l)
            if n > 0:
                hits.append((n, s))
        hits.sort(key=lambda x: -x[0])
        return [dict(s) for _, s in hits]

    # ---- 增删改 ----
    def create_skill(
        self,
        name: str,
        description: str = "",
        category: str = "自定义",
        keywords: Optional[List[str]] = None,
        system_prompt: str = "",
        enabled: bool = True,
    ) -> Dict[str, Any]:
        skill_id = "sk_" + uuid.uuid4().hex[:8]
        skill = {
            "id": skill_id,
            "name": name,
            "description": description or name,
            "category": category or "自定义",
            "keywords": [k.strip() for k in (keywords or []) if k.strip()],
            "system_prompt": system_prompt,
            "enabled": bool(enabled),
            "builtin": False,
            "created_at": time.time(),
        }
        self._skills[skill_id] = skill
        self._save()
        return dict(skill)

    def update_skill(self, skill_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        skill = self._skills.get(skill_id)
        if skill is None:
            return None
        for key in ("name", "description", "category", "keywords", "system_prompt", "enabled"):
            if key in changes:
                if key == "keywords":
                    skill[key] = [k.strip() for k in (changes[key] or []) if str(k).strip()]
                else:
                    skill[key] = changes[key]
        skill["updated_at"] = time.time()
        self._save()
        return dict(skill)

    def delete_skill(self, skill_id: str) -> bool:
        if skill_id not in self._skills:
            return False
        del self._skills[skill_id]
        self._save()
        return True

    def set_enabled(self, skill_id: str, enabled: bool) -> Optional[Dict[str, Any]]:
        return self.update_skill(skill_id, {"enabled": bool(enabled)})

    # ---- 集成：把匹配技能的 system_prompt 附加到对话 ----
    def context_blocks(self, text: str, max_skills: int = 2) -> List[str]:
        """命中技能 → 生成可注入 System Prompt 的上下文块。"""
        matched = self.match(text)[:max_skills]
        blocks = []
        for s in matched:
            prompt = (s.get("system_prompt") or "").strip()
            if prompt:
                blocks.append(f"## 技能[{s['name']}]\n{prompt}")
        return blocks
