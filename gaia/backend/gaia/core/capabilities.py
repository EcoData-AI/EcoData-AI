"""The single source of truth for what GAIA can actually do right now.

Every surface that could imply a capability — the sidebar, the system status
panel, the privacy dashboard, the model's own system prompt — reads from here.
Flipping a flag to `True` is the last step of shipping a feature, not the first.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Capability:
    key: str
    label: str
    available: bool
    milestone: int
    detail: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability("chat", "Chat", True, 1, "Streaming conversations with the configured model."),
    Capability("history", "Conversation history", True, 1, "Stored locally in SQLite."),
    Capability("providers", "Model providers", True, 1, "Anthropic, OpenAI-compatible, Ollama."),
    Capability("settings", "Settings & privacy", True, 1, "Provider, model and data controls."),
    Capability("backups", "Backup & restore", True, 1, "Export and import the local database."),
    Capability("tools", "Tool system", True, 2, "Calculator, Python, filesystem, terminal."),
    Capability("python", "Python sandbox", True, 2, "Sandboxed execution with NumPy/SciPy/SymPy."),
    Capability("filesystem", "Filesystem access", True, 2, "Workspace-scoped read and write."),
    Capability("terminal", "Terminal", True, 2, "Audited command execution with approvals."),
    Capability("voice", "Voice", True, 3, "Speech-to-text and text-to-speech (first slice)."),
    Capability("memory", "Memory", True, 4, "Inspectable episodic and semantic memory."),
    Capability("projects", "Projects", True, 4, "Goals, tasks, notes and project context."),
    Capability("knowledge", "Documents & RAG", False, 5, "PDF/CSV/Markdown ingestion, retrieval."),
    Capability("tutor", "Tutor mode", False, 6, "Socratic teaching with spaced repetition."),
    Capability("study", "Study", False, 6, "Subjects, courses, quizzes and progress."),
    Capability("research", "Research", False, 7, "Web search, source evaluation, citations."),
    Capability("economics", "Economics engine", False, 8, "Formal models from plain-English asks."),
    Capability("game_theory", "Game theory engine", False, 8, "Nash equilibria, mixed strategies."),
    Capability("simulation", "Simulation Lab", False, 9, "Monte Carlo experiments and sweeps."),
    Capability("experiments", "Experiments", False, 9, "Reproducible, seeded, saved runs."),
    Capability("agent_loop", "Autonomous agent loop", False, 10, "Multi-step planning, verifying."),
)

BY_KEY = {c.key: c for c in CAPABILITIES}


def is_available(key: str) -> bool:
    capability = BY_KEY.get(key)
    return bool(capability and capability.available)
