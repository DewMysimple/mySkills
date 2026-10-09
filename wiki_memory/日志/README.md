---
type: knowledge
status: active
kind: process
importance: high
updated: 2026-10-07
topic: work-log
source_logs:
  - "[[日志/工程维护/2026-09-07-精简视频转录技能并建立工程记忆]]"
supersedes: null
---

# 工作日志说明

本目录记录每次实质任务发生了什么。长期有效的事实、决策、架构和流程应沉淀到 当前状态/、决策/ 或 知识/。

## 文件命名

本仓库采用 standard，使用 `日志/<分类>/YYYY-MM-DD-任务标题.md`；同一天标题冲突时追加 -02、-03。

| kind | 分类目录 |
| --- | --- |
| feature | 功能添加 |
| ui | UI修改 |
| bug | Bug处理 |
| discussion | 工程讨论 |
| test | 测试验证 |
| maintenance | 工程维护 |

按主要交付物选择一个 kind，目录与字段保持一致。六类目录均保留，空目录用 `.gitkeep` 跟踪；不为分类编造任务记录。lite 项目可直接使用 `日志/YYYY-MM-DD-任务标题.md`。

## 日志要求

每篇日志包含目标与结果、已确认的决策、检查与操作范围、文件变更、测试与验证、问题与下一步、待确认长期记忆。只记录摘要和相对路径，不复制完整聊天、内部推理、密钥、令牌或大段命令输出。

## 索引

日志索引由 `python -X utf8 wiki_memory/工具/memory.py index --project . --apply` 刷新，写入 [[日志/MOC_工作日志|工作日志 MOC]] 的自动区。旧 `memory_lint.py` 保留作历史工具，不再用其 index 覆盖当前索引。
