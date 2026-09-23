# spec-builder

把模糊的任务需求转成结构化、可执行、可验收的 SPEC（任务规格 / 执行规范 / 执行契约），用于 Agent 的规划、执行与验收。

支持五种规格类型：`feature`、`bugfix`、`refactor`、`research`、`ops`。

## 一分钟看懂怎么用

1. **写**：照 `templates/<类型>.yaml` 起稿，成品写到**当前项目**的 `specs/<id>.yaml`。
2. **问**：拿不准、需要用户拍板的事，必须真的问出去（一次最多 3 个）。没拿到答复之前，`status` 只能停在 `draft`。
3. **做**：开工时 `spec_status.py --to in_progress`。
4. **收尾**：做完的那一刻 `spec_status.py --to done`，把结论、逐条验收结果、跑过的命令、遗留项一次写全。
5. **复核**：独立复核者或用户本人确认后 `--to verified`——这才算真正闭环。
6. **随时**：`validate_spec.py` 自检，`specs/specs.html` 浏览。

## 状态阶梯（现在有 6 档）

| status | 中文 | 什么时候进 | 谁改 |
|---|---|---|---|
| `draft` | 草稿 | 默认；只要还有问题没问过用户，就停在这里 | 作者 |
| `ready` | 就绪 | 问题都问过了（或写成知情假设），验收标准写全 | 作者 / 用户 |
| `in_progress` | 进行中 | 有人开始动手 | 执行者 |
| `done` | 已完成（待复核） | 执行者**自查**做完，`verification` 写好了 | 执行者 |
| `verified` | 已验证 | **独立复核者或用户本人**确认通过 | 复核者 / 用户 |
| `blocked` | 受阻 | 卡住了，`blocked_reason` 写清卡在哪 | 任何人 |

- `done` 与 `verified` 是两件事：前者是干活的人说做完了（`verified_by: self`），后者是别人确认过。**只有 `verified` 才算闭环**，看板上"待复核"的就是 `done`。
- 允许回退：验收没过就退回 `in_progress`，别口头说一声就算了；回退同样写 `status_log`。
- 每次状态变化都要在 `status_log` 追加一条（谁、何时、从哪到哪、为什么），脚本会自动写。看板上的"N 天没动"就是这么算出来的。

## 必须真的问用户

把问题写进 `open_questions` 不等于问过了。规则是：

- `blocking_questions`：**不问就不能开工**，每条写 `{q, answered, asked_at, answer}`。
- `open_questions`：可以先做但要让用户知情，每条写 `{q, status, asked_at, answer, assumption, if_wrong, confirm_by}`；
  - `status: open` = **还没问过用户**（纯字符串写法也按这个算）→ `ready` 及以上状态一律报错；
  - `status: answered` = 问过了，`answer` 里放**用户原话**；
  - `status: assumed` = 用户说"你先干"，按假设推进——必须同时填 `assumption` / `if_wrong` / `confirm_by` 三个，交付时念给用户听。
- 用户没答复之前 `status` 只能停在 `draft`。

## 做完要收尾（一条命令）

"做完"和"状态改成 done"必须是同一个动作，所以收尾只有一条命令：

```bash
# 执行者自查完成（status → done）
python3 <skill-dir>/scripts/spec_status.py specs/<id>.yaml --to done \
  --by impl-agent \
  --note "3 项 AC 全过，44 项测试通过" \
  --result "11/11 AC 通过；pnpm test 2 suites / 262 passed" \
  --acceptance "AC#1 空筛选返回 400|pass|pnpm test -- export.spec.ts -> 12 passed" \
  --command "pnpm --filter server test -> 2 suites / 262 passed" \
  --unverified "AC#11 需发布后 24h 观察" \
  --follow-up "F1（中）：历史周数据未回填，用户确认后再做"

# 独立复核或用户确认通过（status → verified）
python3 <skill-dir>/scripts/spec_status.py specs/<id>.yaml --to verified \
  --verify-by independent --verifier "verifier-task-3" --result "11/11 AC 复核通过"
```

脚本一次改完 `status` / `status_log` / `version`（+1）/ `updated` / `verification` / `follow_ups`，并且是定向文本编辑（不会丢注释、不会重排字段）。**前置条件不满足时会拒绝执行**并逐条告诉你还差什么；`--force` 能跳过检查，但等于把问题留给下一个读 SPEC 的人，别用。

脚本替不了的三件事：已答复的阻塞问题要把结论落进 `context` / 验收标准并**清空列表**（标 `done` 时必须为空）；没做完的事写进 `follow_ups`；bugfix 的 `root_cause.confirmed` 要改成 `true`。

## 包含内容

- `SKILL.md` — 技能主文件：类型判定、执行流程、状态阶梯、提问与收尾、自检清单。
- `templates/` — 五种类型的填空模板（已含 `status_log` / `verification` / `follow_ups` 与结构化问题字段）。
- `references/spec-field-guide.md` — 字段含义与填写标准。
- `examples/` — 五种类型的成品示例，覆盖整条状态阶梯（见下）。
- `scripts/validate_spec.py` — 校验脚本：结构检查 + 生命周期门槛 `G0`~`G7`，支持 `--json`、`--lenient`。
- `scripts/spec_status.py` — 收尾用的原子命令：改状态、追加 `status_log`、version +1、写入 `verification` 与 `follow_ups`。
- `scripts/ensure_viewer.py` — 在项目 `specs/` 下创建 `specs.html`（仅缺失时，已有不覆盖）。
- `assets/specs.html` — 单文件查看器：读取项目 `specs/` 下所有 YAML，渲染并按 `G0`~`G7` 标出 error / warning。
- `evals/evals.json` — 12 个评测用例、101 条断言。

## 使用

把本目录放到技能加载路径下（例如 `~/.agents/skills/spec-builder/`）。当需求涉及 SPEC、任务规格、修 bug、重构、调研或上线变更，或者"任务做完了/更新规格状态"时触发。

生成的 SPEC 默认写入**用户当前打开的项目根目录**下的 `specs/`（不是技能目录）；技能自身的 `templates/`、`scripts/`、`references/` 仍在技能目录内。

### 校验一份 SPEC

```bash
python3 scripts/validate_spec.py specs/feature-user-export.yaml
python3 scripts/validate_spec.py specs/feature-user-export.yaml --json
python3 scripts/validate_spec.py legacy-specs/*.yaml --lenient   # 体检历史 SPEC，G1~G5 降级为提醒
```

退出码：`0` = 无 error；`1` = 有 error；`2` = 读取或解析失败；`3` = 用法错误。

### 校验器查什么（G0~G7）

| 编号 | 查什么 | 不满足 |
|---|---|---|
| `G0` | 类型/状态取值合法；必填字段与格式（含 `id`、`version`、`updated`、验收标准质量） | error（状态非法以前只是 warning，现在拦下来） |
| `G1` | `ready` / `in_progress`（以及 done / verified）不许有没问过用户的问题；**标了 `answered` 就必须写用户原话**，而且 `answer` 必须是**非空白字符串**（`0` / `false` / 列表 / 映射都拦），只缺 `asked_at` 给提醒——写个 `answered: true` 蒙不过去 | error，点名第几条并告诉你下一步 |
| `G2` | `done` / `verified` 必须有据：`verification.result`、**逐条 `acceptance` 与 `acceptance_criteria` 条数对齐**、**`pass`/`fail` 必须给 `evidence`**、**`not_run` 要列进 `unverified`**、**同一 `criterion` 不能复制粘贴凑数、`criterion` 也不能只剩 `AC#1` 这种编号**、`blocking_questions` 为空、`status_log` 末条对齐 | error（`not_run` 没进 `unverified`、条数多于 AC、criterion 重复或只剩编号都是 warning，不挡门） |
| `G3` | `verified` 的验证人必须是 `independent` 或 `user`，有 `verifier` / `verified_at`，且没有 `fail` 项 | error |
| `G4` | `blocked` 必须写 `blocked_reason` | error |
| `G5` | `status_log` 末条与当前状态、`version` 对得上；缺失且非 draft 只是提醒 | error / warning |
| `G6` | 未知顶层字段（字段漂移），并告诉你标准字段名，如 `implementation` / `verified` → `verification`、`known_p2` → `follow_ups` | warning |
| `G7` | `ready` / `in_progress` 超过 14 天没动（看 `status_log` 末条日期，没有就看 `updated`） | warning |

报错信息都带编号（如 `G2: ...`），方便对照；`--json` 的 `errors` / `warnings` 里每条也带 `gate` 字段。

## 浏览 SPEC

`specs/specs.html` 是一份自包含的查看器（Tailwind CSS v4 + js-yaml，均走 CDN），只读，不修改 SPEC。

创建（缺失时）：

```bash
python3 scripts/ensure_viewer.py <项目根目录>
```

打开方式：

1. **双击 `specs.html`**：页面里点"选择 specs 文件夹"或把 `specs/` 拖入（浏览器不允许 file:// 页面自动读取同目录文件）。
2. **本地服务**：项目根目录运行 `python3 -m http.server 8000`，访问 `http://localhost:8000/specs/specs.html`，自动读取同目录全部 YAML。

查看器里能直接看到：

- 状态徽章六档齐全，`done` 会多标一个**待复核**，`verified` 标**已验证**；
- **N 个问题没问过**（红色）：`open_questions` 里 `status: open` 或纯字符串的条数；
- **N 天没动**（黄色）：`ready` / `in_progress` 且 `status_log` 末条日期距今超过 14 天；
- 详情页有**验收记录**（结论 / 验证人 / 逐条 AC 结果 / 命令 / 没验的部分）和**遗留问题**；`done` / `verified` 却没有验收记录的，直接红字提示"此 SPEC 没有验收记录"；
- `status: assumed` 的知情假设单独列出，提醒交付时要念给用户听；
- 标了"已答复"却没写用户原话、标了 `pass` 却没有证据、逐条对照条数不够（"只对照了 1 / 3 条验收标准"）、`not_run` 没进 `unverified`——这些都会在详情页直接标红/标黄。

支持按类型/状态分组、搜索过滤；验收标准可勾选，**但打勾只存在浏览器本地（localStorage），不会写回 SPEC**——要留下验收结论请用 `spec_status.py`。

## 示例：五种类型 × 状态阶梯

`examples/` 里的五份成品同时演示了字段写法和状态阶梯，并且都通过 `validate_spec.py`（0 error / 0 warning）：

| 文件 | 类型 | status | 演示重点 |
|---|---|---|---|
| `feature-user-export.yaml` | feature | `verified` | 完整 `verification`（结论 / 独立复核人 / 逐条 AC+证据 / 命令 / 未验项）、`open_questions` 的 answered 与 assumed、`follow_ups` |
| `bugfix-coupon-expiry.yaml` | bugfix | `done` | 自查完成待复核：`verified_by: self`、一条 `not_run` + `unverified` 诚实标注 |
| `refactor-order-state.yaml` | refactor | `ready` | 已答复的阻塞问题长什么样、可以开工的状态 |
| `ops-order-service-v3-rollout.yaml` | ops | `in_progress` | 执行中：结论落进 `context` / `rollback` 后清空阻塞问题、留一条 `assumed` |
| `research-detail-cache-choice.yaml` | research | `draft` | 还有问题没问过用户 → 只能停在 draft，不能开工 |

## 评测

`evals/evals.json` 有 12 个用例：前 8 个覆盖五种类型、信息不足需澄清、校验已有 SPEC、查看器安装；新增 4 个专门盯这次改进的三件事：

- **ask-before-ready**：用户没回答问题时，agent 必须真的把问题发给用户并停在 `draft`，不许自问自答；
- **finish-with-verification**：一份 SPEC 收尾后，最终 YAML 必须有 `verification`、`status` 与 `status_log` 都更新、`version` +1；
- **user-reports-done**：用户说"做完了"但没改状态时，agent 要动手收尾（跑 `spec_status.py`），不能只回一句"好的"；
- **field-name-drift**：字段名写错（`verified` / `implementation` / `known_p2`）必须被指出并改回标准字段。

## 设计要点

- **先分类再动笔**：五类规格的关注点不同，类型判错后面全错。
- **能被机器拦住的，不靠记性**：每条规则要么进校验器（`G0`~`G7`），要么有一条原子命令（`spec_status.py`），要么是查看器上的可见标记。
- **状态是结论，verification 是依据**：两者都要有，不允许只写一个。
- **"没问过"和"问过了"必须能区分**：`open` = 没问过，`answered` = 问过了，`assumed` = 知情假设。
- **对老 SPEC 友好**：缺 `status_log` 这类历史问题只告警不判死，`--lenient` 可把生命周期门槛降级为提醒。
- **SPEC 是执行契约**：规划前读它，执行后逐条核对 `acceptance_criteria`。
- **统一 schema 便于机器处理**：稳定 `id`、`version`、`updated`、`related`，可被代码审查与工作流直接引用。
