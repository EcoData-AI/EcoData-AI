# API

Base URL: `http://127.0.0.1:8756` (the desktop shell picks a free port and injects it as
`window.__GAIA_API_BASE__`). Loopback only, no authentication — see [SECURITY.md](SECURITY.md).

Interactive docs are served at `/docs` while the backend is running.

---

## Chat

### `POST /api/chat`

Streams one assistant turn as Server-Sent Events.

```json
{
  "conversation_id": "a1b2…",
  "content": "Explain Nash equilibrium",
  "provider_id": null,
  "model_id": null
}
```

`provider_id` and `model_id` override the configured defaults for this turn only.

**Response:** `text/event-stream`.

| Event | Payload | Meaning |
|---|---|---|
| `user_message` | `{id, sequence, title}` | The user turn was persisted. `title` may be newly derived. |
| `start` | `{message_id, sequence, provider_id, model_id, context:{sources, estimated_input_tokens, dropped_messages}}` | The provider accepted the request. |
| `delta` | `{text}` | Append to the assistant message. Emitted many times. |
| `tool_call` | `{call_id, tool, arguments, risk_level}` | A tool call was accepted for execution (`risk_level: "safe"`) or is about to be gated (`"confirm"`). |
| `tool_confirm_required` | `{call_id, tool, arguments}` | A `CONFIRM`-risk call (`python_sandbox`) is waiting on `POST /api/chat/tool-confirmations/{call_id}`. |
| `tool_result` | `{call_id, tool, ok, content, display, error}` | A tool call finished. `ok: false` is reported here, not as a turn `error` — the model sees it and can react. |
| `error` | `{kind, message, remedy, status}` | The turn failed. Terminal. |
| `done` | `{message_id, stop_reason, latency_ms, input_tokens, output_tokens, cost_usd}` | The turn completed. Terminal. |

`tool_call`/`tool_confirm_required`/`tool_result` can repeat (a turn may call more than one tool,
and may call the provider again after a result comes back), interleaved with further `delta`
events, up to an internal per-turn cap.

```
event: start
data: {"message_id":"c3d4…","provider_id":"anthropic","model_id":"claude-opus-5", …}

event: delta
data: {"text":"A Nash equilibrium is "}

event: done
data: {"message_id":"c3d4…","stop_reason":"end_turn","latency_ms":4210,"input_tokens":812,"output_tokens":394,"cost_usd":0.013916}
```

**Errors arrive as an `error` event, not an HTTP status**, because the response has usually
already started. `kind` is one of `not_configured`, `auth_error`, `rate_limited`, `unavailable`,
`refused`, `not_found`, `internal_error`. `remedy` is a sentence the UI can show as the next
step.

Only malformed requests fail before the stream: an empty `content` returns `422`.

### `POST /api/chat/tool-confirmations/{call_id}`

Resolves a pending `CONFIRM`-risk tool call raised mid-turn by a `tool_confirm_required` event.

```json
{ "approved": true }
```

`204` on success. `404` if there was nothing pending for that id — already resolved, or the
5-minute wait timed out (an unanswered confirmation auto-denies rather than hanging the turn
forever). `python_sandbox` is the only tool that uses this path today.

---

## Conversations

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/conversations` | `?q=` searches titles **and** message bodies; `?include_archived=`, `?limit=`, `?offset=` |
| `POST` | `/api/conversations` | `{title?, provider_id?, model_id?}` → `201` |
| `GET` | `/api/conversations/{id}` | Includes all messages |
| `PATCH` | `/api/conversations/{id}` | `{title?, pinned?, archived?, system_prompt?, model_id?, provider_id?}` — only the fields you send are changed |
| `DELETE` | `/api/conversations/{id}` | `204`; messages cascade |
| `GET` | `/api/conversations/{id}/messages` | Ordered by `sequence` |

A `message` carries `role`, `content`, `sequence`, `status`
(`complete` / `streaming` / `stopped` / `error`), `error`, and per-turn `provider_id`,
`model_id`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`. `extra` holds
`{"tool_calls": [...]}` when the turn called a tool (same shape as the `tool_result` SSE event),
or `null` otherwise.

---

## Providers and models

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/providers` | Includes `configured` and a `key_hint` like `…1234`. **Never returns a key.** |
| `PUT` | `/api/providers/{id}/credentials` | `{api_key?, base_url?, default_model?}`. The key goes to the OS keyring. |
| `DELETE` | `/api/providers/{id}/credentials` | Removes the stored key |
| `GET` | `/api/providers/{id}/models` | Catalogue for Anthropic; a live query for the others |
| `POST` | `/api/providers/{id}/test` | Real connection check → `{state, detail, latency_ms}` |

`state` is `ok`, `not_configured` or `error`. `context_window: 0` means "unknown" — the UI shows
`—` rather than inventing a number, and the same applies to a `null` cost.

---

## Settings

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/settings` | `{values, data_dir}` |
| `PATCH` | `/api/settings` | `{values:{…}}`; an unknown key returns `400` |

Keys: `llm.active_provider`, `llm.active_model`, `llm.temperature`, `llm.max_tokens`,
`llm.monthly_cost_limit_usd`, `general.custom_instructions`, `general.onboarding_complete`,
`appearance.theme`.

Secrets are **not** settings and are never returned here.

---

## System

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/health` | `{status, version}` — the shell's readiness probe |
| `GET` | `/api/capabilities` | Every feature with `available` and `milestone`. The source of truth for what exists. |
| `GET` | `/api/system/status` | Per-component state; unbuilt features report `not_built` |
| `GET` | `/api/system/info` | Version, platform, paths |
| `GET` | `/api/privacy` | Per-data-category location: `LOCAL`, `CLOUD`, `EXTERNAL`, `NOT BUILT` |

`/api/privacy` reflects the **currently selected provider** — choosing Ollama flips
`LLM inference` from `CLOUD` to `LOCAL`.

---

## Workspace

Registers the directories `filesystem_read`, `filesystem_write`, and `terminal` (see
`docs/ARCHITECTURE.md`, "Tool system") are allowed to touch. This is a settings action, not a
tool call — no `ToolCall` audit row, no risk gate. No Settings UI exists for this yet; use these
endpoints directly.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/workspace/roots` | List every registered root |
| `POST` | `/api/workspace/roots` | `{path, writable?}` → `201`. `path` must be absolute, must already exist, must be a directory, and must not itself be a filesystem root (`C:\`, `/`) |
| `DELETE` | `/api/workspace/roots/{id}` | `204`; `404` if unknown |

```json
{ "path": "C:\\Users\\you\\Documents\\gaia-workspace", "writable": true }
```

`writable: false` (the default) allows `filesystem_read` only — `filesystem_write` and `terminal`
both refuse even an approved call against a read-only root.

---

## Voice

Push-to-talk only in this first slice — no wake word, no always-listening, no barge-in. Neither
endpoint is part of a chat turn; see `docs/ARCHITECTURE.md`, "Voice", for how they bracket an
otherwise-unmodified `POST /api/chat` call.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/voice/transcribe` | Multipart `file` (a recorded clip). `200` → `{text, language}`. `422` if empty or no speech detected, `413` if over 25 MB, `502` if the engine fails. |
| `POST` | `/api/voice/speak` | `{text}` → raw `audio/wav` bytes in the response body. `422` if `text` is empty, `502` if the engine fails. |

Both endpoints write a temporary file under the data directory's `voice/` folder and delete it in
a `finally` block before responding — nothing is retained after the request completes, success or
failure. See docs/PRIVACY.md, "Voice", for the full data-retention statement.

### Engine choice and evaluation

| | STT: `faster-whisper` | TTS: `pyttsx3` |
|---|---|---|
| Model | `tiny.en`, ~75 MB | none — uses OS voices already installed |
| Backend | CTranslate2 (no PyTorch) | SAPI5 (Windows), NSSpeechSynthesizer (macOS, untested), espeak (Linux, untested) |
| Load time | ~3s once cached (~60–100s first download) | instant, nothing to download |
| RAM | roughly 200–400 MB resident once loaded | negligible — delegates to the OS |
| Latency (short clip, this machine) | ~1s to transcribe | ~1–3s to synthesize a sentence |
| License | MIT (both the wrapper and the Whisper weights) | MIT (`pyttsx3`); underlying OS engine's own terms |
| Offline | fully, after the one-time model download | fully, always |
| Confirmed working here | yes — real transcription tested, not assumed | yes — real synthesis tested, not assumed |

Alternatives considered and why they weren't the first choice: plain `openai-whisper` pulls in a
full PyTorch install, a large dependency this project has avoided everywhere else, for a CPU
inference speed disadvantage against CTranslate2. Piper (local, neural, much better voice quality
than `pyttsx3`) was the presumed default going in, but this milestone's stated priority is
reliability over quality for the *first* slice — `pyttsx3` needs no model fetch at all, so it
cannot fail a first run the way a multi-hundred-MB Piper voice download could. Piper remains the
documented next `TTSProvider`.

Both are swappable per `voice.stt_provider`/`voice.tts_provider` settings
(`gaia/services/settings_service.py`) — no Settings UI for this yet, same gap as workspace roots.

---

## Backups

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/backup/export` | Consistent snapshot via SQLite's backup API, safe while running |
| `POST` | `/api/backup/import` | Multipart `file`. Validates the header and schema first, copies the current database aside, then swaps. `restart_required: true`. |

Backups contain conversations and settings. They do **not** contain API keys.

---

## Endpoints that do not exist yet

`/api/memory`, `/api/projects`, `/api/research`, `/api/simulations`, `/api/study` are named in
the roadmap but **are not implemented**. They return `404`. Check `/api/capabilities` rather than
assuming. The tool-call loop itself is live (`/api/chat` and `/api/chat/tool-confirmations/{id}`,
above), with all five tools from Milestone 2's original scope registered: calculator,
python_sandbox, filesystem_read, filesystem_write, terminal.
