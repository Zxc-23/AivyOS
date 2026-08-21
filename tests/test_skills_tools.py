"""技能（Skills）与工具（Tools）管理测试。"""

import asyncio
import os
import shutil
import unittest
import urllib.request
from unittest.mock import MagicMock, patch

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


class TestSkillMarketplace(AivyTestCase):
    def _build_server(self):
        from aivyos_core.chat.engine import ChatEngine
        from aivyos_core.server_entry import build_server

        cfg = make_config()
        cfg["ipc"]["port"] = 0
        import uuid
        home = os.path.join(os.getcwd(), ".aivyos_test", "mkt_" + uuid.uuid4().hex[:8])
        os.makedirs(home, exist_ok=True)
        cfg["home"] = home
        engine = ChatEngine(cfg)
        server = build_server(engine, cfg)
        return server, engine

    def test_market_list(self):
        """skills.market-list：返回市场技能并标注已安装。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-list"]({}))
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["count"], 10)
        names = {s["name"] for s in result["skills"]}
        self.assertIn("会议纪要", names)
        self.assertIn("简历优化", names)
        for s in result["skills"]:
            self.assertIn("installed", s)
            self.assertFalse(s["installed"])  # 初始未安装

    def test_market_sources(self):
        """skills.market-sources：返回内置 + 远程平台列表。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-sources"]({}))
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["count"], 5)
        ids = {s["id"] for s in result["sources"]}
        self.assertIn("builtin", ids)
        self.assertIn("agentskillexchange", ids)
        self.assertIn("dukelyuu", ids)
        builtin = next(s for s in result["sources"] if s["id"] == "builtin")
        self.assertGreaterEqual(builtin["skill_count"], 20)

    def test_market_browse_builtin(self):
        """skills.market-browse：内置源返回目录。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-browse"]({"source": "builtin"}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"]["id"], "builtin")
        self.assertGreaterEqual(result["total"], 10)

    def test_market_browse_builtin_search(self):
        """内置源浏览 + 关键词过滤。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-browse"]({"source": "builtin", "keyword": "简历"}))
        self.assertTrue(result["ok"])
        self.assertTrue(all("简历" in s["name"] or "简历" in s["description"] for s in result["skills"]))

    def test_market_browse_github_mocked(self):
        """skills.market-browse：GitHub 源用 mock trees API + raw 拉取。"""
        import json as _json

        from aivyos_core.server_entry import build_server

        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}

        fake_tree = MagicMock()
        fake_tree.read.return_value = _json.dumps({"tree": [
            {"type": "blob", "path": "skills/translate/SKILL.md"},
            {"type": "blob", "path": "skills/code-review/SKILL.md"},
            {"type": "tree", "path": "skills"},
        ]}).encode("utf-8")
        tree_cm = MagicMock()
        tree_cm.__enter__.return_value = fake_tree

        fake_md = MagicMock()
        fake_md.read.return_value = (
            "---\nname: translate\ndescription: 专业翻译\nkeywords: [翻译, translate]\n---\n你是专业翻译助手。"
        ).encode("utf-8")
        md_cm = MagicMock()
        md_cm.__enter__.return_value = fake_md

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "git/trees" in url:
                return tree_cm
            if "raw.githubusercontent" in url:
                return md_cm
            raise OSError("unexpected url: " + url)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = asyncio.run(handlers["skills.market-browse"]({"source": "agentskillexchange", "limit": 5}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"]["id"], "agentskillexchange")
        self.assertGreaterEqual(len(result["skills"]), 1)
        translate = next(s for s in result["skills"] if s["name"] == "translate")
        self.assertEqual(translate["description"], "专业翻译")
        self.assertIn("source_url", translate)
        self.assertIn("installed", translate)
        self.assertFalse(translate["installed"])

    def test_market_browse_github_error(self):
        """GitHub 源浏览失败（网络异常）→ 返回错误信息。"""
        from aivyos_core.server_entry import build_server

        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        with patch("urllib.request.urlopen", side_effect=OSError("connection failed")):
            result = asyncio.run(handlers["skills.market-browse"]({"source": "agentskillexchange"}))
        self.assertFalse(result["ok"])
        self.assertIn("浏览失败", result["error"])

    def test_market_browse_unknown_source(self):
        """浏览未知市场源 → 失败。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-browse"]({"source": "unknown-market"}))
        self.assertFalse(result["ok"])
        self.assertIn("未知市场源", result["error"])

    def test_market_list_search(self):
        """市场搜索：按关键词过滤。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-list"]({"keyword": "简历"}))
        self.assertTrue(result["ok"])
        self.assertTrue(all("简历" in s["name"] or "简历" in s["description"] for s in result["skills"]))
        self.assertGreaterEqual(result["count"], 1)

    def test_weather_skill_in_market(self):
        """天气查询技能在市场内置目录中，可安装并匹配。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-browse"]({"source": "builtin", "keyword": "天气"}))
        self.assertTrue(result["ok"])
        self.assertTrue(any(s["name"] == "天气查询" for s in result["skills"]))
        # 安装
        inst = asyncio.run(handlers["skills.market-install"]({"id": "mkt-weather"}))
        self.assertTrue(inst["ok"])
        self.assertEqual(inst["skill"]["name"], "天气查询")
        # 提示词包含 wttr.in 免费接口说明
        self.assertIn("wttr.in", inst["skill"]["system_prompt"])
        # 匹配
        chat = asyncio.run(handlers["chat.send"]({"text": "今天北京天气怎么样", "session_id": None}))
        self.assertTrue(any("天气" in s for s in chat.get("skills", [])))

    def test_market_install(self):
        """skills.market-install：安装后出现在我的技能且市场标注已安装。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-install"]({"id": "mkt-meeting-minutes"}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["skill"]["name"], "会议纪要")
        # 我的技能列表包含
        mine = asyncio.run(handlers["skills.list"]({}))
        self.assertTrue(any(s["id"] == "mkt-meeting-minutes" for s in mine["skills"]))
        # 市场标注已安装
        market = asyncio.run(handlers["skills.market-list"]({}))
        item = next(s for s in market["skills"] if s["id"] == "mkt-meeting-minutes")
        self.assertTrue(item["installed"])

    def test_market_install_unknown(self):
        """安装不存在的市场技能 → 失败。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.market-install"]({"id": "mkt-unknown"}))
        self.assertFalse(result["ok"])

    def test_parse_skill_md(self):
        """解析 SKILL.md（YAML frontmatter + 正文）。"""
        from aivyos_core.skills import parse_skill_md

        md = """---
name: translate
description: 专业翻译助手
keywords: [翻译, translate, 中英互译]
---
你是专业翻译。翻译时保持术语一致。
"""
        parsed = parse_skill_md(md, fallback_name="fallback")
        self.assertTrue(parsed["ok"])
        skill = parsed["skill"]
        self.assertEqual(skill["name"], "translate")
        self.assertEqual(skill["description"], "专业翻译助手")
        self.assertIn("翻译", skill["keywords"])
        self.assertIn("专业翻译", skill["system_prompt"])

    def test_parse_skill_md_no_frontmatter(self):
        """无 frontmatter → 全文作为 system_prompt。"""
        from aivyos_core.skills import parse_skill_md

        parsed = parse_skill_md("直接是提示词内容", fallback_name="plain")
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["skill"]["name"], "plain")
        self.assertEqual(parsed["skill"]["system_prompt"], "直接是提示词内容")

    def test_remote_import_mocked(self):
        """skills.remote-import：mock 拉取 SKILL.md → 安装到本地。"""
        from unittest.mock import patch

        from aivyos_core.server_entry import build_server

        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        md = "---\nname: doc-writer\ndescription: 文档写作\n---\n你是文档写作助手。"
        fake_resp = MagicMock()
        fake_resp.read.return_value = md.encode("utf-8")
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = fake_resp
        with patch("urllib.request.urlopen", return_value=fake_cm):
            result = asyncio.run(handlers["skills.remote-import"]({
                "url": "https://raw.githubusercontent.com/x/y/main/skills/doc-writer/SKILL.md",
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result["install"]["name"], "doc-writer")
        self.assertIn("文档写作", result["install"]["system_prompt"])

    def test_remote_import_fetch_failure(self):
        """远程拉取失败 → 返回错误。"""
        from aivyos_core.server_entry import build_server

        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["skills.remote-import"]({
            "url": "http://127.0.0.1:1/nonexistent/SKILL.md",
        }))
        self.assertFalse(result["ok"])
        self.assertIn("拉取失败", result["error"])


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
