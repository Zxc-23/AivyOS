"""断点续传下载器（沙箱网络慢/不稳定场景）。用法：python scripts/dl_resume.py <url> <out> [timeout_s]"""
import os
import re
import sys
import time
import urllib.request

CHUNK = 256 * 1024


def download(url: str, out: str, timeout: float = 30.0, max_tries: int = 60) -> None:
    total = 0
    for attempt in range(1, max_tries + 1):
        resume = os.path.getsize(out) if os.path.exists(out) else 0
        headers = {"Range": f"bytes={resume}-"} if resume else {}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_len = resp.headers.get("Content-Length")
                expected = int(content_len) + resume if content_len and not resume else None
                mode = "ab" if resume else "wb"
                with open(out, mode) as f:
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
                        total += len(chunk)
                size = os.path.getsize(out)
                print(f"[ok] {out} {size} bytes (tries={attempt}, resumed={resume > 0})", flush=True)
                return
        except Exception as e:
            print(f"[retry {attempt}] {type(e).__name__}: {e}", flush=True)
            time.sleep(1.5)
    raise SystemExit(f"下载失败: {url}")


if __name__ == "__main__":
    url, out = sys.argv[1], sys.argv[2]
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    download(url, out, timeout)
