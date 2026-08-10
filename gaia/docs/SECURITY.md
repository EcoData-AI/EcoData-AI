# Security

## Threat model

GAIA is a **single-user desktop application**. It assumes the person at the keyboard owns the
machine and the data. It is not multi-tenant and has no user accounts.

What it defends against:

- Secrets leaking into version control, logs, backups or API responses.
- The backend being reachable from outside the machine.
- A malformed or hostile backup file corrupting or replacing your data unnoticed.
- The backend outliving the UI as an orphan process.

What it does **not** defend against, by design:

- An attacker who already has your user account. They can read the database directly.
- Anything the cloud provider you chose does with the text you send it.
- Malware with your privileges reading the OS keyring.

## Network

The backend binds `127.0.0.1` and has **no authentication**, because a local desktop app has no
second party to authenticate. The consequence is direct: **never bind it to `0.0.0.0` or expose
it through a tunnel or reverse proxy.** Anyone who can reach the port has full access to every
conversation and can spend your API credits.

`GAIA_HOST` exists for unusual development setups. Changing it away from loopback is a security
decision, not a convenience one.

CORS is restricted to the Tauri origins and the Vite dev server. The webview also runs under a
Content-Security-Policy that blocks remote scripts and limits `connect-src` to loopback.

## Secrets

| Rule | How it is enforced |
|---|---|
| Never in git | `.gitignore` covers `.env`, `*.key`, `*.pem`, `credentials.json`, `*.db` |
| Never in the database | Keys go through `core/secrets.py` only; the `settings` table is JSON key/value with no secret path |
| Never in logs | No code path passes a key to a logger; the JSON formatter redacts secret-shaped field names as a backstop |
| Never in a response | The providers endpoint returns a four-character `key_hint`, never the value — covered by a test |
| Never in a backup | Backups are the SQLite file, which has never held a key |

Storage precedence: environment variable → OS keyring → owner-only file (`0600`). The file
fallback exists because headless Linux frequently has no keyring backend; without it, users
would paste keys into shell profiles instead, which is worse.

## Input handling

- Every request body is validated by Pydantic. `content` is capped at 200,000 characters.
- Settings keys are checked against an allow-list; an unknown key is a `400`, so the settings
  table cannot be used as arbitrary storage.
- Provider ids are checked against the registry before use.
- Backup import verifies the SQLite magic header **and** the presence of GAIA's own tables
  before touching anything, then copies the current database aside so an import can be undone.
- Markdown is rendered by `react-markdown`, which does not evaluate raw HTML. Links open
  externally with `rel="noreferrer noopener"`.

## Process lifetime

The backend must not outlive the window. Two independent mechanisms:

1. The Rust shell kills the child on `ExitRequested`/`Exit`.
2. The backend polls its parent PID every two seconds and exits when it disappears — this covers
   `SIGKILL` on the shell, where mechanism 1 cannot run.

Verified in this build: killing the shell leaves no orphaned Python process.

## Permission model (Milestones 2+)

Nothing in v0.1 touches your filesystem, runs code, or executes commands, so there is nothing to
gate yet. The model those features will use is fixed now so it is not retrofitted:

| Level | Behaviour | Examples |
|---|---|---|
| **SAFE** | Runs without asking; audited | Read within an allowed workspace, calculate, analyse |
| **CONFIRM** | Shows the exact action and waits for approval | Write or move a file, install a package, run an unusual command |
| **BLOCKED** | Refused, or requires explicit per-action escalation | Recursive deletion, partition changes, disabling protections, exfiltrating data |

Supporting decisions already in place:

- `tool_calls` exists in the schema now, so the audit trail is never retrofitted. Every
  invocation will record arguments, risk level, how it cleared the permission gate, and result.
- `workspace_roots` will hold the explicitly allowed directories. Access outside them is denied,
  with path traversal blocked by canonicalising and re-checking containment — never by string
  matching.
- Python will execute in a subprocess with memory, wall-clock and process limits, never inside
  the API process.
- Commands will be shown in full before execution. GAIA will never run a hidden command.

## Reporting a vulnerability

Open a GitHub issue for anything non-sensitive. For something that should not be public, contact
the repository owner directly rather than filing publicly.
