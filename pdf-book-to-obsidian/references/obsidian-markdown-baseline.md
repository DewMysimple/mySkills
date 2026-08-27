# Obsidian Markdown baseline

Use this reference when the selected output is intended for Obsidian. It is a
conversion checklist, not a copy of the Obsidian help site. The linked official
pages are the authority when a syntax detail changes or a book needs a feature
not covered here.

## Official sources

- [基本格式语法](https://obsidian.md/zh/help/syntax)
- [高级格式语法](https://obsidian.md/zh/help/advanced-syntax)
- [Obsidian 风格的 Markdown 语法](https://obsidian.md/zh/help/obsidian-flavored-markdown)
- [标注（Callout）](https://obsidian.md/zh/help/callouts)
- [附件](https://obsidian.md/zh/help/attachments)
- [属性](https://obsidian.md/zh/help/%E7%BC%96%E8%BE%91%E4%B8%8E%E6%A0%BC%E5%BC%8F%E5%8C%96/%E5%B1%9E%E6%80%A7)
- [文档规范](https://obsidian.md/zh/help/style-guide)

Obsidian combines CommonMark, GitHub Flavored Markdown, and LaTeX with
Obsidian-specific extensions. The official syntax pages describe the
supported extensions and should be consulted instead of assuming that every
Markdown application renders them in the same way.

## Baseline selection

- `obsidian`: default for this Skill. Prefer Obsidian Wiki links, file embeds,
  Callouts, and other documented extensions when they improve the book system.
- `commonmark`: opt-in compatibility mode. Prefer ordinary Markdown links and
  image links, avoid Wiki links and Callouts, and retain only broadly portable
  syntax.

User choices for a particular book override these defaults. Source fidelity
still takes priority over making a region look more structured.

## Conversion checklist

### Text and structure

- Use `#` through `######` for confirmed heading levels.
- Keep ordinary paragraphs separated by one blank line.
- Treat a single physical line break as a soft wrap unless the PDF evidence or
  the user's plan requires a hard break.
- Remove only confirmed PDF extraction artifacts; do not rewrite wording.
- Keep consecutive same-level list items together. Preserve blank lines needed
  by nested or multi-block list items.

### Links and embeds

Use Obsidian syntax in `obsidian` mode:

```markdown
[[A note]]
![[An attachment.png]]
![[A note#A heading]]
```

Use ordinary Markdown destinations in `commonmark` mode. Encode spaces in
portable link destinations or use an angle-bracket destination. Do not invent
links to concepts that are not present in the source or confirmed book plan.

### Callouts

For an explicit block-leading editorial label, use the corresponding Obsidian
Callout in `obsidian` mode:

```markdown
> [!NOTE]
>
> Original note text.
```

The default mappings are:

| Source label | Callout type |
| --- | --- |
| Note / Notes | `NOTE` |
| Tip / Hint | `TIP` |
| Warning / Caution | `WARNING` |
| Important | `IMPORTANT` |
| Danger / Error | `DANGER` |
| Example | `EXAMPLE` |

Only a label at the start of a block qualifies. Do not convert ordinary prose
such as “note that ...”. A standalone label may include the immediately
following continuous prose paragraphs until a heading, list, table, code,
image, source-page reference, or another structural block. Labels inside
lists, tables, code blocks, or other nested structures remain unchanged and
are reported for Agent review.

In `commonmark` mode, leave these labels as ordinary source text unless the
user explicitly chooses a compatible admonition convention.

### Code and tables

- Use fenced code blocks with a language identifier only when the PDF evidence
  supports the language; use `text` when it does not.
- Preserve indentation, blank lines, and characters inside code fences.
- Use Markdown tables only when headers and column boundaries are reliable.
- Escape `|` inside table cells.
- Keep uncertain visual tables in source-preserving form with a report entry.

### Properties and metadata

- Keep YAML frontmatter valid and at the beginning of the note.
- Generate only properties selected by the book plan, such as `tags`,
  `aliases`, or `cssclasses`.
- Do not place rich Markdown inside properties; keep property values small and
  machine-readable.

## Safety and review

- Never use CSS, multi-column layout, third-party plugin syntax, HTML, or web
  embeds as an automatic fallback.
- Use those features only after the Agent identifies a real need and the user
  confirms the book-specific choice.
- Preview representative rendered blocks before writing.
- Audit headings, list spacing, Callouts, links, embeds, tables, code fences,
  frontmatter, and source-page references after generation.
- Preserve uncertain regions and record why they were not converted.
