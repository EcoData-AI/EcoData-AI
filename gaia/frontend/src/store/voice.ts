import { create } from 'zustand'
import { voiceApi } from '@/lib/voice'
import { useChatStore } from './chat'

/**
 * Voice's own state machine only covers what voice itself is doing —
 * capturing, transcribing, or speaking. "thinking" and "using a tool" are
 * not duplicated here: they already exist as `useChatStore`'s `sending` and
 * `draft.toolCalls`, which a transcribed message drives exactly the same way
 * a typed one does. The UI composes both stores rather than this one trying
 * to mirror chat state it doesn't own.
 */
export type VoiceState = 'idle' | 'listening' | 'transcribing' | 'speaking' | 'error'

interface VoiceStore {
  state: VoiceState
  error: string | null
  micRecorder: MediaRecorder | null
  startListening: () => Promise<void>
  stopListening: () => void
  speak: (text: string) => Promise<void>
  dismissError: () => void
}

export const useVoiceStore = create<VoiceStore>((set, get) => ({
  state: 'idle',
  error: null,
  micRecorder: null,

  async startListening() {
    const current = get().state
    if (current !== 'idle' && current !== 'error') return
    set({ state: 'listening', error: null })

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      // Covers both "permission denied" and "no microphone present" —
      // getUserMedia doesn't reliably distinguish them across browsers.
      set({ state: 'error', error: 'Microphone access was denied or no microphone is available.' })
      return
    }

    const chunks: BlobPart[] = []
    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(stream)
    } catch {
      stream.getTracks().forEach((track) => track.stop())
      set({ state: 'error', error: 'Recording is not supported in this browser.' })
      return
    }

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop())
      void finishRecording(chunks, recorder.mimeType || 'audio/webm')
    }
    recorder.start()
    set({ micRecorder: recorder })
  },

  stopListening() {
    const { state, micRecorder } = get()
    if (state !== 'listening' || !micRecorder) return
    set({ state: 'transcribing' })
    micRecorder.stop()
  },

  async speak(text: string) {
    set({ state: 'speaking', error: null })
    try {
      const blob = await voiceApi.speak(text)
      await playAudioBlob(blob)
      set((current) => (current.state === 'speaking' ? { state: 'idle' } : {}))
    } catch (err) {
      set({
        state: 'error',
        error: err instanceof Error ? err.message : 'Speech playback failed.',
      })
    }
  },

  dismissError() {
    set({ state: 'idle', error: null })
  },
}))

function playAudioBlob(blob: Blob): Promise<void> {
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  return new Promise((resolve) => {
    const cleanup = () => {
      URL.revokeObjectURL(url)
      resolve()
    }
    audio.onended = cleanup
    audio.onerror = cleanup
    audio.play().catch(cleanup)
  })
}

async function finishRecording(chunks: BlobPart[], mimeType: string): Promise<void> {
  const blob = new Blob(chunks, { type: mimeType })
  if (blob.size === 0) {
    useVoiceStore.setState({ state: 'error', error: 'No audio was recorded.' })
    return
  }

  let text: string
  try {
    const result = await voiceApi.transcribe(blob)
    text = result.text.trim()
  } catch (err) {
    useVoiceStore.setState({
      state: 'error',
      error: err instanceof Error ? err.message : 'Transcription failed.',
    })
    return
  }

  if (!text) {
    useVoiceStore.setState({
      state: 'error',
      error: 'Could not make out any speech in that recording.',
    })
    return
  }

  // From here on, the transcribed text is just a chat message — the exact
  // same `send()` a typed message goes through, tool calls and all. Voice
  // never talks to the model, a provider, or a tool directly.
  useVoiceStore.setState({ state: 'idle' })
  await useChatStore.getState().send(text)

  const messages = useChatStore.getState().messages
  const last = messages[messages.length - 1]
  if (last && last.role === 'assistant' && last.status === 'complete' && last.content.trim()) {
    await useVoiceStore.getState().speak(last.content)
  }
}
