#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确保项目 specs/ 下有一份 specs.html 查看器。

用法：
    python3 ensure_viewer.py [项目根目录或 specs 目录]
    python3 ensure_viewer.py . --force        # 覆盖已有的 specs.html

行为：
    - 默认使用当前工作目录。参数以 specs 结尾时视为 specs 目录，否则视为项目根目录。
    - specs/ 不存在则创建。
    - specs.html 缺失时从技能 assets/specs.html 复制；已存在则保留（除非 --force），
      避免覆盖用户或其它工具改动过的版本。
退出码：0 = 已存在或复制成功；2 = 找不到模板或写入失败。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ASSET = Path(__file__).resolve().parent.parent / "assets" / "specs.html"


def resolve_specs_dir(raw: str) -> Path:
    p = Path(raw).expanduser().resolve()
    return p if p.name == "specs" else p / "specs"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="确保 specs/specs.html 查看器存在")
    ap.add_argument("path", nargs="?", default=".", help="项目根目录或 specs 目录（默认当前目录）")
    ap.add_argument("--force", action="store_true", help="覆盖已有的 specs.html")
    args = ap.parse_args(argv)

    if not ASSET.is_file():
        sys.stderr.write("找不到查看器模板：%s\n" % ASSET)
        return 2

    specs = resolve_specs_dir(args.path)
    try:
        specs.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.stderr.write("无法创建 %s：%s\n" % (specs, exc))
        return 2

    target = specs / "specs.html"
    if target.exists() and not args.force:
        print("已存在，未覆盖：%s" % target)
        return 0
    try:
        shutil.copyfile(ASSET, target)
    except OSError as exc:
        sys.stderr.write("写入失败 %s：%s\n" % (target, exc))
        return 2
    print("已创建查看器：%s" % target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
