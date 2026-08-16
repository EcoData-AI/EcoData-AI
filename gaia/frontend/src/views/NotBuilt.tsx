import type { Capability } from '@/lib/api'

interface Props {
  capability: Capability | undefined
  label: string
}

/**
 * Shown for every navigation entry whose feature does not exist yet.
 *
 * The product spec is explicit: a surface must never look functional when it
 * is not. This screen states plainly what is missing and when it is planned,
 * with no mock data and no disabled-looking controls that suggest otherwise.
 */
export function NotBuilt({ capability, label }: Props) {
  return (
    <div className="panel">
      <div className="panel__inner">
        <h2>{capability?.label ?? label}</h2>
        <p className="panel__lede">Not built yet.</p>

        <div className="card" style={{ marginTop: 20 }}>
          <p style={{ marginTop: 0 }}>
            {capability?.detail ?? 'This part of GAIA has not been implemented.'}
          </p>
          <p style={{ marginBottom: 0, color: 'var(--text-muted)' }}>
            Planned for <strong>Milestone {capability?.milestone ?? '—'}</strong>. Until it ships,
            nothing here is wired to a backend, and GAIA will tell you the same thing if you ask
            it in chat — it will not simulate a result.
          </p>
        </div>

        <h3>What works today</h3>
        <ul>
          <li>Streaming chat with a configurable model provider</li>
          <li>Conversation history, search, rename, pin and delete — stored locally</li>
          <li>Settings, privacy dashboard, system status and database backup</li>
        </ul>
      </div>
    </div>
  )
}
