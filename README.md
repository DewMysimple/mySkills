# mySkills

[English](README.en.md)

## 项目简介

`mySkills` 是 DewMysimple 用来创建、维护和分享个人 Codex Skills 的仓库。

每个 Skill 都是一个独立的能力包，通常通过 `SKILL.md` 描述适用场景、处理原则和工作流程，并可根据需要提供 `agents/openai.yaml` 等辅助配置。

当前仓库包含课堂转录整理、PDF 书籍转 Markdown 和工程记忆三个独立 Skill。

## 当前 Skill

| Skill | 用途 |
| --- | --- |
| [video-transcript-polisher](video-transcript-polisher/SKILL.md) | 保真整理 Whisper / ASR 课堂转录 |
| [pdf-book-to-obsidian](pdf-book-to-obsidian/SKILL.md) | 按确认的方案将 PDF 书籍转为可导航的 Markdown 系统 |
| [wiki-memory](wiki-memory/SKILL.md) | 为工程配置和维护可交接的项目记忆 |

`video-transcript-polisher` 主要用于：

- 修复有充分证据的 ASR 错误和可明确判断的局部语法错误，恢复断句与自然段。
- 在讲者持续展开的主题切换处使用源文标题，按需将明确的步骤或并列事项排成列表。
- 保留讲者的语言、信息顺序、推理、例子、自我修正与不确定性，以及数字、专名、时间戳和说话人标签。
- 整理稿只呈现讲者表达过的内容，保留原始语言。
- 长篇转录需要分段时，按原文顺序编辑，核对覆盖范围和衔接后再保存。
- 默认将处理稿写入输入文件旁的 `processed/` 目录，保留原始文件。

## 使用方式

### 工程记忆 wiki-memory

[`wiki-memory`](wiki-memory/SKILL.md) 在工程根目录的 `wiki_memory/` 配置可交接记忆：未指定模式时小项目默认一页当前状态，日志可平铺；指定 `standard` 时完成概览、架构、约束、待办和问题五页的实质内容，并按六类目录保存日志，保留证据与未核实项。已验证事实随任务同步，未决选型保留为候选。支持检索、交接、体检和保留历史的压缩。

```text
使用 $wiki-memory 在当前工程根目录配置 standard 工程记忆，保留已有 AGENTS.md 和项目文档，并根据实际代码完成五页状态。
```

初始化工具默认预览，加 `--apply` 才写入；拒绝覆盖已有记忆。`wiki_memory/README.md` 是唯一导航与使用说明，`wiki_memory/AGENTS.md` 保存维护协议，不另建 `入口.md`；中文专题名称保留。已有子目录记忆和旧导航需要显式迁移，内容与历史保留；旧布局可只读检查，不等于符合新规范。项目内保存独立的维护工具，只需 Python 3.10+，无第三方运行依赖。单独更新 Skill 不会自动迁移其他项目或复制本仓库的记忆资料。

标准版的真实目录与虚构日志示例见 [日志布局样例](wiki-memory/assets/standard-log-layout/)。[LLM Wiki 理论原文](wiki-memory/references/llm-wiki.md) 随 Skill 保留供按需查阅，来源与工程化边界见 [记忆模型](wiki-memory/references/memory-model.md)。

3.4.0 保留 Schema 2。新 `init` 默认显式设置 `"link_style": "markdown"`。已有项目缺此字段时沿用 Wiki 导航和原 Markdown 日志表格；显式切换时编辑配置，预览 `index` 后再加 `--apply`。手写链接和历史正文保留。

```text
python -X utf8 wiki-memory/scripts/memory.py impact --project . --base <commit> --head HEAD
python -X utf8 wiki-memory/scripts/memory.py tool-diff --project .
```

`impact` 按 Git 变更和页面来源列出复核候选。可选 `verified_rev` 记录整页核实基线，文件变更只提供复核线索。`tool-diff` 对比工具版本声明、指纹及配置兼容性；审查差异后按授权同步项目独立副本和协议，保留定制。[升级说明](wiki-memory/references/memory-model.md#升级独立工具与导航格式) · [隔离 A/B/C 评测](wiki-memory/references/handoff-evaluation.md)

Skill 仍为显式调用。已接入项目的日常开发、检索和交接按项目协议进行；只读窄查询可按需定位，修改和接续保留完整启动读取。日常记忆修改后执行一次普通检查，初始化、结构迁移或明确完整验收时改用严格检查。两项专项只读命令均按需运行。

### 课堂转录 video-transcript-polisher

获取仓库后，将需要使用的 Skill 目录导入你的 Codex Skills 配置中，然后可以显式调用：

```text
Use $video-transcript-polisher to fix clear local errors and make sustained topic shifts easy to find while preserving what the speaker said.
```

这个 Skill 也支持在任务内容与其适用场景匹配时被自动发现。

## 仓库结构

```text
mySkills/
├── AGENTS.md
├── README.md
├── README.en.md
├── wiki_memory/                  # 本仓库的工程记忆，不是 Skill
│   ├── README.md                # 导航与使用说明
│   ├── AGENTS.md
│   ├── 当前状态/                 # 五页全局状态
│   ├── 知识/                     # 按 Skill 检索
│   ├── 决策/
│   ├── 日志/
│   └── 工具/memory.py
├── pdf-book-to-obsidian/
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   ├── scripts/
│   └── tests/
├── video-transcript-polisher/
│   ├── SKILL.md
│   ├── references/
│   │   ├── approved-output-backfill.md
│   │   ├── batch-review.md
│   │   └── long-transcripts.md
│   ├── scripts/
│   ├── tests/
│   └── agents/
│       └── openai.yaml
└── wiki-memory/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── assets/
    │   ├── protocol.md
    │   └── standard-log-layout/  # 六个实际分类目录及示例日志
    ├── references/
    │   ├── memory-model.md
    │   ├── handoff-evaluation.md # 按需运行的独立换会话评测
    │   └── llm-wiki.md           # 可选理论背景原文
    └── scripts/
        ├── memory.py
        ├── handoff_cases.py     # 临时工程评测材料生成器
        └── test_memory.py
```

仓库采用“一项 Skill 一个一级目录”的管理方式。个人课堂样本和处理稿属于本地工作材料，默认不纳入仓库。

## 仓库工程记忆

本仓库采用标准版工程记忆。只读窄查询按协议定位相关来源；修改、接续或影响较大的任务先读项目概览、当前约束和当前待办。已读且未变的内容可复用。 [工程记忆导航](wiki_memory/README.md) · [记忆维护协议](wiki_memory/AGENTS.md)

`wiki-memory/` 是可复用的能力包，`wiki_memory/` 保存本仓库的事实和交接信息，两者独立。完成有文件修改的任务时，按 [AGENTS.md](AGENTS.md) 同步记忆、验证、提交并推送。

本仓库有实质修改时，在根目录统一刷新索引并普通检查一次：

```text
python -X utf8 "wiki_memory/工具/memory.py" index --project "." --apply
python -X utf8 "wiki_memory/工具/memory.py" check --project "."
```

初始化、迁移或明确完整验收时，将 check 换成 check --require-ready，不连续运行两者。不因普通同步调用 Skill、运行迁移计划或重跑 Skill 的全套测试；遵守根 AGENTS 中的实际验证与交付要求。

## 新增 Skill

新增 Skill 时，为它创建独立的一级目录，并至少包含一个 `SKILL.md`。如果需要，可以添加 `agents/openai.yaml` 或其他直接服务于该 Skill 的资源。创建或修改 Skill 时遵循 `skill-creator` 的规范，并在提交前完成结构和内容验证。

## 项目地址

[https://github.com/DewMysimple/mySkills](https://github.com/DewMysimple/mySkills)
