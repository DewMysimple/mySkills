---
type: decision
status: active
kind: process
importance: high
updated: 2026-10-09
topic: memory-layout-and-navigation
sources: ["AGENTS.md", "wiki-memory/SKILL.md", "用户指令：2026-10-09 工程记忆必须位于工程根目录，取消入口.md，仅使用AGENTS.md与README.md，保留中文专题名称"]
---

# 根目录记忆与 README 统一导航

## 背景与选择

决策者：用户，2026-10-09。lion 的实践把记忆放在 `docs/wiki_memory/`，旧框架又将说明与导航拆成 README 和入口两份文档，增加了定位和维护成本。

所有新配置统一使用工程根目录的 `wiki_memory/`；本仓库同样采用该规范。用户进一步明确保留中文专题文件和目录名，仅取消 `入口.md`。

## 分工与验收

- `AGENTS.md` 保存维护协议；`README.md` 合并说明、模式选择依据和唯一导航。当前事实只在五页状态与相关专题维护。
- standard 保留项目概览、系统架构、当前约束、当前待办、已知问题五页，并采用框架约定的必需章节。不能仅凭文件存在或普通体检成功声称内容已就绪。
- 初始化页可以 proposed；交付时核实当前事实、填写证据和恢复信息，运行 `check --require-ready` 并人工核对事实与未验证范围。
- 已有历史保留，迁移只改导航和必要引用；旧位置不再保留第二套有效记忆。工具与协议升级必须显式执行。

## 影响与验证

3.0.0 升级调整了根目录约束、README 导航、配置版本和交付检查；不扩大 Git、部署或其他项目操作的授权。交付验证结果见本次任务日志，不能把本决策视为已经测试通过的证明。
