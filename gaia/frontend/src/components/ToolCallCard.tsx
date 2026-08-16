import type { ToolCallLogEntry } from '@/lib/api'
import type { DraftToolCall } from '@/store/chat'

/** Either a live in-flight call or the persisted record of a finished one —
 * `DraftToolCall` carries a `status`, a completed `ToolCallLogEntry` does not. */
type ToolCallView = DraftToolCall | (ToolCallLogEntry & { status?: undefined })

interface Props {
  call: ToolCallView
  onResolve?: (callId: string, approved: boolean) => void
}

function summarize(call: ToolCallView): string {
  const display = call.display
  if (display && typeof display.expression === 'string' && typeof display.result === 'string') {
    return `${display.expression} = ${display.result}`
  }
  try {
    return JSON.stringify(call.arguments)
  } catch {
    return String(call.arguments)
  }
}

export function ToolCallCard({ call, onResolve }: Props) {
  // A persisted log entry has no `status` field at all — treat it as done.
  const status = call.status ?? 'done'
  const failed = status === 'done' && call.ok === false

  return (
    <div className="tool-call">
      <div className="tool-call__header">
        <span className="tag tag--muted">tool</span>
        <span className="tool-call__name">{call.tool}</span>
        {status === 'running' && <span className="msg__status">running</span>}
        {status === 'awaiting_confirmation' && <span className="tag tag--warn">needs approval</span>}
        {status === 'done' && (failed ? <span className="tag tag--error">failed</span> : <span className="tag tag--ok">done</span>)}
      </div>
      <div className="tool-call__body mono">{summarize(call)}</div>
      {failed && call.error && (
        <div className="tool-call__body" style={{ color: 'var(--danger)' }}>
          {call.error}
        </div>
      )}
      {status === 'awaiting_confirmation' && onResolve && (
        <div className="tool-call__actions">
          <button className="btn btn--primary" onClick={() => onResolve(call.call_id, true)}>
            Approve
          </button>
          <button className="btn" onClick={() => onResolve(call.call_id, false)}>
            Deny
          </button>
        </div>
      )}
    </div>
  )
}
