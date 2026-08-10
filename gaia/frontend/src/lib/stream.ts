/**
 * Server-Sent Events over `fetch`.
 *
 * `EventSource` cannot issue a POST, and the chat turn needs a request body, so
 * the SSE framing is parsed by hand off the response stream. A partial frame at
 * a chunk boundary is common, so the buffer is only consumed up to the last
 * complete `\n\n`.
 */

import { apiBase, ApiError } from './api'

export interface StreamErrorPayload {
  kind: string
  message: string
  remedy?: string | null
  status?: number | null
}

export interface ChatStreamHandlers {
  onUserMessage?: (data: { id: string; sequence: number; title: string }) => void
  onStart?: (data: {
    message_id: string
    sequence: number
    provider_id: string
    model_id: string
    context: {
      sources: string[]
      estimated_input_tokens: number
      dropped_messages: number
    }
  }) => void
  onDelta?: (text: string) => void
  onError?: (error: StreamErrorPayload) => void
  onDone?: (data: {
    message_id: string
    stop_reason: string | null
    latency_ms: number
    input_tokens: number | null
    output_tokens: number | null
    cost_usd: number | null
  }) => void
}

export interface ChatStreamRequest {
  conversationId: string
  content: string
  providerId?: string
  modelId?: string
  signal?: AbortSignal
}

export async function streamChat(
  request: ChatStreamRequest,
  handlers: ChatStreamHandlers,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${apiBase()}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: request.conversationId,
        content: request.content,
        provider_id: request.providerId,
        model_id: request.modelId,
      }),
      signal: request.signal,
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') return
    throw new ApiError('Could not reach the GAIA backend. Is it running?', 0)
  }

  if (!response.ok || !response.body) {
    let message = `The backend rejected the request (${response.status}).`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') message = body.detail
      else if (Array.isArray(body?.detail)) message = body.detail[0]?.msg ?? message
    } catch {
      /* keep the generic message */
    }
    handlers.onError?.({ kind: 'request_failed', message, status: response.status })
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        dispatch(buffer.slice(0, boundary), handlers)
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
    }
    if (buffer.trim()) dispatch(buffer, handlers)
  } catch (error) {
    if ((error as Error).name === 'AbortError') return
    throw error
  } finally {
    reader.releaseLock()
  }
}

function dispatch(frame: string, handlers: ChatStreamHandlers): void {
  let event = ''
  const dataLines: string[] = []

  for (const line of frame.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
  }
  if (!event || dataLines.length === 0) return

  let data: unknown
  try {
    data = JSON.parse(dataLines.join('\n'))
  } catch {
    return
  }

  switch (event) {
    case 'user_message':
      handlers.onUserMessage?.(data as never)
      break
    case 'start':
      handlers.onStart?.(data as never)
      break
    case 'delta':
      handlers.onDelta?.((data as { text: string }).text)
      break
    case 'error':
      handlers.onError?.(data as StreamErrorPayload)
      break
    case 'done':
      handlers.onDone?.(data as never)
      break
  }
}
