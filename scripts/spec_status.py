#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推进 SPEC 状态并收尾的原子命令（spec-builder 生命周期工具）。

用法示例：
    python3 scripts/spec_status.py spec.yaml --to in_progress --by impl-agent
    python3 scripts/spec_status.py spec.yaml --to done \
        --by impl-agent \
        --note "3 项 AC 全过，单测 44 passed" \
        --result "11/11 AC 通过，44 项测试全绿" \
        --acceptance "AC#3 空筛选返回 400|pass|pnpm test -- x.spec.ts -> 44 passed" \
        --command "pnpm --filter server test -> 2 suites / 262 passed" \
        --artifact "tmp/verify-report.md" \
        --unverified "AC#11 需发布后 24h 观察" \
        --follow-up "F1（中）：重试后 participants 偏小"
    python3 scripts/spec_status.py spec.yaml --to verified --verify-by independent --verifier reviewer-a
    python3 scripts/spec_status.py spec.yaml --to blocked --reason "等运维开通权限"

脚本只做这几件事：改 status / version +1 / updated 改成今天 / 追加 status_log /
写入或合并 verification / 追加 follow_ups。前置条件不满足时拒绝执行（退出码 3）且不写文件。

格式保证（环境里没有 ruamel.yaml，只有 PyYAML）：
    * 绝不用 yaml.dump 整份重写——那会丢注释、乱掉字段顺序；
    * 只做定向文本编辑：顶层单行字段替换值（保留行尾注释）、块级字段整块替换或按锚点插入；
    * 写之前把新文本 yaml.safe_load 回读，确认 status/version/updated/status_log/verification
      都是预期值，任何不一致就中止且不写文件；
    * 写临时文件 + os.replace 原子替换，--backup 时先存 <file>.bak。

写盘与并发（R8.1 / R8.2）：
    * 只读文件（权限位没有任何写位，例如 444）默认拒绝写入（退出码 3）；--force 可以强推。
      注意：判断用的是权限位，不是 os.access（root 下恒真、受 ACL 影响）。
    * 整个「读 → 改 → 写」窗口对目标文件加排他锁（fcntl.flock），并且**加锁之后才读内容**：
      多 agent 并发推进同一份 SPEC 时，后到的进程会读到前面的结果，状态转移逐条追加而不是互相覆盖。
    * 拿不到锁不永久阻塞：等待约 10 秒后退出码 2，提示"另一个进程正在写这份 SPEC，请稍后重试"。
    * 平台没有 fcntl（非 Unix）时降级为不加锁，只打印一条提示，不报错。

退出码：
    0 = 成功（写盘完成且自检没有新 error；--dry-run 正常结束也是 0）
    1 = 已写入，但自检发现新 error（例如 --force 强行推进）——文件已落盘，但状态不可信
    2 = 读取/解析失败、回读校验不通过、写入失败，或等锁超时（都不写文件）
    3 = 用法错误、前置条件不满足，或目标是只读文件且没加 --force（都不写文件）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - 非 Unix 平台：降级为不加锁
    fcntl = None

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    raise SystemExit(2)

import validate_spec as vs  # noqa: E402  与校验器共用同一套门槛判定

VALIDATE_PY = HERE / "validate_spec.py"
ALLOWED_TO = ("draft", "ready", "in_progress", "done", "verified", "blocked")
AC_STATUS = ("pass", "fail", "not_run")

# 顶层字段缩进基线：本技能生成的文件都是 spec: 下缩进 2 空格


class _Parser(argparse.ArgumentParser):
    """用法错误统一走退出码 3。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("用法错误：%s\n" % message)
        raise SystemExit(3)


# --------------------------------------------------------------------------
# YAML 文本定向编辑（不重排、不丢注释）
# --------------------------------------------------------------------------

def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _blank_or_comment(line: str) -> bool:
    text = line.strip()
    return text == "" or text.startswith("#")


def detect_field_indent(lines) -> int:
    """找出顶层字段的缩进：有 spec: 包裹就是它 +2，否则取 status/type/... 的最小缩进。"""
    wrapper = None
    for raw in lines:
        m = re.match(r"^([ ]*)spec\s*:\s*(#.*)?$", raw.rstrip("\n").rstrip("\r"))
        if m:
            wrapper = len(m.group(1)) + 2
            break
    cands = []
    pat = re.compile(r"^([ ]*)(?:status|type|name|id|version|updated)\s*:")
    for raw in lines:
        m = pat.match(raw.rstrip("\n").rstrip("\r"))
        if m:
            cands.append(len(m.group(1)))
    if wrapper is not None and wrapper in cands:
        return wrapper
    if cands:
        return min(cands)
    return wrapper if wrapper is not None else 0


def find_key_line(lines, key, indent):
    pat = re.compile(r"^ {%d}%s\s*:(.*)$" % (indent, re.escape(key)))
    for i, raw in enumerate(lines):
        m = pat.match(raw.rstrip("\n").rstrip("\r"))
        if m:
            return i, m.group(1)
    return None


def _is_seq_item(line: str) -> bool:
    """列表项：以 '- ' 开头或单独一个 '-'（含 PyYAML safe_dump 默认的缩进式 block sequence）。"""
    text = line.strip()
    return text == "-" or text.startswith("- ")


def find_block(lines, key, indent):
    """返回 {start, end, head}；end 已回退掉块尾的空白行/纯注释行（它们属于下一个字段）。

    R3(b)：键名后面若接「缩进式」列表项（如 '- date: ...' 与键同缩进，PyYAML safe_dump 默认风格），
    这些行也算本块的内容；否则会把非空块当空块，只替换键名行、把原列表项留在原地 → 非法 YAML。
    """
    found = find_key_line(lines, key, indent)
    if not found:
        return None
    i, head = found
    key_has_inline = bool(head.strip())
    j = i + 1
    while j < len(lines):
        line = lines[j].rstrip("\n").rstrip("\r")
        if line.strip() and not _blank_or_comment(line) and _indent_of(line) <= indent:
            if not (not key_has_inline and _is_seq_item(line)):
                break
        j += 1
    end = j
    while end > i + 1 and _blank_or_comment(lines[end - 1]):
        end -= 1
    return {"start": i, "end": end, "head": head.strip(), "indent": indent}


def detect_dash_indent(lines, block, default):
    """已有块里列表项 '-' 的缩进：缩进式与键同级，缩进式（默认风格）是键缩进 +2。"""
    for line in lines[block["start"] + 1:block["end"]]:
        if _blank_or_comment(line):
            continue
        if _is_seq_item(line):
            return _indent_of(line)
        break
    return default


def set_scalar(lines, key, value_text, indent):
    """替换顶层单行字段的值，保留行尾注释与换行符。"""
    found = find_key_line(lines, key, indent)
    if not found:
        raise KeyError(key)
    i, _head = found
    raw = lines[i]
    ending = "\n" if raw.endswith("\n") else ""
    body = raw.rstrip("\n").rstrip("\r")
    m = re.match(r"^(%s%s\s*:\s*)(.*?)(\s+#.*)?$" % (" " * indent, re.escape(key)), body)
    if not m:
        raise ValueError("无法解析 %s 行：%r" % (key, body))
    lines[i] = m.group(1) + value_text + (m.group(3) or "") + ending
    return lines


def block_has_content(lines, block):
    """块下方是否有真正的列表/映射内容行。

    只有「键名单独一行 + 下面有内容」才能安全地在块尾追加条目；
    写成行内形式（status_log: [] 或 follow_ups: [] # 注释）或空块，都必须整块替换，
    否则会在 [] 后面塞进缩进列表项，生成非法 YAML。
    """
    for line in lines[block["start"] + 1:block["end"]]:
        if not _blank_or_comment(line):
            return True
    return False


def replace_block(lines, block, new_lines):
    lines[block["start"]:block["end"]] = new_lines
    return lines


def insert_lines(lines, index, new_lines):
    """R3(a)：插到某一行后面时先保证那一行以换行结尾，否则新行会被拼到末行 → 非法 YAML
    （文件末尾没有换行是很常见的写法）。"""
    if index > 0 and lines[index - 1] and not lines[index - 1].endswith("\n"):
        lines[index - 1] = lines[index - 1] + "\n"
    lines[index:index] = new_lines
    return lines


def insert_after_block(lines, key, indent, new_lines):
    block = find_block(lines, key, indent)
    if not block:
        return None
    insert_lines(lines, block["end"], new_lines)
    return lines


_PLAIN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "none", "y", "n", "~"}


def scalar(value) -> str:
    """把值序列化成 YAML 标量；字符串一律双引号转义（json.dumps 的转义对 YAML 双引号同样合法）。"""
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    if _PLAIN_RE.match(text) and text.lower() not in _RESERVED:
        return text
    return json.dumps(text, ensure_ascii=False)


def emit_status_log_entry(entry, dash_indent):
    """dash_indent = 列表项 '-' 的缩进：缩进式写 key_indent+2，缩进式写 key_indent。"""
    dash = " " * dash_indent
    field = " " * (dash_indent + 2)
    return [
        "%s- date: %s\n" % (dash, scalar(entry.get("date"))),
        "%sfrom: %s\n" % (field, scalar(entry.get("from"))),
        "%sto: %s\n" % (field, scalar(entry.get("to"))),
        "%sby: %s\n" % (field, scalar(entry.get("by"))),
        "%sversion: %s\n" % (field, scalar(entry.get("version"))),
        "%snote: %s\n" % (field, scalar(entry.get("note"))),
    ]


def emit_status_log(entries, key_indent, dash_indent):
    pad = " " * key_indent
    out = ["%sstatus_log:\n" % pad]
    for entry in entries:
        out.extend(emit_status_log_entry(entry, dash_indent))
    return out


def emit_generic_value(key, value, indent, out):
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            out.append("%s%s: {}\n" % (pad, key))
            return
        out.append("%s%s:\n" % (pad, key))
        for k, v in value.items():
            emit_generic_value(str(k), v, indent + 2, out)
    elif isinstance(value, list):
        if not value:
            out.append("%s%s: []\n" % (pad, key))
            return
        out.append("%s%s:\n" % (pad, key))
        for item in value:
            if isinstance(item, dict):
                if not item:
                    out.append("%s  - {}\n" % pad)
                    continue
                first = True
                for k, v in item.items():
                    if first and not isinstance(v, (dict, list)):
                        out.append("%s  - %s: %s\n" % (pad, k, scalar(v)))
                        first = False
                    else:
                        emit_generic_value(str(k), v, indent + 4, out)
                if first:
                    out.append("%s  - {}\n" % pad)
            elif isinstance(item, list):
                out.append("%s  - []\n" % pad)
            else:
                out.append("%s  - %s\n" % (pad, scalar(item)))
    else:
        out.append("%s%s: %s\n" % (pad, key, scalar(value)))


def emit_verification(ver, indent):
    pad = " " * indent
    out = ["%sverification:\n" % pad]
    out.append("%s  result: %s\n" % (pad, scalar(ver.get("result", ""))))
    out.append("%s  verified_by: %s\n" % (pad, scalar(ver.get("verified_by", ""))))
    out.append("%s  verifier: %s\n" % (pad, scalar(ver.get("verifier", ""))))
    out.append("%s  verified_at: %s\n" % (pad, scalar(ver.get("verified_at", ""))))
    acc = ver.get("acceptance") if isinstance(ver.get("acceptance"), list) else []
    if acc:
        out.append("%s  acceptance:\n" % pad)
        for item in acc:
            if isinstance(item, dict):
                out.append("%s    - criterion: %s\n" % (pad, scalar(item.get("criterion", ""))))
                out.append("%s      status: %s\n" % (pad, scalar(item.get("status", ""))))
                out.append("%s      evidence: %s\n" % (pad, scalar(item.get("evidence", ""))))
            else:
                out.append("%s    - criterion: %s\n" % (pad, scalar(item)))
                out.append("%s      status: %s\n" % (pad, scalar("not_run")))
                out.append("%s      evidence: %s\n" % (pad, scalar("")))
    else:
        out.append("%s  acceptance: []\n" % pad)
    for key in ("commands", "artifacts", "unverified"):
        values = ver.get(key) if isinstance(ver.get(key), list) else []
        if values:
            out.append("%s  %s:\n" % (pad, key))
            for value in values:
                if isinstance(value, (dict, list)):
                    emit_generic_value(key, [value], indent + 2, out)
                else:
                    out.append("%s    - %s\n" % (pad, scalar(value)))
        else:
            out.append("%s  %s: []\n" % (pad, key))
    known = {"result", "verified_by", "verifier", "verified_at", "acceptance",
             "commands", "artifacts", "unverified"}
    for key, value in ver.items():
        if key not in known:
            emit_generic_value(str(key), value, indent + 2, out)
    return out


def emit_follow_ups(items, dash_indent):
    dash = " " * dash_indent
    out = []
    for item in items:
        if isinstance(item, dict):
            first = True
            for k, v in item.items():
                if first and not isinstance(v, (dict, list)):
                    out.append("%s- %s: %s\n" % (dash, k, scalar(v)))
                    first = False
                else:
                    emit_generic_value(str(k), v, dash_indent + 2, out)
            if first:
                out.append("%s- {}\n" % dash)
        elif isinstance(item, list):
            out.append("%s- []\n" % dash)
        else:
            out.append("%s- %s\n" % (dash, scalar(item)))
    return out


# --------------------------------------------------------------------------
# 变更计划
# --------------------------------------------------------------------------

def parse_acceptance(raw: str):
    """'AC#3 描述|pass|证据' → (criterion, status, evidence)。"""
    parts = raw.split("|")
    criterion = parts[0].strip()
    status = parts[1].strip() if len(parts) > 1 else "not_run"
    evidence = "|".join(parts[2:]).strip() if len(parts) > 2 else ""
    if status not in AC_STATUS:
        raise ValueError("--acceptance 的第 2 段必须是 %s（收到 %r）：%s"
                         % (" | ".join(AC_STATUS), status, raw))
    if not criterion:
        raise ValueError("--acceptance 缺少验收标准描述：%s" % raw)
    return criterion, status, evidence


def build_plan(spec, args, today):
    status_now = spec.get("status")
    old_version = spec.get("version")
    if not isinstance(old_version, int) or isinstance(old_version, bool) or old_version < 1:
        old_version = 0
    new_version = old_version + 1

    note = args.note or ""
    if args.force:
        note = (note + "（forced：跳过 G1/G2 前置检查）") if note else "forced：跳过 G1/G2 前置检查"

    entries = [e for e in vs.as_list(spec.get("status_log")) if isinstance(e, dict)]
    entry = {"date": today, "from": status_now if status_now else "none", "to": args.to,
             "by": args.by, "version": new_version, "note": note}

    plan = {"status": args.to, "version": new_version, "updated": today,
            "status_log": entries + [entry], "new_entry": entry,
            "verification": None, "follow_ups": None, "blocked_reason": None}

    want_ver = args.to in ("done", "verified") or any(
        [args.result, args.acceptance, args.command, args.artifact, args.unverified,
         args.verify_by, args.verifier])
    if want_ver:
        ver = dict(vs.verification_of(spec))
        if args.result is not None:
            ver["result"] = args.result
        else:
            ver.setdefault("result", "")
        if args.verify_by:
            ver["verified_by"] = args.verify_by
        elif args.to == "done":
            ver["verified_by"] = "self"
        else:
            ver.setdefault("verified_by", "")
        if args.verifier is not None:
            ver["verifier"] = args.verifier
        else:
            ver.setdefault("verifier", "")
        if args.to in ("done", "verified"):
            ver["verified_at"] = today
        else:
            ver.setdefault("verified_at", "")
        acc = [a for a in vs.as_list(ver.get("acceptance")) if isinstance(a, dict)]
        for raw in (args.acceptance or []):
            criterion, status, evidence = parse_acceptance(raw)
            replaced = False
            for j, item in enumerate(acc):
                if item.get("criterion") == criterion:
                    acc[j] = {"criterion": criterion, "status": status, "evidence": evidence}
                    replaced = True
                    break
            if not replaced:
                acc.append({"criterion": criterion, "status": status, "evidence": evidence})
        ver["acceptance"] = acc
        for key, values in (("commands", args.command), ("artifacts", args.artifact),
                            ("unverified", args.unverified)):
            current = list(vs.as_list(ver.get(key)))
            for value in (values or []):
                if value not in current:
                    current.append(value)
            ver[key] = current
        plan["verification"] = ver

    if args.follow_up:
        fups = list(vs.as_list(spec.get("follow_ups")))
        fups.extend(str(x) for x in args.follow_up)
        plan["follow_ups"] = fups
        plan["new_follow_ups"] = [str(x) for x in args.follow_up]

    if args.to == "blocked" and args.reason:
        plan["blocked_reason"] = args.reason
    return plan


def simulated_spec(spec, plan):
    out = dict(spec)
    out["status"] = plan["status"]
    out["version"] = plan["version"]
    out["updated"] = plan["updated"]
    out["status_log"] = plan["status_log"]
    if plan["verification"] is not None:
        out["verification"] = plan["verification"]
    if plan["follow_ups"] is not None:
        out["follow_ups"] = plan["follow_ups"]
    if plan["blocked_reason"] is not None:
        out["blocked_reason"] = plan["blocked_reason"]
    return out


def compute_unmet(spec, plan, args, target, label):
    """返回 ([(gate, message)], 模拟推进后的 spec)：进入 target 还差什么。"""
    cli_unmet = []
    if target in ("done", "verified"):
        if not args.note:
            cli_unmet.append(("G2", "缺少 --note（status_log 要写清这次为什么算完成，例如 \"3 项 AC 全过，单测 44 passed\"）"))
        if not args.result:
            cli_unmet.append(("G2", "缺少 --result（verification.result 用于写结论）"))
    if target == "blocked" and not args.reason:
        cli_unmet.append(("G4", "缺少 --reason（blocked_reason 要写清卡在哪、需要什么才能继续）"))
    if target == "verified":
        if not args.verify_by:
            cli_unmet.append(("G3", "缺少 --verify-by independent|user（verified 必须由独立复核者或用户确认；自查只能标 done）"))
        if not args.verifier:
            cli_unmet.append(("G3", "缺少 --verifier（写清是谁复核的：agent 名 / 人名）"))
    if target == "done" and args.verify_by and args.verify_by != "self":
        cli_unmet.append(("G2", "--to done 时 --verify-by 只能是 self；需要独立复核请用 --to verified"))

    sim = simulated_spec(spec, plan)
    gate_unmet = [(g, t) for g, _s, t in vs.prereq_findings(sim, target, label=label)]

    # --acceptance 按需必需：文件里已经写好、且结构合格的逐条结论就不必重打一遍；
    # 只有真缺（文件里没有 + 命令行也没给）时才要求传，并说清是哪一种缺法。
    existing_acc = vs.as_list(vs.verification_of(spec).get("acceptance"))
    sim_acc = vs.as_list(vs.verification_of(sim).get("acceptance"))
    acceptance_gap = target in ("done", "verified") and not args.acceptance and vs.is_blank(sim_acc)
    if acceptance_gap:
        if args.result:
            cli_unmet.append(("G2", "你给了 --result，但没给逐条 AC 结论：verification.acceptance 还是空的。"
                              "用 --acceptance \"AC#1 描述|pass|证据\" 逐条补（可重复传），"
                              "或者先手写进 YAML 的 verification.acceptance（每项 {criterion, status, evidence}）再重跑。"))
        elif vs.is_blank(existing_acc):
            cli_unmet.append(("G2", "verification.acceptance 完全没写：文件里没有逐条验收结论，--acceptance 也没传。"
                              "用 --acceptance \"AC#1 描述|pass|证据\" 逐条补（可重复传）。"))
        else:
            acceptance_gap = False   # 写了但条目不合格：交给下面逐条门槛报具体哪条不行
    if acceptance_gap:
        gate_unmet = [u for u in gate_unmet if "verification.acceptance 为空" not in u[1]]

    # 上面 CLI 层已经点名缺哪个参数，这里去掉同义的派生报错，避免一条毛病报两遍
    if not args.result:
        gate_unmet = [u for u in gate_unmet if "verification.result 为空" not in u[1]]
    if not args.reason:
        gate_unmet = [u for u in gate_unmet if "blocked_reason 为空" not in u[1]]
    if not args.verify_by:
        gate_unmet = [u for u in gate_unmet if "verification.verified_by" not in u[1]]
    if not args.verifier:
        gate_unmet = [u for u in gate_unmet if "verification.verifier 为空" not in u[1]]

    deduped, seen = [], set()
    for gate, text in cli_unmet + gate_unmet:
        if (gate, text) in seen:
            continue
        seen.add((gate, text))
        deduped.append((gate, text))
    return deduped, sim


# --------------------------------------------------------------------------
# 写盘
# --------------------------------------------------------------------------

def apply_edits(text, plan):
    """定向文本编辑，返回 (new_text, changes)。"""
    lines = text.splitlines(keepends=True)
    orig_last = lines[-1] if lines else None  # R4：判断末尾原本有没有换行
    indent = detect_field_indent(lines)
    changes = []

    # 1) 顶层单行字段：status / version / updated
    for key, value in (("status", plan["status"]),
                       ("version", plan["version"]),
                       ("updated", plan["updated"])):
        found = find_key_line(lines, key, indent)
        if found:
            set_scalar(lines, key, scalar(value), indent)
            changes.append("替换顶层 %s 行 → %s" % (key, scalar(value)))
        else:
            anchor = "spec:" if "spec:" in text else None
            new_line = "%s%s: %s\n" % (" " * indent, key, scalar(value))
            if anchor:
                for i, raw in enumerate(lines):
                    if re.match(r"^[ ]*spec\s*:", raw):
                        insert_lines(lines, i + 1, [new_line])
                        break
            else:
                insert_lines(lines, 0, [new_line])
            changes.append("新增顶层 %s 行 → %s" % (key, scalar(value)))

    # 2) status_log：整块替换 / 追加一条 / 按锚点插入（锚点 = status 行之后）
    block = find_block(lines, "status_log", indent)
    if block is None:
        new_block = emit_status_log(plan["status_log"], indent, indent + 2)
        if insert_after_block(lines, "status", indent, new_block) is None:
            insert_lines(lines, len(lines), new_block)
        changes.append("新增 status_log（%d 条）" % len(plan["status_log"]))
    elif not block_has_content(lines, block):
        replace_block(lines, block, emit_status_log(plan["status_log"], indent, indent + 2))
        changes.append("填充空的 status_log（%d 条）" % len(plan["status_log"]))
    else:
        # R3(b)：沿用已有块的列表缩进风格（缩进式 / 缩进式），不要混两种
        dash = detect_dash_indent(lines, block, indent + 2)
        insert_lines(lines, block["end"], emit_status_log_entry(plan["new_entry"], dash))
        changes.append("status_log 追加 1 条（%s → %s，version %s，列表缩进 %d）"
                       % (plan["new_entry"]["from"], plan["new_entry"]["to"],
                          plan["new_entry"]["version"], dash))

    # 2.5) blocked_reason：--to blocked --reason 时写入（没有这一行就按锚点插入）
    if plan["blocked_reason"] is not None:
        if find_key_line(lines, "blocked_reason", indent):
            set_scalar(lines, "blocked_reason", scalar(plan["blocked_reason"]), indent)
            changes.append("替换顶层 blocked_reason 行")
        else:
            new_line = "%sblocked_reason: %s\n" % (" " * indent, scalar(plan["blocked_reason"]))
            if insert_after_block(lines, "status", indent, [new_line]) is None:
                insert_lines(lines, 0, [new_line])
            changes.append("新增顶层 blocked_reason 行 → %s" % scalar(plan["blocked_reason"]))

    # 3) verification：整块替换，或插到 status_log 之后
    if plan["verification"] is not None:
        block = find_block(lines, "verification", indent)
        new_block = emit_verification(plan["verification"], indent)
        if block is None:
            if insert_after_block(lines, "status_log", indent, new_block) is None:
                insert_lines(lines, len(lines), new_block)
            changes.append("新增 verification（result + %d 条 acceptance）"
                           % len(plan["verification"].get("acceptance") or []))
        else:
            replace_block(lines, block, new_block)
            changes.append("更新 verification（result + %d 条 acceptance）"
                           % len(plan["verification"].get("acceptance") or []))

    # 4) follow_ups：追加 / 整块替换 / 插入
    if plan["follow_ups"] is not None:
        block = find_block(lines, "follow_ups", indent)
        if block is None:
            new_block = ["%sfollow_ups:\n" % (" " * indent)] + emit_follow_ups(plan["follow_ups"], indent + 2)
            if insert_after_block(lines, "verification", indent, new_block) is None and \
                    insert_after_block(lines, "status_log", indent, new_block) is None:
                insert_lines(lines, len(lines), new_block)
            changes.append("新增 follow_ups（%d 条）" % len(plan["follow_ups"]))
        elif not block_has_content(lines, block):
            replace_block(lines, block, ["%sfollow_ups:\n" % (" " * indent)]
                          + emit_follow_ups(plan["follow_ups"], indent + 2))
            changes.append("填充 follow_ups（%d 条）" % len(plan["follow_ups"]))
        else:
            new_items = plan.get("new_follow_ups") or []
            if new_items:
                dash = detect_dash_indent(lines, block, indent + 2)
                insert_lines(lines, block["end"], emit_follow_ups(new_items, dash))
            changes.append("follow_ups 追加 %d 条" % len(new_items))

    new_text = "".join(lines)
    # R4：行尾风格保持原样（CRLF 文件不要被整体转成 LF，否则 git diff 会显示整份重写）
    nl_total = text.count("\n")
    crlf_total = text.count("\r\n")
    if nl_total and crlf_total == nl_total:
        new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
    # R4：原本末尾没有换行、且最后一行仍是原文那一行 → 保持没有换行
    if not text.endswith("\n") and orig_last is not None and lines and lines[-1] is orig_last:
        if new_text.endswith("\r\n"):
            new_text = new_text[:-2]
        elif new_text.endswith("\n"):
            new_text = new_text[:-1]
    return new_text, changes


def verify_written(new_text, plan):
    """写盘前回读校验：解析后的值必须是预期值，否则中止且不写。"""
    try:
        data = yaml.safe_load(new_text)
    except Exception as exc:  # noqa: BLE001
        return ["新内容不是合法 YAML（生成逻辑有 bug，未写文件）：%s" % exc]
    spec = data.get("spec", data) if isinstance(data, dict) else None
    if not isinstance(spec, dict):
        return ["回读失败：新内容不是 YAML 映射"]
    problems = []
    if spec.get("status") != plan["status"]:
        problems.append("status 回读为 %r，预期 %r" % (spec.get("status"), plan["status"]))
    if spec.get("version") != plan["version"]:
        problems.append("version 回读为 %r，预期 %r" % (spec.get("version"), plan["version"]))
    if str(spec.get("updated")) != str(plan["updated"]):
        problems.append("updated 回读为 %r，预期 %r" % (spec.get("updated"), plan["updated"]))
    log = [e for e in vs.as_list(spec.get("status_log")) if isinstance(e, dict)]
    if not log or log[-1].get("to") != plan["status"] or log[-1].get("version") != plan["version"]:
        problems.append("status_log 末条回读为 %r，预期 to=%r version=%r"
                        % (log[-1] if log else None, plan["status"], plan["version"]))
    if plan["verification"] is not None:
        ver = spec.get("verification")
        if not isinstance(ver, dict):
            problems.append("verification 回读失败（不是映射）")
        else:
            if plan["verification"].get("result") and ver.get("result") != plan["verification"]["result"]:
                problems.append("verification.result 回读为 %r" % (ver.get("result"),))
            if len(vs.as_list(ver.get("acceptance"))) != len(plan["verification"].get("acceptance") or []):
                problems.append("verification.acceptance 回读条数 %d，预期 %d"
                                % (len(vs.as_list(ver.get("acceptance"))),
                                   len(plan["verification"].get("acceptance") or [])))
    if plan["follow_ups"] is not None:
        if len(vs.as_list(spec.get("follow_ups"))) != len(plan["follow_ups"]):
            problems.append("follow_ups 回读条数 %d，预期 %d"
                            % (len(vs.as_list(spec.get("follow_ups"))), len(plan["follow_ups"])))
    if plan["blocked_reason"] is not None and spec.get("blocked_reason") != plan["blocked_reason"]:
        problems.append("blocked_reason 回读为 %r，预期 %r"
                        % (spec.get("blocked_reason"), plan["blocked_reason"]))
    return problems


def atomic_write(path: Path, text: str, backup: bool):
    # R4：mkstemp 建出来是 600，写完要恢复原文件权限（644 别变成 600）
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        mode = None
    if backup:
        shutil.copy2(str(path), str(path) + ".bak")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".spec-status-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def self_check(path: Path):
    """写完自动跑一次 validate_spec.py（子进程），返回 (errors, warnings, checks, raw)。"""
    proc = subprocess.run([sys.executable, str(VALIDATE_PY), str(path), "--json"],
                          capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except Exception:  # noqa: BLE001
        return None, None, None, {"stdout": proc.stdout, "stderr": proc.stderr,
                                  "returncode": proc.returncode}
    return data.get("errors", []), data.get("warnings", []), data.get("checks", []), data


# --------------------------------------------------------------------------
# 并发锁（R8.2）与只读保护（R8.1）
# --------------------------------------------------------------------------

LOCK_TIMEOUT_SECONDS = 10.0   # 拿不到锁时的有限等待
LOCK_POLL_SECONDS = 0.05


def acquire_file_lock(path: Path, timeout=LOCK_TIMEOUT_SECONDS):
    """R8.2：对目标文件加排他锁，覆盖整个「读 → 改 → 写」窗口。

    返回 (fd, error)：error 为 None 表示加锁成功；"timeout" 等待超时；
    "unsupported" 平台没有 fcntl（降级为不加锁）；"open-failed" 文件打不开。

    关键点：加锁之后还要确认锁住的正是 path 当前指向的 inode。写盘用 os.replace 会换 inode，
    否则后到的进程会拿着旧 inode 的锁去读旧内容，等于没锁。
    """
    if fcntl is None:
        return None, "unsupported"
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return None, "open-failed"
        if time.monotonic() >= deadline:
            os.close(fd)
            return None, "timeout"
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        os.close(fd)
                        return None, "timeout"
                    time.sleep(LOCK_POLL_SECONDS)
            info_fd = os.fstat(fd)
            try:
                info_path = os.stat(str(path))
            except FileNotFoundError:
                info_path = None
            if info_path is not None and (info_fd.st_dev, info_fd.st_ino) == \
                    (info_path.st_dev, info_path.st_ino):
                return fd, None
            os.close(fd)  # inode 被别的进程换过：重新打开、重新加锁
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise


def read_locked(path: Path, lock_fd):
    """R8.2：加锁之后才读内容（后到的进程要读到前一个进程写好的结果）。"""
    if lock_fd is not None:
        os.lseek(lock_fd, 0, os.SEEK_SET)
        chunks = []
        while True:
            chunk = os.read(lock_fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    return path.read_bytes()


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv=None):
    parser = _Parser(description="推进 SPEC 状态并收尾（原子命令）")
    parser.add_argument("path", help="SPEC YAML 文件路径")
    parser.add_argument("--to", required=True, choices=ALLOWED_TO,
                        help="目标状态：%s" % " | ".join(ALLOWED_TO))
    parser.add_argument("--by", default=os.environ.get("USER") or "agent",
                        help="谁推进的（写成 status_log.by），默认取 $USER")
    parser.add_argument("--note", help="状态转移说明（done/verified 必填）")
    parser.add_argument("--reason", help="blocked 原因（--to blocked 必填）")
    parser.add_argument("--result", help="verification.result：一句话结论 + 关键数字")
    parser.add_argument("--acceptance", action="append", metavar="描述|pass|证据",
                        help="逐条验收结论，可重复传；第 2 段必须是 %s" % " | ".join(AC_STATUS))
    parser.add_argument("--command", action="append", help="实际跑过的命令与结果，可重复传")
    parser.add_argument("--artifact", action="append", help="日志 / 报告 / 截图路径，可重复传")
    parser.add_argument("--unverified", action="append", help="明确没验的部分 + 原因，可重复传")
    parser.add_argument("--follow-up", action="append", dest="follow_up",
                        help="遗留问题（写清优先级与触发条件），可重复传")
    parser.add_argument("--verify-by", choices=("self", "independent", "user"),
                        help="verification.verified_by；--to verified 必填")
    parser.add_argument("--verifier", help="复核者标识（agent 名 / 人名）；--to verified 必填")
    parser.add_argument("--force", action="store_true", help="跳过前置门槛检查（仍照常记录 status_log）")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="只打印将要做的事，不写文件")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--backup", action="store_true", help="写盘前先存 <file>.bak")
    args = parser.parse_args(argv)

    if args.to == "verified" and args.verify_by == "self":
        parser.error("--to verified 不能用 --verify-by self：自查只能标 done；"
                     "独立复核用 independent，用户确认用 user。")
    try:
        for raw in (args.acceptance or []):
            parse_acceptance(raw)
    except ValueError as exc:
        parser.error(str(exc))

    path = Path(args.path)
    lock_fd, lock_err = acquire_file_lock(path)
    if lock_err == "timeout":
        sys.stderr.write("另一个进程正在写这份 SPEC，请稍后重试（已等待约 %.0f 秒仍未拿到锁）\n"
                         % LOCK_TIMEOUT_SECONDS)
        return 2
    if lock_err == "open-failed":
        sys.stderr.write("无法读取 %s：文件不存在或打不开\n" % args.path)
        return 2
    if lock_err == "unsupported":
        sys.stderr.write("提示：当前环境不支持文件锁（fcntl 不可用），"
                         "并发推进同一份 SPEC 可能丢更新。\n")
    try:
        return run_locked(path, args, lock_fd)
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)  # 关闭 fd 即释放 flock
            except OSError:
                pass


def run_locked(path, args, lock_fd):
    """R8.2：整个「读 → 改 → 写」窗口都在排他锁内，加锁之后才读文件内容。"""
    try:
        raw = read_locked(path, lock_fd)
        # R4：用 bytes 解码，避免 universal newlines 把 CRLF 吃掉（否则写回会整体转成 LF）
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write("无法读取 %s：%s\n" % (args.path, exc))
        return 2
    try:
        spec = vs.load_spec(text)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("YAML 解析失败：%s\n" % exc)
        return 2

    # R8.1：只读文件（权限位一个写位都没有）默认拒绝，--force 才强推
    try:
        file_mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        file_mode = None
    readonly = file_mode is not None and (file_mode & 0o222) == 0
    if readonly and args.dry_run:
        sys.stderr.write("提示：目标文件是只读的（mode %s），真正写入会被拒绝，除非加 --force。\n"
                         % oct(file_mode)[2:])
    elif readonly and not args.force:
        readonly_msg = ("目标文件是只读的（mode %s）。确认要改就先 chmod +w；"
                        "确实要强推就加 --force。" % oct(file_mode)[2:])
        if args.json:
            print(json.dumps({"ok": False, "path": str(path), "from": spec.get("status"),
                              "to": args.to, "version": None, "changes": [],
                              "unmet": [{"gate": "R8.1", "message": readonly_msg}],
                              "readonly": True, "dry_run": False},
                             ensure_ascii=False, indent=2))
        else:
            print(readonly_msg)
        return 3

    today = date.today().isoformat()
    status_now = spec.get("status")
    plan = build_plan(spec, args, today)

    unmet, sim = compute_unmet(spec, plan, args, args.to, str(path))
    skipped = []
    if unmet and args.force:
        skipped = unmet
        unmet = []

    if unmet:
        if args.json:
            print(json.dumps({"ok": False, "path": str(path), "from": status_now, "to": args.to,
                              "version": plan["version"], "changes": [], "unmet":
                              [{"gate": g, "message": m} for g, m in unmet],
                              "unmet_text": ["%s: %s" % (g, m) for g, m in unmet],
                              "dry_run": bool(args.dry_run)}, ensure_ascii=False, indent=2))
        else:
            print("✗ 不能推进到 %s，还差 %d 项：" % (args.to, len(unmet)))
            for gate, message in unmet:
                print("  - %s: %s" % (gate, message))
            print("  （--force 可跳过检查，但仍会照常记录 status_log）")
        return 3

    try:
        new_text, changes = apply_edits(text, plan)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("生成新内容失败，未写文件：%s\n" % exc)
        return 2
    problems = verify_written(new_text, plan)
    if problems:
        sys.stderr.write("回读校验不通过，已中止且未写文件：\n")
        for p in problems:
            sys.stderr.write("  - %s\n" % p)
        return 2

    if args.dry_run:
        if args.json:
            print(json.dumps({"ok": True, "path": str(path), "from": status_now, "to": args.to,
                              "version": plan["version"], "changes": changes, "unmet": [],
                              "skipped": ["%s: %s" % (g, m) for g, m in skipped],
                              "dry_run": True, "written": False}, ensure_ascii=False, indent=2))
        else:
            print("（dry-run，不写文件）%s：%s → %s，version %s"
                  % (path, status_now, args.to, plan["version"]))
            for c in changes:
                print("  - %s" % c)
            for gate, message in skipped:
                print("  ! --force 跳过的门槛 %s: %s" % (gate, message))
        return 0

    pre_errors = vs.validate(spec, label=str(path))[0]
    try:
        atomic_write(path, new_text, args.backup)
    except OSError as exc:
        sys.stderr.write("写入失败，原文件未改动：%s\n" % exc)
        return 2

    post_errors, post_warnings, post_checks, raw = self_check(path)
    new_errors = []
    if post_errors is None:
        sys.stderr.write("自检脚本执行异常（退出码 %s）：%s\n"
                         % (raw.get("returncode"), (raw.get("stderr") or "").strip()))
    else:
        new_errors = [e for e in post_errors if e not in pre_errors]

    if args.json:
        print(json.dumps({
            "ok": not new_errors, "path": str(path), "from": status_now, "to": args.to,
            "version": plan["version"], "changes": changes, "unmet": [],
            "skipped": ["%s: %s" % (g, m) for g, m in skipped],
            "dry_run": False, "written": True, "backup": bool(args.backup),
            "self_check": {"errors": post_errors if post_errors is not None else [],
                           "warnings": post_warnings or [],
                           "new_errors": new_errors},
        }, ensure_ascii=False, indent=2))
    else:
        print("SPEC 状态推进：%s" % path)
        print("  %s → %s（version %s → %s，updated %s）"
              % (status_now, args.to, spec.get("version"), plan["version"], today))
        for c in changes:
            print("  - %s" % c)
        for gate, message in skipped:
            print("  ! --force 跳过的门槛 %s: %s" % (gate, message))
        if args.backup:
            print("  原文件已备份到 %s.bak" % path)
        print("  已原子写入（临时文件 + os.replace）")
        print("[自检] python3 scripts/validate_spec.py %s --json" % path)
        if post_errors is None:
            print("  自检脚本执行异常，请手工跑一次 validate_spec.py")
        else:
            print("  结果：%s（%d error / %d warning）"
                  % ("FAIL" if post_errors else "PASS", len(post_errors), len(post_warnings)))
            for e in post_errors[:10]:
                print("  ✗ %s" % e)
            for w in post_warnings[:10]:
                print("  ⚠ %s" % w)
        if new_errors:
            print("⚠ 注意：这次推进引入了 %d 条新的 error，状态可能不可信，请先修："
                  % len(new_errors))
            for e in new_errors:
                print("  ✗ %s" % e)

    return 1 if new_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
