"""Context Builder — decides what actually gets sent to the model.

The rule from the product spec is: never send the whole database to the LLM,
so the job is budgeting the conversation, memories, project context and
retrieved document passages against the model's context window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from gaia.core.persona import build_system_prompt
from gaia.db.base import utcnow
from gaia.db.models import DocumentChunk, Memory, Message, Project, ProjectTask, StudyPlan
from gaia.llm.base import ChatMessage

if TYPE_CHECKING:
    from gaia.services.study_service import PlanStatus, TopicStatus

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


TUTOR_RULES = """\
How to teach in this session:
- Teach, don't just answer. Lead with questions that make the user reason, and build on what \
they say. When a concept is genuinely new, explain it briefly and concretely, then check \
understanding with a question.
- Ask one question at a time, then wait for the answer.
- While the user is working on a question or exercise you set, do not give the answer or the \
full solution. If they are stuck, give the smallest hint that gets them moving. Reveal the \
answer only if they explicitly ask for it or say they give up — then explain it and follow up \
with a similar question to check it landed.
- When the user answers a question or exercise that tests a topic, grade it honestly and call \
record_study_progress with that topic's exact title and a 0-5 score. Never record a score for \
something you only explained, or for an answer they did not give.
- Adapt to the scores: after a 0-2, explain the topic a different way and ask an easier \
question; after repeated 5s, move faster and raise the difficulty. Vary the format: short \
questions, worked problems, small quizzes.
- Move on once the focus topic is mastered (80%+). Tell the user where they are in the course \
when they move to a new topic or module.
"""


def _topic_line(topic: TopicStatus, now: datetime) -> str:
    if not topic.started:
        return f"- {topic.topic} — not started"
    detail = f"{round(topic.mastery * 100)}% after {topic.attempts} attempt(s)"
    if topic.mastered:
        detail = "mastered, " + detail
    if topic.due:
        detail += ", due for review now"
    elif topic.next_review_at is not None:
        days = max(0, (topic.next_review_at - now).days)
        detail += ", review " + ("tomorrow" if days <= 1 else f"in {days} days")
    if topic.last_note:
        detail += f" — last note: {topic.last_note}"
    return f"- {topic.topic} — {detail}"


def _tutor_section(plan: StudyPlan, status: PlanStatus, now: datetime) -> str:
    lines = [
        f"\n## Tutor mode — course: {plan.subject}",
        "This conversation is a tutoring session for one of the user's courses, created on "
        "their request. You are their tutor here.",
    ]
    if plan.goal:
        lines.append(f"Their goal: {plan.goal}")
    lines.append(f"Level: {plan.level}" if plan.level else "Level: not assessed yet.")
    lines.append(f"Progress: {status.mastered_count} of {status.topic_count} topics mastered.")
    lines.append("\nCourse outline, in teaching order, with progress so far:")
    module = None
    for topic in status.topics:
        if topic.module != module:
            module = topic.module
            lines.append(f"### {module}")
        lines.append(_topic_line(topic, now))

    lines.append("\nWhat to do now:")
    if not plan.level:
        lines.append(
            "- Start with a short diagnostic: two or three quick questions spanning the course, "
            "easy to harder, one at a time. Then call set_study_level, tell the user briefly "
            "what you found, and begin teaching at the right point. Answers that test a "
            "specific topic can be recorded against it."
        )
    if status.due:
        lines.append(
            "- These topics are due for spaced-repetition review: "
            + "; ".join(t.topic for t in status.due)
            + ". Open with one quick review question on each before new material, and record "
            "each answer."
        )
    current = status.current
    if current is None:
        lines.append(
            "- Every topic is mastered. Offer a cumulative quiz, harder problems, or a "
            "follow-on course."
        )
    else:
        lines.append(f"- Focus topic: {current.topic} (module: {current.module}).")
    return "\n".join(lines) + "\n\n" + TUTOR_RULES


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
    study_plan: StudyPlan | None = None,
    study_status: PlanStatus | None = None,
    now: datetime | None = None,
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

    if study_plan is not None and study_status is not None:
        system += _tutor_section(study_plan, study_status, now or utcnow())
        sources.append("tutor")

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
        system += f"\n## Summary of earlier messages in this conversation\n{summary.strip()}\n"
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
