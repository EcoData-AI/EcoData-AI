/**
 * Typed client for GAIA's voice endpoints.
 *
 * Deliberately outside `stream.ts`/the chat SSE contract: STT runs before a
 * normal `send()` call (the transcribed text is indistinguishable from
 * typing once it reaches the chat store), and TTS runs after one, on the
 * already-persisted final assistant text. Neither call is part of a chat
 * turn — see docs/ARCHITECTURE.md, "Voice".
 */

import { apiBase, ApiError } from './api'

export interface TranscribeResult {
  text: string
  language: string | null
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) return body.detail[0]?.msg ?? fallback
  } catch {
    /* keep the fallback */
  }
  return fallback
}

export const voiceApi = {
  /** Upload a recorded clip, get back the transcribed text. */
  async transcribe(blob: Blob): Promise<TranscribeResult> {
    const form = new FormData()
    form.append('file', blob, 'recording.audio')

    let response: Response
    try {
      response = await fetch(`${apiBase()}/api/voice/transcribe`, { method: 'POST', body: form })
    } catch {
      throw new ApiError('Could not reach the GAIA backend. Is it running?', 0)
    }
    if (!response.ok) {
      throw new ApiError(
        await readErrorDetail(response, `Transcription failed (${response.status}).`),
        response.status,
      )
    }
    return (await response.json()) as TranscribeResult
  },

  /** Synthesize `text` to speech, get back playable audio. */
  async speak(text: string): Promise<Blob> {
    let response: Response
    try {
      response = await fetch(`${apiBase()}/api/voice/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
    } catch {
      throw new ApiError('Could not reach the GAIA backend. Is it running?', 0)
    }
    if (!response.ok) {
      throw new ApiError(
        await readErrorDetail(response, `Speech synthesis failed (${response.status}).`),
        response.status,
      )
    }
    return await response.blob()
  },
}
