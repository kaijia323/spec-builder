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
    - 已存在时会检测「旧版查看器」：技能模板与目标文件开头都带
      <!-- spec-builder-viewer: N --> 标记（前 2KB 内）。目标是旧版就提示可以用 --force 更新；
      解析不到标记（本地改过 / 不是本技能生成的）只说明无法识别，不建议覆盖别人的文件；
      技能模板本身没有标记时跳过检测、保持原样输出。
退出码：0 = 已存在或复制成功；2 = 找不到模板或写入失败。
    （旧版检测只是提示，不会把「已存在」变成失败。）
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ASSET = Path(__file__).resolve().parent.parent / "assets" / "specs.html"

# 版本标记由 assets/specs.html 维护，放在文件前 2KB 内；解析不到就跳过检测（不报错）
VERSION_MARKER = re.compile(r"spec-builder-viewer:\s*(\d+)")
MARKER_WINDOW = 2048  # 只在开头 2KB 里找，避免误命中正文里的同名字符串


def resolve_specs_dir(raw: str) -> Path:
    p = Path(raw).expanduser().resolve()
    return p if p.name == "specs" else p / "specs"


def read_version(path: Path):
    """读文件开头 2KB 里的 <!-- spec-builder-viewer: N -->，返回 int；没有或读不了返回 None。"""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(MARKER_WINDOW)
    except OSError:
        return None
    match = VERSION_MARKER.search(head)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:  # pragma: no cover - 正则已限定数字
        return None


def version_notice(target: Path, asset_version):
    """已存在且不覆盖时，判断要不要提示旧版查看器；返回要打印的行（list，可为空）。"""
    if asset_version is None:
        return []  # 技能模板里没有版本标记：跳过检测，保持原来的输出
    target_version = read_version(target)
    if target_version is None:
        return ["  （无法识别版本，可能被本地改过）"]
    if target_version < asset_version:
        return [
            "检测到旧版查看器（v%d → v%d）：新版会把 status 阶梯（含\"已验证\"）、" % (target_version, asset_version),
            "\"N 个问题没问过\"、\"N 天没动\"、验收记录等显示出来。",
            "要更新请运行：python3 ensure_viewer.py <项目根目录> --force",
            "（会覆盖你本地对 specs.html 的改动，如有）",
        ]
    return []  # 版本相同或更新：保持原样


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="确保 specs/specs.html 查看器存在")
    ap.add_argument("path", nargs="?", default=".", help="项目根目录或 specs 目录（默认当前目录）")
    ap.add_argument("--force", action="store_true", help="覆盖已有的 specs.html")
    args = ap.parse_args(argv)

    if not ASSET.is_file():
        sys.stderr.write("找不到查看器模板：%s\n" % ASSET)
        return 2
    asset_version = read_version(ASSET)

    specs = resolve_specs_dir(args.path)
    try:
        specs.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.stderr.write("无法创建 %s：%s\n" % (specs, exc))
        return 2

    target = specs / "specs.html"
    if target.exists() and not args.force:
        print("已存在，未覆盖：%s" % target)
        for line in version_notice(target, asset_version):
            print(line)
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
