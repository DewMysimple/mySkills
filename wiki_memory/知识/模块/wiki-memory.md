---
type: knowledge
status: active
kind: module
importance: high
updated: 2026-10-09
verified: 2026-10-09
topic: skill-wiki-memory
sources: ["wiki-memory/SKILL.md", "wiki-memory/scripts/memory.py", "wiki-memory/scripts/test_memory.py", "wiki-memory/assets/protocol.md", "wiki-memory/references/memory-model.md", "wiki_memory/.memory.json", "wiki_memory/工具/memory.py"]
---

# Skill：工程记忆

维护入口是 `wiki-memory/SKILL.md`。协议模板、按需参考和脚本分别承担项目协议、模式/页面/迁移说明及初始化/索引/体检。

## 布局与内容合同

- 用户明确要求记忆在工程根目录 `wiki_memory/`。README 是唯一导航和使用说明，AGENTS 是维护协议；取消独立入口页，保留中文专题名称。选择依据见 [[决策/ADR-003-根目录记忆与README统一导航.md|ADR-003]]。
- 用户指定 standard 时完整维护五页。各页按 Skill 表格的小节填写目标、架构、约束、焦点、问题、证据及恢复上下文；不靠空文件或配置字段宣称已完成。不默认复制全部代码文档或编造决策。
- 新建仍需先预览，`--apply` 才写入。当前版本 `3.0.0`、配置 schema `2` 和 `navigation: README.md`；Python 3.10+、标准库运行。项目内工具是独立副本，升级须对比定制协议。
- 旧位置/旧 schema 可以只读 check；index 必须先迁移根目录位置、合并导航、修引用和配置。不能重新 init 覆盖旧记忆，也不能只改版本字段。自定义旧索引名要显式合并到标准 MOC。

## 核实与工具

- 普通 check 不代表初始事实已完成；配置交付运行 `check --require-ready`，核对所选模式必需状态 active、有来源、必需小节非空且不是原样初始化提示。结构通过后仍人工核实事实、来源支持程度和实际测试范围。
- 索引只更新生成区与 MOC 编辑日期，保留手写内容。写入有锁、文件/配置/页面集合快照及失败回滚；其他编辑器和并行 Agent 仍需协调。
- 已修复知识/状态/决策文件名含 `#`、字面 `%20` 时自生成断链，以及 Windows `.MD` 页面触发错误并发提示的问题。普通中文路径保持可读，仅保留字符编码。
- 首次接入若需要 Git 交付，核对实际远程引用；工具不联网、不自行提交推送。一个项目的持续授权不传给另一个项目。

## 实际验证与限制

2026-10-09，Windows / Python 3.14.2，基线 `43ecd52` 加本次变更：`python -B -X utf8 wiki-memory/scripts/test_memory.py` 68 项通过；Skill 结构校验通过。本仓库工具副本的 index 与 `check --require-ready` 已实际执行并通过，最终页数和实践结果在本次任务日志记录。

历史 2.1.0 的 55 项测试属于 2026-10-07，见 [[日志/2026-10-07-实践问题复盘与修复.md|实践复盘日志]]，不替代当前验证。未证明所有平台兼容性、全部敏感内容检测或模型不会遗忘；真实项目语义仍依赖源码与用户要求核实。
