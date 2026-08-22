# -*- coding: utf-8 -*-
"""发布更新包：构建 → 签名 → 打 zip → 输出 GitHub Releases 上传指引。

用法：
  python scripts/publish_update.py --root <包目录> --version 1.2.0 \
      [--type feature] [--out dist/update] [--repo Zxc-23/AivyOS]

流程：
  1. 构建更新包目录（--root，含要更新的文件）
  2. 用 scripts/sign_update.py 签名（复用 ~/.aivyos/pki/ 的 Root/Intermediate 密钥，客户端同密钥可验签）
  3. 打包 zip：aivyos-<version>.zip + manifest.signed.json
  4. 输出上传到 GitHub Releases 的命令（gh release create）

说明：
  - 首次运行会生成 PKI 密钥到 --pki（默认 ~/.aivyos/pki），与客户端共享；
    若客户端已有 pki，请用相同 --pki 目录（保证 Root 公钥一致才能验签通过）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile
from pathlib import Path


def main() -> None:
    import sys as _sys

    # 跨平台安全输出（Windows GBK 控制台打印 UTF-8 中文会崩）
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="AivyOS 发布更新包（签名 + zip + GitHub Releases 指引）")
    ap.add_argument("--root", required=True, help="更新包目录（构建产物）")
    ap.add_argument("--version", required=True, help="发布版本（语义版本）")
    ap.add_argument("--type", default="feature", choices=["critical", "feature", "patch"])
    ap.add_argument("--out", default="dist/update", help="输出目录")
    ap.add_argument("--pki", default=None, help="PKI 密钥目录（缺省 ~/.aivyos/pki，与客户端一致）")
    ap.add_argument("--repo", default="Zxc-23/AivyOS", help="GitHub 仓库（上传指引用）")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # PKI 目录：默认 ~/.aivyos/pki（与客户端 UpdateService 相同位置）
    pki_dir = Path(args.pki) if args.pki else Path(os.path.expanduser("~/.aivyos/pki"))
    pki_dir.mkdir(parents=True, exist_ok=True)
    root_key = pki_dir / "root.seed"
    inter_key = pki_dir / "intermediate.seed"
    if not root_key.exists() or not inter_key.exists():
        print(f"[发布] 首次生成 PKI 密钥 → {pki_dir}")
        print("       客户端必须使用同一 pki 目录（或复制 root.seed/intermediate.seed 到客户端 ~/.aivyos/pki/）")
        print("       否则验签会失败（Root 公钥不一致）。")
    else:
        print(f"[发布] 复用 PKI 密钥 ← {pki_dir}")

    # ① 签名（生成 manifest.signed.json 到 --out）
    sign_out = out / "signed"
    sign_out.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "scripts/sign_update.py",
        "--root", str(root), "--version", args.version, "--type", args.type,
        "--root-key", str(root_key), "--intermediate-key", str(inter_key),
        "--out", str(sign_out),
    ]
    print(f"[发布] 签名: {' '.join(cmd)}")
    r = subprocess.run(
        cmd, cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print(f"[发布] 签名失败:\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    print(r.stdout.strip())

    manifest = sign_out / "manifest.signed.json"
    if not manifest.exists():
        print("[发布] 签名产物缺失", file=sys.stderr)
        sys.exit(1)

    # ② 打包 zip（包含更新包文件 + manifest）
    zip_name = f"aivyos-{args.version}.zip"
    zip_path = out / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(root).as_posix())
        zf.write(manifest, "manifest.signed.json")
    print(f"[发布] 更新包: {zip_path} ({zip_path.stat().st_size / 1024:.1f} KB)")

    # ③ 输出 GitHub Releases 上传指引
    tag = f"v{args.version}"
    print()
    print("=" * 60)
    print(f"  GitHub Releases 上传指引 (repo: {args.repo})")
    print("=" * 60)
    print(f"  1. 创建 release 并上传两个 asset:")
    print(f"     - {zip_path}")
    print(f"     - {manifest}")
    print()
    print("  命令行方式:")
    print(f"    gh release create {tag} \\")
    print(f"        \"{zip_path}\" \"{manifest}\" \\")
    print(f"        --repo {args.repo} --title \"AivyOS {args.version}\" --notes \"更新说明\"")
    print()
    print(f"  或网页方式: https://github.com/{args.repo}/releases/new?tag={tag}")
    print(f"  （上传 {zip_name} 和 manifest.signed.json 两个文件）")
    print()
    print(f"  客户端检查时要求 asset 命名：")
    print("     - manifest.signed.json（必须）")
    print("     - *.zip 或 *.upd（更新包，推荐 .zip）")
    print("=" * 60)


if __name__ == "__main__":
    main()
