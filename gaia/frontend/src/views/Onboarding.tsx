import { useEffect, useState } from 'react'
import { api, ApiError, type ModelInfo, type Provider } from '@/lib/api'

interface Props {
  onComplete: () => void
}

/**
 * First-run setup: choose a provider, give it credentials, verify the
 * connection for real, then start. The "Start" button stays disabled until a
 * live connection test has actually succeeded — the wizard never claims a
 * working setup it has not proven.
 */
export function Onboarding({ onComplete }: Props) {
  const [step, setStep] = useState(0)
  const [providers, setProviders] = useState<Provider[]>([])
  const [providerId, setProviderId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [models, setModels] = useState<ModelInfo[]>([])
  const [modelId, setModelId] = useState('')
  const [dataDir, setDataDir] = useState('')
  const [testing, setTesting] = useState(false)
  const [verified, setVerified] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api.listProviders().then((list) => {
      setProviders(list)
      setProviderId(list[0]?.id ?? '')
    })
    void api.getSettings().then((settings) => setDataDir(settings.data_dir))
  }, [])

  const provider = providers.find((p) => p.id === providerId)

  const runTest = async () => {
    setTesting(true)
    setError(null)
    setVerified(false)
    try {
      await api.setCredentials(providerId, {
        api_key: apiKey.trim() || undefined,
        base_url: baseUrl.trim() || undefined,
      })
      const health = await api.testProvider(providerId)
      if (health.state !== 'ok') {
        setError(health.detail || 'The provider is not reachable.')
        return
      }
      setVerified(true)
      const available = await api.listModels(providerId)
      setModels(available)
      setModelId(available[0]?.id ?? '')
      setStep(2)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not verify the connection.')
    } finally {
      setTesting(false)
    }
  }

  const finish = async () => {
    await api.updateSettings({
      'llm.active_provider': providerId,
      'llm.active_model': modelId || null,
      'general.onboarding_complete': true,
    })
    onComplete()
  }

  const skip = async () => {
    // Skipping is allowed, but the chat composer stays disabled until a
    // provider works, so the app never looks functional when it is not.
    await api.updateSettings({ 'general.onboarding_complete': true })
    onComplete()
  }

  return (
    <div className="onboarding">
      <div className="onboarding__card">
        <h1 style={{ fontSize: 22, margin: '0 0 4px' }}>Welcome to GAIA</h1>
        <p style={{ color: 'var(--text-muted)', marginTop: 0 }}>
          General-purpose Adaptive Intelligence Assistant — Beta v0.1
        </p>

        <div className="steps" style={{ marginTop: 20 }}>
          {[0, 1, 2].map((index) => (
            <div key={index} className="steps__dot" data-done={index <= step} />
          ))}
        </div>

        {step === 0 && (
          <>
            <h3 style={{ marginTop: 0 }}>Choose a model provider</h3>
            <div className="stack">
              {providers.map((entry) => (
                <label key={entry.id} className="card row" style={{ gap: 12, cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="onboarding-provider"
                    checked={providerId === entry.id}
                    onChange={() => setProviderId(entry.id)}
                  />
                  <span style={{ flex: 1 }}>
                    <strong>{entry.display_name}</strong>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      {entry.is_local
                        ? 'Runs on your machine. Nothing leaves this computer.'
                        : 'Cloud service. Your messages are sent to the provider.'}
                    </div>
                  </span>
                </label>
              ))}
            </div>
            <div className="row" style={{ marginTop: 18 }}>
              <button className="btn btn--primary" onClick={() => setStep(1)} disabled={!providerId}>
                Continue
              </button>
              <button className="btn btn--ghost" onClick={() => void skip()}>
                Skip for now
              </button>
            </div>
          </>
        )}

        {step === 1 && provider && (
          <>
            <h3 style={{ marginTop: 0 }}>Configure {provider.display_name}</h3>
            {provider.requires_api_key && (
              <label className="field">
                <span className="field__label">API key</span>
                <input
                  className="input"
                  type="password"
                  autoFocus
                  autoComplete="off"
                  placeholder="sk-…"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                />
                <span className="field__hint">
                  Stored in your operating system's keyring.{' '}
                  {provider.setup_url && (
                    <a href={provider.setup_url} target="_blank" rel="noreferrer noopener">
                      Get a key
                    </a>
                  )}
                </span>
              </label>
            )}
            <label className="field">
              <span className="field__label">Endpoint URL (optional)</span>
              <input
                className="input"
                type="url"
                placeholder={provider.id === 'ollama' ? 'http://127.0.0.1:11434' : 'Default'}
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </label>

            {error && (
              <div className="notice notice--error">
                <div className="notice__body">{error}</div>
              </div>
            )}

            <div className="row" style={{ marginTop: 4 }}>
              <button className="btn btn--primary" onClick={() => void runTest()} disabled={testing}>
                {testing ? 'Testing…' : 'Test connection'}
              </button>
              <button className="btn" onClick={() => setStep(0)}>
                Back
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h3 style={{ marginTop: 0 }}>Choose a model</h3>
            {verified && (
              <p style={{ color: 'var(--ok)', marginTop: 0 }}>Connection verified.</p>
            )}
            <label className="field">
              <span className="field__label">Model</span>
              <select
                className="select"
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
              >
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
            </label>

            <div className="card" style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Your conversations will be stored locally at
              </div>
              <div className="mono" style={{ marginTop: 4 }}>
                {dataDir}
              </div>
            </div>

            <div className="row">
              <button className="btn btn--primary" onClick={() => void finish()} disabled={!verified}>
                Start using GAIA
              </button>
              <button className="btn" onClick={() => setStep(1)}>
                Back
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
