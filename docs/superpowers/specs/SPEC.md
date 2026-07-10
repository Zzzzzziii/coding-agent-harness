# Coding Agent Harness — 设计文档 (SPEC)

> 项目：AI4SE 期末项目 A · Coding Agent Harness
> 日期：2026-07-08
> 状态：已通过 brainstorming 签字确认

---

## 1. 问题陈述

### 要解决什么问题？

当一个 LLM 能完成大部分"思考"时，把它变成一个稳定、可靠的编码智能体需要的不是更多提示词，而是 harness 这层工程：主循环、工具分发、治理护栏、反馈闭环、上下文管理、配置。本项目实现一个最小可用的 coding agent harness，让 agent 能自主读写文件、执行命令、运行测试、根据测试结果自我修正，同时在危险动作前暂停等待人工审批。

### 目标用户是谁？

- 想要一个可自主完成简单编码任务（如"修复失败的测试"）的开发者
- 想要研究/学习 agent harness 内部机制的学生
- 需要对 agent 行为有治理控制（范围围栏、危险动作审批）的团队

### 为什么值得做？

`Agent = LLM + Harness`。LLM 是 CPU，harness 是让 CPU 真正可靠工作的一切工程。本项目用 Superpowers（一个 harness）去造另一个 harness，从而对 agent 工程方法论形成第一手理解。重点深挖治理维度——这是最纯代码、最易确定性测试、最契合 A.4 要求的维度。

---

## 2. 用户故事

### US1: 执行编码任务
> 作为开发者，我想给 agent 一个编码任务（如"修复失败的测试"），让它自主读写文件、运行测试、根据结果自我修正，直到任务完成。

- **Independent**：不依赖其他故事
- **Negotiable**：具体工具集可调整
- **Valuable**：核心价值，agent 能闭环工作
- **Estimable**：主循环 + 工具 + 反馈，范围清晰
- **Small**：单一闭环
- **Testable**：Mock LLM 驱动下完成"读→改→跑测试→通过"
- **验收**：agent 能完成闭环，无需人工干预（非危险动作）

### US2: 危险动作拦截
> 作为开发者，我想让 agent 在执行危险命令（如 `rm -rf /`）前被自动拦截，防止破坏系统。

- **验收**：任何匹配 `dangerous_patterns` 的命令不执行，agent 收到拦截反馈

### US3: HITL 人工审批
> 作为开发者，我想在 WebUI 上看到 agent 请求执行的危险动作，并批准或拒绝它，agent 据此继续或改变策略。

- **验收**：危险动作 → WebUI 显示 pending 审批 → 用户 approve/reject → agent 收到结果并 resume

### US4: 范围围栏
> 作为开发者，我想限制 agent 只能操作指定目录，防止它读写项目外的文件。

- **验收**：`write_file("/etc/passwd")` 被拒绝；`write_file("/workspace/foo.py")` 通过

### US5: 安全配置 API Key
> 作为开发者，我想安全地配置 DeepSeek API key，它不硬编码、不进 git、不回显明文。

- **验收**：key 从 `.env` 加载或首次运行引导录入；查看状态只显示 `configured: true`；可更新/清除

---

## 3. 功能规约（按模块）

### 模块 1: AgentLoop（主循环）
- **输入**：`task: str`, `config: Config`
- **行为**：循环 tick 直到停机或 max_iters
- **输出**：`AgentRunResult`（最终状态、迭代次数、动作历史）
- **边界条件**：max_iters 到达 → 强制停机；LLM 调用失败 → 重试 3 次后停机
- **错误处理**：解析失败 → 回灌错误要求重试

### 模块 2: LLMClient（抽象层）
- **输入**：`messages: list[Message]`, `tools: list[ToolSchema]`
- **行为**：调用 LLM API
- **输出**：`LLMResponse`（content, tool_calls, finish_reason）
- **边界条件**：网络超时 30s；rate limit → 指数退避重试
- **错误处理**：API key 无效 → 立即报错；网络错误 → 重试 3 次

### 模块 3: ToolRegistry（工具分发）
- **输入**：`action: Action`
- **行为**：查找 handler 并执行
- **输出**：`ToolResult`
- **边界条件**：未知工具名 → 错误；工具执行超时 60s
- **错误处理**：工具异常 → 捕获并转为 `ToolResult(ok=False, error=...)`

### 模块 4: Governance（治理）★ 重点维度
- **输入**：`action: Action`
- **行为**：三层检查（ScopeFence → Guardrail → HITL）
- **输出**：`GovernanceDecision`
- **边界条件**：HITL 超时 300s → 自动 reject
- **错误处理**：路径解析失败 → 保守拒绝

### 模块 5: Feedback（反馈）
- **输入**：`ToolResult`（来自 run_tests）
- **行为**：解析 pytest 输出
- **输出**：`TestFeedback`
- **边界条件**：非测试命令输出不解析；解析失败 → 返回 raw_output
- **错误处理**：无（解析失败不崩溃）

### 模块 6: WebUI（HITL 审批界面）
- **输入**：HTTP 请求
- **行为**：展示 pending 审批，接收 approve/reject
- **输出**：HTML 页面 / JSON 响应
- **边界条件**：仅响应来自本机的请求（开发阶段）
- **错误处理**：无效 approval_id → 404

### 模块 7: Config（配置）
- **输入**：`config.yaml` + `.env`
- **行为**：加载并校验配置
- **输出**：`Config` 对象
- **边界条件**：缺失必填项 → 启动失败并提示
- **错误处理**：YAML 解析错误 → 明确报错

### 模块 8: CredentialStore（凭据）
- **输入**：用户交互 / `.env`
- **行为**：加载、存储、查看状态、更新、清除 API key
- **输出**：key 或状态
- **边界条件**：查看状态不回显明文
- **错误处理**：key 不存在 → 引导录入

---

## 4. 非功能性需求

### 4.1 性能
- 单次 LLM 调用超时 30s
- 工具执行超时 60s
- HITL 等待超时 300s
- max_iters 默认 20，兜底防死循环

### 4.2 安全（含凭据威胁模型）

| 威胁 | 场景 | 对策 |
|---|---|---|
| 硬编码泄露 | key 写在源码里 | 代码中零硬编码；CI 扫描 `.env` 不进 git |
| Git 历史泄露 | `.env` 被提交 | `.gitignore` 排除 `.env`；README 警告 |
| 日志泄露 | 调试时打印 key | `DeepSeekClient` 日志脱敏，只记 `sk-***...***` |
| 进程环境可见 | `export` 进 shell history | 用 `.env` + `python-dotenv` 加载，不用 `export` |
| 容器内泄露 | Docker 环境变量可见 | `docker run -e` 传入；不写入镜像；`.env.example` 提供模板 |

### 4.3 可用性
- WebUI 简洁可用，pending 审批一目了然
- CLI 命令符合直觉：`harness run <task>` / `harness serve` / `harness creds status`

### 4.4 可观测性
- 每次迭代输出 `[iter N] action=xxx result=xxx` 到 stdout + 日志文件
- WebUI 显示实时活动流

### 4.5 可靠性
- LLM 调用失败重试 3 次（指数退避）
- 工具异常捕获不崩溃
- max_iters 兜底防死循环

---

## 5. 系统架构

### 5.1 组件图

```
┌─────────────────────────────────────────────────────────┐
│                        Config (YAML)                      │
│  allowed_paths, dangerous_patterns, model, max_iters     │
└──────────────────────────┬──────────────────────────────┘
                           │ loads
┌──────────────────────────▼──────────────────────────────┐
│                    AgentLoop (主循环)                     │
│  organize context → call LLM → parse action → dispatch   │
│  → governance check → execute → feed back → stop?        │
└──┬──────────┬──────────┬──────────┬──────────┬─────────┘
   │          │          │          │          │
┌──▼───┐  ┌──▼───┐  ┌───▼────┐  ┌──▼───┐  ┌──▼────┐
│ LLM  │  │Memory│  │Govern- │  │Tool  │  │Feed-  │
│Abstr.│  │(min) │  │ance ★  │  │Regist│  │back   │
└──┬───┘  └──────┘  └───┬────┘  └──┬───┘  └──┬────┘
   │                     │           │          │
   │              ┌──────▼─────┐     │          │
   │              │ HITL State │     │          │
   │              │  Machine   │     │          │
   │              └──────┬─────┘     │          │
   │                     │           │          │
   │              ┌──────▼───────────▼───┐      │
   │              │   WebUI (FastAPI)    │      │
   │              │  approve / reject    │      │
   │              └──────────────────────┘      │
┌──▼───────────────────────────────────────────▼──┐
│              DeepSeekClient  |  MockLLMClient     │
│         (openai SDK + base_url)  (deterministic)  │
└──────────────────────────────────────────────────┘
```

### 5.2 数据流（一次完整循环）

```
用户输入任务: "修复 tests/test_foo.py 中失败的测试"
    │
    ▼
1. AgentLoop.tick()
   - ContextStore 组装 messages (system + history + task)
   - 调用 LLMClient.chat(messages)
   - 解析 LLM 返回 → Action
    │
    ▼ Action
2. Governance.check(action)
   - ScopeFence: path 在 allowed_paths 内?
     否 → GovernanceDecision(blocked, "out of scope")
   - Guardrail: command 匹配危险模式?
     是 → HITLStateMachine.create(action) → pending
          → AgentLoop 阻塞等待 WebUI 审批
          → approved → 继续 / rejected → 拒绝
   - 都通过 → GovernanceDecision(blocked=False)
    │
    ▼ not blocked
3. ToolRegistry.dispatch(action)
   - 查找 tool handler, 执行, 返回 ToolResult
   - 若 tool == "run_tests":
     TestRunner.parse(ToolResult.output) → TestFeedback
    │
    ▼ ToolResult / TestFeedback
4. FeedbackInjector.inject(result)
   - 将结果转为 Message(role="tool", content=...)
   - 追加到 ContextStore
    │
    ▼
5. Stop判断
   - LLM 返回 "done" / 无 tool_call → 停止
   - 达到 max_iters → 停止
   - 否则 → 回到步骤 1
```

### 5.3 外部依赖

| 依赖 | 用途 | 必需性 |
|---|---|---|
| DeepSeek API | LLM 调用 | 真实运行必需，测试用 Mock 替代 |
| `openai` Python 库 | HTTP 客户端调用 DeepSeek（兼容 API） | 必需 |
| `fastapi` + `uvicorn` | WebUI 后端 | 必需 |
| `pyyaml` | 配置文件解析 | 必需 |
| `python-dotenv` | `.env` 加载 | 必需 |
| `pytest` | 测试框架 | 必需 |

---

## 6. 数据模型

```python
# 经冷启动验证（见 SPEC_PROCESS.md §4.5）后与 PLAN 对齐的澄清：
#   - 类型用 str + 注释（放弃 Literal，换取可直接粘贴的代码 + 运行时校验；CI 不跑 mypy）。
#   - Action 携带治理结果字段（blocked/status…），这是 demo 断言所必需的。
#   - 时间戳用 float（由调用方注入），保证 mock-LLM 下确定性可测（呼应 A.4-C）。

@dataclass
class Message:
    role: str                          # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str | None = None    # 用于关联 tool 调用与结果

@dataclass
class Action:
    tool: str                          # "read_file" | "write_file" | "run_shell" | "run_tests"
    args: dict                         # 工具参数
    raw_llm_response: str | None       # 原始 LLM 输出，用于调试
    blocked: bool = False              # 由 Governance.check 写回
    block_reason: str | None = None
    approval_id: str | None = None     # HITL 审批 id
    status: str | None = None          # HITL 结果: "approved" | "rejected" | None

@dataclass
class ToolResult:
    ok: bool
    output: dict                       # 工具特定输出
    error: str | None = None

@dataclass
class GovernanceDecision:
    blocked: bool
    reason: str
    layer: str | None = None           # "scope_fence" | "guardrail" | "hitl"
    approval_id: str | None = None     # HITL 时生成

@dataclass
class ApprovalRecord:
    id: str
    action: Action
    status: str = "pending"            # "pending" | "approved" | "rejected"
    created_at: float = 0.0            # 由调用方注入的时间戳，保证确定性测试
    decided_at: float | None = None
    feedback_to_agent: str | None = None  # 回灌给 agent 的拒绝理由
    __test__ = False                   # 抑制 pytest 把 Test* 类误当测试类收集

@dataclass
class TestFeedback:
    passed: int
    failed: int
    errors: list[str]
    raw_output: str
    __test__ = False
    @property
    def success(self) -> bool:         # failed==0 且 passed>0；unparseable 时 passed=0 → False（避免误报通过）
        return self.failed == 0 and self.passed > 0

@dataclass
class AgentRunResult:
    final_status: str                  # "success" | "failed" | "max_iters" | "error"
    iterations: int
    actions: list[Action]
    executed_commands: list[str]
```

### 实体关系

- `AgentLoop` 持有 `LLMClient`, `ContextStore`, `Governance`, `ToolRegistry`, `FeedbackInjector`
- `Governance` 持有 `ScopeFence`, `Guardrail`, `HITLStateMachine`
- `HITLStateMachine` 持有 `dict[approval_id → ApprovalRecord]`
- `ToolRegistry` 持有 `dict[tool_name → handler]`
- `ContextStore` 持有 `list[Message]`

### 约束

- `Action.tool` 必须是已注册工具名，否则 ToolRegistry 返回错误
- `ApprovalRecord.status` 只能 pending → approved/rejected（单向）
- `ContextStore` 消息数受 max_tokens 约束，超限时截断最早非系统消息

---

## 7. 凭据与分发设计

### 7.1 凭据存储方案

- **主方案**：`.env` 文件 + `python-dotenv` 加载。`.env` 明文，README 明确说明风险。
- **首次引导**：检测到无 key 时，交互式提示用户输入（`getpass` 隐藏输入），写入 `.env` 并设权限 `600`。
- **查看状态**：`python -m harness creds status` → 输出 `configured: true`，不回显明文。
- **更新/清除**：`creds set` / `creds clear` 子命令。

### 7.2 分发形态：Docker 镜像

**Dockerfile 要点：**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY . .
# 不 COPY .env，不 ENV API_KEY
EXPOSE 8000
CMD ["python", "-m", "harness", "serve"]
```

**用户运行方式：**
```bash
docker build -t coding-harness .
docker run -it --rm \
  -e DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY \
  -p 8000:8000 \
  -v $(pwd)/workspace:/workspace \
  coding-harness
```

- key 通过 `-e` 传入容器，不写入镜像
- 工作目录通过 volume 挂载，agent 只能操作 `/workspace`
- WebUI 通过 `8000` 端口访问

### 7.3 已知限制

- 平台：Linux/macOS/Windows（Docker Desktop）
- 架构：amd64 / arm64
- 前置依赖：Docker、DeepSeek API key
- 容器内无系统钥匙串，key 仅通过环境变量传入

---

## 8. 技术选型与理由

| 选型 | 理由 |
|---|---|
| **Python 3.11+** | 生态成熟，LLM SDK 丰富，pytest 测试体验好，上手快（开发机 3.11.9；Docker 镜像 `python:3.12-slim`） |
| **DeepSeek (deepseek-chat)** | OpenAI 兼容 API，价格低，编码能力足够 |
| **`openai` 库 + 自定义 base_url** | DeepSeek API 兼容 OpenAI 格式，复用成熟 SDK，无需自写 HTTP |
| **FastAPI + uvicorn** | 轻量 WebUI 后端，异步支持好，自带 OpenAPI 文档 |
| **pytest** | Python 测试标准，fixture/标记机制适合 mock LLM 测试 |
| **pyyaml** | 配置文件，声明式约束 agent 行为 |
| **python-dotenv** | `.env` 加载，避免 `export` 进 shell history |
| **Docker** | 单条命令可启动，Python 项目分发最契合 |

本项目为纯 CLI/后端 + 轻量 WebUI，不涉及复杂前端，豁免 Open Design 要求。

---

## 9. 验收标准

| 功能 | 完成的客观判定标准 |
|---|---|
| AgentLoop | Mock LLM 驱动下完成"读→改→跑测试→通过"闭环，≤ max_iters 停机 |
| Guardrail | `rm -rf /` 等 5+ 危险模式全部被拦截，每次确定性成立 |
| HITL 状态机 | pending→approved→执行 / pending→rejected→回灌，状态流转正确 |
| ScopeFence | 项目外路径 100% 拒绝，项目内路径通过 |
| Feedback | pytest 失败输出被正确解析，结构化结果回灌进上下文 |
| WebUI | pending 审批可见，approve/reject 可操作，agent 据 resume |
| CredentialStore | key 不回显明文；status 只显示 configured: true/false |
| Config | YAML 缺失必填项 → 启动失败并明确提示 |
| 分发 | `docker build` + `docker run` 单条命令可启动 |
| CI | `.gitlab-ci.yml` 含 `unit-test` job，push 自动运行，最后状态 pass |

---

## 10. 风险与未决问题

| 风险 | 影响 | 缓解 |
|---|---|---|
| DeepSeek API 格式与 OpenAI SDK 细微差异 | LLM 调用失败 | 抽象层隔离；集成测试用真实 API 验证一次 |
| LLM 不返回 tool_calls 而是纯文本 | Action 解析失败 | 解析器兜底：尝试从文本提取 JSON；失败则回灌要求重试 |
| pytest 输出格式跨版本变化 | TestRunner 解析失败 | 正则宽松匹配；解析失败返回 raw_output 不崩溃 |
| HITL 阻塞导致循环卡死 | agent 无响应 | 300s 超时自动 reject；WebUI 显示超时倒计时 |
| Docker volume 权限问题 | agent 无法写 /workspace | Dockerfile 设非 root 用户；README 说明挂载权限 |
| Mock LLM 脚本与真实 LLM 行为不一致 | 测试通过但真实运行失败 | 机制演示用 Mock 保证确定性；真实 LLM 行为不作为机制验收标准 |

---

## 11. 领域与机制设计（A.5 专属）

### 11.1 领域：Coding

本 harness 面向软件开发场景：agent 能读写代码、执行命令、运行测试，并根据测试结果自我修正。

### 11.2 四类机制（A.3）

#### 动作/工具

| 工具 | 输入 | 行为 | 输出 | 边界/错误 |
|---|---|---|---|---|
| `read_file` | `path: str` | 读取文件内容 | `{content, ok}` | 路径超出 scope → 拒绝；文件不存在 → 错误回灌 |
| `write_file` | `path, content` | 写入文件 | `{bytes_written, ok}` | 路径超出 scope → 拒绝；权限不足 → 错误 |
| `run_shell` | `command: str` | 执行 shell 命令 | `{stdout, stderr, exit_code}` | 危险命令 → 护栏拦截；超时 → 终止 |
| `run_tests` | `test_cmd: str` | 运行测试命令 | `{passed, failed, output}` | 解析 pytest 输出；失败 → 反馈回灌 |

#### 客观反馈信号

- `TestRunner` 执行 `run_tests`，解析 pytest 文本输出（正则匹配 `passed`/`failed`/`error` 行）
- 产出结构化结果：`{passed: int, failed: int, errors: list[str], raw_output: str}`
- `FeedbackInjector` 将此结构化结果作为 `tool_result` 回灌进上下文
- **这是代码机制不是提示词**：解析逻辑是确定性的正则 + 解析器，不依赖 LLM 判断

#### 危险动作（治理深挖 — 重点贡献）

三层防护，全部是确定性代码：

```
Action 产生
  │
  ▼
Layer 1: ScopeFence (范围围栏)
  - 白名单路径检查：path 是否在 allowed_paths 内？
  - 算法：os.path.realpath + os.path.normcase + os.sep 段安全比较
    （normcase 在 Windows 小写化、POSIX 恒等 → 跨平台一致）
  - 处理：相对路径规范化、符号链接解析、Windows 大小写、路径穿越(../)
  - 路径无需真实存在（purepath 风格的规范化比较，不触发 FileNotFoundError）
  - 否 → 直接拒绝，不进 Layer 2
  │ in scope
  ▼
Layer 2: Guardrail (护栏) — 两级
  - deny_patterns（毁灭性命令，硬阻断，不经 HITL）：rm -rf /, fork bomb
  - dangerous_patterns（需人工审批，进 HITL）：git push --force, drop table
  - deny 优先于 dangerous（被 deny 的不再判为 dangerous）
  - 是(dangerous) → 进入 Layer 3 (HITL)
  │ dangerous
  ▼
Layer 3: HITLStateMachine
  状态: pending → approved/rejected → (resume)
  - 暂停 → 等待人工审批
  - approved → 执行
  - rejected → 拒绝，回灌给 agent
  │
  ▼ (approved or not dangerous)
Tool 执行
```

**HITL 状态机详细设计：**

```
                    ┌──────────┐
         ┌─────────►│ PENDING  │◄──── agent 产生危险动作
         │          └────┬─────┘
         │               │
         │       ┌───────┴───────┐
         │       ▼               ▼
         │  ┌─────────┐   ┌──────────┐
         │  │APPROVED │   │ REJECTED │
         │  └────┬────┘   └────┬─────┘
         │       │              │
         │       ▼              ▼
         │  执行动作        拒绝+回灌结果给agent
         │       │         (agent 收到"被拒绝"反馈)
         │       ▼
         └──► RESUMED (循环继续)
```

- 状态存储在内存 `dict[approval_id → ApprovalRecord]`
- WebUI 通过 FastAPI 轮询/SSE 获取 pending 列表，POST approve/reject
- `AgentLoop` 在 HITL pending 时阻塞等待（带超时）

#### 记忆（最小实现）

- `ContextStore`：维护 `messages: list[Message]`，超出 max_tokens 时从最早的非系统消息开始截断
- 不做跨会话持久化（YAGNI）
- 系统提示词包含项目约定（从 Config 加载）

### 11.3 重点维度：治理

选择治理作为重点深挖维度，理由：

1. **纯代码构成**：护栏、状态机、围栏全部是确定性代码，不依赖 LLM 智能
2. **最易确定性测试**：直接构造 Action 调用函数，断言拦截/放行，每次成立
3. **最契合 A.4 要求**：A.4-C 的"移除 LLM 后还能单测验证"判据，治理维度天然满足
4. **与 WebUI 需求合一**：HITL 审批 WebUI 就是治理维度的组成部分，不产生额外工作

### 11.4 机制编码实现方式（呼应 A.4）

- **反馈信号** = `TestRunner`（解析器）+ `FeedbackInjector`（回灌器），确定性代码
- **危险动作拦截** = `Guardrail`（模式匹配）+ `HITLStateMachine`（状态机）+ `ScopeFence`（围栏），确定性代码
- **工具分发** = `ToolRegistry`（注册 + 分发），确定性代码
- **停机判断** = `AgentLoop` 的 stop 条件检查，确定性代码
- **记忆读写** = `ContextStore`（追加 + 截断），确定性代码

所有机制移除真实 LLM 后，用 MockLLMClient 即可确定性验证。

### 11.5 配置文件结构 (`config.yaml`)

```yaml
llm:
  model: "deepseek-chat"
  base_url: "https://api.deepseek.com"
  max_tokens: 4096
  temperature: 0.0

agent:
  max_iters: 20
  system_prompt_file: "prompts/system.md"

governance:
  allowed_paths:
    - "/workspace/"
  deny_patterns:                      # 毁灭性命令，硬阻断，不经 HITL
    - 'rm\s+-rf\s+/'
    - ':\(\)\{\s*:\|:&\s*\};:'        # fork bomb
  dangerous_patterns:                 # 需人工审批，进 HITL
    - 'drop\s+(table|database)'
    - 'git\s+push\s+--force'
  hitl_timeout_seconds: 300

tests:
  command: "pytest tests/ -v --tb=short"
```

---

## 12. 测试策略

### 12.1 三层测试

| 层级 | 范围 | 工具 | 依赖 LLM? |
|---|---|---|---|
| **单元测试** | 每个组件独立，Mock LLM | pytest | 否（确定性） |
| **集成测试** | 组件组合，Mock LLM 驱动完整循环 | pytest | 否（Mock 脚本化） |
| **机制演示** | A.6 三项确定性行为 | pytest（标记 `@pytest.mark.demo`） | 否 |

### 12.2 测试目录结构

```
tests/
├── unit/
│   ├── test_guardrail.py          # 危险模式匹配：rm -rf, drop table, fork bomb...
│   ├── test_scope_fence.py        # 路径白名单：/workspace 内通过，/etc 拒绝
│   ├── test_hitl_state_machine.py # pending→approved/rejected 状态流转
│   ├── test_tool_registry.py      # 工具分发：已知工具执行，未知工具报错
│   ├── test_test_runner.py        # pytest 输出解析：passed/failed/errors
│   ├── test_feedback_injector.py  # 结果回灌为 tool message
│   ├── test_context_store.py      # 消息截断：超 max_tokens 截断非系统消息
│   ├── test_config.py             # YAML 加载与校验
│   ├── test_credential_store.py   # key 加载/状态/清除，不回显明文
│   └── test_llm_parser.py         # LLM 响应解析为 Action
├── integration/
│   ├── test_agent_loop_mock.py    # Mock LLM 驱动完整循环：任务→动作→反馈→停机
│   └── test_governance_pipeline.py # 三层防护串联：scope→guardrail→hitl
├── demo/
│   └── test_mechanism_demo.py     # A.6 三项机制演示
└── conftest.py                    # MockLLMClient fixture, 临时 workspace
```

### 12.3 MockLLMClient 设计

```python
class MockLLMClient:
    def __init__(self, script: list[LLMResponse]):
        self.script = script  # 按顺序返回的脚本化响应
        self._idx = 0
    def chat(self, messages, tools=None):
        resp = self.script[self._idx]
        self._idx += 1
        return resp
```

### 12.4 机制演示（A.6 三项）

```python
# demo/test_mechanism_demo.py

@pytest.mark.demo
def test_demo_1_guardrail_intercepts():
    """① 治理护栏拦截危险动作"""
    mock = MockLLMClient([llm_response(tool="run_shell", args={"command": "rm -rf /"})])
    loop = AgentLoop(llm=mock, governance=Governance(...))
    result = loop.run("delete everything")
    assert result.actions[0].blocked is True
    assert "rm -rf" not in result.executed_commands  # 未执行

@pytest.mark.demo
def test_demo_2_feedback_self_correction():
    """② 反馈闭环使 agent 改变下一步动作"""
    mock = MockLLMClient([
        llm_response(tool="write_file", args={"path": "bad.py", "content": "syntax error!!"}),
        llm_response(tool="run_tests", args={}),
        llm_response(tool="write_file", args={"path": "bad.py", "content": "valid code"}),  # 修正
        llm_response(tool="run_tests", args={}),
        llm_response(finish=True),  # 停机
    ])
    result = loop.run("fix the test")
    assert result.iterations == 5
    assert result.final_status == "success"

@pytest.mark.demo
def test_demo_3_hitl_rejection():
    """③ 重点维度：HITL reject 后 agent 收到反馈"""
    mock = MockLLMClient([
        llm_response(tool="run_shell", args={"command": "git push --force"}),  # 危险
        llm_response(tool="run_shell", args={"command": "git status"}),        # 改用安全命令
        llm_response(finish=True),
    ])
    hitl = HITLStateMachine()
    loop = AgentLoop(llm=mock, governance=Governance(hitl=hitl, ...))
    # 模拟人工 reject
    loop.on_pending = lambda approval_id: hitl.reject(approval_id)
    result = loop.run("push my code")
    assert result.actions[0].status == "rejected"
    assert "git status" in result.executed_commands  # agent 改变了策略
```

### 12.5 一键运行

`make test` 或 `pytest tests/ -v`

---

## 13. 实现边界声明（A.4）

### 必须自己实现，不得寄生于现成框架

- ✅ **agent 主循环**：`AgentLoop` 自己实现（组织上下文 → 调用 LLM → 解析动作 → 分发执行 → 回灌结果 → 停机判断）
- ✅ **可注入 mock 的 LLM 抽象层**：`LLMClient` 接口 + `DeepSeekClient` / `MockLLMClient`
- ✅ **工具分发**：`ToolRegistry` 自己实现
- ✅ **治理护栏**：`Guardrail` + `HITLStateMachine` + `ScopeFence` 自己实现
- ✅ **反馈闭环**：`TestRunner` + `FeedbackInjector` 自己实现
- ✅ **记忆**：`ContextStore` 自己实现
- ✅ **配置**：`Config` 加载与校验自己实现

### 允许使用的底层零件

- `openai` 库（DeepSeek API 的 HTTP 客户端）
- `fastapi` + `uvicorn`（WebUI）
- `pyyaml`（配置解析）
- `python-dotenv`（.env 加载）
- `pytest`（测试）

### 不使用的高层框架

- 不使用 LangChain `AgentExecutor`、AutoGen、CrewAI、LlamaIndex agent
- 不使用任何现成 agent 编排框架的高层循环

### 机制是代码不是提示词

- 反馈信号 = `TestRunner` 解析器（代码），不是"让 LLM 自行检查"的提示词
- 危险动作拦截 = `Guardrail` 函数（代码），不是"提醒 LLM 注意安全"的提示词
- 移除真实 LLM 后，所有核心机制仍能用 MockLLMClient 驱动的确定性单元测试验证
