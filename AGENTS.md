# Agent Instructions for `mySkills`

This file contains the repository-level instructions for coding agents. It is intentionally concise and does not duplicate the full README.

## Repository purpose

`mySkills` is DewMysimple's collection of personal Codex Skills. Each Skill is an independently discoverable capability package with its own `SKILL.md`.

The `video-transcript-polisher` Skill faithfully polishes Whisper/ASR video-lecture Markdown transcripts. It may correct strongly supported ASR wording, restore punctuation and paragraph structure, and apply restrained Markdown organization. It must not summarize, translate, expand, or rewrite the original lecture. Other Skills have their own task contracts in their respective `SKILL.md` files.

## Documentation and context

- `README.md` is the Chinese default overview for people visiting the GitHub repository.
- `README.en.md` is the English translation for people who request or prefer English documentation.
- For routine engineering or Skill tasks, do not read both README files. Read only the relevant language version when a repository overview is needed; prefer `README.md` by default.
- Treat this `AGENTS.md` as the source for agent-specific repository rules. Do not use README content as a substitute for these instructions.
- Engineering memory lives in the project-root `wiki_memory/`. `wiki_memory/AGENTS.md` defines its protocol and `wiki_memory/README.md` is its sole navigation document; read the project overview, global constraints, and current todos, then task-related architecture, decisions, knowledge, and logs as needed. Keep Chinese topic names; do not create a separate `入口.md`.

## Directory management

- Use one Skill per top-level directory. Do not combine multiple Skills in one directory.
- Every Skill must contain `SKILL.md`. Add `agents/openai.yaml`, scripts, references, or assets only when they directly support that Skill.
- When creating or updating a Skill, read and follow the available `skill-creator` guidance. Use its initializer for a new Skill, but do not reinitialize an existing Skill.
- Do not add unnecessary README files, examples, scripts, or other maintenance structure inside a Skill.
- `wiki-memory/` is a reusable Skill; `wiki_memory/` is this repository's engineering memory. The latter is repository documentation, not another Skill or an asset to distribute with every Skill.

## Working rules

- Inspect the current files and Git status before editing, and preserve unrelated user changes.
- Keep source lecture transcripts unchanged by default. Put local processed copies in a sibling `processed/` directory unless the user requests another destination.
- Treat lecture samples and processed copies as local working materials; do not copy or stage them by default.
- After changing a Skill, run applicable validation, including `skill-creator`'s `quick_validate.py`. If a dependency is unavailable, record the reason and complete feasible manual checks.
- The user reaffirmed the standing workflow on 2026-10-07: before the final reply for each completed task that changes repository files, synchronize relevant engineering memory, run applicable validation, review the diff, commit the task's changes, and push the current branch to its configured upstream. No further confirmation is needed for this routine commit and push.
- Stage explicit task paths or hunks, including previously unfinished changes from the same task. Preserve unrelated pre-existing changes and other tasks' staged work; do not include them automatically. Read-only conversations need no empty commit.
- Report the commit and push result. If validation, conflicts, credentials, or remote changes block delivery, preserve the work and report the specific blocker; do not force-push or claim delivery succeeded.

## Engineering memory

- Keep durable project facts in `wiki_memory/当前状态/`, confirmed design choices in `wiki_memory/决策/`, stable working knowledge in `wiki_memory/知识/`, and task history in `wiki_memory/日志/`.
- After a substantive task, append one concise log entry and refresh indexes with `python -X utf8 wiki_memory/工具/memory.py index --project . --apply`.
- Run `python -X utf8 wiki_memory/工具/memory.py check --project .` before completing a memory change. Do not delete historical logs or overwrite an active decision without explicit authorization.
- `wiki_memory/工具/memory_lint.py` is retained as a historical tool. Use `memory.py` for current maintenance; the old index command rewrites the whole log index and must not be mixed with the marked-area generator.
