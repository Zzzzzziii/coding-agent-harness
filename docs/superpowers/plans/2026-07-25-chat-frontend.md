# Chat-Driven Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a chat-driven Web UI that streams the agent's step-by-step execution (action → governance → tool result → HITL pause → resolve) over SSE, served at the root `/`.

**Architecture:** `AgentLoop` gains an optional `on_event` callback (default `None` → zero behavior change). A module-level `wrap_approver` brackets the existing `blocking_approver` to emit `hitl_pending`/`hitl_resolved`. `HarnessServer` gains a `_runs` registry (`run_id → queue.Queue`); `POST /chat` starts a worker thread that pipes loop events into the queue, `GET /chat/{run_id}/stream` drains it as SSE. A single vanilla-JS `index.html` renders events as chat bubbles; inline approve/reject call the existing `/approvals` endpoints.

**Tech Stack:** Python 3.11, FastAPI/Starlette `StreamingResponse` (sync generator in threadpool), `queue.Queue`, SSE/EventSource, vanilla JS (no build, no CDN).

## Global Constraints

- Credentials (`DEEPSEEK_API_KEY`) NEVER hardcoded / committed / logged / in plaintext configs; the chat frontend sends `mock=true` only — no key in any browser request/response.
- Harness kernel self-implemented (no LangChain/AutoGen/CrewAI); `on_event=None` path must behave identically to before (existing tests stay green).
- TDD mandatory; all tests mock-LLM deterministic, no network, no DeepSeek key.
- `AgentLoop.__init__` new `on_event` kwarg goes AFTER `approver` (both default `None`) so existing positional/kwarg callers are unbroken.
- Follow existing code style: `# harness/...` file-header comments, dataclasses, no type-annotation noise beyond the codebase norm.

---

## File Structure

| path | responsibility | action |
|---|---|---|
| `harness/loop.py` | main loop; add `on_event` + `_emit` + 5 emission points | modify |
| `harness/server.py` | `wrap_approver` fn; `_runs` registry; `run_task(on_event=)`; `POST /chat`; `GET /chat/{run_id}/stream`; `GET /` FileResponse | modify |
| `harness/web/app.py` | HITL approval API; remove the untested GET `/` HTML table | modify |
| `harness/web/static/index.html` | self-contained chat UI (HTML+CSS+JS) | create |
| `tests/unit/test_loop_events.py` | assert loop event sequence + `on_event=None` regression | create |
| `tests/unit/test_wrap_approver.py` | assert hitl_pending/hitl_resolved emission | create |
| `tests/integration/test_streaming.py` | end-to-end SSE: approve/reject/404/health/root | create |
| `README.md` | update §3 Running (chat UI) + §7 Limitations | modify |
| `AGENT_LOG.md` | append stage-6 entry | modify |

Decomposition rationale: each task is one TDD cycle with an independent reviewer gate. `wrap_approver` is a module function (not a method) so it is unit-testable without constructing a `HarnessServer`. The streaming endpoints (Task 3) precede the frontend+root (Task 4) so the UI's `/chat` calls resolve when the page loads.

---

### Task 1: AgentLoop `on_event` emission

**Files:**
- Modify: `harness/loop.py`
- Test: `tests/unit/test_loop_events.py` (create)

**Interfaces:**
- Produces: `AgentLoop.__init__(..., approver=None, on_event=None)`; emits events `{"type":"step","iter":int}`, `{"type":"action","tool":str,"args":dict}`, `{"type":"governance","blocked":bool,"reason":str,"layer":str|None,"approval_id":str|None}`, `{"type":"tool_result","tool":str,"ok":bool,"output":dict,"error":str|None}`, `{"type":"success"|"error"|"max_iters","final_status":str,"iterations":int}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_loop_events.py
from harness.models import ToolResult
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.governance.pipeline import Governance
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.tools.base import ToolRegistry
from harness.feedback.injector import FeedbackInjector
from harness.feedback.test_runner import TestRunner
from harness.memory.context_store import ContextStore
from harness.loop import AgentLoop


def _loop(mock, tmp_path, on_event=None):
    reg = ToolRegistry()
    reg.register("run_shell", {}, lambda args: ToolResult(
        ok=True, output={"stdout": args.get("command", "")}, error=None))
    gov = Governance(ScopeFence([str(tmp_path) + "/"]), Guardrail([], []), HITLStateMachine())
    cs = ContextStore("sys")

    class C:
        max_iters = 20

    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), on_event=on_event)


def test_on_event_emits_full_sequence(tmp_path):
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "echo hi"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    events = []
    _loop(mock, tmp_path, on_event=events.append).run("say hi")
    types = [e["type"] for e in events]
    assert types[0] == "step"
    assert {"type": "action", "tool": "run_shell", "args": {"command": "echo hi"}} in events
    assert any(e["type"] == "governance" and e["blocked"] is False for e in events)
    assert any(e["type"] == "tool_result" and e["tool"] == "run_shell" for e in events)
    assert types[-1] == "success"


def test_on_event_none_no_crash(tmp_path):
    mock = MockLLMClient([LLMResponse("done", [], "stop")])
    r = _loop(mock, tmp_path).run("hi")  # on_event defaults None
    assert r.final_status == "success"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_loop_events.py -v`
Expected: FAIL — `AgentLoop.__init__() got an unexpected keyword argument 'on_event'`.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `harness/loop.py` with:

```python
# harness/loop.py
from harness.models import Action, AgentRunResult, Message
from harness.llm.base import next_action

class AgentLoop:
    def __init__(self, llm, config, governance, tools, context_store,
                 feedback_injector, test_runner, approver=None, on_event=None):
        self.llm = llm
        self.config = config
        self.governance = governance
        self.tools = tools
        self.context_store = context_store
        self.feedback_injector = feedback_injector
        self.test_runner = test_runner
        self.approver = approver
        self.on_event = on_event

    def _emit(self, event):
        if self.on_event is not None:
            self.on_event(event)

    def run(self, task: str) -> AgentRunResult:
        actions: list[Action] = []
        executed: list[str] = []
        self.context_store.add(Message("user", task))
        max_iters = getattr(self.config, "max_iters", 20)
        for i in range(1, max_iters + 1):
            self._emit({"type": "step", "iter": i})
            try:
                resp = self._chat_with_retry()
            except StopIteration:  # mock script exhausted → end gracefully, don't crash
                self._emit({"type": "error", "final_status": "error", "iterations": i})
                return AgentRunResult("error", i, actions, executed)
            if resp is None:
                self._emit({"type": "error", "final_status": "error", "iterations": i})
                return AgentRunResult("error", i, actions, executed)
            action = next_action(resp)
            if action is None:
                self._emit({"type": "success", "final_status": "success", "iterations": i})
                return AgentRunResult("success", i, actions, executed)
            self._emit({"type": "action", "tool": action.tool, "args": action.args})
            decision = self.governance.check(action, approver=self.approver)
            action.blocked = decision.blocked
            action.block_reason = decision.reason
            action.approval_id = decision.approval_id
            actions.append(action)
            self._emit({"type": "governance", "blocked": decision.blocked,
                        "reason": decision.reason, "layer": decision.layer,
                        "approval_id": decision.approval_id})
            tool_call_id = resp.tool_calls[0].id if resp.tool_calls else f"step{i}"
            if decision.blocked:
                self.feedback_injector.inject_block(action, decision, tool_call_id)
                continue
            result = self.tools.dispatch(action)
            self._emit({"type": "tool_result", "tool": action.tool, "ok": result.ok,
                        "output": result.output, "error": result.error})
            if action.tool == "run_tests":
                tf = self.test_runner.parse(result)
                self.feedback_injector.inject_test(action, tf, tool_call_id)
                executed.append(action.args.get("test_cmd") or "pytest")
            else:
                self.feedback_injector.inject_result(action, result, tool_call_id)
                if action.tool in ("run_shell",):
                    executed.append(action.args.get("command", ""))
        self._emit({"type": "max_iters", "final_status": "max_iters", "iterations": max_iters})
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_loop_events.py -v && pytest -q`
Expected: 2 new tests PASS; full suite still green (on_event defaults None → existing loop tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add harness/loop.py tests/unit/test_loop_events.py
git commit -m "feat(loop): add on_event callback emitting step/action/governance/tool_result/done"
```

---

### Task 2: `wrap_approver` HITL event emission

**Files:**
- Modify: `harness/server.py` (add module-level `wrap_approver`)
- Test: `tests/unit/test_wrap_approver.py` (create)

**Interfaces:**
- Consumes: `ApprovalRecord` (`harness.governance.hitl.ApprovalRecord`, fields `id: str`, `action: Action`).
- Produces: `wrap_approver(real_approver: Callable[[ApprovalRecord], bool], on_event: Callable[[dict], None]) -> Callable[[ApprovalRecord], bool]`. Emits `{"type":"hitl_pending","approval_id":str,"tool":str,"args":dict}` before the real approver, `{"type":"hitl_resolved","approval_id":str,"status":"approved"|"rejected"}` after; returns the real approver's bool unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_wrap_approver.py
from harness.server import wrap_approver
from harness.governance.hitl import ApprovalRecord
from harness.models import Action


def _rec(i="apv_1", cmd="git push --force"):
    return ApprovalRecord(id=i, action=Action("run_shell", {"command": cmd}))


def test_wrap_approver_pending_then_resolved_approved():
    events = []
    w = wrap_approver(lambda rec: True, events.append)
    assert w(_rec()) is True
    assert events[0] == {"type": "hitl_pending", "approval_id": "apv_1",
                          "tool": "run_shell", "args": {"command": "git push --force"}}
    assert events[1] == {"type": "hitl_resolved", "approval_id": "apv_1", "status": "approved"}


def test_wrap_approver_rejected():
    events = []
    w = wrap_approver(lambda rec: False, events.append)
    assert w(_rec("apv_2")) is False
    assert events[1] == {"type": "hitl_resolved", "approval_id": "apv_2", "status": "rejected"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_wrap_approver.py -v`
Expected: FAIL — `cannot import name 'wrap_approver' from 'harness.server'`.

- [ ] **Step 3: Write minimal implementation**

Add to the top of `harness/server.py` (after the existing imports, before `blocking_approver`):

```python
def wrap_approver(real_approver, on_event):
    """Wrap an approver to emit hitl_pending (before) and hitl_resolved (after).
    The real approver still owns the blocking wait + timeout; this only brackets it."""
    def _wrapped(rec):
        on_event({"type": "hitl_pending", "approval_id": rec.id,
                  "tool": rec.action.tool, "args": rec.action.args})
        approved = real_approver(rec)
        on_event({"type": "hitl_resolved", "approval_id": rec.id,
                  "status": "approved" if approved else "rejected"})
        return approved
    return _wrapped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_wrap_approver.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add harness/server.py tests/unit/test_wrap_approver.py
git commit -m "feat(server): wrap_approver emits hitl_pending/hitl_resolved events"
```

---

### Task 3: Streaming endpoints (`POST /chat`, `GET /chat/{id}/stream`)

**Files:**
- Modify: `harness/server.py` (`HarnessServer.__init__` + `run_task` signature + `build_app` two new routes)
- Test: `tests/integration/test_streaming.py` (create)

**Interfaces:**
- Consumes: `wrap_approver` (Task 2), `AgentLoop(on_event=)` (Task 1).
- Produces: `HarnessServer.run_task(task, mock=False, on_event=None)`; `HarnessServer._runs: dict[str, queue.Queue]`; HTTP `POST /chat?task=&mock=true -> {"run_id": str}`; HTTP `GET /chat/{run_id}/stream` → `text/event-stream` of `data: {json}\n\n` lines (404 on unknown id).

**Streaming-test mechanic:** approve/reject happens via `POST /approvals/{id}/approve|reject` (existing endpoints, covered by `test_web.py`) BEFORE draining the stream — the worker thread blocks inside `blocking_approver` polling the shared `srv.hitl`; the test waits for `srv.hitl.pending()` to appear, POSTs the decision, then `GET`s the stream which drains the fully-buffered events.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_streaming.py
import json
import time
import textwrap
from fastapi.testclient import TestClient
from harness.config import Config
from harness.server import HarnessServer, build_app


def _cfg(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("sys")
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        llm: {model: deepseek-chat, base_url: "https://api.deepseek.com", max_tokens: 4096, temperature: 0.0}
        agent: {max_iters: 20, system_prompt_file: prompts/system.md}
        governance: {allowed_paths: ["/workspace/"], dangerous_patterns: ["git push --force"], deny_patterns: ["rm -rf /"], hitl_timeout_seconds: 300}
        tests: {command: "pytest -q"}
    """))
    return Config.load(str(p))


def _wait_for_pending(srv, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = srv.hitl.pending()
        if p:
            return p[0]
        time.sleep(0.02)
    raise AssertionError("no HITL pending record appeared in time")


def _events(resp):
    return [json.loads(line[len("data:"):].strip())
            for line in resp.text.splitlines() if line.startswith("data:")]


def test_chat_stream_demo_approve(tmp_path):
    srv = HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))
    c = TestClient(build_app(srv))
    r = c.post("/chat?task=demo&mock=true")
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    rec = _wait_for_pending(srv)  # worker reached git push --force → HITL pending
    c.post(f"/approvals/{rec.id}/approve")  # HTTP approve unblocks the worker

    events = _events(c.get(f"/chat/{run_id}/stream"))
    types = [e["type"] for e in events]
    assert "hitl_pending" in types
    assert {"type": "hitl_resolved", "approval_id": rec.id, "status": "approved"} in events
    assert types[-1] == "success"


def test_chat_stream_demo_reject(tmp_path):
    srv = HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))
    c = TestClient(build_app(srv))
    run_id = c.post("/chat?task=demo&mock=true").json()["run_id"]
    rec = _wait_for_pending(srv)
    c.post(f"/approvals/{rec.id}/reject", json={"reason": "no"})

    events = _events(c.get(f"/chat/{run_id}/stream"))
    types = [e["type"] for e in events]
    assert {"type": "hitl_resolved", "approval_id": rec.id, "status": "rejected"} in events
    assert types[-1] == "success"  # rejected push → loop continues to git status → done


def test_chat_unknown_run_404(tmp_path):
    c = TestClient(build_app(HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))))
    assert c.get("/chat/run_bogus/stream").status_code == 404


def test_health_still_ok(tmp_path):
    c = TestClient(build_app(HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))))
    assert c.get("/health").json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_streaming.py -v`
Expected: FAIL — `404` or `AttributeError` on `POST /chat` (route not yet defined).

- [ ] **Step 3: Write minimal implementation**

Update the top imports of `harness/server.py` to:

```python
# harness/server.py
import threading
import time
import json
import queue as _queue
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from harness.config import Config
from harness.creds import CredentialStore
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
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.web.app import make_app
```

Keep `wrap_approver` (Task 2), `blocking_approver`, `_mock_demo_script` as-is. Replace `HarnessServer` and `build_app` with:

```python
class HarnessServer:
    def __init__(self, config, workspace="."):
        self.config = config
        self.workspace = workspace
        self.hitl = HITLStateMachine()
        self._lock = threading.Lock()
        self.activity = []
        self._runs: dict[str, _queue.Queue] = {}
        self._run_counter = 0

    def run_task(self, task, mock=False, on_event=None):
        if mock:
            llm = _mock_demo_script()
        else:
            from harness.llm.deepseek import DeepSeekClient
            key = CredentialStore.interactive_first_run()
            llm = DeepSeekClient(api_key=key, model=self.config.llm.model,
                                 base_url=self.config.llm.base_url,
                                 max_tokens=self.config.llm.max_tokens,
                                 temperature=self.config.llm.temperature)
        reg = ToolRegistry(); register_builtins(reg, self.config, workspace=self.workspace)
        gov = Governance(ScopeFence(self.config.governance.allowed_paths),
                         Guardrail(self.config.governance.dangerous_patterns,
                                   self.config.governance.deny_patterns),
                         self.hitl)
        approver = blocking_approver(self.hitl, self.config.governance.hitl_timeout_seconds)
        if on_event is not None:
            approver = wrap_approver(approver, on_event)
        cs = ContextStore(open(self.config.agent.system_prompt_file, encoding="utf-8").read())
        loop = AgentLoop(llm, self.config, gov, reg, cs, FeedbackInjector(cs), TestRunner(),
                         approver=approver, on_event=on_event)
        result = loop.run(task)
        with self._lock:
            self.activity.append(f"status={result.final_status} iters={result.iterations} "
                                 f"executed={result.executed_commands}")
        return result.final_status


def build_app(srv):
    """FastAPI app: HITL routes (make_app) + /health + /run + /activity + /chat streaming."""
    app = make_app(srv.hitl)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/run")
    def run_task(task: str, mock: bool = False):
        t = threading.Thread(target=srv.run_task, args=(task,), kwargs={"mock": mock}, daemon=True)
        t.start()
        return {"started": True, "task": task, "mock": mock}

    @app.post("/chat")
    def chat(task: str, mock: bool = True):
        with srv._lock:
            srv._run_counter += 1
            run_id = f"run_{srv._run_counter}"
        q: _queue.Queue = _queue.Queue()
        srv._runs[run_id] = q

        def _worker():
            try:
                srv.run_task(task, mock=mock, on_event=q.put)
            finally:
                q.put(None)  # sentinel: SSE generator stops

        threading.Thread(target=_worker, daemon=True).start()
        return {"run_id": run_id}

    @app.get("/chat/{run_id}/stream")
    def stream(run_id: str):
        if run_id not in srv._runs:
            raise HTTPException(404, "unknown run_id")
        q = srv._runs[run_id]

        def _gen():
            while True:
                try:
                    ev = q.get(timeout=1)
                except _queue.Empty:
                    continue
                if ev is None:
                    break
                yield f"data: {json.dumps(ev)}\n\n"
            srv._runs.pop(run_id, None)

        return StreamingResponse(_gen(), media_type="text/event-stream")

    @app.get("/activity")
    def activity():
        with srv._lock:
            return {"activity": list(srv.activity)}

    return app


def serve(config_path="config.yaml", host="0.0.0.0", port=8000):
    import uvicorn
    cfg = Config.load(config_path)
    srv = HarnessServer(cfg)
    uvicorn.run(build_app(srv), host=host, port=port)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_streaming.py -v && pytest -q`
Expected: 4 new tests PASS; full suite green (existing `POST /run` still works — `on_event` defaults None).

- [ ] **Step 5: Commit**

```bash
git add harness/server.py tests/integration/test_streaming.py
git commit -m "feat(server): POST /chat + GET /chat/{id}/stream SSE over on_event queue"
```

---

### Task 4: Chat UI + root route

**Files:**
- Create: `harness/web/static/index.html`
- Modify: `harness/web/app.py` (remove untested GET `/` HTML table)
- Modify: `harness/server.py` `build_app` (add `GET /` → `FileResponse`)
- Test: `tests/integration/test_streaming.py` (append `test_root_serves_chat_ui`)

**Interfaces:**
- Consumes: `POST /chat` + `GET /chat/{id}/stream` (Task 3), `POST /approvals/{id}/approve|reject` (existing).
- Produces: `GET /` → 200 HTML (the chat UI); `make_app` no longer registers `/`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_streaming.py`:

```python
def test_root_serves_chat_ui(tmp_path):
    c = TestClient(build_app(HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))))
    r = c.get("/")
    assert r.status_code == 200
    assert "chat" in r.text.lower()
    assert "EventSource" in r.text or "/chat/" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_streaming.py::test_root_serves_chat_ui -v`
Expected: FAIL — `404` (no `GET /` in `build_app` yet; `make_app`'s `/` was removed in Step 3 below, but if you run before editing, `make_app`'s `/` returns the old HITL table which lacks "EventSource"). Either way: FAIL until the chat UI is served at `/`.

- [ ] **Step 3: Write minimal implementation**

3a. Create `harness/web/static/index.html`:

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coding Agent Harness</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; margin: 0; background: #f7f7f8; color: #222; }
  header { background: #1f2937; color: #fff; padding: 12px 20px; }
  header h1 { margin: 0; font-size: 18px; }
  header span { opacity: .7; font-size: 12px; margin-left: 8px; }
  #chat { max-width: 820px; margin: 0 auto; padding: 16px; }
  #log { min-height: 320px; }
  .msg { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px 12px; margin: 6px 0; font-size: 14px; }
  .step { color: #6b7280; font-size: 12px; text-align: center; margin: 10px 0; background: transparent; border: none; }
  .agent { border-left: 3px solid #3b82f6; }
  .gov-ok { border-left: 3px solid #10b981; }
  .gov-block { border-left: 3px solid #ef4444; background: #fef2f2; }
  .tool { border-left: 3px solid #8b5cf6; }
  .hitl { border-left: 3px solid #f59e0b; background: #fffbeb; }
  .term { border-left: 3px solid #111827; font-weight: bold; }
  .btns button { margin-right: 8px; padding: 4px 12px; border-radius: 6px; border: 1px solid #d1d5db; background: #fff; cursor: pointer; }
  .btns .approve { border-color: #10b981; color: #047857; }
  .btns .reject { border-color: #ef4444; color: #b91c1c; }
  .btns button:disabled { opacity: .4; cursor: default; }
  pre { white-space: pre-wrap; margin: 4px 0; font-size: 13px; }
  form { display: flex; gap: 8px; margin-top: 16px; }
  input { flex: 1; padding: 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; }
  button.send { padding: 10px 18px; border: none; background: #3b82f6; color: #fff; border-radius: 8px; font-size: 14px; cursor: pointer; }
  button.send:disabled { background: #9ca3af; }
</style>
</head>
<body>
<header><h1>Coding Agent Harness</h1><span>governance deep-dive · mock demo</span></header>
<div id="chat">
  <div id="log"></div>
  <form id="f">
    <input id="task" placeholder="输入任务（mock demo：propose git push --force → HITL → git status → done）" value="demo" autocomplete="off">
    <button class="send" id="send" type="submit">发送</button>
  </form>
</div>
<script>
const log = document.getElementById("log");
const form = document.getElementById("f");
const taskInput = document.getElementById("task");
const sendBtn = document.getElementById("send");
let es = null;

function add(cls, html) {
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.innerHTML = html;
  log.appendChild(d);
  window.scrollTo(0, document.body.scrollHeight);
}
function esc(s) { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;"); }

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const task = taskInput.value.trim() || "demo";
  sendBtn.disabled = true;
  add("step", "— starting task: " + esc(task) + " (mock=true) —");
  try {
    const r = await fetch("/chat?task=" + encodeURIComponent(task) + "&mock=true", {method: "POST"});
    const data = await r.json();
    openStream(data.run_id);
  } catch (err) {
    add("term", "✗ failed to start: " + esc(err));
    sendBtn.disabled = false;
  }
});

function openStream(runId) {
  es = new EventSource("/chat/" + runId + "/stream");
  es.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    handle(ev);
  };
  es.onerror = () => { if (es) { es.close(); sendBtn.disabled = false; } };
}

function handle(ev) {
  switch (ev.type) {
    case "step": add("step", "Step " + ev.iter); break;
    case "action": add("agent", "🤖 <b>" + esc(ev.tool) + "</b><pre>" + esc(JSON.stringify(ev.args)) + "</pre>"); break;
    case "governance":
      if (ev.blocked) add("gov-block", "⛔ blocked — " + esc(ev.reason) + " [" + esc(ev.layer) + "]");
      else add("gov-ok", "✅ governance ok" + (ev.layer ? " [" + esc(ev.layer) + "]" : ""));
      break;
    case "tool_result":
      add("tool", "📤 " + esc(ev.tool) + (ev.ok ? " ok" : " error") +
        "<pre>" + esc(JSON.stringify(ev.output || {}) + (ev.error ? "\n" + ev.error : "")) + "</pre>");
      break;
    case "hitl_pending":
      add("hitl", "⚠️ needs approval — <b>" + esc(ev.tool) + "</b><pre>" + esc(JSON.stringify(ev.args)) + "</pre>" +
        '<div class="btns"><button class="approve" onclick="approve(\'' + ev.approval_id + '\', this)">approve</button>' +
        '<button class="reject" onclick="reject(\'' + ev.approval_id + '\', this)">reject</button></div>');
      break;
    case "hitl_resolved": add("hitl", ev.status === "approved" ? "✅ approved" : "❌ rejected"); break;
    case "success": add("term", "✅ done — success, " + ev.iterations + " iters"); finish(); break;
    case "error": add("term", "✗ error after " + ev.iterations + " iters"); finish(); break;
    case "max_iters": add("term", "⏱ max iters (" + ev.iterations + ")"); finish(); break;
  }
}
function finish() { if (es) { es.close(); es = null; } sendBtn.disabled = false; }

async function approve(id, btn) { btn.disabled = true; await fetch("/approvals/" + id + "/approve", {method: "POST"}); }
async function reject(id, btn) {
  btn.disabled = true;
  await fetch("/approvals/" + id + "/reject", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({reason: "rejected via UI"})});
}
window.approve = approve; window.reject = reject;
</script>
</body>
</html>
```

3b. In `harness/web/app.py`, delete the `@app.get("/")` route (the `root()` function, lines defining the HITL HTML table) — keep `/approvals`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject`, and the GET convenience links. The resulting `make_app` ends after the reject convenience-link route.

3c. In `harness/server.py` `build_app`, add the root route inside `build_app` (after `app = make_app(srv.hitl)`):

```python
    from fastapi.responses import FileResponse

    @app.get("/")
    def root():
        return FileResponse(Path(__file__).parent / "web" / "static" / "index.html")
```

(`FileResponse` import can also be hoisted to the top-of-file imports; either is fine — keep it consistent with the Task 3 imports which already added `StreamingResponse` at top. If hoisting, add `FileResponse` to that top import line and drop the local import here.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_streaming.py::test_root_serves_chat_ui -v && pytest -q`
Expected: new test PASS; full suite green (`make_app` root removal is untested by `test_web.py`/`test_server.py` — verified those assert only `/approvals` + approve/reject + `/health` + `/run`).

- [ ] **Step 5: Commit**

```bash
git add harness/web/static/index.html harness/web/app.py harness/server.py tests/integration/test_streaming.py
git commit -m "feat(web): chat-driven UI at root / (vanilla JS, SSE, inline HITL)"
```

---

### Task 5: Docs (README + AGENT_LOG)

**Files:**
- Modify: `README.md` (§3 Running + §7 Known Limitations)
- Modify: `AGENT_LOG.md` (append stage 6)

**Interfaces:** n/a (prose). No code, no test.

- [ ] **Step 1: Update README §3**

Replace the `### Start the WebUI (HITL approval interface)` subsection (the `harness serve` block + its paragraph) with:

```markdown
### Start the WebUI (chat-driven agent + HITL approval)

```bash
harness serve
```

Opens FastAPI server on **http://localhost:8000**. The root path `/` is a **chat UI**: type a task, watch the agent's each step (LLM action → governance verdict → tool output → HITL pause → resolve) stream as chat bubbles in real time over SSE. The public demo runs mock-only (deterministic, no API key, no credit burn); inline Approve/Reject buttons call the existing HITL endpoints. `POST /run?mock=true` (fire-and-forget) and `GET /approvals` (JSON) remain available; `GET /health` for health checks.
```

- [ ] **Step 2: Update README §7 Known Limitations**

Append this bullet to the `## 7. Known Limitations` list:

```markdown
- **Chat WebUI**: Single-user, no auth (inherits the HITL limitation). Public deploy is mock-only (no real-LLM toggle exposed); real agent tasks use `harness run`. If a client disconnects mid-stream, the run's event queue is leaked until process restart (accepted for single-user demo scale). No chat history persistence.
```

- [ ] **Step 3: Append AGENT_LOG stage 6**

Append to `AGENT_LOG.md` (after the 阶段 5 entry):

```markdown
## 阶段 6：聊天驱动前端（2026-07-25）

- **brainstorming → spec → plan**：`superpowers:brainstorming`（单次任务+步骤流；公网只 mock；SSE+on_event；vanilla JS）→ spec `docs/superpowers/specs/2026-07-25-chat-frontend-design.md`（commit `0f5ac46`）→ 本 plan。
- **实现**（5 个 TDD task，feat/chat-frontend 分支）：①`AgentLoop.on_event` 回调（5 个 emit 点，默认 None 不改既有行为）②`wrap_approver`（包裹 `blocking_approver`，emit hitl_pending/resolved，不动治理内核）③`POST /chat`+`GET /chat/{id}/stream`（`_runs` queue + SSE 同步生成器）④`index.html` 聊天 UI（vanilla，根 `/`，内联 approve/reject 复用现有端点）⑤README+AGENT_LOG。
- **测试**：新增 `test_loop_events`(2) + `test_wrap_approver`(2) + `test_streaming`(5，approve/reject/404/health/root) = 9 新测试；全确定性 mock-LLM 无网络。既有 63 测试保持绿（`on_event=None` 默认）。
- **commit 清单**：`git log --oneline feat/chat-frontend` 输出即为本阶段逐 task 提交（实现在执行时填入）。
- **公网**：聊天 UI 只发 `mock=true`，不耗 DeepSeek 额度；真实 LLM 路径在端点存在但前端不暴露。
```

(Replace the last `commit 清单` parenthetical with the actual `git log --oneline feat/chat-frontend` output after committing Tasks 1–5.)

- [ ] **Step 4: Run full suite + verify no code regressions**

Run: `pytest -q`
Expected: all green (67 tests: 63 existing + 9 new − 5 streaming overlap = ... see actual count; the point is no failures).

- [ ] **Step 5: Commit**

```bash
git add README.md AGENT_LOG.md
git commit -m "docs: chat-driven frontend — README running/limitations + AGENT_LOG stage 6"
```

---

## Self-Review (completed by plan author)

**1. Spec coverage:** §4.1 loop on_event → T1; §4.2 wrap_approver → T2; §4.3 `_runs`+`POST /chat`+`GET /chat/{id}/stream` → T3; §4.4 make_app root removal → T4; §4.5 frontend → T4; §5 event protocol → T1+T2 (emission) + T3 (tests assert); §6 data flow → T3 tests; §7 error handling → T3 (404 test, HITL timeout reuses existing approver, error event emitted by T1 impl); §8 testing → T1/T2/T3/T4; §9 files → all; §10 YAGNI → T5 README; §11 acceptance 1–8 → covered. No gaps.

**2. Placeholder scan:** No TBD/TODO/"add appropriate"/"similar to Task N". All steps contain executable code or exact prose. The only forward-reference is T5 Step 3's note to paste actual `git log` output (a real command, not a placeholder).

**3. Type consistency:** `on_event: Callable[[dict],None]` — same param name in T1 (`AgentLoop.__init__`) + T2 (`wrap_approver`) + T3 (`run_task`, `q.put`). Event field names: `approval_id`/`tool`/`args` (hitl_pending), `approval_id`/`status` (hitl_resolved), `blocked`/`reason`/`layer`/`approval_id` (governance), `tool`/`ok`/`output`/`error` (tool_result), `iter` (step), `final_status`/`iterations` (terminal) — identical across loop emits, test assertions, and frontend reads. `run_id` format `run_{n}` matches T3 impl + T3 test. `make_app` root removal verified untested (test_web.py/test_server.py assert only `/approvals`+approve/reject+`/health`+`/run`). Consistent.
