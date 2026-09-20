import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import { voiceApi } from './voice'

describe('voiceApi.transcribe', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the transcribed text on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ text: 'hello gaia', language: 'en' }),
      } as unknown as Response),
    )
    const result = await voiceApi.transcribe(new Blob(['fake audio']))
    expect(result).toEqual({ text: 'hello gaia', language: 'en' })
  })

  it('throws an ApiError with the backend detail on failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: 'Could not make out any speech in that recording.' }),
      } as unknown as Response),
    )
    await expect(voiceApi.transcribe(new Blob(['x']))).rejects.toMatchObject({
      message: 'Could not make out any speech in that recording.',
      status: 422,
    })
  })

  it('reports a network failure as an ApiError rather than throwing raw', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(voiceApi.transcribe(new Blob(['x']))).rejects.toBeInstanceOf(ApiError)
  })
})

describe('voiceApi.speak', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns a playable blob on success', async () => {
    const fakeBlob = new Blob(['fake wav bytes'], { type: 'audio/wav' })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: async () => fakeBlob,
      } as unknown as Response),
    )
    const result = await voiceApi.speak('hello')
    expect(result).toBe(fakeBlob)
  })

  it('throws an ApiError with the backend detail on failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => ({ detail: 'Speech synthesis failed: engine unavailable' }),
      } as unknown as Response),
    )
    await expect(voiceApi.speak('hello')).rejects.toMatchObject({
      message: 'Speech synthesis failed: engine unavailable',
      status: 502,
    })
  })
})

describe('fetch call shape', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ text: '', language: null }),
      blob: async () => new Blob([]),
    } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('transcribe posts multipart form data to /api/voice/transcribe', async () => {
    await voiceApi.transcribe(new Blob(['audio']))
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/voice/transcribe')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
  })

  it('speak posts JSON to /api/voice/speak', async () => {
    await voiceApi.speak('hello world')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/voice/speak')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ text: 'hello world' })
  })
})
