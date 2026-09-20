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

## Permission model (Milestone 2 — complete)

Five tools exist now, all of Milestone 2's original scope: `calculator` and `filesystem_read`
(`SAFE`); `python_sandbox`, `filesystem_write` and `terminal` (`CONFIRM`).

| Level | Behaviour | Examples |
|---|---|---|
| **SAFE** | Runs without asking; audited | Calculate, read within an allowed workspace — `calculator`, `filesystem_read` |
| **CONFIRM** | Shows the exact action and waits for approval | Run code, write a file, run a command — `python_sandbox`, `filesystem_write`, `terminal` |
| **BLOCKED** | Refused, or requires explicit per-action escalation | Recursive deletion, partition changes, disabling protections, exfiltrating data |

There is no per-action escalation flow yet, so `BLOCKED`-tier behaviour is approximated today by
`terminal`'s pattern-based refusal (below) rather than a real escalation UI — worth knowing if a
future tool needs a genuine `BLOCKED` risk level rather than a within-tool refusal.

What's actually enforced for `python_sandbox` today, and what is not:

- Runs in a real subprocess, never inline in the API process, with a wall-clock timeout and a
  sanitised environment — GAIA's own secrets (see "Secrets" above) are never visible to it.
- Runs inside `config.sandbox_dir`, a directory dedicated to this purpose.
- Memory, CPU and process-count limits are enforced via `resource.setrlimit` on POSIX only —
  **Windows has no equivalent stdlib mechanism**, so on Windows the wall-clock timeout is the only
  ceiling. Stated plainly rather than implied to be covered.
- The subprocess shares the backend's own Python environment, so sandboxed code can `import gaia`
  and reach the app's database and secrets modules at the Python level — this is not yet
  contained. It is why the tool is `CONFIRM`: the human approval in front of every call is real
  protection today independent of how complete the technical sandboxing is.
- No network isolation exists. Sandboxed code can make outbound connections.

What's actually enforced for `filesystem_read`/`filesystem_write` today:

- Nothing is accessible until a `workspace_root` row exists (`POST /api/workspace/roots`) —
  there is no default directory either tool falls back to.
- Every path is canonicalised (`Path.resolve()`, which collapses `..` and follows symlinks) and
  re-checked for containment inside an *enabled* root — never string or prefix matching on the
  raw path, which both `..` and a symlink can defeat.
- A root's own `writable` flag is independent of the tool's `CONFIRM` risk level: a read-only
  root refuses `filesystem_write` even if the call is approved.
- Registering a root is a settings action taken by the person at the keyboard (the same threat
  model as everything else in this document), not something a model can request — it carries no
  audit row and no risk gate, matching how a provider API key is set.
- Content is size-capped (200 KB read, 1 MB write) and must be valid UTF-8 text; there is no
  binary file support.
- There is no move or delete operation. Deletion is `BLOCKED`-tier per the table above; rather
  than define a tool and mark it permanently blocked, it is simply not implemented.

What's actually enforced for `terminal` today, and what is not:

- Every call requires approval, and the user is shown the **exact** command before it runs —
  GAIA never runs a hidden or paraphrased command. This transparency is the primary defence.
- `cwd` must resolve inside an enabled, **writable** workspace root — required even for a
  command that only looks read-only, because a shell can always do more than it appears to.
- A short, explicit blocklist refuses a command matching an unambiguously destructive pattern
  **even after approval**: recursive deletion (`rm -r`, `rd /s`, `del /s`, `Remove-Item
  -Recurse`), disk formatting/partitioning (`format`, `diskpart`, `mkfs`, `fdisk`, raw `dd` to a
  device), disabling Windows Defender or a Windows/Linux firewall, disabling SELinux, and the
  classic shell fork-bomb signature.
- **This blocklist is pattern matching on the command's tokens, not a security boundary.** It
  is checked with `shlex`-based tokenisation against actual flag tokens, so it does not
  false-positive on `git push --force` or `docker rm -f` (neither is `rm -r`) — but it also does
  **not** stop deliberate evasion: variable expansion, quoting tricks, an equivalent command
  phrased differently. It catches a model plainly asking for something catastrophic, not
  determined intent to get around it.
- Wall-clock timeout, sanitised environment, and — POSIX only — `resource.setrlimit` memory/CPU
  limits, identical disclosed gap on Windows as `python_sandbox`.

Supporting decisions already in place:

- `tool_calls` records every invocation now — arguments, risk level, how it cleared the
  permission gate (`auto` / `approved` / `denied`), status, timing, result.
- The `CONFIRM` pause-and-resume path (`services/tool_confirmation.py`) is proven over a live
  connection by `python_sandbox`, `filesystem_write`, and now `terminal` — three independent
  tools, not just built speculatively for one.

## Voice (Milestone 3, first slice)

Not a new authentication or network surface: the microphone is captured entirely in the browser
(`getUserMedia`), gated by the browser's own OS-level permission prompt — GAIA's backend never
requests microphone access itself, and receives only the audio bytes the frontend already chose
to upload. `/api/voice/transcribe` and `/api/voice/speak` are ordinary loopback-only endpoints,
covered by the same no-authentication threat model as every other route (see "Network" above).

What's actually enforced:

- Push-to-talk only. Recording starts only on an explicit user action and stops on another one —
  there is no timer-based or automatic recording anywhere in this slice.
- Every temporary audio file (an uploaded recording, a synthesized reply) is deleted in a
  `finally` block before its endpoint returns, success or failure — verified by tests that assert
  `config.voice_dir` is empty after both a successful and a failing request, not just documented.
- Upload size is capped (25 MB) before anything touches disk.
- `pyttsx3.runAndWait()` was found, empirically, to hang indefinitely rather than raise when its
  output directory doesn't exist. Fixed with a pre-flight directory check plus a wall-clock
  `asyncio.wait_for` backstop on both the STT and TTS calls — stated here because a hang that
  silently ties up a request is exactly the kind of failure mode this document exists to name
  rather than let go undocumented.

What is not attempted in this slice, on purpose: wake-word detection, always-listening capture,
barge-in/interruption, and any cloud STT/TTS integration — see docs/ROADMAP.md and
docs/ARCHITECTURE.md, "Voice", for what's deliberately deferred and why.

## Reporting a vulnerability

Open a GitHub issue for anything non-sensitive. For something that should not be public, contact
the repository owner directly rather than filing publicly.
