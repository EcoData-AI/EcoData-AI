# Architecture

GAIA Beta v0.1 — Milestones 1–4.

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
┌─▶ stream provider events → SSE deltas, accumulating text
│         ↓
│   tool(s) requested? ──no──▶ done
│        │yes
│        ▼
│   gate + execute each call (see "Tool system"), append results
└── loop (bounded — MAX_TOOL_ITERATIONS)
      ↓
success → status="complete", record tokens/cost/latency
failure → status="error" (nothing streamed) or "stopped" (partial text kept)
```

The assistant row exists **before** the first token. An interrupted turn therefore leaves a
visible partial message with an honest status, rather than vanishing or appearing complete.

Event names: `user_message`, `start`, `delta`, `tool_call`, `tool_confirm_required`,
`tool_result`, `error`, `done`. Errors arrive as an `error` event rather than an HTTP status,
because by then the response has already begun.

Only the **final** assistant text is ever persisted as a `Message` row — the tool round-trip
within a turn (the model's tool-use request, the result fed back) lives in memory for the
duration of that one request and in the `ToolCall` audit table, never as its own `Message`. This
is what lets `context_builder` stay untouched: replayed history is exactly what it always was.

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

## Tool system

`gaia/tools/` mirrors `gaia/llm/` on purpose: a small ABC (`base.py`), a registry that is the
single place that knows what exists (`registry.py`), and one module per tool. Five tools ship so
far — Milestone 2's full original scope: `calculator.py` (`SAFE`), `python_sandbox.py`
(`CONFIRM`), `filesystem.py`'s `FilesystemReadTool` (`SAFE`) / `FilesystemWriteTool` (`CONFIRM`),
and `terminal.py`'s `TerminalTool` (`CONFIRM`). Read/write are two classes, not one tool with a
risk-varying argument, because `risk_level` is fixed per class and must never depend on what a
request asks for.

```python
class Tool(abc.ABC):
    name: str; description: str; parameters: dict  # JSON Schema
    risk_level: RiskLevel                            # SAFE | CONFIRM | BLOCKED
    async def execute(self, arguments: dict) -> ToolResult   # must never raise
```

**Risk level is a class attribute the tool itself declares — never something the model, the
request, or a prompt can set.** The registry is the enforcement point:

| Level | Advertised to the model? | Executes how |
|---|---|---|
| `SAFE` | yes | immediately, no pause |
| `CONFIRM` | yes | pauses the stream for the user to approve or deny |
| `BLOCKED` | **no** — filtered out of `tool_specs_for_provider()` | never |

A `BLOCKED` tool stays fully defined in code but invisible at runtime, the same way an unbuilt
capability cannot look built in one place and unbuilt in another (`core/capabilities.py`).

**The tool-call loop** lives in `chat_service.stream_turn`: the provider is called, and if it
requests a tool, GAIA executes it (or waits on a confirmation), appends the result, and calls the
provider again — up to `MAX_TOOL_ITERATIONS` (6) times per turn. A model that never stops
requesting tools does not hang the turn: it stops there, and the assistant message says so rather
than pretending to have finished normally.

**Confirmation** cannot pause and resume on the same SSE connection, so a `CONFIRM`-risk call
uses a small side channel (`services/tool_confirmation.py`): an in-memory `{call_id:
asyncio.Future}` map. The turn's generator `await`s its own future after yielding
`tool_confirm_required`; `POST /api/chat/tool-confirmations/{call_id}` resolves it. Nothing here
is persisted — a confirmation lost to a restart auto-denies after five minutes, consistent with
chat turns already having no server-side cancellation (see "Known limits" below). This path was
built speculatively alongside Calculator (which never touches it, being `SAFE`) and is now
exercised for real by `python_sandbox`, including over a live connection
(`test_chat_tools_confirm.py`), not just in isolation.

**`python_sandbox` is a different risk class from `calculator`, and its docstring says so
plainly.** It runs arbitrary code in a subprocess with a wall-clock timeout, a sanitised
environment (GAIA's own secrets are never in it), and a dedicated working directory
(`config.sandbox_dir`) — but on Windows there is no memory/CPU/process ceiling (the `resource`
module the POSIX path uses does not exist there), and the subprocess shares the backend's own
venv, so sandboxed code can `import gaia` and reach the app's database and secrets modules at the
Python level. Neither gap is silently accepted: they are why this tool is `CONFIRM`, not `SAFE` —
the human approval is real protection today even where the technical sandboxing is partial. Full
containment needs a separate restricted interpreter or OS-level isolation (a container, a VM,
Windows Sandbox), not attempted yet.

**`filesystem_read`/`filesystem_write`** use the `workspace_roots` table (schema-only until this
milestone) to decide what exists at all: with no root registered, both tools say so rather than
falling back to some default directory. Containment is `Path.resolve()` plus a `relative_to`
containment check against every enabled root — never string or prefix matching, which `..` and
symlinks defeat. A root's own `writable` flag gates the write tool independently of the tool's own
`CONFIRM` risk level: a read-only root refuses writes even with approval. Registering a root
(`POST /api/workspace/roots`, `api/workspace.py`) is a user-initiated settings change, not a
model-invoked tool call — it carries no `ToolCall` row and no risk gate, the same way setting a
provider API key doesn't. There is no Settings UI tab for it yet; roots are added through the API
directly for now. This containment logic (`resolve_within_workspace`) lives in
`services/workspace_service.py`, not in `filesystem.py`, specifically so `terminal.py` can share
it rather than reimplementing the same check.

**`terminal`** runs a shell command (`subprocess.run(..., shell=True)`) inside a `cwd` that must
resolve to an enabled, *writable* workspace root — the same mechanism as `filesystem_write`,
required even for a command that looks read-only, because a shell can always do more than it
appears to. Beyond the `CONFIRM` gate itself, a pattern-based blocklist
(`terminal._blocked_reason`) refuses a short list of unambiguously destructive commands —
recursive deletion, disk formatting, disabling Windows Defender or a Linux firewall, the classic
fork-bomb signature — **even after approval**, matching `docs/SECURITY.md`'s own risk table, which
puts those at `BLOCKED`-tier rather than merely `CONFIRM`-tier. This is pattern matching on the
command's tokens (`shlex`-split, checked for actual flag tokens rather than substring search — so
`git push --force` and `docker rm -f` are correctly left alone, since neither is `rm -r`), **not a
security boundary**: it stops the obvious literal forms a model might plainly ask for, not
deliberate evasion. The primary defence stays the confirmation itself — the user sees the exact
command before anything runs. `python_sandbox.py`'s subprocess-safety plumbing (minimal
environment, POSIX `resource.setrlimit`, output truncation) was extracted into
`tools/_process_safety.py` so this tool didn't reimplement it a third time.

**Provider translation.** `LLMProvider.stream_chat` takes an optional `tools` argument (a list of
provider-neutral `{name, description, parameters}` specs) and can emit a
`StreamEvent(type="tool_use", ...)`. Each provider translates this into its own wire format —
Anthropic's `tool_use`/`tool_result` content blocks, Ollama's whole-object `tool_calls` (one
NDJSON line), OpenAI's incrementally-streamed partial-JSON `tool_calls` (accumulated by index).
Tool execution itself never happens inside a provider file — providers only describe what was
requested; `chat_service` decides whether and how it runs.

**Audit trail.** Every call becomes one `ToolCall` row — arguments, risk level, approval
(`auto`/`approved`/`denied`), status, timing, and a truncated result summary — written regardless
of outcome. The table already existed in the initial schema (see "Database" below); this
milestone is what starts writing to it.

## Voice

`gaia/voice/` mirrors `gaia/llm/` and `gaia/tools/` on purpose — same small ABC (`base.py`), same
single-registry pattern (`registry.py`) — but it is a **peer** of those two families, not a
dependent of either. `STTProvider`/`TTSProvider` never see a conversation, never call the model,
and are never invoked as a tool call:

```python
class STTProvider(abc.ABC):
    async def health(self) -> ProviderHealth
    async def transcribe(self, audio_path: str) -> TranscriptionResult

class TTSProvider(abc.ABC):
    async def health(self) -> ProviderHealth
    async def synthesize(self, text: str, *, out_path: str) -> SynthesisResult
```

**Voice sits entirely outside the chat turn.** `chat_service.py` has no idea it exists — zero
lines changed there for this milestone. The pipeline is two ordinary HTTP calls bracketing an
otherwise-untouched turn:

```
mic capture (frontend)
      │
      ▼
POST /api/voice/transcribe  ──▶  STTProvider.transcribe()  ──▶  {text}
      │
      ▼
POST /api/chat  ── the exact same call a typed message makes — SSE, tool loop,
      │            ToolCall audit, everything, unmodified
      ▼
{final assistant text, already persisted}
      │
      ▼
POST /api/voice/speak  ──▶  TTSProvider.synthesize()  ──▶  audio/wav bytes
      │
      ▼
playback (frontend, <audio>/Web Audio)
```

A spoken request is indistinguishable from a typed one by the time it reaches `send()` in
`store/chat.ts` — `store/voice.ts` calls the same `useChatStore.getState().send(text)` a typed
message uses, so tool calls, confirmations, and the audit trail all work identically regardless
of how the text arrived. This is deliberate, not incidental: see "The chat turn" above for why
nothing upstream of `send()` should ever need to know.

**Providers, and why these two.** `faster_whisper` (STT) and `pyttsx3` (TTS) — both installed and
confirmed working on this machine before being adopted, not assumed. Full evaluation (RAM, load
time, accuracy, licensing, alternatives) lives in `docs/API.md`'s Voice section rather than
duplicated here; the short version: `faster-whisper`'s `tiny.en` model runs on CTranslate2 (no
PyTorch dependency, unlike this project's other choices), loads in ~3s once cached, and produced
usable transcriptions in testing. `pyttsx3` wraps the OS's own speech engine (SAPI5 on Windows) —
zero model download, so it can never fail a first run while fetching a multi-hundred-MB voice
model. Both are registered in `voice.stt_provider`/`voice.tts_provider` settings
(`settings_service.py`), the same swap-without-code-changes story `llm.active_provider` already
gives chat providers. Piper (local, neural, much better prosody) is the documented next
`TTSProvider` once voice quality matters more than "does the pipeline work at all."

**A real reliability finding, not a hypothetical one:** `pyttsx3.runAndWait()` was found to hang
indefinitely — not raise — when pointed at an output path whose parent directory doesn't exist,
because the "utterance finished" event it waits on never fires if the write never happened. Fixed
with two independent guards: the output directory is checked before the engine is ever touched,
and the whole call is wrapped in a wall-clock `asyncio.wait_for` as a backstop against any other
cause of the same failure mode. `faster_whisper`'s transcription carries the same kind of timeout
as a matter of consistency, though CPU-bound decode work is far less prone to hanging than a call
into an OS API.

**Audio lifecycle.** Every temporary file — an incoming recording, a synthesized reply — is
written under `config.voice_dir` and deleted in a `finally` block before its endpoint returns.
Nothing here is meant to outlive the single request that created it; see docs/PRIVACY.md, "Voice".

## Memory

Milestone 4, first slice. `gaia/services/memory_service.py` owns the CRUD against the `memories`
table (schema already existed, unused until now); the only writer is
`gaia/tools/memory.py`'s `RememberTool`.

**`remember` is `CONFIRM`-risk, not `SAFE`.** Every other decision in this milestone follows from
that one: writing a memory is a persistent, cross-conversation side effect — closer to a
filesystem write than to the calculator — so the user sees the exact `content` and `kind` before
anything is stored, the same gate `filesystem_write`/`terminal` already use. The system prompt
(`core/persona.py`) additionally instructs the model to call it only when the user explicitly
asks to remember something, never to record its own inference; the CONFIRM gate is the backstop
if that instruction is ever ignored, not the only defence. `kind` is restricted to
`"semantic"`/`"episodic"` this slice — `"project"` needs a conversation-to-project link that does
not exist until Projects ships, and `"knowledge"` belongs to Milestone 5.

**Injection into context is unconditional, not retrieval-based.** `memory_service.
relevant_memories()` returns every `enabled=True` row, ordered by `importance` then recency, and
capped at 20 — there is no embedding search yet (that arrives with Milestone 5's RAG work), so
"relevant" for now just means "not disabled and not crowded out by the cap." `chat_service.
stream_turn` fetches these once per turn and passes them to `context_builder.build_context`,
which appends a `## Things to remember about the user` section to the system prompt and marks
`"memory"` in `sources` — the same additive pattern `summary` already used, so nothing about the
function's existing contract changed. Included memories get `last_used_at` bumped, which is what
the Memory screen's ordering could build on later, though nothing reads it yet.

**The Memory screen (`frontend/src/views/Memory.tsx`) is deliberately read/edit/delete/disable
only — it has no "add memory" control.** The roadmap's own wording for this milestone ("search,
edit, delete and disable") already excludes creation, and enforcing "the only writer is the
CONFIRM-gated tool" in the UI as well as the API keeps there being exactly one path memories can
be created through, with exactly one place that path is gated.

## Conversation summarisation

Milestone 4, first slice. This closes a gap the "Known limits" section below used to list: the
`Conversation.summary`/`summarized_through` columns and the `context_builder` consumption of them
existed from Milestone 1, but nothing ever wrote to them, so a long conversation simply dropped
its oldest turns once the history budget was exceeded rather than compacting them.

`context_builder.build_context` now additionally reports `oldest_kept_sequence` on its
`BuiltContext` — the `sequence` of the earliest message actually kept this turn, or `None` if
nothing was dropped. `gaia/services/summarization_service.py`'s `summarize_if_needed` is the pure
core: given that boundary, it gathers every complete `user`/`assistant` message between
`conversation.summarized_through` and the boundary, asks the turn's own provider/model for an
updated summary (folding in whatever summary already existed), and advances
`summarized_through` — but only on success. A `ProviderError` leaves both columns untouched, so
the next turn retries the same window rather than silently losing it.

**This runs as a detached `asyncio.Task`, not inline before the turn's `done` event.** An SSE
generator can be torn down the instant the client consumes `done`, and tying summarisation to
that request's lifecycle risks it never running at all — the same reasoning `docs/ARCHITECTURE.
md`'s existing "no request cancellation" known limit already lives with. `chat_service.
stream_turn` fires `summarization_service.summarize_in_background` with the exact
`provider_id`/`model_id` the turn itself used (never re-resolved, to avoid racing a
provider/model change against the user's very next turn) and the `oldest_kept_sequence` that
turn's own `build_context` computed — recomputing that boundary independently would risk drifting
from the budgeting logic that produced it. The task opens its own `session_scope()` and swallows
every exception; a failed summarisation must never surface as a chat-turn error, since by the
time it runs the turn has already completed successfully.

## Projects

Milestone 4, second slice. `gaia/services/project_service.py` owns CRUD for `Project` and
`ProjectTask` (schema already existed, unused until now) — same shape as `conversation_service.py`.
`gaia/api/projects.py` is the HTTP surface: projects, their tasks, and one exception described
below.

**Project-scoped memory is created manually, not by the `remember` tool.** `Memory.kind="project"`
requires a `project_id` (`memory_service.create_memory` enforces this — and, symmetrically,
rejects a `project_id` on any other kind, so "a project memory always has exactly one project" is
a database-level invariant, not just a convention). The model has no notion of "the current
project" to scope a memory to — tools are conversation-agnostic by design (see "Memory" above) —
so `POST /api/projects/{id}/memories` is the one place memory creation happens outside the
CONFIRM-gated tool, deliberately scoped to a project and initiated from that project's page.
Editing or deleting a project memory reuses the general `/api/memory/{id}` routes unchanged; the
general Memory screen also lists project memories (tagged by `kind`), rather than hiding them, so
"inspectable" still means everything.

**A conversation is assigned to a project via `Conversation.project_id`**, a nullable FK that
existed since Milestone 1 (`ondelete="SET NULL"` — deleting a project unassigns its conversations
rather than deleting them). Setting it is an ordinary `PATCH /api/conversations/{id}` with
`{"project_id": "..."}` — but *unassigning* needs one deliberate exception:
`conversation_service.update_conversation`'s generic `setattr` loop skips any `None` value by
design (so a client can never accidentally null a field just by omitting it), which would also
silently swallow an explicit `{"project_id": null}` meant to clear it. `api/conversations.py`
pops `project_id` out of the payload and sets it directly, before the generic call handles
everything else — the one field genuinely needs to accept `None` as a real, intentional value.

**Project-aware context** is `context_builder.build_context`'s `project`/`project_tasks`
parameters: when a conversation's `project_id` is set, `chat_service.stream_turn` resolves the
`Project`, its open (`status != "done"`) tasks, and its project-scoped memories
(`memory_service.project_memories`), merging the memories into the same list the Memory slice
already built (so `## Things to remember about the user` and the `"memory"` source need no
changes — each line already shows its `kind`, so a `(project)` entry reads as scoped on its own)
and passing `project`/`project_tasks` separately for their own `## Current project` section (name,
description, goals, and open task *titles* — not notes, to stay compact), appending `"project"` to
`sources`. `memory_service.relevant_memories()` (the general, non-project list) explicitly
excludes `kind="project"` — otherwise every project's memory would leak into every conversation
regardless of assignment, not just the ones actually working on that project.

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

| Live | Schema only (no API surface) |
|---|---|
| `conversations`, `messages` | `documents`, `document_chunks` |
| `settings`, `task_runs` | `experiments`, `simulation_runs` |
| `tool_calls` (audit — live from Milestone 2) | `study_plans`, `learning_progress` |
| `workspace_roots` (live from Milestone 2) | `permissions` |
| `memories`, `projects`, `project_tasks` (live from Milestone 4) | |

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

- **Memory has no retrieval — it's a capped, unconditional list.** `relevant_memories()` and
  `project_memories()` both return every enabled memory in scope (up to 20), ranked by importance
  and recency; there is no embedding search to pick the ones actually relevant to the current
  turn. Fine at the scale one person's (or one project's) opt-in memories reach; would need real
  retrieval well before Milestone 5's document RAG work reuses the same idea at larger scale.
- **A project's own conversations aren't listed or filterable anywhere.** The topbar picker
  assigns a conversation to a project, but there is no "show me every conversation in this
  project" view yet — the sidebar's conversation list is not project-aware.
- **`sqlite+pysqlite` with sync sessions inside async endpoints.** Local SQLite writes are
  sub-millisecond, so they run inline. This becomes a real blocking concern only if storage
  moves off local SQLite, at which point the async engine (`aiosqlite`, already in the URL
  helper) is the path.
- **Cost estimates are catalogue-based**, so they are wrong for a model GAIA does not know. The
  UI renders unknown costs as `—` rather than guessing.
- **No request cancellation on the server.** Pressing Stop aborts the client stream; the
  provider request finishes in the background. The partial text is persisted honestly as
  `stopped`.
