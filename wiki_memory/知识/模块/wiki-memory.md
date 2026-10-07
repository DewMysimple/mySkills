---
type: knowledge
status: active
kind: module
importance: high
updated: 2026-10-07
verified: 2026-10-07
topic: skill-wiki-memory
sources: ["wiki-memory/SKILL.md", "wiki-memory/scripts/memory.py", "wiki-memory/scripts/test_memory.py", "wiki-memory/assets/protocol.md", "wiki-memory/references/memory-model.md"]
---

# Skill：工程记忆

维护入口是 `wiki-memory/SKILL.md`。`assets/protocol.md` 是生成项目协议的模板；`references/memory-model.md` 解释页面、迁移和压缩；`scripts/memory.py` 提供初始化、索引、体检。

- 模式由 Agent 根据上下文判断，脚本不自动评分。单个主要交付物默认 lite，多条独立演进边界可选 standard；不按文件数硬判大小。
- 初始化先预览，`--apply` 才写入；拒绝重建已有记忆。索引只更新自动区域，当前事实由 Agent 根据代码和指令维护。
- 当前版本 `2.1.0`，Python 3.10+、标准库运行。项目副本独立，升级需核对版本与定制协议。
- 首次接入若需要 Git 交付，初始化前核对实际远程引用；不能只信本地跟踪缓存。工具不联网，初始化会检查常见位置和项目指令中可识别的旧记忆引用，其他自定义位置仍需 Agent 盘点。
- 原子写入前核对页面与配置的同一份快照；配置并发变化或新建会停止索引。已接入布局的导航类型与自动区标记进入体检，日志表格使用相对 Markdown 链接。
- 本仓库配置了 `moc_defaults`，新目录 MOC 自动补齐旧协议必需的 `kind`、`importance`；已有页面的自定义字段保留。
- 修改能力包时验证其脚本和模板；是否升级本仓库的 `wiki_memory/` 副本属于单独操作，不能因符号链接安装就认为副本自动变化。

已执行（2026-10-07，Windows / Python 3.14.2，基线 `2f5af29` 加本轮变更）：

```text
python -X utf8 "wiki-memory/scripts/test_memory.py"
```

结果：55 项通过，含本轮新增的 16 项回归检查；Skill 结构校验通过，项目独立工具体检 29 页零错误、零警告。另在临时 Git 仓库验证远程滞后场景，并核对实际日志表格四列与历史保留。测试不代替真实项目事实核实，详情见 [[日志/2026-10-07-实践问题复盘与修复.md|实践复盘日志]]；首次接入历史见 [[日志/2026-10-07-配置仓库工程记忆.md|配置日志]]。
