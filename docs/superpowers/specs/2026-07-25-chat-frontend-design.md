# Chat-Driven Frontend — Design Spec

> Date: 2026-07-25
> Status: Approved (brainstorming 2026-07-25) → pending plan
> Extends: `docs/superpowers/specs/SPEC.md` (Coding Agent Harness)
> Scope: Add a chat-driven Web UI that streams the agent's step-by-step execution. **Does not change** the harness kernel contract, governance model, or existing 63 tests.

---

## 1. Goal & Background

The deployed harness currently exposes only a bare HITL approval table at `/` (HTML). Stakeholders cannot *see* the agent work — they only see pending approvals. This spec adds a **chat-driven frontend**: type a task, watch the agent's each step (LLM-chosen action → governance verdict → tool output → HITL pause → resolve) stream as chat bubbles in real time.

Core thesis unchanged: `Agent = LLM + Harness`. The LLM still only picks the next step; the harness (loop, governance, tools, feedback) is hand-implemented. The frontend is a **new presentation surface** over the existing kernel — no agent frameworks introduced.

## 2. Decisions (locked in brainstorming)

1. **Interaction model: single-shot task + step stream.** One task → agent runs to completion → each kernel step streamed as a chat bubble. No mid-run user injection (only HITL approve/reject, which the kernel already supports). True multi-turn mid-run is explicitly out of scope (would require redesigning `AgentLoop` to pause for input).
2. **Public deploy = mock-only.** The public chat frontend sends `mock=true` only — deterministic, no DeepSeek credit burn, no abuse. The streaming endpoint accepts a `mock` param and the real-LLM path exists for local/CLI, but the frontend does not expose a real toggle.
3. **Streaming transport: SSE** (Server-Sent Events) via `on_event` callback on `AgentLoop`. Not WebSocket (overkill for unidirectional server→client; approve/reject reuse existing POST endpoints). Not polling (laggy).
4. **Frontend tech: vanilla JS**, single self-contained `index.html` (embedded CSS+JS). No build step, no framework, ships inside the existing Docker `COPY harness`. Aligns with the self-implementation ethos (SPEC §13).
5. **Root `/` becomes the chat UI.** `make_app`'s untested GET `/` HITL table is removed; `/approvals` (JSON) + approve/reject endpoints remain (tested, deliverable).

## 3. Architecture

```
Browser (index.html, vanilla JS)
  │
  │ 1. POST /chat?task=...&mock=true        2. EventSource GET /chat/{run_id}/stream
  ▼                                        ▼
build_app (FastAPI)
  │ POST /chat   → spawn worker thread, return {run_id}
  │ GET  /chat/{run_id}/stream → SSE generator drains run queue
  │
  ▼
HarnessServer._runs: {run_id → queue.Queue}
  │
  ▼  worker thread
HarnessServer.run_task(task, mock, on_event)   ← existing method + on_event param
  │  wraps blocking_approver to emit hitl_pending / hitl_resolved
  ▼
AgentLoop.run(task)  ← existing, + on_event callback emitting step/action/governance/tool_result/done
  │
  ▼  (unchanged kernel)
governance.check → tools.dispatch → feedback_injector → stop
```

**Key invariants preserved:**
- `AgentLoop` with `on_event=None` behaves identically to today (existing 63 tests stay green).
- The blocking HITL wait still happens inside `governance.check` via the `approver` callback — unchanged. The `on_event` emission brackets it (before/after) via an approver wrapper; it does not alter the wait semantics.
- `blocking_approver`, `HITLStateMachine`, governance pipeline, tool dispatch, feedback injection — **zero changes**.

## 4. Components

### 4.1 `AgentLoop` (`harness/loop.py`) — minimal addition

- `__init__` gains `on_event: Callable[[dict], None] | None = None` (stored as `self.on_event`).
- A private helper `def _emit(self, event): if self.on_event is not None: self.on_event(event)`.
- Emission points (all conditional on `on_event` being set, so the no-callback path is untouched):
  - Top of each iteration: `_emit({"type":"step","iter":i})`.
  - After `next_action(resp)` returns non-None: `_emit({"type":"action","tool":action.tool,"args":action.args})`.
  - After `governance.check(...)` returns `decision`: `_emit({"type":"governance","blocked":decision.blocked,"reason":decision.reason,"layer":decision.layer,"approval_id":decision.approval_id})`.
  - After `tools.dispatch(action)` (non-blocked path): `_emit({"type":"tool_result","tool":action.tool,"ok":result.ok,"output":result.output,"error":result.error})`.
  - Terminal: `_emit({"type":"success"|"error"|"max_iters","final_status":...,"iterations":i})` immediately before each `return AgentRunResult(...)`.
- `hitl_pending` / `hitl_resolved` are NOT emitted from the loop body — they are emitted by the **approver wrapper** (§4.2), which is the only site that has the `ApprovalRecord` (and thus `approval_id`) and brackets the blocking wait.

### 4.2 Approver wrapper (`harness/server.py`)

`HarnessServer.run_task` already builds `approver = blocking_approver(self.hitl, timeout)`. When `on_event is not None`, wrap it:

```python
def _wrap_approver(self, real_approver, on_event):
    def _wrapped(rec):
        on_event({"type":"hitl_pending","approval_id":rec.id,
                  "tool":rec.action.tool,"args":rec.action.args})
        approved = real_approver(rec)          # blocks until web decides / timeout
        on_event({"type":"hitl_resolved","approval_id":rec.id,
                  "status":"approved" if approved else "rejected"})
        return approved
    return _wrapped
```

This is the sole emission site for HITL events. It reuses `blocking_approver` unchanged (the wrapper delegates; the real approver still owns the poll loop + timeout). For the CLI path (`on_event=None`, no approver wrap), behavior is unchanged.

### 4.3 `HarnessServer` (`harness/server.py`) — run registry + streaming

- `__init__` adds `self._runs: dict[str, "queue.Queue"] = {}` and `self._run_counter = 0`.
- `run_task(self, task, mock=False, on_event=None)`: add `on_event` param; thread it into `AgentLoop(..., on_event=on_event)` and wrap the approver per §4.2 when `on_event` is set. Existing `POST /run` path calls `run_task(task, mock=mock)` (no `on_event`) — unchanged.
- `build_app` adds three routes:
  - `POST /chat?task=...&mock=true` → allocate `run_id = f"run_{n}"`, create `queue.Queue()`, store in `srv._runs`, spawn daemon worker: `srv.run_task(task, mock=mock, on_event=lambda ev: q.put(ev))` in a `try/finally` that pushes sentinel `None`. Return `{"run_id": run_id}`. Endpoint signature: `def chat(task: str, mock: bool = True)` — `mock` defaults `True` so the public frontend (which omits the flag) is always mock; the real path is reachable only by an explicit `mock=false` call (local/CLI).
  - `GET /chat/{run_id}/stream` → 404 if unknown; else `StreamingResponse(sync_gen, media_type="text/event-stream")` where `sync_gen` drains `q.get(timeout=1)`, yields `f"data: {json.dumps(ev)}\n\n"` per event, stops on sentinel `None`, then pops `srv._runs[run_id]`. (Sync generator runs in Starlette's threadpool — `TestClient`-consumable, no `asyncio`/`janus` dependency.)
  - `GET /` → `FileResponse("harness/web/static/index.html")` (the chat UI).

### 4.4 `make_app` (`harness/web/app.py`) — drop root table

- Remove the GET `/` HITL HTML table (untested — verified `test_web.py`/`test_server.py` assert only `/approvals` + approve/reject + `/health` + `/run`).
- Keep `/approvals` (JSON), `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject`, and the GET convenience links — these are the HITL deliverable and are tested.

### 4.5 Frontend (`harness/web/static/index.html`) — single file, vanilla

Self-contained HTML with embedded CSS + `<script>`. Behavior:
- Chat input + Send button. On send: `fetch("/chat?task=...&mock=true", {method:"POST"})` → `{run_id}`; open `new EventSource("/chat/"+run_id+"/stream")`; disable input until terminal event.
- `onmessage`: `JSON.parse(e.data)` → render a bubble by `type`:
  - `step` → small divider "Step {iter}".
  - `action` → agent bubble: "🔧 {tool}: {args}".
  - `governance` → governance bubble: blocked → "⛔ {reason}" (red); ok → "✅ ok" (green).
  - `tool_result` → "📤 {tool}: {output|error}".
  - `hitl_pending` → bubble with **Approve / Reject** buttons; on click, `fetch("/approvals/{id}/approve|reject", {method:"POST"})`; disable buttons after click.
  - `hitl_resolved` → "✅ approved" / "❌ rejected".
  - `success`/`error`/`max_iters` → terminal bubble "✅ done (success, {iters} iters)" etc.; `EventSource.close()`.
- Autoscroll to latest. Minimal clean styling. No external requests (no CDN) — fully self-contained, works behind China network blocks.

## 5. Event Protocol (SSE wire format)

Each SSE message: `data: <json>\n\n`. JSON events (all field names stable — they are the contract):

| type | fields | emitted by | when |
|---|---|---|---|
| `step` | `iter:int` | loop | top of each iteration |
| `action` | `tool:str, args:dict` | loop | LLM returned a non-None action |
| `governance` | `blocked:bool, reason:str, layer:str\|null, approval_id:str\|null` | loop | after `governance.check` (post-resolution) |
| `tool_result` | `tool:str, ok:bool, output:dict, error:str\|null` | loop | after `tools.dispatch` (non-blocked only) |
| `hitl_pending` | `approval_id:str, tool:str, args:dict` | approver wrapper | before blocking wait |
| `hitl_resolved` | `approval_id:str, status:"approved"\|"rejected"` | approver wrapper | after blocking wait returns |
| `success` | `final_status:"success", iterations:int` | loop | `next_action` is None |
| `error` | `final_status:"error", iterations:int` | loop | `StopIteration` / `resp is None` |
| `max_iters` | `final_status:"max_iters", iterations:int` | loop | loop exhausted budget |

`layer` values: `"scope_fence"` | `"guardrail"` (deny) | `"hitl"` (dangerous) | `null` (ok).

## 6. Data Flow (mock demo trace)

Public chat sends `mock=true` → `_mock_demo_script()` (existing): `[git push --force, git status, done]`. Event stream on **approve**:

```
step{1} → action{run_shell, git push --force}
  → hitl_pending{apv_1, run_shell, git push --force}   [user clicks Approve]
  → hitl_resolved{apv_1, approved}
  → governance{blocked:false, reason:approved, layer:hitl, approval_id:apv_1}
  → tool_result{run_shell, ok:false, error:...}          [push fails: not a git repo — harmless]
step{2} → action{run_shell, git status}
  → governance{blocked:false, layer:null}
  → tool_result{run_shell, ok:true, output:...}
step{3} → success{final_status:success, iterations:3}
```

On **reject**: `hitl_resolved{apv_1,rejected}` → `governance{blocked:true,layer:hitl}` → loop continues to `git status` → ... → `success`. Either path demonstrates the HITL mechanism end-to-end in the chat.

## 7. Error Handling

- **Loop error / StopIteration** → emit `error` → worker `finally` pushes sentinel → SSE closes cleanly.
- **HITL 300s timeout** → `blocking_approver` auto-rejects → `hitl_resolved{rejected}` → loop proceeds per governance decision (blocked → continue). No special-casing.
- **Unknown `run_id` on `/chat/{id}/stream`** → HTTP 404.
- **Client disconnect mid-stream** → generator stops being pulled; worker still finishes + pushes sentinel; the `run_id` entry is not popped (leaked until process restart). **Accepted known limitation** for a single-user demo; a TTL reaper is YAGNI. Documented in README limitations.
- **Concurrent runs** → each gets a unique `run_id` + its own `queue` (thread-safe `queue.Queue`); no cross-talk.
- **`mock=false` (real LLM) without a configured key** → `CredentialStore.interactive_first_run()` raises in the worker → `error` event → SSE closes. (Frontend never sends `mock=false` publicly.)

## 8. Testing (mock-LLM, deterministic, no network)

New `tests/integration/test_streaming.py` using `fastapi.testclient.TestClient` + `build_app`:

- `test_chat_stream_demo_approve`: `POST /chat?task=demo&mock=true` → `{run_id}` → `GET /chat/{run_id}/stream` → collect events until terminal. Assert sequence contains: `action{git push --force}` → `hitl_pending{apv_1}` → (POST `/approvals/apv_1/approve`) → `hitl_resolved{approved}` → `governance{blocked:false,layer:hitl}` → `tool_result{run_shell}` → `success`.
- `test_chat_stream_demo_reject`: same but POST `/approvals/apv_1/reject` → assert `hitl_resolved{rejected}` → `governance{blocked:true}` → loop continues to `git status` → `success`.
- `test_chat_unknown_run_404`: `GET /chat/run_bogus/stream` → 404.
- `test_chat_health_still_ok`: regression — `/health` still `{"status":"ok"}` after adding routes.

**Streaming-test mechanic:** consume the SSE via `with client.stream("GET", url) as r: for line in r.iter_lines(): ...` so the test can POST `/approvals/{id}/approve` *after* reading `hitl_pending` while the stream stays open — the worker thread blocks inside `blocking_approver` polling the shared `HITLStateMachine` until that POST resolves it. (Starlette `TestClient` runs the app on an anyio portal, so the concurrent GET-stream + POST works.)

All deterministic (MockLLMClient), no network, no DeepSeek key. Existing 63 tests stay green (`on_event=None` default → no behavior change; `make_app` root removal untested).

## 9. Files

| path | change |
|---|---|
| `harness/loop.py` | + `on_event` param + `_emit` helper + 5 emission points |
| `harness/server.py` | `run_task(on_event=)` + `_wrap_approver` + `_runs` registry + `POST /chat` + `GET /chat/{id}/stream` + `GET /` FileResponse |
| `harness/web/app.py` | remove GET `/` table; keep `/approvals` + approve/reject |
| `harness/web/static/index.html` | **new** — chat UI (HTML+CSS+JS, self-contained) |
| `tests/integration/test_streaming.py` | **new** — 4 tests |
| `README.md` | update §3 Running (chat UI) + §7 Known Limitations (disconnect leak, mock-only public, single-user) |
| `AGENT_LOG.md` | record the new feature stage |
| `Dockerfile` | **no change** — `COPY harness` already includes `static/` |

## 10. Scope / YAGNI / Known Limitations

- **No auth** — single-user, no session (inherits existing HITL WebUI limitation).
- **No real-LLM toggle on public frontend** — mock-only; real path exists in endpoint for local/CLI.
- **No chat history persistence** — each run is ephemeral (queue + run_id, GC'd on completion).
- **No mid-run multi-turn** — single-shot task; the kernel's loop model is task→completion.
- **Client-disconnect queue leak** — §7; accepted for demo scale.
- **Static assets served from process CWD-relative path** — `FileResponse("harness/web/static/index.html")` resolves under the Docker `WORKDIR /app` and local repo root; verified in plan.

## 11. Acceptance Criteria

1. `GET /` returns the chat UI (HTML 200), not the old HITL table.
2. `POST /chat?task=demo&mock=true` returns `{"run_id":"run_1"}` and starts a worker.
3. `GET /chat/{run_id}/stream` yields SSE events matching §6's sequence for the mock demo.
4. Inline Approve/Reject in the chat call the existing `/approvals/{id}/approve|reject` endpoints and unblock the loop.
5. New `test_streaming.py` passes (4 tests); existing 63 tests stay green; total 67.
6. `on_event=None` path (CLI `harness run --mock`, `POST /run`) behaves identically to before.
7. Docker image serves the chat UI at `/` with no Dockerfile change.
8. No DeepSeek key required for the public chat (mock-only); no key in any frontend request/response.
