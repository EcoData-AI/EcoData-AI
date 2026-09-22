import { useCallback, useEffect, useState } from 'react'
import { api, type Memory, type Project, type ProjectTask } from '@/lib/api'

const TASK_STATUSES = ['todo', 'doing', 'done']

export function Projects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [newProjectName, setNewProjectName] = useState('')

  const load = useCallback(async () => {
    const result = await api.listProjects()
    setProjects(result)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const createProject = async () => {
    const name = newProjectName.trim()
    if (!name) return
    const project = await api.createProject({ name })
    setNewProjectName('')
    setProjects((prev) => [project, ...prev])
    setSelectedId(project.id)
  }

  const selected = projects.find((p) => p.id === selectedId)

  return (
    <div className="panel">
      <div className="panel__inner">
        <h2>Projects</h2>
        <p className="panel__lede">
          Goals, tasks and project-scoped memory. Assign a conversation to a project from the
          chat topbar to bring its goals and open tasks into context.
        </p>

        <div className="row" style={{ margin: '18px 0' }}>
          <input
            className="input"
            placeholder="New project name…"
            value={newProjectName}
            onChange={(event) => setNewProjectName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void createProject()
            }}
            style={{ flex: 1 }}
          />
          <button className="btn btn--primary" onClick={() => void createProject()}>
            Create
          </button>
        </div>

        {projects.length === 0 ? (
          <p style={{ color: 'var(--text-muted)' }}>No projects yet.</p>
        ) : (
          <div className="row" style={{ flexWrap: 'wrap', marginBottom: 20 }}>
            {projects.map((project) => (
              <button
                key={project.id}
                className="btn"
                style={
                  project.id === selectedId
                    ? { borderColor: 'var(--accent)', color: 'var(--accent)', fontWeight: 600 }
                    : undefined
                }
                onClick={() => setSelectedId(project.id)}
              >
                {project.name}
              </button>
            ))}
          </div>
        )}

        {selected && (
          <ProjectDetail
            key={selected.id}
            project={selected}
            onDeleted={() => {
              setProjects((prev) => prev.filter((p) => p.id !== selected.id))
              setSelectedId(null)
            }}
            onUpdated={(updated) =>
              setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
            }
          />
        )}
      </div>
    </div>
  )
}

function ProjectDetail({
  project,
  onDeleted,
  onUpdated,
}: {
  project: Project
  onDeleted: () => void
  onUpdated: (project: Project) => void
}) {
  const [description, setDescription] = useState(project.description ?? '')
  const [goals, setGoals] = useState(project.goals ?? '')
  const [saved, setSaved] = useState(false)

  const [tasks, setTasks] = useState<ProjectTask[]>([])
  const [newTask, setNewTask] = useState('')

  const [memories, setMemories] = useState<Memory[]>([])
  const [newMemory, setNewMemory] = useState('')

  useEffect(() => {
    void api.listProjectTasks(project.id).then(setTasks)
    void api.listProjectMemories(project.id).then(setMemories)
  }, [project.id])

  const saveDetails = async () => {
    const updated = await api.updateProject(project.id, { description, goals })
    onUpdated(updated)
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  const addTask = async () => {
    const title = newTask.trim()
    if (!title) return
    const task = await api.createProjectTask(project.id, { title })
    setTasks((prev) => [...prev, task])
    setNewTask('')
  }

  const setTaskStatus = async (task: ProjectTask, status: string) => {
    const updated = await api.updateProjectTask(project.id, task.id, { status })
    setTasks((prev) => prev.map((t) => (t.id === task.id ? updated : t)))
  }

  const removeTask = async (task: ProjectTask) => {
    await api.deleteProjectTask(project.id, task.id)
    setTasks((prev) => prev.filter((t) => t.id !== task.id))
  }

  const addMemory = async () => {
    const content = newMemory.trim()
    if (!content) return
    const memory = await api.createProjectMemory(project.id, content)
    setMemories((prev) => [...prev, memory])
    setNewMemory('')
  }

  const removeMemory = async (memory: Memory) => {
    if (!window.confirm('Delete this project memory? This cannot be undone.')) return
    await api.deleteMemory(memory.id)
    setMemories((prev) => prev.filter((m) => m.id !== memory.id))
  }

  const archiveProject = async () => {
    const updated = await api.updateProject(project.id, { archived: !project.archived })
    onUpdated(updated)
  }

  const deleteProject = async () => {
    if (
      !window.confirm(
        `Delete "${project.name}"? Its tasks and memory are deleted too. Conversations assigned to it are kept, just unassigned.`,
      )
    ) {
      return
    }
    await api.deleteProject(project.id)
    onDeleted()
  }

  return (
    <div className="card" style={{ marginTop: 8 }}>
      <h3>{project.name}</h3>

      <label className="field">
        <span className="field__label">Description</span>
        <textarea
          className="textarea"
          rows={2}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>

      <label className="field">
        <span className="field__label">Goals</span>
        <textarea
          className="textarea"
          rows={2}
          value={goals}
          onChange={(event) => setGoals(event.target.value)}
        />
      </label>

      <div className="row">
        <button className="btn btn--primary" onClick={() => void saveDetails()}>
          Save
        </button>
        {saved && <span style={{ color: 'var(--ok)' }}>Saved.</span>}
      </div>

      <h3>Tasks</h3>
      <div className="stack">
        {tasks.map((task) => (
          <div key={task.id} className="row" style={{ gap: 8 }}>
            <select
              className="select"
              value={task.status}
              onChange={(event) => void setTaskStatus(task, event.target.value)}
              style={{ width: 100 }}
            >
              {TASK_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <span style={{ flex: 1 }}>{task.title}</span>
            <button className="btn btn--ghost" aria-label="Delete task" onClick={() => void removeTask(task)}>
              ✕
            </button>
          </div>
        ))}
        {tasks.length === 0 && <p style={{ color: 'var(--text-muted)' }}>No tasks yet.</p>}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <input
          className="input"
          placeholder="New task…"
          value={newTask}
          onChange={(event) => setNewTask(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void addTask()
          }}
          style={{ flex: 1 }}
        />
        <button className="btn" onClick={() => void addTask()}>
          Add
        </button>
      </div>

      <h3>Project memory</h3>
      <div className="stack">
        {memories.map((memory) => (
          <div key={memory.id} className="row" style={{ gap: 8 }}>
            <span style={{ flex: 1 }}>{memory.content}</span>
            <button
              className="btn btn--ghost"
              aria-label="Delete memory"
              onClick={() => void removeMemory(memory)}
            >
              ✕
            </button>
          </div>
        ))}
        {memories.length === 0 && (
          <p style={{ color: 'var(--text-muted)' }}>Nothing remembered for this project yet.</p>
        )}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <input
          className="input"
          placeholder="Something to remember for this project…"
          value={newMemory}
          onChange={(event) => setNewMemory(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void addMemory()
          }}
          style={{ flex: 1 }}
        />
        <button className="btn" onClick={() => void addMemory()}>
          Add
        </button>
      </div>

      <div className="row" style={{ marginTop: 20 }}>
        <button className="btn" onClick={() => void archiveProject()}>
          {project.archived ? 'Unarchive' : 'Archive'}
        </button>
        <button className="btn btn--danger" onClick={() => void deleteProject()}>
          Delete project
        </button>
      </div>
    </div>
  )
}
