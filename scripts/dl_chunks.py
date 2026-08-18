"""并行分块下载器（绕过单连接限速）。用法：python scripts/dl_chunks.py <url> <out> <chunks>"""
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CHUNK = 512 * 1024


def get_total(url: str, timeout: float = 30.0) -> int:
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cr = r.headers.get("Content-Range", "")
        total = int(cr.split("/")[-1]) if "/" in cr else None
        if total is None:
            raise RuntimeError(f"无法获取总大小: {cr}")
        return total


def download_range(url: str, part: str, start: int, end: int) -> None:
    pos = os.path.getsize(part) if os.path.exists(part) else 0
    start += pos
    tries = 0
    while start <= end and tries < 200:
        req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                with open(part, "ab" if pos else "wb") as f:
                    while True:
                        d = r.read(CHUNK)
                        if not d:
                            break
                        f.write(d)
                        start += len(d)
                pos = start
            return
        except Exception as e:
            tries += 1
            time.sleep(1.0)
    raise SystemExit(f"分块失败 {part}: start={start}")


def main() -> None:
    url, out, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    total = get_total(url)
    print(f"总大小: {total/1e6:.1f} MB, 分 {n} 块", flush=True)
    size = os.path.getsize(out) if os.path.exists(out) else 0
    done = min(size, total)
    if done >= total:
        print("已完成", flush=True)
        return
    if done > 0:  # 已下载部分视为第一块进度
        done = 0
    step = (total + n - 1) // n
    parts = []
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = []
        for i in range(n):
            s, e = i * step, min((i + 1) * step - 1, total - 1)
            p = f"{out}.part{i}"
            parts.append(p)
            futs.append(ex.submit(download_range, url, p, s, e))
        for f in futs:
            f.result()
    with open(out, "wb") as fh:
        for p in parts:
            with open(p, "rb") as pf:
                while True:
                    d = pf.read(1 << 20)
                    if not d:
                        break
                    fh.write(d)
            os.remove(p)
    print(f"[ok] {out} {os.path.getsize(out)} bytes", flush=True)


if __name__ == "__main__":
    main()
