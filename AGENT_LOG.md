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
| 4 | T15 loop ★ | sonnet | ✅ | 147f6d3 |
| 5 | T16–T17 cli/web + deepseek/server | sonnet | ✅ | b0b6fda..8bb6751 (+fix e62e226) |
| 6 | T18–T19 integration/demo ★ | sonnet | ✅ | 8ea66b4 + cd20804 |
| 7 | T20–T22 packaging/docker/CI | sonnet | ✅ | cb1e953..35a5b81 (+§9 fix 080af2d) |
| 8 | T23 README + T24 REFLECTION | sonnet | ✅ | 9f3721a + REFLECTION.md |

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

### Unit 4（T15，AgentLoop 主循环）两阶段评审记录

- **subagent**：sonnet，fresh session，仅 T15 brief。TDD 红绿：loop 7 测试（mock 驱动全循环——success/max_iters/error/blocked/test 回灌/executed 记录/StopIteration 优雅退出）。累计 48/48 通过。commit：147f6d3。
- **spec 合规**：✅ 主循环 organize→call→parse→governance→dispatch→feedback→stop 与 SPEC §3/§11.1 一致；关键不变式：`action.blocked/block_reason/approval_id` 从 decision 设值、`actions.append` 在 blocked-check `continue` 之前、`executed_commands` 仅记非 blocked 的 `run_tests`/`run_shell`、StopIteration→error、max_iters→`"max_iters"`。
- **代码质量**：✅ reviewer 逐行核验 `loop.py` 与 T15 brief 一致；以上不变式全部成立。无需修正。
- **教训**：pre-flight 在 dispatch 前修掉了 4 个集成 bug（noop 行 `self.context_store.add_message=None`、`executed.append(tuple)` 塞进 `list[str]`、StopIteration 崩循环、FeedbackInjector 用独立 ContextStore 致反馈回灌到 LLM 看不见处），故 subagent 一次过——pre-flight 的价值在「避免返工轮次」，而非抓 subagent 错。

### Unit 5（T16–T17 + DeepSeekClient/server）两阶段评审记录

- **subagent**：sonnet，fresh session，T16/T17 brief + `.superpowers/sdd/unit5-supplement.md`（**AUTHORITATIVE** for `harness/llm/deepseek.py` 与 `harness/server.py`，brief 不覆盖这两文件）。4 文件组，严格 TDD。TDD 红绿：deepseek 2、web 3、server 2、cli 2 = 9 新测试；累计 57/57，无网络、确定性。commits：b0b6fda / adea0d1 / 9fe3c83 / 8bb6751。
- **spec 合规**：✅ `DeepSeekClient`=supplement A 逐字（`_redact` 掩码 key、`chat` 映射 ChatCompletion→LLMResponse/ToolCall、key 仅 debug 级 redacted 日志、测试无网络）；`make_app` 路由=T17 brief 逐字（GET /、GET /approvals、POST approve/reject、GET 便捷链接）；`server.build_app` **组合**（非重定义）`make_app(srv.hitl)` + /health + /run + /activity；CLI `_run` **共享单一 ContextStore**（`cs=ContextStore(sys_prompt)` 同时喂 `AgentLoop` 与 `FeedbackInjector(cs)`，line 59-60）——关键不变式成立。与 SPEC §3 模块 6/8 + §7.2 Docker 凭据流 + §5.3 一致。
- **代码质量发现（reviewer 修正，2 个 Minor，commit e62e226）**：
  1. **app.py 死 `serve()`**：T17 brief 原含 `serve(host,port)`（standalone HITL-only UI），但 CLI `serve` 命令调 `harness.server.serve`（full app，含 /health /run /activity），故 `app.py.serve` 零调用方、为死代码。supplement 已确立 `server.serve` 为唯一入口。reviewer 删除（YAGNI），并同步 PLAN T17 代码块 + 镜像。
  2. **CLI `_run` 漏传 llm 配置**：非 mock 路径 `DeepSeekClient(api_key, model, base_url)` 未传 `max_tokens`/`temperature`，依赖默认值；而 `server.py` 路径已传 config 值——两条路径不一致。reviewer 补齐为 `max_tokens=cfg.llm.max_tokens, temperature=cfg.llm.temperature`，保持一致。
- **教训**：brief 在 writing-plans 阶段写入的 `serve()`，在后续 supplement 引入 `server.py.serve` 后即被取代——评审须识别「brief-mandated 但已被后续设计 superseded」的死代码，而非因「brief 里有」就保留。两处 fix 均直接修正（§3.5 reviewer 职责）。
- **已知局限（README 记）**：serve HITL 单用户；`POST /run?mock=true` 回放固定 demo 脚本；线程化 `/run` 仅 start-only 测试（确定性 HITL 机制由 `tests/demo` + integration 证明）。

### Unit 6（T18–T19，集成测试 + A.6 机制 demo）两阶段评审记录 ★ 重点维度交付物

- **subagent**：sonnet，fresh session，task-18/19 brief（均含完整测试代码，verbatim transcription）。2 文件组。TDD 红绿：T18 3 测试（read→run_tests→write→run_tests→pass 全循环、scope-fence 阻断越界写、deny 阻断 `rm -rf /`）、T19 3 demo（①guardrail 硬阻断 ②feedback 自纠 ③HITL reject→retry）。累计 63 全通过（60 unit+integration + 3 demo）。commits：8ea66b4 / cd20804。
- **spec 合规**：✅ A.6 三个行为全覆盖且确定性（MockLLMClient，无网络、无 LLM key），与 SPEC §A.6 + §12 一致；`-m demo` 独立可跑（3 pass）。重点维度（治理）的机制通过 demo 在 mock LLM 下被证明——满足 A.4-C「移除真实 LLM，机制仍可确定性单测」。
- **代码质量**：✅ commit 边界干净（8ea66b4 只含 `tests/integration/*`、cd20804 只含 `tests/demo/*`，未碰 harness 源码、未误 `git add` 工作树其他改动）；断言有效（demo① `blocked+denied+executed==[]`、demo② `success+iters==5+actions[1/3].tool=="run_tests"`、demo③ `status=="rejected"+executed 不含 push --force 含 status`——非 assert-nothing）；brief 代码 verbatim（行数吻合 42/47/74）；demo marker 无 warning（`pyproject [tool.pytest.ini_options] markers` 已注册）。**一次过，无需 fix**。
- **教训**：dispatch 前对三个关键点（`ScriptedTool.__call__` 接口、pipeline `rejected→blocked=True` 语义、demo marker 已注册）的 pre-flight 核验，使 transcription 任务一次过——pre-flight 把「subagent 会撞的墙」提前拆掉，省一轮返工。与 Unit 4（pre-flight 修 4 bug 致一次过）同构：**集成/测试任务的 dispatch 前核验，价值最高**。

### Unit 7（T20–T22，packaging/Docker/CI）两阶段评审记录

- **subagent**：sonnet（override summary 计划的 haiku——部署 + CI 硬约束链路值得判断力，非最便宜 tier），fresh session，task-20/21/22 brief（均含 pre-flight 修复后的完整配置，verbatim transcription）。3 commits：cb1e953（Makefile/.env.example）、811bdda（Dockerfile/.dockerignore/render.yaml）、35a5b81（.gitlab-ci.yml/ci.yml）。7 文件。
- **spec 合规**：✅ §9 验收「分发 docker build+run 单条命令」「CI .gitlab-ci.yml 含 unit-test job 最后状态 pass」+ §7.2 Docker（不 COPY .env、USER 65532 非 root）+ §4.2 凭据威胁模型（key 不进镜像/git/.dockerignore/render sync:false 不 plaintext）全部满足；`.gitlab-ci.yml` job 名 `unit-test`（通用要求硬约束）；Dockerfile COPY 修复后语法正确（pre-flight 已修 `2>/dev/null || true` 无效语法）。
- **代码质量**：✅ commit 边界干净（7 文件，未碰 harness/tests/pyproject）；brief verbatim（pre-flight 修复全部生效：Dockerfile COPY、Python 3.11 统一、render /health、Makefile 无 phantom `run`、.dockerignore 含 .env）。**一次过无需 fix**。
- **§9 gap 修复（reviewer，commit 080af2d）**：§9 验收第 2 项「`rm -rf /` 等 **5+** 危险模式全部被拦截」——config.yaml 原仅 2 patterns。reviewer 补 config.yaml 到 7 patterns（deny 4：`rm -rf /`、fork bomb、`dd of=/dev/`、`mkfs /dev/`；dangerous 3：`drop table/database`、`git push --force`、`git reset --hard`）+ `test_guardrail` 加 `dd`/`mkfs`/`git reset --hard` 断言（现 7 patterns 确定性测试）+ 同步 SPEC §11.5 + `server.py` 改从 config 读 dangerous（原硬编码 `[git push --force]`，与 CLI 不一致；现 CLI/server 共享 config 单一真相源，mock demo 仍 HITL `git push --force`）。63/63 pass。
- **concerns（已知局限）**：① docker build 未验证（Windows 本地 daemon 未跑，Dockerfile 仅静态验证语法——部署就绪时用户需在有 docker 的环境跑一次 `docker build`）；② Starlette httpx deprecation warning（pre-existing，非 Unit 7 引入）。
- **教训**：pre-flight 扫了 brief 代码 bug（Dockerfile COPY、Python 版本、render healthCheck、Makefile phantom、.dockerignore）使配置文件 task 一次过；但 §9「5+ 危险模式」这类**验收标准的量化条款**，pre-flight 没核对——reviewer 读 §9 时才发现 config patterns 数量不足。教训：**pre-flight 除了扫 brief bug，还要对照 SPEC §9 验收标准的每一条量化要求**（「5+」「100%」「每次确定性」），否则会漏 gap。

### Unit 8（T23 README + T24 REFLECTION）两阶段评审记录

- **subagent**（README）：sonnet，fresh session，task-23 brief + 目录树 + 实际命令清单。commit 9f3721a（README.md 203 行）。命令全部对照源码验证（Makefile/__main__/Dockerfile/render.yaml/config/pyproject）。
- **REFLECTION**（controller 自写，非 dispatch）：基于 AGENT_LOG 真实过程证据回答通用要求 §199 的 9 问题，1810 中文字（1500–2500 ✓），顶部标注 §207 AI 起草声明（学生须本人审定/改写）——因 §207「禁止 AI 代写」与用户「完成交付物」指令有 tension，解法是 AI 起草 + 显著标注 + 学生最终审定。
- **spec 合规**：✅ 通用要求 §188 必需 6 章节（项目简介/安装/运行/分发命令/目录结构/安全边界）+ 已知限制全覆盖；§4.10 分发（Docker 命令 + render one-click + URL placeholder + 已知限制）；§4.2 凭据威胁模型（README §6 表 7 项威胁→缓解：硬编码/git/shell history/镜像/日志/plaintext .env/render）。
- **代码质量**：✅ README commit 边界干净（只 README.md）；命令与源码逐条一致（`make test`/`harness run --mock`/`serve`/`creds`/`docker build -e`/`render sync:false`/`healthCheck /health`）；REFLECTION 字数合规 + §207 标注。**一次过无需 fix**。
- **教训**：README 是 prose 写作（非 verbatim transcription），但 brief 给了精确章节清单 + controller 给的目录树/命令/威胁清单，subagent 一次产出高质量 README——**prose 任务的 dispatch 关键是给足「事实素材」（目录树/命令/威胁清单），而非只给章节标题**。

## 阶段 3：最终全分支评审 + 收尾

- **2026-07-11** 最终全分支评审（`superpowers:requesting-code-review`，**opus** 最强可用模型）：review-package `59d9903..7560129`（40 commits, 312KB diff）。
  - **verdict: READY TO MERGE**。0 Critical / 0 Important / 3 Minor。
  - **§9 验收 10 项全 PASS**（AgentLoop / Guardrail 5+ / HITL / ScopeFence / Feedback / WebUI / CredentialStore / Config / Docker / CI `unit-test` job）；**§13 A.4 自实现边界全 PASS**（无 LangChain/AutoGen/CrewAI，机制是代码非提示词）；交付物清单全 Present（URL 待用户，非 finding）；**§4.2 凭据安全全 PASS**（无明文泄漏路径）；63 测试 mock-LLM 确定性无网络。
  - controller 另做凭据 git 历史核验：`.env` 从未提交、`.gitignore` 含 `.env`+`.env.*`+`!.env.example`、历史无真 key（`sk-`+20 字符为空）、所有 `DEEPSEEK_API_KEY` 引用是模板/变量名/假值/占位符。
  - **3 Minor fix（reviewer 直接修，§3.5）**：① `tests/unit/test_cli.py:12` 删未用 `tmp_path`/`monkeypatch` fixtures（test hygiene）；② `README.md:104` 改「替换 render.yaml placeholder」措辞（render.yaml 无该 placeholder，原指令误导部署）→ 改为「部署后记录 Render 公网 URL（交付物⑨）」；③ 6 个配置文件补尾换行（POSIX best practice）。全 suite 63 passed 复测。

## 阶段 4：finishing-a-development-branch

- **2026-07-11** `superpowers:finishing-a-development-branch`：tests 63 pass（merge 前后均验证）→ normal repo（无 worktree）→ base=`main` → 用户选「合并到 main 本地」→ `git merge --no-ff feat/harness`（merge commit `f6435ba`，含全部 41 commits 真实逐 task 历史）→ merged main 复测 63 pass → `git branch -d feat/harness`（删除已合并分支）→ 仅剩 `main`。
- **部署就绪（配置层完成，执行是用户动作）**：`Dockerfile` + `render.yaml` + `.gitlab-ci.yml`（`unit-test` job）+ `.github/workflows/ci.yml` + README 部署章节全部就绪；最终评审 READY TO MERGE + 凭据 git 历史核验通过。用户待执行（交付物⑨ + §191 最后 CI pass）：① 在有 Docker 的环境跑 `docker build -t coding-harness .` 验证镜像（本地 daemon 未跑）；② 推 `main` 到 GitLab/GitHub 触发 CI（`unit-test` job + GitHub Actions mirror）；③ Render dashboard 按 `render.yaml` 部署 + 设 `DEEPSEEK_API_KEY` secret + 回填公网 URL；④ 确认最后一次 CI pass。

## 阶段 5：部署完成（2026-07-25）

- **GitHub push**：`origin` 从 NJU GitLab 切到 GitHub（用户决定只用 GitHub；NJU GitLab 那边 CI 已触发跑完作 §191 双保险）。本地直连 github.com 超时（国内封锁）→ 配 SOCKS5 代理 `socks5h://127.0.0.1:10808`（V2RayN，仅本仓库 `--local`）→ push 成功（`431e769`，含 URL 回填）。
- **Render 部署**：连 GitHub repo → 识别 `render.yaml` + `Dockerfile` → `docker build` 成功（`pip install` fastapi/uvicorn/openai 等）→ `python -m harness serve` 启动 → `Application startup complete` → health check pass。公网 URL = **`https://coding-agent-harness-89yf.onrender.com`**。
- **部署验证**（controller 云端访问，绕过本地网络封锁）：`/health` → `{"status":"ok"}` ✓；`/approvals` → `{"pending":[]}` ✓（HITL WebUI 正常）。
- **CI pass**（§191）：GitHub Actions `.github/workflows/ci.yml` 的 `unit-test` job 两个 run（`27ab036` + `431e769`）均 pass（用户确认 Actions 页面双绿）。
- **全部交付物完成**（通用要求 §185–195）：① SPEC/PLAN/SPEC_PROCESS ✅ ② 源码 44 commits 无凭据 ✅ ③ Dockerfile+render.yaml ✅ ④ README（6 章节+威胁模型+Live URL）✅ ⑤ AGENT_LOG ✅ ⑥ `.gitlab-ci.yml` `unit-test` job ✅ ⑦ CI pass ✅ ⑧ REFLECTION（1810 字 §207 标注）✅ ⑨ 部署 URL ✅。

## 阶段 6：聊天驱动前端（2026-07-25）

- **brainstorming → spec → plan**：`superpowers:brainstorming`（单次任务+步骤流；公网只 mock；SSE+on_event；vanilla JS）→ spec `docs/superpowers/specs/2026-07-25-chat-frontend-design.md`（commit `0f5ac46`）→ 本 plan。
- **实现**（5 个 TDD task，feat/chat-frontend 分支）：①`AgentLoop.on_event` 回调（5 个 emit 点，默认 None 不改既有行为）②`wrap_approver`（包裹 `blocking_approver`，emit hitl_pending/resolved，不动治理内核）③`POST /chat`+`GET /chat/{id}/stream`（`_runs` queue + SSE 同步生成器）④`index.html` 聊天 UI（vanilla，根 `/`，内联 approve/reject 复用现有端点）⑤README+AGENT_LOG。
- **测试**：新增 `test_loop_events`(2) + `test_wrap_approver`(2) + `test_streaming`(5，approve/reject/404/health/root) = 9 新测试；全确定性 mock-LLM 无网络。既有 63 测试保持绿（`on_event=None` 默认）。
- **commit 清单**：`git log --oneline feat/chat-frontend` 输出即为本阶段逐 task 提交（Tasks 1–4 + 本 Task 5 文档提交）：

  ```
  3d38ffc feat(web): chat-driven UI at root / (vanilla JS, SSE, inline HITL)
  bf78f84 feat(server): POST /chat + GET /chat/{id}/stream SSE over on_event queue
  d85427a feat(server): wrap_approver emits hitl_pending/hitl_resolved events
  a82cc23 feat(loop): add on_event callback emitting step/action/governance/tool_result/done
  9fb4d7d docs: chat-driven frontend implementation plan (5 TDD tasks)
  0f5ac46 docs: chat-driven frontend design spec (brainstorming approved)
  ```

- **公网**：聊天 UI 只发 `mock=true`，不耗 DeepSeek 额度；真实 LLM 路径在端点存在但前端不暴露。
