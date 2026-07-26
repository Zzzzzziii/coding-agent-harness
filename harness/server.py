# harness/server.py
import threading
import time
import json
import queue as _queue
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, FileResponse
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


def blocking_approver(hitl, timeout_seconds):
    """Blocks until the WebUI decides on the shared HITL, or rejects after timeout (SPEC §10)."""
    def _approver(rec):
        deadline = time.time() + timeout_seconds
        while True:
            cur = hitl.get(rec.id)
            if cur is None or cur.status != "pending":
                return (cur is not None) and cur.status == "approved"
            if time.time() > deadline:
                hitl.reject(rec.id, "HITL timeout")
                return False
            time.sleep(0.1)
    return _approver


def _mock_demo_script():
    # Replays A.6 demo③: propose dangerous push -> (HITL) -> retry safe status -> done.
    return MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "git push --force"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c1", "run_shell", {"command": "git status"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])


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

    @app.get("/")
    def root():
        return FileResponse(Path(__file__).parent / "web" / "static" / "index.html")

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