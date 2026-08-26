# Agent Instructions for `mySkills`

This file contains the repository-level instructions for coding agents. It is intentionally concise and does not duplicate the full README.

## Repository purpose

`mySkills` is DewMysimple's collection of personal Codex Skills. Each Skill is an independently discoverable capability package with its own `SKILL.md`.

The current Skill, `video-transcript-polisher`, faithfully polishes Whisper/ASR video-lecture Markdown transcripts. It may correct strongly supported ASR wording, restore punctuation and paragraph structure, and apply restrained Markdown organization. It must not summarize, translate, expand, or rewrite the original lecture.

## Documentation and context

- `README.md` is the Chinese default overview for people visiting the GitHub repository.
- `README.en.md` is the English translation for people who request or prefer English documentation.
- For routine engineering or Skill tasks, do not read both README files. Read only the relevant language version when a repository overview is needed; prefer `README.md` by default.
- Treat this `AGENTS.md` as the source for agent-specific repository rules. Do not use README content as a substitute for these instructions.

## Directory management

- Use one Skill per top-level directory. Do not combine multiple Skills in one directory.
- Every Skill must contain `SKILL.md`. Add `agents/openai.yaml`, scripts, references, or assets only when they directly support that Skill.
- When creating or updating a Skill, read and follow the available `skill-creator` guidance. Use its initializer for a new Skill, but do not reinitialize an existing Skill.
- Do not add unnecessary README files, examples, scripts, or other maintenance structure inside a Skill.

## Working rules

- Inspect the current files and Git status before editing, and preserve unrelated user changes.
- Keep source lecture transcripts unchanged by default. Put local processed copies in a sibling `processed/` directory unless the user requests another destination.
- Treat lecture samples and processed copies as local working materials; do not copy or stage them by default.
- After changing a Skill, run applicable validation, including `skill-creator`'s `quick_validate.py`. If a dependency is unavailable, record the reason and complete feasible manual checks.
- Review the diff before committing. Commit, push, or perform other external Git operations only when the user explicitly requests them.
