import { create } from 'zustand'
import {
  api,
  ApiError,
  type Conversation,
  type Message,
} from '@/lib/api'
import { streamChat, type StreamErrorPayload } from '@/lib/stream'

/** A message that exists only in the UI while its turn is in flight. */
export interface DraftMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: 'streaming' | 'error'
  error?: StreamErrorPayload
}

interface ChatState {
  conversations: Conversation[]
  activeId: string | null
  messages: Message[]
  draft: DraftMessage | null
  pendingUser: string | null
  searchQuery: string
  loadingConversations: boolean
  loadingMessages: boolean
  sending: boolean
  turnError: StreamErrorPayload | null
  lastTurnStats: {
    model_id?: string
    latency_ms?: number
    input_tokens?: number | null
    output_tokens?: number | null
    cost_usd?: number | null
    context_sources?: string[]
  } | null
  abortController: AbortController | null

  loadConversations: (query?: string) => Promise<void>
  setSearchQuery: (query: string) => void
  selectConversation: (id: string) => Promise<void>
  newConversation: () => Promise<string | null>
  renameConversation: (id: string, title: string) => Promise<void>
  togglePin: (id: string) => Promise<void>
  deleteConversation: (id: string) => Promise<void>
  send: (content: string) => Promise<void>
  stop: () => void
  dismissTurnError: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  activeId: null,
  messages: [],
  draft: null,
  pendingUser: null,
  searchQuery: '',
  loadingConversations: false,
  loadingMessages: false,
  sending: false,
  turnError: null,
  lastTurnStats: null,
  abortController: null,

  async loadConversations(query) {
    set({ loadingConversations: true })
    try {
      const conversations = await api.listConversations(query ?? get().searchQuery)
      set({ conversations })
    } finally {
      set({ loadingConversations: false })
    }
  },

  setSearchQuery(query) {
    set({ searchQuery: query })
  },

  async selectConversation(id) {
    set({ activeId: id, loadingMessages: true, messages: [], turnError: null, draft: null })
    try {
      const detail = await api.getConversation(id)
      // Guard against a slow response for a conversation the user already left.
      if (get().activeId !== id) return
      set({ messages: detail.messages })
    } catch (error) {
      if (get().activeId === id) {
        set({
          turnError: {
            kind: 'load_failed',
            message: error instanceof ApiError ? error.message : 'Could not load that conversation.',
          },
        })
      }
    } finally {
      if (get().activeId === id) set({ loadingMessages: false })
    }
  },

  async newConversation() {
    try {
      const conversation = await api.createConversation()
      set((state) => ({
        conversations: [conversation, ...state.conversations],
        activeId: conversation.id,
        messages: [],
        draft: null,
        turnError: null,
        lastTurnStats: null,
      }))
      return conversation.id
    } catch (error) {
      set({
        turnError: {
          kind: 'create_failed',
          message:
            error instanceof ApiError ? error.message : 'Could not start a new conversation.',
        },
      })
      return null
    }
  },

  async renameConversation(id, title) {
    const trimmed = title.trim()
    if (!trimmed) return
    const updated = await api.updateConversation(id, { title: trimmed })
    set((state) => ({
      conversations: state.conversations.map((c) => (c.id === id ? { ...c, ...updated } : c)),
    }))
  },

  async togglePin(id) {
    const current = get().conversations.find((c) => c.id === id)
    if (!current) return
    const updated = await api.updateConversation(id, { pinned: !current.pinned })
    set((state) => ({
      conversations: state.conversations
        .map((c) => (c.id === id ? { ...c, ...updated } : c))
        .sort((a, b) => Number(b.pinned) - Number(a.pinned)),
    }))
  },

  async deleteConversation(id) {
    await api.deleteConversation(id)
    set((state) => {
      const conversations = state.conversations.filter((c) => c.id !== id)
      const wasActive = state.activeId === id
      return {
        conversations,
        activeId: wasActive ? (conversations[0]?.id ?? null) : state.activeId,
        messages: wasActive ? [] : state.messages,
      }
    })
    const next = get().activeId
    if (next && get().messages.length === 0) await get().selectConversation(next)
  },

  async send(content) {
    const trimmed = content.trim()
    if (!trimmed || get().sending) return

    let conversationId = get().activeId
    if (!conversationId) {
      conversationId = await get().newConversation()
      if (!conversationId) return
    }

    const controller = new AbortController()
    set({
      sending: true,
      turnError: null,
      pendingUser: trimmed,
      draft: null,
      abortController: controller,
    })

    try {
      await streamChat(
        { conversationId, content: trimmed, signal: controller.signal },
        {
          onUserMessage: ({ title }) => {
            set((state) => ({
              conversations: state.conversations.map((c) =>
                c.id === conversationId ? { ...c, title } : c,
              ),
            }))
          },
          onStart: ({ message_id, provider_id, model_id, context }) => {
            set({
              draft: { id: message_id, role: 'assistant', content: '', status: 'streaming' },
              lastTurnStats: {
                model_id: `${provider_id}/${model_id}`,
                context_sources: context.sources,
              },
            })
          },
          onDelta: (text) => {
            set((state) =>
              state.draft ? { draft: { ...state.draft, content: state.draft.content + text } } : {},
            )
          },
          onError: (error) => {
            set({ turnError: error })
          },
          onDone: (data) => {
            set((state) => ({
              lastTurnStats: {
                ...state.lastTurnStats,
                latency_ms: data.latency_ms,
                input_tokens: data.input_tokens,
                output_tokens: data.output_tokens,
                cost_usd: data.cost_usd,
              },
            }))
          },
        },
      )
    } catch (error) {
      set({
        turnError: {
          kind: 'transport',
          message:
            error instanceof ApiError
              ? error.message
              : 'The connection to the GAIA backend was lost.',
          remedy: 'Check that the backend is running, then try again.',
        },
      })
    } finally {
      set({ sending: false, abortController: null, pendingUser: null, draft: null })
      // Re-read from the database: it is the source of truth for what was
      // actually persisted, including a partial reply from an aborted turn.
      if (get().activeId === conversationId) {
        try {
          const detail = await api.getConversation(conversationId)
          set({ messages: detail.messages })
        } catch {
          /* leave the optimistic view in place */
        }
      }
      await get().loadConversations()
    }
  },

  stop() {
    get().abortController?.abort()
  },

  dismissTurnError() {
    set({ turnError: null })
  },
}))
