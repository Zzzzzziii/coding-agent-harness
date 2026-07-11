# Coding Agent Harness

A self-implemented **Coding Agent Harness** — the agent (LLM) only decides the next step; everything else (main loop, tool dispatch, governance guardrail, feedback, context, configuration) is hand-written.

**Deep-dive dimension: Governance** — scope fence, guardrail, and human-in-the-loop (HITL) state machine.

Built from scratch: no LangChain, AutoGen, CrewAI, or any third-party agent executor (SPEC Section 13).

---

## 1. Project Overview

```
Agent = LLM + Harness
```

| Component | What it does |
|-----------|-------------|
| **LLM** (DeepSeek Chat) | Picks the next action (tool call or stop) |
| **Harness** (this repo) | Everything else: main loop, tool dispatch, governance filtering, test-feedback injection, context management, CLI, and WebUI |

The harness enforces a three-layer governance pipeline:

1. **Scope Fence** — restricts file-system access to an allowed workspace.
2. **Guardrail** — blocks destructive commands (e.g. `rm -rf /`, fork bomb, `mkfs`); suspicious actions (e.g. `git push --force`, `DROP TABLE`) are diverted to HITL.
3. **HITL State Machine** — pauses on risky actions, presents them to a human via WebUI, and enforces a timeout.

---

## 2. Installation

**Prerequisites:** Python >= 3.11, pip.

```bash
# Clone the repository, then:
pip install -e ".[test]"
```

Installs runtime dependencies (`openai`, `fastapi`, `uvicorn`, `pyyaml`, `python-dotenv`) and test dependencies (`pytest`, `httpx`).

---

## 3. Running

### Run all tests (63 tests, mock-LLM deterministic)

```bash
make test
# or equivalently:
pytest -q
```

### Run a task from the CLI

```bash
# With a real DeepSeek API key (prompts on first run if not configured):
harness run "Write a Python script that prints Fibonacci numbers"

# In mock mode (no API key needed, deterministic demo):
harness run --mock "Write a Python script that prints Fibonacci numbers"
```

### Start the WebUI (HITL approval interface)

```bash
harness serve
```

Opens FastAPI server on **http://localhost:8000**. Visit the root path to see pending HITL approval requests (approve/reject). A `POST /run?mock=true` endpoint replays a fixed deterministic demo; set `mock=false` (or omit) for real tasks with a configured API key.

### Manage credentials

```bash
harness creds status    # Shows "configured: true" or "false" — never echoes the key
harness creds set       # Prompts with hidden input (getpass), writes to .env
harness creds clear     # Removes key from .env
```

**Note:** `creds set` uses `getpass` — the key is never echoed to screen or shell history.

---

## 4. Distribution

### Docker

```bash
docker build -t coding-harness .
docker run -e DEEPSEEK_API_KEY=sk-... -p 8000:8000 coding-harness
```

The Docker image:
- Uses `python:3.11-slim` (~130 MB).
- Does **not** include `.env` (excluded by `.dockerignore`).
- Runs as non-root user `65532`.
- Exposes port 8000; CMD starts `harness serve`.

### Render (one-click deploy)

1. Push the repo to GitHub/GitLab.
2. In the Render dashboard, create a **New Web Service** → select your repo.
3. Render auto-detects `render.yaml`. Set `DEEPSEEK_API_KEY` as a **secret environment variable** (Render dashboard → Environment → Secret File).
4. **After deployment**, replace the placeholder `<TODO: your render web URL>` in `render.yaml` with your actual Render URL (e.g. `https://coding-agent-harness.onrender.com`).
5. Health check endpoint: `/health`.

---

## 5. Directory Structure

```
README.md                  ← This file
config.yaml                # Harness configuration (LLM, governance, tests)
.env.example               # Credential template (copy to .env)
Makefile                   # test/lint/serve/docker targets
Dockerfile                 # Container image
render.yaml                # Render one-click deploy descriptor
.gitlab-ci.yml             # GitLab CI pipeline
pyproject.toml             # Package metadata (entry point: harness)
prompts/
└── system.md              # System prompt

harness/
├── __main__.py            # CLI entry: run/serve/creds
├── config.py              # Config loader (yaml)
├── creds.py               # Credential store (.env / env-var / getpass)
├── models.py              # Data models
├── loop.py                # AgentLoop main loop
├── server.py              # Serve harness (FastAPI + uvicorn integration)
├── llm/                   # LLM abstraction
│   ├── base.py            # LLMClient protocol, LLMResponse, ToolCall
│   ├── mock.py            # MockLLMClient (deterministic, no API key)
│   └── deepseek.py        # DeepSeek Chat adapter
├── governance/            # ★ Governance deep-dive
│   ├── scope_fence.py     # Filesystem path containment
│   ├── guardrail.py       # Dangerous/deny-pattern detection
│   ├── hitl.py            # Human-in-the-loop state machine
│   └── pipeline.py        # Governance pipeline orchestrator
├── tools/                 # Tool system
│   ├── base.py            # ToolRegistry
│   └── builtin.py         # Built-in tools (read/write/shell/tests)
├── feedback/              # Test feedback loop
│   ├── test_runner.py     # Run tests, parse results
│   └── injector.py        # Inject test feedback into agent context
├── memory/                # Context management
│   └── context_store.py   # Shared context store
└── web/                   # Web UI
    └── app.py             # FastAPI HITL approval app (make_app)

tests/
├── unit/                  # 20+ unit test files
├── integration/           # Integration tests (mock LLM)
└── demo/                  # Mechanism demonstration (A.6)
```

---

## 6. Security Boundaries (Credential Threat Model)

The API key (`DEEPSEEK_API_KEY`) is the only sensitive credential. The harness follows these rules:

| Threat | Mitigation |
|--------|-----------|
| **Hard-coded key in source** | Zero key literals in code; CI scans enforce this. |
| **Key committed to git** | `.gitignore` excludes `.env` and `.env.*` (except `.env.example`, which contains only a template). |
| **Key in shell history** | `creds set` uses `getpass` (hidden input); never `export DEEPSEEK_API_KEY=...`. |
| **Key in Docker image** | `.dockerignore` excludes `.env`; the Dockerfile does not `COPY .env` or `ENV API_KEY`. Pass at runtime via `docker run -e DEEPSEEK_API_KEY=...`. |
| **Key in logs or plaintext configs** | `creds status` shows only `configured: true/false`; all log output redacts the key to `sk-***...***`. `config.yaml` holds no secrets. |
| **Key in Render config** | `render.yaml` sets `sync: false` — the key is entered as a **secret** in the dashboard, never stored in the repo. |
| **Plaintext `.env` on disk** | On POSIX, `creds set` applies `chmod 0600` to `.env`. The remaining risk (plaintext at rest) is documented; users on shared machines should consider encrypted volumes or OS keychain alternatives. |

### Quick credential setup

```bash
# Option A: interactive (hidden input, recommended)
harness creds set

# Option B: manual .env file
cp .env.example .env
# Edit .env with your key; .env is gitignored

# Option C: environment variable (Docker / CI)
export DEEPSEEK_API_KEY="sk-..."
```

---

## 7. Known Limitations

- **Platform**: Developed on Windows; deployed on Linux (Docker / Render). The `chmod 0600` hardening on `.env` is POSIX-only (no-op on Windows).
- **Docker**: Required for the container execution path. `docker build` has not been verified on a production Docker host — users must run once before deploying.
- **HITL WebUI**: Single-user; no authentication or session management. Suitable for local development and demonstration only.
- **Demo vs. real mode**: `POST /run?mock=true` replays a fixed deterministic script (propose dangerous push → HITL → retry safe → done). Real tasks require `mock=false` and a configured DeepSeek API key.
- **Test count**: 63 tests (unit + integration + demo), all using mock-LLM for deterministic, API-key-free execution.

---

## CI Pipeline

A GitLab CI job (`.gitlab-ci.yml`) runs `pip install ".[test]" && pytest -q` on every push. A GitHub Actions mirror is also available.

---

*Built for the AI4SE final project. Governance deep-dive: scope fence + guardrail + HITL. No agent frameworks used.*