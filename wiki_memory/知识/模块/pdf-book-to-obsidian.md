---
type: knowledge
status: active
kind: module
importance: high
updated: 2026-10-07
verified: 2026-10-07
topic: skill-pdf-book-to-obsidian
sources: ["pdf-book-to-obsidian/SKILL.md", "pdf-book-to-obsidian/scripts/pdf_book_pipeline.py", "pdf-book-to-obsidian/tests/test_pipeline.py", "pdf-book-to-obsidian/references/layout-repair.md"]
---

# Skill：PDF 书籍转换

入口是 `pdf-book-to-obsidian/SKILL.md`；`scripts/pdf_book_pipeline.py` 承担提取、预览、生成、审计和回滚；专题修复脚本处理布局、图片、结构、目录等；`references/` 保存任务契约和维护规范。

- 保留原书语言、内容与顺序，先检查 PDF 和讨论方案，确认目标位置、粒度及相关选择后再生成正式输出。Obsidian 是可选的消费端。
- 已生成 Markdown 的局部维护与整书转换分别处理；保留原 PDF、手写内容及可恢复备份，按实际来源证据判断结构。
- 此页只记录已检查的职责与边界；本轮开始前已有的行为修改仍待所属任务验证，见 [[当前状态/当前待办.md|当前待办]]。

现有测试入口（本轮未执行）：

```text
python -X utf8 "pdf-book-to-obsidian/tests/test_pipeline.py"
```

接续前核对 Python 与 PDF 相关依赖；该测试文件导入 `reportlab` 以及本目录转换模块。2026-10-07 本轮仅 Skill 结构校验通过，不代表 PDF 修复功能已通过行为测试。
