# Architecture

GAIA Beta v0.1 — Milestone 1.

## Stack

| Layer | Choice |
|---|---|
| Desktop shell | Tauri 2 (Rust) |
| Frontend | React 18 + TypeScript + Vite, Zustand for state |
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Database | SQLite via SQLAlchemy 2, migrated with Alembic |
| Secrets | OS keyring, with an owner-only file fallback |

This matches the stack in the brief. Two choices are worth recording.

**Why Tauri rather than Electron.** The bundle is ~10 MB rather than ~150 MB, and the app
already needs a Python backend process — adding a second full runtime (Node) buys nothing. The
cost is that the webview is the platform's own, so rendering differs slightly across
platforms; for a text-and-Markdown interface that is an acceptable trade.

**Why the backend is a child process rather than a bundled sidecar binary.** Freezing Python
with PyInstaller and shipping it per-platform is a large ongoing cost, and it makes the sandboxed
Python execution planned for Milestone 2 awkward — that feature wants a real interpreter with
real packages. Instead the installer creates a virtualenv next to the app, and the Rust shell
launches `python -m gaia` from it. The trade is that Python must exist on the machine, which the
installer checks for and explains.

## Process model

```
┌──────────────────────────────────────────────────────┐
│ GAIA (Tauri, Rust)                                   │
│                                                      │
│  1. spawn  python -m gaia --print-port --parent-pid  │
│  2. read   {"event":"listening","port":N} on stdout  │
│  3. create window, inject window.__GAIA_API_BASE__   │
│  4. on exit, kill the child                          │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ WebView — React bundle                         │  │
│  │        │  fetch + SSE over 127.0.0.1:N         │  │
│  └────────┼───────────────────────────────────────┘  │
└───────────┼──────────────────────────────────────────┘
            ▼
   ┌──────────────────────────────┐
   │ FastAPI (child process)      │
   │  loopback only, no auth      │──▶ SQLite (data dir)
   │  parent-PID watchdog         │──▶ Provider (cloud or local)
   └──────────────────────────────┘
```

Two independent guarantees keep the backend from outliving the UI: the shell kills the child on
exit, and the child polls its parent PID every two seconds and exits if it disappears. The
second covers `SIGKILL` on the shell, where the first cannot run.

The backend binds `127.0.0.1` and has **no authentication**. That is a deliberate single-user
desktop assumption, and the reason it must never be exposed on a routable interface.

## Layering

```
gaia/
├── config.py          settings + on-disk layout; the only place paths are defined
├── db/                Base, models, session, migrations
├── llm/               provider abstraction (base, registry, catalog, 4 providers)
├── core/              persona, context_builder, secrets, capabilities, logging_setup
├── services/          conversation, settings, chat (orchestration)
├── api/               FastAPI routers — HTTP shape only, no business logic
└── schemas/           Pydantic request/response models
```

Dependencies point one way: `api → services → core/llm → db`. A router never touches a provider
directly, and no layer below `api` knows about HTTP.

## The chat turn

`POST /api/chat` returns Server-Sent Events. `EventSource` cannot POST, so the client parses SSE
framing off the `fetch` response body.

```
persist user message
      ↓
resolve provider + model  ──▶ ProviderError → error event, stop
      ↓
build context (budgeted against the model's context window)
      ↓
create assistant row, status="streaming"
      ↓
stream provider events → SSE deltas, accumulating text
      ↓
success → status="complete", record tokens/cost/latency
failure → status="error" (nothing streamed) or "stopped" (partial text kept)
```

The assistant row exists **before** the first token. An interrupted turn therefore leaves a
visible partial message with an honest status, rather than vanishing or appearing complete.

Event names: `user_message`, `start`, `delta`, `error`, `done`. Errors arrive as an `error`
event rather than an HTTP status, because by then the response has already begun.

## Provider abstraction

`LLMProvider` is the only interface above the vendor layer:

```python
class LLMProvider(ABC):
    id: str; display_name: str; is_local: bool; requires_api_key: bool
    async def list_models(self) -> list[ModelInfo]
    async def health(self) -> ProviderHealth          # must never raise
    def stream_chat(...) -> AsyncIterator[StreamEvent]
```

Implementations: `anthropic` (official SDK), `openai_compatible` (httpx — covers OpenAI, LM
Studio, vLLM, OpenRouter), `ollama` (httpx, NDJSON), and `mock` (offline, test-only, hidden
unless `GAIA_ENABLE_MOCK_PROVIDER=1`).

Providers translate transport and vendor failures into `ProviderError` subclasses carrying a
plain-language `message` and an actionable `remedy`. Nothing above this layer sees an httpx or
SDK exception, which is what lets the UI show a real explanation instead of a stack trace.

**Model capability flags are load-bearing, not decoration.** `llm/catalog.py` records which
models reject sampling parameters: the Claude 5-series and Opus 4.7/4.8 return HTTP 400 if
`temperature` is sent, and `output_config.effort` errors on Haiku 4.5. An unrecognised model id
defaults to the newer-model behaviour, because omitting a parameter always works while sending a
rejected one is a hard failure.

## Context builder

`core/context_builder.py` decides what is actually sent. It assembles the persona, the user's
custom instructions, any conversation-specific prompt and rolling summary, then walks history
**backwards** so the newest turns always survive, filling half the context window. Messages that
are still streaming or that failed are excluded — replaying a half-written assistant turn
corrupts the thread — and a leading assistant message is dropped, since providers require the
first turn to be from the user.

Token counts are a `len(text) / 3.5` heuristic for budgeting only; providers do the real
counting and report it back in `usage`.

## Database

The full schema from the brief exists up front so migrations stay linear as milestones land.
**Only a subset is wired to anything.**

| Live in v0.1 | Schema only (no API surface) |
|---|---|
| `conversations`, `messages` | `projects`, `project_tasks`, `memories` |
| `settings`, `task_runs` | `documents`, `document_chunks` |
| `tool_calls` (audit, written from M2) | `experiments`, `simulation_runs` |
| | `study_plans`, `learning_progress` |
| | `permissions`, `workspace_roots` |

`messages.sequence` is a monotonic per-conversation integer with a uniqueness constraint —
timestamps collide under streaming, so ordering cannot depend on them. Alembic runs
`upgrade head` at startup, so a user never runs a migration by hand.

## The honesty constraint

The brief's §3 and §53 are enforced structurally rather than by remembering:

- `core/capabilities.py` is the single source of truth for what exists. The sidebar, system
  status panel and privacy dashboard all read from it, so an unbuilt feature cannot look built
  in one place and unbuilt in another.
- Navigation entries for unbuilt features are reachable and land on a screen that says exactly
  what is missing and when it is planned — no mock data, no decorative disabled controls.
- The system prompt lists what GAIA cannot do and instructs it to say so rather than simulate a
  result.
- Shipping a feature means flipping its capability flag **last**, after it works.

## Known limits in v0.1

- **No conversation summarisation.** The `summary` column and the context builder support it,
  but nothing writes one, so a very long conversation drops its oldest turns instead of
  compacting them. Milestone 3.
- **`sqlite+pysqlite` with sync sessions inside async endpoints.** Local SQLite writes are
  sub-millisecond, so they run inline. This becomes a real blocking concern only if storage
  moves off local SQLite, at which point the async engine (`aiosqlite`, already in the URL
  helper) is the path.
- **Cost estimates are catalogue-based**, so they are wrong for a model GAIA does not know. The
  UI renders unknown costs as `—` rather than guessing.
- **No request cancellation on the server.** Pressing Stop aborts the client stream; the
  provider request finishes in the background. The partial text is persisted honestly as
  `stopped`.
