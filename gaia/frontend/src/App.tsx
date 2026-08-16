import { useCallback, useEffect, useState } from 'react'
import { Sidebar, type ViewId } from '@/components/Sidebar'
import { api, ApiError, type Capability, type Provider } from '@/lib/api'
import { useChatStore } from '@/store/chat'
import { ChatView } from '@/views/ChatView'
import { NotBuilt } from '@/views/NotBuilt'
import { Onboarding } from '@/views/Onboarding'
import { Settings, applyTheme } from '@/views/Settings'

type Boot =
  | { phase: 'connecting' }
  | { phase: 'unreachable'; detail: string }
  | { phase: 'onboarding' }
  | { phase: 'ready' }

export function App() {
  const [boot, setBoot] = useState<Boot>({ phase: 'connecting' })
  const [view, setView] = useState<ViewId>('chat')
  const [version, setVersion] = useState('0.1.0')
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [providers, setProviders] = useState<Provider[]>([])
  const [activeProviderId, setActiveProviderId] = useState<string | null>(null)

  const chat = useChatStore()

  const refreshProviders = useCallback(async () => {
    const [list, settings] = await Promise.all([api.listProviders(), api.getSettings()])
    setProviders(list)
    setActiveProviderId((settings.values['llm.active_provider'] as string) ?? null)
  }, [])

  const start = useCallback(async () => {
    setBoot({ phase: 'connecting' })
    try {
      const health = await api.health()
      setVersion(health.version)

      const [caps, settings] = await Promise.all([api.capabilities(), api.getSettings()])
      setCapabilities(caps)
      applyTheme((settings.values['appearance.theme'] as string) ?? 'system')
      await refreshProviders()

      if (!settings.values['general.onboarding_complete']) {
        setBoot({ phase: 'onboarding' })
        return
      }

      setBoot({ phase: 'ready' })
      await chat.loadConversations()
      const first = useChatStore.getState().conversations[0]
      if (first) await chat.selectConversation(first.id)
    } catch (error) {
      setBoot({
        phase: 'unreachable',
        detail:
          error instanceof ApiError
            ? error.message
            : 'The GAIA backend did not respond. It may still be starting up.',
      })
    }
    // `chat` methods are stable zustand actions; re-running on store changes
    // would restart the boot sequence on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshProviders])

  useEffect(() => {
    void start()
  }, [start])

  // Debounced conversation search.
  useEffect(() => {
    if (boot.phase !== 'ready') return
    const handle = setTimeout(() => void chat.loadConversations(), 220)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.searchQuery, boot.phase])

  if (boot.phase === 'connecting') {
    return (
      <div className="empty">
        <h2>Starting GAIA…</h2>
        <p>Connecting to the local backend.</p>
      </div>
    )
  }

  if (boot.phase === 'unreachable') {
    return (
      <div className="empty">
        <h2>GAIA can't reach its backend</h2>
        <p>{boot.detail}</p>
        <p style={{ color: 'var(--text-faint)', fontSize: 13 }}>
          If you launched GAIA from a terminal, check that the Python backend started. The desktop
          app normally starts it for you.
        </p>
        <button className="btn btn--primary" style={{ marginTop: 12 }} onClick={() => void start()}>
          Retry
        </button>
      </div>
    )
  }

  if (boot.phase === 'onboarding') {
    return <Onboarding onComplete={() => void start()} />
  }

  const activeProvider = providers.find((p) => p.id === activeProviderId)
  const providerReady = Boolean(activeProvider?.configured)
  const providerHint = activeProvider
    ? `${activeProvider.display_name} needs ${
        activeProvider.requires_api_key ? 'an API key' : 'to be running'
      } before GAIA can answer.`
    : 'Choose a model provider to get started.'

  const capabilityFor = (key: string) => capabilities.find((c) => c.key === key)
  const viewCapability: Partial<Record<ViewId, string>> = {
    study: 'study',
    projects: 'projects',
    research: 'research',
    knowledge: 'knowledge',
    simulation: 'simulation',
    experiments: 'experiments',
  }

  return (
    <div className="app">
      <Sidebar
        view={view}
        onSelectView={setView}
        version={version}
        capabilities={capabilities}
        conversations={chat.conversations}
        activeId={chat.activeId}
        searchQuery={chat.searchQuery}
        onSearch={chat.setSearchQuery}
        onNewConversation={() => void chat.newConversation()}
        onSelectConversation={(id) => void chat.selectConversation(id)}
        onRename={(id, title) => void chat.renameConversation(id, title)}
        onTogglePin={(id) => void chat.togglePin(id)}
        onDelete={(id) => void chat.deleteConversation(id)}
      />

      <main className="main">
        {view === 'chat' && (
          <ChatView
            providerReady={providerReady}
            providerHint={providerHint}
            onOpenSettings={() => setView('settings')}
          />
        )}
        {view === 'settings' && <Settings onProvidersChanged={() => void refreshProviders()} />}
        {viewCapability[view] && (
          <NotBuilt capability={capabilityFor(viewCapability[view]!)} label={view} />
        )}
      </main>
    </div>
  )
}
