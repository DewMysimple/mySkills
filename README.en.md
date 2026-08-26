# mySkills

[简体中文](README.md)

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
├── README.en.md
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
