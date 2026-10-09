---
type: knowledge
status: active
kind: module
importance: high
updated: 2026-09-17
topic: video-transcript-polisher
source_logs:
  - "[[日志/工程维护/2026-09-17-收紧视频转录技能启发式规则]]"
  - "[[日志/工程维护/2026-09-07-精简视频转录技能并建立工程记忆]]"
supersedes: null
---

# video-transcript-polisher

## 一句话结论

这是一个保真整理 Whisper/ASR 视频课堂转写的 Skill，核心目标是提高可读性并提供适度的章节结构，但不改变原文的语言、信息顺序和含义。

## 入口与资源

- 核心入口：video-transcript-polisher/SKILL.md
- 批处理复核：video-transcript-polisher/references/batch-review.md
- approved-output 回填：video-transcript-polisher/references/approved-output-backfill.md
- UI 元数据：video-transcript-polisher/agents/openai.yaml

## 边界

- 允许高置信度 ASR 词语纠错、标点恢复、段落整理和适度的 Markdown 结构。
- 用户明确的标点、标题、列表和布局要求优先；结构化只在明显改善导航时执行。
- 段落长度和标题数量只用于触发复核，不是输出目标；不要把“适度”机械化成固定数量，也不要把“稀疏”执行成“零标题”。
- `#` 仅用于原文已有或用户明确要求的文档标题；`##` 用于清晰且持续的主题或方法阶段。
- 语法和熟悉度只能辅助纠错；数字、专名、API、函数名和文件名等高风险词必须有原文重复、唯一上下文或用户参考支持。
- 不负责总结、翻译、扩写、事实核查或重写成文章。
- 默认不覆盖输入文件；小批量或强关联文件由主 Agent 处理。

## 常见维护点

- 共享规则放在 SKILL.md。
- 只对批处理或回填必要的规则放到 references/，不要重新堆回入口。
- 修改入口或参考文件后以 UTF-8 模式运行结构校验并检查相互链接。

## 来源

- [[决策/ADR-001-按需加载技能复杂流程|按需加载技能复杂流程]]
- [[日志/工程维护/2026-09-07-精简视频转录技能并建立工程记忆|本轮重构日志]]
