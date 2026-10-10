---
type: knowledge
status: active
kind: module
importance: high
updated: 2026-10-10
verified: 2026-10-10
topic: skill-wiki-memory
sources: ["wiki-memory/SKILL.md", "wiki-memory/scripts/memory.py", "wiki-memory/scripts/test_memory.py", "wiki-memory/scripts/handoff_cases.py", "wiki-memory/assets/protocol.md", "wiki-memory/references/memory-model.md", "wiki-memory/references/handoff-evaluation.md", "wiki_memory/.memory.json", "wiki_memory/工具/memory.py"]
---

# Skill：工程记忆

入口为 wiki-memory/SKILL.md；3.2.0 主入口约 2738 字符，初始化合同、页面写法、迁移和预算在 references/memory-model.md 按需读。项目内 AGENTS 保留完整协议，独立工具不依赖个人安装位置。

## 布局与来源

用户指定根目录 wiki_memory/、README 唯一导航、中文专题及 standard 六类日志，依据 [[决策/ADR-003-根目录记忆与README统一导航.md|ADR-003]]、[[决策/ADR-004-标准日志分类与理论溯源.md|ADR-004]]；这些选择没有改变。standard 完成五页实质状态，lite 为一页；示例不复制为真实历史，可选理论原文保持原样。

区分需求、选择、实现和漂移，来源按项目相对路径记录。协议与命令更新保留本地约定、历史日期、结论和当时命令；source Skill 更新不批量升级其他项目。

## 工具行为与设计选择

- init 先预览，--apply 才写入；已有记忆不重新初始化。index 只刷新生成区和 MOC 编辑日期，有锁、快照检查、原子写入和失败回滚。
- check 排除代码块、注释、引用及明显否定示例，正式接入块须唯一且成对；无标记旧接入兼容但警告人工复核。根 AGENTS 的原读取规则现已加正式标记，权限内容未改。
- read_budget 统计 Unicode 字符，默认启动 16000、单页 6000、待办 20；可部分覆盖，0 禁用。超限只提示；非法配置仍报错。默认阈值由 Agent 在用户授权整改范围内选定，不是用户明确指定值，也不冒充模型 token。
- plan-migration 始终只读并拒绝 --apply，列出移动、导航合并、引用修正、冲突、未分类日志和状态工作。不猜 kind、不自动执行；项目 Markdown 外的代码/配置文字仍需人工盘点。
- schema 仍为 2、navigation 为 README.md；本仓库工具/配置/协议显式升级 3.2.0，moc_defaults 与 mySkills 定制规则保留。历史 memory_lint.py 不混用。

## 验证与接续

2026-10-10，Windows / Python 3.14.2，基线 60057b3 加本任务未提交变更：99 项脚本回归、Skill 结构校验通过；四个无历史上下文的隔离 Agent 完成接续、冲突、分支和升级评测。前三个案例文件全部保持原样；升级案例原源码、配置、测试与历史日志哈希保持原样，12 页严格体检通过。

维护者用 scripts/handoff_cases.py 在临时目录生成真实可运行小工程；实际结果及读取统计见 references/handoff-evaluation.md。评测观察到长参考输出截断和导航重复读取，已加按章读取提示；不把自查或脚本单测当作独立换会话验证。一次小工程评测不证明所有平台、真实大型项目或模型不会遗忘。

以前 3.1.0 的 81 项测试和其他项目结果仅属历史，见 [[日志/工程维护/2026-10-09-补齐标准日志分类与理论参考.md|此前日志]]；本次只升级 mySkills 副本和隔离材料。任务记录及最终本仓库检查见 [[日志/工程维护/2026-10-10-完善工程记忆校验与交接评测.md|整改日志]]。
