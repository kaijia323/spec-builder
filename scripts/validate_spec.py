#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 SPEC 文件是否符合 spec-builder 的结构要求。

用法：
    python3 validate_spec.py specs/feature-export.yaml
    python3 validate_spec.py - < spec.yaml
    python3 validate_spec.py spec.yaml --json

退出码：0 = 无 error；1 = 有 error；2 = 读取或解析失败。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    raise SystemExit(2)

KNOWN_TYPES = ("feature", "bugfix", "refactor", "research", "ops")
KNOWN_STATUS = ("draft", "ready", "in_progress", "done", "blocked")

COMMON_REQUIRED = ("type", "name", "id", "version", "updated", "status",
                   "context", "acceptance_criteria", "failure_handling")
COMMON_PRESENT = ("assumptions", "blocking_questions", "open_questions", "related")

TYPE_REQUIRED = {
    "feature": ("goal", "inputs", "outputs", "constraints", "steps"),
    "bugfix": ("symptom", "environment", "reproduction", "evidence", "scope",
               "root_cause", "fix", "regression_tests"),
    "refactor": ("goal", "current_state", "motivation", "scope", "behavior_contract",
                 "steps", "rollback"),
    "research": ("question", "background", "methods", "deliverables",
                 "decision_criteria", "timebox"),
    "ops": ("goal", "target", "changes", "risks", "rollback", "monitoring"),
}

NESTED_REQUIRED = {
    "feature": {"outputs": ("format",)},
    "bugfix": {
        "reproduction": ("steps", "expected", "actual"),
        "root_cause": ("hypothesis",),
        "fix": ("approach",),
    },
}

WEAK_WORDS = ("正常", "合理", "流畅", "完善", "良好", "稳定", "友好", "易用",
              "整洁", "差不多", "尽量", "基本", "优化", "提升体验")

MEASURABLE = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "通过", "返回",
              "包含", "不再", "一致", "等于", "报错", "错误码", "秒", "毫秒",
              "测试", "=", "P95", "覆盖", "提示", "拒绝", "拦截", "限制", "禁止",
              "条", "行", "次", "无")

FAILURE_HINTS = ("失败", "异常", "超时", "错误", "报错", "拒绝", "403", "404",
                 "400", "500", "降级", "回滚", "上限", "为空", "并发", "幂等",
                 "重复", "越权", "重试")


def is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        return text == "" or text.upper() == "TBD"
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0 or all(is_blank(v) for v in value)
    if isinstance(value, dict):
        return len(value) == 0 or all(is_blank(v) for v in value.values())
    return False


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def criteria_items(spec):
    items = as_list(spec.get("acceptance_criteria"))
    return [c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) for c in items]


def weak_criteria(criteria):
    hits = []
    for i, item in enumerate(criteria, 1):
        word = next((w for w in WEAK_WORDS if w in item), None)
        if word and not any(m in item for m in MEASURABLE) and len(item) < 25:
            hits.append((i, item, word))
    return hits


def load_spec(text: str) -> dict:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("顶层不是 YAML 映射")
    spec = data.get("spec", data)
    if not isinstance(spec, dict):
        raise ValueError("spec 字段不是映射")
    return spec


def validate(spec: dict):
    errors, warnings, checks = [], [], []
    stype = spec.get("type")
    if stype not in KNOWN_TYPES:
        errors.append("type 缺失或非法：%r；应为 %s" % (stype, "/".join(KNOWN_TYPES)))
        return errors, warnings, checks
    checks.append("type = %s" % stype)

    status = spec.get("status")
    if status not in KNOWN_STATUS:
        warnings.append("status 非法或缺失：%r；建议取值 %s" % (status, "/".join(KNOWN_STATUS)))
    else:
        checks.append("status = %s" % status)

    for field in COMMON_REQUIRED + TYPE_REQUIRED.get(stype, ()):
        if field not in spec:
            errors.append("缺少必填字段：%s" % field)
        elif is_blank(spec.get(field)):
            errors.append("必填字段为空：%s" % field)

    for field in COMMON_PRESENT:
        if field not in spec:
            errors.append("缺少字段（可为空数组）：%s" % field)

    sid = spec.get("id")
    if is_blank(sid):
        errors.append("缺少稳定标识 id（格式 <type>-<slug>）")
    else:
        sid = str(sid)
        if not sid.startswith(str(stype) + "-"):
            errors.append("id 应以 %s- 开头：%r" % (stype, sid))
        elif re.search(r"\s", sid) or re.search(r"[A-Z]", sid):
            warnings.append("id 建议全小写、无空格：%r" % sid)
        checks.append("id = %s" % sid)

    version = spec.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        warnings.append("version 应为 >= 1 的整数：%r" % version)

    updated = spec.get("updated")
    if not isinstance(updated, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", updated):
        warnings.append("updated 应为 YYYY-MM-DD：%r" % updated)

    blocking = as_list(spec.get("blocking_questions"))
    if status == "ready" and not is_blank(blocking):
        errors.append("status=ready 但 blocking_questions 非空；请先解决阻塞问题，或把 status 改为 draft")

    for parent, children in NESTED_REQUIRED.get(stype, {}).items():
        node = spec.get(parent)
        if isinstance(node, dict):
            for child in children:
                if is_blank(node.get(child)):
                    errors.append("必填子字段为空：%s.%s" % (parent, child))

    criteria = criteria_items(spec)
    if not criteria:
        errors.append("acceptance_criteria 为空或缺失")
    else:
        checks.append("acceptance_criteria = %d 条" % len(criteria))
        for i, item, word in weak_criteria(criteria):
            warnings.append("第 %d 条验收标准疑似不可验证（含“%s”且无量化线索）：%s" % (i, word, item))
        if stype in ("feature", "refactor", "ops") and len(criteria) < 3:
            warnings.append("验收标准偏少（%d 条）；建议覆盖正常、边界、失败路径" % len(criteria))
        text = " ".join(criteria)
        if not any(h in text for h in FAILURE_HINTS):
            warnings.append("验收标准似乎只覆盖正常路径；建议补充边界（空/上限/并发）与失败（异常/超时/权限）路径")

    if not as_list(spec.get("examples")):
        warnings.append("没有 examples；建议至少补一个输入→输出示例")

    if stype == "bugfix":
        root = spec.get("root_cause") or {}
        fix = spec.get("fix") or {}
        if isinstance(root, dict) and root.get("confirmed") is False and isinstance(fix, dict) and not is_blank(fix.get("approach")):
            warnings.append("root_cause.confirmed 为 false；fix 应先包含定位/验证步骤，不要直接改代码")
        text = " ".join(criteria)
        if criteria and not any(k in text for k in ("复现", "回归", "不再", "原")):
            warnings.append("bugfix 验收标准建议包含“原复现步骤不再出现”或“回归测试通过”")

    if stype == "refactor":
        bc = as_list(spec.get("behavior_contract"))
        if bc and len(bc) < 2:
            warnings.append("behavior_contract 至少列出 2 条必须保持不变的外部行为")

    if stype == "ops":
        risks = as_list(spec.get("risks"))
        if risks and any(is_blank(r) for r in risks):
            warnings.append("risks 条目不完整")
        mon = as_list(spec.get("monitoring"))
        if mon and any(is_blank(m) for m in mon):
            warnings.append("monitoring 条目不完整")

    return errors, warnings, checks


def render(path_label, stype, errors, warnings, checks):
    lines = ["SPEC 校验：%s" % path_label, "类型：%s" % (stype or "(未知)"), ""]
    for c in checks:
        lines.append("  ✓ %s" % c)
    if errors:
        lines.append("")
        lines.append("ERROR（%d）：" % len(errors))
        for e in errors:
            lines.append("  ✗ %s" % e)
    if warnings:
        lines.append("")
        lines.append("WARN（%d）：" % len(warnings))
        for w in warnings:
            lines.append("  ⚠ %s" % w)
    lines.append("")
    if errors:
        lines.append("结果：FAIL（%d error / %d warning）" % (len(errors), len(warnings)))
    else:
        lines.append("结果：PASS（0 error / %d warning）" % len(warnings))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验 spec-builder 生成的 SPEC")
    parser.add_argument("path", help="SPEC 文件路径，或用 - 从 stdin 读取")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    if args.path == "-":
        text, label = sys.stdin.read(), "<stdin>"
    else:
        p = Path(args.path)
        try:
            text, label = p.read_text(encoding="utf-8"), str(p)
        except OSError as exc:
            if args.json:
                print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
            else:
                sys.stderr.write("无法读取 %s：%s\n" % (args.path, exc))
            return 2

    try:
        spec = load_spec(text)
    except Exception as exc:  # noqa: BLE001
        if args.json:
            print(json.dumps({"valid": False, "error": "YAML 解析失败：%s" % exc}, ensure_ascii=False))
        else:
            sys.stderr.write("YAML 解析失败：%s\n" % exc)
        return 2

    errors, warnings, checks = validate(spec)
    if args.json:
        print(json.dumps({
            "valid": not errors,
            "type": spec.get("type"),
            "errors": errors,
            "warnings": warnings,
            "checks": checks,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(label, spec.get("type"), errors, warnings, checks))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
