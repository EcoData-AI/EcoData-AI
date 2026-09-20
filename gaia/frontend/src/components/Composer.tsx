import { useEffect, useRef, useState } from 'react'
import { useVoiceStore, type VoiceState } from '@/store/voice'

interface Props {
  onSend: (text: string) => void
  onStop: () => void
  sending: boolean
  disabled?: boolean
  disabledReason?: string
}

function voiceStatusLabel(state: VoiceState): string | null {
  switch (state) {
    case 'listening':
      return 'Listening…'
    case 'transcribing':
      return 'Transcribing…'
    case 'speaking':
      return 'Speaking…'
    default:
      return null
  }
}

function micTitle(state: VoiceState, disabled: boolean | undefined): string {
  if (disabled) return 'Configure a model provider in Settings first'
  switch (state) {
    case 'listening':
      return 'Stop recording'
    case 'transcribing':
      return 'Transcribing your recording…'
    case 'speaking':
      return 'GAIA is speaking'
    case 'error':
      return 'Voice error — click to dismiss'
    default:
      return 'Start voice input'
  }
}

export function Composer({ onSend, onStop, sending, disabled, disabledReason }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const voice = useVoiceStore()

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

  const micBusy = voice.state === 'transcribing' || voice.state === 'speaking'
  const statusLabel = voiceStatusLabel(voice.state)

  const onMicClick = () => {
    if (voice.state === 'listening') voice.stopListening()
    else if (voice.state === 'error') voice.dismissError()
    else if (voice.state === 'idle') void voice.startListening()
  }

  return (
    <div className="composer">
      <div className="composer__inner">
        {(statusLabel || voice.error) && (
          <div className={`voice-status voice-status--${voice.state}`} role="status">
            {voice.error ?? statusLabel}
          </div>
        )}
        <div className="composer__box">
          <button
            type="button"
            className="btn btn--ghost composer__mic"
            data-voice-state={voice.state}
            aria-label={micTitle(voice.state, disabled)}
            title={micTitle(voice.state, disabled)}
            disabled={disabled || sending || micBusy}
            onClick={onMicClick}
          >
            ●
          </button>
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
          <span>Enter to send · Shift+Enter for a new line · hold the mic for voice</span>
          {disabled && disabledReason && (
            <span style={{ color: 'var(--warn)' }}>{disabledReason}</span>
          )}
        </div>
      </div>
    </div>
  )
}
