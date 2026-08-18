"""Cargo 本地 HTTP 代理（绕过沙箱 schannel 限制）。

cargo 的 libcurl 使用 schannel（沙箱禁用）→ 无法直接访问 https 源。
本代理将 rsproxy 的 HTTPS 源以纯 HTTP 暴露给 cargo：
- /index/*        → http://rsproxy.cn/index/*
- /crates/*/download → http://rsproxy.cn/api/v1/crates/*/download
- /index/config.json  → 动态生成，dl 指向本地 http 地址

用法：python scripts/cargo_http_proxy.py [port]（默认 31888）
"""

from __future__ import annotations

import http.server
import json
import sys
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 31888
UPSTREAM = "http://rsproxy.cn"


class Proxy(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path
        if path == "/index/config.json":
            body = json.dumps({"dl": f"http://127.0.0.1:{PORT}/crates", "api": UPSTREAM}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/crates/"):
            upstream = UPSTREAM + "/api/v1" + path
        else:
            upstream = UPSTREAM + path
        try:
            with urllib.request.urlopen(urllib.request.Request(upstream), timeout=120) as r:
                data = r.read()
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(str(e))))
            self.end_headers()
            self.wfile.write(str(e).encode())


if __name__ == "__main__":
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Proxy)
    print(f"cargo http proxy listening on 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
