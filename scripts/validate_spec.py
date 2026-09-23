#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 SPEC 文件是否符合 spec-builder 的结构要求。

用法：
    python3 validate_spec.py specs/feature-export.yaml
    python3 validate_spec.py - < spec.yaml
    python3 validate_spec.py spec.yaml --json
    python3 validate_spec.py specs/*.yaml            # 批量体检
    python3 validate_spec.py --lenient old/specs/*.yaml   # 历史语料：G1~G5 降级为 warning

退出码：0 = 无 error；1 = 有 error；2 = 读取或解析失败；3 = 用法错误。

门槛编号 G0~G8（与 assets/specs.html 的 JS 实现一一对应，两侧注释都带编号）：
    G0 类型与枚举合法 + 基础结构/质量检查（改造前老校验器的全部检查都归到 G0）
    G1 可以开工：status ∈ {ready, in_progress} 时 blocking_questions 逐条 answered=true、
       open_questions 无 status=open（纯字符串 = 还没问过用户）
    G2 完成必须有据：status ∈ {done, verified} 时 G1 成立 + blocking_questions 为空 +
       verification.result 非空 + verification.acceptance 非空且每项有 criterion/status +
       open_questions 全是 answered 或（assumed 且 if_wrong/confirm_by 非空）+
       status_log 非空时末条 to == 当前 status
    G3 已验证要有人：status=verified 时 verified_by ∈ {independent, user}、verifier 与
       verified_at 非空、acceptance 里没有 fail
    G4 受阻要说原因：status=blocked 时 blocked_reason 非空
    G5 状态要留痕：status_log 非空时末条 to == status、末条 version == version；
       status_log 缺失或为空且 status != draft → warning（老语料友好）
    G6 字段不要漂移：未知顶层字段 → warning，并给出标准字段名与常见别名映射
    G7 状态别放烂：status ∈ {ready, in_progress} 且最后状态日期距今超过 --stale-days → warning
    G8 就绪门槛：原「ready + blocking_questions 非空」的检查已被 G1 取代（语义更强），
       不再单独报出门槛号，仅在 JS/Python 注释里保留编号对照。

--json 兼容约定（后来者不要“顺手统一”成对象数组，会破坏老消费方）：
    1. valid / type / errors / warnings / checks 五个字段名与语义保持不变；
    2. errors 与 warnings 仍然是「字符串数组」，每条以 “G2: ” 这样的门槛号开头；
    3. 需要结构化消费时用新增的 error_items / warning_items =
       [{"gate": "G2", "message": "..."}]，gate 单独成字段。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    raise SystemExit(2)

KNOWN_TYPES = ("feature", "bugfix", "refactor", "research", "ops")
# G0：status 必须是这六个之一（改造前只有 5 个，且非法只给 warning）
KNOWN_STATUS = ("draft", "ready", "in_progress", "done", "verified", "blocked")
# --lenient 只降级生命周期门槛；G0（结构合法性）与 G6/G7（本来就是 warning）不降级
LIFECYCLE_GATES = ("G1", "G2", "G3", "G4", "G5")
# 进入某个状态必须满足的门槛；spec_status.py 直接复用这张表做前置检查
STATUS_PREREQ_GATES = {
    "draft": (),
    "ready": ("G1",),
    "in_progress": ("G1",),
    "done": ("G1", "G2"),
    "verified": ("G1", "G2", "G3"),
    "blocked": ("G4",),
}

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

# G6 白名单：标准顶层字段（COMMON_REQUIRED + COMMON_PRESENT + META + 各类型模板里合法出现的字段）
META_FIELDS = ("status_log", "verification", "follow_ups", "blocked_reason")
TYPE_OPTIONAL = {
    "feature": ("out_of_scope", "tools", "examples"),
    "bugfix": ("examples", "steps", "severity"),
    "refactor": ("examples", "out_of_scope", "constraints"),
    "research": ("examples", "hypotheses"),
    "ops": ("examples", "constraints", "out_of_scope"),
}
# G6 常见别名映射（只提示，不自动改）：语料里真实出现过的自创字段
FIELD_ALIASES = {
    "implementation": "verification",
    "acceptance_evidence": "verification",
    "field_evidence": "verification",
    "verified": "verification",
    "result": "verification",
    "evidence_result": "verification",
    "known_p2": "follow_ups",
    "issues": "follow_ups",
    "remaining": "follow_ups",
}
NO_STANDARD_FIELD = ("sync_targets", "defects")
STANDARD_FIELD_HINT = ("type/name/id/version/updated/status/context/acceptance_criteria/"
                       "failure_handling/assumptions/blocking_questions/open_questions/"
                       "related/status_log/verification/follow_ups + 该类型的专属字段（见 templates/）")

WEAK_WORDS = ("正常", "合理", "流畅", "完善", "良好", "稳定", "友好", "易用",
              "整洁", "差不多", "尽量", "基本", "优化", "提升体验")

MEASURABLE = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "通过", "返回",
              "包含", "不再", "一致", "等于", "报错", "错误码", "秒", "毫秒",
              "测试", "=", "P95", "覆盖", "提示", "拒绝", "拦截", "限制", "禁止",
              "条", "行", "次", "无")

FAILURE_HINTS = ("失败", "异常", "超时", "错误", "报错", "拒绝", "403", "404",
                 "400", "500", "降级", "回滚", "上限", "为空", "并发", "幂等",
                 "重复", "越权", "重试")

OPEN_Q_STATUS = ("open", "answered", "assumed")
AC_STATUS = ("pass", "fail", "not_run")


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


def spec_cmd(label=None) -> str:
    """把文件名嵌进可执行提示里，例如 python3 scripts/spec_status.py x.yaml。"""
    if not label or label == "<stdin>":
        label = "<spec.yaml>"
    return "python3 scripts/spec_status.py %s" % label


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


# --------------------------------------------------------------------------
# 问题字段归一化（兼容第 3 节：纯字符串 = {q: 字符串, status: open} = 还没问过用户）
# --------------------------------------------------------------------------

# R7：criterion 归一化口径（与 assets/specs.html 的 JS 逐字共用同一套正则字面量）
# PUNCT 用 \xNN 写法，Python 与 JS 都能逐字粘贴（不用 \p{P}，Python 标准库 re 不支持）
CRITERION_PUNCT = (r"[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e"
                   r"\u2000-\u206f\u3000-\u303f\uff00-\uffef]")
CRITERION_TRAILING_PUNCT_RE = re.compile(CRITERION_PUNCT + r"+$")
CRITERION_PUNCT_RE = re.compile(CRITERION_PUNCT)
AC_REF_RE = re.compile(r"AC\s*[#＃]?\s*\d+(\s*[-–~,、]\s*\d+)*", re.IGNORECASE)


def norm_criterion(text) -> str:
    """R7.1 归一化：去首尾空白 → 去内部空白 → 统一小写 → 去尾部标点（连续一串一起删）。"""
    s = str(text).strip()
    s = re.sub(r"\s+", "", s)
    s = s.lower()
    return CRITERION_TRAILING_PUNCT_RE.sub("", s)


def criterion_bare(text) -> str:
    """R7.2 判断「只剩编号」：剥掉 AC#1 / AC1 / AC 1-3 后，再去掉标点与空白。"""
    s = AC_REF_RE.sub("", norm_criterion(text))
    s = CRITERION_PUNCT_RE.sub("", s)
    return re.sub(r"\s+", "", s)


def _answer_type_name(value) -> str:
    """R7.3：报错里说清 answer 实际是什么类型（None 写成 null，与 JS 侧一致）。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def duplicate_key_warnings(text: str):
    """R5：PyYAML 对同层重复键静默取最后一个（js-yaml 会直接报错）。

    用 yaml.compose 遍历节点树找出同层重复键，返回 [(键路径, 行号)]；只告警，不升级成 error
    （老文件里可能有，别把老语料判死）。
    """
    try:
        root = yaml.compose(text)
    except Exception:  # noqa: BLE001  解析失败另有专门的报错路径
        return []
    hits = []

    def walk(node, path):
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key_node, value_node in node.value:
                key = str(key_node.value) if isinstance(key_node, yaml.ScalarNode) else "<非标量键>"
                full = path + key
                if key in seen:
                    hits.append((full, key_node.start_mark.line + 1))
                seen.add(key)
                walk(value_node, full + ".")
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item, path)

    walk(root, "")
    return hits


def norm_blocking(item) -> dict:
    if isinstance(item, str):
        return {"q": item, "answered": False, "data": None, "answer": "", "asked_at": ""}
    if isinstance(item, dict):
        q = item.get("q") or item.get("question") or ""
        return {"q": str(q), "answered": item.get("answered") is True, "data": item,
                "answer": item.get("answer"), "asked_at": item.get("asked_at")}
    return {"q": str(item), "answered": False, "data": None, "answer": "", "asked_at": ""}


def norm_open(item) -> dict:
    if isinstance(item, str):
        return {"q": item, "status": "open", "data": None, "answer": "", "asked_at": ""}
    if isinstance(item, dict):
        q = item.get("q") or item.get("question") or ""
        st = item.get("status")
        if st is None:
            # 老写法只有 answered/answer；答过就算 answered，否则视为没问过
            if item.get("answered") is True or not is_blank(item.get("answer")):
                st = "answered"
            else:
                st = "open"
        return {"q": str(q), "status": str(st), "data": item,
                "answer": item.get("answer"), "asked_at": item.get("asked_at")}
    return {"q": str(item), "status": "open", "data": None, "answer": "", "asked_at": ""}


def verification_of(spec):
    ver = spec.get("verification")
    return ver if isinstance(ver, dict) else {}


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# 门槛检查：check_gN(spec, ...) -> [(gate, severity, text)]
# validate() 与 scripts/spec_status.py 共用这些函数，保证两边判定完全一致。
# --------------------------------------------------------------------------

def check_g1(spec, label=None):
    """G1 可以开工：blocking_questions 全部拿到答复；open_questions 没有 open（含纯字符串项）。

    R1：「问过了」不能是空口白话——answered / answered: true 时必须写 answer 原话，否则 error；
    asked_at 为空只给 warning（提醒补日期，不挡门）。
    """
    out = []
    for i, item in enumerate(as_list(spec.get("blocking_questions")), 1):
        info = norm_blocking(item)
        if not info["answered"]:
            out.append(("G1", "error",
                        "blocking_questions[%d] 还没拿到用户答复：%s。下一步：用提问工具问用户，"
                        "把答复原话写进 blocking_questions[%d].answer 并把 answered 改成 true。"
                        % (i, _short(info["q"]), i)))
        else:
            answer = info["answer"]
            if not isinstance(answer, str):  # R7.3：先判类型（数字/布尔/列表/映射/null 一律 error）
                out.append(("G1", "error",
                            "blocking_questions[%d].answer 必须是字符串（当前是 %s）："
                            "把用户原话写成文本，例如 answer: \"50 MB，超了就分批\"。"
                            % (i, _answer_type_name(answer))))
            elif is_blank(answer):
                out.append(("G1", "error",
                            "blocking_questions[%d] 写了 answered: true，但 answer 是空的："
                            "你说问了用户，那用户原话是什么？把答复原话写进 "
                            "blocking_questions[%d].answer；用户明确说先做时改成 assumed 并填 "
                            "assumption / if_wrong / confirm_by。" % (i, i)))
            if is_blank(info["asked_at"]):
                out.append(("G1", "warning",
                            "blocking_questions[%d] 是 answered 但没写 asked_at（什么时候问的用户）；"
                            "补个日期方便回溯。" % i))
    for i, item in enumerate(as_list(spec.get("open_questions")), 1):
        info = norm_open(item)
        st = info["status"]
        if st == "open":
            out.append(("G1", "error",
                        "open_questions[%d] 仍是 open（= 还没问过用户）：%s。下一步：用提问工具问用户，"
                        "把答复原话写进 open_questions[%d].answer 并把 status 改成 answered；"
                        "用户明确说先做时改成 assumed，并填 assumption / if_wrong / confirm_by。"
                        % (i, _short(info["q"]), i)))
        elif st not in OPEN_Q_STATUS:
            out.append(("G1", "error",
                        "open_questions[%d].status=%r 不是合法取值（%s）。"
                        % (i, st, " | ".join(OPEN_Q_STATUS))))
        elif st == "answered":
            answer = info["answer"]
            if not isinstance(answer, str):  # R7.3：先判类型
                out.append(("G1", "error",
                            "open_questions[%d].answer 必须是字符串（当前是 %s）："
                            "把用户原话写成文本，例如 answer: \"50 MB，超了就分批\"。"
                            % (i, _answer_type_name(answer))))
            elif is_blank(answer):
                out.append(("G1", "error",
                            "open_questions[%d] 写了 status: answered，但 answer 是空的："
                            "你说问了用户，那用户原话是什么？把答复原话写进 "
                            "open_questions[%d].answer；用户明确说先做时改成 assumed 并填 "
                            "assumption / if_wrong / confirm_by。" % (i, i)))
            if is_blank(info["asked_at"]):
                out.append(("G1", "warning",
                            "open_questions[%d] 是 answered 但没写 asked_at（什么时候问的用户）；"
                            "补个日期方便回溯。" % i))
    return out


def check_g2(spec, label=None):
    """G2 完成必须有据：status ∈ {done, verified} 时 G1 成立 + 结论/逐条验收齐备。"""
    out = list(check_g1(spec, label))
    status = spec.get("status")
    cmd = spec_cmd(label)
    blocking = as_list(spec.get("blocking_questions"))
    if not is_blank(blocking):
        infos = [norm_blocking(b) for b in blocking]
        answered_n = sum(1 for info in infos if info["answered"])
        unanswered_n = len(infos) - answered_n
        first = infos[0]
        out.append(("G2", "error",
                    "status=%s 但 blocking_questions 还挂着 %d 条没搬走（已答复 %d 条 / 没答复 %d 条；"
                    "第 1 条：%s，%s）。已答复的把结论落进 context / acceptance_criteria / follow_ups "
                    "后删掉这条；没答复的先回去问用户（用提问工具），拿到答复再搬走。"
                    % (status, len(infos), answered_n, unanswered_n, _short(first["q"]),
                       "已答复" if first["answered"] else "还没拿到用户答复")))
    ver = spec.get("verification")
    if not isinstance(ver, dict):
        out.append(("G2", "error",
                    "status=%s 但没有 verification（或 verification 不是映射）。跑 '%s --to %s "
                    "--by <你> --note '3 项 AC 全过' --result '一句话结论+关键数字' "
                    "--acceptance 'AC#1 描述|pass|证据' 可一次补齐 status/version/updated/"
                    "status_log/verification。" % (status, cmd, status)))
    else:
        if is_blank(ver.get("result")):
            out.append(("G2", "error",
                        "status=%s 但 verification.result 为空。补一句结论+关键数字，例如 "
                        "'11/11 AC 通过，44 项测试全绿'：'%s --to %s --result \"...\"'。"
                        % (status, cmd, status)))
        acc = as_list(ver.get("acceptance"))
        if is_blank(acc):
            out.append(("G2", "error",
                        "status=%s 但 verification.acceptance 为空。逐条对照 acceptance_criteria 写结论："
                        "'%s --to %s --acceptance \"AC#1 描述|pass|命令输出或路径\"'（可重复传）。"
                        % (status, cmd, status)))
        else:
            for i, item in enumerate(acc, 1):
                if not isinstance(item, dict):
                    out.append(("G2", "error",
                                "verification.acceptance[%d] 不是映射；应为 "
                                "{criterion, status, evidence}，status ∈ %s。"
                                % (i, " | ".join(AC_STATUS))))
                    continue
                if is_blank(item.get("criterion")):
                    out.append(("G2", "error",
                                "verification.acceptance[%d].criterion 为空；每条都要写清对应哪条验收标准。"
                                % i))
                if item.get("status") not in AC_STATUS:
                    out.append(("G2", "error",
                                "verification.acceptance[%d].status=%r 非法或缺失；应为 %s。"
                                % (i, item.get("status"), " | ".join(AC_STATUS))))
                # R2：pass/fail 必须有证据；not_run 必须列进 verification.unverified
                item_status = item.get("status")
                if item_status in ("pass", "fail") and is_blank(item.get("evidence")):
                    out.append(("G2", "error",
                                "verification.acceptance[%d] 是 %s 但没有 evidence"
                                "（命令输出 / 路径 / 观测数字）；验收结论必须有据，"
                                "不能只写一个 %s。" % (i, item_status, item_status)))
                if item_status == "not_run" and not is_blank(item.get("criterion")):
                    unverified_text = " ".join(str(u) for u in as_list(ver.get("unverified")))
                    if str(item.get("criterion")) not in unverified_text:
                        out.append(("G2", "warning",
                                    "verification.acceptance[%d] 是 not_run，但没写进 "
                                    "verification.unverified；明确没验的部分要单独列出来"
                                    "（不允许用“基本都过了”含糊过去）。" % i))
            # R7.1 / R7.2：criterion 内容检查（都是 warning——合并结论、跨条引用都是合法写法，不挡门）
            first_seen = {}
            for i, item in enumerate(acc, 1):
                if not isinstance(item, dict) or is_blank(item.get("criterion")):
                    continue
                key = norm_criterion(item.get("criterion"))
                if key:  # 空结果不参与查重（criterion 为空另有 G2 error）
                    if key in first_seen:
                        out.append(("G2", "warning",
                                    "第 %d、%d 条验收结论的 criterion 一模一样，像是复制粘贴；"
                                    "每条 AC 要写它自己的实际结论。" % (first_seen[key], i)))
                    else:
                        first_seen[key] = i
                if len(criterion_bare(item.get("criterion"))) < 2:
                    out.append(("G2", "warning",
                                "第 %d 条验收结论的 criterion 只有编号，看不出验的是什么；"
                                "请写上 AC 的原文或这条的实际结论。" % i))
            # R2：逐条对照要真的逐条（条数与 acceptance_criteria 对齐）
            criteria = criteria_items(spec)
            if criteria:
                if len(acc) < len(criteria):
                    out.append(("G2", "error",
                                "verification.acceptance 只有 %d 条，acceptance_criteria 有 %d 条——"
                                "逐条对照没做全。逐条补上每一条 AC 的结论；确实想合并成一条结论的，"
                                "就把 acceptance_criteria 合并成一条，而不是用一条结论盖住 %d 条标准。"
                                % (len(acc), len(criteria), len(criteria))))
                elif len(acc) > len(criteria):
                    out.append(("G2", "warning",
                                "verification.acceptance 有 %d 条，acceptance_criteria 只有 %d 条；"
                                "多出来的结论可能是验收标准漏写了，回头对一下。"
                                % (len(acc), len(criteria))))
    # open_questions：done/verified 时必须是 answered，或 assumed 且 if_wrong/confirm_by 都填了
    for i, item in enumerate(as_list(spec.get("open_questions")), 1):
        info = norm_open(item)
        st = info["status"]
        data = info["data"] if isinstance(info["data"], dict) else {}
        if st == "open" or st not in OPEN_Q_STATUS:
            continue  # 已经有 G1 的报错，不重复刷屏
        if st == "assumed":
            for field, hint in (("if_wrong", "假设错了会怎样"),
                                ("confirm_by", "最迟什么时候回头确认（步骤或日期）")):
                if is_blank(data.get(field)):
                    out.append(("G2", "error",
                                "open_questions[%d] 是 assumed（知情假设）但缺 %s（%s）；"
                                "用户说先做也要把这三件事写清楚：assumption / if_wrong / confirm_by。"
                                % (i, field, hint)))
            if is_blank(data.get("assumption")):
                out.append(("G2", "warning",
                            "open_questions[%d] 是 assumed 但 assumption 为空；写清按什么假设推进。"
                            % i))
    # done 是自查（verified_by: self）；写了别的复核身份却没走 verified，提示一句
    if status == "done":
        vb = verification_of(spec).get("verified_by")
        if vb not in ("self", "", None):
            out.append(("G2", "warning",
                        "status=done 但 verification.verified_by=%r；done 表示自查（verified_by: self），"
                        "已经有独立复核/用户确认的话请改标 verified。" % (vb,)))
    # status_log 与当前 status 对齐的检查统一放在 check_g5（status=done/verified 时门槛号仍打 G2），
    # 这里不再重复报一次，避免同一条毛病出两条 error。
    return out


def check_g3(spec, label=None):
    """G3 已验证要有人：status=verified 时必须由独立复核者或用户确认，且没有 fail 项。"""
    out = []
    if spec.get("status") != "verified":
        return out
    cmd = spec_cmd(label)
    ver = verification_of(spec)
    vb = ver.get("verified_by")
    if vb not in ("independent", "user"):
        out.append(("G3", "error",
                    "status=verified 但 verification.verified_by=%r；verified 必须由独立复核者或用户"
                    "确认（independent | user），自查只能标 done。跑 '%s --to verified "
                    "--verify-by independent --verifier <复核者>'。" % (vb, cmd)))
    if is_blank(ver.get("verifier")):
        out.append(("G3", "error",
                    "status=verified 但 verification.verifier 为空；写清是谁复核的（agent 名 / 人名）。"))
    if is_blank(ver.get("verified_at")):
        out.append(("G3", "error",
                    "status=verified 但 verification.verified_at 为空；复核日期写 YYYY-MM-DD。"))
    for i, item in enumerate(as_list(ver.get("acceptance")), 1):
        if isinstance(item, dict) and item.get("status") == "fail":
            out.append(("G3", "error",
                        "verification.acceptance[%d] 是 fail（%s）；有失败项不能标 verified："
                        "降级为 done，并把失败项写进 verification.unverified 与 follow_ups。"
                        % (i, _short(str(item.get("criterion", ""))))))
    return out


def check_g4(spec, label=None):
    """G4 受阻要说原因：status=blocked 时 blocked_reason 非空。"""
    if spec.get("status") != "blocked":
        return []
    if is_blank(spec.get("blocked_reason")):
        return [("G4", "error",
                 "status=blocked 但 blocked_reason 为空；写清卡在哪、需要什么才能继续。"
                 "跑 '%s --to blocked --reason \"...\"' 会一并记录原因。" % spec_cmd(label))]
    return []


def check_g5(spec, label=None):
    """G5 状态要留痕：末条 to/version 对齐；缺失或为空只告警（老语料 36 份都没 status_log）。"""
    out = []
    status = spec.get("status")
    entries = [e for e in as_list(spec.get("status_log")) if isinstance(e, dict)]
    if not entries:
        if status in KNOWN_STATUS and status != "draft":
            out.append(("G5", "warning",
                        "没有 status_log（历史 SPEC）。建议补一条最近的状态转移；之后用 '%s --to ...' "
                        "推进状态会自动追加。手工改 status 不留痕，验收时看不出谁在什么时候改的。"
                        % spec_cmd(label)))
        return out
    last = entries[-1]
    if last.get("to") != status:
        gate = "G2" if status in ("done", "verified") else "G5"
        out.append((gate, "error",
                    "status_log 最后一条是 to=%r，与当前 status=%r 不一致；手改 status 不算数。"
                    "用 '%s --to %s --by <你> --note \"...\"' 让脚本同时改 "
                    "status/version/updated/status_log。"
                    % (last.get("to"), status, spec_cmd(label), status)))
    if last.get("version") != spec.get("version"):
        out.append(("G5", "error",
                    "status_log 最后一条 version=%r 与顶层 version=%r 不一致；改状态必须同时 version +1"
                    "（spec_status.py 会自动 +1）。" % (last.get("version"), spec.get("version"))))
    return out


def check_g6(spec, stype):
    """G6 字段不要漂移：未知顶层字段 → warning + 标准字段名/别名提示。"""
    allowed = set(COMMON_REQUIRED) | set(COMMON_PRESENT) | set(META_FIELDS)
    allowed |= set(TYPE_REQUIRED.get(stype, ())) | set(TYPE_OPTIONAL.get(stype, ()))
    out = []
    for key in spec:
        if key in allowed:
            continue
        if key in FIELD_ALIASES:
            out.append(("G6", "warning",
                        "疑似字段漂移：未知顶层字段 %r，标准字段是 %r。把验收结论/证据搬到 %s 里，"
                        "不要自创字段名。" % (key, FIELD_ALIASES[key], FIELD_ALIASES[key])))
        elif key in NO_STANDARD_FIELD:
            out.append(("G6", "warning",
                        "疑似字段漂移：未知顶层字段 %r，没有对应的标准字段；请放进 context 或 scope。"
                        % key))
        else:
            out.append(("G6", "warning",
                        "未知顶层字段 %r。标准字段：%s。" % (key, STANDARD_FIELD_HINT)))
    return out


def check_g7(spec, stale_days=14, label=None):
    """G7 状态别放烂：ready/in_progress 且最后状态日期距今超过 stale_days → warning。"""
    status = spec.get("status")
    if status not in ("ready", "in_progress"):
        return []
    entries = [e for e in as_list(spec.get("status_log")) if isinstance(e, dict)]
    when = entries[-1].get("date") if entries else None
    source = "status_log 末条 date"
    if is_blank(when):
        when = spec.get("updated")
        source = "updated（没有 status_log）"
    day = parse_date(when)
    if day is None:
        return []
    days = (date.today() - day).days
    if days <= stale_days:
        return []
    cmd = spec_cmd(label)
    return [("G7", "warning",
             "status=%s 但最后一次状态变动是 %s（%s，%d 天前，阈值 %d 天）；确认是「做完了没改状态」"
             "还是卡住了——做完立刻跑 '%s --to done ...'，卡住则 '%s --to blocked --reason \"...\"'。"
             % (status, day.isoformat(), source, days, stale_days, cmd, cmd))]


def _short(text, limit=60) -> str:
    text = str(text).replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def prereq_findings(spec, target_status, label=None):
    """spec_status.py 用的前置检查：进入 target_status 还差哪些门槛（只看 error）。"""
    funcs = {"G1": check_g1, "G2": check_g2, "G3": check_g3, "G4": check_g4}
    out, seen = [], set()
    for gate in STATUS_PREREQ_GATES.get(target_status, ()):
        for item in funcs[gate](spec, label):
            if item[1] != "error":
                continue
            key = (item[0], item[2])
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


# --------------------------------------------------------------------------
# 主校验流程
# --------------------------------------------------------------------------

def _split(findings, checks, lenient):
    errors, warnings = [], []
    for gate, sev, text in findings:
        if lenient and gate in LIFECYCLE_GATES and sev == "error":
            sev = "warning"
        line = "%s: %s" % (gate, text)
        bucket = errors if sev == "error" else warnings
        if line not in bucket:
            bucket.append(line)
    return errors, warnings, checks


def validate(spec: dict, *, lenient: bool = False, stale_days: int = 14, label=None):
    """校验一份 SPEC，返回 (errors, warnings, checks)。

    兼容说明：函数名、返回值形状与改造前一致（三个 list），新增参数都有默认值。
    """
    findings, checks = [], []
    cmd = spec_cmd(label)
    stype = spec.get("type")
    status = spec.get("status")

    # ---------- G0 类型与枚举合法 ----------
    if status not in KNOWN_STATUS:
        findings.append(("G0", "error",
                         "status 非法或缺失：%r；必须是 %s 之一（status 写错现在是 error，不再是 warning）。"
                         "用 '%s --to draft --by <你> --note \"建档\"' 可自动补上 "
                         "status/version/updated/status_log。"
                         % (status, "/".join(KNOWN_STATUS), cmd)))
    else:
        checks.append("status = %s" % status)

    if stype not in KNOWN_TYPES:
        findings.append(("G0", "error", "type 缺失或非法：%r；应为 %s" % (stype, "/".join(KNOWN_TYPES))))
        # 类型不明 → 后续类型相关检查无从下手，与改造前一致：直接结束
        return _split(findings, checks, lenient)
    checks.append("type = %s" % stype)

    # ---------- G0 基础结构（老校验器的检查，全部归入 G0） ----------
    for field in COMMON_REQUIRED + TYPE_REQUIRED.get(stype, ()):
        if field not in spec:
            findings.append(("G0", "error", "缺少必填字段：%s" % field))
        elif is_blank(spec.get(field)):
            findings.append(("G0", "error", "必填字段为空：%s" % field))

    for field in COMMON_PRESENT:
        if field not in spec:
            findings.append(("G0", "error", "缺少字段（可为空数组）：%s" % field))

    sid = spec.get("id")
    if is_blank(sid):
        findings.append(("G0", "error", "缺少稳定标识 id（格式 <type>-<slug>）"))
    else:
        sid = str(sid)
        if not sid.startswith(str(stype) + "-"):
            findings.append(("G0", "error", "id 应以 %s- 开头：%r" % (stype, sid)))
        elif re.search(r"\s", sid) or re.search(r"[A-Z]", sid):
            findings.append(("G0", "warning", "id 建议全小写、无空格：%r" % sid))
        checks.append("id = %s" % sid)

    version = spec.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        findings.append(("G0", "warning", "version 应为 >= 1 的整数：%r" % version))

    updated = spec.get("updated")
    if not isinstance(updated, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", updated):
        findings.append(("G0", "warning", "updated 应为 YYYY-MM-DD（加引号，避免被解析成日期对象）：%r" % updated))

    for parent, children in NESTED_REQUIRED.get(stype, {}).items():
        node = spec.get(parent)
        if isinstance(node, dict):
            for child in children:
                if is_blank(node.get(child)):
                    findings.append(("G0", "error", "必填子字段为空：%s.%s" % (parent, child)))

    criteria = criteria_items(spec)
    if not criteria:
        findings.append(("G0", "error", "acceptance_criteria 为空或缺失"))
    else:
        checks.append("acceptance_criteria = %d 条" % len(criteria))
        for i, item, word in weak_criteria(criteria):
            findings.append(("G0", "warning",
                             "第 %d 条验收标准疑似不可验证（含“%s”且无量化线索）：%s" % (i, word, item)))
        if stype in ("feature", "refactor", "ops") and len(criteria) < 3:
            findings.append(("G0", "warning",
                             "验收标准偏少（%d 条）；建议覆盖正常、边界、失败路径" % len(criteria)))
        text = " ".join(criteria)
        if not any(h in text for h in FAILURE_HINTS):
            findings.append(("G0", "warning",
                             "验收标准似乎只覆盖正常路径；建议补充边界（空/上限/并发）与失败（异常/超时/权限）路径"))

    if not as_list(spec.get("examples")):
        findings.append(("G0", "warning", "没有 examples；建议至少补一个输入→输出示例"))

    if stype == "bugfix":
        root = spec.get("root_cause") or {}
        fix = spec.get("fix") or {}
        if isinstance(root, dict) and root.get("confirmed") is False and isinstance(fix, dict) \
                and not is_blank(fix.get("approach")):
            findings.append(("G0", "warning",
                             "root_cause.confirmed 为 false；fix 应先包含定位/验证步骤，不要直接改代码"))
        text = " ".join(criteria)
        if criteria and not any(k in text for k in ("复现", "回归", "不再", "原")):
            findings.append(("G0", "warning",
                             "bugfix 验收标准建议包含“原复现步骤不再出现”或“回归测试通过”"))

    if stype == "refactor":
        bc = as_list(spec.get("behavior_contract"))
        if bc and len(bc) < 2:
            findings.append(("G0", "warning",
                             "behavior_contract 至少列出 2 条必须保持不变的外部行为"))

    if stype == "ops":
        risks = as_list(spec.get("risks"))
        if risks and any(is_blank(r) for r in risks):
            findings.append(("G0", "warning", "risks 条目不完整"))
        mon = as_list(spec.get("monitoring"))
        if mon and any(is_blank(m) for m in mon):
            findings.append(("G0", "warning", "monitoring 条目不完整"))

    # ---------- G1 / G2 / G3 / G4 ----------
    if status in ("ready", "in_progress"):
        findings.extend(check_g1(spec, label))          # G1 可以开工
    if status in ("done", "verified"):
        findings.extend(check_g2(spec, label))          # G2 完成必须有据（内含 G1）
    if status == "verified":
        findings.extend(check_g3(spec, label))          # G3 已验证要有人
    if status == "blocked":
        findings.extend(check_g4(spec, label))          # G4 受阻要说原因

    # ---------- G5 状态要留痕 ----------
    findings.extend(check_g5(spec, label))

    # ---------- G6 字段不要漂移 ----------
    findings.extend(check_g6(spec, stype))

    # ---------- G7 状态别放烂 ----------
    findings.extend(check_g7(spec, stale_days, label))

    if status in ("ready", "in_progress") and not any(
            g == "G1" for g, _s, _t in findings):
        checks.append("G1: 没有未答复的 blocking/open question")
    if status in ("done", "verified") and not any(g == "G2" for g, _s, _t in findings):
        checks.append("G2: verification 结论与逐条验收齐全")
    if status == "verified" and not any(g == "G3" for g, _s, _t in findings):
        checks.append("G3: 复核人/日期齐备且无 fail 项")

    return _split(findings, checks, lenient)


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

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


def structured_items(lines):
    """errors/warnings 的字符串数组 → [{gate, message}]，供 --json 的结构化消费。"""
    items = []
    for line in lines:
        gate, sep, message = line.partition(": ")
        items.append({"gate": gate if sep else "", "message": message if sep else line})
    return items


class _Parser(argparse.ArgumentParser):
    """用法错误统一走退出码 3（argparse 默认是 2，会和“解析失败”撞车）。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("用法错误：%s\n" % message)
        raise SystemExit(3)


def check_path(path, args):
    """校验一个路径，返回结果字典；不抛异常。"""
    if path == "-":
        label, text = "<stdin>", sys.stdin.read()
    else:
        label = path
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {"path": path, "label": label, "read_error": str(exc), "exit_code": 2,
                    "valid": False, "type": None, "errors": [], "warnings": [], "checks": [],
                    "error_items": [], "warning_items": []}
    try:
        spec = load_spec(text)
    except Exception as exc:  # noqa: BLE001
        return {"path": path, "label": label, "read_error": "YAML 解析失败：%s" % exc,
                "exit_code": 2, "valid": False, "type": None, "errors": [], "warnings": [],
                "checks": [], "error_items": [], "warning_items": []}
    errors, warnings, checks = validate(spec, lenient=args.lenient,
                                        stale_days=args.stale_days, label=label)
    for key_path, line_no in duplicate_key_warnings(text):  # R5：重复键只告警
        msg = ("G0: 重复键 %r（第 %d 行）：PyYAML 只取最后一个值，被覆盖的那个不生效，"
               "请删掉多余的那个（查看器用的 js-yaml 会直接拒绝这份文件）。" % (key_path, line_no))
        if msg not in warnings:
            warnings.append(msg)
    return {"path": path, "label": label, "read_error": None, "exit_code": 1 if errors else 0,
            "valid": not errors, "type": spec.get("type"), "errors": errors,
            "warnings": warnings, "checks": checks,
            "error_items": structured_items(errors), "warning_items": structured_items(warnings)}


def main(argv=None):
    parser = _Parser(description="校验 spec-builder 生成的 SPEC")
    parser.add_argument("path", nargs="+", help="SPEC 文件路径（可传多个），或用 - 从 stdin 读取")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--lenient", action="store_true",
                        help="把生命周期门槛 G1~G5 降级为 warning（体检历史语料用）")
    parser.add_argument("--stale-days", type=int, default=14,
                        help="G7 停滞判定天数，默认 14")
    args = parser.parse_args(argv)
    if args.stale_days < 1:
        parser.error("--stale-days 必须是正整数")
    if args.path.count("-") > 1:
        parser.error("stdin（-）只能出现一次")

    results = [check_path(p, args) for p in args.path]
    exit_code = 2 if any(r["exit_code"] == 2 for r in results) else (
        1 if any(r["exit_code"] == 1 for r in results) else 0)

    if args.json:
        if len(results) == 1:
            r = results[0]
            if r["read_error"]:
                # 与改造前一致：读取/解析失败时输出 {"valid": false, "error": ...}
                print(json.dumps({"valid": False, "error": r["read_error"]}, ensure_ascii=False))
            else:
                print(json.dumps({
                    "valid": r["valid"],
                    "type": r["type"],
                    "errors": r["errors"],
                    "warnings": r["warnings"],
                    "checks": r["checks"],
                    "error_items": r["error_items"],
                    "warning_items": r["warning_items"],
                    "path": r["path"],
                    "lenient": bool(args.lenient),
                    "exit_code": r["exit_code"],
                }, ensure_ascii=False, indent=2))
        else:
            files = [{"path": r["path"], "valid": r["valid"], "type": r["type"],
                      "errors": r["errors"], "warnings": r["warnings"], "checks": r["checks"],
                      "error_items": r["error_items"], "warning_items": r["warning_items"],
                      **({"error": r["read_error"]} if r["read_error"] else {})}
                     for r in results]
            print(json.dumps({
                "valid": all(f["valid"] for f in files),
                "files": files,
                "summary": {"files": len(files),
                            "errors": sum(len(f["errors"]) for f in files),
                            "warnings": sum(len(f["warnings"]) for f in files),
                            "read_failures": sum(1 for r in results if r["exit_code"] == 2),
                            "exit_code": exit_code},
            }, ensure_ascii=False, indent=2))
        return exit_code

    for r in results:
        if r["read_error"]:
            sys.stderr.write("无法读取/解析 %s：%s\n" % (r["path"], r["read_error"]))
            continue
        print(render(r["label"], r["type"], r["errors"], r["warnings"], r["checks"]))
        if len(results) > 1:
            print()
    if len(results) > 1:
        total_e = sum(len(r["errors"]) for r in results)
        total_w = sum(len(r["warnings"]) for r in results)
        print("汇总：%d 份 / %d error / %d warning / 退出码 %d"
              % (len(results), total_e, total_w, exit_code))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
