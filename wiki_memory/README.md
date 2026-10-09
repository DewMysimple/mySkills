---
type: moc
status: active
kind: process
importance: high
updated: 2026-10-09
topic: memory-entry
sources: []
---

# mySkills 工程记忆

这是 mySkills 的可审计 Markdown 工程记忆。日志保留事件历史，当前状态、决策和知识页保存经来源核实的结论；实际代码、项目指令和用户要求优先。

本项目使用工程根目录的 `wiki_memory/`，采用 `standard`。2026-10-07 由 Agent 根据三个 Skill 独立迭代的边界选择五页布局；2026-10-09 用户明确要求根目录位置和 README 统一导航，保留中文专题名称。选择与验收见 [[决策/ADR-003-根目录记忆与README统一导航.md|记忆布局决策]]。

## 读取与维护

1. 先读 [维护协议](AGENTS.md)，每轮必读项目概览、当前约束、当前待办，再按任务读取架构、问题、决策和模块知识。
2. 当前分支、revision 与未提交改动以当轮 Git 检查为准；不要将旧日志的验证视为当前验证。当前事实只保存在状态和专题页，本页负责说明和导航。
3. 实质修改结束后同步相关记忆并留日志，刷新索引，再体检和人工核查。持续提交推送授权见项目根 `AGENTS.md`。

```text
python -X utf8 "wiki_memory/工具/memory.py" index --project "." --apply
python -X utf8 "wiki_memory/工具/memory.py" check --project "." --require-ready
```

`check --require-ready` 检查必需状态页、章节与证据字段，不能代替源码语义核实。历史 `memory_lint.py` 保留追溯，不再运行它的整页索引写入。

## 目录与职责

```text
wiki_memory/
├── AGENTS.md       # 维护协议
├── README.md       # 系统说明与唯一导航
├── .memory.json    # standard 布局、导航与工具版本
├── 当前状态/        # 项目概览、系统架构、当前约束、当前待办、已知问题
├── 决策/           # 已采用选择、候选及替代关系
├── 知识/           # 模块、流程、规范和运维专题
├── 日志/           # 单一 MOC 与按 kind 分类的追加式历史
│   ├── 功能添加/
│   ├── UI修改/
│   ├── Bug处理/
│   ├── 工程讨论/
│   ├── 测试验证/
│   └── 工程维护/
├── 模板/           # 本仓库已有页面模板
└── 工具/           # 当前 memory.py 与历史 memory_lint.py
```

记忆随 Git 保存。`wiki-memory/` 是可分发 Skill，`wiki_memory/` 是本仓库记忆，二者独立；个人 Skill 安装不自动升级项目工具。

## 专题分类

- [[知识/模块/README.md|模块知识]]
- [[知识/流程/README.md|流程知识]]
- [[知识/规范/README.md|工程规范]]
- [[知识/运维/README.md|运维知识]]
- [工作日志目录](日志/MOC_工作日志.md)

本项目采用 standard，日志按主要交付物的 `kind` 写入对应分类目录，六类保留；空目录用 `.gitkeep` 随 Git 保存。2026-10-09 用户明确要求恢复原模板的文件夹分类，详见 [[决策/ADR-004-标准日志分类与理论溯源.md|日志布局与理论溯源决策]]。可复用示例和可选理论背景分别位于 `wiki-memory/assets/standard-log-layout/`、`wiki-memory/references/llm-wiki.md`；示例不会复制为项目真实历史。

<!-- wiki-memory:auto:start -->

## 当前状态

- [[当前状态/已知问题.md|已知问题]] — active
- [[当前状态/当前待办.md|当前待办]] — active
- [[当前状态/当前约束.md|当前约束]] — active
- [[当前状态/系统架构.md|系统架构]] — active
- [[当前状态/项目概览.md|项目概览]] — active

- [[决策/MOC_决策.md|工程决策目录]] — 4 页，按主题或模块检索。
- [[知识/MOC_知识.md|稳定知识目录]] — 11 页，按主题或模块检索。

<!-- wiki-memory:auto:end -->
