---
type: knowledge
status: active
kind: module
importance: high
updated: 2026-11-06
topic: video-transcript-polisher
sources: ["video-transcript-polisher/SKILL.md", "video-transcript-polisher/references/long-transcripts.md", "video-transcript-polisher/references/batch-review.md", "video-transcript-polisher/references/approved-output-backfill.md", "video-transcript-polisher/scripts/check_fidelity.py", "video-transcript-polisher/tests/evaluation.md", "video-transcript-polisher/tests/practice-cases.json", "用户指令：2026-11-06 编辑转录文本并保护讲者原始内容"]
source_logs:
  - "[[日志/Bug处理/2026-11-06-解除转录重复确认门禁]]"
  - "[[日志/功能添加/2026-11-06-按真实样本修复转录可读性]]"
  - "[[日志/功能添加/2026-11-06-迭代视频转录保真整理]]"
  - "[[日志/工程维护/2026-09-17-收紧视频转录技能启发式规则]]"
  - "[[日志/工程维护/2026-09-07-精简视频转录技能并建立工程记忆]]"
supersedes: null
---

# video-transcript-polisher

## 一句话结论

保真整理 Whisper/ASR 课堂转录，让读者更容易连续阅读、定位和复习讲者的原始内容。

## 入口与资源

- [核心入口](../../../video-transcript-polisher/SKILL.md)
- [长篇分段](../../../video-transcript-polisher/references/long-transcripts.md)、[批处理](../../../video-transcript-polisher/references/batch-review.md)、[批准稿回填](../../../video-transcript-polisher/references/approved-output-backfill.md)
- [界面元数据](../../../video-transcript-polisher/agents/openai.yaml)、[回归样例与评审](../../../video-transcript-polisher/tests/evaluation.md)

## 边界

- 用户于 2026-11-06 确定「编辑转录文本」原则及 L1 文本修复、L2 局部润色与结构、L3 知识重写边界。入口按该边界执行，局部调整保留讲者的顺序、语气、推理、自我修正和限制条件。
- 用户明确的标点、标题、列表和布局要求优先；结构化只在明显改善导航时执行。
- 段落长度和标题数量只用于触发复核，不是输出目标；不要把“适度”机械化成固定数量，也不要把“稀疏”执行成“零标题”。
- `#` 仅用于原文已有或用户明确要求的文档标题；`##` 用于清晰且持续的主题或方法阶段。
- 判断 ASR 词语身份时，语法和熟悉度只作辅助。数字、专名、API、函数名和文件名等高风险词必须有原文重复、唯一上下文或用户参考支持。
- 句法修复和词语身份识别分开判断。对冗余虚词和明确词形错误，使用不改变原意的最小修复。只有原文上下文能确认无独立含义且没有后续回指时，才去掉未完成的起句。
- 不负责总结、翻译、扩写、事实核查或重写成文章。
- 源文件默认保持原样。明确授权范围内，预检后直接处理。每份通过双审查的文件可以独立保存，路径冲突、未授权覆盖或元数据异常单独隔离。用户明确要求全有或全无时才采用批次原子语义。见 [调度与写入决策](../../决策/ADR-005-转录调度与逐文件写入.md)。
- 长篇使用同一份源映射和连续范围账本检查覆盖、顺序、衔接、术语及源文件身份。范围账本和候选稿保存在正式目标外。
- 批准稿回填按明确映射进行。原样保留目标 frontmatter 前缀，正文只处理开头的分隔空行。写入前后核对批准稿、目标前缀和正文。
- 候选稿分别复核保真和阅读体验。可选的标准库检查器只报告可比对的字面差异，语义判断依赖逐段对照。
- 普通润色从源文定位确定可修的句段及持续展开的主题。成稿后逐处复查，保留原有口头转场，必要时在相应位置加源内标题。

## 常见维护点

- 共享规则放在 SKILL.md。
- 长篇分段、批处理和回填细节按场景加载。
- 修改规则后运行结构校验，并按回归指南用合成样例检查保真、可读性和文件安全。回归时固定 Skill 路径和版本，单独核对已安装副本。

## 来源

- [[决策/ADR-001-按需加载技能复杂流程|按需加载技能复杂流程]]
- [[日志/工程维护/2026-09-07-精简视频转录技能并建立工程记忆|本轮重构日志]]
