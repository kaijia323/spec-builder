---
name: spec-builder
description: "把模糊的任务需求转成结构化、可执行、可验收的 SPEC（任务规格 / 执行规范 / 执行契约）。先判定 spec 类型（feature 新功能、bugfix 缺陷修复、refactor 重构、research 调研、ops 运维），再按类型补全字段，最多反问 3 个澄清问题，产出 Markdown + YAML 规格并用校验脚本自检。当用户提到 SPEC、任务规格、执行规范、需求说明、验收标准、Agent 任务说明、执行契约、修 bug、缺陷、报错、异常、复现、回归、hotfix、根因、定位、修复方案、重构、调研、部署时使用。即使用户没有明说 SPEC，只要在为 Agent 的规划、执行或验收准备任务说明，也应使用本 Skill。"
---

# SPEC Builder（任务规格生成器）

把一段自然语言需求，变成一份人和 Agent 都能照着执行、并能照着验收的 SPEC。

SPEC 是**执行契约**：规划时读它、执行时按它做、验收时拿 `acceptance_criteria` 逐条核对。一份好的 SPEC 让执行者不必反复回来问，也让验收者不必凭感觉判断“做没做完”。

## 核心原则

1. **先分类，再动笔。** 需求类、缺陷类、重构类的 SPEC 关注点完全不同。类型判错，后面全错。
2. **验收标准必须可验证。** 不要写“功能正常”“体验流畅”，要写能复现、能跑出通过/失败结论的句子。这是整份 SPEC 里最重要的部分。
3. **缺信息先问，但只问阻塞项。** 只问真正阻塞、且无法合理假设的问题；能合理假设的，写进 SPEC 并标注为假设。
4. **最小完整。** 字段够用就好，不要为填模板堆废话——空话会稀释真正的约束。
5. **写清“不做什么”。** 明确边界（`not_affected`、`out_of_scope`）往往比多写三条需求更能防止返工。
6. **诚实标注不确定。** 根因没确认就写没确认，需求有歧义就列出歧义。假装确定是最危险的。
7. **沿用用户的术语。** 用户怎么说就怎么记，不要自作主张换一套名词。

## 流程

### 第 0 步：判定 spec 类型

| 类型 | 什么时候用 | 核心问题 |
|---|---|---|
| `feature` | 要新增能力、改变行为 | 要做什么新东西 |
| `bugfix` | 期望行为 ≠ 实际行为 | 什么坏了、为什么坏、怎么证明修好了 |
| `refactor` | 外部行为不变，内部结构要改 | 怎么改而不改变行为 |
| `research` | 方案未定，先调研再决策 | 要回答什么问题，据此做什么决策 |
| `ops` | 部署、监控、故障处理、变更 | 改什么、风险是什么、怎么回滚 |

混合任务（例如“先调研再实现”）按主类型写，并在 `steps` 里体现其它类型的产出。拿不准时问用户一句，不要猜。

容易混淆时：

- **性能回归**（原来快、现在慢）→ `bugfix`；**不知道瓶颈在哪** → 先 `research`，定位后再开 `bugfix`。
- **重构时顺手修 bug** → 若“外部行为不变”是硬约束就用 `refactor`，把 bug 场景写进 `behavior_contract` 与回归用例；否则按 `bugfix` 处理。
- **安全漏洞** → `bugfix`（`severity: critical`），证据里写清可利用路径。
- **新功能顺带改变旧行为** → `feature`，把被改变的行为写进 `constraints` 或验收标准。

### 第 1 步：抽取已知信息

从用户原话和历史上下文里尽量榨出：目标、输入、输出、约束、失败处理、验收标准、相关文件/接口、环境与版本。先复用用户已经给出的原话和术语。

### 第 2 步：澄清（最多 3 个问题）

只有当缺失信息会实质改变 SPEC 的结论时才提问。高价值的问题通常是：

- 输出要有确定格式或 schema 吗？（没有它，验收无从谈起）
- 这个改动会碰哪些系统/文件？有没有绝对不能碰的部分？
- 有没有可复现的输入、日志或环境？
- 成功/失败如何判定？谁来做最终验收？

能合理假设的，用“假设：……”写进 SPEC 并放进 `assumptions` 或 `open_questions`，不要用一连串问题打断用户。

### 第 3 步：按模板生成 SPEC

1. 读取对应模板：`templates/<type>.yaml`。
2. 逐字段填充。没有信息的字段写 “TBD” 或留空，**不要删字段**——校验脚本会指出来。
3. 至少补一个真实示例到 `examples`（简短即可，能说明输入→输出即可）。
4. 长表格、字段定义放到正文说明里，不要塞进 YAML。

### 第 4 步：自检

运行本 Skill 目录下的校验脚本，按报错补全：

```bash
python3 <skill-dir>/scripts/validate_spec.py <spec-file>   # <skill-dir> = 本 Skill 目录（skill_resources 的 base directory）
```

用户只粘贴了 SPEC 正文、没有文件时，先把正文写到临时文件再校验。

### 第 5 步：输出

- 用 **Markdown 说明 + YAML 规格**两部分回复；YAML 放在代码块里，或写入文件。
- **输出位置**：写入**用户当前打开的项目根目录**（harness 工作区根目录，即会话的 `pwd`）下的 `specs/` 文件夹，文件名为 `<id>.yaml`；`specs/` 不存在就先创建。
  - 这里的 `specs/` 是**项目里的**，不是本 Skill 目录里的；技能自带的 `templates/`、`scripts/`、`references/` 才位于技能目录。
  - 判断项目根目录：以 harness 当前工作目录为准；若用户显式给了路径，以用户为准。
  - **安全边界**：若当前工作目录看起来就是技能安装目录（例如 `~/.agents/skills` 或 `~/.agents/skills/<skill-name>`），说明项目路径不明确——先问用户项目在哪或让其指定输出路径，**不要**把 SPEC 写进技能目录。
- 结尾列出：假设、`open_questions`，以及需要用户拍板的地方。

## 各类型要点

### feature
必填：`goal`、`inputs`、`outputs`、`constraints`、`steps`、`acceptance_criteria`、`failure_handling`。
验收标准尽量写成“输入 X → 期望输出 Y”或 Given/When/Then。`outputs.schema` 能用 JSON Schema 或字段表就写清楚。

### bugfix
必填：`symptom`、`environment`、`reproduction`、`evidence`、`scope`、`root_cause`、`fix`、`regression_tests`、`acceptance_criteria`、`failure_handling`。
最关键的是**能证明“原来会坏、现在不坏”**：
1. 原复现步骤不再复现；
2. 根因被解释清楚，而不是只盖住症状；
3. 回归测试通过；
4. 没有引入新问题；
5. 改动范围可控，`scope.not_affected` 写清。
如果 `root_cause.confirmed: false`，`fix` 应先给定位/验证方案，而不是直接改代码。

### refactor
必填：`goal`、`current_state`、`motivation`、`scope`、`behavior_contract`、`steps`、`rollback`、`acceptance_criteria`。
`behavior_contract` 明确列出重构前后必须保持一致的外部行为；验收重点是“行为不变 + 测试通过 + 结构目标达成”。

### research
必填：`question`、`background`、`methods`、`deliverables`、`decision_criteria`、`timebox`。
产出不是代码，而是“结论 + 依据 + 建议方案”。写清什么证据能支撑什么决策。

### ops
必填：`goal`、`target`、`changes`、`risks`、`rollback`、`monitoring`、`acceptance_criteria`、`failure_handling`。
必须能在出问题时回滚，且回滚步骤可执行。监控指标要写清阈值和观察窗口。

## 验收标准怎么写

好：`用户删除 localStorage 中的 token 后点击“个人中心”，1 秒内跳转到登录页，且不再出现 401 卡死`——可复现、可判定。

坏：`修复登录问题`、`功能正常`、`体验流畅`、`代码整洁`。

可验证的线索：具体输入、具体输出、具体错误、具体阈值、命令、测试名，以及“通过/失败/返回/包含/不再”这类能判定的词。

## 输出格式

```yaml
spec:
  type: feature | bugfix | refactor | research | ops
  name: 任务名称
  id: <type>-<slug>            # 稳定标识，后续引用/更新/审查都用它
  version: 1                   # 每次实质修改 +1
  updated: YYYY-MM-DD
  status: draft | ready | in_progress | done | blocked
  related: []                  # issue / PR / 事故 / 监控链接
  goal: 最终目标（一句话）
  context: 背景与上下文
  assumptions: []              # 明确写出的假设
  blocking_questions: []       # 回答前不能开工的问题（非空时 status 不能是 ready）
  open_questions: []           # 可并行确认、不阻塞开工
  inputs: []
  outputs:
    format: 输出格式
    schema: 可选 schema
  constraints: []
  tools: []
  steps: []
  acceptance_criteria: []
  failure_handling: []
  examples: []
```

各类型的完整字段见 `templates/`；字段含义与填写标准见 `references/spec-field-guide.md`；可参考 `examples/` 里的成品。

## 公共元字段与就绪规则

每个 SPEC 都要有：

- `id`：稳定标识，格式 `<type>-<短横线 slug>`，例如 `bugfix-coupon-expired-500`。引用、更新、代码审查都靠它。
- `version`：整数，从 1 开始；每次实质修改 +1。
- `updated`：最后更新日期（YYYY-MM-DD）。
- `related`：相关 issue / PR / 事故 / 监控链接，没有就留空数组。
- `blocking_questions`：**回答前不能开工**的问题；与 `open_questions`（可并行确认、不阻塞）分开写。

**就绪门槛**：`status: ready` 仅当 `blocking_questions` 为空时成立。带着未决阻塞问题标 ready，执行者会在实现到一半时才发现要返工——这比多问一句代价大得多。校验脚本会拒绝 `ready` + 非空 `blocking_questions` 的组合。

**验收标准覆盖**：除可验证外，正式 SPEC 的验收标准要覆盖三类路径——正常、边界（空/上限/并发/幂等）、失败（异常/超时/权限/5xx）。只写正常路径的规格，等于把失败处理留给执行者猜。

## 自检清单

- [ ] 类型判定正确，且用了对应模板
- [ ] 目标清晰、可衡量
- [ ] 输入明确（数据、文件、接口、环境）
- [ ] 输出有格式或 schema
- [ ] 约束、权限、边界写清
- [ ] 至少一条“不做什么”的边界
- [ ] 每条验收标准都可验证，无“正常/合理/流畅”这类词
- [ ] bugfix 的验收能证明“原来会坏、现在不坏”，并有回归测试
- [ ] 失败/重试/回滚/转人工策略已定义
- [ ] 至少一个输入→输出示例
- [ ] 假设和未决问题已列出，且阻塞问题与普通问题分开
- [ ] 有稳定 `id`、`version`、`updated`
- [ ] `status: ready` 时 `blocking_questions` 为空
- [ ] 验收标准覆盖正常、边界、失败三类路径
- [ ] 校验脚本无 error
- [ ] SPEC 文件已写入**当前项目根目录**下的 `specs/` 文件夹（不是技能目录）

## 与执行循环集成

- **规划前**：执行者先读 SPEC，确认 `acceptance_criteria` 可执行；有疑问就问，不要默默改需求。
- **执行中**：新发现写回 `evidence` / `open_questions`。需求变了，先改 SPEC 再改代码。
- **验收时**：逐条核对 `acceptance_criteria`，每条给通过/失败和证据，不用“基本完成”含糊过去。
- **维护已有 SPEC**：`id` 不变，`version` +1，更新 `updated`；已解决的问题从 `blocking_questions` / `open_questions` 移走，并把结论写进 `context` 或验收标准，不要只删问题。
- **代码审查**：`code-review` 这类 Skill 可以把本 SPEC 作为“Spec”一轴的输入。
