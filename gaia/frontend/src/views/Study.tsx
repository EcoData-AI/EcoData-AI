import { useCallback, useEffect, useState } from 'react'
import {
  api,
  ApiError,
  type StudyLevel,
  type StudyPlan,
  type StudyPlanDetail,
  type StudyTopic,
} from '@/lib/api'

/**
 * Milestone 6: courses, per-topic mastery and spaced-repetition reviews. The
 * tutoring itself happens in chat — "Study now" opens (or creates) a study
 * session, a conversation whose system prompt carries the course outline,
 * progress and the Socratic rules. See docs/ARCHITECTURE.md, "Tutor and study".
 */

const LEVELS: StudyLevel[] = ['beginner', 'intermediate', 'advanced']

interface Props {
  onOpenConversation: (conversationId: string) => void
}

export function Study({ onOpenConversation }: Props) {
  const [plans, setPlans] = useState<StudyPlan[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [subject, setSubject] = useState('')
  const [goal, setGoal] = useState('')
  const [level, setLevel] = useState<StudyLevel | ''>('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setPlans(await api.listStudyPlans())
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const create = async () => {
    if (!subject.trim() || creating) return
    setCreating(true)
    setError(null)
    try {
      const plan = await api.createStudyPlan({
        subject: subject.trim(),
        goal: goal.trim() || undefined,
        level: level || null,
      })
      setSubject('')
      setGoal('')
      setLevel('')
      await load()
      setSelectedId(plan.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create that course.')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="panel">
      <div className="panel__inner">
        <h2>Study</h2>
        <p className="panel__lede">
          Courses GAIA tutors you through. It assesses your level, asks rather than tells, grades
          your answers, and brings topics back for review just before you'd forget them. You can
          also just ask in chat — "teach me game theory" — and approve the course it proposes.
        </p>

        <div className="card" style={{ margin: '18px 0' }}>
          <div className="stack" style={{ gap: 8 }}>
            <input
              className="input"
              placeholder="What do you want to learn? e.g. Game theory"
              aria-label="Subject"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void create()
              }}
            />
            <input
              className="input"
              placeholder="Your goal (optional) — e.g. read economics papers comfortably"
              aria-label="Goal"
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
            />
            <div className="row">
              <select
                className="select"
                aria-label="Level"
                value={level}
                onChange={(event) => setLevel(event.target.value as StudyLevel | '')}
              >
                <option value="">Assess my level</option>
                {LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
              <button
                className="btn btn--primary"
                onClick={() => void create()}
                disabled={creating || !subject.trim()}
              >
                {creating ? 'Designing the course…' : 'Create course'}
              </button>
            </div>
            <span className="field__hint">
              The outline is written by your configured model, so this takes as long as one reply.
            </span>
          </div>
        </div>

        {error && (
          <div className="notice notice--error" style={{ marginBottom: 16 }}>
            <div className="notice__body">{error}</div>
          </div>
        )}

        {plans.length === 0 ? (
          <p style={{ color: 'var(--text-muted)' }}>No courses yet.</p>
        ) : (
          <div className="row" style={{ flexWrap: 'wrap', marginBottom: 20 }}>
            {plans.map((plan) => (
              <button
                key={plan.id}
                className="btn"
                style={
                  plan.id === selectedId
                    ? { borderColor: 'var(--accent)', color: 'var(--accent)', fontWeight: 600 }
                    : undefined
                }
                onClick={() => setSelectedId(plan.id)}
              >
                {plan.subject}{' '}
                <span className="tag tag--muted">
                  {plan.mastered_count}/{plan.topic_count}
                </span>
                {plan.due_count > 0 && <span className="tag tag--warn"> {plan.due_count} due</span>}
              </button>
            ))}
          </div>
        )}

        {selectedId && (
          <CourseDetail
            key={selectedId}
            planId={selectedId}
            onOpenConversation={onOpenConversation}
            onChanged={() => void load()}
            onDeleted={() => {
              setSelectedId(null)
              void load()
            }}
          />
        )}
      </div>
    </div>
  )
}

function CourseDetail({
  planId,
  onOpenConversation,
  onChanged,
  onDeleted,
}: {
  planId: string
  onOpenConversation: (conversationId: string) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [plan, setPlan] = useState<StudyPlanDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api
      .getStudyPlan(planId)
      .then(setPlan)
      .catch(() => setError('Could not load that course.'))
  }, [planId])

  if (error) {
    return (
      <div className="notice notice--error">
        <div className="notice__body">{error}</div>
      </div>
    )
  }
  if (!plan) return null

  const apply = (updated: StudyPlanDetail) => {
    setPlan(updated)
    onChanged()
  }

  const openSession = async (fresh: boolean) => {
    if (!fresh && plan.latest_conversation_id) {
      onOpenConversation(plan.latest_conversation_id)
      return
    }
    const conversation = await api.startStudySession(plan.id)
    onOpenConversation(conversation.id)
  }

  const setLevel = async (level: StudyLevel) => apply(await api.updateStudyPlan(plan.id, { level }))

  const selfGrade = async (topic: string, score: number) =>
    apply(await api.reviewStudyTopic(plan.id, { topic, score }))

  const reset = async () => {
    if (!window.confirm(`Reset all progress in "${plan.subject}"? The outline is kept.`)) return
    apply(await api.resetStudyPlan(plan.id))
  }

  const remove = async () => {
    if (
      !window.confirm(
        `Delete "${plan.subject}" and its progress? Its study sessions stay, as ordinary conversations.`,
      )
    )
      return
    await api.deleteStudyPlan(plan.id)
    onDeleted()
  }

  const modules = plan.outline.modules.map((module) => ({
    title: module.title,
    topics: plan.topics.filter((t) => t.module === module.title),
  }))
  const percent = plan.topic_count ? Math.round((plan.mastered_count / plan.topic_count) * 100) : 0

  return (
    <div className="card">
      <div className="row row--between" style={{ alignItems: 'flex-start' }}>
        <div>
          <h3 style={{ margin: 0 }}>{plan.subject}</h3>
          {plan.goal && <p style={{ margin: '4px 0 0', color: 'var(--text-muted)' }}>{plan.goal}</p>}
        </div>
        <select
          className="select"
          aria-label="Course level"
          value={plan.level ?? ''}
          onChange={(event) => void setLevel(event.target.value as StudyLevel)}
        >
          {!plan.level && <option value="">Not assessed yet</option>}
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
      </div>

      <div style={{ margin: '14px 0 6px' }}>
        <div
          role="progressbar"
          aria-label="Topics mastered"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          style={{
            height: 8,
            borderRadius: 999,
            background: 'var(--border)',
            overflow: 'hidden',
          }}
        >
          <div style={{ width: `${percent}%`, height: '100%', background: 'var(--accent)' }} />
        </div>
        <div className="row row--between" style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          <span>
            {plan.mastered_count} of {plan.topic_count} topics mastered
            {plan.due_count > 0 && ` · ${plan.due_count} due for review`}
          </span>
          <span>{plan.current_topic ? `Next: ${plan.current_topic}` : 'Course complete'}</span>
        </div>
      </div>

      <div className="row" style={{ margin: '12px 0 16px', flexWrap: 'wrap' }}>
        <button className="btn btn--primary" onClick={() => void openSession(false)}>
          {plan.latest_conversation_id ? 'Continue studying' : 'Start studying'}
        </button>
        {plan.latest_conversation_id && (
          <button className="btn" onClick={() => void openSession(true)}>
            New session
          </button>
        )}
        <button className="btn" onClick={() => void reset()}>
          Reset progress
        </button>
        <button className="btn btn--danger" onClick={() => void remove()}>
          Delete course
        </button>
      </div>

      {modules.map((module) => (
        <div key={module.title} style={{ marginBottom: 14 }}>
          <h4 style={{ margin: '0 0 6px' }}>{module.title}</h4>
          <table className="table">
            <thead>
              <tr>
                <th>Topic</th>
                <th>Mastery</th>
                <th>Next review</th>
                <th title="Grade yourself without the tutor: 0 = no idea, 5 = easy">Self-grade</th>
              </tr>
            </thead>
            <tbody>
              {module.topics.map((topic) => (
                <TopicRow key={topic.topic} topic={topic} onGrade={selfGrade} />
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

function TopicRow({
  topic,
  onGrade,
}: {
  topic: StudyTopic
  onGrade: (topic: string, score: number) => Promise<void>
}) {
  return (
    <tr>
      <td>
        {topic.topic}
        {topic.last_note && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{topic.last_note}</div>
        )}
      </td>
      <td>
        {topic.attempts === 0 ? (
          <span className="tag tag--muted">not started</span>
        ) : (
          <span className={topic.mastered ? 'tag tag--ok' : 'tag'}>
            {Math.round(topic.mastery * 100)}%
          </span>
        )}
      </td>
      <td>
        {topic.due ? (
          <span className="tag tag--warn">due now</span>
        ) : (
          <span style={{ fontSize: 13 }}>{formatReview(topic.next_review_at)}</span>
        )}
      </td>
      <td>
        <select
          className="select"
          aria-label={`Self-grade ${topic.topic}`}
          value=""
          onChange={(event) => {
            if (event.target.value !== '') void onGrade(topic.topic, Number(event.target.value))
          }}
          style={{ fontSize: 12 }}
        >
          <option value="">—</option>
          {[0, 1, 2, 3, 4, 5].map((score) => (
            <option key={score} value={score}>
              {score}
            </option>
          ))}
        </select>
      </td>
    </tr>
  )
}

export function formatReview(iso: string | null, now: Date = new Date()): string {
  if (!iso) return '—'
  const days = Math.round((new Date(iso).getTime() - now.getTime()) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'tomorrow'
  return `in ${days} days`
}
