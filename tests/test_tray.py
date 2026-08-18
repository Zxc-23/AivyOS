"""托盘模块测试（Phase 3 Week 9）：状态机 / 分级通知 / 文件路由。"""

import asyncio
import os
import shutil
import unittest

from aivyos_core.tray.file_router import route_file, route_files, supported_extensions
from aivyos_core.tray.notify import NOTIFY_LEVELS, TrayNotificationManager
from aivyos_core.tray.state_machine import TRAY_STATES, TrayStateMachine, TrayStateError

from tests import AivyTestCase, _TMP


class TestTrayStateMachine(AivyTestCase):
    def test_8_states(self):
        self.assertEqual(
            TRAY_STATES,
            ("idle", "listening", "working", "voice", "updating", "booting", "error", "paused"),
        )

    def test_boot_complete(self):
        m = TrayStateMachine(initial="booting")
        self.assertTrue(m.on("boot_complete"))
        self.assertEqual(m.state, "idle")

    def test_listen_cycle(self):
        m = TrayStateMachine(initial="idle")
        self.assertTrue(m.on("listening_start"))
        self.assertEqual(m.state, "listening")
        self.assertTrue(m.on("listening_stop"))
        self.assertEqual(m.state, "idle")

    def test_task_cycle(self):
        m = TrayStateMachine(initial="idle")
        self.assertTrue(m.on("task_start"))
        self.assertEqual(m.state, "working")
        self.assertTrue(m.on("task_done"))
        self.assertEqual(m.state, "idle")

    def test_voice_cycle(self):
        m = TrayStateMachine(initial="idle")
        self.assertTrue(m.on("voice_start"))
        self.assertEqual(m.state, "voice")
        self.assertTrue(m.on("voice_end"))
        self.assertEqual(m.state, "idle")

    def test_update_then_restart(self):
        m = TrayStateMachine(initial="idle")
        self.assertTrue(m.on("update_detected"))
        self.assertEqual(m.state, "updating")
        self.assertTrue(m.on("install_restart"))
        self.assertEqual(m.state, "booting")

    def test_pause_resume(self):
        m = TrayStateMachine(initial="listening")
        self.assertTrue(m.on("pause"))
        self.assertEqual(m.state, "paused")
        self.assertTrue(m.on("resume"))
        self.assertEqual(m.state, "idle")

    def test_error_from_any_state(self):
        for s in TRAY_STATES:
            if s == "error":
                continue  # 已在 error：无转换（同状态幂等）
            m = TrayStateMachine(initial=s)
            self.assertTrue(m.on("error"), s)
            self.assertEqual(m.state, "error")

    def test_retry_ok(self):
        m = TrayStateMachine(initial="error")
        self.assertTrue(m.on("retry_ok"))
        self.assertEqual(m.state, "idle")

    def test_illegal_transition_honest(self):
        m = TrayStateMachine(initial="idle")
        self.assertFalse(m.on("voice_end"))  # idle 下无 voice_end 转换
        self.assertEqual(m.state, "idle")    # 状态不变（不假成功）

    def test_unknown_event_raises(self):
        m = TrayStateMachine(initial="idle")
        with self.assertRaises(TrayStateError):
            m.on("no_such_event")

    def test_guard_booting_ignores_left_and_double_click(self):
        m = TrayStateMachine(initial="booting")
        self.assertFalse(m.allow_action("left_click"))   # §3.2 booting 忽略左键
        self.assertFalse(m.allow_action("double_click")) # §3.4 booting 忽略双击
        self.assertIsNone(m.left_click())

    def test_guard_updating_ignores_double_click(self):
        m = TrayStateMachine(initial="updating")
        self.assertFalse(m.allow_action("double_click"))
        self.assertTrue(m.allow_action("left_click"))

    def test_left_click_state_aware(self):
        m = TrayStateMachine(initial="idle")
        self.assertEqual(m.left_click(), "toggle")
        m.on("task_start")
        self.assertEqual(m.left_click(), "show-task")
        m.on("task_done")
        m.on("error")
        self.assertEqual(m.left_click(), "show-error")

    def test_listener_notified(self):
        events = []
        m = TrayStateMachine(initial="booting")
        m.add_listener(lambda old, new, ev: events.append((old, new, ev)))
        m.on("boot_complete")
        m.on("listening_start")
        self.assertEqual(events, [("booting", "idle", "boot_complete"), ("idle", "listening", "listening_start")])

    def test_visual_and_dict(self):
        m = TrayStateMachine(initial="idle")
        v = m.visual()
        self.assertIn("tooltip", v)
        self.assertIn("color", v)
        d = m.to_dict()
        self.assertEqual(d["state"], "idle")


class TestTrayNotification(AivyTestCase):
    def test_levels_defined(self):
        for lv in ("urgent", "important", "normal", "silent"):
            self.assertIn(lv, NOTIFY_LEVELS)
        self.assertTrue(NOTIFY_LEVELS["urgent"]["bypass_dnd"])
        self.assertFalse(NOTIFY_LEVELS["normal"]["bypass_dnd"])

    def test_normal_send_delivers(self):
        sent = []
        mgr = TrayNotificationManager(dnd=False, sender=lambda t, b, l, a: sent.append((t, b, l)))
        r = asyncio.run(mgr.send("标题", "内容", "normal"))
        self.assertFalse(r["queued"])
        self.assertEqual(sent, [("标题", "内容", "normal")])

    def test_dnd_queues_non_bypass(self):
        sent = []
        mgr = TrayNotificationManager(dnd=True, sender=lambda t, b, l, a: sent.append((t, b, l)))
        r = asyncio.run(mgr.send("普通", "排队", "normal"))
        self.assertTrue(r["queued"])
        self.assertEqual(mgr.pending_count(), 1)
        self.assertEqual(sent, [])  # 勿扰中未投递

    def test_urgent_bypasses_dnd(self):
        sent = []
        mgr = TrayNotificationManager(dnd=True, sender=lambda t, b, l, a: sent.append((t, b, l)))
        r = asyncio.run(mgr.send("紧急", "绕过勿扰", "urgent"))
        self.assertFalse(r["queued"])
        self.assertEqual(sent, [("紧急", "绕过勿扰", "urgent")])

    def test_flush_pending_after_dnd(self):
        sent = []
        mgr = TrayNotificationManager(dnd=True, sender=lambda t, b, l, a: sent.append((t, b, l)))
        asyncio.run(mgr.send("A", "a", "normal"))
        asyncio.run(mgr.send("B", "b", "important"))
        self.assertEqual(mgr.pending_count(), 2)
        mgr.set_dnd(False)  # 勿扰结束
        n = asyncio.run(mgr.flush_pending())
        self.assertEqual(n, 2)
        self.assertEqual(len(sent), 2)
        self.assertEqual(mgr.pending_count(), 0)

    def test_icon_flash_on_urgent(self):
        flashed = []
        mgr = TrayNotificationManager(
            dnd=True,
            icon_flash=lambda s: flashed.append(s),
            sender=lambda t, b, l, a: None,
        )
        asyncio.run(mgr.send("紧急", "x", "urgent"))
        self.assertEqual(flashed, ["error"])  # §3.6 urgent → 图标红闪


class TestFileRouter(AivyTestCase):
    def setUp(self):
        self.dir = os.path.join(_TMP, "tray_files")
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir)

    def _f(self, name, content=b"x"):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(content)
        return p

    def test_text_route(self):
        r = route_file(self._f("notes.txt"))
        self.assertEqual(r.analyzer, "text")
        d = r.to_dict()
        self.assertIn("action", d)
        self.assertEqual(d["name"], "notes.txt")

    def test_code_route(self):
        r = route_file(self._f("main.py"))
        self.assertEqual(r.analyzer, "code")

    def test_image_route(self):
        r = route_file(self._f("photo.png", b"\x89PNG\r\n\x1a\nxxxx"))
        self.assertEqual(r.analyzer, "image")

    def test_unknown_ext_magic_detect_pdf(self):
        r = route_file(self._f("noext", b"%PDF-1.4 fake"))
        self.assertEqual(r.analyzer, "document")  # 文件头推断

    def test_unknown_falls_back_other(self):
        r = route_file(self._f("weird.zzz"))
        self.assertEqual(r.analyzer, "other")

    def test_route_files_multi(self):
        rs = route_files([self._f("a.md"), self._f("b.csv")])
        analyzers = {r["analyzer"] for r in rs}
        self.assertEqual(analyzers, {"text", "sheet"})

    def test_supported_extensions(self):
        exts = supported_extensions()
        self.assertIn(".txt", exts)
        self.assertIn(".png", exts)


if __name__ == "__main__":
    unittest.main()
