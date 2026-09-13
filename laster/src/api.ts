import type {
  AdaptResult,
  BootstrapData,
  ChatMode,
  Conversation,
  Message,
  Project,
  PromptVersion,
} from './types'

const query = new URLSearchParams(window.location.search)
const queryToken = query.get('token')
if (queryToken) {
  localStorage.setItem('laster:access-token', queryToken)
  query.delete('token')
  const remainingQuery = query.toString()
  window.history.replaceState(
    null,
    '',
    `${window.location.pathname}${remainingQuery ? `?${remainingQuery}` : ''}${window.location.hash}`,
  )
}
const accessToken = queryToken || localStorage.getItem('laster:access-token')

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken ? { 'X-Laster-Token': accessToken } : {}),
      ...options?.headers,
    },
  })
  const payload = (await response.json()) as T & { error?: string }
  if (!response.ok) {
    throw new Error(payload.error || `Erreur HTTP ${response.status}`)
  }
  return payload
}

export const api = {
  bootstrap: () => request<BootstrapData>('/api/bootstrap'),

  listConversations: (projectId: string) =>
    request<{ conversations: Conversation[] }>(
      `/api/conversations?project_id=${encodeURIComponent(projectId)}`,
    ),

  createConversation: (projectId: string, model: string) =>
    request<{ conversation: Conversation }>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify({ projectId, model }),
    }),

  deleteConversation: (conversationId: string) =>
    request<{ ok: boolean }>(`/api/conversations/${conversationId}`, {
      method: 'DELETE',
    }),

  listMessages: (conversationId: string) =>
    request<{ messages: Message[] }>(
      `/api/conversations/${conversationId}/messages`,
    ),

  setProject: (projectId: string) =>
    request<{ ok: boolean }>('/api/settings/project', {
      method: 'POST',
      body: JSON.stringify({ projectId }),
    }),

  addProject: (path: string) =>
    request<{ project: Project }>('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  browseProject: () =>
    request<{ project?: Project; cancelled?: boolean }>('/api/projects/browse', {
      method: 'POST',
      body: '{}',
    }),

  listPrompts: (projectId: string) =>
    request<{ prompts: PromptVersion[] }>(
      `/api/prompts?project_id=${encodeURIComponent(projectId)}`,
    ),

  savePrompt: (projectId: string, content: string, source = 'draft') =>
    request<{ ok: boolean }>('/api/prompts', {
      method: 'POST',
      body: JSON.stringify({ projectId, content, source }),
    }),

  adaptPrompt: (
    projectId: string,
    targetModel: string,
    prompt: string,
    intent: string,
  ) =>
    request<AdaptResult>('/api/adapt', {
      method: 'POST',
      body: JSON.stringify({ projectId, targetModel, prompt, intent }),
    }),

  chat: (
    conversationId: string,
    projectId: string,
    model: string,
    mode: ChatMode,
    content: string,
  ) =>
    request<{ userMessage: Message; assistantMessage: Message }>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ conversationId, projectId, model, mode, content }),
    }),
}
