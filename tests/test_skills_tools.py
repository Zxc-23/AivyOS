"""技能（Skills）与工具（Tools）管理测试。"""

import asyncio
import os
import shutil
import unittest

from tests import AivyTestCase, make_config


class TestSkills(AivyTestCase):
    def _build_server(self):
        from aivyos_core.chat.engine import ChatEngine
        from aivyos_core.server_entry import build_server

        cfg = make_config()
        cfg["ipc"]["port"] = 0
        # 独立技能文件（避免污染其他测试）
        import uuid
        home = os.path.join(os.getcwd(), ".aivyos_test", "skills_" + uuid.uuid4().hex[:8])
        os.makedirs(home, exist_ok=True)
        cfg["home"] = home
        engine = ChatEngine(cfg)
        server = build_server(engine, cfg)
        return server, engine

    def test_skills_list_has_builtins(self):
        """skills.list：首次运行生成内置技能。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.list"]({}))
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["skills"]), 8)  # 8 个内置技能
        names = {s["name"] for s in result["skills"]}
        self.assertIn("邮件处理", names)
        self.assertIn("周报生成", names)
        self.assertIn("看图理解", names)

    def test_skills_crud(self):
        """skills.create/update/delete 完整生命周期。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        created = asyncio.run(handlers["skills.create"]({
            "name": "会议纪要",
            "description": "整理会议要点",
            "category": "办公",
            "keywords": ["会议", "纪要"],
            "system_prompt": "你是会议纪要助手。",
            "enabled": True,
        }))
        self.assertTrue(created["ok"])
        sid = created["skill"]["id"]

        # 更新
        updated = asyncio.run(handlers["skills.update"]({
            "id": sid,
            "changes": {"enabled": False, "description": "整理会议要点与行动项"},
        }))
        self.assertTrue(updated["ok"])
        self.assertFalse(updated["skill"]["enabled"])
        self.assertIn("行动项", updated["skill"]["description"])

        # 列表可见
        listed = asyncio.run(handlers["skills.list"]({}))
        self.assertTrue(any(s["id"] == sid for s in listed["skills"]))

        # 删除
        deleted = asyncio.run(handlers["skills.delete"]({"id": sid}))
        self.assertTrue(deleted["ok"])
        listed2 = asyncio.run(handlers["skills.list"]({}))
        self.assertFalse(any(s["id"] == sid for s in listed2["skills"]))

    def test_skills_set_enabled(self):
        """skills.set-enabled：启停技能。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        listed = asyncio.run(handlers["skills.list"]({}))
        sid = listed["skills"][0]["id"]
        result = asyncio.run(handlers["skills.set-enabled"]({"id": sid, "enabled": False}))
        self.assertTrue(result["ok"])
        self.assertFalse(result["skill"]["enabled"])

    def test_skill_match_and_context(self):
        """技能匹配：命中触发词返回技能，context_blocks 生成提示词块。"""
        from aivyos_core.skills import SkillManager

        import uuid
        path = os.path.join(os.getcwd(), ".aivyos_test", "skillmatch_" + uuid.uuid4().hex[:8] + ".json")
        mgr = SkillManager(path)
        hits = mgr.match("帮我起草一封回复邮件")
        self.assertTrue(any(s["name"] == "邮件处理" for s in hits))
        blocks = mgr.context_blocks("帮我处理邮件")
        self.assertTrue(any("技能[邮件处理]" in b for b in blocks))
        os.remove(path)

    def test_chat_send_returns_skills(self):
        """chat.send：命中技能时返回 skills 字段。"""
        from aivyos_core.server_entry import build_server

        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["chat.send"]({"text": "帮我处理一下邮件", "session_id": None}))
        self.assertTrue(result["text"])
        self.assertTrue(any("邮件" in s for s in result.get("skills", [])))


class TestTools(AivyTestCase):
    def _build_server(self):
        from aivyos_core.chat.engine import ChatEngine
        from aivyos_core.server_entry import build_server

        cfg = make_config()
        cfg["ipc"]["port"] = 0
        import uuid
        home = os.path.join(os.getcwd(), ".aivyos_test", "tools_" + uuid.uuid4().hex[:8])
        os.makedirs(home, exist_ok=True)
        cfg["home"] = home
        engine = ChatEngine(cfg)
        server = build_server(engine, cfg)
        return server, engine

    def test_tools_list(self):
        """tools.list：列出已注册 MCP 工具（含权限/服务器/启停）。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["tools.list"]({}))
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["count"], 1)
        for t in result["tools"]:
            self.assertIn("name", t)
            self.assertIn("permission", t)
            self.assertIn("enabled", t)
            self.assertTrue(t["enabled"])  # 默认全启用

    def test_tools_set_enabled_persists(self):
        """tools.set-enabled：启停工具并持久化。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        listed = asyncio.run(handlers["tools.list"]({}))
        name = listed["tools"][0]["name"]
        result = asyncio.run(handlers["tools.set-enabled"]({"name": name, "enabled": False}))
        self.assertTrue(result["ok"])
        self.assertFalse(result["enabled"])
        # 重新列出 → 状态保持
        listed2 = asyncio.run(handlers["tools.list"]({}))
        tool = next(t for t in listed2["tools"] if t["name"] == name)
        self.assertFalse(tool["enabled"])


if __name__ == "__main__":
    unittest.main()
