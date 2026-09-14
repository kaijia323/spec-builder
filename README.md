# spec-builder

把模糊的任务需求转成结构化、可执行、可验收的 SPEC（任务规格 / 执行规范 / 执行契约），用于 Agent 的规划、执行与验收。

支持五种规格类型：`feature`、`bugfix`、`refactor`、`research`、`ops`。

## 包含内容

- `SKILL.md` — 技能主文件：类型判定、执行流程、公共元字段与就绪门槛、验收标准写法、执行循环集成。
- `templates/` — 五种类型的填空模板。
- `references/spec-field-guide.md` — 字段含义与填写标准。
- `examples/` — 五种类型的成品示例。
- `scripts/validate_spec.py` — 校验脚本：必填字段、空值、弱验收标准、`ready` 门槛、类型专属检查。
- `evals/evals.json` — 7 个评测用例与 61 条断言。

## 使用

把本目录放到技能加载路径下（例如 `~/.agents/skills/spec-builder/`）。当需求涉及 SPEC、任务规格、修 bug、重构、调研或上线变更，且要为 Agent 准备任务说明时触发。

生成的 SPEC 默认写入**用户当前打开的项目根目录**下的 `specs/`（不是技能目录）；技能自身的 `templates/`、`scripts/`、`references/` 仍在技能目录内。

校验一份 SPEC：

```bash
python3 scripts/validate_spec.py specs/feature-user-export.yaml
python3 scripts/validate_spec.py specs/feature-user-export.yaml --json
```

退出码：0 = 无 error，1 = 有 error，2 = 读取或解析失败。

## 设计要点

- **先分类再动笔**：五类规格的关注点不同，类型判错后面全错。
- **就绪门槛**：`status: ready` 仅当 `blocking_questions` 为空，避免带着未决问题开工。
- **验收标准必须可验证**，并覆盖正常、边界、失败三类路径。
- **SPEC 是执行契约**：规划前读它，执行后逐条核对 `acceptance_criteria`。
- **统一 schema 便于机器处理**：稳定 `id`、`version`、`updated`、`related`，可被代码审查与工作流直接引用。

## 校验脚本

`validate_spec.py` 按类型检查必填字段与空值，检测不可验证的验收标准，强制执行 `ready` 门槛，并对 bugfix / refactor / ops 做专属检查。仓库内 5 个示例全部 0 error / 0 warning。

## 评测

在 7 个用例（feature / bugfix / refactor / research / ops / 信息不足需澄清 / 校验已有 SPEC）上：

| 配置 | 通过率 |
|---|---|
| 加载技能 | 100%（61/61） |
| 不加载技能 | 约 69%（42/61） |

技能的主要价值是把规格统一成可校验的契约；对能力较强的模型，内容详略本身差距不大。
