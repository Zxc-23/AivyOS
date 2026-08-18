"""MCP browser Server（文档 §5.1.2 / T3.4）：browser-use / Playwright 驱动 + mock 回退。

- 真实后端：playwright（可选）——导航/截图/取文本（browser-use 为 Phase 2 后续升级）
- mock 回退：明确标注，不伪装
"""

from __future__ import annotations

import base64
from typing import Any, Dict, Optional

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool


class BrowserServer:
    def __init__(self) -> None:
        self._pw = None
        try:
            import playwright  # noqa: F401

            self._pw = "playwright"
        except ImportError:
            pass
        self.backend = self._pw or "mock"

    async def _navigate(self, args: Dict[str, Any]) -> ToolResult:
        url = args.get("url", "")
        if not url.startswith(("http://", "https://")):
            return ToolResult(False, error=f"URL 格式非法: {url}")
        if self._pw == "playwright":
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page()
                    await page.goto(url, timeout=15000)
                    title = await page.title()
                    await browser.close()
                return ToolResult(True, content=f"已导航至 {url}", data={"title": title, "backend": "playwright"})
            except Exception as e:
                return ToolResult(False, error=f"playwright 失败: {e}")
        return ToolResult(True, content=f"（mock browser）导航 {url}：接入 playwright 后返回真实页面", data={"backend": "mock"})

    async def _screenshot(self, args: Dict[str, Any]) -> ToolResult:
        if self._pw == "playwright":
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page()
                    await page.goto(args.get("url", "about:blank"), timeout=15000)
                    png = await page.screenshot()
                    await browser.close()
                return ToolResult(True, data={"image": base64.b64encode(png).decode(), "backend": "playwright"})
            except Exception as e:
                return ToolResult(False, error=f"playwright 失败: {e}")
        return ToolResult(True, content="（mock browser）截图：接入 playwright 后返回真实图像", data={"backend": "mock"})

    def tools(self) -> list[Tool]:
        return [
            make_tool(
                "browser_navigate", "打开网页（§7.1）",
                {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
                self._navigate, PermissionLevel.L1, server="browser",
            ),
            make_tool(
                "browser_screenshot", "网页截图",
                {"type": "object", "properties": {"url": {"type": "string"}}},
                self._screenshot, PermissionLevel.L0, server="browser",
            ),
        ]
