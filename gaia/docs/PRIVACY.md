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
| Python execution | **LOCAL** | Isolated subprocess, requires your approval every time |
| Filesystem access | **LOCAL** | Only inside directories you explicitly allow |
| Terminal commands | **LOCAL** | Requires your approval every time; a directory you allowed |
| Voice (microphone, synthesized speech) | **LOCAL** | See "Voice" below — nothing is sent anywhere, nothing is kept |
| Memory | **LOCAL** | Stored only when you ask GAIA to remember something, and only after you approve it |
| Projects (goals, tasks, project memory) | **LOCAL** | Same database; goals/tasks are yours, project memory follows the same opt-in rule as Memory |
| Documents | **LOCAL** | The file and its extracted text stay in your data directory; retrieval is lexical (BM25), nothing is sent anywhere to search it |
| Telemetry / analytics | **none** | GAIA collects nothing and phones home to nobody |
| Web search | **not built** | Milestone 7 |

## What leaves your machine

Exactly one thing, and only if you configure a cloud provider: **the text of a chat turn**. That
means the system prompt, your custom instructions, the portion of the conversation history that
fits the context budget, and whatever `context_builder` assembled for that turn — project
context, remembered facts, and any document passages BM25 retrieved. If a tool call happened
(reading a file, running Python, a terminal command), its result is fed back to the model within
the same turn and is sent the same way. All of this only ever goes to the provider you configured
for that turn; nothing is sent anywhere else.

Nothing beyond that is transmitted: no analytics, no crash reports, no usage statistics, no
conversation titles, no metadata.

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
- **A memory** — delete it on the Memory screen (or a project's own memory list). Immediate, and
  it stops influencing replies on your very next turn.
- **A project** — delete it on the Projects screen. Its tasks and project memory are deleted with
  it; conversations that were assigned to it are kept, just unassigned.
- **A document** — delete it on the Knowledge screen. Removes the stored file and every chunk of
  its extracted text; it immediately stops being found by retrieval.
- **Everything** — quit GAIA and delete the data directory. Nothing survives elsewhere.
- **An API key** — Settings → AI & Models → Remove key. This clears the keyring entry and the
  file fallback.

There is no server-side copy to request deletion of, because there is no server.

## Voice

Push-to-talk only — GAIA is never listening unless you are actively holding/clicking the
microphone button. There is no wake word and no always-on recording in this version.

- **Your recording** is uploaded to the local backend, transcribed by a local speech-to-text
  engine (`faster-whisper`, running entirely on this machine — see docs/API.md), written to a
  temporary file for the duration of that one request, and deleted immediately after — win or
  fail. It is never sent to a cloud service, never logged, and never stored in the database.
- **GAIA's spoken replies** are synthesized locally too (`pyttsx3`, using your operating system's
  own voices) from text that was already going to be shown to you on screen. The synthesized
  audio is generated, played, and not retained — same temporary-file-then-delete lifecycle as a
  recording.
- Nothing about a voice request differs from a typed one once it reaches the model: no additional
  data is sent to a cloud LLM provider because you used voice instead of typing.
- If the microphone is unavailable or you deny permission, GAIA reports that plainly — see
  docs/API.md, "Voice" — and text chat is unaffected either way.

## Features that are not built yet

Web search does not exist yet. It is listed in the dashboard as `NOT BUILT` rather than omitted,
so the list stays a complete account of GAIA's data surface as features land. When it arrives it
will be **external**, and will be labelled as such at the point of use.
