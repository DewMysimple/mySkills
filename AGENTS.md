# Agent Instructions for `mySkills`

This file defines the repository purpose and working conventions for future agents. It is intentionally bilingual.

## 中文规则

### 项目用途

`C:\Users\Administrator\Desktop\mySkills` 是 DewMysimple 用来创建、维护和分享个人 Codex Skills 的仓库。每个 Skill 都应当是一个可以独立发现、读取和维护的能力包。

当前仓库包含 `video-transcript-polisher`，用于对 Whisper/ASR 视频课堂 Markdown 转录进行保真式加工：只做有充分依据的词语纠错、标点和段落优化，以及克制的 Markdown 结构整理；不得总结、翻译、扩写或改写课堂原生内容。

### 目录管理

- 遵循“一项 Skill 一个一级目录”，不要把多个 Skill 混在同一个一级目录中。
- 每个 Skill 至少包含 `SKILL.md`；只有确实需要时才添加 `agents/openai.yaml`、脚本、引用资料或资源。
- 新增或修改 Skill 时，使用并完整遵循可用的 `skill-creator` 规范；新建 Skill 可使用初始化器，修改已有 Skill 时不要重复初始化。
- 不为 Skill 添加无实际用途的 README、示例、脚本或其他维护结构。
- 根目录的 `README.md` 和本文件是仓库级文档，不属于任何单独 Skill。

### 工作约束

- 开始修改前先检查当前文件、目录结构和 Git 状态，保留用户已有的无关变更。
- 处理课堂转录时默认保留原始文件；本地处理稿放在输入文件旁的 `processed/` 目录，除非用户明确要求改变位置。
- 课堂样本和处理稿属于本地工作材料，默认不复制到仓库，也不加入 Git。
- 修改 Skill 后执行适用的校验，包括 `skill-creator` 的 `quick_validate.py`；如果环境缺少依赖，应记录原因并完成可执行的手工检查。
- 提交前检查 diff，确认只包含用户当前请求范围内的文件，没有新增事实、总结性内容或无关格式变化。
- 只有用户明确要求时才提交、推送或进行其他外部 Git 操作。

## English Rules

### Repository Purpose

`C:\Users\Administrator\Desktop\mySkills` is DewMysimple's repository for creating, maintaining, and sharing personal Codex Skills. Every Skill should be an independently discoverable, readable, and maintainable capability package.

The repository currently contains `video-transcript-polisher`, which faithfully polishes Whisper/ASR Markdown transcripts of video lectures. It may correct words when strongly supported, restore punctuation and paragraph structure, and apply restrained Markdown organization. It must not summarize, translate, expand, or rewrite the original lecture.

### Directory Management

- Follow a “one Skill per top-level directory” structure; do not combine multiple Skills in one top-level directory.
- Every Skill must contain `SKILL.md`; add `agents/openai.yaml`, scripts, references, or assets only when they are genuinely needed.
- Use and fully follow the available `skill-creator` guidance when creating or updating a Skill. Use its initializer for a new Skill, but do not reinitialize an existing Skill.
- Do not add README files, examples, scripts, or other maintenance structure that has no concrete purpose for a Skill.
- The root `README.md` and this file are repository-level documentation, not files belonging to an individual Skill.

### Working Constraints

- Inspect the current files, directory structure, and Git status before editing, and preserve unrelated user changes.
- Keep source lecture transcripts unchanged by default. Put local processed copies in a `processed/` directory beside the input unless the user explicitly requests another location.
- Treat lecture samples and processed copies as local working materials; do not copy them into the repository or stage them by default.
- After changing a Skill, run applicable checks, including `skill-creator`'s `quick_validate.py`. If a dependency is unavailable, record the reason and complete all feasible manual checks.
- Review the diff before committing to ensure it contains only files within the user's current request and introduces no new facts, summaries, or unrelated formatting changes.
- Commit, push, or perform other external Git operations only when the user explicitly requests them.
