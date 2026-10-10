---
type: moc
status: active
kind: process
importance: high
updated: 2026-10-10
topic: memory-entry
sources: []
---

# mySkills 工程记忆

日志保留历史，当前状态、决策和知识保存有来源的结论；实际代码、项目指令和用户要求优先。本页只说明与导航，维护规则见 [AGENTS.md](AGENTS.md)。

本项目采用根目录 wiki_memory/ 和 standard：2026-10-07 按三个独立 Skill 的维护边界选用五页；2026-10-09 用户明确根目录、README 唯一导航及六类日志。依据：[[决策/ADR-003-根目录记忆与README统一导航.md|布局决策]]、[[决策/ADR-004-标准日志分类与理论溯源.md|日志与理论决策]]。

## 读取与维护

先读协议及概览、约束、待办三页，再按任务定位专题；历史按需检索。接续时重查 Git 分支、revision 和工作区。实质修改结束后同步相关页、留日志、刷新索引并人工核实；提交推送授权见项目根 AGENTS.md。

```text
python -X utf8 "wiki_memory/工具/memory.py" index --project . --apply
python -X utf8 "wiki_memory/工具/memory.py" check --project . --require-ready
```

结构通过不证明语义正确。读取预算只提示；迁移先运行只读 plan-migration。历史 memory_lint.py 不与当前索引混用。

## 专题与历史

- [[知识/模块/README.md|模块知识]]
- [[知识/流程/README.md|流程知识]]
- [[知识/规范/README.md|工程规范]]
- [[知识/运维/README.md|运维知识]]
- [工作日志](日志/MOC_工作日志.md)：standard 按六类 kind 归档，空目录保留 .gitkeep，仅维护一个日志 MOC。

状态、决策、知识、日志各自保存事实与历史；模板/ 保留本仓库模板，工具/ 保存独立工具副本。wiki-memory/ 是可分发 Skill，wiki_memory/ 是本仓库文档，随 Git 保存；安装 Skill 不自动升级项目。

[日志布局示例](../wiki-memory/assets/standard-log-layout/) 是虚构教学内容，[理论原文](../wiki-memory/references/llm-wiki.md) 可选阅读，均不当作项目历史。

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
