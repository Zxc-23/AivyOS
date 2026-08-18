"""通用 HTML → Markdown 转换（用于读取 AivyOS 历史规格文档）。
用法：python scripts/html2md.py <input.html> <output.md>"""
import re
import sys
from pathlib import Path


def inline(text: str) -> str:
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.S)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.S)
    text = re.sub(r"<a href=\"(.*?)\".*?>(.*?)</a>", r"[\2](\1)", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return text.strip()


def convert(html: str) -> str:
    # 保护代码块
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return f"@@CODE{len(codes)-1}@@"

    html = re.sub(r"<pre[^>]*>(.*?)</pre>", stash, html, flags=re.S)
    html = re.sub(r"<code[^>]*>(.*?)</code>", stash, html, flags=re.S)

    # 表格
    def table(m):
        rows = re.findall(r"<tr>(.*?)</tr>", m.group(1), flags=re.S)
        lines = []
        for i, row in enumerate(rows):
            cells = [inline(c) for c in re.findall(r"<t[hd]>(.*?)</t[hd]>", row, flags=re.S)]
            if not cells:
                continue
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in cells) + " |")
        return "\n".join(lines)

    html = re.sub(r"<table[^>]*>(.*?)</table>", table, html, flags=re.S)

    # 块元素换行
    html = re.sub(r"</(p|h[1-6]|li|div|blockquote)>", "\n", html)
    html = re.sub(r"<(h[1-6])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)[1]) + " ", html)
    html = re.sub(r"<(li)[^>]*>", "\n- ", html)
    html = re.sub(r"<(blockquote)[^>]*>", "\n> ", html)
    html = re.sub(r"<hr\s*/?>", "\n---\n", html)
    # 还原代码块
    html = re.sub(r"@@CODE(\d+)@@", lambda m: "\n```\n" + codes[int(m.group(1))] + "\n```\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    lines = [ln.rstrip() for ln in html.split("\n")]
    out, blank = [], 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln)
    return "\n".join(out).strip() + "\n"


if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(convert(src.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"已转换: {src.name} → {dst} ({dst.stat().st_size} bytes)")
