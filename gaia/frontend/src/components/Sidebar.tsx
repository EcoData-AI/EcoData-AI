import { useState } from 'react'
import type { Capability, Conversation } from '@/lib/api'

export type ViewId =
  | 'chat'
  | 'study'
  | 'projects'
  | 'research'
  | 'knowledge'
  | 'simulation'
  | 'experiments'
  | 'settings'

interface NavEntry {
  id: ViewId
  label: string
  icon: string
  /** Capability key that gates this view; undefined means always available. */
  capability?: string
}

const NAV: NavEntry[] = [
  { id: 'chat', label: 'Chat', icon: '◆' },
  { id: 'study', label: 'Study', icon: '◇', capability: 'study' },
  { id: 'projects', label: 'Projects', icon: '▤', capability: 'projects' },
  { id: 'research', label: 'Research', icon: '◎', capability: 'research' },
  { id: 'knowledge', label: 'Knowledge', icon: '▣', capability: 'knowledge' },
  { id: 'simulation', label: 'Simulation Lab', icon: '⬡', capability: 'simulation' },
  { id: 'experiments', label: 'Experiments', icon: '⬢', capability: 'experiments' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
]

interface Props {
  view: ViewId
  onSelectView: (view: ViewId) => void
  version: string
  capabilities: Capability[]
  conversations: Conversation[]
  activeId: string | null
  searchQuery: string
  onSearch: (query: string) => void
  onNewConversation: () => void
  onSelectConversation: (id: string) => void
  onRename: (id: string, title: string) => void
  onTogglePin: (id: string) => void
  onDelete: (id: string) => void
}

export function Sidebar(props: Props) {
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const byKey = new Map(props.capabilities.map((c) => [c.key, c]))

  const commitRename = (id: string) => {
    if (renameValue.trim()) props.onRename(id, renameValue)
    setRenamingId(null)
  }

  return (
    <nav className="sidebar" aria-label="Main">
      <div className="sidebar__brand">
        <h1>GAIA</h1>
        <span className="sidebar__version">Beta v{props.version}</span>
      </div>

      <div className="sidebar__section">
        {NAV.map((entry) => {
          const capability = entry.capability ? byKey.get(entry.capability) : undefined
          const locked = Boolean(entry.capability) && capability?.available !== true
          return (
            <button
              key={entry.id}
              className="nav-item"
              aria-current={props.view === entry.id ? 'page' : undefined}
              onClick={() => props.onSelectView(entry.id)}
              // Locked views are still reachable: selecting one shows an honest
              // "not built yet" panel rather than silently doing nothing.
              title={
                locked
                  ? `Not built yet — planned for Milestone ${capability?.milestone ?? '?'}`
                  : entry.label
              }
            >
              <span className="nav-item__icon" aria-hidden="true">
                {entry.icon}
              </span>
              <span>{entry.label}</span>
              {locked && <span className="nav-item__badge">soon</span>}
            </button>
          )
        })}
      </div>

      {props.view === 'chat' && (
        <>
          <div className="sidebar__section" style={{ paddingTop: 12 }}>
            <button className="btn btn--primary btn--block" onClick={props.onNewConversation}>
              New conversation
            </button>
            <input
              className="input"
              style={{ marginTop: 8 }}
              type="search"
              placeholder="Search conversations…"
              aria-label="Search conversations"
              value={props.searchQuery}
              onChange={(event) => props.onSearch(event.target.value)}
            />
          </div>

          <div className="sidebar__label">
            {props.searchQuery ? 'Results' : 'Conversations'}
          </div>

          <div className="sidebar__scroll">
            {props.conversations.length === 0 && (
              <p style={{ padding: '4px 8px', color: 'var(--text-faint)', fontSize: 12 }}>
                {props.searchQuery ? 'No matches.' : 'No conversations yet.'}
              </p>
            )}
            {props.conversations.map((conversation) => (
              <div
                key={conversation.id}
                className="conv"
                data-active={conversation.id === props.activeId}
              >
                {renamingId === conversation.id ? (
                  <input
                    className="input"
                    style={{ padding: '2px 6px', fontSize: 13 }}
                    autoFocus
                    value={renameValue}
                    onChange={(event) => setRenameValue(event.target.value)}
                    onBlur={() => commitRename(conversation.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') commitRename(conversation.id)
                      if (event.key === 'Escape') setRenamingId(null)
                    }}
                  />
                ) : (
                  <>
                    <button
                      className="conv__title"
                      onClick={() => props.onSelectConversation(conversation.id)}
                      onDoubleClick={() => {
                        setRenamingId(conversation.id)
                        setRenameValue(conversation.title)
                      }}
                      title={conversation.title}
                    >
                      {conversation.pinned && <span className="conv__pin">▪ </span>}
                      {conversation.title}
                    </button>
                    <span className="conv__actions">
                      <button
                        className="btn btn--ghost"
                        title={conversation.pinned ? 'Unpin' : 'Pin'}
                        aria-label={conversation.pinned ? 'Unpin conversation' : 'Pin conversation'}
                        onClick={() => props.onTogglePin(conversation.id)}
                      >
                        ▪
                      </button>
                      <button
                        className="btn btn--ghost"
                        title="Rename"
                        aria-label="Rename conversation"
                        onClick={() => {
                          setRenamingId(conversation.id)
                          setRenameValue(conversation.title)
                        }}
                      >
                        ✎
                      </button>
                      <button
                        className="btn btn--ghost"
                        title="Delete"
                        aria-label="Delete conversation"
                        onClick={() => {
                          if (
                            window.confirm(
                              `Delete "${conversation.title}"? This cannot be undone.`,
                            )
                          ) {
                            props.onDelete(conversation.id)
                          }
                        }}
                      >
                        ✕
                      </button>
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {props.view !== 'chat' && <div className="sidebar__scroll" />}
    </nav>
  )
}
