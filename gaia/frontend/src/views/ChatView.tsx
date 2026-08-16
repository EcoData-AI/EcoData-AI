import { useEffect } from 'react'
import { Composer } from '@/components/Composer'
import { MessageList } from '@/components/MessageList'
import { useChatStore } from '@/store/chat'

interface Props {
  providerReady: boolean
  providerHint: string
  onOpenSettings: () => void
}

export function ChatView({ providerReady, providerHint, onOpenSettings }: Props) {
  const {
    conversations,
    activeId,
    messages,
    draft,
    pendingUser,
    sending,
    loadingMessages,
    turnError,
    lastTurnStats,
    send,
    stop,
    dismissTurnError,
    newConversation,
    resolveToolConfirmation,
  } = useChatStore()

  const active = conversations.find((c) => c.id === activeId)

  // Keyboard shortcut for a new conversation, matching the platform convention.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        void newConversation()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [newConversation])

  const isEmpty = !activeId || (messages.length === 0 && !sending && !loadingMessages)

  return (
    <>
      <header className="topbar">
        <div className="topbar__title">{active?.title ?? 'GAIA'}</div>
        <div className="topbar__meta">
          {lastTurnStats?.model_id && <span>{lastTurnStats.model_id}</span>}
          {sending && <span>streaming…</span>}
        </div>
      </header>

      {isEmpty ? (
        <div className="thread">
          <div className="thread__inner">
            {!providerReady && (
              <div className="notice notice--warn">
                <div className="notice__title">No model provider is configured</div>
                <div className="notice__body">{providerHint}</div>
                <div className="notice__actions">
                  <button className="btn btn--primary" onClick={onOpenSettings}>
                    Open Settings
                  </button>
                </div>
              </div>
            )}
            <div className="empty">
              <h2>Start a conversation</h2>
              <p>
                GAIA is a local-first assistant. Your conversations are stored on this machine,
                not in the cloud.
              </p>
              <p style={{ color: 'var(--text-faint)', fontSize: 13 }}>
                This is Milestone 1: chat, history and model providers. Tools, memory, documents
                and voice are not built yet and GAIA will say so rather than pretend.
              </p>
            </div>
          </div>
        </div>
      ) : (
        <MessageList
          messages={messages}
          draft={draft}
          pendingUser={pendingUser}
          sending={sending}
          onResolveToolConfirmation={(callId, approved) =>
            void resolveToolConfirmation(callId, approved)
          }
        />
      )}

      {turnError && (
        <div style={{ padding: '0 24px' }}>
          <div className="composer__inner">
            <div className="notice notice--error">
              <div className="notice__title">{errorTitle(turnError.kind)}</div>
              <div className="notice__body">
                {turnError.message}
                {turnError.remedy && (
                  <>
                    <br />
                    {turnError.remedy}
                  </>
                )}
              </div>
              <div className="notice__actions">
                {needsSettings(turnError.kind) && (
                  <button className="btn btn--primary" onClick={onOpenSettings}>
                    Open Settings
                  </button>
                )}
                <button className="btn" onClick={dismissTurnError}>
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <Composer
        onSend={(text) => void send(text)}
        onStop={stop}
        sending={sending}
        disabled={!providerReady}
        disabledReason={!providerReady ? 'Configure a model provider in Settings first' : undefined}
      />
    </>
  )
}

function errorTitle(kind: string): string {
  switch (kind) {
    case 'not_configured':
      return 'No model is configured'
    case 'auth_error':
      return 'The provider rejected your API key'
    case 'rate_limited':
      return 'Rate limit reached'
    case 'refused':
      return 'The model declined this request'
    case 'unavailable':
    case 'transport':
      return 'Could not reach the model'
    default:
      return "GAIA couldn't complete that turn"
  }
}

function needsSettings(kind: string): boolean {
  return kind === 'not_configured' || kind === 'auth_error'
}
