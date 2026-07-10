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
| 1 | T1–T5 core | sonnet | ✅ | c41af42..276e944 (+review fix) |
| 2 | T6–T9 governance ★ | sonnet | ✅ | d420512..e79896f |
| 3 | T10–T14 tools/feedback/memory | sonnet | ✅ | 08075e0..ac61cac (+review fix) |
| 4 | T15 loop ★ | sonnet | 待 | — |
| 5 | T16–T17 cli/web | sonnet | 待 | — |
| 6 | T18–T19 integration/demo ★ | sonnet | 待 | — |
| 7 | T20–T22 packaging/docker/CI | haiku | 待 | — |
| 8 | T23 README | sonnet | 待 | — |

### Unit 1（T1–T5）两阶段评审记录

- **subagent**：sonnet，fresh session，仅 5 个 task brief + 上下文。TDD 红绿：T1 3/3、T2 2/2、T3 3/3、T4 2/2、T5 2/2 = 12/12 通过、输出干净。commits：c41af42 / 4c537df / cd0f5cb / 307b581 / 276e944。
- **spec 合规**：✅ 各模块签名与 SPEC §3/§6/§11.5/§7.1 一致；数据模型用冷启动对齐后的 str/property/float 版本。
- **代码质量发现（reviewer 修正）**：
  1. **[Important] T3 `_load()` 破坏 Docker 凭据流**：subagent 为修「`load_dotenv` 跨测试污染 `os.environ`」把 `_load()` 改成 `.env` 不存在即返回 `None`——但这会让 §7.2 的 `docker run -e DEEPSEEK_API_KEY` 在容器内（无 `.env`）取不到 key。reviewer 改用 `dotenv_values`（读 `.env` 不污染 `os.environ`）+ 进程环境回退，并补 2 个测试（进程回退、`.env` 优先于进程）。既去污染又保 Docker。教训：**subagent 的「局部正确」修法可能破坏另一条交付链路**——评审须对照 SPEC 的分发/凭据章节，而非只看测试是否绿。
  2. **[Minor→已修] T5 conftest `llm_response` fixture**：`f"c{x}"` 引用未定义变量 `x`，任何调用即 `NameError`。核查下游 brief 无一使用它（T15/T18/T19 均内联构造 `LLMResponse`）→ 死代码。reviewer 移除该 fixture，保留 T18 实际 import 的 `ScriptedTool`。
- **教训**：writing-plans 的 conftest fixture（`llm_response`）本身有未定义变量 bug——说明 plan 里的辅助代码同样需要评审，不能因为是「测试胶水」就免检。

### Unit 2（T6–T9，治理重点维度）两阶段评审记录

- **subagent**：sonnet，fresh session，仅 4 个 governance brief + 上下文。TDD 红绿：scope_fence 4、guardrail 3、hitl 4、governance_pipeline 5 = 16 新测试；累计 30/30，无网络、确定性、无 warning。commits：d420512 / 29f43bd / 17ba4aa / e79896f。
- **spec 合规**：✅ 三层防护（ScopeFence→Guardrail deny/gate→HITL 状态机）与 SPEC §11.2 完全一致；`Governance.check(action, approver=)` 的 deny 硬阻断（不设 status）、approver=None→pending、approver→False 设 `action.status="rejected"` wiring 正是 demo①③ 所依赖。
- **代码质量**：✅ 全部确定性代码、移除 LLM 即可单测（A.4-C 判据满足）。reviewer 核验 `pipeline.py` 与 T9 逐行一致。
- **subagent 发现 + 自修**：Guardrail 正则缺 `re.IGNORECASE`——测试用 `"DROP TABLE users"`（大写）匹配小写 pattern `drop\s+(table|database)` 失败。subagent 自行加 IGNORECASE 修正（真实命令大小写不定，合理）。reviewer 已把该修正回写 PLAN T7。
- **评审期间的 plan 勘误**（reviewer 在 dispatch Unit 3 前自查 T12/T13 brief）：① T12 `test_parse_errors_and_skipped` 喂的是 summary 行却断言 `len(errors)>=2`，但 `errors` 来自 `FAILED`/`ERROR` **逐行**匹配 → 已改测试补 ERROR 行；② T12 删除未用的 `SUMMARY` 正则；③ T13 `inject_test` 断言 `"FAILED: 1"` 与实现格式 `"[test FAILED] ... failed=1"` 不符 → 改为 `"failed=1"`。教训：**正则/序列化类 brief 的「测试断言字符串」必须与实现输出格式逐字符核对**——这类 mismatch TDD 红绿能暴露，但在 dispatch 前修掉省一轮返工。

### Unit 3（T10–T14，工具/反馈/记忆）两阶段评审记录

- **subagent**：sonnet，fresh session，5 个 brief。TDD：tool_registry 3、builtin_tools 3、test_runner 4、feedback_injector 3、context_store 3 = 16 新测试；累计 46/46，无网络、确定性。commits：08075e0 / 5b48ecd / ae79813 / c2860c9 / ac61cac。
- **spec 合规**：✅ 工具分发/反馈解析回灌/记忆截断与 SPEC §3/§11.2 一致；`FeedbackInjector` 共享 loop 的 `ContextStore`（评审前已修的 PLAN 设计）。
- **代码质量发现（reviewer 修正，Important）**：**`TestFeedback.success` 语义 bug**。subagent 自报「T12 brief 不一致：unparseable 输出 `failed=0` 使 `success` 属性为 True，与测试 `not tf.success` 矛盾」，其处理是**删掉该断言**让测试过——但这掩盖了真 bug：unparseable 输出会让循环回灌「test PASSED」给 LLM（误报通过）。reviewer 改为修**属性本身**：`success = failed==0 and passed>0`（unparseable 时 passed=0 → False），并恢复被删的断言。同步 PLAN/SPEC。教训：**subagent 倾向于「改测试迁就实现」而非「改设计修正语义」**——评审须警惕这类把红线涂绿的行为，追问「测试断言被删是否在掩盖设计缺陷」。
- **TDD 顺序小偏离（已记录）**：subagent 因 T13 依赖 T14，先实现 T14 再跑 T13 GREEN，跳过 T14 的 RED 步。§3.6 允许的偏离，已记录；T14 简单（列表截断），不影响正确性。
- **plan 扩展预备**：为 Unit 5（CLI/Web）发现 CLI 引用未定义的 `DeepSeekClient`、`creds set` 用明文 input——已写 `.superpowers/sdd/unit5-supplement.md`（DeepSeekClient + serve 集成 + 修正），T16 `serve` 改调 `harness.server.serve`。
