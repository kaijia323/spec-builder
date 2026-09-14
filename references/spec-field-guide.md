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
必填。`draft`（草稿）→ `ready`（可执行）→ `in_progress` → `done`；卡住用 `blocked`。**只有 `blocking_questions` 为空的 SPEC 才能标 `ready`**，否则执行者会在实现到一半时才发现要返工。

### blocking_questions
可空数组。回答前不能开工的问题。与 `open_questions` 的分工：会影响实现方向的放这里，只是锦上添花的放 `open_questions`。

### goal
必填。一句话说清最终目标，可衡量。避免“优化系统”这类没有终点的目标。

### context
必填。为什么要做、涉及哪些系统/文件、相关的历史决策。执行者靠它建立正确的心智模型。

### assumptions
把“你没问、但按常理假设了”的事写出来。执行者据此判断要不要回来确认。没有就留空数组，不要编。

### open_questions
不阻塞开工、可以并行确认的问题。把不确定性摊开比藏起来安全；但真正会影响实现方向的，要放进 `blocking_questions`。

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

## 验收标准对照表

| 弱 | 强 |
|---|---|
| 功能正常 | 输入 X，返回 200，响应体包含字段 Y |
| 修复登录问题 | 原复现步骤不再出现 401，且 1 秒内跳转登录页 |
| 性能优化 | P95 从 800ms 降到 200ms 以内（100 并发压测） |
| 代码整洁 | 6 个重复的流转判断收敛为 1 个状态机模块，单测覆盖率 ≥ 80% |
| 体验流畅 | 首屏可交互时间 ≤ 2s（3G 网络模拟） |
