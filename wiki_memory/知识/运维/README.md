---
type: knowledge
status: active
kind: operations
importance: medium
updated: 2026-10-07
topic: operations
source_logs:
  - "[[日志/工程维护/2026-09-07-精简视频转录技能并建立工程记忆]]"
supersedes: null
---

# 运维知识

本仓库没有常驻服务。日常维护主要是检查 Skill 目录结构、运行校验、刷新工程记忆索引以及提交推送 Git 变更。

- 记忆检查：`python -X utf8 wiki_memory/工具/memory.py check --project .`
- 刷新索引：`python -X utf8 wiki_memory/工具/memory.py index --project . --apply`
- 旧 `memory_lint.py` 留作历史工具，不再使用其整页重建索引命令。
