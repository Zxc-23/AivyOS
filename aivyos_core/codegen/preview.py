"""自动预览控制器（文档 §11 / T5.5、T5.9）：分类型 dev server 生命周期管理 + 截图 AI 视觉验证。

- 开发服务器管理（§11）：start/stop/list/status/reload，vite/webpack/python http.server
- 截图反馈（§11 截图反馈）：browser 截图 → vision Understand 描述 → 渲染验证
- 多设备视口（§11 多设备预览 / T5.9）：desktop/mobile/tablet
"""

from __future__ import annotations

import base64
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

# 项目类型 → 默认 dev 端口（Node 类固定端口，静态类自动分配）
DEFAULT_PORTS = {
    "static-site": 0,
    "python-cli": 0,
    "python-api": 0,
    "react-web-app": 5173,
    "vue-web-app": 5173,
    "nextjs-app": 3000,
    "tauri-desktop-app": 5173,
}


class PreviewController:
    def __init__(self, browser_server=None, understand=None) -> None:
        self._servers: Dict[str, Dict[str, Any]] = {}  # workspace -> {srv, proc, type, url, port}
        self.browser_server = browser_server  # 可选 MCP browser server（截图/监控）
        self.understand = understand  # 可选 vision UnderstandBackend（§3.3 AI 视觉验证）

    # ---- 开发服务器生命周期管理（§11 开发服务器）----

    def start(self, workspace, project_type: str = "static-site", port: int = 0) -> str:
        """启动开发服务器，返回 URL。已启动则复用。静态→http.server；Node→npm run dev。"""
        ws = Path(workspace).resolve()
        key = str(ws)
        if key in self._servers:
            return self._servers[key]["url"]

        if project_type in ("static-site", "python-cli", "python-api"):
            import functools

            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ws))
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port or DEFAULT_PORTS[project_type]), handler)
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            url = f"http://127.0.0.1:{srv.server_address[1]}/"
            self._servers[key] = {"srv": srv, "proc": None, "type": project_type, "url": url, "port": srv.server_address[1]}
        else:
            import subprocess

            proc = None
            try:
                proc = subprocess.Popen(
                    ["npm", "run", "dev"], cwd=str(ws),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                pass  # npm 缺失 → 降级静态 http.server（§2 优雅降级）
            if proc is None:
                import functools

                handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ws))
                srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                url = f"http://127.0.0.1:{srv.server_address[1]}/"
                self._servers[key] = {"srv": srv, "proc": None, "type": project_type, "url": url, "port": srv.server_address[1]}
                log.warning("npm 缺失，%s 降级静态预览 %s", project_type, url)
                return url
            port = port or DEFAULT_PORTS.get(project_type, 5173)
            url = f"http://127.0.0.1:{port}/"
            self._servers[key] = {"srv": None, "proc": proc, "type": project_type, "url": url, "port": port}
        log.info("预览启动: %s (%s) → %s", ws, project_type, url)
        return url

    def stop(self, workspace=None) -> None:
        if workspace is None:
            targets = list(self._servers.keys())
        else:
            key = str(Path(workspace).resolve())
            targets = [key] if key in self._servers else []
        for key in targets:
            info = self._servers.pop(key)
            srv, proc = info.get("srv"), info.get("proc")
            if srv is not None:
                try:
                    srv.shutdown()
                    srv.server_close()
                except Exception:
                    pass
            if proc is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def list_servers(self) -> list[Dict[str, Any]]:
        """列出全部 dev server（§11 开发服务器管理）。"""
        return [
            {"workspace": k, "type": v["type"], "url": v["url"], "port": v["port"]}
            for k, v in self._servers.items()
        ]

    def server_status(self, workspace=None) -> Dict[str, Any]:
        return {"active": len(self._servers), "servers": self.list_servers(), "viewports": VIEWPORTS}

    # ---- 截图验证（§11 截图反馈 / T5.5）----

    async def screenshot(self, url: str) -> Dict[str, Any]:
        if self.browser_server is not None:
            r = await self.browser_server._screenshot({"url": url})
            return {"ok": r.ok, "image": r.data.get("image") if r.ok else None, "backend": r.data.get("backend", "?")}
        return {"ok": False, "backend": "none", "note": "未配置 browser server"}

    # ---- AI 视觉验证（§11 截图反馈：AI 视觉检查 / §3.3）----

    async def visual_check(self, url: str) -> Dict[str, Any]:
        """截图 → vision Understand 描述 → 判定页面是否正常渲染。

        - understand 为 None 或 mock → 标注 honest "未接入视觉模型"，不伪造判定
        - 真实理解后端：若描述包含异常关键词（错误/空白/404/失败）→ 判为异常
        """
        shot = await self.screenshot(url)
        if not shot.get("ok") or not shot.get("image"):
            return {"ok": False, "verdict": "no-screenshot", "backend": shot.get("backend", "none")}
        if self.understand is None:
            return {"ok": True, "verdict": "not-verified", "note": "未配置 vision Understand，跳过 AI 视觉验证", "backend": shot["backend"]}
        try:
            image = base64.b64decode(shot["image"])
            desc = self.understand.describe(image)
        except Exception as e:
            return {"ok": False, "verdict": "vision-error", "error": str(e), "backend": shot["backend"]}
        if getattr(self.understand, "name", "") == "mock-vision":
            return {"ok": True, "verdict": "not-verified", "note": desc, "backend": shot["backend"]}
        abnormal = any(k in desc for k in ("错误", "404", "空白", "无法", "失败", "error", "not found"))
        return {"ok": not abnormal, "verdict": "abnormal" if abnormal else "normal", "description": desc[:200], "backend": shot["backend"]}

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
                png = await page.screenshot()
                await browser.close()
            return {"device": device, "viewport": vp, "image": base64.b64encode(png).decode(), "backend": "playwright"}
        except ImportError:
            return {"device": device, "viewport": vp, "backend": "mock", "note": "接入 playwright 后返回真实截图"}
