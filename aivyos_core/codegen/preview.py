"""自动预览控制器（文档 §11 / T5.5）：分类型启动 dev server + 截图验证 + 多设备视口（T5.9）。"""

from __future__ import annotations

import asyncio
import http.server
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# 各项目类型的开发服务器（§11：vite/webpack/python http.server 等）
VIEWPORTS = {
    "desktop": (1280, 800),
    "mobile": (390, 844),
    "tablet": (768, 1024),
}


class PreviewController:
    def __init__(self, browser_server=None) -> None:
        self._servers: Dict[str, Any] = {}  # workspace -> (srv, thread)
        self.browser_server = browser_server  # 可选 MCP browser server（截图）

    # ---- dev server ----

    def start(self, workspace, project_type: str = "static-site", port: int = 0) -> str:
        """启动开发服务器，返回 URL。分类型：静态→http.server；Node 项目→npm run dev（子进程）。"""
        ws = Path(workspace).resolve()
        if str(ws) in self._servers:
            return f"http://127.0.0.1:{self._servers[str(ws)][0].server_port}/"

        if project_type in ("static-site", "python-cli", "python-api"):
            import functools

            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ws))
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            self._servers[str(ws)] = (srv, None)
            url = f"http://127.0.0.1:{srv.server_address[1]}/"
        else:
            # Node 项目（react/vue/next/tauri）：npm run dev 子进程
            import subprocess

            proc = subprocess.Popen(
                ["npm", "run", "dev"], cwd=str(ws),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._servers[str(ws)] = (None, proc)
            url = "http://127.0.0.1:5173/" if project_type != "nextjs-app" else "http://127.0.0.1:3000/"
        log.info("预览启动: %s → %s", ws, url)
        return url

    def stop(self, workspace=None) -> None:
        if workspace is None:
            targets = list(self._servers.keys())
        else:
            key = str(Path(workspace).resolve())
            targets = [key] if key in self._servers else []
        for key in targets:
            srv, proc = self._servers.pop(key)
            if srv is not None:
                srv.shutdown()
                srv.server_close()
            if proc is not None:
                proc.terminate()

    # ---- 截图验证（§11 截图反馈 / T5.5）----

    async def screenshot(self, url: str) -> Dict[str, Any]:
        if self.browser_server is not None:
            return await self.browser_server._screenshot({"url": url})
        return {"backend": "none", "note": "未配置 browser server"}

    # ---- 多设备视口（§11 多设备预览 / T5.9）----

    async def capture_viewport(self, url: str, device: str = "desktop") -> Dict[str, Any]:
        """按设备视口截图（Playwright 真实 / mock 回退）。"""
        vp = VIEWPORTS.get(device, VIEWPORTS["desktop"])
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page(viewport={"width": vp[0], "height": vp[1]})
                await page.goto(url, timeout=15000)
                import base64

                png = await page.screenshot()
                await browser.close()
            return {"device": device, "viewport": vp, "image": base64.b64encode(png).decode(), "backend": "playwright"}
        except ImportError:
            return {"device": device, "viewport": vp, "backend": "mock", "note": "接入 playwright 后返回真实截图"}

    def status(self) -> Dict[str, Any]:
        return {"active": len(self._servers), "viewports": VIEWPORTS}
