# Privacy

GAIA is local-first. This document states exactly what is stored, where, and what leaves your
machine. The same information is shown live in the app under **Settings → Privacy**, generated
from the running configuration rather than written by hand.

## Summary

| Data | Location | Detail |
|---|---|---|
| Conversations and messages | **LOCAL** | SQLite in your data directory |
| Settings | **LOCAL** | Same database |
| API keys | **LOCAL** | OS keyring, or an owner-only file |
| Logs | **LOCAL** | Rotated JSON in your data directory |
| Backups | **LOCAL** | Written only when you ask |
| LLM inference | **LOCAL or CLOUD** | Depends on the provider you chose |
| Telemetry / analytics | **none** | GAIA collects nothing and phones home to nobody |
| Memory, documents, Python, web search | **not built** | Milestones 2–6 |

## What leaves your machine

Exactly one thing, and only if you configure a cloud provider: **the text of a chat turn**. That
means the system prompt, your custom instructions, and the portion of the conversation history
that fits the context budget — sent to Anthropic or your configured OpenAI-compatible endpoint
so it can generate a reply.

Nothing else is transmitted. No file contents (GAIA cannot read files yet), no analytics, no
crash reports, no usage statistics, no conversation titles, no metadata.

**Choose the Ollama provider and nothing leaves at all** — inference runs on your own hardware.
The privacy dashboard shows `LLM inference — LOCAL` when that is the case, and `CLOUD` when it
is not. It reads the live setting, so it cannot drift out of date.

When you send data to a cloud provider, that provider's own terms and retention policy apply.
GAIA has no influence over what they do with it, which is the reason the dashboard names the
provider explicitly rather than saying "the cloud".

## Where data is stored

| Platform | Path |
|---|---|
| Linux | `~/.local/share/GAIA` |
| macOS | `~/Library/Application Support/GAIA` |
| Windows | `%LOCALAPPDATA%\GAIA` |

Override with `GAIA_DATA_DIR`. On POSIX systems the directory is created with mode `0700` —
owner-only. Nothing user-generated is ever written inside the application or the source
repository.

## API keys

Keys are resolved in this order: environment variable → OS keyring → owner-only file
(`config/credentials.json`, mode `0600`, used when a machine has no keyring backend — common on
headless Linux).

A key is **never** written to the database, **never** included in a backup, **never** written to
a log, and **never** returned by the API. The providers endpoint returns only a `key_hint` — the
last four characters — so you can tell which key is configured without transporting it.

## Logs

Structured JSON, rotated at 5 MB with three generations, in `logs/gaia.log`. They record request
timing, provider id, model id, token counts and errors. The formatter redacts any field named
like a secret as a backstop; no code path passes a key to a logger in the first place.

**Message content is not logged.**

## Deleting data

- **One conversation** — delete it in the sidebar. Messages cascade immediately.
- **Everything** — quit GAIA and delete the data directory. Nothing survives elsewhere.
- **An API key** — Settings → AI & Models → Remove key. This clears the keyring entry and the
  file fallback.

There is no server-side copy to request deletion of, because there is no server.

## Features that are not built yet

Memory, document ingestion, Python execution and web search do not exist in v0.1. They are
listed in the dashboard as `NOT BUILT` rather than omitted, so the list stays a complete account
of GAIA's data surface as features land. When they arrive:

- Memory, documents and Python will be **local**, and memory will be opt-in and inspectable.
- Web search will be **external**, and will be labelled as such at the point of use.
