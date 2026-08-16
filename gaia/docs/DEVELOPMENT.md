# Development

## Setup

```bash
./scripts/install.sh      # venv + backend deps + frontend build
```

Or by hand:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cd ../frontend && npm install
cd .. && npm install      # Tauri CLI
```

## Running

Two terminals — this is the fastest loop, with hot reload on the UI:

```bash
cd backend  && .venv/bin/python -m gaia    # API on :8756
cd frontend && npm run dev                 # UI on :5173, proxies /api to :8756
```

Open http://localhost:5173.

The desktop shell against the dev server:

```bash
npx tauri dev
```

In debug builds the shell deliberately does **not** spawn a backend — you are running one
yourself, and the Vite proxy handles `/api`. Release builds spawn and supervise it.

Without the shell at all:

```bash
./scripts/run.sh          # backend serves frontend/dist, opens a browser
```

## Environment

`GAIA_DATA_DIR` is the one you will want most — point it somewhere disposable so experiments do
not touch your real conversations:

```bash
export GAIA_DATA_DIR=/tmp/gaia-dev
export GAIA_ENABLE_MOCK_PROVIDER=1    # offline provider, no API key needed
```

Full list in `backend/.env.example`.

## Testing

```bash
cd backend  && .venv/bin/python -m pytest        # 36 tests
cd backend  && .venv/bin/python -m ruff check gaia tests
cd frontend && npm test                          # SSE parser
cd frontend && npm run build                     # typecheck + build
```

Tests use `GAIA_ENABLE_MOCK_PROVIDER=1` and a per-test temporary data directory. The `gaia_env`
fixture unsets `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` so a developer's real credentials can
never leak into a test run — or get used by one.

The mock provider is not a language model. It echoes its input with an explicit `[mock provider]`
prefix so a canned response can never be mistaken for a real one.

## Database changes

```bash
cd backend
.venv/bin/python -m alembic revision --autogenerate -m "add widgets"
.venv/bin/python -m alembic upgrade head          # or just restart the app
```

The app runs `upgrade head` at startup. Always read the generated migration before committing —
autogenerate misses server defaults and column renames (it sees a drop plus an add). Migrations
use `render_as_batch=True` because SQLite cannot `ALTER` most things in place.

## Adding a provider

1. Subclass `LLMProvider` in `gaia/llm/`. Implement `list_models`, `health` and `stream_chat`.
2. Translate every transport and vendor error into a `ProviderError` subclass with a `message`
   and an actionable `remedy`. Nothing above this layer should see an httpx or SDK exception.
3. `health()` must never raise — return `ProviderHealth(HealthState.ERROR, …)` instead.
4. Register it in `PROVIDER_CLASSES` and add its id to `available_provider_ids()`.
5. If the vendor rejects certain parameters on certain models, record that in
   `llm/catalog.py` rather than branching inline. Sending a rejected parameter is a hard 400;
   omitting an optional one always works, so default to omitting.
6. Add the env var name to `ENV_VARS` in `core/secrets.py` if it has a conventional one.

## Adding a feature that the UI exposes

Order matters — this is what keeps the interface honest:

1. Build it. Backend, then API, then UI.
2. Test it.
3. Document it.
4. **Then** flip its flag in `core/capabilities.py` to `available=True`.
5. Update `BASE_SYSTEM_PROMPT` in `core/persona.py`, which lists what GAIA cannot do — otherwise
   GAIA will keep telling users a shipped feature does not exist.

Steps 4 and 5 are the last things you do, not the first.

## Layout

```
gaia/
├── backend/          FastAPI + SQLAlchemy + Alembic
│   ├── gaia/
│   │   ├── api/          routers (HTTP shape only)
│   │   ├── core/         persona, context, secrets, capabilities, logging
│   │   ├── db/           models, session, migrations
│   │   ├── llm/          provider abstraction
│   │   ├── schemas/      Pydantic models
│   │   └── services/     business logic
│   ├── alembic/
│   └── tests/
├── frontend/         React + TypeScript + Vite
│   └── src/{components,views,lib,store}
├── src-tauri/        Rust desktop shell
├── scripts/          install / run, per platform
└── docs/
```

Dependencies point one way: `api → services → core/llm → db`. A router should contain no
business logic; if you are writing an `if` in a router that is not about HTTP, it belongs in a
service.

## Conventions

- Python: ruff, 100 columns, type hints on public functions.
- TypeScript: strict mode, no `any`, `@/` alias for `src/`.
- Comments explain *why*, not *what*. A comment restating the code is noise; a comment recording
  a non-obvious constraint (a vendor 400, an ordering requirement) earns its place.
- Commits are logical units with a body explaining the reasoning.

## Debugging

**Backend won't start** — run `.venv/bin/python -m gaia` directly; the traceback goes to stderr.
Check `logs/gaia.log` in your data directory.

**UI can't reach the backend** — in dev, confirm the backend is on :8756 (the Vite proxy target).
In the packaged app the shell injects the port; check `window.__GAIA_API_BASE__` in devtools.

**Streaming stalls** — check for a proxy buffering the response. The backend sets
`X-Accel-Buffering: no` and `Cache-Control: no-transform` for exactly this.

**A provider fails** — Settings → AI & Models → Test connection reports the real reason.
