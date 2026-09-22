"""Conversation summarisation — the pure `summarize_if_needed` core.

`summarize_in_background`'s own DB/provider wiring is exercised indirectly by
`test_chat_tools.py`'s ordinary chat-turn tests (it is fired as a detached
task and must never raise into them); this file is about the summarisation
logic itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from gaia.llm.base import (
    HealthState,
    LLMProvider,
    ModelInfo,
    ProviderConfig,
    ProviderHealth,
    StreamEvent,
)
from gaia.llm.mock_provider import MOCK_MODEL_ID, MockProvider
from gaia.services import conversation_service, summarization_service


def _mock_provider() -> MockProvider:
    return MockProvider(ProviderConfig())


class _FailingProvider(LLMProvider):
    id = "failing"
    display_name = "Failing (test only)"
    requires_api_key = False

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(HealthState.OK)

    async def stream_chat(
        self, messages, *, model, system=None, temperature=0.7, max_tokens=4096, tools=None
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="error", error={"message": "boom"})


async def test_summarize_if_needed_does_nothing_without_a_boundary(session):
    conversation = conversation_service.create_conversation(session)
    await summarization_service.summarize_if_needed(
        session, conversation, [], None, _mock_provider(), MOCK_MODEL_ID
    )
    assert conversation.summary is None


async def test_summarize_if_needed_does_nothing_when_nothing_is_pending(session):
    conversation = conversation_service.create_conversation(session)
    m1 = conversation_service.add_message(session, conversation, role="user", content="hi")
    m2 = conversation_service.add_message(session, conversation, role="assistant", content="hey")
    conversation.summarized_through = m1.sequence
    session.commit()

    # Nothing strictly between summarized_through and oldest_kept_sequence.
    await summarization_service.summarize_if_needed(
        session, conversation, [m1, m2], m2.sequence, _mock_provider(), MOCK_MODEL_ID
    )
    assert conversation.summary is None
    assert conversation.summarized_through == m1.sequence


async def test_summarize_if_needed_folds_pending_messages_and_advances_boundary(session):
    conversation = conversation_service.create_conversation(session)
    m1 = conversation_service.add_message(session, conversation, role="user", content="I like tea")
    m2 = conversation_service.add_message(session, conversation, role="assistant", content="Noted.")
    m3 = conversation_service.add_message(
        session, conversation, role="user", content="latest message"
    )

    await summarization_service.summarize_if_needed(
        session, conversation, [m1, m2, m3], m3.sequence, _mock_provider(), MOCK_MODEL_ID
    )

    assert conversation.summary
    assert conversation.summarized_through == m2.sequence


async def test_summarize_if_needed_leaves_boundary_untouched_on_provider_error(session):
    conversation = conversation_service.create_conversation(session)
    m1 = conversation_service.add_message(session, conversation, role="user", content="I like tea")
    m2 = conversation_service.add_message(session, conversation, role="user", content="latest")

    await summarization_service.summarize_if_needed(
        session,
        conversation,
        [m1, m2],
        m2.sequence,
        _FailingProvider(ProviderConfig()),
        "any-model",
    )

    assert conversation.summary is None
    assert conversation.summarized_through == 0


async def test_summarize_in_background_swallows_a_missing_conversation(session):
    # `session` isolates this to a throwaway `gaia_env` — `summarize_in_background`
    # opens its own session_scope() and must never touch a developer's real data.
    # Must also never raise: it runs detached, with nothing to report a failure to.
    await summarization_service.summarize_in_background(
        conversation_id="no-such-id",
        oldest_kept_sequence=1,
        provider_id="mock",
        model_id=MOCK_MODEL_ID,
    )
