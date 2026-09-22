/**
 * Typed client for the GAIA backend.
 *
 * The base URL is relative in the browser (Vite proxies /api) and can be
 * overridden by the Tauri shell, which injects the backend's port on
 * `window.__GAIA_API_BASE__` once the child process reports it.
 */

declare global {
  interface Window {
    __GAIA_API_BASE__?: string
  }
}

export function apiBase(): string {
  return window.__GAIA_API_BASE__ ?? ''
}

/** A tool call as recorded on a persisted message — see `ToolCallView` in the
 * chat store for the equivalent shape while a turn is still streaming. */
export interface ToolCallLogEntry {
  call_id: string
  tool: string
  ok: boolean
  content: string
  display?: Record<string, unknown> | null
  error?: string | null
  arguments: Record<string, unknown>
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  sequence: number
  status: 'complete' | 'streaming' | 'stopped' | 'error'
  error: string | null
  provider_id: string | null
  model_id: string | null
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
  latency_ms: number | null
  extra: { tool_calls?: ToolCallLogEntry[] } | null
  created_at: string
}

export interface Conversation {
  id: string
  title: string
  provider_id: string | null
  model_id: string | null
  system_prompt: string | null
  project_id: string | null
  pinned: boolean
  archived: boolean
  created_at: string
  updated_at: string
  last_message_at: string | null
  message_count: number
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface Provider {
  id: string
  display_name: string
  is_local: boolean
  requires_api_key: boolean
  setup_url: string | null
  configured: boolean
  key_hint: string | null
  key_source: string | null
  base_url: string | null
  default_model: string | null
}

export interface ModelInfo {
  id: string
  name: string
  provider_id: string
  context_window: number
  max_output_tokens: number
  supports_streaming: boolean
  supports_vision: boolean
  supports_tools: boolean
  is_local: boolean
  input_cost_per_mtok: number | null
  output_cost_per_mtok: number | null
}

export interface Capability {
  key: string
  label: string
  available: boolean
  milestone: number
  detail: string
}

export interface ComponentStatus {
  name: string
  state: 'ok' | 'disabled' | 'not_configured' | 'error' | 'not_built'
  detail: string
}

export interface SystemStatus {
  version: string
  components: ComponentStatus[]
  data_dir: string
  active_provider: string | null
  active_model: string | null
}

export interface Memory {
  id: string
  kind: string
  content: string
  source: string | null
  project_id: string | null
  importance: number
  enabled: boolean
  last_used_at: string | null
  created_at: string
  updated_at: string
}

export interface Project {
  id: string
  name: string
  description: string | null
  goals: string | null
  workspace_path: string | null
  archived: boolean
  created_at: string
  updated_at: string
}

export interface ProjectTask {
  id: string
  project_id: string
  title: string
  notes: string | null
  status: string
  order_index: number
  created_at: string
  updated_at: string
}

export interface PrivacyRow {
  label: string
  location: string
  detail: string
}

export interface SettingsPayload {
  values: Record<string, unknown>
  data_dir: string
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase()}${path}`, {
      ...init,
      headers: {
        ...(init?.body && !(init.body instanceof FormData)
          ? { 'Content-Type': 'application/json' }
          : {}),
        ...init?.headers,
      },
    })
  } catch {
    // A network-level failure here almost always means the backend process is
    // not up; say that rather than surfacing "Failed to fetch".
    throw new ApiError('Could not reach the GAIA backend. Is it running?', 0)
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail)) detail = body.detail[0]?.msg ?? detail
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),

  listConversations: (query?: string) =>
    request<Conversation[]>(
      `/api/conversations${query ? `?q=${encodeURIComponent(query)}` : ''}`,
    ),

  createConversation: (title?: string) =>
    request<Conversation>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),

  getConversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),

  updateConversation: (id: string, patch: Partial<Conversation>) =>
    request<Conversation>(`/api/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  deleteConversation: (id: string) =>
    request<void>(`/api/conversations/${id}`, { method: 'DELETE' }),

  listProviders: () => request<Provider[]>('/api/providers'),

  setCredentials: (
    providerId: string,
    payload: { api_key?: string; base_url?: string; default_model?: string },
  ) =>
    request<Provider>(`/api/providers/${providerId}/credentials`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  clearCredentials: (providerId: string) =>
    request<Provider>(`/api/providers/${providerId}/credentials`, { method: 'DELETE' }),

  listModels: (providerId: string) =>
    request<ModelInfo[]>(`/api/providers/${providerId}/models`),

  testProvider: (providerId: string) =>
    request<{ state: string; detail: string; latency_ms: number | null }>(
      `/api/providers/${providerId}/test`,
      { method: 'POST' },
    ),

  getSettings: () => request<SettingsPayload>('/api/settings'),

  updateSettings: (values: Record<string, unknown>) =>
    request<SettingsPayload>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify({ values }),
    }),

  capabilities: () => request<Capability[]>('/api/capabilities'),

  systemStatus: () => request<SystemStatus>('/api/system/status'),

  privacy: () => request<PrivacyRow[]>('/api/privacy'),

  resolveToolConfirmation: (callId: string, approved: boolean) =>
    request<void>(`/api/chat/tool-confirmations/${callId}`, {
      method: 'POST',
      body: JSON.stringify({ approved }),
    }),

  listMemories: (params?: { q?: string; kind?: string }) => {
    const query = new URLSearchParams()
    if (params?.q) query.set('q', params.q)
    if (params?.kind) query.set('kind', params.kind)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request<Memory[]>(`/api/memory${suffix}`)
  },

  updateMemory: (id: string, patch: { content?: string; importance?: number; enabled?: boolean }) =>
    request<Memory>(`/api/memory/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  deleteMemory: (id: string) => request<void>(`/api/memory/${id}`, { method: 'DELETE' }),

  listProjects: (includeArchived?: boolean) =>
    request<Project[]>(`/api/projects${includeArchived ? '?include_archived=true' : ''}`),

  createProject: (payload: { name: string; description?: string; goals?: string }) =>
    request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),

  getProject: (id: string) => request<Project>(`/api/projects/${id}`),

  updateProject: (id: string, patch: Partial<Project>) =>
    request<Project>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),

  listProjectTasks: (projectId: string) =>
    request<ProjectTask[]>(`/api/projects/${projectId}/tasks`),

  createProjectTask: (projectId: string, payload: { title: string; notes?: string }) =>
    request<ProjectTask>(`/api/projects/${projectId}/tasks`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateProjectTask: (
    projectId: string,
    taskId: string,
    patch: { title?: string; notes?: string; status?: string },
  ) =>
    request<ProjectTask>(`/api/projects/${projectId}/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  deleteProjectTask: (projectId: string, taskId: string) =>
    request<void>(`/api/projects/${projectId}/tasks/${taskId}`, { method: 'DELETE' }),

  listProjectMemories: (projectId: string) =>
    request<Memory[]>(`/api/projects/${projectId}/memories`),

  createProjectMemory: (projectId: string, content: string) =>
    request<Memory>(`/api/projects/${projectId}/memories`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),

  exportBackupUrl: () => `${apiBase()}/api/backup/export`,

  importBackup: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ status: string; restart_required: boolean }>('/api/backup/import', {
      method: 'POST',
      body: form,
    })
  },
}
