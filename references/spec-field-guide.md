# SPEC 字段填写指南

本文件解释 `spec-builder` 模板里各字段的含义、填写标准和常见错误。SKILL.md 放流程，这里放细节。生成或校验 SPEC 时不确定某字段怎么填，就来这里查。

## 通用字段

### type
必填。`feature | bugfix | refactor | research | ops` 之一。判据：

- 期望行为 ≠ 实际行为 → `bugfix`
- 要新增可观察的能力 → `feature`
- 只改内部结构、外部行为不变 → `refactor`
- 方案未定，先要结论 → `research`
- 部署 / 监控 / 变更 / 故障 → `ops`

### name
必填。短、可识别，能在一堆任务里一眼认出来，例如“用户列表导出 Excel”。

### id
必填。稳定标识，格式 `<type>-<小写短横线 slug>`，例如 `bugfix-coupon-expired-500`。id 一旦确定就不要改：引用、更新、代码审查都靠它定位同一份规格。

### version
必填。整数，从 1 开始；每次实质修改 +1。

### updated
必填。最后更新日期，格式 YYYY-MM-DD。

### related
可空数组。相关 issue / PR / 事故 / 监控链接，把“这份规格从哪来”留下痕迹。

### status
必填。六选一，逐级递进：

| status | 含义 | 进入条件 |
|---|---|---|
| `draft` | 草稿 | 默认；**还有问题没问过用户时只能停在这里** |
| `ready` | 就绪 | 阻塞问题都已答复，且没有 `status: open` 的普通问题 |
| `in_progress` | 进行中 | 同上，且已有人开工 |
| `done` | 已完成（待复核） | 执行者自查完成，`verification` 写全 |
| `verified` | 已验证 | 独立复核者或用户本人确认通过 |
| `blocked` | 受阻 | `blocked_reason` 写清卡在哪 |

`done` 与 `verified` 必须分开：前者是干活的人自己说完成了，后者是别人确认过。只有 `verified` 才算闭环。验收没过就退回 `in_progress`。

状态值写错（例如 `shipped`、`completed`）是 **error**，不是提醒——状态是这份 SPEC 的结论，不能含糊。

### status_log
必填（新建 SPEC 时可以是空数组，之后由 `spec_status.py` 追加）。每次状态转移加一条，不要覆盖历史：

```yaml
status_log:
  - date: "2026-09-23"
    from: in_progress     # 第一次从无到有写 none
    to: done
    by: impl-agent        # 谁推进的
    version: 3            # 转移后的 version
    note: "3 项 AC 全过，44 项测试通过"
```

末条的 `to` 必须等于当前的 `status`，`version` 必须等于当前的 `version`——否则说明有人手改了状态没留痕，校验会报错。看板上的“N 天没动过”也是靠它算的。

### blocked_reason
`status: blocked` 时必填。写清卡在哪、卡在谁身上、需要什么才能继续。不要写“等确认”这种等于没说的话。

### blocking_questions
可空数组（标 `done` 时必须为空）。**回答前不能开工**的问题：

```yaml
blocking_questions:
  - q: "单个导出文件上限多少 MB？"
    answered: true
    asked_at: "2026-09-23"
    answer: "50 MB，超了就分批"    # 用户原话
```

与 `open_questions` 的分工：会影响实现方向的放这里（答复前不能标 `ready`），其余放 `open_questions`。注意 `answered` 默认是 false——**写下来不等于问过了**。

### goal
必填。一句话说清最终目标，可衡量。避免“优化系统”这类没有终点的目标。

### context
必填。为什么要做、涉及哪些系统/文件、相关的历史决策。执行者靠它建立正确的心智模型。

### assumptions
把“你没问、但按常理假设了”的事写出来。执行者据此判断要不要回来确认。没有就留空数组，不要编。

### open_questions
需要用户拍板、但不挡开工的问题。**关键：`status: open` 的意思是“这条还没问过用户”**——所以任何 `ready` / `in_progress` / `done` / `verified` 的 SPEC 里都不允许存在 `open`。

```yaml
open_questions:
  - q: "历史周没有数据，要不要一次性回填？"
    status: answered        # open | answered | assumed
    asked_at: "2026-09-23"
    answer: "不回填，旧周按 0 处理"   # answered 时必填，用用户原话

  - q: "要不要顺带给阶段贡献加一条飘字提示？"
    status: assumed
    assumption: "按不做处理，保持静默入账"
    if_wrong: "用户其实想要提示，需要再发一次小版本"
    confirm_by: "发版前让用户在测试服确认一次"
```

三种状态的填写要求：

- `open`：还没问过用户。只能出现在 `draft` 里。
- `answered`：问过了，`answer` 填用户原话。不要转述成自己的判断——原话是以后吵架时的依据。
  **`answer` 不能空**：写个 `answered` 但没有原话会被校验拦下，因为那等于"声称问过了"却拿不出证据。
- `assumed`：用户说过“你先按你的想法做”，或者这条实在次要。**`assumption` / `if_wrong` / `confirm_by` 三个都要填**，等于把风险和回头确认的时机写在明面上。交付时要把 `assumed` 的条目念给用户听。

纯字符串写法（旧格式）会被当成 `status: open`，也就是“问都没问过”——这是故意的，用来暴露历史遗留。

### acceptance_criteria
整份 SPEC 最重要的字段。每条都要能被独立判定通过/失败。写法：

- 具体输入 → 具体输出：“筛选 status=active → 导出行全部为 active”。
- 具体阈值：“30 秒内出现任务”“2 秒内提示”。
- 具体错误 / 状态码 / 命令 / 测试名。
- 至少覆盖：正常路径、边界、失败路径。

反例：`功能正常`、`体验流畅`、`代码优雅`、`尽量快`。

### failure_handling
每条写 `scenario` + `handling`。handling 从这些里选：重试、降级、回滚、告警、转人工、中止并报告。没有失败处理的任务默认“出问题没人管”。

### examples
至少一个输入→输出示例。不用很长，能说明契约即可。

### verification
`status: done` / `verified` 时必填——这是“做完了”的凭证，也是唯一安放验收结论的地方。

```yaml
verification:
  result: "11/11 AC 通过；服务端 2 suites / 262 passed"   # 一句话结论 + 关键数字
  verified_by: self          # self | independent | user
  verifier: ""               # 复核者标识；verified 时必填
  verified_at: "2026-09-22"
  acceptance:
    - criterion: "AC#3 空筛选返回 400"
      status: pass           # pass | fail | not_run
      evidence: "pnpm test -- export.spec.ts -> 12 passed"
  commands:
    - "pnpm --filter server test -> 2 suites / 262 passed"
  artifacts:
    - "tmp/verify-report.md"
  unverified:
    - "AC#11 需发布后 24h 观察测试服真实数据"
```

填写要求：

- `verified_by: self` 表示执行者自查，只能配 `done`。
- `status: verified` 必须由 `independent`（独立复核者）或 `user`（用户本人）来标，且 `verifier` 非空。
- `acceptance` 要**逐条**对应 `acceptance_criteria`：条数不能少于验收标准（想合并就先把 AC 合并），标 `pass`/`fail` 的必须给 `evidence`。写“基本都过了”等于没写。
- 标了 `not_run` 的条目要同时出现在 `unverified` 里，说明为什么没验、什么时候补。
- 有 `fail` 项时不能标 `verified`；确实要带着已知问题发布，就留在 `done`，把失败项写进 `unverified` 与 `follow_ups`。
- `research` 类型的 `verification` 放结论与依据即可，`commands` 可以留空。

**不要自创字段名。** 校验器会识别这些常见漂移并提示改回标准字段：
`implementation` / `acceptance_evidence` / `field_evidence` / `result` / `verified` → `verification`；
`known_p2` / `remaining` / `issues` → `follow_ups`。

### follow_ups
可空数组。这次没做完、或做完才发现的事，每条写清优先级和触发条件：

```yaml
follow_ups:
  - "F1（中）：重试后结算文档 participants 偏小，弹窗不受影响；下次改结算时分母落库时一起修。"
  - "F5：本次未部署测试服，发布后按 AC#11 观察一次真实数据。"
```

写在对话里、或写成“已知问题”四个字，下一个人都找不到。

## feature 专属字段

- `goal`：新能力的最终目标。
- `inputs`：每项写清 `name / description / source / required`。source 要具体到文件、API、用户输入还是数据库。
- `outputs`：`format` 必填（文件类型 / 接口 / 数据结构）；`schema` 能用 JSON Schema 或字段表；`path` 写产出落点。
- `constraints`：技术、时间、依赖、权限、合规限制。
- `out_of_scope`：明确不做什么，防止范围蔓延。
- `tools`：允许使用的工具 / 接口，便于执行者选择。
- `steps`：建议步骤，不是死板脚本，但要能照着走。

## bugfix 专属字段

- `severity`：`low | medium | high | critical`。决定优先级，不影响修复内容。
- `symptom`：用户能观察到的现象，用用户的语言。
- `environment`：版本、系统、运行时、账号、配置。复现的前提。
- `reproduction`：`steps / expected / actual / frequency` 四件套。steps 要能被人照着一步步做出来。
- `evidence`：日志、网络、截图、堆栈、相关文件，每条带 `detail` 和 `location`。
- `scope.affected / not_affected`：影响面与**明确不受影响**的部分。
- `root_cause`：`hypothesis / evidence / confirmed`。`confirmed: false` 时，`fix` 必须先给定位/验证方案，不要直接猜着改。
- `fix`：`approach / files / constraints / alternatives_considered`。constraints 通常包含“最小改动”“不引入新依赖”。
- `regression_tests`：修复后必须重跑的场景，覆盖正常、原缺陷、相邻功能。

**bugfix 的验收标准必须能证明“原来会坏、现在不坏”**，至少覆盖：原复现步骤不再复现、根因被解释、回归测试通过、无新问题、改动范围可控。

## refactor 专属字段

- `current_state`：现状与痛点，最好带上具体文件/位置。
- `motivation`：为什么值得重构，不重构会怎样。
- `behavior_contract`：**外部行为不变的清单**，重构的验收锚点。用户看得到的行为、API、事件、数据格式都算。
- `rollback`：如何安全回退。
- 验收重点：行为不变 + 测试通过 + 结构目标达成。

## research 专属字段

- `question`：要回答的核心问题，一次一个。
- `hypotheses`：先写下候选答案，调研才有方向。
- `methods`：调研 / 实验方法（读文档、压测、POC、对比实验）。
- `deliverables`：结论报告、选型建议、POC、决策记录。
- `decision_criteria`：什么证据支持什么决策，避免“调完再说”。
- `timebox`：时间盒。调研容易发散，必须有个截止。

## ops 专属字段

- `target`：环境、服务、区域。
- `changes`：具体变更项。
- `risks`：每条写 `risk / likelihood / impact / mitigation`。
- `rollback`：触发条件 + 可执行步骤。**没有回滚方案的变更不允许上线。**
- `monitoring`：指标、阈值、观察窗口、异常时动作。
- 验收重点：变更生效 + 指标达标 + 出问题能按预案回滚。

## 校验门槛对照表

`validate_spec.py` 的报错信息里带门槛编号，对照这张表看：

| 编号 | 检查什么 | 违反时 |
|---|---|---|
| `G0` | type 合法；status 是六个取值之一 | error |
| `G1` | `ready`/`in_progress`：阻塞问题都已答复**且带用户答复原话**（`answer` 非空），且没有没问过的普通问题 | error |
| `G2` | `done`/`verified`：`blocking_questions` 为空、`verification` 写全、`acceptance` 条数不少于 `acceptance_criteria` 且 `pass`/`fail` 必须带 `evidence`、问题全部结清、`status_log` 末条与当前状态一致 | error |
| `G3` | `verified`：验证人不是执行者本人，`verifier`/`verified_at` 非空，没有 `fail` 项 | error |
| `G4` | `blocked`：`blocked_reason` 非空 | error |
| `G5` | `status_log` 末条的 `to`/`version` 与当前值一致；缺 `status_log` 的老 SPEC 只提醒 | error / warning |
| `G6` | 顶层出现非标准字段（字段漂移） | warning |
| `G7` | `ready`/`in_progress` 且状态超过 `--stale-days`（默认 14）天没动 | warning |
| `G8` | 原有结构检查：必填字段、验收标准可验证性、类型专属字段等 | error / warning |

体检历史 SPEC 时用 `--lenient`，它会把 `G1`~`G5` 降级为提醒，只看结构和字段健康度。

## 验收标准对照表

| 弱 | 强 |
|---|---|
| 功能正常 | 输入 X，返回 200，响应体包含字段 Y |
| 修复登录问题 | 原复现步骤不再出现 401，且 1 秒内跳转登录页 |
| 性能优化 | P95 从 800ms 降到 200ms 以内（100 并发压测） |
| 代码整洁 | 6 个重复的流转判断收敛为 1 个状态机模块，单测覆盖率 ≥ 80% |
| 体验流畅 | 首屏可交互时间 ≤ 2s（3G 网络模拟） |
