# GAIA

**General-purpose Adaptive Intelligence Assistant** — a local-first desktop AI application.

GAIA is software: a program that runs language models and tools on your behalf. It is not
conscious and does not pretend to be. Your conversations, settings and data stay on your
machine; you choose which model provider — cloud or fully local — answers your questions.

> **Status: Beta v0.1 — Milestones 1–4 shipped.**
> Chat, conversation history, model providers, tools (calculator, Python, filesystem, terminal),
> voice (first slice), memory and projects all work. Documents, research, tutoring and simulation
> are **not built yet**. GAIA says so plainly in the interface and in conversation rather than
> pretending otherwise. See [ROADMAP.md](docs/ROADMAP.md).

---

## What works today

| Feature | Status |
|---|---|
| Streaming chat with Markdown, code blocks, tables and LaTeX | ✅ |
| Conversation history — search, rename, pin, archive, delete | ✅ |
| Provider abstraction: Anthropic, OpenAI-compatible, Ollama | ✅ |
| First-run setup wizard with a real connection test | ✅ |
| Privacy dashboard and system status | ✅ |
| Local SQLite storage with export/import backups | ✅ |
| API keys in the OS keyring, never in the database | ✅ |
| Tools · Python sandbox · filesystem · terminal, with SAFE/CONFIRM/BLOCKED gating and an audit trail | ✅ |
| Voice — push-to-talk STT/TTS, fully local | ✅ |
| Memory — opt-in, CONFIRM-gated `remember` tool, an inspectable Memory screen | ✅ |
| Projects — goals, tasks, project-scoped memory, project-aware context | ✅ |
| Documents & RAG | ⛔ Milestone 5 |
| Tutor · Study | ⛔ Milestone 6 |
| Research | ⛔ Milestone 7 |
| Economics · Game theory | ⛔ Milestone 8 |
| Simulation Lab | ⛔ Milestone 9 |
| Autonomous agent loop | ⛔ Milestone 10 |

---

## Install

**Requirements:** Python 3.10+, Node.js 18+. Rust is only needed to build the desktop app.

```bash
# macOS / Linux
git clone <this repository>
cd gaia
./scripts/install.sh
./scripts/run.sh
```

```powershell
# Windows
cd gaia
.\scripts\install.ps1
.\scripts\run.ps1
```

`run.sh` starts the backend and opens the interface. On first launch GAIA walks you through
choosing a provider, entering credentials and testing the connection.

### Build the desktop application

```bash
./scripts/install.sh --build      # macOS / Linux
.\scripts\install.ps1 -Build      # Windows
```

The installer lands in `src-tauri/target/release/bundle/` — a `.dmg` on macOS, `.deb`/`.AppImage`
on Linux, `.msi`/`.exe` on Windows. Install it and launch **GAIA** like any other application;
the desktop shell starts and stops the backend for you.

On Linux, building requires the Tauri system libraries:

```bash
sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev \
                 librsvg2-dev patchelf build-essential curl wget file libssl-dev
```

---

## Choosing a provider

| Provider | Where inference runs | Needs |
|---|---|---|
| **Anthropic** | Cloud | An API key from [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| **OpenAI-compatible** | Cloud or local | A base URL and key — works with OpenAI, LM Studio, vLLM, OpenRouter, llama.cpp |
| **Ollama** | Your machine | [Ollama](https://ollama.com) running locally, with at least one model pulled |

Pick Ollama if you want nothing at all to leave your computer. GAIA's privacy dashboard
(Settings → Privacy) always tells you which is which.

---

## Where your data lives

Everything GAIA writes goes to one directory outside the source tree:

| Platform | Path |
|---|---|
| Linux | `~/.local/share/GAIA` |
| macOS | `~/Library/Application Support/GAIA` |
| Windows | `%LOCALAPPDATA%\GAIA` |

```
GAIA/
├── database/     conversations, messages, settings (SQLite)
├── logs/         structured JSON logs, rotated
├── backups/      database exports
├── config/       credential fallback when no OS keyring is available
├── sandbox/      workspace-scoped filesystem and Python sandbox roots
├── memory/       reserved for later (memory itself lives in database/, below)
├── documents/    (Milestone 5)
├── projects/     reserved for later (project data itself lives in database/, below)
└── experiments/  (Milestone 9)
```

API keys are stored in your OS keyring — never in the database, never in a backup, never in git.

---

## Development

```bash
cd backend && .venv/bin/python -m gaia   # terminal 1: API on :8756
cd frontend && npm run dev               # terminal 2: UI on :5173, proxies /api
```

Or run the desktop shell against the dev server with `npx tauri dev` from `gaia/`.

```bash
cd backend && .venv/bin/python -m pytest    # 36 backend tests
cd frontend && npm test                      # frontend tests
```

See [DEVELOPMENT.md](docs/DEVELOPMENT.md).

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Stack, layering, request lifecycle, design decisions |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Local setup, workflows, testing, adding a provider |
| [API.md](docs/API.md) | Every HTTP endpoint, with the SSE protocol |
| [PRIVACY.md](docs/PRIVACY.md) | What is stored, what leaves the machine, and when |
| [SECURITY.md](docs/SECURITY.md) | Threat model, secret handling, the permission model |
| [ROADMAP.md](docs/ROADMAP.md) | Milestones and their definition of done |

---

## Licence

MIT.
