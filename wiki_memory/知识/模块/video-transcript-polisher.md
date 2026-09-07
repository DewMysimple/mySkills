---
type: knowledge
status: active
kind: module
importance: high
updated: 2026-09-07
topic: video-transcript-polisher
source_logs:
  - "[[日志/2026-09-07-精简视频转录技能并建立工程记忆]]"
supersedes: null
---

# video-transcript-polisher

## 一句话结论

这是一个保守整理 Whisper/ASR 视频课堂转写的 Skill，核心目标是提高可读性但不改变原文的语言、信息顺序和含义。

## 入口与资源

- 核心入口：video-transcript-polisher/SKILL.md
- 批处理复核：video-transcript-polisher/references/batch-review.md
- approved-output 回填：video-transcript-polisher/references/approved-output-backfill.md
- UI 元数据：video-transcript-polisher/agents/openai.yaml

## 边界

- 允许高置信度 ASR 词语纠错、标点恢复、段落整理和克制的 Markdown 结构。
- 不负责总结、翻译、扩写、事实核查或重写成文章。
- 默认不覆盖输入文件；小批量或强关联文件由主 Agent 处理。

## 常见维护点

- 共享规则放在 SKILL.md。
- 只对批处理或回填必要的规则放到 references/，不要重新堆回入口。
- 修改入口或参考文件后运行结构校验并检查相互链接。

## 来源

- [[决策/ADR-001-按需加载技能复杂流程|按需加载技能复杂流程]]
- [[日志/2026-09-07-精简视频转录技能并建立工程记忆|本轮重构日志]]
