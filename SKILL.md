---
name: spec-builder
description: "把模糊的任务需求转成结构化、可执行、可验收的 SPEC（任务规格 / 执行规范 / 执行契约）。先判定 spec 类型（feature 新功能、bugfix 缺陷修复、refactor 重构、research 调研、ops 运维），再按类型补全字段，主动向用户澄清最多 3 个关键问题，产出 Markdown + YAML 规格并用校验脚本自检。也用于推进和收尾已有 SPEC：更新 status、补齐验收结论、做完了改状态。当用户提到 SPEC、任务规格、执行规范、需求说明、验收标准、Agent 任务说明、执行契约、修 bug、缺陷、报错、异常、复现、回归、hotfix、根因、定位、修复方案、重构、调研、部署、任务做完了/更新规格状态时使用。即使用户没有明说 SPEC，只要在为 Agent 的规划、执行或验收准备任务说明，也应使用本 Skill。"
---

# SPEC Builder（任务规格生成器）

把一段自然语言需求，变成一份人和 Agent 都能照着执行、并能照着验收的 SPEC。

SPEC 是**执行契约**：规划时读它、执行时按它做、验收时拿 `acceptance_criteria` 逐条核对。一份好的 SPEC 让执行者不必反复回来问，也让验收者不必凭感觉判断“做没做完”。

## 核心原则

1. **先分类，再动笔。** 需求类、缺陷类、重构类的 SPEC 关注点完全不同。类型判错，后面全错。
2. **验收标准必须可验证。** 不要写“功能正常”“体验流畅”，要写能复现、能跑出通过/失败结论的句子。这是整份 SPEC 里最重要的部分。
3. **该问的一定要问，别替用户拍板。** 把问题写进文件不等于问过了。只问需要用户拍板的事，一次最多 3 个；用户没答复之前不动手。
4. **最小完整。** 字段够用就好，不要为填模板堆废话——空话会稀释真正的约束。
5. **写清“不做什么”。** 明确边界（`not_affected`、`out_of_scope`）往往比多写三条需求更能防止返工。
6. **诚实标注不确定。** 根因没确认就写没确认，需求有歧义就列出歧义。假装确定是最危险的。
7. **沿用用户的术语。** 用户怎么说就怎么记，不要自作主张换一套名词。
8. **状态跟着事实走。** 做完的那一刻就改 `status`，别攒着——状态一旦滞后，看板就没人信了。收尾要改七八个地方，所以有 `scripts/spec_status.py` 一条命令改完；省事，才可能做到及时。
9. **结论要有落点。** 做完的结论、验过的证据、没做的事，各有各的位置（`verification`、`verification.unverified`、`follow_ups`）。全塞进 `context` 或者干脆不写，下一个人就得重新考古。

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

### 第 2 步：澄清（必须真的问用户）

写 SPEC 最容易犯的错，是把该问的问题写进 `open_questions` 就算处理完了——文件里记了一笔，用户却从没看见，执行者只能自己替用户拍板。等用户看到成品才发现方向不对，返工代价远大于当初问一句。

所以记住：**`open_questions` 是“要问用户的问题”，不是“我替用户决定了的事”。**

怎么问：

- 用当前环境的提问工具一次问最多 3 个（DSH 是 `ask_user_question`，Claude Code 是 `AskUserQuestion`）。超过 3 个就排优先级，先问会改变实现方向的。
- 拿到答复后，把**用户原话**写回该条的 `answer`，`status` 改成 `answered`。不要转述成自己的判断。
- 用户明确说“你别问了我先干”时，把该条改成 `assumed`，并把 `assumption`（我按什么推进）、`if_wrong`（假设错了会怎样）、`confirm_by`（最迟什么时候回头确认）**三个都填上**。这是知情的假设，不是一个没问出口的问题；交付时要把这几条念给用户听。
- **用户没答复之前，`status` 只能停在 `draft`。** 不问就开工，正是这个 Skill 要防的事。环境里没有提问工具时，就在回复里显式列出问题并停下等答复。

哪些问题值得占用用户的时间：

- 输出要有确定格式或 schema 吗？（没有它，验收无从谈起）
- 这个改动会碰哪些系统/文件？有没有绝对不能碰的部分？
- 有没有可复现的输入、日志或环境？
- 成功/失败如何判定？谁来做最终验收？

不阻塞、但确实需要用户拍板的事（例如“历史数据要不要回填”），也照样要问——只是它们走 `open_questions`，答复前不挡开工。

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

脚本会连生命周期一起查：状态值合不合法、该问的问题问过没有、标了 `done` 有没有验收证据。
报错信息里带门槛编号（`G1`、`G2`…），字段含义见 `references/spec-field-guide.md`。
体检历史 SPEC 时可以用 `--lenient` 把生命周期门槛降级为提醒。

用户只粘贴了 SPEC 正文、没有文件时，先把正文写到临时文件再校验。

### 第 5 步：输出

- 用 **Markdown 说明 + YAML 规格**两部分回复；YAML 放在代码块里，或写入文件。
- **输出位置**：写入**用户当前打开的项目根目录**（harness 工作区根目录，即会话的 `pwd`）下的 `specs/` 文件夹，文件名为 `<id>.yaml`；`specs/` 不存在就先创建。
  - 这里的 `specs/` 是**项目里的**，不是本 Skill 目录里的；技能自带的 `templates/`、`scripts/`、`references/` 才位于技能目录。
  - 判断项目根目录：以 harness 当前工作目录为准；若用户显式给了路径，以用户为准。
  - **安全边界**：若当前工作目录看起来就是技能安装目录（例如 `~/.agents/skills` 或 `~/.agents/skills/<skill-name>`），说明项目路径不明确——先问用户项目在哪或让其指定输出路径，**不要**把 SPEC 写进技能目录。
- **查看器**：确保项目 `specs/` 下有 `specs.html`。运行 `python3 <skill-dir>/scripts/ensure_viewer.py <项目根目录>`：缺失时它从技能 `assets/specs.html` 复制一份；已存在则保留，但如果那份是**旧版查看器**，它会提示用户（新版才会显示“待复核 / 已验证 / N 个问题没问过”这些标记）。提示了就转告用户，由用户决定要不要 `--force` 更新——不要替用户覆盖他们可能改过的文件。它是一份通用查看器：浏览器里一次性读取 `specs/` 下所有符合规则的 YAML，按类型/状态分组、可搜索，并按 `validate_spec.py` 的规则标出 error / warning。不需要为每份 SPEC 生成单独的 HTML，也不要写进技能目录。
- 结尾列出：假设、问题的答复情况（哪些问了、哪些还是 `assumed` 的知情假设）、以及需要用户拍板的地方。

## 状态阶梯

状态是这份 SPEC 的结论，不是装饰。每个状态都有明确的进入条件，校验脚本会逐条检查。

| status | 含义 | 什么时候进 |
|---|---|---|
| `draft` | 草稿 | 默认状态；还有问题没问过用户时，只能停在这里 |
| `ready` | 就绪 | 问题都问过（或已写成知情假设），验收标准写全，可以开工 |
| `in_progress` | 进行中 | 有人开始动手 |
| `done` | 已完成（待复核） | 执行者自查做完，`verification` 写好了 |
| `verified` | 已验证 | 独立复核者或用户本人确认通过 |
| `blocked` | 受阻 | 卡住了，`blocked_reason` 写清卡在哪 |

`done` 和 `verified` 分开，是因为“干活的人说做完了”和“别人确认过”本来就是两件事。只有 `done` 的 SPEC 在待复核队列里；只有 `verified` 才算真正闭环。验收发现没过就退回 `in_progress`，别口头说一声就算了。

每次状态变化都要在 `status_log` 追一条记录（谁、什么时候、从哪到哪、为什么），脚本会自动写。看板上“N 天没动过”的提醒就是从这儿来的——它比任何人的记性都可靠。

## 收尾：做完的那一刻

“做完”和“状态改成 done”必须是同一个动作。分两步做，第二步一定会忘——项目里一堆早就上线的 SPEC 状态还停在 `ready`，就是这么来的。

要改的地方有七八处（status、status_log、version、updated、verification、遗留项清理），所以用脚本一次改完：

```bash
# 执行者自查完成
python3 <skill-dir>/scripts/spec_status.py specs/<id>.yaml --to done \
  --by impl-agent \
  --note "3 项 AC 全过，44 项测试通过" \
  --result "11/11 AC 通过；pnpm test 2 suites / 262 passed" \
  --acceptance "AC#1 空筛选返回 400|pass|pnpm test -- export.spec.ts -> 12 passed" \
  --command "pnpm --filter server test -> 2 suites / 262 passed" \
  --follow-up "F1（中）：历史周数据未回填，用户确认后再做"

# 独立复核或用户确认通过
python3 <skill-dir>/scripts/spec_status.py specs/<id>.yaml --to verified \
  --verify-by independent --verifier "verifier-task-3" --result "11/11 AC 复核通过"
```

前置条件不满足时脚本会**拒绝执行**，并逐条告诉你还差什么（哪条问题没问过用户、缺哪段证据）。差东西的时候不要用 `--force` 糊过去——它能推出一份"status 写着 done、校验却过不了"的 SPEC，这种状态是不可信的，等于把问题留给下一个读它的人。多个 agent 同时推进同一份文件也不会互相覆盖——脚本会排队（等不到锁时约 10 秒后报错让你重试）。如果文件是只读的（`chmod -w`），它会拒绝写入并提示你先 `chmod +w`，确实要强推才加 `--force`。

收尾还要顺手清理，这三件事脚本替不了：

- **已答复的阻塞问题**：把结论落进 `context` 或验收标准，然后把条目删掉。标 `done` 时 `blocking_questions` 必须是空的。
- **`open_questions` 里不要当日志用**：写“某件事已完成”“决定采用 A 方案”这类结论，会被当成“还没问过用户”而拦住你。结论写进正文，问题列表只放真的需要用户拍板的事。
- **没做完的事**：进 `follow_ups`，每条写清优先级和触发条件。不要留在对话里，也不要写成“已知问题”四个字。
- **bugfix 的 `root_cause.confirmed`**：改成 `true`；确实没确认的，把未确认的部分写进 `follow_ups`，不要留着 `false` 让下一个人以为根因还没找到。

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
产出不是代码，而是“结论 + 依据 + 建议方案”。写清什么证据能支撑什么决策。收尾时 `verification` 放结论与依据，`commands` 可以留空。

### ops
必填：`goal`、`target`、`changes`、`risks`、`rollback`、`monitoring`、`acceptance_criteria`、`failure_handling`。
必须能在出问题时回滚，且回滚步骤可执行。监控指标要写清阈值和观察窗口。

## 验收标准怎么写

好：`用户删除 localStorage 中的 token 后点击“个人中心”，1 秒内跳转到登录页，且不再出现 401 卡死`——可复现、可判定。

坏：`修复登录问题`、`功能正常`、`体验流畅`、`代码整洁`。

可验证的线索：具体输入、具体输出、具体错误、具体阈值、命令、测试名，以及“通过/失败/返回/包含/不再”这类能判定的词。

**验收标准覆盖**：除可验证外，正式 SPEC 的验收标准要覆盖三类路径——正常、边界（空/上限/并发/幂等）、失败（异常/超时/权限/5xx）。只写正常路径的规格，等于把失败处理留给执行者猜。

## 输出格式

```yaml
spec:
  type: feature | bugfix | refactor | research | ops
  name: 任务名称
  id: <type>-<slug>            # 稳定标识，后续引用/更新/审查都用它
  version: 1                   # 每次实质修改 +1
  updated: YYYY-MM-DD
  status: draft | ready | in_progress | done | verified | blocked
  related: []                  # issue / PR / 事故 / 监控链接
  status_log: []               # 状态变更记录，脚本自动追加
  blocked_reason: ""           # status=blocked 时必填
  goal: 最终目标（一句话）
  context: 背景与上下文
  assumptions: []              # 明确写出的假设
  blocking_questions: []       # 每条 {q, answered, asked_at, answer}；标 done 时必须为空
  open_questions: []           # 每条 {q, status, answer, assumption, if_wrong, confirm_by}
  inputs: []
  outputs:
    format: 输出格式
    schema: 可选 schema
  constraints: []
  tools: []
  steps: []
  acceptance_criteria: []
  failure_handling: []
  verification:                # status=done / verified 时必填
    result: 一句话结论 + 关键数字
    verified_by: self | independent | user
    acceptance: []             # 逐条 AC 的通过/失败与证据
  follow_ups: []               # 遗留问题
  examples: []
```

各类型的完整字段见 `templates/`；字段含义与填写标准见 `references/spec-field-guide.md`；可参考 `examples/` 里的成品。

## 公共元字段与就绪规则

每个 SPEC 都要有：

- `id`：稳定标识，格式 `<type>-<短横线 slug>`，例如 `bugfix-coupon-expired-500`。引用、更新、代码审查都靠它。
- `version`：整数，从 1 开始；每次实质修改 +1（状态推进也算）。
- `updated`：最后更新日期（YYYY-MM-DD）。
- `related`：相关 issue / PR / 事故 / 监控链接，没有就留空数组。
- `status_log`：状态变更记录，每条含 `date / from / to / by / version / note`。
- `blocking_questions`：**回答前不能开工**的问题；`open_questions`：可以并行推进、但要用户拍板的事。两者都要真的问过用户才能往下走。

**就绪门槛**：`status: ready` 要求 `blocking_questions` 全部 `answered: true` **且带着用户的答复原话**（`answer` 不能空——写个 `answered: true` 糊过去不算问过），并且没有 `status: open` 的普通问题——也就是“一条都没问过用户”就不能开工。带着没问出口的问题标 ready，执行者会在实现到一半时才发现要返工，这比多问一句代价大得多。校验脚本会拦住这个组合。

**完成门槛**：`status: done` 要求 `blocking_questions` 为空、`verification.result` 写全、`acceptance` **逐条**对应 `acceptance_criteria`（条数不能少；标 `pass`/`fail` 的必须给证据）、`status_log` 末条与当前状态一致。想合并成一条结论，就把 `acceptance_criteria` 合并成一条——不要用一条结论盖住三条标准。`status: verified` 还要求验证人不是执行者本人，且没有 `fail` 的验收项。

## 自检清单

- [ ] 类型判定正确，且用了对应模板
- [ ] 目标清晰、可衡量
- [ ] 输入明确（数据、文件、接口、环境）
- [ ] 输出有格式或 schema
- [ ] 约束、权限、边界写清
- [ ] 至少一条“不做什么”的边界
- [ ] 每条验收标准都可验证，无“正常/合理/流畅”这类词
- [ ] 验收标准覆盖正常、边界、失败三类路径
- [ ] bugfix 的验收能证明“原来会坏、现在不坏”，并有回归测试
- [ ] 失败/重试/回滚/转人工策略已定义
- [ ] 至少一个输入→输出示例
- [ ] 该问用户的问题**已经真的问过**，用户原话写进了 `answer`；没有一条还停在“没问过”
- [ ] 用户没答复时 `status` 停在 `draft`，没有偷偷开工
- [ ] 写成 `assumed` 的假设都填了 `assumption`/`if_wrong`/`confirm_by`，交付时会念给用户听
- [ ] 有稳定 `id`、`version`、`updated`
- [ ] `status: ready` 时没有未答复的阻塞问题，也没有没问过的普通问题
- [ ] 做完时跑了 `spec_status.py --to done`，`status_log` 里有记录，`version` 已 +1
- [ ] `done` 的 `verification` 写全了逐条 AC 结果、跑过的命令和未覆盖项
- [ ] `verified` 的验证人不是执行者本人
- [ ] 遗留问题在 `follow_ups` 里，已答复问题的结论落到了正文
- [ ] 校验脚本无 error
- [ ] SPEC 文件已写入**当前项目根目录**下的 `specs/` 文件夹（不是技能目录）
- [ ] 项目 `specs/` 下有 `specs.html` 查看器（缺失时用 `scripts/ensure_viewer.py` 创建，已有则不覆盖）

## 浏览 SPEC（specs.html）

`specs/specs.html` 是一份自包含的查看器（Tailwind CSS v4 + js-yaml，均走 CDN），把 `specs/` 下的 YAML 渲染成人类友好的视图，并按 `validate_spec.py` 的规则在浏览器里标出 error / warning。它只读，不会修改 SPEC——页面上给验收标准打的勾只记在浏览器本地，不会写回 YAML，别把它当成交付凭证。

创建（仅在缺失时）：

```bash
python3 <skill-dir>/scripts/ensure_viewer.py <项目根目录>
```

打开方式二选一：

1. **双击 `specs.html`**（file://）：页面里点“选择 specs 文件夹”或把 `specs/` 拖进去。浏览器不允许 file:// 页面自动读取同目录文件，所以需要这一步。
2. **本地服务**：在项目根目录运行 `python3 -m http.server 8000`，访问 `http://localhost:8000/specs/specs.html`。此时会自动读取同目录所有 YAML，无需手选。

查看器支持按类型/状态分组与搜索；它会标出“待复核”“✓已验证”“N 个问题没问过”“N 天没动”这类状态，并在详情页展开状态历史、验收记录与遗留问题。验收标准可勾选，进度记在浏览器本地，用于验收时逐条核对。

打开历史 SPEC 时看到一片红色不用慌：那多半是缺少 `status_log` / `verification`，或者带着从没问过用户的问题——正是这次改进要暴露的东西。只想看结构问题，用 `validate_spec.py --lenient` 把生命周期门槛降级为提醒。

## 与执行循环集成

| 时刻 | 谁 | 做什么 |
|---|---|---|
| 规划前 | 执行者 | 读 SPEC，确认 `acceptance_criteria` 可执行；有疑问就问，不要默默改需求 |
| 开工时 | 执行者 | `spec_status.py --to in_progress`；确认没有 `status: open` 的问题 |
| 执行中 | 执行者 | 新发现写回 `evidence`；需求变了，先改 SPEC 再改代码 |
| 做完 | 执行者 | **立刻** `spec_status.py --to done`，把逐条验收结果写进 `verification` |
| 验收时 | 复核者 / 用户 | 逐条核对 `acceptance_criteria`，每条给通过/失败和证据；通过则 `--to verified` |
| 发现没过 | 复核者 | 退回 `in_progress`，把失败项写进 SPEC，不要口头说一声就算了 |

维护已有 SPEC 时：`id` 不变，`version` +1。已答复的问题从列表里移走时，把结论写进 `context` 或验收标准，不要只删问题。任何“我做完了”的口头结论都不算数——SPEC 里的 `status` 和 `verification` 才是凭证。

`code-review` 这类 Skill 可以把本 SPEC 作为“Spec”一轴的输入，`verified` 状态的 SPEC 尤其适合当审查基准。
