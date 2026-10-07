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
- 当前版本 `2.0.0`，Python 3.10+、标准库运行。项目副本独立，升级需核对版本与定制协议。
- 修改能力包时验证其脚本和模板；是否升级本仓库的 `wiki_memory/` 副本属于单独操作，不能因符号链接安装就认为副本自动变化。

已执行（2026-10-07，Windows / Python 3.14.2，基线 `18ae4c8` 加本地变更）：

```text
python -X utf8 "wiki-memory/scripts/test_memory.py"
```

结果：39 项通过。Skill 结构校验也通过。随后实际用于本仓库的旧记忆迁移，整合远程 `30d770e` 后，28 页体检零错误、零警告。测试不代替真实项目事实核实，详情见 [[日志/2026-10-07-配置仓库工程记忆.md|配置日志]]。
