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
| `tool_confirm_required` | `{call_id, tool, arguments}` | A `CONFIRM`-risk call is waiting on `POST /api/chat/tool-confirmations/{call_id}`. Not emitted for any tool shipped today — Calculator is `SAFE`. |
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
forever). No tool shipped today calls this path; it exists for `CONFIRM`-risk tools to come.

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
above) — only Calculator is registered so far; Python, filesystem and terminal tools are not.
