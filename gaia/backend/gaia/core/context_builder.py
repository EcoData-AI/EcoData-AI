"""Context Builder — decides what actually gets sent to the model.

The rule from the product spec is: never send the whole database to the LLM,
so the job is budgeting the conversation, memories, project context and
retrieved document passages against the model's context window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gaia.core.persona import build_system_prompt
from gaia.db.models import DocumentChunk, Memory, Message, Project, ProjectTask
from gaia.llm.base import ChatMessage

#: Rough characters-per-token used for budgeting. Deliberately conservative
#: (real ratios run ~3.5–4.5 for English prose, higher for code). This is a
#: budgeting heuristic, not a token count — providers do the real counting.
CHARS_PER_TOKEN = 3.5

#: Share of the context window we are willing to fill with history, leaving room
#: for the system prompt, the model's reasoning, and its reply.
HISTORY_BUDGET_RATIO = 0.5

#: Used when a provider does not report a context window (0 = unknown).
FALLBACK_CONTEXT_WINDOW = 32_000


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def _citation_label(chunk: DocumentChunk) -> str:
    title = chunk.document.title
    return f"{title}, p.{chunk.page}" if chunk.page is not None else title


@dataclass(slots=True)
class BuiltContext:
    system: str
    messages: list[ChatMessage]
    #: Messages dropped because they did not fit, oldest first.
    dropped_message_count: int = 0
    estimated_input_tokens: int = 0
    #: Names of the context sources actually used, for the observability panel.
    sources: list[str] = field(default_factory=list)
    #: `sequence` of the oldest message actually kept this turn; `None` if
    #: nothing was dropped. Lets `summarization_service` know exactly which
    #: messages are now at risk of falling out of context permanently.
    oldest_kept_sequence: int | None = None


def build_context(
    *,
    history: list[Message],
    context_window: int,
    custom_instructions: str | None = None,
    conversation_system_prompt: str | None = None,
    summary: str | None = None,
    memories: list[Memory] | None = None,
    project: Project | None = None,
    project_tasks: list[ProjectTask] | None = None,
    retrieved_chunks: list[DocumentChunk] | None = None,
) -> BuiltContext:
    """Assemble the request payload for one turn.

    `history` must be in chronological order and must already include the new
    user message. Messages that failed or are still streaming are skipped —
    sending a half-written assistant turn back to the model corrupts the thread.
    """
    system = build_system_prompt(custom_instructions)
    if conversation_system_prompt and conversation_system_prompt.strip():
        system += f"\n## Instructions for this conversation\n{conversation_system_prompt.strip()}\n"

    sources = ["persona"]
    if custom_instructions:
        sources.append("custom_instructions")
    if conversation_system_prompt:
        sources.append("conversation_instructions")

    if project is not None:
        parts = [f"Name: {project.name}"]
        if project.description and project.description.strip():
            parts.append(f"Description: {project.description.strip()}")
        if project.goals and project.goals.strip():
            parts.append(f"Goals: {project.goals.strip()}")
        if project_tasks:
            task_lines = "\n".join(f"- {t.title}" for t in project_tasks)
            parts.append(f"Open tasks:\n{task_lines}")
        system += "\n## Current project\n" + "\n".join(parts) + "\n"
        sources.append("project")

    if retrieved_chunks:
        passages = "\n\n".join(f"[{_citation_label(c)}]\n{c.content}" for c in retrieved_chunks)
        system += (
            "\n## Retrieved passages\n"
            "The following passages were retrieved from the user's own documents because they "
            "matched this turn's message. When you use one, cite it in your reply using its "
            "exact label in brackets, e.g. [Title, p.3]. Do not cite a passage you did not "
            "actually use, and do not invent a citation for something not shown here.\n\n"
            f"{passages}\n"
        )
        sources.append("knowledge")

    if memories:
        lines = "\n".join(f"- ({m.kind}) {m.content}" for m in memories)
        system += f"\n## Things to remember about the user\n{lines}\n"
        sources.append("memory")

    if summary and summary.strip():
        system += (
            "\n## Summary of earlier messages in this conversation\n"
            f"{summary.strip()}\n"
        )
        sources.append("conversation_summary")

    window = context_window if context_window > 0 else FALLBACK_CONTEXT_WINDOW
    system_tokens = estimate_tokens(system)
    budget = max(1_000, int(window * HISTORY_BUDGET_RATIO) - system_tokens)

    usable = [
        m
        for m in history
        if m.role in ("user", "assistant") and m.status == "complete" and m.content.strip()
    ]

    # Walk backwards so the most recent turns always survive, then restore order.
    selected: list[Message] = []
    used = 0
    for message in reversed(usable):
        cost = estimate_tokens(message.content)
        if selected and used + cost > budget:
            break
        selected.append(message)
        used += cost
    selected.reverse()

    if selected:
        sources.append("conversation_history")

    # An assistant message must never lead the thread: providers require the
    # first turn to be from the user.
    while selected and selected[0].role != "user":
        selected.pop(0)

    dropped_count = len(usable) - len(selected)
    return BuiltContext(
        system=system,
        messages=[ChatMessage(role=m.role, content=m.content) for m in selected],  # type: ignore[arg-type]
        dropped_message_count=dropped_count,
        estimated_input_tokens=system_tokens + used,
        sources=sources,
        oldest_kept_sequence=selected[0].sequence if selected and dropped_count > 0 else None,
    )
