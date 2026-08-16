import { useEffect, useRef } from 'react'
import type { Message } from '@/lib/api'
import type { DraftMessage } from '@/store/chat'
import { Markdown } from './Markdown'
import { ToolCallCard } from './ToolCallCard'

interface Props {
  messages: Message[]
  draft: DraftMessage | null
  pendingUser: string | null
  sending: boolean
  onResolveToolConfirmation?: (callId: string, approved: boolean) => void
}

function formatTokens(input: number | null, output: number | null): string | null {
  if (input == null && output == null) return null
  return `${input ?? '—'} in / ${output ?? '—'} out`
}

function formatCost(cost: number | null): string | null {
  if (cost == null) return null
  if (cost === 0) return 'free (local)'
  // Sub-cent costs are the common case; show enough digits to be meaningful.
  return cost < 0.01 ? `$${cost.toFixed(5)}` : `$${cost.toFixed(4)}`
}

function StatusChip({ status }: { status: Message['status'] }) {
  if (status === 'complete') return null
  const label =
    status === 'error' ? 'failed' : status === 'stopped' ? 'incomplete' : 'streaming'
  return <span className={`msg__status msg__status--${status}`}>{label}</span>
}

export function MessageList({
  messages,
  draft,
  pendingUser,
  sending,
  onResolveToolConfirmation,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null)
  const scrollerRef = useRef<HTMLDivElement>(null)
  const pinnedToBottom = useRef(true)

  // Follow the stream, but stop following the moment the user scrolls up to
  // read something — yanking the viewport back is the classic chat-UI sin.
  useEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller) return
    const onScroll = () => {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight
      pinnedToBottom.current = distance < 80
    }
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => scroller.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (pinnedToBottom.current) {
      endRef.current?.scrollIntoView({ block: 'end' })
    }
  }, [messages, draft?.content, pendingUser])

  return (
    <div className="thread" ref={scrollerRef}>
      <div className="thread__inner">
        {messages.map((message) => (
          <article key={message.id} className={`msg msg--${message.role}`}>
            <header className="msg__role">
              <span>{message.role === 'user' ? 'You' : 'GAIA'}</span>
              <StatusChip status={message.status} />
            </header>
            {message.role === 'assistant' && message.extra?.tool_calls?.length ? (
              <div className="tool-calls">
                {message.extra.tool_calls.map((call) => (
                  <ToolCallCard key={call.call_id} call={call} />
                ))}
              </div>
            ) : null}
            <div className="msg__body">
              {message.role === 'user' ? (
                message.content
              ) : (
                <Markdown content={message.content || '_(no content)_'} />
              )}
            </div>
            {message.role === 'assistant' && message.status !== 'complete' && message.error && (
              <div className="msg__footer" style={{ color: 'var(--danger)' }}>
                {message.error}
              </div>
            )}
            {message.role === 'assistant' && message.status === 'complete' && (
              <footer className="msg__footer">
                {message.model_id && <span>{message.model_id}</span>}
                {formatTokens(message.input_tokens, message.output_tokens) && (
                  <span>{formatTokens(message.input_tokens, message.output_tokens)}</span>
                )}
                {formatCost(message.cost_usd) && <span>{formatCost(message.cost_usd)}</span>}
                {message.latency_ms != null && <span>{(message.latency_ms / 1000).toFixed(1)}s</span>}
              </footer>
            )}
          </article>
        ))}

        {pendingUser && (
          <article className="msg msg--user">
            <header className="msg__role">
              <span>You</span>
            </header>
            <div className="msg__body">{pendingUser}</div>
          </article>
        )}

        {sending && (
          <article className="msg msg--assistant">
            <header className="msg__role">
              <span>GAIA</span>
              <span className="msg__status">thinking</span>
            </header>
            {draft?.toolCalls?.length ? (
              <div className="tool-calls">
                {draft.toolCalls.map((call) => (
                  <ToolCallCard key={call.call_id} call={call} onResolve={onResolveToolConfirmation} />
                ))}
              </div>
            ) : null}
            <div className="msg__body">
              {draft?.content ? (
                <>
                  <Markdown content={draft.content} />
                  <span className="cursor" aria-hidden="true" />
                </>
              ) : (
                <span className="cursor" aria-hidden="true" />
              )}
            </div>
          </article>
        )}

        <div ref={endRef} />
      </div>
    </div>
  )
}
