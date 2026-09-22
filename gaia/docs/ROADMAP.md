# Roadmap

Milestones ship one at a time. Each one must leave GAIA in a genuinely runnable state — the
whole point of the sequencing is that there is never a version where a feature is visible but
fake.

## Definition of done

A feature is done only when **all** of these hold:

1. It actually works end to end, wired to a real backend.
2. It is integrated with the rest of the app, not bolted on.
3. It has tests.
4. Its failure modes are handled and produce a readable explanation, not a stack trace.
5. Documentation is updated.
6. It respects the architecture and the permission model.
7. It breaks nothing that already worked.
8. Its flag in `core/capabilities.py` is flipped to `available` — **last**, not first.

Until step 8, the interface says the feature does not exist, and GAIA says so in conversation
too.

---

## ✅ Milestone 1 — Desktop app, chat, providers *(shipped)*

Tauri shell that supervises the Python backend · React + TypeScript interface · provider
abstraction with Anthropic, OpenAI-compatible and Ollama · SSE streaming · SQLite with Alembic ·
conversation history with search, rename, pin, archive, delete · first-run wizard with a real
connection test · privacy dashboard · system status · backup export/import · OS-keyring secrets.

Acceptance: open GAIA, talk to it, get a real answer, close it, reopen it, find the conversation
still there. **Verified.**

## Milestone 2 — Tools

Tool interface (`name`, `description`, `schema`, `permissions`, `risk_level`, `execute`) ·
tool-call loop with results rendered in the thread · SAFE/CONFIRM/BLOCKED gating with the
approval dialog · `tool_calls` audit trail · Calculator · Python sandbox (subprocess, resource
limits, NumPy/Pandas/SciPy/SymPy/Matplotlib) · workspace-scoped filesystem · audited terminal.

Acceptance: ask GAIA to compute something and watch it run real code, see the command before it
runs, and find the run in the audit log.

## ✅ Milestone 3 — Voice, first slice *(shipped)*

`STTProvider`/`TTSProvider` behind swappable interfaces (`gaia/voice/`, mirroring `gaia/llm/` and
`gaia/tools/`) · push-to-talk microphone capture · playback · `faster-whisper` (STT) and
`pyttsx3` (TTS), both local, no cloud dependency · voice sits entirely outside the chat turn — a
spoken request reaches `send()` exactly like a typed one, so tools, confirmations and the audit
trail all work identically. Moved ahead of Memory/Projects because it stood on its own, needed no
prior milestone, and was ready first.

Acceptance: hold the mic, ask a question, hear the answer spoken back. **Verified.**

Later, once voice quality matters more than "does the pipeline work at all": barge-in,
end-of-speech detection, streaming, and a neural TTS voice (Piper) in place of the OS's own.

## Milestone 4 — Memory and projects

Working / episodic / semantic / project memory · an inspectable Memory screen with search, edit,
delete and disable · opt-in capture, never automatic · conversation summarisation feeding the
context builder · projects with goals, tasks, notes and their own memory · project-aware
context.

Acceptance: "remember that I prefer formal notation", see it in the Memory screen, delete it,
and watch it stop influencing replies. **Verified** for the memory half below; projects remains
open.

**✅ Memory, first slice** *(shipped)* — semantic and episodic memory via an opt-in, CONFIRM-gated
`remember` tool; the Memory screen (search, edit, disable, delete); conversation summarisation
feeding the context builder, closing the gap `docs/ARCHITECTURE.md`'s "Known limits" flagged.
Shipped as its own slice the way Voice shipped ahead of Memory/Projects in Milestone 3 — Projects
needed more design (goals/tasks UI, project-aware context, project-scoped memory) and depended on
nothing memory itself needed to ship.

**⛔ Projects** — still pending: goals, tasks, notes, a Projects screen, project-scoped memory
(the `project` memory `kind`), and project-aware context via `Conversation.project_id`.

## Milestone 5 — Documents and retrieval

PDF/TXT/Markdown/CSV/code ingestion · chunking · embeddings · retrieval into the context builder
· citations that name the passage supporting each claim.

Acceptance: import a PDF, ask about it, get an answer that points at the specific passage.

## Milestone 6 — Tutor and study

Level assessment · generated curriculum · Socratic questioning that withholds the answer while
you are still working · exercises, quizzes, spaced repetition · progress tracking · the Study
screen.

Acceptance: "teach me game theory" produces a real course that adapts to your answers.

## Milestone 7 — Research

Search · multi-source retrieval · source evaluation · extraction · synthesis with citations.
GAIA must never claim to have read a source it did not fetch.

## Milestone 8 — Economics and game theory

Supply/demand, elasticity, competition, monopoly, oligopoly, externalities, growth, agent-based
models, basic econometrics · players, strategies, payoff matrices, dominance, best responses,
pure and mixed Nash equilibria, repeated games, evolutionary dynamics · natural language →
formal model → code → simulation → plot → interpretation.

## Milestone 9 — Simulation Lab

Experiment definition, Monte Carlo runs, parameter sweeps, scenario comparison, saved and
reproducible experiments (seed + environment recorded), visualisation.

Acceptance: run a repeated prisoner's dilemma with 100 agents over 1000 rounds, save it, and
reproduce it exactly days later.

## Milestone 10 — Agent loop

Observe → understand → plan → act → verify → continue, over multiple steps · task manager with
progress and cancellation · observability panel showing plan, tools used, files touched,
commands run · verification appropriate to the work (tests for code, checks for simulations,
source verification for research) · specialised agents only where they earn their complexity.

---

## Deliberately not scheduled

Multi-user support, a hosted backend, mobile clients, and a plugin marketplace. Each would
compromise the local-first, single-user assumptions that make the rest of the design simple.
