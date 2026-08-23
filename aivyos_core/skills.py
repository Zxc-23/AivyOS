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
    # ---- 双模型协同工作台（workbench 计划书 §4.1.3）----
    {
        "id": "claude-implement",
        "name": "Claude 实现",
        "category": "开发",
        "description": "调用 Claude Code CLI 实现功能、批量改代码",
        "keywords": ["claude", "让 claude 写", "claude 实现", "claude 写"],
        "system_prompt": "用户希望由 Claude Code 实现时：调用 MCP 工具 workbench_claude_run（L3，需用户确认），prompt 中写清需求、涉及文件与验收标准；返回结果后总结改动要点。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "codex-review",
        "name": "Codex 审查",
        "category": "开发",
        "description": "调用 Codex / ChatGPT CLI 审查代码、给出改进意见",
        "keywords": ["review", "审查", "让 gpt 看看", "codex 审查", "代码评审"],
        "system_prompt": "用户要求审查代码时：调用 MCP 工具 workbench_codex_run（L3，需用户确认），prompt 中包含待审查内容与审查重点；整理返回的问题清单按严重程度排序。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "codex-doc",
        "name": "Codex 文档生成",
        "category": "开发",
        "description": "调用 Codex / ChatGPT CLI 生成接口文档、Swagger",
        "keywords": ["生成文档", "写 swagger", "接口文档", "api 文档"],
        "system_prompt": "用户要求生成文档时：调用 MCP 工具 workbench_codex_run（L3，需用户确认），prompt 中说明接口信息与文档格式要求；返回后用 workbench_vscode_open 打开产出文件。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "dual-agent",
        "name": "双模型对比",
        "category": "开发",
        "description": "同一问题并行调用 Claude 与 Codex，对比两个模型的输出",
        "keywords": ["双模型", "一起", "对比", "两个模型", "compare"],
        "system_prompt": "用户要求双模型对比时：分别调用 workbench_claude_run 与 workbench_codex_run（L3，需用户确认）；输出时明确标记「共识部分」与「分歧部分」，分歧不自动取舍，由用户选择。",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "vscode-open",
        "name": "VS Code 打开",
        "category": "开发",
        "description": "在 VS Code 中打开指定文件或目录",
        "keywords": ["打开 vscode", "在编辑器里看", "用 vscode 打开", "vscode"],
        "system_prompt": "用户想在编辑器中查看时：调用 MCP 工具 workbench_vscode_open（L1）；VS Code CLI 不可用时提示用户手动打开并给出文件路径。",
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
        skill_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        sid = skill_id or ("sk_" + uuid.uuid4().hex[:8])
        if sid in self._skills:
            # 已存在同名 id → 覆盖更新（幂等安装）
            return self.update_skill(sid, {
                "name": name, "description": description, "category": category,
                "keywords": keywords or [], "system_prompt": system_prompt, "enabled": bool(enabled),
            }) or dict(self._skills[sid])
        skill = {
            "id": sid,
            "name": name,
            "description": description or name,
            "category": category or "自定义",
            "keywords": [k.strip() for k in (keywords or []) if k.strip()],
            "system_prompt": system_prompt,
            "enabled": bool(enabled),
            "builtin": False,
            "created_at": time.time(),
        }
        self._skills[sid] = skill
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


# =====================================================================
#  技能市场（Skill Marketplace）
# =====================================================================

# ---- 内置市场技能种子（可从市场一键安装到本地，含安装标记 source=market）----
MARKET_SKILLS: List[Dict[str, Any]] = [
    {
        "id": "mkt-meeting-minutes",
        "name": "会议纪要",
        "category": "办公",
        "description": "将会议内容整理为结构化纪要：结论、待办、责任人、截止时间",
        "keywords": ["会议", "纪要", "会议记录", "meeting", "minutes"],
        "system_prompt": "你是会议纪要助手。整理会议纪要时：1) 提取会议结论与决策；2) 列出待办事项并标注责任人与截止时间；3) 用「结论/待办/决议」三段式输出；4) 信息缺失时标注「待确认」。",
        "source": "market",
    },
    {
        "id": "mkt-resume-optimizer",
        "name": "简历优化",
        "category": "职场",
        "description": "优化简历：量化成果、突出亮点、适配目标岗位",
        "keywords": ["简历", "优化简历", "求职", "resume", "cv"],
        "system_prompt": "你是简历优化专家。优化简历时：1) 将描述转化为可量化的成果（数字+动词开头）；2) 针对目标岗位调整关键词；3) 控制单条经历 1-2 行；4) 给出修改理由。",
        "source": "market",
    },
    {
        "id": "mkt-interview-coach",
        "name": "面试模拟",
        "category": "职场",
        "description": "模拟面试官提问、评估回答、给出改进建议",
        "keywords": ["面试", "模拟面试", "面试官", "interview"],
        "system_prompt": "你是面试模拟教练。模拟面试时：1) 一次只问一个问题；2) 用 STAR 法则评估回答（情境-任务-行动-结果）；3) 回答后给出改进建议；4) 控制难度循序渐进。",
        "source": "market",
    },
    {
        "id": "mkt-translator",
        "name": "专业翻译",
        "category": "语言",
        "description": "中英互译，保留专业术语与语气风格",
        "keywords": ["翻译", "translate", "英文翻译", "中文翻译"],
        "system_prompt": "你是专业翻译。翻译时：1) 保持原文语气与专业术语；2) 技术文档保留术语一致性；3) 长句拆分为符合目标语言习惯的短句；4) 输出译文 + 关键术语对照表。",
        "source": "market",
    },
    {
        "id": "mkt-english-tutor",
        "name": "英语陪练",
        "category": "语言",
        "description": "英语对话陪练：纠错、扩展表达、分级难度",
        "keywords": ["英语", "英语练习", "口语", "english", "tutor"],
        "system_prompt": "你是英语陪练老师。陪练时：1) 用英语对话并纠正明显错误；2) 每次纠错后给出正确表达与 1 个扩展；3) 难度根据用户水平自适应；4) 会话结束总结新学表达。",
        "source": "market",
    },
    {
        "id": "mkt-data-analysis",
        "name": "数据分析",
        "category": "数据",
        "description": "分析数据：找趋势、异常、相关性，输出结论建议",
        "keywords": ["数据分析", "数据", "统计", "图表", "analysis"],
        "system_prompt": "你是数据分析师。分析数据时：1) 先明确指标与口径；2) 描述趋势与异常点；3) 区分相关性与因果性；4) 输出「结论-证据-建议」结构；5) 数据不足时明确说明。",
        "source": "market",
    },
    {
        "id": "mkt-excel-helper",
        "name": "Excel 公式助手",
        "category": "数据",
        "description": "Excel/表格公式、函数、数据清洗技巧",
        "keywords": ["excel", "表格", "公式", "函数", "vlookup"],
        "system_prompt": "你是 Excel 助手。解答表格问题时：1) 给出可直接使用的公式与说明；2) 复杂场景给出分步操作；3) 标注公式适用版本；4) 提供替代方案（Power Query/透视表）。",
        "source": "market",
    },
    {
        "id": "mkt-code-review",
        "name": "代码审查",
        "category": "开发",
        "description": "审查代码：可读性、性能、安全、边界条件",
        "keywords": ["代码审查", "review", "code review", "审查代码"],
        "system_prompt": "你是资深代码审查员。审查代码时：1) 按「严重性」分级列出问题（阻断/主要/建议）；2) 每个问题给出修复示例；3) 关注安全（注入/越权）与边界条件；4) 肯定写得好的部分。",
        "source": "market",
    },
    {
        "id": "mkt-debug-expert",
        "name": "Bug 定位专家",
        "category": "开发",
        "description": "根据报错信息与代码定位 bug，给出排查思路",
        "keywords": ["bug", "报错", "异常", "排错", "调试", "debug"],
        "system_prompt": "你是调试专家。定位 Bug 时：1) 先解读完整报错栈；2) 缩小范围：输入→处理→输出的二分法；3) 给出可执行的排查步骤；4) 修复后建议补充的回归测试。",
        "source": "market",
    },
    {
        "id": "mkt-api-docs",
        "name": "API 文档编写",
        "category": "开发",
        "description": "为接口生成规范文档：参数、示例、错误码",
        "keywords": ["api", "接口文档", "openapi", "swagger", "文档"],
        "system_prompt": "你是 API 文档工程师。编写接口文档时：1) 说明用途与权限要求；2) 列出请求/响应参数含类型与必填；3) 给出 curl 与 Python/JS 示例；4) 列出常见错误码与排查提示。",
        "source": "market",
    },
    {
        "id": "mkt-ppt-outline",
        "name": "PPT 大纲生成",
        "category": "创意",
        "description": "根据主题生成演示文稿大纲与演讲要点",
        "keywords": ["ppt", "演示文稿", "幻灯片", "大纲", "presentation"],
        "system_prompt": "你是演示设计助手。生成 PPT 大纲时：1) 先定核心结论（一页一观点）；2) 用「开场-问题-方案-案例-行动」结构；3) 每页给出标题与要点及建议配图；4) 附带演讲时间分配。",
        "source": "market",
    },
    {
        "id": "mkt-story-writer",
        "name": "故事创作",
        "category": "创意",
        "description": "创作故事：人物、冲突、节奏、多风格切换",
        "keywords": ["故事", "小说", "创作", "写作", "story"],
        "system_prompt": "你是故事创作助手。创作时：1) 先确认题材、篇幅与目标读者；2) 用「人物-目标-冲突-转折」构建骨架；3) 描写用动词与感官细节；4) 章节结尾留钩子。",
        "source": "market",
    },
    {
        "id": "mkt-image-prompt",
        "name": "绘图提示词",
        "category": "创意",
        "description": "生成高质量 AI 绘图提示词（Midjourney/Stable Diffusion）",
        "keywords": ["绘图", "提示词", "midjourney", "stable diffusion", "绘画"],
        "system_prompt": "你是 AI 绘画提示词工程师。生成提示词时：1) 结构：主体+环境+风格+光照+画质词；2) 给出 2-3 个变体（不同风格）；3) 附反向提示词；4) 说明关键参数（比例/镜头）。",
        "source": "market",
    },
    {
        "id": "mkt-meditation",
        "name": "冥想引导",
        "category": "健康",
        "description": "冥想与放松引导：呼吸练习、正念、减压",
        "keywords": ["冥想", "放松", "减压", "呼吸", "meditation"],
        "system_prompt": "你是冥想引导师。引导时：1) 语速缓慢、每句停顿；2) 先引导呼吸（吸气4秒-屏息2秒-呼气6秒）；3) 用身体扫描帮助放松；4) 结束时给回到当下的过渡。",
        "source": "market",
    },
    {
        "id": "mkt-meal-plan",
        "name": "健康食谱",
        "category": "健康",
        "description": "定制食谱：营养均衡、卡路里控制、食材替换",
        "keywords": ["食谱", "健康餐", "卡路里", "营养", "meal"],
        "system_prompt": "你是营养师。定制食谱时：1) 先确认目标（减脂/增肌/均衡）与忌口；2) 每日三餐+加餐，标注热量；3) 提供食材替换选项；4) 给出采购清单。",
        "source": "market",
    },
    {
        "id": "mkt-finance-tips",
        "name": "理财建议",
        "category": "生活",
        "description": "个人理财规划：预算、储蓄、投资基础知识",
        "keywords": ["理财", "预算", "储蓄", "投资", "记账"],
        "system_prompt": "你是理财顾问（合规提醒：不构成投资建议）。规划时：1) 先了解收入/支出/负债结构；2) 建议 50/30/20 预算法则起步；3) 风险提示前置；4) 推荐前说明各类资产的风险等级。",
        "source": "market",
    },
    {
        "id": "mkt-travel-planner",
        "name": "旅行规划",
        "category": "生活",
        "description": "行程规划：路线、预算、美食、注意事项",
        "keywords": ["旅行", "行程", "旅游", "攻略", "travel"],
        "system_prompt": "你是旅行规划师。规划行程时：1) 先确认天数、预算、偏好（人文/自然/美食）；2) 每日行程控制 2-3 个核心点避免赶路；3) 附交通方式与时间；4) 给出备选方案应对天气变化。",
        "source": "market",
    },
    {
        "id": "mkt-legal-basics",
        "name": "法律常识",
        "category": "生活",
        "description": "常见法律问题科普：合同、劳动、消费维权",
        "keywords": ["法律", "合同", "维权", "劳动法", "legal"],
        "system_prompt": "你是法律科普助手（不构成正式法律意见）。回答时：1) 用通俗语言解释法条；2) 标注「以最新法律法规为准」；3) 涉及重大权益建议咨询专业律师；4) 给出维权步骤与证据留存建议。",
        "source": "market",
    },
    {
        "id": "mkt-study-planner",
        "name": "学习计划",
        "category": "教育",
        "description": "制定学习计划：目标拆解、时间安排、复习策略",
        "keywords": ["学习", "计划", "备考", "复习", "study"],
        "system_prompt": "你是学习规划师。制定计划时：1) 先定目标与现有时间；2) 用「预习-学习-复习-测试」循环；3) 结合艾宾浩斯遗忘曲线安排复习；4) 每周留出弹性时间。",
        "source": "market",
    },
    {
        "id": "mkt-paper-summary",
        "name": "论文解读",
        "category": "教育",
        "description": "解读学术论文：核心贡献、方法、实验、局限",
        "keywords": ["论文", "文献", "paper", "解读论文"],
        "system_prompt": "你是学术解读助手。解读论文时：1) 用 3 句话概括核心贡献；2) 拆解方法与创新点；3) 评估实验设计有效性；4) 指出局限与后续方向；5) 术语首次出现附中文解释。",
        "source": "market",
    },
    {
        "id": "mkt-weather",
        "name": "天气查询",
        "category": "生活",
        "description": "查询实时天气、短期预报与趋势图表（免费，无需 API Key）",
        "keywords": ["天气", "气温", "下雨", "预报", "weather", "forecast", "气温", "天气图"],
        "system_prompt": "你是天气助手，使用完全免费、无需 API Key 的 wttr.in 服务查询天气。查询步骤：1) 确认城市（默认北京），城市名用英文（Beijing / Shanghai / Guangzhou / Shenzhen 等）；2) 实时天气：curl -s \"wttr.in/<城市>?format=3\"（如 Beijing: ⛅ +27°C）；3) 详细预报：curl -s \"wttr.in/<城市>?format=j1\" 返回 JSON，提取 current_condition 的 temp_C、humidity、windspeedKmph 与 weather 数组里未来 3 天的 mintempC/maxtempC、hourly 的 chanceofrain；4) 多城市对比：curl -s \"wttr.in/北京?format=3\" 逐个查询（支持中文名），或一次查多个用 + 连接（wttr.in/city1+city2）；5) 趋势图表：如需可视化图表，可用 wttr.in/<城市>_0p.png 生成 PNG 天气图（含温度曲线），用图片理解能力查看并描述趋势；6) 用中文报告：当前天气、气温、体感、降雨概率、未来 2-3 天趋势（对比时用表格列出各城市）；7) 命令失败（无网络/超时）时诚实告知，绝不编造天气。Windows 环境命令里 URL 必须用双引号包住（避免 ? 和 & 被 shell 解析）。",
        "source": "market",
    },
    {
        "id": "mkt-currency",
        "name": "汇率换算",
        "category": "生活",
        "description": "实时汇率查询与货币换算（免费，无需 API Key）",
        "keywords": ["汇率", "换算", "美元", "人民币", "欧元", "currency", "exchange rate", "USD", "CNY"],
        "system_prompt": "你是汇率助手，使用完全免费、无需 API Key 的 open.er-api.com 服务。查询步骤：1) 确认货币对（如 USD/CNY 美元兑人民币，EUR/USD 欧元兑美元）；2) 获取汇率：curl -s \"https://open.er-api.com/v6/latest/USD\"（基准货币大写，返回 JSON，rates 字段含所有货币汇率），或用 curl -s \"https://open.er-api.com/v6/latest/CNY\" 以人民币为基准；3) 换算公式：目标金额 = 源金额 × (目标货币汇率 / 源货币汇率)；4) 常用货币代码：CNY 人民币、USD 美元、EUR 欧元、JPY 日元、GBP 英镑、HKD 港币、KRW 韩元、AUD 澳元；5) 用中文报告：当前汇率、换算结果、汇率更新时间；6) 可同时报多个货币对对比；7) 命令失败时诚实告知，不编造汇率。Windows 环境 URL 用双引号包住。",
        "source": "market",
    },
    {
        "id": "mkt-world-time",
        "name": "世界时间",
        "category": "生活",
        "description": "查询世界各地时间与时差（本地计算，零网络依赖）",
        "keywords": ["时间", "时差", "时区", "世界时间", "几点", "东京时间", "timezone", "time"],
        "system_prompt": "你是时间助手。查询世界各地时间与时差：1) 用 Python 计算（零网络依赖）：from datetime import datetime, timezone, timedelta；now_utc = datetime.now(timezone.utc)；各城市时间 = now_utc + timedelta(hours=偏移)；2) 常用时区偏移（UTC+）：北京/上海/香港 +8、东京 +9、首尔 +9、悉尼 +10、伦敦 +0、巴黎/柏林 +1、纽约 -5、芝加哥 -6、洛杉矶 -8、新加坡 +8、迪拜 +4、莫斯科 +3；3) 时差计算：目标城市与用户所在城市的小时差 = 偏移差；4) 用中文报告：各城市当前时间（YYYY-MM-DD HH:MM）+ 与本地时差；5) 夏令时地区（欧美）提示可能相差 1 小时，建议以实际为准；6) 支持多城市同时查询，用列表呈现。",
        "source": "market",
    },
]


# ---- 技能市场源（内置 + 远程平台）----
MARKET_SOURCES: List[Dict[str, Any]] = [
    {
        "id": "builtin",
        "name": "内置精选",
        "desc": "AivyOS 预置的 20 个精选技能（离线可用）",
        "type": "builtin",
        "icon": "🛍️",
    },
    {
        "id": "agentskillexchange",
        "name": "AgentSkillExchange",
        "desc": "精选开放目录，支持 OpenClaw / Claude Code / Codex 等 40+ agent",
        "type": "github",
        "repo": "agentskillexchange/skills",
        "branch": "main",
        "icon": "🌐",
        "homepage": "https://github.com/agentskillexchange/skills",
    },
    {
        "id": "dukelyuu",
        "name": "Skills Marketplace",
        "desc": "首个开源技能市场（Claude Code / Cline / Cursor / Copilot）",
        "type": "github",
        "repo": "dukelyuu/skills-marketplace",
        "branch": "main",
        "icon": "🌐",
        "homepage": "https://github.com/dukelyuu/skills-marketplace",
    },
    {
        "id": "claude-skills",
        "name": "Claude Skills",
        "desc": "Claude Code 生态技能（skills.sh / 社区仓库）",
        "type": "github",
        "repo": "hoveychen/claude-skills",
        "branch": "main",
        "icon": "🌐",
        "homepage": "https://github.com/hoveychen/claude-skills",
    },
    {
        "id": "openclaw-skills",
        "name": "OpenClaw Skills",
        "desc": "OpenClaw 生态技能（兼容 agentskills.io）",
        "type": "github",
        "repo": "dAAAb/openclaw-skills",
        "branch": "main",
        "icon": "🌐",
        "homepage": "https://github.com/dAAAb/openclaw-skills",
    },
    {
        "id": "ai-skills",
        "name": "AI Skills Hub",
        "desc": "Claude Code / Manus / OpenClaw 等多 agent 技能合集",
        "type": "github",
        "repo": "bytesagain/ai-skills",
        "branch": "main",
        "icon": "🌐",
        "homepage": "https://github.com/bytesagain/ai-skills",
    },
]


class SkillMarketplace:
    """技能市场：内置精选技能 + 多平台远程接入。

    远程接入：解析 Claude Code / OpenClaw 通用的 SKILL.md 格式
    （YAML frontmatter：name/description，正文为 system_prompt），
    支持从 GitHub 仓库浏览（git trees API 索引 + raw 拉取解析）与安装。
    """

    def __init__(self, local: SkillManager) -> None:
        self.local = local

    # ---- 市场源 ----
    def list_sources(self) -> List[Dict[str, Any]]:
        """返回全部市场源（含技能数）。"""
        out = []
        for s in MARKET_SOURCES:
            item = dict(s)
            if s["type"] == "builtin":
                item["skill_count"] = len(MARKET_SKILLS)
            else:
                item["skill_count"] = 0  # 远程源计数需浏览后获取
            out.append(item)
        return out

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        return next((s for s in MARKET_SOURCES if s["id"] == source_id), None)

    # ---- 市场目录 ----
    def list_market(self, keyword: str = "") -> List[Dict[str, Any]]:
        """列出市场技能；keyword 过滤名称/描述/关键词。"""
        out = []
        for s in MARKET_SKILLS:
            item = dict(s)
            item["installed"] = self.local.get_skill(item["id"]) is not None
            out.append(item)
        if keyword:
            k = keyword.lower()
            out = [s for s in out if k in s["name"].lower() or k in s["description"].lower()
                   or any(k in str(x).lower() for x in s.get("keywords", []))]
        return out

    def install(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """从市场安装技能到本地（幂等：已存在则更新，不存在则创建）。"""
        spec = next((s for s in MARKET_SKILLS if s["id"] == skill_id), None)
        if spec is None:
            return None
        existing = self.local.get_skill(skill_id)
        fields = {
            "name": spec["name"],
            "description": spec["description"],
            "category": spec["category"],
            "keywords": spec["keywords"],
            "system_prompt": spec["system_prompt"],
            "enabled": True,
        }
        if existing:
            return self.local.update_skill(skill_id, fields)
        created = self.local.create_skill(
            name=fields["name"], description=fields["description"],
            category=fields["category"], keywords=fields["keywords"],
            system_prompt=fields["system_prompt"], enabled=True,
            skill_id=skill_id,
        )
        return self.local.get_skill(skill_id) or created

    def install_by_id(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """按 id 安装（保持与 MARKET_SKILLS 中 id 一致）。"""
        spec = next((s for s in MARKET_SKILLS if s["id"] == skill_id), None)
        if spec is None:
            return None
        return self.install(skill_id)

    # ---- 远程市场浏览（GitHub 仓库索引）----
    def browse_source(
        self,
        source_id: str,
        keyword: str = "",
        limit: int = 60,
        timeout: float = 20.0,
    ) -> Dict[str, Any]:
        """浏览市场源：内置返回本地目录；GitHub 源用 trees API 索引 SKILL.md。

        返回 {"ok", "source", "skills": [...], "total"}
        远程技能的 installed 通过本地是否已有同名（name 归一化 id）判断。
        """
        src = self.get_source(source_id)
        if src is None:
            return {"ok": False, "error": f"未知市场源: {source_id}"}
        if src["type"] == "builtin":
            skills = self.list_market(keyword)
            return {"ok": True, "source": src, "skills": skills, "total": len(skills)}

        if src["type"] == "github":
            try:
                items = self._browse_github(src, limit=limit, timeout=timeout)
            except Exception as e:
                return {"ok": False, "error": f"浏览失败: {e}", "source": src, "skills": []}
            if keyword:
                k = keyword.lower()
                items = [s for s in items if k in s["name"].lower() or k in s["description"].lower()
                         or any(k in str(x).lower() for x in s.get("keywords", []))]
            return {"ok": True, "source": src, "skills": items, "total": len(items)}
        return {"ok": False, "error": f"不支持的市场类型: {src.get('type')}", "source": src, "skills": []}

    def _browse_github(
        self,
        src: Dict[str, Any],
        limit: int = 60,
        timeout: float = 20.0,
    ) -> List[Dict[str, Any]]:
        """用 GitHub git trees API 递归列出仓库文件，过滤 SKILL.md 并解析。"""
        import urllib.request

        repo = src.get("repo", "")
        branch = src.get("branch", "main")
        api_url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
        req = urllib.request.Request(api_url, headers={"User-Agent": "AivyOS-SkillMarket", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        tree = data.get("tree", [])
        skill_paths = [t["path"] for t in tree if t.get("type") == "blob" and t.get("path", "").upper().endswith("SKILL.MD")]

        out: List[Dict[str, Any]] = []
        for path in skill_paths[:limit]:
            raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
            try:
                parsed = self.fetch_remote_skill_preview(raw_url, timeout=6.0)
                if parsed.get("ok"):
                    skill = parsed["skill"]
                    skill["source_url"] = raw_url
                    skill["source_path"] = path
                    sid = str(skill.get("name", "")).strip().lower().replace(" ", "-")
                    skill["installed"] = self.local.get_skill(sid) is not None
                    out.append(skill)
                    continue
            except Exception:
                pass
            # raw 拉取失败（限速/网络）→ 用路径生成最小条目，安装时再拉取
            name = _path_skill_name(path)
            sid = name.lower().replace(" ", "-")
            out.append({
                "id": sid,
                "name": name,
                "category": "远程",
                "description": f"来自 {repo}（点击预览可加载详细提示词）",
                "keywords": [],
                "system_prompt": "",
                "installed": self.local.get_skill(sid) is not None,
                "source_url": raw_url,
                "source_path": path,
                "needs_fetch": True,
            })
        return out

    def fetch_remote_skill_preview(self, url: str, timeout: float = 10.0) -> Dict[str, Any]:
        """拉取 SKILL.md 并解析（不安装，返回预览）。"""
        import urllib.request

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AivyOS-SkillMarket"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "error": f"拉取失败: {e}"}
        parsed = parse_skill_md(text, fallback_name=_url_skill_name(url))
        return parsed

    # ---- 远程 SKILL.md 接入 ----
    def fetch_remote_skill(self, url: str, timeout: float = 15.0) -> Dict[str, Any]:
        """从远程 URL 拉取 SKILL.md 并解析为技能。

        支持：GitHub raw / 任意返回 SKILL.md 文本的 URL。
        SKILL.md 格式（Claude Code / OpenClaw 通用）：
            ---
            name: xxx
            description: xxx
            ---
            正文（作为 system_prompt）
        解析失败时 name 回退为 URL 文件名，正文作为 system_prompt。
        """
        parsed = self.fetch_remote_skill_preview(url, timeout=timeout)
        if not parsed.get("ok"):
            return parsed
        return {
            "ok": True,
            "preview": parsed["skill"],
            "install": self._import_parsed(parsed["skill"]),
        }

    def _import_parsed(self, skill: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """把解析出的技能写入本地（来源 remote），保留稳定 id（如 doc-writer）。"""
        sid = str(skill.get("id") or skill.get("name", "")).strip().lower().replace(" ", "-")
        if not sid or sid in ("远程技能",):
            sid = "sk_" + uuid.uuid4().hex[:8]
        return self.local.create_skill(
            name=skill["name"],
            description=skill.get("description", ""),
            category=skill.get("category", "远程导入"),
            keywords=skill.get("keywords", []),
            system_prompt=skill.get("system_prompt", ""),
            enabled=True,
            skill_id=sid,
        )

    def import_skill_md(self, skill: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """直接导入已解析的技能字典（IPC 用）。"""
        return self._import_parsed(skill)


def parse_skill_md(text: str, fallback_name: str = "远程技能") -> Dict[str, Any]:
    """解析 SKILL.md（YAML frontmatter + 正文）。

    返回 {"ok": True, "skill": {...}} 或 {"ok": False, "error": ...}
    """
    import re

    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "内容为空"}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        # 无 frontmatter → 全文作为 system_prompt
        return {
            "ok": True,
            "skill": {
                "name": fallback_name,
                "description": "",
                "keywords": [],
                "system_prompt": text[:4000],
            },
        }
    front_raw, body = m.group(1), m.group(2).strip()
    fields: Dict[str, Any] = {}
    for line in front_raw.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip().strip("\"'")
        if key == "name":
            fields["name"] = val
        elif key == "description":
            fields["description"] = val
        elif key == "category":
            fields["category"] = val
        elif key in ("keywords", "tags"):
            # 支持逗号分隔或列表
            if val.startswith("["):
                val = val.strip("[]")
            fields["keywords"] = [k.strip().strip("\"'") for k in val.split(",") if k.strip()]
    return {
        "ok": True,
        "skill": {
            "name": fields.get("name") or fallback_name,
            "description": fields.get("description", ""),
            "category": fields.get("category", "远程导入"),
            "keywords": fields.get("keywords", []),
            "system_prompt": body[:4000],
        },
    }


def _url_skill_name(url: str) -> str:
    """从 URL 推导技能名（如 .../skills/translate/SKILL.md → translate）。"""
    name = url.rstrip("/").split("/")[-1]
    if name.upper() == "SKILL.MD":
        name = url.rstrip("/").split("/")[-2] if "/" in url.rstrip("/") else "远程技能"
    return name.replace("-", " ").replace("_", " ").strip() or "远程技能"


def _path_skill_name(path: str) -> str:
    """从仓库路径推导技能显示名（.../skills/xxx/SKILL.md → xxx）。"""
    parts = [p for p in path.split("/") if p]
    if parts and parts[-1].upper() == "SKILL.MD":
        parts = parts[:-1]
    name = parts[-1] if parts else "远程技能"
    return name.replace("-", " ").replace("_", " ").strip() or "远程技能"
