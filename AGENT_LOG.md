# AGENT_LOG.md — AI4SE 期末项目 A · Coding Agent Harness

> 按时间顺序记录关键节点：时间戳与 task 编号、触发的 Superpowers 技能、关键 prompt/context 配置、subagent 输出关键片段或 commit hash、人工干预、教训。本日志是实现工作最重要的「过程证据」。

---

## 阶段 0：规约与计划（brainstorming → writing-plans）

- **2026-07-08** `superpowers:brainstorming`（先前会话）：产出并签字 `docs/superpowers/specs/SPEC.md`。关键决策：交付物=自实现 harness 内核（非框架配置）；重点维度=治理；反馈=代码解析器（非提示词）；mock-LLM 确定性测试。
- **2026-07-10** `superpowers:writing-plans`：产出 `PLAN.md`，24 个 TDD 任务、canonical 接口、依赖/并行图。镜像到 `docs/superpowers/plans/2026-07-10-coding-agent-harness.md`。
  - prompt 配置：要求「每步 2–5 分钟、明确文件路径、明确验证步骤（含失败测试）、无 placeholder、类型跨任务一致」。
  - 教训：writing-plans 产出代码完整，但**不校验 SPEC↔PLAN 内部一致性**——这成为冷启动的价值所在。

## 阶段 1：冷启动验证（§4.5）

- **2026-07-10** 派发**陌生智能体**冷启动：fresh **sonnet** subagent（与主开发智能体 glm-5.2 不同模型、零历史、仅 SPEC+PLAN），attempt T1+T6，pause-on-uncertainty。工作目录 `_coldstart_scratch/`（已清理，产出不予合并）。
  - 输出关键片段（commit/状态）：6/6 测试通过；但报告 **14 个暂停点（G1–G14）+ 10 条 SPEC↔PLAN 不一致（I1–I10）**。
  - 高严重度：I1 Python 3.12↔3.11；I2 `TestFeedback.success` 字段↔属性；I6 `Action` 缺治理字段；I7 时间戳 datetime↔float；G9–G12 ScopeFence Windows 大小写/相对路径未指定；PLAN 内部 T8 漏 `created_at`。
  - 误报 1 条（I8：称 `AgentRunResult` 无 `executed_commands`，实为误读——但提示数据模型块不够醒目）。
  - 人工干预：据冷启动对 SPEC/PLAN 做修订（diff 见 `SPEC_PROCESS.md §4.3`）。澄清度评分 4/10 → 修订后对齐为单一权威定义。
  - 教训：**冷启动是刺破「主智能体共享上下文造成的清晰度幻觉」的唯一环节**，抓出了 3 条高严重度不一致与一组 Windows 盲区——单人项目中最接近同侪评审的真实反馈。

## 阶段 1.5：pre-flight plan review（subagent-driven-development 启动前扫描）

- **2026-07-10** `superpowers:subagent-driven-development` 启动前的 plan 扫描，发现 3 处冷启动未覆盖的集成 bug（冷启动仅做 T1/T6）：
  - T15 `AgentLoop`：残留 `self.context_store.add_message = None` noop；`executed.append((...))` 把 tuple 塞进 `list[str]`；mock 耗尽时 `StopIteration` 会崩循环；`FeedbackInjector` 用了**独立** `ContextStore`（反馈回灌到 LLM 看不见的地方）。
  - T16 CLI：同上「独立 store」bug。
  - T18 集成测试：先注册 ScriptedTool(run_tests) 再 `register_builtins`，后者覆盖前者。
  - 人工干预：已直接修订 PLAN（5 处 Edit）。教训：**writing-plans 的集成级代码需在 dispatch 前再过一遍**——逐任务 TDD 测试红绿不保证跨任务装配正确。

## 阶段 2：subagent-driven 实现（进行中）

> 批次化说明（deviation，依通用要求 §3.6 记录）：将 24 个 PLAN task 按内聚的 TDD 循环合并为 8 个 dispatch unit（Unit 1 = T1–T5，Unit 2 = T6–T9，…）。理由：多个 PLAN task <15 行且共享文件/测试循环，逐行 dispatch 会把开销乘以 N 而无额外评审价值；仍保持「每 unit 一个新鲜 subagent + 两阶段评审 + 提交」的纪律。模型选择：机械转写+测试用 haiku；集成/判断用 sonnet；最终全分支评审用最强可用。

| Unit | PLAN tasks | 模型 | 状态 | commit |
|---|---|---|---|---|
| 1 | T1–T5 core | haiku | 进行中 | — |
| 2 | T6–T9 governance ★ | sonnet | 待 | — |
| 3 | T10–T14 tools/feedback/memory | haiku | 待 | — |
| 4 | T15 loop ★ | sonnet | 待 | — |
| 5 | T16–T17 cli/web | sonnet | 待 | — |
| 6 | T18–T19 integration/demo ★ | sonnet | 待 | — |
| 7 | T20–T22 packaging/docker/CI | haiku | 待 | — |
| 8 | T23 README | sonnet | 待 | — |
