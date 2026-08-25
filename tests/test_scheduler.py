"""主动调度器测试（AIVY-FEAT-CORE-001 Core-F1）：Cron/事件/条件 三触发。"""

import asyncio
import time
import unittest
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from tests import AivyTestCase


class TestCronTrigger(AivyTestCase):
    """CronTrigger 测试（3 tests）。"""

    def test_every_minute_next_fire_within_62s(self):
        """* * * * *：下一次触发应在 62 秒内（下一分钟整点）。"""
        from aivyos_core.scheduler.triggers import CronTrigger

        after = datetime(2026, 8, 25, 10, 30, 45)
        t = CronTrigger("* * * * *")
        nxt = t.next_fire_at(after)
        expected = datetime(2026, 8, 25, 10, 31, 0)
        self.assertEqual(nxt, expected)
        self.assertLessEqual((nxt - after).total_seconds(), 62.0)

    def test_daily_9am_future(self):
        """N H * * *：今天 9:00 还未到 → 今天 9:00；若已过 → 明天 9:00。"""
        from aivyos_core.scheduler.triggers import CronTrigger

        t = CronTrigger("0 9 * * *")
        after_future = datetime(2026, 8, 25, 8, 30, 0)
        self.assertEqual(t.next_fire_at(after_future), datetime(2026, 8, 25, 9, 0, 0))
        after_past = datetime(2026, 8, 25, 10, 0, 0)
        self.assertEqual(t.next_fire_at(after_past), datetime(2026, 8, 26, 9, 0, 0))

    def test_invalid_spec_raises_NotImplementedError(self):
        """其他复杂 cron spec 抛 NotImplementedError。"""
        from aivyos_core.scheduler.triggers import CronTrigger

        with self.assertRaises(NotImplementedError):
            CronTrigger("*/15 * * * *").next_fire_at(datetime.now())
        with self.assertRaises(NotImplementedError):
            CronTrigger("0 9 * * 1-5").next_fire_at(datetime.now())


class TestEventTrigger(AivyTestCase):
    """EventTrigger 测试（4 tests）。"""

    def test_match_same_name_true(self):
        """同名事件 → match 返回 True。"""
        from aivyos_core.scheduler.triggers import EventTrigger

        t = EventTrigger("user_joined")
        self.assertTrue(t.match("user_joined", {"uid": 1}))

    def test_mismatch_name_false(self):
        """异名事件 → match 返回 False。"""
        from aivyos_core.scheduler.triggers import EventTrigger

        t = EventTrigger("user_joined")
        self.assertFalse(t.match("user_left", {"uid": 1}))

    def test_fire_event_invokes_1_listener(self):
        """fire_event 后 1 个 listener 被调用且收到 payload。"""
        from aivyos_core.scheduler.runner import ActiveScheduler

        async def scenario():
            sched = ActiveScheduler()
            received = []

            async def listener(payload):
                received.append(payload)

            await sched.start()
            sched.add_event_listener("chat_msg", listener)
            await asyncio.sleep(0.01)
            sched.fire_event("chat_msg", {"text": "hi"})
            await asyncio.sleep(0.1)
            await sched.stop()
            return received

        received = asyncio.run(scenario())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["text"], "hi")

    def test_fire_event_invokes_2_listeners_both_called_count_1(self):
        """fire_event 后 2 个 listener 各被调用 1 次。"""
        from aivyos_core.scheduler.runner import ActiveScheduler

        async def scenario():
            sched = ActiveScheduler()
            calls_a = []
            calls_b = []

            async def listener_a(payload):
                calls_a.append(1)

            async def listener_b(payload):
                calls_b.append(1)

            await sched.start()
            sched.add_event_listener("chat_msg", listener_a)
            sched.add_event_listener("chat_msg", listener_b)
            await asyncio.sleep(0.01)
            sched.fire_event("chat_msg", {"text": "hi"})
            await asyncio.sleep(0.1)
            await sched.stop()
            return sum(calls_a), sum(calls_b)

        a, b = asyncio.run(scenario())
        self.assertEqual(a, 1)
        self.assertEqual(b, 1)


class TestConditionTrigger(AivyTestCase):
    """ConditionTrigger 测试（4 tests）。"""

    def test_eval_true_once_true(self):
        """表达式首次为 True → 返回 True。"""
        from aivyos_core.scheduler.triggers import ConditionTrigger

        t = ConditionTrigger("ctx['value'] > 5", cooldown_seconds=60.0)
        self.assertTrue(t.evaluate({"value": 10}))

    def test_cooldown_within_60s_false(self):
        """冷却期内（<60s）再次 True → 返回 False。"""
        from aivyos_core.scheduler.triggers import ConditionTrigger

        t = ConditionTrigger("ctx['value'] > 5", cooldown_seconds=60.0)
        t.evaluate({"value": 10})
        self.assertFalse(t.evaluate({"value": 10}))

    def test_cooldown_after_61s_true_again(self):
        """冷却后（≥61s）再次 True → 返回 True。"""
        from aivyos_core.scheduler.triggers import ConditionTrigger

        t = ConditionTrigger("ctx['value'] > 5", cooldown_seconds=0.05)
        self.assertTrue(t.evaluate({"value": 10}))
        self.assertFalse(t.evaluate({"value": 10}))
        time.sleep(0.06)
        self.assertTrue(t.evaluate({"value": 10}))

    def test_eval_false_never_fires(self):
        """表达式一直为 False → 永不触发。"""
        from aivyos_core.scheduler.triggers import ConditionTrigger

        t = ConditionTrigger("ctx['value'] > 100", cooldown_seconds=0.0)
        for _ in range(5):
            self.assertFalse(t.evaluate({"value": 10}))


class TestRegistry(AivyTestCase):
    """JobRegistry 测试（3 tests）。"""

    def test_register_get_roundtrip(self):
        """register → get 往返一致。"""
        from aivyos_core.scheduler.registry import JobRegistry
        from aivyos_core.scheduler.triggers import EventTrigger

        reg = JobRegistry()

        async def my_fn(x):
            return x

        trigger = EventTrigger("ev")
        reg.register("job_1", trigger, my_fn, args=(42,))
        job = reg.get("job_1")
        self.assertIsNotNone(job)
        self.assertEqual(job["job_id"], "job_1")
        self.assertIs(job["trigger"], trigger)
        self.assertEqual(job["args"], (42,))

    def test_unregister_then_None(self):
        """unregister → get 返回 None。"""
        from aivyos_core.scheduler.registry import JobRegistry
        from aivyos_core.scheduler.triggers import EventTrigger

        reg = JobRegistry()

        async def my_fn():
            pass

        reg.register("job_2", EventTrigger("ev"), my_fn)
        self.assertIsNotNone(reg.get("job_2"))
        reg.unregister("job_2")
        self.assertIsNone(reg.get("job_2"))

    def test_list_returns_all(self):
        """list 返回全部注册任务。"""
        from aivyos_core.scheduler.registry import JobRegistry
        from aivyos_core.scheduler.triggers import EventTrigger

        reg = JobRegistry()

        async def fn_a():
            pass

        async def fn_b():
            pass

        reg.register("a", EventTrigger("ea"), fn_a)
        reg.register("b", EventTrigger("eb"), fn_b)
        jobs = reg.list()
        self.assertEqual(len(jobs), 2)
        ids = {j["job_id"] for j in jobs}
        self.assertEqual(ids, {"a", "b"})


class TestActiveScheduler(AivyTestCase):
    """ActiveScheduler 测试（4 tests）。"""

    def test_start_stop_no_leak_task(self):
        """start → stop 后无残留 task。"""
        from aivyos_core.scheduler.runner import ActiveScheduler

        async def scenario():
            sched = ActiveScheduler()
            self.assertIsNone(sched._task)
            await sched.start()
            self.assertIsNotNone(sched._task)
            self.assertFalse(sched._task.done())
            await sched.stop()
            self.assertTrue(sched._task.done() or sched._task.cancelled())
            return True

        self.assertTrue(asyncio.run(scenario()))

    def test_fire_event_after_start_receives_payload(self):
        """start 后 fire_event → 关联 job 的 coro_fn 收到 payload。"""
        from aivyos_core.scheduler.registry import JobRegistry
        from aivyos_core.scheduler.runner import ActiveScheduler
        from aivyos_core.scheduler.triggers import EventTrigger

        async def scenario():
            sched = ActiveScheduler()
            fired = []

            async def job_fn(payload=None):
                fired.append(payload)

            await sched.start()
            sched._registry.register(
                "ev_job",
                EventTrigger("my_ev"),
                job_fn,
                args=(),
            )
            await asyncio.sleep(0.01)
            sched.fire_event("my_ev", {"k": "v"})
            await asyncio.sleep(0.15)
            await sched.stop()
            return fired

        fired = asyncio.run(scenario())
        self.assertGreaterEqual(len(fired), 1)
        self.assertEqual(fired[0]["k"], "v")

    def test_scheduler_runs_3_condition_triggers_in_2s(self):
        """2s 内 3 个条件触发各自至少触发 1 次。"""
        from aivyos_core.scheduler.runner import ActiveScheduler
        from aivyos_core.scheduler.triggers import ConditionTrigger

        async def scenario():
            sched = ActiveScheduler()
            counters = {"c1": 0, "c2": 0, "c3": 0}

            async def fn_c1():
                counters["c1"] += 1

            async def fn_c2():
                counters["c2"] += 1

            async def fn_c3():
                counters["c3"] += 1

            sched._registry.register("c1", ConditionTrigger("ctx['c1']", cooldown_seconds=0.05), fn_c1)
            sched._registry.register("c2", ConditionTrigger("ctx['c2']", cooldown_seconds=0.05), fn_c2)
            sched._registry.register("c3", ConditionTrigger("ctx['c3']", cooldown_seconds=0.05), fn_c3)
            ctx = {"c1": True, "c2": True, "c3": True}
            await sched.start()
            end = time.time() + 1.5
            while time.time() < end:
                sched.evaluate_conditions(ctx)
                await asyncio.sleep(0.05)
            await sched.stop()
            return counters

        counters = asyncio.run(scenario())
        self.assertGreaterEqual(counters["c1"], 1)
        self.assertGreaterEqual(counters["c2"], 1)
        self.assertGreaterEqual(counters["c3"], 1)

    def test_cron_trigger_invokes_job_within_62s(self):
        """CronTrigger 注册后 62s 内 job 被调用（* * * * * 场景）。"""
        from aivyos_core.scheduler.runner import ActiveScheduler
        from aivyos_core.scheduler.triggers import CronTrigger

        async def scenario():
            sched = ActiveScheduler()
            fired_ts = []

            async def cron_job():
                fired_ts.append(time.time())

            sched._registry.register("cron1", CronTrigger("* * * * *"), cron_job)
            start_ts = time.time()
            await sched.start()
            deadline = start_ts + 65.0
            while time.time() < deadline and not fired_ts:
                await asyncio.sleep(0.2)
            await sched.stop()
            return fired_ts, start_ts

        fired_ts, start_ts = asyncio.run(scenario())
        self.assertGreaterEqual(len(fired_ts), 1)
        self.assertLessEqual(fired_ts[0] - start_ts, 62.0)


if __name__ == "__main__":
    unittest.main()
