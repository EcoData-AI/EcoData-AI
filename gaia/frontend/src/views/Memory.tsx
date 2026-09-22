import { useCallback, useEffect, useState } from 'react'
import { api, type Memory as MemoryRow } from '@/lib/api'

/**
 * The inspectable side of Milestone 4's memory slice: search, edit, disable
 * and delete. There is no "add memory" control here on purpose — the only
 * writer is the `remember` tool, gated behind the chat turn's own
 * confirmation dialog (see docs/ARCHITECTURE.md, "Memory").
 */
export function Memory() {
  const [memories, setMemories] = useState<MemoryRow[]>([])
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  const load = useCallback(async () => {
    const result = await api.listMemories({ q: query || undefined, kind: kind || undefined })
    setMemories(result)
  }, [query, kind])

  useEffect(() => {
    const handle = setTimeout(() => void load(), 200)
    return () => clearTimeout(handle)
  }, [load])

  const toggleEnabled = async (memory: MemoryRow) => {
    const updated = await api.updateMemory(memory.id, { enabled: !memory.enabled })
    setMemories((prev) => prev.map((m) => (m.id === memory.id ? updated : m)))
  }

  const commitEdit = async (memory: MemoryRow) => {
    setEditingId(null)
    if (!editValue.trim() || editValue === memory.content) return
    const updated = await api.updateMemory(memory.id, { content: editValue.trim() })
    setMemories((prev) => prev.map((m) => (m.id === memory.id ? updated : m)))
  }

  const remove = async (memory: MemoryRow) => {
    if (!window.confirm('Delete this memory? This cannot be undone.')) return
    await api.deleteMemory(memory.id)
    setMemories((prev) => prev.filter((m) => m.id !== memory.id))
  }

  return (
    <div className="panel">
      <div className="panel__inner">
        <h2>Memory</h2>
        <p className="panel__lede">
          Facts and preferences GAIA was explicitly asked to remember. Nothing is captured
          automatically — every entry here came from a conversation where you asked GAIA to
          remember something, and approved it.
        </p>

        <div className="row" style={{ margin: '18px 0' }}>
          <input
            className="input"
            type="search"
            placeholder="Search memories…"
            aria-label="Search memories"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            style={{ flex: 1 }}
          />
          <select
            className="select"
            aria-label="Filter by kind"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">All kinds</option>
            <option value="semantic">Semantic</option>
            <option value="episodic">Episodic</option>
          </select>
        </div>

        {memories.length === 0 ? (
          <p style={{ color: 'var(--text-muted)' }}>
            {query || kind
              ? 'No matches.'
              : 'Nothing remembered yet. Ask GAIA to remember something in a conversation.'}
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Kind</th>
                <th>Content</th>
                <th>Enabled</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {memories.map((memory) => (
                <tr key={memory.id} style={memory.enabled ? undefined : { opacity: 0.5 }}>
                  <td>
                    <span className="tag tag--muted">{memory.kind}</span>
                  </td>
                  <td>
                    {editingId === memory.id ? (
                      <input
                        className="input"
                        autoFocus
                        value={editValue}
                        onChange={(event) => setEditValue(event.target.value)}
                        onBlur={() => void commitEdit(memory)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') void commitEdit(memory)
                          if (event.key === 'Escape') setEditingId(null)
                        }}
                      />
                    ) : (
                      <span
                        role="button"
                        tabIndex={0}
                        title="Click to edit"
                        style={{ cursor: 'text' }}
                        onClick={() => {
                          setEditingId(memory.id)
                          setEditValue(memory.content)
                        }}
                      >
                        {memory.content}
                      </span>
                    )}
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={memory.enabled}
                      aria-label={memory.enabled ? 'Disable memory' : 'Enable memory'}
                      onChange={() => void toggleEnabled(memory)}
                    />
                  </td>
                  <td>
                    <button
                      className="btn btn--ghost"
                      title="Delete"
                      aria-label="Delete memory"
                      onClick={() => void remove(memory)}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
