import type { ToolCallLogEntry } from '@/lib/api'
import type { DraftToolCall } from '@/store/chat'

type ToolCallView = DraftToolCall | (ToolCallLogEntry & { status?: undefined })

interface Props {
  call: ToolCallView
  onResolve?: (callId: string, approved: boolean) => void
}

const PREVIEW_CHAR_LIMIT = 500
const LISTING_ROW_LIMIT = 20

type DisplayShape = Record<string, unknown>

function renderArguments(call: ToolCallView) {
  let text: string
  try {
    text = JSON.stringify(call.arguments)
  } catch {
    text = String(call.arguments)
  }
  return <div className="tool-call__body mono">{text}</div>
}

function renderCalculator(display: DisplayShape) {
  if (typeof display.expression !== 'string' || typeof display.result !== 'string') return null
  return (
    <div className="tool-call__body mono">
      {display.expression} = {display.result}
    </div>
  )
}

function renderDirectoryListing(display: DisplayShape) {
  const entries = Array.isArray(display.entries)
    ? (display.entries as Array<{ name: string; type: string; size: number | null }>)
    : []
  const shown = entries.slice(0, LISTING_ROW_LIMIT)
  return (
    <div className="tool-call__body">
      <div className="mono tool-call__path">{String(display.path ?? '')}</div>
      <ul className="tool-call__listing">
        {shown.map((entry) => (
          <li key={entry.name}>
            <span aria-hidden="true">{entry.type === 'dir' ? '📁' : '📄'}</span> {entry.name}
            {entry.size != null && <span className="tool-call__size"> — {entry.size} B</span>}
          </li>
        ))}
      </ul>
      {entries.length > shown.length && (
        <div className="tool-call__body">…and {entries.length - shown.length} more entries</div>
      )}
    </div>
  )
}

function renderFileContent(display: DisplayShape, content: string | undefined) {
  const text = content ?? ''
  const truncated = text.length > PREVIEW_CHAR_LIMIT
  const preview = truncated ? text.slice(0, PREVIEW_CHAR_LIMIT) + '…' : text
  return (
    <div className="tool-call__body">
      <div className="mono tool-call__path">
        {String(display.path ?? '')} — {String(display.size ?? '?')} bytes
      </div>
      <pre className="tool-call__preview">{preview || '(empty file)'}</pre>
    </div>
  )
}

function renderFilesystemRead(display: DisplayShape, content: string | undefined) {
  if (display.kind === 'directory') return renderDirectoryListing(display)
  if (display.kind === 'file') return renderFileContent(display, content)
  return null
}

function renderFilesystemWrite(display: DisplayShape) {
  return (
    <div className="tool-call__body mono">
      {String(display.mode ?? 'overwrite')} → {String(display.path ?? '')} (
      {String(display.bytes_written ?? 0)} bytes)
    </div>
  )
}

/** Rich, tool-specific rendering of a *successful* result. Falls back to the
 * raw arguments (via the caller) for anything not special-cased here — new
 * tools stay legible without needing frontend changes, this just makes the
 * common ones nicer. */
function renderResult(call: ToolCallView) {
  const display = call.display as DisplayShape | null | undefined
  if (!display) return null
  if (call.tool === 'calculator') return renderCalculator(display)
  if (call.tool === 'filesystem_read') return renderFilesystemRead(display, call.content)
  if (call.tool === 'filesystem_write') return renderFilesystemWrite(display)
  return null
}

export function ToolCallCard({ call, onResolve }: Props) {
  const status = call.status ?? 'done'
  const hasResult = status === 'done'
  const failed = hasResult && call.ok === false
  const body = hasResult && !failed ? renderResult(call) : null

  return (
    <div className="tool-call">
      <div className="tool-call__header">
        <span className="tag tag--muted">tool</span>
        <span className="tool-call__name">{call.tool}</span>
        {status === 'running' && <span className="msg__status">running</span>}
        {status === 'awaiting_confirmation' && <span className="tag tag--warn">needs approval</span>}
        {status === 'done' &&
          (failed ? <span className="tag tag--error">failed</span> : <span className="tag tag--ok">done</span>)}
      </div>
      {body ?? renderArguments(call)}
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
