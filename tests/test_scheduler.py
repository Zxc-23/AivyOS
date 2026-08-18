"""主动调度器测试（§5.3 / T3.10）：cron 解析 / 事件 / 条件。"""

import asyncio
import unittest
from datetime import datetime

from aivyos_core.scheduler import CronError, CronSchedule, Scheduler

from tests import AivyTestCase


class TestCronSchedule(AivyTestCase):
    def test_parse_and_match(self):
        from datetime import timedelta

        def next_weekday(d, target=0):  # target 0=周一
            return d + timedelta(days=(target - d.weekday()) % 7)

        c = CronSchedule("0 9 * * 1-5")  # 工作日 9:00
        mon = next_weekday(datetime(2026, 8, 1))
        self.assertTrue(c.matches(mon.replace(hour=9, minute=0)))  # 周一 9:00
        self.assertFalse(c.matches(mon.replace(hour=9, minute=1)))
        sunday = mon + timedelta(days=6)
        self.assertFalse(c.matches(sunday.replace(hour=9, minute=0)))  # 周日

    def test_every_minute(self):
        c = CronSchedule("* * * * *")
        self.assertTrue(c.matches(datetime(2026, 1, 1, 0, 0)))
        self.assertTrue(c.matches(datetime(2026, 12, 31, 23, 59)))

    def test_step_and_range(self):
        c = CronSchedule("*/15 * 1-5 * *")
        self.assertTrue(c.matches(datetime(2026, 8, 3, 10, 15)))
        self.assertTrue(c.matches(datetime(2026, 8, 3, 10, 30)))
        self.assertFalse(c.matches(datetime(2026, 8, 6, 10, 15)))  # 日 6 超出 1-5

    def test_next_run(self):
        c = CronSchedule("0 9 * * *")
        after = datetime(2026, 8, 17, 8, 30)
        nxt = c.next_run(after)
        self.assertEqual(nxt, datetime(2026, 8, 17, 9, 0))

    def test_invalid_field(self):
        with self.assertRaises(CronError):
            CronSchedule("99 * * * *")

    def test_invalid_parts(self):
        with self.assertRaises(CronError):
            CronSchedule("0 9 * *")


class TestScheduler(AivyTestCase):
    def test_event_job(self):
        async def scenario():
            sched = Scheduler(tick_s=0.05)
            ev = asyncio.Event()
            fired = []

            @sched.on_event("测试事件", ev)
            async def job():
                fired.append("run")

            # 手动模拟主循环一次（不启动无限循环）
            ev.set()
            for job in sched.jobs:
                if job.event and job.event.is_set():
                    job.event.clear()
                    await sched._run_job(job)
            self.assertEqual(fired, ["run"])
            self.assertEqual(sched.status()[0]["runs"], 1)

        asyncio.run(scenario())

    def test_condition_job(self):
        async def scenario():
            sched = Scheduler(tick_s=0.05)
            flag = {"ok": False}
            fired = []

            @sched.on_condition("条件任务", lambda: flag["ok"], interval_s=0.05)
            async def job():
                fired.append("run")

            flag["ok"] = True
            for job in sched.jobs:
                if job.condition and job.condition():
                    await sched._run_job(job)
            self.assertEqual(fired, ["run"])

        asyncio.run(scenario())

    def test_job_error_captured(self):
        async def scenario():
            sched = Scheduler()
            ev = asyncio.Event()

            @sched.on_event("坏任务", ev)
            async def bad():
                raise ValueError("boom")

            ev.set()
            for job in sched.jobs:
                if job.event and job.event.is_set():
                    job.event.clear()
                    await sched._run_job(job)
            self.assertIn("boom", sched.status()[0]["error"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
