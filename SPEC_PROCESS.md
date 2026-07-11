# SPEC_PROCESS.md — 与 Superpowers 协作生成 Spec / Plan 的过程

> 项目：AI4SE 期末项目 A · Coding Agent Harness
> 主开发智能体：Claude Code（glm-5.2 会话）
> 冷启动智能体：fresh sonnet subagent（不同模型、零历史）
> 本文档覆盖：通用要求 §4.1（brainstorming 关键节点 + ≥3 轮迭代 + AI 建议取舍）与 §4.5（陌生智能体冷启动试运行）。

---

## 0. 协作过程概述

本项目严格按 Superpowers 七步工作流推进：

`brainstorming → writing-plans → (冷启动验证) → using-git-worktrees / subagent-driven-development → test-driven-development → requesting-code-review → finishing-a-development-branch`

- **brainstorming** 已在先前会话完成并签字确认，沉淀为 `docs/superpowers/specs/SPEC.md`（下文「SPEC」）。本节从该签字稿反推设计对话的关键节点与迭代（先前会话的实时对话未留存逐字稿，但设计决策完整编码于 SPEC；此处据 SPEC 忠实重建）。
- **writing-plans** 在本会话执行：调用 `superpowers:writing-plans` 技能，产出 `PLAN.md`（24 个 TDD 任务、canonical 接口、依赖/并行图）。
- **冷启动验证**（§4.5）在本会话执行并产出**真实证据**：派发一个与主智能体**不同模型**（sonnet vs glm-5.2）、**全新 session、零历史**的 subagent，仅给 SPEC + PLAN，令其尝试 T1/T6 并「遇不确定即暂停」。其报告暴露了 SPEC↔PLAN 的多处不一致与 Windows 路径盲区；据此对 SPEC/PLAN 做了修订（见 §4.5）。

---

## 1. brainstorming 关键节点（设计对话中被追问并敲定的决策）

brainstorming 技能的核心价值是「主动追问你究竟想做什么，分块呈现设计供签字」。下列是设计阶段被追问、并最终敲定的关键问题：

1. **「LLM 还是 harness，你的交付物到底是哪一层？」**
   - 追问动机：题目说「用 Superpowers 造一个 harness」，但 Superpowers 本身就是 harness，容易把宿主框架的能力误当成自己的产物。
   - 敲定：交付物是**我自己编码的 harness 内核**（主循环/工具分发/治理/反馈/记忆/配置），不是在现成 agent 框架上做配置。SPEC §13「实现边界声明」即据此写就，明确「宿主框架可辅助构建，但不能代替你所构建的那台机器运转」。

2. **「六个维度都做，还是挑一个深挖？」**
   - 追问动机：通用要求 §3.4 深度优先，A.4-D 要求「基础完整 + 一个重点维度深入」。
   - 敲定：六维度皆有最低实现，**治理（护栏/沙箱/HITL 状态机）为重点**。理由：治理纯由确定性代码构成、最易用 mock 单测、最契合 A.4-C「移除 LLM 后仍可验证」判据，且 HITL 审批 WebUI 本身就是治理的组成（不产生额外工作）。

3. **「反馈信号到底是代码还是提示词？」**
   - 追问动机：这是 A.4-B 的命门——「让 LLM 自行检查」是提示词版（不算实现），「写一个 pytest 解析器」才是代码版。
   - 敲定：反馈 = `TestRunner`（正则解析 pytest 输出 → 结构化 `TestFeedback`）+ `FeedbackInjector`（回灌为 tool message）。确定性代码，移除真实 LLM 仍可测。

4. **「真实 LLM 跑挂了，机制还算数吗？」**
   - 追问动机：A.4-C 的硬判据。
   - 敲定：所有核心机制替换为 `MockLLMClient`（脚本化 `LLMResponse`）后，用确定性单测验证；真实 DeepSeek 仅作可选集成测试，不作为机制验收标准。SPEC §12 测试策略据此设计三层（单元/集成/机制演示）。

5. **「凭据放哪？`.env` 够安全吗？」**
   - 追问动机：通用要求 §3.1，且 Windows 开发机无系统钥匙串的便利。
   - 敲定：`.env` + `python-dotenv`（明文风险已在 SPEC §4.2 威胁模型标注）；首次运行 `getpass` 隐藏录入、文件权限 600、查看状态只回显 `configured: true/false`。容器分发以 `-e` 注入，不入镜像。

---

## 2. 至少 3 轮关键迭代

### 迭代 1：从「做一个 coding agent」到「做 harness 这层工程」

- 起点设想：写一个能修测试的 agent。
- 追问：「那 agent loop、工具、治理这些工程，你是调框架还是自己写？」
- 处理决策：明确 **Agent = LLM + Harness**，LLM 只做「下一步决策」一行，其余全是工程。把交付边界从「一个能用的 agent」收敛到「一个可注入 mock、可单测、可治理的 harness 内核」。这一轮把项目从「应用」拉回到「工程深度」。

### 迭代 2：从「六个维度平均用力」到「治理深挖」

- 起点设想：决策/工具/记忆/治理/反馈/配置六维度各做一个模块。
- 追问：「深度优先要求一个 main contribution，你选哪个？」
- 处理决策：选治理。重写 §11 为「三层防护（ScopeFence→Guardrail→HITLStateMachine）全部确定性代码」，并把 HITL 状态机做成 `pending→approved|rejected` 单向迁移、带 `Approver` 可注入回调（让循环在 mock 下同步确定性运行）。记忆维度降为最小 `ContextStore`（YAGNI 跨会话持久化）。

### 迭代 3：从「dangerous_patterns 一锅烩」到「deny / gate 两级」

- 起点设想：所有危险命令（`rm -rf /`、`git push --force`）都走 HITL。
- 追问（自检）：「`rm -rf /` 即使人工批准也不该执行——HITL 不该成为毁灭性动作的逃生口。」
- 处理决策：把护栏拆成两级——`deny_patterns`（毁灭性，**硬阻断、不经 HITL**）与 `dangerous_patterns`（需审批，进 HITL），deny 优先。这让 §A.6 机制演示更干净：demo①纯护栏硬拦截 `rm -rf /`，demo③HITL 拒绝 `git push --force` 后 agent 改策略。该决策在冷启动后被回写进 SPEC §11.2/§11.5 与 PLAN T7。

> 这一轮恰好印证了 A.4 的精神：把「危险动作拦截」从提示词（「请不要删库」）落到代码（`guardrail.is_denied()` 返回 True 即阻断），且移除 LLM 仍可单测。

---

## 3. AI 建议的采纳与推翻

**采纳的 AI 建议：**
- 用 `python-dotenv` 而非 `export`（避免进 shell history）——采纳，写入 SPEC §8/§4.2。
- HITL 用可注入 `Approver` 回调而非异步阻塞——采纳，使循环在 mock 下同步确定性（A.4-C 友好）。
- 时间戳用 `float` 由调用方注入——采纳，保证状态机单测确定性。

**推翻/修正的 AI 建议：**
- AI 倾向把记忆做成「向量库 + 跨会话检索」以显工程量；**推翻**，降为最小 `ContextStore`（YAGNI——本项目重点在治理，记忆深挖会稀释主贡献，且 §A.4 明确「若以记忆为重点须自实现检索」，不在本重点）。
- AI 建议 `success` 作为可存字段方便构造；**修正**为派生 `@property`（避免与 `failed` 状态不一致）——此点在冷启动中被陌生智能体再次佐证（I2）。

**反思——brainstorming 技能的得失：**
- 做得好的：强制把「交付边界」「重点维度」「机制是代码不是提示词」这三个最容易在 AI 协作中含糊过去的命门摆上台面，逐项签字。它不是替我设计，而是替我**质询**。
- 让我不满的：brainstorming 产出的 SPEC 在「内部一致性」上缺乏自动校验——SPEC 正文（`Literal`、`datetime`、3.12）与随后 PLAN 的 paste-able 代码（`str`、`float`、3.11）出现多处不一致，而 brainstorming 没有提示去对账。正是这个缺口，让 §4.5 冷启动成为不可替代的环节（见下）。

---

## 4. §4.5 冷启动试运行（核心客观证据）

### 4.1 操作合规性

- 第二智能体类型**不同**：主开发智能体为本会话（glm-5.2）；冷启动 subagent 为 **sonnet**（不同模型），全新 session、零历史、不导入任何 memory。
- 仅提供 SPEC + PLAN，未补充任何口头解释。
- 指令：从 PLAN 选 T1（数据模型）+ T6（ScopeFence）自主推进，**「遇到不确定之处即暂停询问，而非凭猜测继续」**；工作限于临时 scratch 目录，不得 commit。
- 产出：6/6 测试通过（T1 三项、T6 三项），但报告暴露大量 spec 缺陷。**冷启动产出代码不予合并**（其目的是反馈而非实现），scratch 目录已清理。

> 局限声明：理想冷启动应跨**产品**（如 Codex / Gemini CLI）而不仅跨模型。本环境无法启动外部 CLI，故以「不同模型 + 零历史 + 仅 SPEC/PLAN」逼近。该逼近仍捕获了 §4.5 的核心价值——共享隐性上下文被清零后暴露的真实 spec 缺口。

### 4.2 陌生智能体在哪里暂停/提问、暴露了哪些 spec 缺陷

冷启动报告列出 14 个暂停点（G1–G14）与 10 条 SPEC↔PLAN 不一致（I1–I10）。关键缺陷（按严重度）：

| 编号 | 缺陷 | 严重度 |
|---|---|---|
| I1 | Python 版本：SPEC 3.12 vs PLAN 3.11 | 高（破坏环境） |
| I2 | `TestFeedback.success`：SPEC 字段 vs PLAN 属性 | 高（改 API 语义） |
| I6 | `Action`：PLAN 增加 `blocked/block_reason/approval_id/status`，SPEC 无 | 高（数据模型不匹配） |
| I7 | `ApprovalRecord` 时间戳：`datetime` vs `float` | 中 |
| I3–I5 | `role`/`layer`/`final_status`：`Literal[…]` vs `str` | 中 |
| G9–G12 | ScopeFence 在 **Windows 大小写/相对路径/不存在路径/符号链接** 上未指定（本机即 Windows） | 高 |
| G13 | `TestFeedback` 触发 `PytestCollectionWarning` | 低 |
| 内部 | PLAN「Shared Interfaces」列了 `created_at`，但 T8 实现里**漏了** `created_at` | 中 |
| I8 | 报告称 `AgentRunResult` 无 `executed_commands`——**实为误读**（SPEC §6 本就有） | 误报 |

> I8 这条误报本身就是信号：数据模型块不够醒目，导致陌生智能体扫读时漏看字段。据此我把 §6 数据模型块加了醒目注释。

### 4.3 据此对 SPEC / PLAN 做的修订（关键 diff）

**SPEC §6 数据模型（before → after）：**
```diff
-class Message:
-    role: Literal["system", "user", "assistant", "tool"]
+    role: str   # "system" | "user" | "assistant" | "tool"

 class Action:
     tool: str
     args: dict
     raw_llm_response: str | None
+    blocked: bool = False
+    block_reason: str | None = None
+    approval_id: str | None = None
+    status: str | None = None   # "approved" | "rejected" | None

-class GovernanceDecision:
-    layer: Literal["scope_fence", "guardrail", "hitl"] | None
+    layer: str | None = None   # "scope_fence" | "guardrail" | "hitl"

 class ApprovalRecord:
-    status: Literal["pending", "approved", "rejected"]
-    created_at: datetime
-    decided_at: datetime | None = None
+    status: str = "pending"
+    created_at: float = 0.0          # 调用方注入 → 确定性可测
+    decided_at: float | None = None
+    __test__ = False

 class TestFeedback:
-    success: bool
+    __test__ = False
+    @property
+    def success(self) -> bool: return self.failed == 0

 class AgentRunResult:
-    final_status: Literal["success", "failed", "max_iters", "error"]
+    final_status: str   # "success" | "failed" | "max_iters" | "error"
```
> 取舍：放弃 `Literal` 换「可直接粘贴的代码 + 运行时校验」（CI 不跑 mypy）；`success` 用派生属性避免与 `failed` 状态不一致；时间戳用 `float` 由调用方注入，呼应 A.4-C「移除 LLM 后确定性可测」。

**SPEC §8 技术选型：** `Python 3.12` → `Python 3.11+（开发机 3.11.9；Docker python:3.12-slim）`。

**SPEC §11.2 治理：**
- ScopeFence 补算法说明：`realpath + normcase + sep` 段安全比较；处理相对路径/符号链接/Windows 大小写/穿越；路径无需存在。
- Guardrail 明确**两级**：`deny_patterns`（硬阻断不经 HITL）+ `dangerous_patterns`（进 HITL），deny 优先。

**SPEC §11.5 配置：** `dangerous_patterns` 一锅烩 → 拆 `deny_patterns`（`rm -rf /`、fork bomb）+ `dangerous_patterns`（`drop table`、`git push --force`）。

**PLAN 对齐修订：**
- T1 `TestFeedback`、T8 `ApprovalRecord` 加 `__test__ = False`（G13）。
- T6 ScopeFence 实现改为 `_norm = normcase(realpath(normpath(p)))` + `rp == r or rp.startswith(r+sep)`（G9–G12），并新增 `test_relative_path_normalized`（相对路径进出根）。
- T8 `ApprovalRecord` 补 `created_at: float = 0.0`（修内部不一致）。

### 4.4 冷启动结论

陌生智能体给出的清晰度评分 **4/10**——「基本想法在，但必须靠 PLAN 才能实现，且 SPEC↔PLAN 有 8 处不一致，权威来源不清」。这与 §4.5 的预期吻合：主开发智能体与我在 brainstorming 沉淀的隐性上下文，让我**高估了 SPEC 的清晰度**；冷启动把每个未明文写下的假设变成了一个具体的「我猜了 X」暂停点。修订后 SPEC/PLAN 已对齐到单一权威定义，可进入实现阶段。

---

## 5. 一句话总结

brainstorming 守住了「做什么、做哪层、机制是代码」的命门；writing-plans 把设计落成可执行的 TDD 任务；而 §4.5 冷启动是唯一能刺破「主智能体与我的共享上下文造成的清晰度幻觉」的环节——它在本项目里抓出了 3 条高严重度不一致与一组 Windows 路径盲区，这些是单人项目中最接近同侪评审的真实反馈。
