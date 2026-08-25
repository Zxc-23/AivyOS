# AIVY-FEAT-CORE-001 四大核心功能 Implementation Plan（主动调度器 / 向量数据库 / 记忆连续性 / 知识卡片）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 AivyOS 四大核心能力（① 主动调度器 Cron/事件/条件三触发 ② 向量数据库 Chroma 零依赖接入 ③ mem0 记忆连续性合约对齐 ④ 知识卡片系统=向量+记忆+前端 UI），遵循 YAGNI/DRY/单真源原则；记忆/向量/知识卡片三层通过 `class MemoryStore(CompositeMemory)` 聚合对外，主动调度器独立于记忆，避免环依赖；**全部 40+ 新增单测 TDD 红→绿 + discover 零回归**。

**Architecture:** 4 个独立功能按依赖链单向执行：
- ① 主动调度器（独立模块，任何位置可插入，不依赖记忆/向量/知识）先做
- ② 向量数据库（基础索引层，被 记忆/知识 依赖）做第二
- ③ 记忆连续性增强（依赖向量数据库做 semantically search，对齐 `test_mem0_contract.py` 合约接口）第三
- ④ 知识卡片系统（依赖向量数据库 + 记忆，含数据层/索引层/前端 UI）第四
全部新增函数带中文函数级注释（用户规则 5.6）；**零新增非可选依赖**（Chroma/mem0 全部有降级 Mock 实现，requirements-optional 可选）。

**Tech Stack:** Python 3.11 stdlib + schedule（轻量 cron）/ unittest + TypeScript React 18（知识卡片 UI 追加）；严格 Windows PowerShell 5.1；单真源：`aivyos_core/memory/memory_store.py` = 记忆聚合唯一入口，`aivyos_core/knowledge/cards.py` = 知识卡片唯一出口。

---

## 文件结构（File Structure）

| 路径 | 角色 | 操作 | 关键行范围 |
|---|---|---|---|
| `aivyos_core/scheduler/__init__.py` | 模块入口导出 ActiveScheduler / CronTrigger / EventTrigger / ConditionTrigger | Create | — |
| `aivyos_core/scheduler/triggers.py` | 三触发器类（CronTrigger / EventTrigger / ConditionTrigger） + `next_fire_at()` 抽象 | Create | 3 个 dataclass |
| `aivyos_core/scheduler/registry.py` | JobRegistry：注册/注销/持久化（SQLite 表 jobs_scheduler 与 jobs_memory/knowledge 分开） | Create | register(id, trigger, coro_fn_ref_or_name, args) |
| `aivyos_core/scheduler/runner.py` | ActiveScheduler：单线程 asyncio.TaskGroup + 调度循环（1s 轮询，用 time.perf_counter） | Create | start() / stop() / run_once() / fire_event(name, payload) / evaluate_conditions() |
| `aivyos_core/vector/__init__.py` | 模块入口导出 VectorStore / QueryResult | Create | — |
| `aivyos_core/vector/base.py` | VectorStore ABC（embed / query / delete / upsert）+ MockInMemoryVectorStore（纯 stdlib，默认降级） | Create | 4 抽象方法 + Mock 实现 |
| `aivyos_core/vector/chroma_store.py` | ChromaVectorStore（Chroma 可选依赖） | Create | ChromaDB HTTP/本地 PersistentClient 两种 client |
| `aivyos_core/memory/mem0_adapter.py` | Mem0Adapter：对齐 test_mem0_contract.py 合约（add / search / get / update / delete / history） | Create | 100% 接口对齐；未装 mem0 时自动用 MockInMemoryMemory（vector+sqlite 混合） |
| `aivyos_core/memory/memory_store.py` | CompositeMemory = ShortTerm(环形 FIFO) + LongTerm(Mem0Adapter/search-by-vec) + ActiveScheduler 事件联动写记忆 | Create | 对外统一 MemoryStore |
| `aivyos_core/knowledge/cards.py` | KnowledgeCard dataclass + CardManager（upsert/search/delete/tag/collection） | Create | data model + manager |
| `shell/src/pages/KnowledgeCardsPage.tsx` | 知识卡片前端 UI（搜索框 + Tags 过滤 + 卡片瀑布流 + 详情 Modal + 新建卡片 Form） | Create | TSX |
| `shell/src/routes.tsx` | 路由追加 `/knowledge` → KnowledgeCardsPage | Modify | 原 routes list 末尾追加 |
| `aivyos_core/voice/session.py` | VoiceSession.run_turn 调用 MemoryStore.add() 写对话记忆 | Modify | run_turn 返回前调用 memory_store.add |
| `aivyos_core/server_entry.py` | FastAPI 追加 `GET /api/v1/knowledge/cards?limit=50` / `POST /api/v1/knowledge/cards` | Modify | app 注册路由 |
| `tests/test_scheduler.py` | 新增：三触发器 + 注册中心 + ActiveScheduler 单测（18 tests） | Create | — |
| `tests/test_vector_store.py` | 新增：base 协议 + Mock 全功能 + Chroma skipIf 降级（14 tests） | Create | — |
| `tests/test_mem0_adapter.py` | 新增：mem0 合约接口 100% 对齐；未装 mem0 时 Mock 14 tests | Create | — |
| `tests/test_knowledge_cards.py` | 新增：CardManager CRUD + 搜索 + Tag 过滤 + UI smoke（12 tests） | Create | — |
| `说明文档.md` | §二 §2.6 核心四功能实施方案 + §三 ×4 行 + §1.4 当前目标 3 追加 → 共 8 条 | Modify | §1.4 3→7 条 / §二 §2.6 / §三 进度尾 4 行 |

---

## 硬约束 / 设计不变量

| ID | 不变量 | 出处 |
|---|---|---|
| INV-1 | **零环依赖**：scheduler 不引 vector/memory/knowledge；vector 不引 memory/knowledge；memory 引 vector；knowledge 引 memory+vector | 本计划 |
| INV-2 | **全组件优雅降级**：无 schedule / chromadb / mem0 任何第三方时，Mock 实现自动加载不抛 ImportError（100% stdlib 可跑） | project_memory Lessons Learned |
| INV-3 | **主动调度器 1s 轮询精度**：time.perf_counter 粒度 < 1μs；CronTrigger 偏差 ≤ 1s | 历史 monotonic→perf_counter 经验 |
| INV-4 | **向量 DB top_k 默认 5**，score 范围 [0, 1]；cosine similarity 越接近 1 越相关 | Chroma 默认约定 |
| INV-5 | **记忆三写入口统一**：MemoryStore.add() = 同时写 ① ShortTerm FIFO ring ② LongTerm(mem0/其 Mock) ③ ActiveScheduler Event("memory_added") 广播（如果有监听卡片） | 单真源原则 |
| INV-6 | **知识卡片 = 语义分片 + 向量索引 + 元数据**：分片 size 默认 512 tokens / overlap 64（project_memory 文档分片常量） | 复用 report 分片常量 |
| INV-7 | **记忆去重**：同一 user_id + 相同 normalized_text（去标点/空格/大小写）7 天内只保留最新一条 | test_mem0_contract.py dedup 约定（如果合约有） |
| INV-8 | **中文/英文函数注释 100% 覆盖**：每个 public 类 + 每个 public 方法必须中文 docstring（功能/参数/返回/异常） | 用户规则 5.6 |

---

### Task 1: 主动调度器（三触发器 + 注册中心 + 执行管线）

**Files:**
- Create: `aivyos_core/scheduler/__init__.py` / `triggers.py` / `registry.py` / `runner.py`
- Test: `tests/test_scheduler.py`（18 tests）

- [ ] **Step 1: Write failing tests（测试先行）**

```python
"""tests/test_scheduler.py - 主动调度器三触发器 + 注册中心 + ActiveScheduler。"""
import asyncio
import time
import unittest
from datetime import datetime, timedelta
from typing import Optional


class TestCronTrigger(unittest.TestCase):
    def test_every_minute_next_fire_within_60s(self):
        """每分钟触发：距离 next_fire_at ≤ 60s。"""
        from aivyos_core.scheduler.triggers import CronTrigger
        t = CronTrigger("* * * * *")  # 每分钟
        nxt = t.next_fire_at(after=datetime.now())
        self.assertIsNotNone(nxt)
        self.assertLessEqual((nxt - datetime.now()).total_seconds(), 62)  # 容差 2s

    def test_every_day_9am_returns_future(self):
        """每日 09:00：下次触发必须是未来。"""
        from aivyos_core.scheduler.triggers import CronTrigger
        t = CronTrigger("0 9 * * *")
        nxt = t.next_fire_at(after=datetime.now())
        self.assertGreaterEqual(nxt, datetime.now())


class TestEventTrigger(unittest.TestCase):
    def test_fire_matching_name_invokes_job(self):
        """事件名匹配 → 调用 job。"""
        from aivyos_core.scheduler.runner import ActiveScheduler
        calls = []
        async def job(payload):
            calls.append(payload)

        async def run():
            s = ActiveScheduler()
            s.add_event_listener("user_joined", job)
            await s.fire_event("user_joined", {"name": "Alice"})
            await asyncio.sleep(0.01)
            return calls

        result = asyncio.run(run())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Alice")


class TestConditionTrigger(unittest.TestCase):
    def test_eval_py_expr_true_then_fires_once(self):
        """条件表达式 True → 触发一次，之后冷却 60s 不再触发。"""
        from aivyos_core.scheduler.triggers import ConditionTrigger
        # 条件：counter >= 3（每次 evaluate 检查 ctx.counter）
        t = ConditionTrigger(expr="ctx['counter'] >= 3", cooldown_seconds=60)
        self.assertTrue(t.evaluate({"counter": 3}))
        # 触发后立刻再 eval：cooldown 内应 False
        self.assertFalse(t.evaluate({"counter": 3}))


class TestRegistry(unittest.TestCase):
    def test_register_unregister_roundtrip(self):
        """注册/注销 roundtrip 后 get 返回 None。"""
        from aivyos_core.scheduler.registry import JobRegistry
        async def j(): return 1
        r = JobRegistry()
        r.register("j1", CronTrigger("* * * * *"), j)
        self.assertIsNotNone(r.get("j1"))
        r.unregister("j1")
        self.assertIsNone(r.get("j1"))
```

- [ ] **Step 2: Run failing test → FAIL（ModuleNotFoundError: No module named aivyos_core.scheduler）**
- [ ] **Step 3: Implement 4 files（中注释 100%）**
  - 3.1 triggers.py：Cron 用 croniter（装了则用，没装则内部最小手写 parse_every_minute / parse_hhmm；优先 croniter，无则 MockCronParser 只支持 `* * * * *` 和 `M H * * *` 两种常见模式（足够 MVP））
  - 3.2 registry.py：用 SQLite 表 `scheduler_jobs(id TEXT PK, kind TEXT, spec TEXT, fn_ref TEXT, args_json TEXT, enabled INT, last_fired_ts REAL, created_ts REAL)`
  - 3.3 runner.py：ActiveScheduler 单线程，run_forever while loop sleep(0.25)；每 1s 轮询 Cron+Condition；fire_event 是 asyncio.Queue.put_nowait 立即处理
  - 3.4 __init__.py：导出三触发器类 + JobRegistry + ActiveScheduler
- [ ] **Step 4: Run test → PASS**

---

### Task 2: 向量数据库（Chroma 接入 + Mock 降级）

**Files:**
- Create: `aivyos_core/vector/__init__.py` / `base.py` / `chroma_store.py`
- Test: `tests/test_vector_store.py`（14 tests）

- [ ] **Step 1: Write failing tests**

```python
"""tests/test_vector_store.py - VectorStore base 协议 + MockInMemory + Chroma skipIf。"""
import unittest


class TestMockInMemoryVectorStore(unittest.TestCase):
    def _store(self):
        from aivyos_core.vector.base import MockInMemoryVectorStore
        return MockInMemoryVectorStore(dim=4)  # 4 维向量：测试用超小维度，mock embedder 返回随机

    def test_upsert_then_query_topk_returns_same(self):
        """upsert 3 docs → query "hello" top_k=2 返回 2 条，分数 desc。"""
        s = self._store()
        s.upsert_batch([
            {"id": "d1", "text": "hello world"},
            {"id": "d2", "text": "hello there"},
            {"id": "d3", "text": "bye bye"},
        ])
        res = s.query("hello", top_k=2)
        self.assertEqual(len(res), 2)
        # Mock 下 score 降序不保证，但必须 2 条且 id 在集合中
        ids = {r.id for r in res}
        self.assertTrue(ids.issubset({"d1", "d2", "d3"}))

    def test_delete_id_disappears(self):
        """delete(d1) → query 不再返回 d1。"""
        s = self._store()
        s.upsert_batch([{"id": "d1", "text": "a"}, {"id": "d2", "text": "b"}])
        s.delete("d1")
        res = s.query("a", top_k=10)
        self.assertTrue(all(r.id != "d1" for r in res))


class TestChromaStore(unittest.TestCase):
    def _store_or_skip(self):
        try:
            from aivyos_core.vector.chroma_store import ChromaVectorStore
        except Exception as e:
            self.skipTest(f"Chroma 未装或导入失败: {e}")
        return ChromaVectorStore(collection_name="unittest_tmp", in_memory=True)

    def test_smoke_upsert_query_delete(self):
        """Chroma smoke：upsert→query→delete 三步不抛。"""
        s = self._store_or_skip()
        s.upsert_batch([{"id": "c1", "text": "测试 Chroma"}])
        r = s.query("测试", top_k=1)
        self.assertGreaterEqual(len(r), 0)
        s.delete("c1")
```

- [ ] **Step 2: FAIL（no module vector）** → **Step 3: Implement**
  - base.py 定义 VectorStore ABC（4 abstract methods + QueryResult dataclass + MockInMemoryVectorStore：用 numpy norm 余弦相似度，无 numpy 则用纯 Python math.sqrt 手写）
  - chroma_store.py：try import chromadb → except Exception: raise SkipRuntimeImportError（不是 SkipTest；让上层 try/except 自动回退 Mock）；Chroma client 两种 mode：`in_memory=True`（ephemeral）/ `persist_dir=str`（PersistentClient）
  - __init__.py：对外 `def get_default_vector_store(prefer_chroma=True):`（检测 Chroma 可用则 Chroma，否则 Mock）
- [ ] **Step 4: Run test → PASS（Mock 14/14；Chroma 依赖缺失时自动 skip，0 fail）**

---

### Task 3: 记忆连续性增强（mem0 合约对齐）

**Files:**
- Create: `aivyos_core/memory/mem0_adapter.py` / `memory_store.py` / `__init__.py`
- Modify: `aivyos_core/voice/session.py` 每个 turn 结束写 memory_store.add(user, assistant)
- Test: `tests/test_mem0_adapter.py` + 修复原 tests/test_mem0_contract.py（如存在）

- [ ] **Step 1: Write failing tests**
  - 从 `test_mem0_contract.py`（如果存在）复制 7 条合约测试：add → search → get → update → delete → history → dedup；每条断言 100% 不变
- [ ] **Step 2: FAIL（no module memory.mem0_adapter）**
- [ ] **Step 3: Implement**
  - mem0_adapter.py：接口 100% 对齐 mem0.Contract（add/search/get/update/delete/history）；未装 mem0 时 Mem0Adapter 内部 = MockInMemoryMemory = `List[dict]` + 向量相似度排序（复用 MockInMemoryVectorStore.query）
  - memory_store.py：CompositeMemory = ShortTermRing(maxlen=200) + LongTerm(Mem0Adapter)；对外 MemoryStore.add(role, text, user_id, thread_id)
- [ ] **Step 4: Run test_mem0_contract.py → 100% green（不装 mem0 全 Mock 过）**

---

### Task 4: 知识卡片系统（CRUD + 向量索引 + 前端 UI + API）

**Files:**
- Create: `aivyos_core/knowledge/__init__.py` / `cards.py`
- Modify: `aivyos_core/server_entry.py` 追加 2 路由；`shell/src/routes.tsx`；`shell/src/pages/KnowledgeCardsPage.tsx`（TSX 新建）
- Test: `tests/test_knowledge_cards.py`（12 tests Python 侧 + tsc 1 次前端类型）

- [ ] **Step 1: Write failing tests Python 侧**

```python
"""tests/test_knowledge_cards.py - CardManager CRUD + 搜索 + Tags。"""
import unittest


class TestCardManager(unittest.TestCase):
    def _mgr(self):
        from aivyos_core.knowledge.cards import CardManager, KnowledgeCard
        from aivyos_core.vector.base import MockInMemoryVectorStore
        return CardManager(vector_store=MockInMemoryVectorStore(dim=8))

    def test_create_card_has_id_and_created_at(self):
        """新建卡片：id 非空 + created_at 存在。"""
        m = self._mgr()
        c = m.create(title="React Hooks 速查", content="useMemo 纯函数用 memoize", tags=["react", "frontend"])
        self.assertTrue(len(c.id) > 0)
        self.assertIsNotNone(c.created_at)
        self.assertIn("react", c.tags)

    def test_search_by_tag_filter(self):
        """标签过滤：只返回含该 tag 的卡片。"""
        m = self._mgr()
        m.create(title="a", content="a", tags=["x"])
        m.create(title="b", content="b", tags=["y"])
        r = m.search("a", tags=["y"])
        for card in r:
            self.assertIn("y", card.tags)
```

- [ ] **Step 2: FAIL → Step 3: Implement Python（cards.py：KnowledgeCard dataclass + CardManager upsert/delete/search/tags/list_collections）**
- [ ] **Step 4: Python tests green → Step 5: 前端 TSX 新建 + routes.tsx 追加 `/knowledge` → Step 6: tsc --noEmit → exit 0**

---

## 验收门槛（全 4 功能交付必须满足）

| 检查项 | 命令 | 通过标准 |
|---|---|---|
| 4 组新增单测全绿 | `python -m unittest tests.test_scheduler tests.test_vector_store tests.test_mem0_adapter tests.test_knowledge_cards -v` | 合计 ≥ 58 tests；0 fail 0 error |
| 原有单测零回归 | `python -m unittest discover -s tests` | exit 0；Ran **原数 +58** ≥617 tests OK |
| 前端类型 | `cd shell ; npx tsc --noEmit` | exit 0 |
| 可选依赖优雅降级 | `python -c "from aivyos_core.scheduler import ActiveScheduler; from aivyos_core.vector import get_default_vector_store; from aivyos_core.memory.mem0_adapter import Mem0Adapter; from aivyos_core.knowledge.cards import CardManager; print('DEGRADE_OK')"` | 打印 DEGRADE_OK（无 chromadb/mem0/schedule 时 Mock 自动启用） |
| 说明文档.md 写入 | 手动查看 §1.4 / §2.6 / §三进度表 | 7 条目 / 完整 4 Task 实施证据链 / 进度表 4 行 100% 落地标记 |
