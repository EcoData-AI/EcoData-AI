import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { streamChat, type StreamErrorPayload } from './stream'

/** Serve `chunks` as a streaming fetch response, byte-for-byte as given. */
function mockStream(chunks: string[], ok = true, status = 200) {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return vi.fn().mockResolvedValue({ ok, status, body } as unknown as Response)
}

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

describe('streamChat', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockStream([]))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('dispatches events in order', async () => {
    vi.stubGlobal(
      'fetch',
      mockStream([
        frame('user_message', { id: 'u1', sequence: 1, title: 'Hi' }),
        frame('start', {
          message_id: 'a1',
          sequence: 2,
          provider_id: 'mock',
          model_id: 'mock-echo',
          context: { sources: ['persona'], estimated_input_tokens: 12, dropped_messages: 0 },
        }),
        frame('delta', { text: 'Hello' }),
        frame('delta', { text: ' world' }),
        frame('done', {
          message_id: 'a1',
          stop_reason: 'end_turn',
          latency_ms: 42,
          input_tokens: 5,
          output_tokens: 2,
          cost_usd: null,
        }),
      ]),
    )

    const deltas: string[] = []
    let started = false
    let done = false

    await streamChat(
      { conversationId: 'c1', content: 'hi' },
      {
        onStart: () => {
          started = true
        },
        onDelta: (text) => deltas.push(text),
        onDone: () => {
          done = true
        },
      },
    )

    expect(started).toBe(true)
    expect(deltas.join('')).toBe('Hello world')
    expect(done).toBe(true)
  })

  it('dispatches tool_call, tool_confirm_required and tool_result events', async () => {
    vi.stubGlobal(
      'fetch',
      mockStream([
        frame('tool_call', {
          call_id: 't1',
          tool: 'calculator',
          arguments: { expression: '2+2' },
          risk_level: 'safe',
        }),
        frame('tool_confirm_required', {
          call_id: 't2',
          tool: 'filesystem',
          arguments: { path: '/tmp/x' },
        }),
        frame('tool_result', {
          call_id: 't1',
          tool: 'calculator',
          ok: true,
          content: '4',
          display: { expression: '2+2', result: '4' },
        }),
      ]),
    )

    const calls: unknown[] = []
    const confirms: unknown[] = []
    const results: unknown[] = []

    await streamChat(
      { conversationId: 'c1', content: 'calc: 2+2' },
      {
        onToolCall: (data) => calls.push(data),
        onToolConfirmRequired: (data) => confirms.push(data),
        onToolResult: (data) => results.push(data),
      },
    )

    expect(calls).toEqual([
      { call_id: 't1', tool: 'calculator', arguments: { expression: '2+2' }, risk_level: 'safe' },
    ])
    expect(confirms).toEqual([
      { call_id: 't2', tool: 'filesystem', arguments: { path: '/tmp/x' } },
    ])
    expect(results).toEqual([
      {
        call_id: 't1',
        tool: 'calculator',
        ok: true,
        content: '4',
        display: { expression: '2+2', result: '4' },
      },
    ])
  })

  it('reassembles frames split across chunk boundaries', async () => {
    // A single SSE frame arriving in three arbitrary pieces, as a real socket
    // read can deliver it.
    vi.stubGlobal(
      'fetch',
      mockStream(['event: del', 'ta\ndata: {"text":"par', 'tial"}\n\n']),
    )

    const deltas: string[] = []
    await streamChat({ conversationId: 'c1', content: 'hi' }, { onDelta: (t) => deltas.push(t) })
    expect(deltas).toEqual(['partial'])
  })

  it('handles multiple frames inside one chunk', async () => {
    vi.stubGlobal(
      'fetch',
      mockStream([frame('delta', { text: 'a' }) + frame('delta', { text: 'b' })]),
    )
    const deltas: string[] = []
    await streamChat({ conversationId: 'c1', content: 'hi' }, { onDelta: (t) => deltas.push(t) })
    expect(deltas).toEqual(['a', 'b'])
  })

  it('surfaces backend error events', async () => {
    vi.stubGlobal(
      'fetch',
      mockStream([
        frame('error', {
          kind: 'not_configured',
          message: 'No API key is configured.',
          remedy: 'Add one in Settings.',
        }),
      ]),
    )

    let error: StreamErrorPayload | null = null
    await streamChat({ conversationId: 'c1', content: 'hi' }, { onError: (e) => (error = e) })
    expect(error).not.toBeNull()
    expect(error!.kind).toBe('not_configured')
    expect(error!.remedy).toBe('Add one in Settings.')
  })

  it('reports a non-2xx response as an error rather than throwing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        body: null,
        json: async () => ({ detail: 'content must not be empty' }),
      } as unknown as Response),
    )

    let error: StreamErrorPayload | null = null
    await streamChat({ conversationId: 'c1', content: '' }, { onError: (e) => (error = e) })
    expect(error!.message).toBe('content must not be empty')
    expect(error!.status).toBe(422)
  })

  it('ignores malformed frames instead of aborting the stream', async () => {
    vi.stubGlobal(
      'fetch',
      mockStream([
        'event: delta\ndata: {not json}\n\n',
        'data: orphaned payload with no event\n\n',
        frame('delta', { text: 'ok' }),
      ]),
    )
    const deltas: string[] = []
    await streamChat({ conversationId: 'c1', content: 'hi' }, { onDelta: (t) => deltas.push(t) })
    expect(deltas).toEqual(['ok'])
  })

  it('resolves quietly when the caller aborts', async () => {
    const controller = new AbortController()
    controller.abort()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(Object.assign(new Error('aborted'), { name: 'AbortError' })),
    )

    await expect(
      streamChat({ conversationId: 'c1', content: 'hi', signal: controller.signal }, {}),
    ).resolves.toBeUndefined()
  })
})
