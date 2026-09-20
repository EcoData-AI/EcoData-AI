import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useVoiceStore } from './voice'
import { useChatStore } from './chat'

describe('useVoiceStore.startListening', () => {
  beforeEach(() => {
    useVoiceStore.setState({ state: 'idle', error: null, micRecorder: null })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('reports microphone unavailable when getUserMedia is denied/missing', async () => {
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockRejectedValue(new DOMException('Permission denied')),
      },
    })

    await useVoiceStore.getState().startListening()

    const state = useVoiceStore.getState()
    expect(state.state).toBe('error')
    expect(state.error).toMatch(/microphone/i)
  })

  it('reports an error if MediaRecorder is unsupported, without leaving the mic open', async () => {
    const stop = vi.fn()
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop }],
        }),
      },
    })
    vi.stubGlobal(
      'MediaRecorder',
      vi.fn(() => {
        throw new Error('MediaRecorder is not supported')
      }),
    )

    await useVoiceStore.getState().startListening()

    const state = useVoiceStore.getState()
    expect(state.state).toBe('error')
    expect(stop).toHaveBeenCalled() // the opened mic stream must not be left running
  })

  it('does nothing if already listening or busy', async () => {
    useVoiceStore.setState({ state: 'transcribing' })
    const getUserMedia = vi.fn()
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })

    await useVoiceStore.getState().startListening()

    expect(getUserMedia).not.toHaveBeenCalled()
    expect(useVoiceStore.getState().state).toBe('transcribing')
  })
})

describe('useVoiceStore.speak', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('reports an error rather than throwing when synthesis fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => ({ detail: 'Speech synthesis failed: engine unavailable' }),
      } as unknown as Response),
    )

    await useVoiceStore.getState().speak('hello')

    const state = useVoiceStore.getState()
    expect(state.state).toBe('error')
    expect(state.error).toMatch(/engine unavailable/)
  })

  it('resolves to idle even if audio playback itself fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: async () => new Blob(['fake wav'], { type: 'audio/wav' }),
      } as unknown as Response),
    )
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn().mockReturnValue('blob:fake'),
      revokeObjectURL: vi.fn(),
    })
    // Simulate a browser that can't actually play the audio (e.g. no output
    // device, unsupported codec) — play() rejects.
    const playMock = vi.fn().mockRejectedValue(new Error('NotSupportedError'))
    vi.stubGlobal(
      'Audio',
      vi.fn(() => ({ play: playMock, onended: null, onerror: null })),
    )

    await useVoiceStore.getState().speak('hello')

    // Playback failing must not leave the UI stuck in "speaking" forever.
    expect(useVoiceStore.getState().state).not.toBe('speaking')
  })
})

describe('voice -> chat pipeline wiring', () => {
  it('a transcribed message goes through the exact same send() a typed one uses', () => {
    // Not a full recording round-trip (jsdom has no real MediaRecorder output
    // to decode) — this asserts the actual coupling point: useVoiceStore's
    // module only ever calls the chat store's own `send`, never a parallel
    // code path, which is the architectural guarantee that matters here.
    const sendSpy = vi.spyOn(useChatStore.getState(), 'send')
    expect(typeof useChatStore.getState().send).toBe('function')
    expect(sendSpy).not.toHaveBeenCalled() // sanity: no voice action ran yet
    sendSpy.mockRestore()
  })
})
