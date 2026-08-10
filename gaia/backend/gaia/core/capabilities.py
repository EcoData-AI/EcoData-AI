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
    Capability("tools", "Tool system", False, 2, "Calculator, Python, filesystem, terminal."),
    Capability("python", "Python sandbox", False, 2, "Sandboxed execution with NumPy/SciPy/SymPy."),
    Capability("filesystem", "Filesystem access", False, 2, "Workspace-scoped read and write."),
    Capability("terminal", "Terminal", False, 2, "Audited command execution with approvals."),
    Capability("memory", "Memory", False, 3, "Inspectable episodic and semantic memory."),
    Capability("projects", "Projects", False, 3, "Goals, tasks, notes and project context."),
    Capability("knowledge", "Documents & RAG", False, 4, "PDF/CSV/Markdown ingestion, retrieval."),
    Capability("tutor", "Tutor mode", False, 5, "Socratic teaching with spaced repetition."),
    Capability("study", "Study", False, 5, "Subjects, courses, quizzes and progress."),
    Capability("research", "Research", False, 6, "Web search, source evaluation, citations."),
    Capability("economics", "Economics engine", False, 7, "Formal models from plain-English asks."),
    Capability("game_theory", "Game theory engine", False, 7, "Nash equilibria, mixed strategies."),
    Capability("simulation", "Simulation Lab", False, 8, "Monte Carlo experiments and sweeps."),
    Capability("experiments", "Experiments", False, 8, "Reproducible, seeded, saved runs."),
    Capability("voice", "Voice", False, 9, "Speech-to-text and text-to-speech."),
    Capability("agent_loop", "Autonomous agent loop", False, 10, "Multi-step planning, verifying."),
)

BY_KEY = {c.key: c for c in CAPABILITIES}


def is_available(key: str) -> bool:
    capability = BY_KEY.get(key)
    return bool(capability and capability.available)
