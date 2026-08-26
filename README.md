# mySkills

<details open>
<summary>简体中文</summary>

## 项目简介

`mySkills` 是 DewMysimple 用来创建、维护和分享个人 Codex Skills 的仓库。

每个 Skill 都是一个独立的能力包，通常通过 `SKILL.md` 描述适用场景、处理原则和工作流程，并可根据需要提供 `agents/openai.yaml` 等辅助配置。

当前仓库的第一个 Skill 是 [`video-transcript-polisher`](video-transcript-polisher/SKILL.md)，用于保真处理 Whisper 或其他 ASR 模型生成的视频课堂 Markdown 转录。

## 当前 Skill

`video-transcript-polisher` 主要用于：

- 在语义、常识和上下文有充分依据时纠正 ASR 词语错误；
- 合并语音识别造成的句子碎片，补充标点并优化自然段；
- 适度使用 `#` 和 `##` 标题，以及原文明确存在的列表关系；
- 保留原文语言、信息顺序、数字、专名、例子、论证关系、时间戳和说话人标签；
- 不翻译、不总结、不扩写，不把课堂转写改写成新的文章；
- 将处理稿输出到输入文件旁的 `processed/` 目录，并保持原文件不变。

## 使用方式

获取仓库后，将需要使用的 Skill 目录导入你的 Codex Skills 配置中，然后可以显式调用：

```text
Use $video-transcript-polisher to conservatively polish this lecture transcript without summarizing it.
```

这个 Skill 也支持在任务内容与其适用场景匹配时被自动发现。

## 仓库结构

```text
mySkills/
├── AGENTS.md
├── README.md
└── video-transcript-polisher/
    ├── SKILL.md
    └── agents/
        └── openai.yaml
```

仓库采用“一项 Skill 一个一级目录”的管理方式。个人课堂样本和处理稿属于本地工作材料，默认不纳入仓库。

## 新增 Skill

新增 Skill 时，为它创建独立的一级目录，并至少包含一个 `SKILL.md`。如果需要，可以添加 `agents/openai.yaml` 或其他直接服务于该 Skill 的资源。创建或修改 Skill 时遵循 `skill-creator` 的规范，并在提交前完成结构和内容验证。

## 项目地址

[https://github.com/DewMysimple/mySkills](https://github.com/DewMysimple/mySkills)

</details>

<details>
<summary>English</summary>

## Overview

`mySkills` is DewMysimple's repository for creating, maintaining, and sharing personal Codex Skills.

Each Skill is an independent capability package. It usually uses `SKILL.md` to define its scope, processing principles, and workflow, and may include supporting configuration such as `agents/openai.yaml` when needed.

The first Skill in this repository is [`video-transcript-polisher`](video-transcript-polisher/SKILL.md). It faithfully polishes Markdown transcripts of video lectures produced by Whisper or other ASR systems.

## Current Skill

`video-transcript-polisher` is designed to:

- Correct ASR wording only when semantics, common knowledge, and context provide strong evidence;
- Join fragments caused by speech recognition, restore punctuation, and improve paragraph structure;
- Use `#` and `##` headings sparingly, and create lists only when the source clearly presents list relationships;
- Preserve the source language, information order, numbers, proper names, examples, reasoning, timestamps, and speaker labels;
- Never translate, summarize, expand, or rewrite a lecture into a new article;
- Write processed copies to a `processed/` directory beside the input while keeping the original file unchanged.

## Usage

After obtaining this repository, import the Skill directory you want to use into your Codex Skills configuration. You can then invoke it explicitly:

```text
Use $video-transcript-polisher to conservatively polish this lecture transcript without summarizing it.
```

The Skill can also be discovered automatically when a task matches its intended scope.

## Repository Structure

```text
mySkills/
├── AGENTS.md
├── README.md
└── video-transcript-polisher/
    ├── SKILL.md
    └── agents/
        └── openai.yaml
```

The repository follows a “one Skill per top-level directory” structure. Personal lecture samples and processed copies are local working materials and are not included in the repository by default.

## Adding a Skill

Create a dedicated top-level directory for every new Skill and include at least a `SKILL.md`. Add `agents/openai.yaml` or other resources only when they directly support the Skill. Follow the `skill-creator` guidance when creating or updating a Skill, and complete structural and content checks before committing.

## Repository

[https://github.com/DewMysimple/mySkills](https://github.com/DewMysimple/mySkills)

</details>
