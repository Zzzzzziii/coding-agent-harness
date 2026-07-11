# Coding Agent Harness — Implementation Plan (PLAN.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task (one fresh subagent per task, two-stage review between tasks). Steps use checkbox (`- [ ]`) syntax for tracking. TDD is mandatory: red → green → refactor. No implementation code is written before its failing test.

**Goal:** Build a minimal, self-implemented coding agent harness whose governance layer (scope fence + guardrail + HITL state machine) is the deep-dive focus dimension, fully testable with a mock LLM and no network.

**Architecture:** `Agent = LLM + Harness`. The harness owns the main loop (`AgentLoop`), an injectable LLM abstraction (`LLMClient` with `DeepSeekClient` / `MockLLMClient`), a tool registry (`read_file`/`write_file`/`run_shell`/`run_tests`), a three-layer governance pipeline, a deterministic feedback injector that parses pytest output, a context store with truncation, a FastAPI WebUI for HITL approvals, and a CLI. Every core mechanism is deterministic code verifiable with `MockLLMClient`; the real DeepSeek client is only exercised by an opt-in integration test.

**Tech Stack:** Python 3.11, `openai` SDK (DeepSeek-compatible), `fastapi`+`uvicorn`, `pyyaml`, `python-dotenv`, `pytest`, Docker, GitLab CI + GitHub Actions.

---

## Global Constraints

- Python **3.11** (`requires-python = ">=3.11"`); the dev machine has 3.11.9.
- No real credentials in source, git history, logs, or plaintext configs. `.env` is gitignored; `.env.example` is the template.
- **A.4 boundary:** the harness kernel (loop, LLM abstraction, tool dispatch, governance, feedback, memory, config) is hand-implemented. `openai`/`fastapi`/`pyyaml`/`python-dotenv` are allowed low-level parts. No LangChain/AutoGen/CrewAI/LlamaIndex agent executors.
- **A.4-B/C:** feedback signal and dangerous-action interception are deterministic code (validators/state-machines), not prompts. Remove the real LLM → every mechanism still unit-testable with `MockLLMClient`.
- **A.6:** three deterministic mechanism demos under `tests/demo/` marked `@pytest.mark.demo`.
- One-command tests: `make test` ≡ `pytest -q`. CI `.gitlab-ci.yml` must define a `unit-test` job; a GitHub Actions mirror runs the same.
- Each task ends with a commit; PLAN.md records the commit hash.

---

## Shared Interfaces (canonical — every task must match these signatures)

```python
# harness/models.py
from dataclasses import dataclass, field

@dataclass
class Message:
    role: str                       # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str | None = None

@dataclass
class Action:
    tool: str
    args: dict
    raw_llm_response: str | None = None
    blocked: bool = False
    block_reason: str | None = None
    approval_id: str | None = None
    status: str | None = None       # HITL outcome: "approved" | "rejected" | None

@dataclass
class ToolResult:
    ok: bool
    output: dict
    error: str | None = None

@dataclass
class GovernanceDecision:
    blocked: bool
    reason: str
    layer: str | None = None        # "scope_fence" | "guardrail" | "hitl"
    approval_id: str | None = None

@dataclass
class TestFeedback:
    passed: int
    failed: int
    errors: list[str]
    raw_output: str
    @property
    def success(self) -> bool:      # failed == 0
        return self.failed == 0 and self.passed > 0

@dataclass
class AgentRunResult:
    final_status: str              # "success" | "failed" | "max_iters" | "error"
    iterations: int
    actions: list[Action]
    executed_commands: list[str]
```

```python
# harness/llm/base.py
@dataclass
class ToolCall:
    id: str
    name: str
    args: dict

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str              # "tool_calls" | "stop" | "length"

class LLMClient(Protocol):
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse: ...

def next_action(resp: LLMResponse) -> Action | None:
    # first tool call as Action, or None when the model is done (no tool calls)
```

```python
# harness/tools/base.py
ToolHandler = Callable[[dict], ToolResult]      # handler(args: dict) -> ToolResult
class ToolRegistry:
    def register(self, name: str, schema: dict, handler: ToolHandler) -> None: ...
    def dispatch(self, action: Action) -> ToolResult: ...
    def schemas(self) -> list[dict]: ...          # for LLM tool-use

# harness/governance/*.py
class ScopeFence:
    def __init__(self, allowed_paths: list[str]): ...
    def is_allowed(self, path: str) -> bool: ...
class Guardrail:
    def __init__(self, dangerous_patterns: list[str], deny_patterns: list[str]): ...
    def is_dangerous(self, command: str) -> bool: ...   # HITL-gated
    def is_denied(self, command: str) -> bool: ...      # hard-block
@dataclass
class ApprovalRecord:
    id: str; action: Action; status: str; created_at: float
    decided_at: float | None = None; feedback_to_agent: str | None = None
class HITLStateMachine:
    def create(self, action: Action) -> ApprovalRecord: ...      # status="pending"
    def approve(self, approval_id: str) -> ApprovalRecord: ...
    def reject(self, approval_id: str, reason: str) -> ApprovalRecord: ...
    def get(self, approval_id: str) -> ApprovalRecord | None: ...
    def pending(self) -> list[ApprovalRecord]: ...
Approver = Callable[[ApprovalRecord], bool]                     # True=approve, False=reject
class Governance:
    def __init__(self, scope_fence, guardrail, hitl): ...
    def check(self, action: Action, approver: Approver | None = None) -> GovernanceDecision: ...

# harness/feedback/*.py
class TestRunner:
    def parse(self, tool_result: ToolResult) -> TestFeedback: ...
class FeedbackInjector:
    def __init__(self, context_store): ...
    def inject_result(self, action, result: ToolResult, tool_call_id: str) -> None: ...
    def inject_test(self, action, tf: TestFeedback, tool_call_id: str) -> None: ...
    def inject_block(self, action: Action, decision: GovernanceDecision, tool_call_id: str) -> None: ...

# harness/memory/context_store.py
class ContextStore:
    def __init__(self, system_prompt: str, max_messages: int = 50): ...
    @property
    def messages(self) -> list[Message]: ...
    def add(self, msg: Message) -> None: ...
    def truncate(self) -> None: ...   # drop oldest non-system msgs over max_messages

# harness/loop.py
class AgentLoop:
    def __init__(self, llm, config, governance, tools, context_store,
                 feedback_injector, test_runner, approver=None): ...
    def run(self, task: str) -> AgentRunResult: ...
```

---

## File Structure

```
.
├── pyproject.toml                 # packaging, deps, pytest config, console script
├── Makefile                       # make test / make lint / make run
├── config.yaml                    # declarative agent constraints
├── prompts/system.md              # system prompt (content, not a mechanism)
├── .env.example                   # credential template
├── .gitlab-ci.yml                 # CI w/ unit-test job
├── .github/workflows/ci.yml      # GitHub Actions mirror
├── Dockerfile                     # distribution image
├── render.yaml                    # one-click deploy config
├── README.md  SPEC.md  PLAN.md  SPEC_PROCESS.md  AGENT_LOG.md  REFLECTION.md
└── harness/
    ├── __init__.py
    ├── __main__.py                # CLI: run / serve / creds {status,set,clear}
    ├── models.py
    ├── config.py
    ├── creds.py
    ├── loop.py
    ├── llm/{__init__,base,deepseek,mock}.py
    ├── tools/{__init__,base,builtin}.py
    ├── governance/{__init__,scope_fence,guardrail,hitl,pipeline}.py
    ├── feedback/{__init__,test_runner,injector}.py
    ├── memory/{__init__,context_store}.py
    └── web/{__init__,app}.py
└── tests/
    ├── conftest.py                # MockLLMClient fixture, tmp workspace, scripted tools
    ├── unit/   (one test file per module)
    ├── integration/{test_agent_loop_mock,test_governance_pipeline}.py
    └── demo/test_mechanism_demo.py
```

## Task Dependency & Parallelization

```
T1 models ─┬─► T2 config ─► T3 creds
           ├─► T4 llm/base ─► T5 llm/mock
           ├─► T6 scope_fence ┐
           ├─► T7 guardrail   ├─► T9 gov pipeline
           ├─► T8 hitl ───────┘
           ├─► T10 tools/base ─► T11 tools/builtin
           ├─► T12 test_runner ─► T13 injector
           └─► T14 context_store
T5+T9+T11+T13+T14 ─► T15 agent_loop ─► T16 CLI ─► T17 web ─► T18 integration ─► T19 demo
T18 done ─► T20 packaging ─► T21 docker ─► T22 CI ─► T23 README ─► T24 process docs
```
Parallelizable (independent leaves): T6/T7/T8, T10/T11, T12/T13, T14, T3, T5 — any whose only dependency is T1 (models) can run concurrently in separate worktrees.

---

## Task 1: Project scaffolding + data models

**Files:**
- Create: `pyproject.toml`, `harness/__init__.py`, `harness/models.py`
- Test: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/test_models.py`
- Create: `tests/conftest.py` (minimal, extended later)

**Interfaces:** Produces `Message, Action, ToolResult, GovernanceDecision, TestFeedback, AgentRunResult` (see Shared Interfaces). No upstream deps.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_models.py
from harness.models import (Message, Action, ToolResult, GovernanceDecision,
                            TestFeedback, AgentRunResult)

def test_action_defaults():
    a = Action(tool="read_file", args={"path": "/x"})
    assert a.blocked is False
    assert a.status is None
    assert a.approval_id is None

def test_test_feedback_success():
    tf = TestFeedback(passed=3, failed=0, errors=[], raw_output="")
    assert tf.success is True
    tf2 = TestFeedback(passed=2, failed=1, errors=["boom"], raw_output="")
    assert tf2.success is False

def test_message_roles():
    m = Message(role="tool", content="x", tool_call_id="c1")
    assert m.tool_call_id == "c1"
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/unit/test_models.py -q` → FAIL `ModuleNotFoundError: No module named 'harness'`.

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "coding-agent-harness"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["openai>=1.0", "fastapi>=0.110", "uvicorn>=0.27", "pyyaml>=6.0", "python-dotenv>=1.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]
test = ["pytest>=8.0", "httpx>=0.27"]

[project.scripts]
harness = "harness.__main__:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["demo: A.6 mechanism demonstration"]
addopts = "-ra"

[tool.setuptools.packages.find]
include = ["harness*"]
```

```python
# harness/__init__.py
__version__ = "0.1.0"
```

```python
# harness/models.py
from dataclasses import dataclass

@dataclass
class Message:
    role: str
    content: str
    tool_call_id: str | None = None

@dataclass
class Action:
    tool: str
    args: dict
    raw_llm_response: str | None = None
    blocked: bool = False
    block_reason: str | None = None
    approval_id: str | None = None
    status: str | None = None

@dataclass
class ToolResult:
    ok: bool
    output: dict
    error: str | None = None

@dataclass
class GovernanceDecision:
    blocked: bool
    reason: str
    layer: str | None = None
    approval_id: str | None = None

@dataclass
class TestFeedback:
    passed: int
    failed: int
    errors: list[str]
    raw_output: str
    __test__ = False  # suppress PytestCollectionWarning (class name starts with "Test")
    @property
    def success(self) -> bool:
        return self.failed == 0 and self.passed > 0

@dataclass
class AgentRunResult:
    final_status: str
    iterations: int
    actions: list[Action]
    executed_commands: list[str]
```

(`tests/__init__.py`, `tests/unit/__init__.py`, `tests/conftest.py` are empty files.)

- [ ] **Step 4: Run test to verify it passes** — install editable: `pip install -e ".[test]"`; `pytest tests/unit/test_models.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(models): core data models + project scaffolding"`.

---

## Task 2: Config loader

**Files:** Create `harness/config.py`, `config.yaml`, `prompts/system.md`. Test `tests/unit/test_config.py`.

**Interfaces:** Produces `Config` (a frozen object) with `.llm`, `.agent`, `.governance`, `.tests` namespaces and `Config.load(path: str) -> Config`. Consumes `pyyaml`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py
import textwrap, pathlib
from harness.config import Config

def test_load_valid_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        llm: {model: deepseek-chat, base_url: "https://api.deepseek.com", max_tokens: 4096, temperature: 0.0}
        agent: {max_iters: 20, system_prompt_file: prompts/system.md}
        governance:
          allowed_paths: ["/workspace/"]
          dangerous_patterns: ["git push --force"]
          deny_patterns: ["rm -rf /"]
          hitl_timeout_seconds: 300
        tests: {command: "pytest tests/ -v --tb=short"}
    """))
    c = Config.load(str(cfg))
    assert c.agent.max_iters == 20
    assert c.governance.allowed_paths == ["/workspace/"]
    assert c.governance.deny_patterns == ["rm -rf /"]

def test_missing_required_field_raises(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm: {model: x}\n")   # missing base_url, agent, governance, tests
    try:
        Config.load(str(cfg)); assert False, "should have raised"
    except Exception as e:
        assert "missing" in str(e).lower() or "required" in str(e).lower()
```

- [ ] **Step 2: Run → FAIL** `ModuleNotFoundError: No module named 'harness.config'`.

- [ ] **Step 3: Implementation**

```python
# harness/config.py
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass(frozen=True)
class LLMConfig:
    model: str; base_url: str; max_tokens: int; temperature: float

@dataclass(frozen=True)
class AgentConfig:
    max_iters: int; system_prompt_file: str

@dataclass(frozen=True)
class GovernanceConfig:
    allowed_paths: list[str]; dangerous_patterns: list[str]
    deny_patterns: list[str]; hitl_timeout_seconds: int

@dataclass(frozen=True)
class TestsConfig:
    command: str

@dataclass(frozen=True)
class Config:
    llm: LLMConfig; agent: AgentConfig
    governance: GovernanceConfig; tests: TestsConfig

    @staticmethod
    def load(path: str) -> "Config":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        required = ["llm", "agent", "governance", "tests"]
        for key in required:
            if key not in raw:
                raise ValueError(f"Config missing required section: {key}")
        g = raw["governance"]
        return Config(
            llm=LLMConfig(model=raw["llm"]["model"], base_url=raw["llm"]["base_url"],
                          max_tokens=raw["llm"]["max_tokens"], temperature=raw["llm"]["temperature"]),
            agent=AgentConfig(max_iters=raw["agent"]["max_iters"],
                              system_prompt_file=raw["agent"]["system_prompt_file"]),
            governance=GovernanceConfig(
                allowed_paths=g["allowed_paths"], dangerous_patterns=g.get("dangerous_patterns", []),
                deny_patterns=g.get("deny_patterns", []), hitl_timeout_seconds=g["hitl_timeout_seconds"]),
            tests=TestsConfig(command=raw["tests"]["command"]),
        )
```

Create `config.yaml` and `prompts/system.md` mirroring the test fixture (content identical to SPEC §11.5, plus `deny_patterns`).

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(config): YAML config loader with required-field validation`.

---

## Task 3: CredentialStore

**Files:** Create `harness/creds.py`. Test `tests/unit/test_credential_store.py`.

**Interfaces:** Produces `CredentialStore` with `.get() -> str | None`, `.status() -> {"configured": bool}`, `.set(key: str) -> None`, `.clear() -> None`. Loads from `.env` via `python-dotenv`; first-run prompts via `getpass` (hidden). Never echoes plaintext.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_credential_store.py
from harness.creds import CredentialStore

def test_status_does_not_echo_plaintext(tmp_path, monkeypatch):
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-secret-12345\n")
    cs = CredentialStore(env_path=str(env))
    assert cs.status() == {"configured": True}
    assert cs.get() == "sk-secret-12345"

def test_status_when_missing(tmp_path):
    cs = CredentialStore(env_path=str(tmp_path / ".env"))
    assert cs.status() == {"configured": False}
    assert cs.get() is None

def test_set_and_clear(tmp_path):
    env = tmp_path / ".env"; cs = CredentialStore(env_path=str(env))
    cs.set("sk-new"); assert cs.get() == "sk-new"
    cs.clear(); assert cs.get() is None
    # file mode must be 0600 on posix
    import os, stat
    if os.name == "posix":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
```

- [ ] **Step 2: Run → FAIL** (module missing).
- [ ] **Step 3: Implementation**

```python
# harness/creds.py
import os, stat
from pathlib import Path
from dotenv import load_dotenv

ENV_KEY = "DEEPSEEK_API_KEY"

class CredentialStore:
    def __init__(self, env_path: str = ".env"):
        self.env_path = Path(env_path)

    def _load(self) -> str | None:
        if self.env_path.exists():
            load_dotenv(self.env_path, override=True)
        return os.environ.get(ENV_KEY)

    def get(self) -> str | None:
        return self._load()

    def status(self) -> dict:
        return {"configured": bool(self._load())}

    def set(self, key: str) -> None:
        self._write_env({ENV_KEY: key})

    def clear(self) -> None:
        self._write_env({ENV_KEY: ""}, remove=True)

    def _write_env(self, kv: dict, remove: bool = False) -> None:
        lines = []
        if self.env_path.exists():
            lines = [l for l in self.env_path.read_text(encoding="utf-8").splitlines()
                     if not l.startswith(f"{ENV_KEY}=")]
        if not remove:
            lines.append(f"{ENV_KEY}={kv[ENV_KEY]}")
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if os.name == "posix":
            os.chmod(self.env_path, 0o600)
        os.environ.pop(ENV_KEY, None)
        load_dotenv(self.env_path, override=True)

    @staticmethod
    def interactive_first_run(env_path: str = ".env") -> str | None:
        cs = CredentialStore(env_path)
        if cs.get():
            return cs.get()
        import getpass
        key = getpass.getpass("Enter DEEPSEEK_API_KEY (hidden, no echo): ").strip()
        if key:
            cs.set(key)
        return cs.get()
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(creds): .env credential store, hidden-input first run, no plaintext echo`.

---

## Task 4: LLM abstraction + response parser

**Files:** Create `harness/llm/__init__.py`, `harness/llm/base.py`. Test `tests/unit/test_llm_parser.py`.

**Interfaces:** Produces `ToolCall, LLMResponse, LLMClient` (Protocol), `next_action(resp) -> Action | None`. Consumes `Action` (T1).

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_llm_parser.py
from harness.llm.base import LLMResponse, ToolCall, next_action

def test_next_action_returns_first_tool_call():
    resp = LLMResponse(content=None, tool_calls=[
        ToolCall(id="c0", name="read_file", args={"path": "/a"}),
        ToolCall(id="c1", name="write_file", args={"path": "/b", "content": "x"}),
    ], finish_reason="tool_calls")
    a = next_action(resp)
    assert a is not None and a.tool == "read_file" and a.args == {"path": "/a"}

def test_next_action_none_when_done():
    resp = LLMResponse(content="done", tool_calls=[], finish_reason="stop")
    assert next_action(resp) is None
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/llm/base.py
from dataclasses import dataclass
from typing import Protocol
from harness.models import Action

@dataclass
class ToolCall:
    id: str; name: str; args: dict

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str

class LLMClient(Protocol):
    def chat(self, messages: list, tools: list[dict] | None = None) -> LLMResponse: ...

def next_action(resp: LLMResponse) -> Action | None:
    if resp.tool_calls:
        tc = resp.tool_calls[0]
        return Action(tool=tc.name, args=tc.args, raw_llm_response=resp.content)
    return None
```

`harness/llm/__init__.py` re-exports `LLMClient, LLMResponse, ToolCall, next_action`.

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(llm): LLM abstraction, tool-call parser, next_action`.

---

## Task 5: MockLLMClient

**Files:** Create `harness/llm/mock.py`. Test `tests/unit/test_mock_llm.py`. Also add the fixture to `tests/conftest.py`.

**Interfaces:** Produces `MockLLMClient(script: list[LLMResponse])` returning scripted responses by index; raises if exhausted.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_mock_llm.py
import pytest
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient

def test_scripted_responses_in_order():
    m = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "read_file", {"path": "/a"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    assert m.chat([]).tool_calls[0].name == "read_file"
    assert m.chat([]).finish_reason == "stop"

def test_exhausted_raises():
    m = MockLLMClient([LLMResponse("done", [], "stop")])
    m.chat([])
    with pytest.raises(StopIteration):
        m.chat([])
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/llm/mock.py
from harness.llm.base import LLMResponse, ToolCall

class MockLLMClient:
    def __init__(self, script: list[LLMResponse]):
        self.script = list(script)
        self._idx = 0

    def chat(self, messages, tools=None) -> LLMResponse:
        if self._idx >= len(self.script):
            raise StopIteration("MockLLMClient script exhausted")
        resp = self.script[self._idx]
        self._idx += 1
        return resp
```

Extend `tests/conftest.py` with a `make_mock` helper + scripted-tool factories (used by T15/T18/T19):

```python
# tests/conftest.py
import pytest
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.models import ToolResult

@pytest.fixture
def llm_response():
    def _make(tool=None, args=None, finish=False, content=None):
        if finish:
            return LLMResponse(content or "done", [], "stop")
        return LLMResponse(None, [ToolCall(f"c{x}", tool, args or {})], "tool_calls")
    return _make

class ScriptedTool:
    """Returns canned ToolResults in order (keeps feedback parsing real)."""
    def __init__(self, results):
        self._results = list(results); self._i = 0
    def __call__(self, args):
        r = self._results[self._i]; self._i += 1; return r

@pytest.fixture
def scripted_tool():
    return ScriptedTool
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(llm): MockLLMClient + test fixtures`.

---

## Task 6: ScopeFence  ★ governance

**Files:** Create `harness/governance/__init__.py`, `harness/governance/scope_fence.py`. Test `tests/unit/test_scope_fence.py`.

**Interfaces:** Produces `ScopeFence(allowed_paths).is_allowed(path) -> bool`. Path-normalized prefix check.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_scope_fence.py
from harness.governance.scope_fence import ScopeFence

def test_allows_within_workspace():
    f = ScopeFence(["/workspace/"])
    assert f.is_allowed("/workspace/foo.py") is True
    assert f.is_allowed("/workspace/sub/bar.py") is True

def test_rejects_outside_workspace():
    f = ScopeFence(["/workspace/"])
    assert f.is_allowed("/etc/passwd") is False
    assert f.is_allowed("/workspace_evil/x") is False  # prefix-not-segment attack

def test_traversal_blocked():
    f = ScopeFence(["/workspace/"])
    assert f.is_allowed("/workspace/../etc/passwd") is False

def test_relative_path_normalized(tmp_path, monkeypatch):
    f = ScopeFence([str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    assert f.is_allowed("./sub/file.py") is True    # relative → normalized under workspace
    assert f.is_allowed("../outside.py") is False   # escapes the root
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/governance/scope_fence.py
import os

class ScopeFence:
    def __init__(self, allowed_paths: list[str]):
        self.roots = [self._norm(p) for p in allowed_paths]

    @staticmethod
    def _norm(p: str) -> str:
        # realpath resolves symlinks + ../ traversal; normcase lowercases on Windows
        # (identity on POSIX) for case-insensitive comparison; path need not exist.
        return os.path.normcase(os.path.realpath(os.path.normpath(p)))

    def is_allowed(self, path: str) -> bool:
        rp = self._norm(path)
        return any(rp == r or rp.startswith(r + os.sep) for r in self.roots)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(governance): ScopeFence path whitelist with traversal protection`.

---

## Task 7: Guardrail  ★ governance

**Files:** Create `harness/governance/guardrail.py`. Test `tests/unit/test_guardrail.py`.

**Interfaces:** Produces `Guardrail(dangerous_patterns, deny_patterns)` with `.is_dangerous(cmd)` (HITL-gated) and `.is_denied(cmd)` (hard-block). Regex matching; `deny` takes precedence.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_guardrail.py
from harness.governance.guardrail import Guardrail

def make():
    return Guardrail(
        dangerous_patterns=[r"git\s+push\s+--force", r"drop\s+(table|database)"],
        deny_patterns=[r"rm\s+-rf\s+/", r":\(\)\{.*\};:"])

def test_deny_hard_blocks_catastrophic():
    g = make()
    assert g.is_denied("rm -rf /") is True
    assert g.is_denied(":(){ :|:& };:") is True

def test_dangerous_goes_to_hitl():
    g = make()
    assert g.is_dangerous("git push --force origin main") is True
    assert g.is_dangerous("DROP TABLE users") is True
    assert g.is_dangerous("ls -la") is False

def test_deny_precedence_over_dangerous():
    g = Guardrail(dangerous_patterns=[r"rm"], deny_patterns=[r"rm\s+-rf\s+/"])
    assert g.is_denied("rm -rf /etc") is True
    assert g.is_dangerous("rm -rf /etc") is False  # denied ones aren't also "dangerous"
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/governance/guardrail.py
import re

class Guardrail:
    def __init__(self, dangerous_patterns: list[str], deny_patterns: list[str]):
        self._dangerous = [re.compile(p, re.IGNORECASE) for p in dangerous_patterns]
        self._deny = [re.compile(p, re.IGNORECASE) for p in deny_patterns]

    def is_denied(self, command: str) -> bool:
        return any(p.search(command) for p in self._deny)

    def is_dangerous(self, command: str) -> bool:
        if self.is_denied(command):
            return False  # deny tier handles it; not also flagged for HITL
        return any(p.search(command) for p in self._dangerous)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(governance): Guardrail deny/HITL pattern matcher`.

---

## Task 8: HITLStateMachine  ★ governance

**Files:** Create `harness/governance/hitl.py`. Test `tests/unit/test_hitl_state_machine.py`.

**Interfaces:** Produces `ApprovalRecord` + `HITLStateMachine` with `create/approve/reject/get/pending`. Status transitions `pending→approved|rejected` are one-way (rejecting an already-decided record raises). IDs are deterministic (monotonic counter; `Math.random`/`time` avoided in-script — counter only).

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_hitl_state_machine.py
import pytest
from harness.governance.hitl import HITLStateMachine, ApprovalRecord
from harness.models import Action

def test_create_is_pending():
    sm = HITLStateMachine()
    a = Action(tool="run_shell", args={"command": "git push --force"})
    rec = sm.create(a)
    assert rec.status == "pending"
    assert rec.action is a
    assert sm.get(rec.id) is rec
    assert rec in sm.pending()

def test_approve_then_reject_is_rejected_state():
    sm = HITLStateMachine()
    rec = sm.create(Action("run_shell", {"command": "x"}))
    approved = sm.approve(rec.id)
    assert approved.status == "approved"
    assert approved.decided_at is not None
    with pytest.raises(ValueError):
        sm.reject(rec.id, "too late")  # already decided

def test_reject_sets_feedback():
    sm = HITLStateMachine()
    rec = sm.create(Action("run_shell", {"command": "rm foo"}))
    rej = sm.reject(rec.id, "user said no")
    assert rej.status == "rejected"
    assert rej.feedback_to_agent == "user said no"

def test_unknown_id_raises():
    sm = HITLStateMachine()
    with pytest.raises(KeyError):
        sm.approve("nope")
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/governance/hitl.py
from dataclasses import dataclass, field
from harness.models import Action

@dataclass
class ApprovalRecord:
    id: str
    action: Action
    status: str = "pending"          # pending | approved | rejected
    created_at: float = 0.0          # injected by caller → deterministic in tests
    decided_at: float | None = None
    feedback_to_agent: str | None = None

class HITLStateMachine:
    def __init__(self):
        self._records: dict[str, ApprovalRecord] = {}
        self._counter = 0

    def create(self, action: Action) -> ApprovalRecord:
        self._counter += 1
        rec = ApprovalRecord(id=f"apv_{self._counter}", action=action)
        self._records[rec.id] = rec
        return rec

    def _decide(self, approval_id: str, status: str, reason: str | None, ts: float) -> ApprovalRecord:
        rec = self._records.get(approval_id)
        if rec is None:
            raise KeyError(approval_id)
        if rec.status != "pending":
            raise ValueError(f"approval {approval_id} already {rec.status}")
        rec.status = status
        rec.decided_at = ts
        if reason is not None:
            rec.feedback_to_agent = reason
        return rec

    def approve(self, approval_id, ts: float = 0.0) -> ApprovalRecord:
        return self._decide(approval_id, "approved", None, ts)

    def reject(self, approval_id, reason: str, ts: float = 0.0) -> ApprovalRecord:
        return self._decide(approval_id, "rejected", reason, ts)

    def get(self, approval_id) -> ApprovalRecord | None:
        return self._records.get(approval_id)

    def pending(self) -> list[ApprovalRecord]:
        return [r for r in self._records.values() if r.status == "pending"]
```

> Note on timestamps: real `time.time()` is injected by callers (`ts=`) so the state machine stays deterministic in tests. Production wires `time.time()`.

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(governance): HITL state machine with one-way transitions`.

---

## Task 9: Governance pipeline  ★ governance

**Files:** Create `harness/governance/pipeline.py`. Test `tests/unit/test_governance_pipeline.py`.

**Interfaces:** Produces `Governance(scope_fence, guardrail, hitl)` with `check(action, approver=None) -> GovernanceDecision`. Flow: extract path args → scope fence; for `run_shell`/`run_tests` extract command → deny (hard block, layer=guardrail) else dangerous (HITL via `approver`, layer=hitl). `approver(record)->bool`: True=approved(not blocked), False=rejected(blocked). If no approver and HITL needed → blocked pending (for real async WebUI).

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_governance_pipeline.py
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.governance.pipeline import Governance
from harness.models import Action

def g():
    return Governance(
        ScopeFence(["/workspace/"]),
        Guardrail(dangerous_patterns=[r"git\s+push\s+--force"], deny_patterns=[r"rm\s+-rf\s+/"]),
        HITLStateMachine())

def test_out_of_scope_blocked_at_fence():
    gov = g()
    d = gov.check(Action("write_file", {"path": "/etc/passwd", "content": "x"}))
    assert d.blocked and d.layer == "scope_fence"

def test_deny_hard_blocked():
    gov = g()
    d = gov.check(Action("run_shell", {"command": "rm -rf /"}))
    assert d.blocked and d.layer == "guardrail"

def test_dangerous_approved_via_approver():
    gov = g()
    d = gov.check(Action("run_shell", {"command": "git push --force"}),
                  approver=lambda rec: True)
    assert not d.blocked
    assert d.layer == "hitl"
    assert d.approval_id is not None

def test_dangerous_rejected_via_approver():
    gov = g()
    d = gov.check(Action("run_shell", {"command": "git push --force"}),
                  approver=lambda rec: False)
    assert d.blocked and d.layer == "hitl"

def test_safe_action_passes():
    gov = g()
    d = gov.check(Action("write_file", {"path": "/workspace/a.py", "content": "x"}))
    assert not d.blocked and d.layer is None
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/governance/pipeline.py
from harness.models import Action, GovernanceDecision

class Governance:
    def __init__(self, scope_fence, guardrail, hitl):
        self.scope_fence = scope_fence
        self.guardrail = guardrail
        self.hitl = hitl

    @staticmethod
    def _paths(action: Action) -> list[str]:
        args = action.args or {}
        for key in ("path", "file"):
            if key in args:
                return [args[key]]
        return []

    @staticmethod
    def _command(action: Action) -> str | None:
        if action.tool in ("run_shell", "run_tests"):
            return (action.args or {}).get("command") or (action.args or {}).get("test_cmd")
        return None

    def check(self, action: Action, approver=None) -> GovernanceDecision:
        for p in self._paths(action):
            if not self.scope_fence.is_allowed(p):
                return GovernanceDecision(blocked=True, reason=f"out of scope: {p}", layer="scope_fence")
        cmd = self._command(action)
        if cmd is not None:
            if self.guardrail.is_denied(cmd):
                return GovernanceDecision(blocked=True, reason=f"denied command: {cmd}", layer="guardrail")
            if self.guardrail.is_dangerous(cmd):
                rec = self.hitl.create(action)
                if approver is None:
                    return GovernanceDecision(blocked=True, reason="awaiting HITL", layer="hitl", approval_id=rec.id)
                if approver(rec):
                    self.hitl.approve(rec.id)
                    action.status = "approved"
                    return GovernanceDecision(blocked=False, reason="approved", layer="hitl", approval_id=rec.id)
                else:
                    self.hitl.reject(rec.id, "rejected by human")
                    action.status = "rejected"
                    return GovernanceDecision(blocked=True, reason="rejected by human", layer="hitl", approval_id=rec.id)
        return GovernanceDecision(blocked=False, reason="ok", layer=None)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(governance): three-layer pipeline (scope→guardrail→hitl)`.

---

## Task 10: ToolRegistry

**Files:** Create `harness/tools/__init__.py`, `harness/tools/base.py`. Test `tests/unit/test_tool_registry.py`.

**Interfaces:** Produces `ToolRegistry.register(name, schema, handler)`, `.dispatch(action) -> ToolResult`, `.schemas() -> list[dict]`. Unknown tool → `ToolResult(ok=False, error=...)`. Handler exceptions caught.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_tool_registry.py
import pytest
from harness.tools.base import ToolRegistry
from harness.models import Action, ToolResult

def echo(args): return ToolResult(ok=True, output={"echo": args})
def boom(args): raise RuntimeError("kaboom")

def test_dispatch_known_tool():
    r = ToolRegistry().register("echo", {"name": "echo"}, echo).dispatch(Action("echo", {"x": 1}))
    assert r.ok and r.output == {"echo": {"x": 1}}

def test_unknown_tool_returns_error():
    r = ToolRegistry().dispatch(Action("nope", {}))
    assert not r.ok and "unknown tool" in (r.error or "").lower()

def test_handler_exception_caught():
    r = ToolRegistry().register("boom", {}, boom).dispatch(Action("boom", {}))
    assert not r.ok and "kaboom" in (r.error or "")
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/tools/base.py
from typing import Callable
from harness.models import Action, ToolResult

ToolHandler = Callable[[dict], ToolResult]

class ToolRegistry:
    def __init__(self):
        self._handlers: dict[str, ToolHandler] = {}
        self._schemas: dict[str, dict] = {}

    def register(self, name: str, schema: dict, handler: ToolHandler) -> "ToolRegistry":
        self._handlers[name] = handler
        self._schemas[name] = schema
        return self

    def dispatch(self, action: Action) -> ToolResult:
        h = self._handlers.get(action.tool)
        if h is None:
            return ToolResult(ok=False, output={}, error=f"unknown tool: {action.tool}")
        try:
            return h(action.args or {})
        except Exception as e:  # never crash the loop
            return ToolResult(ok=False, output={}, error=f"{type(e).__name__}: {e}")

    def schemas(self) -> list[dict]:
        return list(self._schemas.values())
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(tools): ToolRegistry dispatch with safe error capture`.

---

## Task 11: Builtin tools

**Files:** Create `harness/tools/builtin.py`. Test `tests/unit/test_builtin_tools.py`.

**Interfaces:** Produces `register_builtins(registry, config)` registering `read_file`/`write_file`/`run_shell`/`run_tests` handlers (each `args -> ToolResult`). `run_tests` executes the configured test command and returns `{"command", "stdout", "exit_code"}` (parsing happens later in `TestRunner`).

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_builtin_tools.py
from harness.tools.base import ToolRegistry
from harness.tools.builtin import register_builtins
from harness.models import Action, ToolResult

def cfg(tmp_path):
    class C: tests = type("T", (), {"command": "pytest -q"})(); 
    return C

def test_read_write_file_roundtrip(tmp_path):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    w = reg.dispatch(Action("write_file", {"path": str(tmp_path/"a.py"), "content": "hi"}))
    assert w.ok and w.output["bytes_written"] == 2
    r = reg.dispatch(Action("read_file", {"path": str(tmp_path/"a.py")}))
    assert r.ok and r.output["content"] == "hi"

def test_read_missing_file_is_error(tmp_path):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    r = reg.dispatch(Action("read_file", {"path": str(tmp_path/"nope.py")}))
    assert not r.ok

def test_run_shell_captures_output(tmp_path):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    r = reg.dispatch(Action("run_shell", {"command": "echo hello"}))
    assert r.ok and "hello" in r.output["stdout"]
```

> Scope enforcement at the tool layer is belt-and-suspenders; governance is authoritative. Tools here just execute within `workspace`.

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/tools/builtin.py
import subprocess
from harness.tools.base import ToolRegistry
from harness.models import ToolResult

def register_builtins(registry: ToolRegistry, config=None, workspace: str = ".") -> None:
    def read_file(args):
        p = args["path"]
        try:
            content = open(p, "r", encoding="utf-8").read()
            return ToolResult(ok=True, output={"content": content, "bytes": len(content.encode())})
        except FileNotFoundError:
            return ToolResult(ok=False, output={}, error=f"not found: {p}")
        except OSError as e:
            return ToolResult(ok=False, output={}, error=f"{e}")

    def write_file(args):
        p, content = args["path"], args["content"]
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(ok=True, output={"bytes_written": len(content.encode())})
        except OSError as e:
            return ToolResult(ok=False, output={}, error=f"{e}")

    def run_shell(args):
        cmd = args["command"]
        try:
            proc = subprocess.run(cmd, shell=True, cwd=workspace,
                                  capture_output=True, text=True, timeout=60)
            return ToolResult(ok=proc.returncode == 0,
                              output={"stdout": proc.stdout, "stderr": proc.stderr,
                                      "exit_code": proc.returncode, "command": cmd})
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output={"command": cmd}, error="timeout after 60s")

    def run_tests(args):
        cmd = (config.tests.command if config else args.get("test_cmd", "pytest -q"))
        try:
            proc = subprocess.run(cmd, shell=True, cwd=workspace,
                                  capture_output=True, text=True, timeout=120)
            return ToolResult(ok=proc.returncode == 0,
                              output={"command": cmd, "stdout": proc.stdout + proc.stderr,
                                      "exit_code": proc.returncode})
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output={"command": cmd}, error="test timeout 120s")

    registry.register("read_file", {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}, read_file)
    registry.register("write_file", {"name": "write_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}}, write_file)
    registry.register("run_shell", {"name": "run_shell", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}, run_shell)
    registry.register("run_tests", {"name": "run_tests", "parameters": {"type": "object"}}, run_tests)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(tools): read/write/run_shell/run_tests builtins`.

---

## Task 12: TestRunner (feedback signal)  ★ feedback

**Files:** Create `harness/feedback/__init__.py`, `harness/feedback/test_runner.py`. Test `tests/unit/test_test_runner.py`.

**Interfaces:** Produces `TestRunner.parse(tool_result: ToolResult) -> TestFeedback`. Regex on pytest `-v` summary lines (`passed`/`failed`/`error`); parse failure → return raw_output, never crash.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_test_runner.py
from harness.feedback.test_runner import TestRunner
from harness.models import ToolResult

def make(stdout, exit_code=1):
    return ToolResult(ok=exit_code == 0, output={"stdout": stdout, "exit_code": exit_code, "command": "pytest"})

def test_parse_all_pass():
    tf = TestRunner().parse(make("==== 3 passed in 0.12s ====", exit_code=0))
    assert tf.passed == 3 and tf.failed == 0 and tf.success

def test_parse_failures():
    out = "FAILED tests/test_a.py::test_one\nFAILED tests/test_a.py::test_two\n==== 2 failed in 0.5s ===="
    tf = TestRunner().parse(make(out))
    assert tf.failed == 2 and not tf.success
    assert any("test_one" in e for e in tf.errors)

def test_parse_errors_and_skipped():
    out = ("ERROR tests/test_a.py::test_a\n"
           "ERROR tests/test_a.py::test_b\n"
           "==== 1 passed, 1 failed, 2 errors, 3 skipped in 1s ====")
    tf = TestRunner().parse(make(out))
    assert tf.passed == 1 and tf.failed == 1
    assert len(tf.errors) >= 2

def test_unparseable_returns_raw():
    tf = TestRunner().parse(make("totally not pytest output"))
    assert tf.passed == 0 and tf.failed == 0 and not tf.success
    assert tf.raw_output == "totally not pytest output"
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/feedback/test_runner.py
import re
from harness.models import ToolResult, TestFeedback

class TestRunner:
    # Individual FAILED/ERROR lines from pytest's short-test-summary section.
    FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(.+)$", re.M)

    def parse(self, tool_result: ToolResult) -> TestFeedback:
        out = (tool_result.output or {}).get("stdout", "") or ""
        m = re.search(r"(\d+)\s*passed", out, re.I)
        f = re.search(r"(\d+)\s*failed", out, re.I)
        e = re.findall(self.FAILED_LINE, out)
        passed = int(m.group(1)) if m else 0
        failed = int(f.group(1)) if f else 0
        if m is None and f is None and not e:
            return TestFeedback(0, 0, [], out)  # unparseable → raw, no crash
        return TestFeedback(passed=passed, failed=failed, errors=e, raw_output=out)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(feedback): deterministic pytest output parser`.

---

## Task 13: FeedbackInjector

**Files:** Create `harness/feedback/injector.py`. Test `tests/unit/test_feedback_injector.py`.

**Interfaces:** Produces `FeedbackInjector(context_store)` with `.inject_result(action, result, tool_call_id)`, `.inject_test(action, tf, tool_call_id)`, `.inject_block(action, decision, tool_call_id)`. Each appends a `Message(role="tool", content=..., tool_call_id=...)`.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_feedback_injector.py
from harness.memory.context_store import ContextStore
from harness.feedback.injector import FeedbackInjector
from harness.models import Action, ToolResult, GovernanceDecision, TestFeedback

def cs(): return ContextStore(system_prompt="sys")

def test_inject_result_appends_tool_message():
    s = cs(); fi = FeedbackInjector(s)
    fi.inject_result(Action("read_file", {"path": "/a"}), ToolResult(True, {"content": "hi"}), "c0")
    assert s.messages[-1].role == "tool"
    assert "hi" in s.messages[-1].content and s.messages[-1].tool_call_id == "c0"

def test_inject_test_serializes_feedback():
    s = cs(); fi = FeedbackInjector(s)
    fi.inject_test(Action("run_tests", {}), TestFeedback(2, 1, ["e"], "raw"), "c0")
    assert "failed=1" in s.messages[-1].content and "errors=[e]" in s.messages[-1].content

def test_inject_block_reports_block_reason():
    s = cs(); fi = FeedbackInjector(s)
    fi.inject_block(Action("run_shell", {"command": "rm -rf /"}),
                    GovernanceDecision(True, "denied command", "guardrail"), "c0")
    assert "BLOCKED" in s.messages[-1].content and "denied command" in s.messages[-1].content
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/feedback/injector.py
from harness.models import Action, ToolResult, GovernanceDecision, TestFeedback, Message

class FeedbackInjector:
    def __init__(self, context_store):
        self.context_store = context_store

    def _add(self, content: str, tool_call_id: str) -> None:
        self.context_store.add(Message(role="tool", content=content, tool_call_id=tool_call_id))

    def inject_result(self, action: Action, result: ToolResult, tool_call_id: str) -> None:
        if result.ok:
            self._add(f"[ok] {action.tool} -> {result.output}", tool_call_id)
        else:
            self._add(f"[error] {action.tool} failed: {result.error}", tool_call_id)

    def inject_test(self, action: Action, tf: TestFeedback, tool_call_id: str) -> None:
        status = "PASSED" if tf.success else "FAILED"
        errs = "; ".join(tf.errors) if tf.errors else ""
        self._add(f"[test {status}] passed={tf.passed} failed={tf.failed} errors=[{errs}]", tool_call_id)

    def inject_block(self, action: Action, decision: GovernanceDecision, tool_call_id: str) -> None:
        self._add(f"[BLOCKED by {decision.layer}] {decision.reason}", tool_call_id)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(feedback): FeedbackInjector serializes results/blocks into context`.

---

## Task 14: ContextStore (memory)

**Files:** Create `harness/memory/__init__.py`, `harness/memory/context_store.py`. Test `tests/unit/test_context_store.py`.

**Interfaces:** Produces `ContextStore(system_prompt, max_messages=50)` with `.messages`, `.add(msg)`, `.truncate()` (drop oldest non-system messages over cap).

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_context_store.py
from harness.memory.context_store import ContextStore
from harness.models import Message

def test_system_prompt_always_first():
    s = ContextStore("sys", max_messages=10)
    assert s.messages[0].role == "system" and s.messages[0].content == "sys"

def test_truncate_drops_oldest_non_system():
    s = ContextStore("sys", max_messages=4)
    for i in range(6):
        s.add(Message("user", f"u{i}"))
    s.truncate()
    assert len(s.messages) == 4
    assert s.messages[0].role == "system"
    assert s.messages[-1].content == "u5"           # newest kept
    assert s.messages[1].content == "u3"            # oldest non-system dropped (u0,u1,u2)

def test_add_keeps_system_first():
    s = ContextStore("sys")
    s.add(Message("user", "hi"))
    assert s.messages[0].role == "system"
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/memory/context_store.py
from harness.models import Message

class ContextStore:
    def __init__(self, system_prompt: str, max_messages: int = 50):
        self._messages: list[Message] = [Message(role="system", content=system_prompt)]
        self.max_messages = max_messages

    @property
    def messages(self) -> list[Message]:
        return self._messages

    def add(self, msg: Message) -> None:
        self._messages.append(msg)
        self.truncate()

    def truncate(self) -> None:
        if len(self._messages) <= self.max_messages:
            return
        system = self._messages[0]
        rest = self._messages[1:]
        keep = rest[-(self.max_messages - 1):]
        self._messages = [system] + keep
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(memory): ContextStore with non-system message truncation`.

---

## Task 15: AgentLoop (main loop)  ★ core

**Files:** Create `harness/loop.py`. Test `tests/unit/test_agent_loop.py` (minimal); full mock-driven loop in T18.

**Interfaces:** Produces `AgentLoop(llm, config, governance, tools, context_store, feedback_injector, test_runner, approver=None).run(task) -> AgentRunResult`. Flow: add user msg → loop ≤ max_iters: `llm.chat` → `next_action`; None → success; `governance.check(action, approver)`; blocked → record+inject+continue; else `tools.dispatch`; if `run_tests` → `test_runner.parse` + `inject_test`; else `inject_result`; track executed commands. max_iters → "max_iters".

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_agent_loop.py
from harness.loop import AgentLoop
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.governance.pipeline import Governance
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.tools.base import ToolRegistry
from harness.tools.builtin import register_builtins
from harness.feedback.injector import FeedbackInjector
from harness.feedback.test_runner import TestRunner
from harness.memory.context_store import ContextStore
from harness.config import AgentConfig

def build_loop(mock, tmp_path, approver=None):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    gov = Governance(ScopeFence([str(tmp_path)+"/"]), Guardrail([], [r"rm\s+-rf\s+/"]), HITLStateMachine())
    class C: max_iters=10
    cs = ContextStore("sys")  # ONE store shared by loop + injector so feedback reaches the LLM
    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), approver=approver)

def test_loop_stops_on_done(tmp_path):
    mock = MockLLMClient([LLMResponse("done", [], "stop")])
    r = build_loop(mock, tmp_path).run("hi")
    assert r.final_status == "success" and r.iterations == 1

def test_loop_executes_then_done(tmp_path):
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "write_file", {"path": str(tmp_path/"a.py"), "content": "x"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = build_loop(mock, tmp_path).run("write a.py")
    assert r.final_status == "success"
    assert (tmp_path/"a.py").read_text() == "x"
    assert r.iterations == 2
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/loop.py
from harness.models import Action, AgentRunResult, Message
from harness.llm.base import next_action

class AgentLoop:
    def __init__(self, llm, config, governance, tools, context_store,
                 feedback_injector, test_runner, approver=None):
        self.llm = llm
        self.config = config
        self.governance = governance
        self.tools = tools
        self.context_store = context_store
        self.feedback_injector = feedback_injector
        self.test_runner = test_runner
        self.approver = approver

    def run(self, task: str) -> AgentRunResult:
        actions: list[Action] = []
        executed: list[str] = []
        self.context_store.add(Message("user", task))
        max_iters = getattr(self.config, "max_iters", 20)
        for i in range(1, max_iters + 1):
            try:
                resp = self._chat_with_retry()
            except StopIteration:  # mock script exhausted → end gracefully, don't crash
                return AgentRunResult("error", i, actions, executed)
            if resp is None:
                return AgentRunResult("error", i, actions, executed)
            action = next_action(resp)
            if action is None:
                return AgentRunResult("success", i, actions, executed)
            decision = self.governance.check(action, approver=self.approver)
            action.blocked = decision.blocked
            action.block_reason = decision.reason
            action.approval_id = decision.approval_id
            actions.append(action)
            tool_call_id = resp.tool_calls[0].id if resp.tool_calls else f"step{i}"
            if decision.blocked:
                self.feedback_injector.inject_block(action, decision, tool_call_id)
                continue
            result = self.tools.dispatch(action)
            if action.tool == "run_tests":
                tf = self.test_runner.parse(result)
                self.feedback_injector.inject_test(action, tf, tool_call_id)
                executed.append(action.args.get("test_cmd") or "pytest")
            else:
                self.feedback_injector.inject_result(action, result, tool_call_id)
                if action.tool in ("run_shell",):
                    executed.append(action.args.get("command", ""))
        return AgentRunResult("max_iters", max_iters, actions, executed)

    def _chat_with_retry(self, retries: int = 3):
        last = None
        for _ in range(retries):
            try:
                return self.llm.chat(self.context_store.messages, tools=self.tools.schemas())
            except StopIteration:
                raise
            except Exception as e:
                last = e
        return None
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(loop): AgentLoop main loop (governance→dispatch→feedback→stop)`.

---

## Task 16: CLI entry point

**Files:** Create `harness/__main__.py`. Test `tests/unit/test_cli.py` (uses `subprocess`/`sys.argv` via `main(argv)`).

**Interfaces:** Produces `main(argv=None)` dispatching `run <task>`, `serve`, `creds {status|set|clear}`. `serve` launches the WebUI (T17). Real `run` wires `DeepSeekClient` (T-real) but tests use a `--mock` flag.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_cli.py
import subprocess, sys
def test_creds_status_when_missing(tmp_path, monkeypatch, capsys):
    from harness.__main__ import main
    monkeypatch.chdir(tmp_path)
    rc = main(["creds", "status"])
    out = capsys.readouterr().out
    assert rc == 0 and "configured: false" in out.lower()
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/__main__.py
import sys
from harness.creds import CredentialStore

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: harness [run <task>|serve|creds {status|set|clear}] [--mock]"); return 0
    cmd = argv[0]
    if cmd == "creds":
        sub = argv[1] if len(argv) > 1 else "status"
        cs = CredentialStore()
        if sub == "status":
            print(f"configured: {'true' if cs.get() else 'false'}"); return 0
        if sub == "set":
            import getpass
            key = getpass.getpass("Paste DEEPSEEK_API_KEY (hidden, no echo): ").strip()
            cs.set(key); print("stored."); return 0
        if sub == "clear":
            cs.clear(); print("cleared."); return 0
        print(f"unknown creds subcommand: {sub}"); return 2
    if cmd == "serve":
        from harness.server import serve; serve(); return 0
    if cmd == "run":
        return _run(argv[1:])
    print(f"unknown command: {cmd}"); return 2

def _run(args):
    from harness.config import Config
    from harness.creds import CredentialStore
    from harness.tools.base import ToolRegistry
    from harness.tools.builtin import register_builtins
    from harness.governance.pipeline import Governance
    from harness.governance.scope_fence import ScopeFence
    from harness.governance.guardrail import Guardrail
    from harness.governance.hitl import HITLStateMachine
    from harness.memory.context_store import ContextStore
    from harness.feedback.injector import FeedbackInjector
    from harness.feedback.test_runner import TestRunner
    from harness.loop import AgentLoop
    cfg = Config.load("config.yaml")
    sys_prompt = open(cfg.agent.system_prompt_file, encoding="utf-8").read()
    if "--mock" in args:
        from harness.llm.mock import MockLLMClient
        from harness.llm.base import LLMResponse, ToolCall
        llm = MockLLMClient([LLMResponse("done", [], "stop")])
        task = " ".join(a for a in args if a != "--mock")
    else:
        from harness.llm.deepseek import DeepSeekClient
        key = CredentialStore.interactive_first_run()
        llm = DeepSeekClient(api_key=key, model=cfg.llm.model, base_url=cfg.llm.base_url)
        task = " ".join(args)
    reg = ToolRegistry(); register_builtins(reg, cfg)
    gov = Governance(ScopeFence(cfg.governance.allowed_paths),
                     Guardrail(cfg.governance.dangerous_patterns, cfg.governance.deny_patterns),
                     HITLStateMachine())
    cs = ContextStore(sys_prompt)  # shared store — feedback reaches the LLM context
    loop = AgentLoop(llm, cfg, gov, reg, cs, FeedbackInjector(cs), TestRunner())
    result = loop.run(task)
    print(f"status={result.final_status} iters={result.iterations} "
          f"actions={len(result.actions)} executed={len(result.executed_commands)}")
    return 0 if result.final_status == "success" else 1

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(cli): harness run/serve/creds entry point`.

---

## Task 17: WebUI (FastAPI HITL approval)

**Files:** Create `harness/web/__init__.py`, `harness/web/app.py`. Test `tests/unit/test_web.py` (httpx TestClient).

**Interfaces:** Produces `make_app(hitl) -> FastAPI` with `GET /` (list pending), `GET /approvals` (JSON), `POST /approvals/{id}/{approve|reject}`. `serve(host, port)` runs uvicorn. WebUI is the HITL surface for governance.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_web.py
from fastapi.testclient import TestClient
from harness.governance.hitl import HITLStateMachine
from harness.models import Action
from harness.web.app import make_app

def test_pending_list_and_approve():
    sm = HITLStateMachine()
    rec = sm.create(Action("run_shell", {"command": "git push --force"}))
    c = TestClient(make_app(sm))
    r = c.get("/approvals"); assert r.status_code == 200
    assert rec.id in [a["id"] for a in r.json()["pending"]]
    c.post(f"/approvals/{rec.id}/approve")
    assert sm.get(rec.id).status == "approved"

def test_reject_records_reason():
    sm = HITLStateMachine()
    rec = sm.create(Action("run_shell", {"command": "x"}))
    c = TestClient(make_app(sm))
    c.post(f"/approvals/{rec.id}/reject", json={"reason": "no"})
    assert sm.get(rec.id).status == "rejected"
    assert sm.get(rec.id).feedback_to_agent == "no"

def test_unknown_id_404():
    c = TestClient(make_app(HITLStateMachine()))
    assert c.post("/approvals/nope/approve").status_code == 404
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementation**

```python
# harness/web/app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from harness.governance.hitl import HITLStateMachine

class RejectBody(BaseModel):
    reason: str = "rejected"

def make_app(hitl: HITLStateMachine) -> FastAPI:
    app = FastAPI(title="Coding Agent Harness — HITL")

    @app.get("/approvals")
    def list_pending():
        return {"pending": [{"id": r.id, "tool": r.action.tool, "args": r.action.args} for r in hitl.pending()]}

    @app.get("/")
    def root():
        ps = hitl.pending()
        rows = "".join(
            f"<tr><td>{r.id}</td><td>{r.action.tool}</td><td>{r.action.args}</td>"
            f'<td><a href="/approvals/{r.id}/approve">approve</a> '
            f'<a href="/approvals/{r.id}/reject?reason=no">reject</a></td></tr>' for r in ps) or "<tr><td>none</td></tr>"
        return f"<html><body><h1>Pending approvals</h1><table border=1>{rows}</table></body></html>"

    @app.post("/approvals/{approval_id}/approve")
    def approve(approval_id: str):
        if not hitl.get(approval_id) or hitl.get(approval_id).status != "pending":
            raise HTTPException(404, "not pending")
        hitl.approve(approval_id); return {"status": "approved"}

    @app.post("/approvals/{approval_id}/reject")
    def reject(approval_id: str, body: RejectBody | None = None):
        if not hitl.get(approval_id) or hitl.get(approval_id).status != "pending":
            raise HTTPException(404, "not pending")
        hitl.reject(approval_id, (body.reason if body else "rejected")); return {"status": "rejected"}

    @app.get("/approvals/{approval_id}/approve")  # convenience link
    def approve_link(approval_id: str):
        return approve(approval_id)

    @app.get("/approvals/{approval_id}/reject")
    def reject_link(approval_id: str, reason: str = "rejected"):
        return reject(approval_id, RejectBody(reason=reason))

    return app
```

> Note: `serve()` lives in `harness/server.py` (`server.serve(config_path, host, port)`, the full app with `/health` `/run` `/activity` — see Task 16b / unit5-supplement). `app.py` exposes only `make_app`. The CLI `serve` command calls `harness.server.serve`.

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `feat(web): FastAPI HITL approval WebUI`.

---

## Task 18: Integration tests (mock-driven full loop)

**Files:** Create `tests/integration/__init__.py`, `tests/integration/test_agent_loop_mock.py`, `tests/integration/test_governance_pipeline.py`.

**Interfaces:** Drives the whole loop with `MockLLMClient` + `ScriptedTool` (canned test output keeps `TestRunner` parsing real). Verifies the closed loop end-to-end deterministically.

- [ ] **Step 1: Failing test**

```python
# tests/integration/test_agent_loop_mock.py
from harness.loop import AgentLoop
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.governance.pipeline import Governance
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.tools.base import ToolRegistry
from harness.tools.builtin import register_builtins
from harness.feedback.injector import FeedbackInjector
from harness.feedback.test_runner import TestRunner
from harness.memory.context_store import ContextStore
from harness.models import ToolResult
from tests.conftest import ScriptedTool

def build(mock, tmp_path, approver=None, test_results=None):
    reg = ToolRegistry()
    register_builtins(reg, None, workspace=str(tmp_path))   # read/write/shell/tests first
    if test_results is not None:
        reg.register("run_tests", {}, ScriptedTool(test_results))  # OVERRIDE tests w/ canned output
    gov = Governance(ScopeFence([str(tmp_path)+"/"]),
                     Guardrail([r"git\s+push\s+--force"], [r"rm\s+-rf\s+/"]), HITLStateMachine())
    class C: max_iters=20
    cs = ContextStore("sys")
    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), approver=approver)

def test_read_modify_test_pass_loop(tmp_path):
    # LLM: read file -> run_tests (fails) -> write fix -> run_tests (passes) -> done
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "read_file", {"path": str(tmp_path/"t.py")})], "tool_calls"),
        LLMResponse(None, [ToolCall("c1", "run_tests", {})], "tool_calls"),
        LLMResponse(None, [ToolCall("c2", "write_file", {"path": str(tmp_path/"t.py"), "content": "ok"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c3", "run_tests", {})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    loop = build(mock, tmp_path, test_results=[
        ToolResult(False, {"stdout": "==== 1 failed in 0.1s ====", "exit_code": 1, "command": "pytest"}, None),
        ToolResult(True,  {"stdout": "==== 1 passed in 0.1s ====", "exit_code": 0, "command": "pytest"}, None),
    ])
    r = loop.run("fix the test")
    assert r.final_status == "success" and r.iterations == 5
```

`tests/integration/test_governance_pipeline.py` tests the **scope-fence and deny layers** end-to-end through the loop — complementing demo③ (which covers the HITL-gate path). It uses no approver and no `run_tests`, so `config=None` is safe (`register_builtins` only dereferences `config` inside the `run_tests` closure):

```python
# tests/integration/test_governance_pipeline.py
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.governance.pipeline import Governance
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.tools.base import ToolRegistry
from harness.tools.builtin import register_builtins
from harness.feedback.injector import FeedbackInjector
from harness.feedback.test_runner import TestRunner
from harness.memory.context_store import ContextStore
from harness.loop import AgentLoop


def _loop(mock, tmp_path, approver=None, dangerous=None, deny=None):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    gov = Governance(ScopeFence([str(tmp_path) + "/"]),
                     Guardrail(dangerous or [], deny or []), HITLStateMachine())
    cs = ContextStore("sys")

    class C:
        max_iters = 20

    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), approver=approver)


def test_scope_fence_blocks_out_of_scope_write(tmp_path):
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "write_file", {"path": "/etc/passwd", "content": "x"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path).run("write outside")
    assert r.actions[0].blocked is True
    assert "scope" in (r.actions[0].block_reason or "").lower()
    assert r.executed_commands == []


def test_deny_blocks_catastrophic_shell(tmp_path):
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "rm -rf /"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path, deny=[r"rm\s+-rf\s+/"]).run("delete all")
    assert r.actions[0].blocked is True
    assert "denied" in (r.actions[0].block_reason or "").lower()
    assert r.executed_commands == []
```

- [ ] **Step 2: Run → FAIL** (`tests/integration/` not yet a package — `__init__.py` missing).
- [ ] **Step 3: Create `tests/integration/__init__.py`** (empty) so pytest collects the package; both test files were written in Step 1.
- [ ] **Step 4: Run** `python -m pytest tests/integration -q` → PASS. (These exercise already-built Units 1–4 through the loop. If RED, a wiring bug surfaced — fix the flagged module, not the test.)
- [ ] **Step 5: Commit** — `test(integration): mock-driven full loop + governance pipeline`.

---

## Task 19: Mechanism demo (A.6)  ★ deliverable

**Files:** Create `tests/demo/__init__.py`, `tests/demo/test_mechanism_demo.py`. Marked `@pytest.mark.demo`.

**Interfaces:** Replays the three A.6 behaviors deterministically under `MockLLMClient`: ① guardrail hard-blocks `rm -rf /`; ② a failing test result is parsed and fed back, agent changes action and passes; ③ HITL reject → agent retries a safe command.

- [ ] **Step 1: Write the failing test (the three `@pytest.mark.demo` cases)**

```python
# tests/demo/test_mechanism_demo.py
import pytest
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.governance.pipeline import Governance
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.tools.base import ToolRegistry
from harness.tools.builtin import register_builtins
from harness.feedback.injector import FeedbackInjector
from harness.feedback.test_runner import TestRunner
from harness.memory.context_store import ContextStore
from harness.loop import AgentLoop
from harness.models import ToolResult

class _Scripted:  # canned run_tests output; keeps TestRunner parsing real
    def __init__(self, results): self._r = list(results); self._i = 0
    def __call__(self, args):
        r = self._r[self._i]; self._i += 1; return r

def _loop(mock, tmp_path, approver=None, dangerous=None, deny=None, test_results=None):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    if test_results is not None:
        reg.register("run_tests", {}, _Scripted(test_results))
    gov = Governance(ScopeFence([str(tmp_path) + "/"]),
                     Guardrail(dangerous or [], deny or []), HITLStateMachine())
    cs = ContextStore("sys")
    class C: max_iters = 20
    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), approver=approver)

@pytest.mark.demo
def test_demo_1_guardrail_intercepts(tmp_path):
    """① Guardrail hard-blocks a catastrophic command (rm -rf /) — never executed."""
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "rm -rf /"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path, deny=[r"rm\s+-rf\s+/"]).run("delete everything")
    assert r.actions[0].blocked is True
    assert "denied" in (r.actions[0].block_reason or "").lower()
    assert r.executed_commands == []                       # rm -rf / never ran

@pytest.mark.demo
def test_demo_2_feedback_self_correction(tmp_path):
    """② A failing test is parsed & fed back; agent changes action and tests pass."""
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "write_file", {"path": str(tmp_path/"t.py"), "content": "syntax error!!"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c1", "run_tests", {})], "tool_calls"),
        LLMResponse(None, [ToolCall("c2", "write_file", {"path": str(tmp_path/"t.py"), "content": "def test_ok():\n    assert True\n"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c3", "run_tests", {})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path, test_results=[
        ToolResult(False, {"stdout": "==== 1 failed in 0.1s ====", "exit_code": 1, "command": "pytest"}, None),
        ToolResult(True,  {"stdout": "==== 1 passed in 0.1s ====", "exit_code": 0, "command": "pytest"}, None),
    ]).run("fix the test")
    assert r.final_status == "success" and r.iterations == 5
    assert r.actions[1].tool == "run_tests" and r.actions[3].tool == "run_tests"

@pytest.mark.demo
def test_demo_3_hitl_rejection_changes_strategy(tmp_path):
    """③ HITL rejects a dangerous command; agent retries with a safe command."""
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "git push --force"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c1", "run_shell", {"command": "git status"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path, approver=lambda rec: False,
              dangerous=[r"git\s+push\s+--force"]).run("push my code")
    assert r.actions[0].status == "rejected"
    assert r.actions[0].blocked is True
    assert "git push --force" not in r.executed_commands
    assert "git status" in r.executed_commands
```

- [ ] **Step 2: Run → FAIL** (file missing) — `python -m pytest tests/demo/test_mechanism_demo.py -q` → collection error (no module).
- [ ] **Step 3: Implementation** — the test file above IS the implementation (demos are tests). Create `tests/demo/__init__.py` (empty) + `tests/demo/test_mechanism_demo.py` with the code above verbatim.
- [ ] **Step 4: Run** `python -m pytest -m demo -q` → 3/3 PASS.
- [ ] **Step 5: Commit** — `test(demo): A.6 three deterministic mechanism demonstrations`.

---

## Task 20: Packaging, Makefile, .env.example

**Files:** Create `Makefile`, `.env.example`. Finalize `pyproject.toml` (already from T1; verify console script + markers).

- [ ] **Step 1: Verify** `make test` ≡ `pytest -q` runs green (no test file here; this task is build glue).
- [ ] **Step 2: Implementation**

```makefile
# Makefile
.PHONY: test lint serve docker
test:
	pytest -q
lint:
	python -m compileall -q harness
serve:
	python -m harness serve
docker:
	docker build -t coding-harness .
```

```bash
# .env.example
# Copy to .env and fill in your key. .env is gitignored.
DEEPSEEK_API_KEY=
```

- [ ] **Step 3: Run** `make test` → all green.
- [ ] **Step 4: Commit** — `build: Makefile, .env.example, packaging`.

---

## Task 21: Dockerfile + render.yaml

**Files:** Create `Dockerfile`, `.dockerignore`, `render.yaml`.

- [ ] **Step 1: Implementation**

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY harness ./harness
COPY config.yaml ./
COPY prompts ./prompts
RUN pip install --no-cache-dir .
EXPOSE 8000
USER 65532
CMD ["python", "-m", "harness", "serve"]
```

```yaml
# render.yaml
services:
  - type: web
    name: coding-agent-harness
    runtime: docker
    plan: free
    dockerfilePath: ./Dockerfile
    envVars:
      - key: DEEPSEEK_API_KEY
        sync: false   # set secret in Render dashboard; never plaintext
    healthCheckPath: /health
```

```bash
# .dockerignore — keep the image lean and keep secrets OUT (.env is never COPYed,
# but list it here too as defense-in-depth)
.git
__pycache__/
*.pyc
*.pyo
.env
.env.*
.superpowers/
tests/
docs/
*.md
.venv/
.pytest_cache/
```

- [ ] **Step 2: Verify** `docker build -t coding-harness .` succeeds locally.
- [ ] **Step 3: Commit** — `build: Dockerfile + render.yaml one-click deploy`.

---

## Task 22: CI (GitLab + GitHub Actions)

**Files:** Create `.gitlab-ci.yml`, `.github/workflows/ci.yml`.

- [ ] **Step 1: Implementation**

```yaml
# .gitlab-ci.yml
image: python:3.11-slim
stages: [test]
unit-test:
  stage: test
  script:
    - pip install --no-cache-dir ".[test]"
    - pytest -q
  rules:
    - if: $CI_PIPELINE_SOURCE == "push"
```

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  unit-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install --no-cache-dir ".[test]"
      - run: pytest -q
```

- [ ] **Step 2: Run** `pytest -q` locally → green (proxy for CI pass).
- [ ] **Step 3: Commit** — `ci: GitLab unit-test job + GitHub Actions mirror`.

---

## Task 23: README.md

**Files:** Create `README.md` with required sections: project intro, install, run, distribution commands, directory structure, security boundaries (credential threat model summary).

- [ ] **Step 1: Implementation** — write README covering: what it is; `pip install -e ".[test]"` / `make test`; `harness run "..."` / `harness serve` / `harness creds status|set|clear`; Docker `docker build` + `docker run -e DEEPSEEK_API_KEY=... -p 8000:8000 ...`; directory tree; security boundary (key in `.env`, never in git/image/logs, plaintext risk of `.env`, 600 perms); deployment (render.yaml one-click, fill URL placeholder); known limits (platform, Docker required for container path).
- [ ] **Step 2: Commit** — `docs: README with install/run/distribute/security sections`.

---

## Task 24: Process deliverables (SPEC_PROCESS, AGENT_LOG, REFLECTION)

**Files:** Create `SPEC_PROCESS.md`, `AGENT_LOG.md`, `REFLECTION.md`.

- `SPEC_PROCESS.md`: brainstorming key questions + ≥3 iteration excerpts + cold-start stranger-agent findings (T-cold, below) with before/after SPEC diffs.
- `AGENT_LOG.md`: timestamped log of every task: skill triggered, prompt/context config, subagent output/commit hash, human edits, lessons.
- `REFLECTION.md`: 1500–2500 words answering the assignment's reflection prompts.

**Cold-start verification (§4.5) — runs as a separate step before T1 implementation:**
- Dispatch a *fresh* general-purpose subagent with NO conversation history, given only `SPEC.md` + this `PLAN.md`, instructed to attempt 1–2 tasks and **pause on uncertainty** rather than guess. Record where it paused and which spec gaps surfaced; fold findings + SPEC/PLAN diffs into `SPEC_PROCESS.md`.

- [ ] **Step 1: Run cold-start subagent.** [ ] **Step 2: Write the three docs.** [ ] **Step 3: Commit** — `docs: SPEC_PROCESS, AGENT_LOG, REFLECTION`.

---

## Self-Review

1. **Spec coverage:** SPEC §3 modules 1–8 → T1(models),T2(config),T3(creds),T4/T5(llm),T9(governance),T10/T11(tools),T12/T13(feedback),T14(memory),T15(loop),T16(cli),T17(web) ✓. SPEC §11 governance four mechanisms → T6/T7/T8/T9 ✓. SPEC §12 tests → T6–T19 ✓. SPEC §A.6 demo → T19 ✓. SPEC §7 distribution → T20/T21 ✓. CI §五.6 → T22 ✓.
2. **Placeholder scan:** T18 Step 3 & T19 Step 3 flag "implementer resolves" details — acceptable because the green step is the resolution itself (TDD: red→green); the red tests are concrete. No "TBD"/"handle errors" without code elsewhere.
3. **Type consistency:** `Action`, `ToolResult`, `GovernanceDecision`, `TestFeedback`, `LLMResponse`, `ToolCall`, `ApprovalRecord` signatures match across all tasks and the Shared Interfaces block. `Governance.check(action, approver=)` used identically in T9/T15/T18/T19. `FeedbackInjector.inject_*` signatures identical in T13/T15. ✓

---

## 进度登记（commit hash per task · 通用要求 §4.7）

> ✅ = 已通过两阶段评审（spec 合规 + 代码质量）并合入；⏳ = 待实现。

| Task | 状态 | commit | 备注 |
|---|---|---|---|
| T1 models | ✅ | c41af42 | Unit 1 |
| T2 config | ✅ | 4c537df | Unit 1 |
| T3 creds | ✅ | cd0f5cb +review | 评审修正：`dotenv_values` 去 `os.environ` 污染 + Docker 进程回退（原 `load_dotenv` 破坏 `-e` 凭据流） |
| T4 llm/base | ✅ | 307b581 | Unit 1 |
| T5 mock + conftest | ✅ | 276e944 +review | 评审修正：移除死代码且有 `NameError` 的 `llm_response` fixture，保留 T18 用的 `ScriptedTool` |
| T6 scope_fence | ✅ | d420512 | Unit 2 ★（canonical realpath+normcase+sep，Windows-safe） |
| T7 guardrail | ✅ | 29f43bd | Unit 2 ★（deny/gate 两级 + re.IGNORECASE，subagent 发现并修正） |
| T8 hitl | ✅ | 17ba4aa | Unit 2 ★（pending→approved|rejected 单向，float ts，created_at） |
| T9 gov pipeline | ✅ | e79896f | Unit 2 ★（scope→guardrail→hitl，可注入 Approver；demo①③ 依赖其 wiring） |
| T10–T14 tools/feedback/memory | ✅ | 08075e0..ac61cac (+fix) | Unit 3；review 修 `TestFeedback.success = failed==0 and passed>0`（unparseable 不再误报 PASSED） |
| T15 loop | ✅ | 147f6d3 | Unit 4 ★（invariants 验证：blocked 入 actions、executed 仅非阻断、StopIteration→error、max_iters） |
| T16–T17 cli/web | ✅ | b0b6fda..8bb6751 (+fix e62e226) | Unit 5；review 修：删 `app.py` 死 `serve()`、CLI `_run` 传 llm `max_tokens`/`temperature` |
| T18–T19 integration/demo | ✅ | 8ea66b4 + cd20804 | Unit 6 ★（A.6 三 demo：①guardrail 硬阻断 `rm -rf /` ②feedback 自纠 ③HITL reject→retry；3 integration + 3 demo，确定性无网络，review 一次过） |
| T20–T22 packaging/docker/CI | ✅ | cb1e953..35a5b81 (+§9 fix 080af2d) | Unit 7；reviewer 补 §9「5+ 危险模式」gap（config 7 patterns + test + SPEC §11.5 + server 从 config 读） |
| T23 README + T24 REFLECTION | ✅ | 9f3721a + REFLECTION.md | Unit 8；README 7 章节 + 凭据威胁模型 7 项；REFLECTION 1810 字（§207 AI 起草标注，学生须本人审定） |