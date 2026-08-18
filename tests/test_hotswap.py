"""热交换与热启动测试（Phase 3 Week 11）：
读写锁并发/写独占 / SafeModuleProxy 热交换 / Drain 八阶段 / 熔断状态机 / 快照原子性 / 健康检查回滚 / 快速启动。"""

import asyncio
import json
import os
import shutil
import sys
import threading
import time
import types
import unittest
from pathlib import Path

from aivyos_core.hotswap import (
    DEFAULT_CHECKS,
    DrainManager,
    FastBoot,
    HealthChecker,
    HotSwapCircuitBreaker,
    ModuleRWLock,
    SafeModuleProxy,
    StateSnapshot,
)

from tests import AivyTestCase, _TMP


# ---- 测试用模块（可注入 reload_fn）----

def make_test_module(schema_version=1, greeting="v1"):
    """构建带状态协议的测试模块对象（非 sys.modules 注册，靠 reload_fn 注入）。"""
    mod = types.ModuleType("hotswap_test_mod")
    mod._STATE_SCHEMA_VERSION__ = schema_version
    mod._PERSISTENT_STATE__ = ["counter", "config"]
    mod.counter = 0
    mod.config = {"max_context_length": 1024}
    mod.greeting = greeting

    def ping(name="x"):
        mod.counter += 1
        return f"{mod.greeting}:{name}"

    async def aping(name="x"):
        mod.counter += 1
        return f"{mod.greeting}:{name}"

    mod.ping = ping
    mod.aping = aping
    return mod


class TestModuleRWLock(AivyTestCase):
    def test_concurrent_reads(self):
        lock = ModuleRWLock()
        lock.acquire_read()
        lock.acquire_read()  # 读可并发
        self.assertEqual(lock.reader_count, 2)
        self.assertEqual(lock.active_count, 2)
        lock.release_read()
        lock.release_read()
        self.assertEqual(lock.reader_count, 0)

    def test_write_exclusive_waits_for_readers(self):
        lock = ModuleRWLock()
        lock.acquire_read()
        result = {"done": False}

        def writer():
            try:
                lock.acquire_write(timeout=2.0)
                result["done"] = True
                lock.release_write()
            except TimeoutError:
                result["done"] = False

        t = threading.Thread(target=writer)
        t.start()
        time.sleep(0.1)
        self.assertFalse(result["done"])  # 读锁未释放，写者阻塞
        lock.release_read()  # 读者离开 → 写者获得
        t.join(timeout=3)
        self.assertTrue(result["done"])

    def test_write_timeout_raises(self):
        lock = ModuleRWLock()
        lock.acquire_read()
        with self.assertRaises(TimeoutError):
            lock.acquire_write(timeout=0.1)
        lock.release_read()

    def test_new_readers_blocked_during_write(self):
        lock = ModuleRWLock()
        lock.acquire_write()
        blocked = {"acquired": False}

        def reader():
            lock.acquire_read()
            blocked["acquired"] = True
            lock.release_read()

        t = threading.Thread(target=reader)
        t.start()
        time.sleep(0.1)
        self.assertFalse(blocked["acquired"])  # 写锁独占期间读者排队
        lock.release_write()
        t.join(timeout=3)
        self.assertTrue(blocked["acquired"])


class TestSafeModuleProxy(AivyTestCase):
    def test_call_and_state_persistence(self):
        mod = make_test_module(greeting="v1")
        proxy = SafeModuleProxy("placeholder", module=mod)
        self.assertEqual(proxy.call("ping", "a"), "v1:a")
        self.assertEqual(mod.counter, 1)

    def test_hot_swap_switches_pointer_and_migrates(self):
        old_mod = make_test_module(schema_version=1, greeting="v1")
        old_mod.counter = 7
        new_mod = make_test_module(schema_version=2, greeting="v2")

        proxy = SafeModuleProxy("placeholder", module=old_mod)
        # 注入 reload_fn：返回新模块（模拟 importlib.reload 成功）
        ok = proxy.hot_swap(timeout=5, reload_fn=lambda m: new_mod)
        self.assertTrue(ok)
        self.assertIs(proxy.module, new_mod)
        # 状态已迁移：counter 跨版本保持
        self.assertEqual(new_mod.counter, 7)
        self.assertEqual(proxy.call("ping", "b"), "v2:b")

    def test_hot_swap_failure_keeps_old(self):
        old_mod = make_test_module(greeting="v1")
        proxy = SafeModuleProxy("placeholder", module=old_mod)

        def boom(m):
            raise ImportError("模拟 import 失败（C5）")

        ok = proxy.hot_swap(timeout=5, reload_fn=boom)
        self.assertFalse(ok)
        self.assertIs(proxy.module, old_mod)  # 指针未切换，旧模块继续服务

    def test_migrate_state_with_migration_fn(self):
        """C2：版本化迁移（§2.4：v1 → v2 结构变更）。"""
        old_mod = make_test_module(schema_version=1)
        old_mod.buffer = [1, 2, 3]
        old_mod._PERSISTENT_STATE__ = ["counter", "config", "buffer"]  # 旧模块声明持久属性
        new_mod = make_test_module(schema_version=2)

        def migrate(old_state, from_version="auto"):
            # v1 → v2: buffer list → dict
            buf = old_state.get("buffer", [])
            old_state["buffer"] = {"messages": buf, "metadata": {"truncated": False}}
            old_state["_state_schema_version__"] = 2
            return old_state

        new_mod._migrate_state_ = migrate
        new_mod._PERSISTENT_STATE__ = ["counter", "config", "buffer"]
        proxy = SafeModuleProxy("placeholder", module=old_mod)
        proxy.hot_swap(timeout=5, reload_fn=lambda m: new_mod)
        self.assertEqual(new_mod.buffer, {"messages": [1, 2, 3], "metadata": {"truncated": False}})


class TestDrainManager(AivyTestCase):
    def test_full_hot_swap_with_health(self):
        old_mod = make_test_module(greeting="v1")
        new_mod = make_test_module(greeting="v2")
        proxy = SafeModuleProxy("placeholder", module=old_mod)

        async def health(m):
            return {"healthy": True}

        drain = DrainManager(proxy, drain_timeout=1.0, health_check=health)
        result = asyncio.run(drain.execute_hot_swap(reload_fn=lambda m: new_mod))
        self.assertTrue(result["success"])
        self.assertEqual(result["released"], 0)
        self.assertIs(proxy.module, new_mod)

    def test_health_failure_rolls_back(self):
        """C6：健康检查失败 → 回滚旧模块。"""
        old_mod = make_test_module(greeting="v1")
        new_mod = make_test_module(greeting="v2")
        proxy = SafeModuleProxy("placeholder", module=old_mod)

        async def health(m):
            return {"healthy": False, "failed": "llm"}

        drain = DrainManager(proxy, health_check=health)
        result = asyncio.run(drain.execute_hot_swap(reload_fn=lambda m: new_mod))
        self.assertFalse(result["success"])
        self.assertTrue(result["rolled_back"])
        self.assertIs(proxy.module, old_mod)  # 指针已回滚

    def test_reload_failure_keeps_old(self):
        """C5：import 失败 → 回滚（指针未切换）。"""
        proxy = SafeModuleProxy("placeholder", module=make_test_module())

        def boom(m):
            raise ImportError("reload 失败")

        drain = DrainManager(proxy)
        result = asyncio.run(drain.execute_hot_swap(reload_fn=boom))
        self.assertFalse(result["success"])
        self.assertIn("reload_failed", result)

    def test_queue_request_released_after_swap(self):
        old_mod = make_test_module(greeting="v1")
        new_mod = make_test_module(greeting="v2")
        proxy = SafeModuleProxy("placeholder", module=old_mod)

        async def health(m):
            return {"healthy": True}

        drain = DrainManager(proxy, health_check=health)
        item = drain.queue_request("aping", ("queued",))
        result = asyncio.run(drain.execute_hot_swap(reload_fn=lambda m: new_mod))
        self.assertTrue(result["success"])
        self.assertEqual(result["released"], 1)
        out = asyncio.run(drain.execute_queued(item))
        self.assertEqual(out, "v2:queued")  # 排队请求转入新模块（D8）


class TestCircuitBreaker(AivyTestCase):
    def test_closed_allows_attempts(self):
        cb = HotSwapCircuitBreaker(failure_threshold=3)
        self.assertTrue(cb.can_attempt())
        cb.record_success()
        self.assertEqual(cb.state, "closed")

    def test_open_after_threshold(self):
        cb = HotSwapCircuitBreaker(failure_threshold=3, cooldown=10)
        for _ in range(2):
            cb.record_failure()
            self.assertTrue(cb.can_attempt())
        cb.record_failure()  # 第 3 次 → open
        self.assertEqual(cb.state, "open")
        self.assertFalse(cb.can_attempt())  # 冷却期内拒绝

    def test_half_open_after_cooldown(self):
        cb = HotSwapCircuitBreaker(failure_threshold=1, cooldown=0.05)
        cb.record_failure()
        self.assertEqual(cb.state, "open")
        time.sleep(0.1)  # 冷却结束
        self.assertTrue(cb.can_attempt())  # half_open 允许一次试探
        self.assertEqual(cb.state, "half_open")
        cb.record_success()
        self.assertEqual(cb.state, "closed")

    def test_degrade_notified(self):
        degraded = []
        cb = HotSwapCircuitBreaker(failure_threshold=1, cooldown=3600, on_degrade=lambda mode: degraded.append(mode))
        cb.record_failure()
        self.assertEqual(degraded, ["cold_install"])  # §2.6 降级冷启动安装


class TestStateSnapshot(AivyTestCase):
    def setUp(self):
        self.dir = Path(_TMP) / ("snap_" + os.urandom(3).hex())
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_snapshot_restore_atomic(self):
        snap = StateSnapshot(self.dir, version="1.3.0")
        snap.register("session", lambda: {"messages": ["hi"]})
        snap.register("scheduler", lambda: {"jobs": [1, 2]})
        data = snap.snapshot()
        self.assertEqual(data["version"], "1.3.0")
        restored = snap.restore()
        self.assertEqual(restored["state"]["session"], {"messages": ["hi"]})
        self.assertEqual(restored["state"]["scheduler"], {"jobs": [1, 2]})
        # 无残留 tmp 文件（原子写入）
        self.assertNotIn("latest.tmp", os.listdir(self.dir))

    def test_restore_missing_returns_none(self):
        snap = StateSnapshot(self.dir)
        self.assertIsNone(snap.restore("nope"))


class TestHealthChecker(AivyTestCase):
    def test_all_pass(self):
        hc = HealthChecker()
        hc.register("llm", lambda: True, timeout=1)
        hc.register("memory", lambda: True, timeout=1)
        r = asyncio.run(hc.verify())
        self.assertTrue(r["healthy"])

    def test_failure_reports_failed(self):
        hc = HealthChecker()
        hc.register("llm", lambda: True, timeout=1)
        hc.register("memory", lambda: False, timeout=1)
        r = asyncio.run(hc.verify())
        self.assertFalse(r["healthy"])
        self.assertEqual(r["failed"], "memory")

    def test_timeout_reports(self):
        async def slow():
            await asyncio.sleep(2)

        hc = HealthChecker(timeouts={"x": 0.05})
        hc.register("x", slow)
        r = asyncio.run(hc.verify())
        self.assertFalse(r["healthy"])
        self.assertTrue(r.get("timeout"))

    def test_default_checks_keys(self):
        self.assertIn("llm", DEFAULT_CHECKS)
        self.assertIn("frontend", DEFAULT_CHECKS)


class TestFastBoot(AivyTestCase):
    def test_phased_boot_order_and_timings(self):
        order = []
        fb = FastBoot()
        fb.register("critical", lambda: order.append("critical"), phase=1)
        fb.register("background", lambda: order.append("background"), phase=2)
        fb.register("finish", lambda: order.append("finish"), phase=3)
        result = asyncio.run(fb.boot())
        self.assertEqual(order, ["critical", "background", "finish"])
        self.assertIn("phase1", result["timings"])
        self.assertIn("total", result["timings"])

    def test_restore_from_snapshot(self):
        snap = StateSnapshot(Path(_TMP) / ("snapb_" + os.urandom(3).hex()))
        snap.register("scheduler", lambda: {"jobs": ["t1"]})
        snap.snapshot()
        fb = FastBoot(snapshot=snap)
        fb.register("scheduler_restore", fb.restore_scheduler(), phase=1)
        result = asyncio.run(fb.boot())
        self.assertEqual(result["results"]["scheduler_restore"], {"jobs": ["t1"]})

    def test_step_failure_isolated(self):
        fb = FastBoot()
        fb.register("bad", lambda: 1 / 0, phase=1)
        fb.register("good", lambda: "ok", phase=1)
        result = asyncio.run(fb.boot())
        self.assertIn("error", result["results"]["bad"])  # 失败隔离，不阻断后续
        self.assertEqual(result["results"]["good"], "ok")


if __name__ == "__main__":
    unittest.main()
