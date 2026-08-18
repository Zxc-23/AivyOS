"""MCP browser Server（文档 §5.1.2 / T3.4）：browser-use / Playwright 驱动 + mock 回退。

后端降级链（§2 代码优先 + 优雅降级）：
- browser-use（可选）：自然语言驱动浏览器执行任务（§7.1，95K stars，底层 Playwright）
- playwright（可选）：直接 API 驱动 —— 导航/截图/监控/视口
- mock：明确标注，不伪装

均不可用时 mock 回退，绝不假装真实浏览器结果。
"""

from __future__ import annotations

import base64
from typing import Any, Dict, Optional

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool


class BrowserServer:
    def __init__(self, llm=None) -> None:
        """llm：可选 LLM 客户端（browser-use Agent 需要），缺省时 browser-use 不可用。"""
        self.llm = llm
        self._bu = None
        self._pw = None
        try:
            import browser_use  # noqa: F401

            self._bu = "browser-use"
        except ImportError:
            pass
        try:
            import playwright  # noqa: F401

            self._pw = "playwright"
        except ImportError:
            pass
        self.backend = self._bu or self._pw or "mock"

    # ---- browser-use 自然语言驱动（§7.1，可选）----

    async def _task(self, args: Dict[str, Any]) -> ToolResult:
        """自然语言任务驱动浏览器（browser-use Agent；缺 LLM/库时降级）。"""
        task = args.get("task", "")
        if not task:
            return ToolResult(False, error="任务描述为空")
        if self._bu == "browser-use" and self.llm is not None:
            try:
                from browser_use import Agent

                agent = Agent(task=task, llm=self.llm)
                history = await agent.run()
                n_steps = len(getattr(history, "history", []) or [])
                return ToolResult(
                    True,
                    content=f"browser-use 已完成任务: {task}",
                    data={"steps": n_steps, "backend": "browser-use"},
                )
            except Exception as e:
                return ToolResult(False, error=f"browser-use 失败: {e}")
        if self._pw == "playwright":
            # 降级：Playwright 直接导航（无法自然语言，仅打开首 URL 若含 http）
            import re

            m = re.search(r"https?://\S+", task)
            if m:
                return await self._navigate({"url": m.group(0)})
            return ToolResult(
                False,
                error="browser-use 不可用（缺 browser_use 包或 LLM），且任务不含 URL，无法降级执行",
            )
        return ToolResult(True, content=f"（mock browser-use）任务: {task[:60]}…：接入 browser-use 后真实执行", data={"backend": "mock"})

    async def _reload(self, args: Dict[str, Any]) -> ToolResult:
        """页面热重载（§11 热重载：文件变化时刷新页面）。"""
        url = args.get("url", "")
        if self._pw == "playwright":
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page()
                    if url:
                        await page.goto(url, timeout=15000)
                    await page.reload(wait_until="domcontentloaded")
                    await browser.close()
                return ToolResult(True, content=f"已热重载 {url or '当前页'}", data={"backend": "playwright"})
            except Exception as e:
                return ToolResult(False, error=f"playwright 热重载失败: {e}")
        return ToolResult(True, content="（mock reload）已刷新页面：接入 playwright 后真实重载", data={"backend": "mock"})

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

    async def _monitor(self, args: Dict[str, Any]) -> ToolResult:
        """浏览器控制台/网络监控（§11 / T5.8）：捕获 console 消息 + 网络请求/响应。"""
        if self._pw == "playwright":
            try:
                from playwright.async_api import async_playwright

                events: Dict[str, list] = {"console": [], "network": []}
                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page()
                    page.on("console", lambda msg: events["console"].append({"type": msg.type, "text": msg.text[:200]}))
                    page.on(
                        "request",
                        lambda req: events["network"].append({"kind": "req", "url": req.url[:200], "method": req.method}),
                    )
                    page.on(
                        "response",
                        lambda res: events["network"].append(
                            {"kind": "res", "url": res.url[:200], "status": res.status}
                        ),
                    )
                    await page.goto(args.get("url", "about:blank"), timeout=15000)
                    await page.wait_for_timeout(args.get("hold_ms", 800))
                    await browser.close()
                return ToolResult(True, data={"events": events, "backend": "playwright"})
            except Exception as e:
                return ToolResult(False, error=f"playwright 监控失败: {e}")
        return ToolResult(True, content="（mock monitor）控制台/网络监控：接入 playwright 后捕获真实事件", data={"events": {"console": [], "network": []}, "backend": "mock"})

    async def _viewport(self, args: Dict[str, Any]) -> ToolResult:
        """多设备视口预览（§11 / T5.9）：desktop/mobile/tablet 截图。"""
        viewports = {
            "desktop": (1280, 800),
            "mobile": (390, 844),
            "tablet": (768, 1024),
        }
        device = args.get("device", "desktop")
        vp = viewports.get(device)
        if vp is None:
            return ToolResult(False, error=f"未知设备: {device}（可选 {list(viewports)}）")
        if self._pw == "playwright":
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page(viewport={"width": vp[0], "height": vp[1]})
                    await page.goto(args.get("url", "about:blank"), timeout=15000)
                    png = await page.screenshot()
                    await browser.close()
                return ToolResult(
                    True, data={"device": device, "viewport": vp, "image": base64.b64encode(png).decode(), "backend": "playwright"}
                )
            except Exception as e:
                return ToolResult(False, error=f"playwright 视口截图失败: {e}")
        return ToolResult(True, content=f"（mock viewport）{device} {vp}：接入 playwright 后返回真实截图", data={"device": device, "viewport": vp, "backend": "mock"})

    def tools(self) -> list[Tool]:
        return [
            make_tool(
                "browser_task", "自然语言浏览器任务（§7.1 browser-use）",
                {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]},
                self._task, PermissionLevel.L2, server="browser",
            ),
            make_tool(
                "browser_reload", "页面热重载（§11）",
                {"type": "object", "properties": {"url": {"type": "string"}}},
                self._reload, PermissionLevel.L0, server="browser",
            ),
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
            make_tool(
                "browser_monitor", "控制台/网络监控（§11）",
                {"type": "object", "properties": {"url": {"type": "string"}, "hold_ms": {"type": "integer"}}, "required": ["url"]},
                self._monitor, PermissionLevel.L1, server="browser",
            ),
            make_tool(
                "browser_viewport", "多设备视口预览（§11）",
                {"type": "object", "properties": {"url": {"type": "string"}, "device": {"type": "string"}}, "required": ["url"]},
                self._viewport, PermissionLevel.L0, server="browser",
            ),
        ]
