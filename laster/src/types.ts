export type Project = {
  id: string
  name: string
  path: string
  uproject: string | null
  lastOpened: string
}

export type LocalModel = {
  id: string
  name: string
  size: number
  sizeLabel: string
  parameterSize: string
  quantization: string
  codeScore: number
  local: boolean
  provider: 'ollama' | 'copilot'
  available: boolean
  description?: string
}

export type Conversation = {
  id: string
  title: string
  model: string
  createdAt: string
  updatedAt: string
  messageCount: number
}

export type ToolTrace = {
  name: string
  arguments: Record<string, unknown>
  result: string
  isError: boolean
  startedAt: string
}

export type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  meta: {
    tools?: ToolTrace[]
    model?: string
  }
  createdAt: string
}

export type PromptVersion = {
  id: string
  content: string
  source: 'draft' | 'sent' | 'original' | 'adapted'
  created_at: string
}

export type RuntimeStatus = {
  ollama: boolean
  copilot: boolean
  mcp: boolean
  unrealEditor: boolean
}

export type BootstrapData = {
  projects: Project[]
  activeProjectId: string | null
  conversations: Conversation[]
  models: LocalModel[]
  status: RuntimeStatus
  launcherCommand: string
}

export type AdaptResult = {
  prompt: string
  adapterModel: string
  targetModel: string
  estimatedCredits: number
  budgetCredits: number
  wordCount: number
}

export type ChatMode = 'chat' | 'agent'
