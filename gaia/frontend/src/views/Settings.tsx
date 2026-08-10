import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  ApiError,
  type ModelInfo,
  type PrivacyRow,
  type Provider,
  type SystemStatus,
} from '@/lib/api'

type Tab = 'models' | 'general' | 'privacy' | 'status' | 'data'

const TABS: { id: Tab; label: string }[] = [
  { id: 'models', label: 'AI & Models' },
  { id: 'general', label: 'General' },
  { id: 'privacy', label: 'Privacy' },
  { id: 'status', label: 'System status' },
  { id: 'data', label: 'Data & backups' },
]

interface Props {
  onProvidersChanged: () => void
}

export function Settings({ onProvidersChanged }: Props) {
  const [tab, setTab] = useState<Tab>('models')

  return (
    <div className="panel">
      <div className="panel__inner">
        <h2>Settings</h2>
        <p className="panel__lede">GAIA Beta v0.1 — Milestone 1.</p>

        <div className="row" style={{ margin: '18px 0 4px', flexWrap: 'wrap' }}>
          {TABS.map((entry) => (
            <button
              key={entry.id}
              className="btn"
              style={
                tab === entry.id
                  ? { borderColor: 'var(--accent)', color: 'var(--accent)', fontWeight: 600 }
                  : undefined
              }
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>

        {tab === 'models' && <ModelsTab onProvidersChanged={onProvidersChanged} />}
        {tab === 'general' && <GeneralTab />}
        {tab === 'privacy' && <PrivacyTab />}
        {tab === 'status' && <StatusTab />}
        {tab === 'data' && <DataTab />}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- models */

function ModelsTab({ onProvidersChanged }: { onProvidersChanged: () => void }) {
  const [providers, setProviders] = useState<Provider[]>([])
  const [activeProvider, setActiveProvider] = useState<string>('')
  const [activeModel, setActiveModel] = useState<string>('')
  const [models, setModels] = useState<ModelInfo[]>([])
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  const load = useCallback(async () => {
    const [list, settings] = await Promise.all([api.listProviders(), api.getSettings()])
    setProviders(list)
    const selected = (settings.values['llm.active_provider'] as string) ?? list[0]?.id ?? ''
    setActiveProvider(selected)
    setActiveModel((settings.values['llm.active_model'] as string) ?? '')
    setBaseUrl(list.find((p) => p.id === selected)?.base_url ?? '')
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!activeProvider) return
    let cancelled = false
    api
      .listModels(activeProvider)
      .then((result) => {
        if (!cancelled) setModels(result)
      })
      .catch(() => {
        if (!cancelled) setModels([])
      })
    return () => {
      cancelled = true
    }
  }, [activeProvider, providers])

  const current = providers.find((p) => p.id === activeProvider)

  const selectProvider = async (id: string) => {
    setActiveProvider(id)
    setActiveModel('')
    setApiKey('')
    setBaseUrl(providers.find((p) => p.id === id)?.base_url ?? '')
    setMessage(null)
    await api.updateSettings({ 'llm.active_provider': id, 'llm.active_model': null })
    onProvidersChanged()
  }

  const selectModel = async (id: string) => {
    setActiveModel(id)
    await api.updateSettings({ 'llm.active_model': id || null })
    onProvidersChanged()
  }

  const saveCredentials = async () => {
    setBusy(true)
    setMessage(null)
    try {
      await api.setCredentials(activeProvider, {
        api_key: apiKey.trim() || undefined,
        base_url: baseUrl.trim() || undefined,
      })
      setApiKey('')
      const health = await api.testProvider(activeProvider)
      setMessage(
        health.state === 'ok'
          ? { tone: 'ok', text: `Connected. ${health.detail}` }
          : { tone: 'error', text: health.detail || 'Connection failed.' },
      )
      await load()
      onProvidersChanged()
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof ApiError ? error.message : 'Could not save the credentials.',
      })
    } finally {
      setBusy(false)
    }
  }

  const testConnection = async () => {
    setBusy(true)
    setMessage(null)
    try {
      const health = await api.testProvider(activeProvider)
      setMessage(
        health.state === 'ok'
          ? {
              tone: 'ok',
              text: `Connected${health.latency_ms != null ? ` in ${health.latency_ms} ms` : ''}. ${health.detail}`,
            }
          : { tone: 'error', text: health.detail || 'Not reachable.' },
      )
    } finally {
      setBusy(false)
    }
  }

  const removeKey = async () => {
    await api.clearCredentials(activeProvider)
    await load()
    onProvidersChanged()
    setMessage({ tone: 'ok', text: 'API key removed from this machine.' })
  }

  return (
    <>
      <h3>Provider</h3>
      <div className="stack">
        {providers.map((provider) => (
          <label key={provider.id} className="card row" style={{ gap: 12, cursor: 'pointer' }}>
            <input
              type="radio"
              name="provider"
              checked={activeProvider === provider.id}
              onChange={() => void selectProvider(provider.id)}
            />
            <span style={{ flex: 1 }}>
              <strong>{provider.display_name}</strong>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {provider.is_local
                  ? 'Runs on this machine — no data leaves your computer.'
                  : 'Cloud service — your messages are sent to this provider.'}
              </div>
            </span>
            <span className={`tag ${provider.configured ? 'tag--ok' : 'tag--muted'}`}>
              {provider.configured
                ? provider.key_hint
                  ? `key ${provider.key_hint}`
                  : 'ready'
                : 'not configured'}
            </span>
          </label>
        ))}
      </div>

      {current && (
        <>
          <h3>{current.display_name}</h3>

          {current.requires_api_key && (
            <label className="field">
              <span className="field__label">API key</span>
              <input
                className="input"
                type="password"
                autoComplete="off"
                placeholder={current.configured ? `Stored (${current.key_hint})` : 'sk-…'}
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
              />
              <span className="field__hint">
                Stored in your OS keyring (or an owner-only file), never in the database and never
                in git.{' '}
                {current.setup_url && (
                  <a href={current.setup_url} target="_blank" rel="noreferrer noopener">
                    Get a key
                  </a>
                )}
              </span>
            </label>
          )}

          <label className="field">
            <span className="field__label">Endpoint URL</span>
            <input
              className="input"
              type="url"
              placeholder={current.id === 'ollama' ? 'http://127.0.0.1:11434' : 'Default'}
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
            <span className="field__hint">
              Leave blank for the provider default. Point this at LM Studio, vLLM or any
              OpenAI-compatible server.
            </span>
          </label>

          <div className="row" style={{ marginBottom: 16 }}>
            <button className="btn btn--primary" onClick={() => void saveCredentials()} disabled={busy}>
              Save
            </button>
            <button className="btn" onClick={() => void testConnection()} disabled={busy}>
              Test connection
            </button>
            {current.configured && current.requires_api_key && (
              <button className="btn btn--danger" onClick={() => void removeKey()} disabled={busy}>
                Remove key
              </button>
            )}
          </div>

          {message && (
            <div className={`notice ${message.tone === 'error' ? 'notice--error' : ''}`}>
              <div className="notice__body">{message.text}</div>
            </div>
          )}

          <h3>Model</h3>
          {models.length === 0 ? (
            <p style={{ color: 'var(--text-muted)' }}>
              No models to list. Configure the provider above, then test the connection.
            </p>
          ) : (
            <>
              <label className="field">
                <span className="field__label">Active model</span>
                <select
                  className="select"
                  value={activeModel}
                  onChange={(event) => void selectModel(event.target.value)}
                >
                  <option value="">Provider default</option>
                  {models.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name}
                    </option>
                  ))}
                </select>
              </label>

              <table className="table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Context</th>
                    <th>Location</th>
                    <th>Cost / Mtok (in / out)</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((model) => (
                    <tr key={model.id}>
                      <td className="mono">{model.id}</td>
                      <td>
                        {model.context_window > 0
                          ? `${(model.context_window / 1000).toLocaleString()}K`
                          : '—'}
                      </td>
                      <td>{model.is_local ? 'Local' : 'Cloud'}</td>
                      <td>
                        {model.input_cost_per_mtok == null
                          ? '—'
                          : model.input_cost_per_mtok === 0
                            ? 'free'
                            : `$${model.input_cost_per_mtok} / $${model.output_cost_per_mtok}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </>
  )
}

/* ------------------------------------------------------------ general */

function GeneralTab() {
  const [instructions, setInstructions] = useState('')
  const [theme, setTheme] = useState('system')
  const [maxTokens, setMaxTokens] = useState(16000)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    void api.getSettings().then((settings) => {
      setInstructions((settings.values['general.custom_instructions'] as string) ?? '')
      setTheme((settings.values['appearance.theme'] as string) ?? 'system')
      setMaxTokens((settings.values['llm.max_tokens'] as number) ?? 16000)
    })
  }, [])

  const save = async () => {
    await api.updateSettings({
      'general.custom_instructions': instructions,
      'appearance.theme': theme,
      'llm.max_tokens': maxTokens,
    })
    applyTheme(theme)
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  return (
    <>
      <h3>Custom instructions</h3>
      <label className="field">
        <span className="field__label">Tell GAIA how you want it to respond</span>
        <textarea
          className="textarea"
          rows={5}
          value={instructions}
          placeholder="e.g. I'm an economics student. Prefer worked examples and formal notation."
          onChange={(event) => setInstructions(event.target.value)}
        />
        <span className="field__hint">
          Added to every conversation's system prompt. It cannot override GAIA's honesty rules.
        </span>
      </label>

      <h3>Appearance</h3>
      <label className="field">
        <span className="field__label">Theme</span>
        <select
          className="select"
          value={theme}
          onChange={(event) => {
            setTheme(event.target.value)
            applyTheme(event.target.value)
          }}
        >
          <option value="system">Match system</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </label>

      <h3>Response length</h3>
      <label className="field">
        <span className="field__label">Maximum output tokens</span>
        <input
          className="input"
          type="number"
          min={256}
          max={128000}
          step={1000}
          value={maxTokens}
          onChange={(event) => setMaxTokens(Number(event.target.value))}
        />
        <span className="field__hint">
          Caps a single reply. On models that reason before answering, this budget covers both the
          reasoning and the reply, so leave headroom.
        </span>
      </label>

      <div className="row">
        <button className="btn btn--primary" onClick={() => void save()}>
          Save
        </button>
        {saved && <span style={{ color: 'var(--ok)' }}>Saved.</span>}
      </div>
    </>
  )
}

export function applyTheme(theme: string): void {
  const root = document.documentElement
  if (theme === 'light' || theme === 'dark') root.setAttribute('data-theme', theme)
  else root.removeAttribute('data-theme')
}

/* ------------------------------------------------------------ privacy */

function PrivacyTab() {
  const [rows, setRows] = useState<PrivacyRow[]>([])

  useEffect(() => {
    void api.privacy().then(setRows)
  }, [])

  return (
    <>
      <h3>Where your data lives</h3>
      <p style={{ color: 'var(--text-muted)', marginTop: 0 }}>
        GAIA is local-first. The only thing that leaves this machine is the text you send to a
        cloud model provider, if you have configured one.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Data</th>
            <th>Location</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              <td>
                <span
                  className={`tag ${
                    row.location === 'LOCAL'
                      ? 'tag--ok'
                      : row.location === 'NOT BUILT'
                        ? 'tag--muted'
                        : 'tag--warn'
                  }`}
                >
                  {row.location}
                </span>
              </td>
              <td style={{ color: 'var(--text-muted)' }}>{row.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

/* ------------------------------------------------------------- status */

function StatusTab() {
  const [status, setStatus] = useState<SystemStatus | null>(null)

  const refresh = useCallback(() => {
    void api.systemStatus().then(setStatus)
  }, [])

  useEffect(refresh, [refresh])

  if (!status) return <p style={{ color: 'var(--text-muted)' }}>Checking…</p>

  return (
    <>
      <div className="row row--between" style={{ marginTop: 24 }}>
        <h3 style={{ margin: 0, border: 0 }}>Components</h3>
        <button className="btn" onClick={refresh}>
          Refresh
        </button>
      </div>
      <table className="table">
        <tbody>
          {status.components.map((component) => (
            <tr key={component.name}>
              <td style={{ width: 190 }}>{component.name}</td>
              <td style={{ width: 120 }}>
                <span
                  className={`tag ${
                    component.state === 'ok'
                      ? 'tag--ok'
                      : component.state === 'error'
                        ? 'tag--error'
                        : component.state === 'not_configured'
                          ? 'tag--warn'
                          : 'tag--muted'
                  }`}
                >
                  {component.state === 'not_built' ? 'not built' : component.state}
                </span>
              </td>
              <td style={{ color: 'var(--text-muted)' }}>{component.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mono" style={{ color: 'var(--text-faint)', marginTop: 16 }}>
        Data directory: {status.data_dir}
      </p>
    </>
  )
}

/* --------------------------------------------------------------- data */

function DataTab() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [dataDir, setDataDir] = useState('')

  useEffect(() => {
    void api.getSettings().then((settings) => setDataDir(settings.data_dir))
  }, [])

  const importBackup = async (file: File) => {
    if (
      !window.confirm(
        'Importing replaces your current GAIA database. Your existing data is copied aside first. Continue?',
      )
    ) {
      return
    }
    try {
      await api.importBackup(file)
      setMessage('Imported. Restart GAIA for the change to take effect.')
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : 'Import failed.')
    }
  }

  return (
    <>
      <h3>Backups</h3>
      <p style={{ color: 'var(--text-muted)', marginTop: 0 }}>
        A backup is a single SQLite file containing your conversations and settings. It does not
        contain API keys — those live in your OS keyring.
      </p>
      <div className="row">
        <a className="btn btn--primary" href={api.exportBackupUrl()} download>
          Export database
        </a>
        <button className="btn" onClick={() => fileRef.current?.click()}>
          Import database…
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".db,.sqlite,.sqlite3"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void importBackup(file)
            event.target.value = ''
          }}
        />
      </div>
      {message && (
        <div className="notice" style={{ marginTop: 14 }}>
          <div className="notice__body">{message}</div>
        </div>
      )}

      <h3>Storage location</h3>
      <p className="mono" style={{ color: 'var(--text-muted)' }}>
        {dataDir || '…'}
      </p>
      <p style={{ color: 'var(--text-faint)', fontSize: 13 }}>
        Everything GAIA writes lives here, outside the application itself.
      </p>
    </>
  )
}
