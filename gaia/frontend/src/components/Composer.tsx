import { useEffect, useRef, useState } from 'react'

interface Props {
  onSend: (text: string) => void
  onStop: () => void
  sending: boolean
  disabled?: boolean
  disabledReason?: string
}

export function Composer({ onSend, onStop, sending, disabled, disabledReason }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Grow with the content up to the CSS max-height, then scroll.
  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${textarea.scrollHeight}px`
  }, [value])

  useEffect(() => {
    if (!sending) textareaRef.current?.focus()
  }, [sending])

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || sending || disabled) return
    onSend(trimmed)
    setValue('')
  }

  return (
    <div className="composer">
      <div className="composer__inner">
        <div className="composer__box">
          <textarea
            ref={textareaRef}
            className="composer__textarea"
            rows={1}
            value={value}
            disabled={disabled}
            placeholder={disabled ? (disabledReason ?? 'Unavailable') : 'Message GAIA…'}
            aria-label="Message GAIA"
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends; Shift+Enter inserts a newline.
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                submit()
              }
            }}
          />
          {sending ? (
            <button className="btn" type="button" onClick={onStop}>
              Stop
            </button>
          ) : (
            <button
              className="btn btn--primary"
              type="button"
              onClick={submit}
              disabled={!value.trim() || disabled}
            >
              Send
            </button>
          )}
        </div>
        <div className="composer__hint">
          <span>Enter to send · Shift+Enter for a new line</span>
          {disabled && disabledReason && (
            <span style={{ color: 'var(--warn)' }}>{disabledReason}</span>
          )}
        </div>
      </div>
    </div>
  )
}
