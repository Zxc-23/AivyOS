"""认证状态机测试（§9.1 / T6.6：转移 + 静默拒绝 + 自动重置）。"""

import asyncio
import unittest

from aivyos_core.auth.state_machine import AuthState, AuthStateMachine

from tests import AivyTestCase


class TestAuthStateMachine(AivyTestCase):
    def test_happy_path(self):
        sm = AuthStateMachine()
        self.assertEqual(sm.state, AuthState.DORMANT)
        sm.wake()
        self.assertEqual(sm.state, AuthState.LISTENING)
        sm.start_verify()
        self.assertEqual(sm.state, AuthState.VERIFYING)
        sm.accept("user_1", 0.85)
        self.assertEqual(sm.state, AuthState.AUTHENTICATED)
        self.assertTrue(sm.is_authenticated())
        self.assertEqual(sm.current_user, "user_1")
        sm.logout()
        self.assertEqual(sm.state, AuthState.DORMANT)

    def test_reject_then_silent_reset(self):
        async def scenario():
            sm = AuthStateMachine(silent_reject=True, reject_timeout_s=0.2)
            sm.wake()
            sm.start_verify()
            sm.reject(score=0.3)
            self.assertEqual(sm.state, AuthState.REJECTED)
            # 静默重置：超时后回到 dormant（不暴露系统存在）
            await asyncio.sleep(0.4)
            self.assertEqual(sm.state, AuthState.DORMANT)
            self.assertIn("silent_reset", [e.action for e in sm.events])

        asyncio.run(scenario())

    def test_reject_not_silent_keeps_state(self):
        async def scenario():
            sm = AuthStateMachine(silent_reject=False)
            sm.wake()
            sm.start_verify()
            sm.reject()
            self.assertEqual(sm.state, AuthState.REJECTED)
            await asyncio.sleep(0.2)
            self.assertEqual(sm.state, AuthState.REJECTED)  # 未启用静默 → 不自动重置

        asyncio.run(scenario())

    def test_transition_guards(self):
        sm = AuthStateMachine()
        # 未监听时不能 start_verify
        sm.start_verify()
        self.assertEqual(sm.state, AuthState.DORMANT)
        # 未验证时 accept 无效
        sm.accept("x", 0.9)
        self.assertEqual(sm.state, AuthState.DORMANT)

    def test_events_logged(self):
        sm = AuthStateMachine()
        sm.wake()
        sm.start_verify()
        sm.accept("u", 0.8)
        actions = [e.action for e in sm.events]
        self.assertIn("wake", actions)
        self.assertIn("accept", actions)


if __name__ == "__main__":
    unittest.main()
