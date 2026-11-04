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

## Engineering memory

Version 3.4.0 of `wiki-memory` keeps schema 2 and stores project memory in `wiki_memory/`. Lite uses one current-state page. Standard maintains five state pages and six log categories. The project README is the sole navigation page. The Skill is explicit-only, and routine work in an initialized project follows its local protocol. Narrow read-only questions can go directly to relevant evidence when the project rules allow it. Changes and handoffs retain the full startup reading.

Init previews changes by default and applies them with `--apply`. New projects set `"link_style": "markdown"` and generate relative links. Existing projects without this field keep Wiki navigation and the original Markdown log table. To switch explicitly, set the field in `.memory.json`, preview `index`, and apply with `index --apply`. Handwritten links and historical pages stay intact.

```text
python -X utf8 wiki-memory/scripts/memory.py impact --project . --base <commit> --head HEAD
python -X utf8 wiki-memory/scripts/memory.py tool-diff --project .
```

`impact` matches Git changes to page sources and flags candidates for review. An optional `verified_rev` records a whole-page verification baseline. `tool-diff` compares declared versions, byte fingerprints, and configuration compatibility. Review differences before updating a project copy and carry forward project customizations. The standalone tool uses Python 3.10+ and the standard library. Run the two analysis commands when needed, with one ordinary check after routine memory changes or a strict check for initialization, structural migration, or full acceptance. [Skill](wiki-memory/SKILL.md) · [Upgrade instructions](wiki-memory/references/memory-model.md#升级独立工具与导航格式) · [Isolated A/B/C evaluation](wiki-memory/references/handoff-evaluation.md)

## Repository Structure

```text
mySkills/
├── AGENTS.md
├── README.md
├── README.en.md
├── wiki_memory/                       # Persistent engineering memory
└── video-transcript-polisher/
    ├── SKILL.md
    ├── references/
    │   ├── approved-output-backfill.md
    │   └── batch-review.md
    └── agents/
        └── openai.yaml
```

The repository follows a “one Skill per top-level directory” structure. Personal lecture samples and processed copies are local working materials and are not included in the repository by default.

## Adding a Skill

Create a dedicated top-level directory for every new Skill and include at least a `SKILL.md`. Add `agents/openai.yaml` or other resources only when they directly support the Skill. Follow the `skill-creator` guidance when creating or updating a Skill, and complete structural and content checks before committing. Repository-level engineering memory lives in [wiki_memory/](wiki_memory/README.md).

## Repository

[https://github.com/DewMysimple/mySkills](https://github.com/DewMysimple/mySkills)
