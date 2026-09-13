import { startTransition, useEffect, useRef, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  Code2,
  Copy,
  Cpu,
  Database,
  FolderOpen,
  Gauge,
  HardDrive,
  History,
  Menu,
  MessageSquarePlus,
  PanelLeftClose,
  PlugZap,
  Plus,
  RefreshCw,
  Rocket,
  Send,
  Settings2,
  Sparkles,
  SquareTerminal,
  Trash2,
  WandSparkles,
  X,
  Zap,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from './api'
import type {
  AdaptResult,
  BootstrapData,
  ChatMode,
  Conversation,
  Message,
  Project,
  PromptVersion,
} from './types'
import './App.css'

const starterPrompts = [
  {
    icon: Code2,
    label: 'Inspecter le gameplay',
    prompt: 'Analyse le gameplay principal de ce projet et signale les trois risques techniques les plus importants.',
  },
  {
    icon: PlugZap,
    label: 'Vérifier Unreal',
    prompt: 'Vérifie l’état du projet Unreal, les plugins actifs et les dernières erreurs dans les logs.',
  },
  {
    icon: Gauge,
    label: 'Préparer une modification',
    prompt: 'Inspecte le projet et propose un plan court et vérifiable pour la prochaine amélioration de gameplay.',
  },
]

const guideSteps = [
  {
    eyebrow: 'Étape 1 sur 7',
    title: 'Vérifie les briques locales',
    body: 'Python, Node.js et Ollama doivent répondre. Le modèle gpt-oss:20b reste local et ne consomme aucun compte externe.',
    detail: 'Laster vérifie ces services à chaque ouverture.',
  },
  {
    eyebrow: 'Étape 2 sur 7',
    title: 'Active les plugins Unreal',
    body: 'Dans Plugins, active Model Context Protocol, Editor Toolset, Python Editor Script Plugin et Terminal.',
    detail: 'Redémarre Unreal une fois les plugins activés.',
  },
  {
    eyebrow: 'Étape 3 sur 7',
    title: 'Démarre le MCP de l’éditeur',
    body: 'Dans Model Context Protocol, garde le port 8000, le chemin /mcp, Auto Start Server et Tool Search activés.',
    detail: 'Le serveur reste limité à 127.0.0.1.',
  },
  {
    eyebrow: 'Étape 4 sur 7',
    title: 'Choisis PowerShell 7',
    body: 'Dans Project Settings > Terminal, renseigne le chemin de pwsh.exe comme exécutable Shell.',
    detail: 'Le terminal intégré pourra lancer Laster directement.',
  },
  {
    eyebrow: 'Étape 5 sur 7',
    title: 'Ajoute une seule commande',
    body: 'Dans Startup Commands, remplace les anciennes lignes par le lanceur Laster ci-dessous.',
    detail: `& 'C:\\Projet\\onepiece\\start-laster.ps1'`,
  },
  {
    eyebrow: 'Étape 6 sur 7',
    title: 'Sélectionne le projet actif',
    body: 'Utilise le sélecteur en haut à gauche. Les conversations et outils MCP suivent automatiquement le projet choisi.',
    detail: 'Les chemins sont validés avant d’être enregistrés.',
  },
  {
    eyebrow: 'Étape 7 sur 7',
    title: 'Contrôle les trois voyants',
    body: 'Ollama et MCP doivent être verts. Unreal devient vert dès que l’éditeur et son serveur MCP sont ouverts.',
    detail: 'Tu peux ensuite travailler en mode Chat ou Agent.',
  },
]

function formatRelativeDate(value: string) {
  const date = new Date(value)
  const seconds = Math.max(1, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return 'à l’instant'
  if (seconds < 3600) return `il y a ${Math.floor(seconds / 60)} min`
  if (seconds < 86400) return `il y a ${Math.floor(seconds / 3600)} h`
  return date.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })
}

function shortPath(path: string) {
  const parts = path.split(/[\\/]/)
  return parts.length > 3 ? `…\\${parts.slice(-3).join('\\')}` : path
}

function GuideShot({ step }: { step: number }) {
  const icons = [HardDrive, PlugZap, Settings2, SquareTerminal, Code2, FolderOpen, Zap]
  const Icon = icons[step] || Rocket
  const labels = [
    ['Python 3.10', 'Ollama 0.34', 'gpt-oss:20b'],
    ['Model Context Protocol', 'Editor Toolset', 'Terminal'],
    ['Port 8000', '/mcp', 'Tool Search'],
    ['pwsh.exe', 'Cascadia Mono', 'ConPTY'],
    ['Startup Commands', 'start-laster.ps1', 'Une seule ligne'],
    ['onepiece', 'Unreal Engine 5.8', 'Projet actif'],
    ['Ollama', 'MCP local', 'Unreal Editor'],
  ][step] || []

  return (
    <main className={`guide-shot guide-shot-${step + 1}`}>
      <div className="shot-window-bar">
        <span />
        <span />
        <span />
        <strong>LASTER / CONFIGURATION</strong>
      </div>
      <div className="shot-body">
        <div className="shot-rail">
          <div className="shot-logo">L/</div>
          {[1, 2, 3, 4].map((item) => <i key={item} />)}
        </div>
        <div className="shot-content">
          <div className="shot-kicker">{guideSteps[step]?.eyebrow}</div>
          <Icon size={58} strokeWidth={1.35} />
          <h1>{guideSteps[step]?.title}</h1>
          <div className="shot-lines">
            {labels.map((label, index) => (
              <div className="shot-line" key={label}>
                <span className={index === 2 ? 'amber' : ''}><Check size={16} /></span>
                <strong>{label}</strong>
                <em>{index === 2 && step === 6 ? 'EN ATTENTE' : 'ACTIF'}</em>
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  )
}

function StatusDot({ active, label }: { active: boolean; label: string }) {
  return (
    <span className={`status-dot ${active ? 'is-active' : ''}`} title={`${label}: ${active ? 'actif' : 'indisponible'}`}>
      <i />
      {label}
    </span>
  )
}

function MessageBlock({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false)

  async function copyMessage() {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }

  return (
    <article className={`message message-${message.role}`}>
      <div className="message-gutter">
        <span>{message.role === 'assistant' ? <Bot size={18} /> : 'N'}</span>
      </div>
      <div className="message-body">
        <div className="message-heading">
          <strong>{message.role === 'assistant' ? 'Laster' : 'Vous'}</strong>
          <span>{formatRelativeDate(message.createdAt)}</span>
          <button className="icon-button subtle" onClick={copyMessage} title="Copier le message">
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </button>
        </div>
        {message.role === 'assistant' ? (
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        ) : (
          <p className="user-copy">{message.content}</p>
        )}
        {!!message.meta.tools?.length && (
          <details className="tool-trace">
            <summary><Zap size={14} /> {message.meta.tools.length} outil{message.meta.tools.length > 1 ? 's' : ''} utilisé{message.meta.tools.length > 1 ? 's' : ''}</summary>
            <div className="tool-list">
              {message.meta.tools.map((tool, index) => (
                <div className="tool-row" key={`${tool.name}-${index}`}>
                  <span className={tool.isError ? 'tool-error' : 'tool-ok'}>{tool.isError ? <CircleAlert size={14} /> : <Check size={14} />}</span>
                  <code>{tool.name}</code>
                  <span>{Object.keys(tool.arguments).join(', ') || 'sans argument'}</span>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>
    </article>
  )
}

function SetupTour({ onClose, launcherCommand }: { onClose: () => void; launcherCommand: string }) {
  const [step, setStep] = useState(0)
  const current = guideSteps[step]
  const currentDetail = step === 4 ? launcherCommand : current.detail

  function finish() {
    localStorage.setItem('laster:tour-complete', 'true')
    onClose()
  }

  return (
    <div className="modal-layer setup-layer" role="dialog" aria-modal="true" aria-label="Configuration de Laster">
      <section className="setup-tour">
        <button className="icon-button setup-close" onClick={finish} title="Fermer le guide"><X size={20} /></button>
        <div className="setup-copy">
          <div className="setup-brand"><span>L/</span> LASTER SETUP</div>
          <div className="setup-progress" aria-label={`Étape ${step + 1} sur 7`}>
            {guideSteps.map((_, index) => <i key={index} className={index <= step ? 'is-done' : ''} />)}
          </div>
          <span className="eyebrow">{current.eyebrow}</span>
          <h2>{current.title}</h2>
          <p>{current.body}</p>
          <div className="setup-detail">
            {step === 4 ? <code>{currentDetail}</code> : <><Check size={17} /> <span>{currentDetail}</span></>}
          </div>
          <div className="setup-nav">
            <button className="icon-button bordered" onClick={() => setStep((value) => Math.max(0, value - 1))} disabled={step === 0} title="Étape précédente"><ArrowLeft size={20} /></button>
            <span>{String(step + 1).padStart(2, '0')} / 07</span>
            {step < guideSteps.length - 1 ? (
              <button className="button primary" onClick={() => setStep((value) => value + 1)}>Suivant <ArrowRight size={18} /></button>
            ) : (
              <button className="button primary" onClick={finish}>Ouvrir Laster <Rocket size={18} /></button>
            )}
          </div>
        </div>
        <div className="setup-visual">
          <img src={`/guide/step-${step + 1}.png`} alt={`Aperçu de configuration : ${current.title}`} />
          <div className="visual-caption"><span>CAPTURE {String(step + 1).padStart(2, '0')}</span><strong>{current.title}</strong></div>
        </div>
      </section>
    </div>
  )
}

function ProjectDialog({ projects, onClose, onSelect, onAdded }: {
  projects: Project[]
  onClose: () => void
  onSelect: (project: Project) => void
  onAdded: (project: Project) => void
}) {
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function addPath() {
    if (!path.trim()) return
    setBusy(true)
    setError('')
    try {
      const { project } = await api.addProject(path.trim())
      onAdded(project)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Projet invalide')
    } finally {
      setBusy(false)
    }
  }

  async function browse() {
    setBusy(true)
    setError('')
    try {
      const result = await api.browseProject()
      if (result.project) onAdded(result.project)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Sélecteur indisponible')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-label="Choisir un projet">
      <section className="dialog project-dialog">
        <header>
          <div><span className="eyebrow">ESPACE DE TRAVAIL</span><h2>Choisir un projet</h2></div>
          <button className="icon-button" onClick={onClose} title="Fermer"><X size={19} /></button>
        </header>
        <div className="project-list">
          {projects.map((project) => (
            <button key={project.id} className="project-row" onClick={() => onSelect(project)}>
              <FolderOpen size={19} />
              <span><strong>{project.name}</strong><small>{shortPath(project.path)}</small></span>
              {project.uproject && <em>UNREAL</em>}
              <ArrowRight size={17} />
            </button>
          ))}
        </div>
        <div className="path-entry">
          <label htmlFor="project-path">Ajouter un dossier</label>
          <div>
            <input id="project-path" value={path} onChange={(event) => setPath(event.target.value)} placeholder="C:\Projets\MonJeu" />
            <button className="button secondary" onClick={browse} disabled={busy}><FolderOpen size={17} /> Parcourir</button>
            <button className="button primary" onClick={addPath} disabled={busy || !path.trim()}><Plus size={17} /> Ajouter</button>
          </div>
          {error && <p className="form-error"><CircleAlert size={15} /> {error}</p>}
        </div>
      </section>
    </div>
  )
}

function PromptDrawer({ projectId, onClose, onRestore }: {
  projectId: string
  onClose: () => void
  onRestore: (content: string) => void
}) {
  const [prompts, setPrompts] = useState<PromptVersion[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listPrompts(projectId)
      .then(({ prompts: values }) => setPrompts(values))
      .finally(() => setLoading(false))
  }, [projectId])

  return (
    <aside className="prompt-drawer">
      <header>
        <div><span className="eyebrow">MÉMOIRE LOCALE</span><h2>Anciens prompts</h2></div>
        <button className="icon-button" onClick={onClose} title="Fermer"><X size={19} /></button>
      </header>
      <div className="prompt-list">
        {loading && <div className="empty-small"><RefreshCw className="spin" size={18} /> Chargement</div>}
        {!loading && !prompts.length && <div className="empty-small">Aucun prompt enregistré pour ce projet.</div>}
        {prompts.map((prompt) => (
          <button className="prompt-version" key={prompt.id} onClick={() => onRestore(prompt.content)}>
            <span><Clock3 size={14} /> {formatRelativeDate(prompt.created_at)} <em>{prompt.source}</em></span>
            <p>{prompt.content}</p>
            <strong>Restaurer <ArrowRight size={14} /></strong>
          </button>
        ))}
      </div>
    </aside>
  )
}

function AdaptDialog({ projectId, model, prompt, onClose, onApply }: {
  projectId: string
  model: string
  prompt: string
  onClose: () => void
  onApply: (content: string) => void
}) {
  const [intent, setIntent] = useState('')
  const [result, setResult] = useState<AdaptResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function adapt() {
    setBusy(true)
    setError('')
    try {
      setResult(await api.adaptPrompt(projectId, model, prompt, intent))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Adaptation impossible')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-label="Adapter le prompt">
      <section className="dialog adapt-dialog">
        <header>
          <div><span className="eyebrow">PROMPT ROUTER</span><h2>Adapter au bon modèle</h2></div>
          <div className="credit-cap"><Gauge size={16} /><strong>{result?.estimatedCredits ?? 0}</strong> / 200 CR</div>
          <button className="icon-button" onClick={onClose} title="Fermer"><X size={19} /></button>
        </header>
        <div className="adapt-grid">
          <div className="adapt-source">
            <label>Prompt actuel</label>
            <div>{prompt}</div>
            <label htmlFor="developer-intent">Nouvelles envies du dev</label>
            <textarea id="developer-intent" value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="Ex. privilégier une solution Blueprint, conserver les API publiques…" />
          </div>
          <div className={`adapt-output ${result ? 'has-result' : ''}`}>
            {result ? (
              <>
                <div className="adapt-meta"><Sparkles size={16} /><span>Adapté par <strong>{result.adapterModel}</strong> pour <strong>{result.targetModel}</strong></span><em>{result.wordCount} mots</em></div>
                <p>{result.prompt}</p>
              </>
            ) : (
              <div className="adapt-placeholder"><WandSparkles size={30} /><span>Le meilleur modèle local sera choisi automatiquement.</span><small>Coût estimé : 0 crédit externe</small></div>
            )}
          </div>
        </div>
        {error && <p className="form-error"><CircleAlert size={15} /> {error}</p>}
        <footer>
          <span><Cpu size={15} /> Cible : {model}</span>
          {!result ? (
            <button className="button primary" onClick={adapt} disabled={busy || !prompt.trim()}>{busy ? <RefreshCw className="spin" size={17} /> : <WandSparkles size={17} />} Adapter</button>
          ) : (
            <button className="button primary" onClick={() => onApply(result.prompt)}><Check size={17} /> Utiliser ce prompt</button>
          )}
        </footer>
      </section>
    </div>
  )
}

function App() {
  const [data, setData] = useState<BootstrapData | null>(null)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [model, setModel] = useState('')
  const [mode, setMode] = useState<ChatMode>('chat')
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [projectDialogOpen, setProjectDialogOpen] = useState(false)
  const [promptDrawerOpen, setPromptDrawerOpen] = useState(false)
  const [adaptDialogOpen, setAdaptDialogOpen] = useState(false)
  const [setupOpen, setSetupOpen] = useState(() => localStorage.getItem('laster:tour-complete') !== 'true')
  const messageEndRef = useRef<HTMLDivElement>(null)
  const textAreaRef = useRef<HTMLTextAreaElement>(null)

  const activeProject = data?.projects.find((project) => project.id === data.activeProjectId) || null
  const activeConversation = conversations.find((conversation) => conversation.id === activeConversationId) || null
  const selectedModel = data?.models.find((item) => item.id === model) || null
  const localModels = data?.models.filter((item) => item.provider === 'ollama') || []
  const copilotModels = data?.models.filter((item) => item.provider === 'copilot') || []

  useEffect(() => {
    api.bootstrap()
      .then((bootstrap) => {
        setData(bootstrap)
        setConversations(bootstrap.conversations)
        const preferred = bootstrap.models.find((item) => item.id === 'gpt-oss:20b') || bootstrap.models[0]
        setModel(preferred?.id || '')
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : 'Laster ne répond pas'))
  }, [])

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  useEffect(() => {
    if (!activeProject || draft.trim().length < 8) return
    const timeout = window.setTimeout(() => {
      api.savePrompt(activeProject.id, draft).catch(() => undefined)
    }, 1200)
    return () => window.clearTimeout(timeout)
  }, [activeProject, draft])

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        newConversation()
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [])

  async function refreshConversations(projectId: string) {
    const result = await api.listConversations(projectId)
    setConversations(result.conversations)
  }

  async function selectProject(project: Project) {
    setError('')
    try {
      await api.setProject(project.id)
      const result = await api.listConversations(project.id)
      setData((current) => current ? { ...current, activeProjectId: project.id } : current)
      setConversations(result.conversations)
      setActiveConversationId(null)
      setMessages([])
      setProjectDialogOpen(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Projet inaccessible')
    }
  }

  async function addProject(project: Project) {
    setData((current) => current ? {
      ...current,
      projects: [project, ...current.projects.filter((item) => item.id !== project.id)],
      activeProjectId: project.id,
    } : current)
    setConversations([])
    setMessages([])
    setActiveConversationId(null)
    setProjectDialogOpen(false)
  }

  async function openConversation(conversation: Conversation) {
    setError('')
    setActiveConversationId(conversation.id)
    setModel(conversation.model || model)
    setSidebarOpen(false)
    try {
      const result = await api.listMessages(conversation.id)
      startTransition(() => setMessages(result.messages))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Conversation inaccessible')
    }
  }

  function newConversation() {
    setActiveConversationId(null)
    setMessages([])
    setDraft('')
    setSidebarOpen(false)
    textAreaRef.current?.focus()
  }

  async function removeConversation(event: React.MouseEvent, conversation: Conversation) {
    event.stopPropagation()
    if (!window.confirm(`Supprimer « ${conversation.title} » ?`)) return
    try {
      await api.deleteConversation(conversation.id)
      setConversations((current) => current.filter((item) => item.id !== conversation.id))
      if (activeConversationId === conversation.id) newConversation()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Suppression impossible')
    }
  }

  async function sendMessage() {
    const content = draft.trim()
    if (!content || !activeProject || !model || sending) return
    setSending(true)
    setError('')
    setDraft('')
    const optimistic: Message = {
      id: `pending-${Date.now()}`,
      role: 'user',
      content,
      meta: {},
      createdAt: new Date().toISOString(),
    }
    setMessages((current) => [...current, optimistic])
    try {
      let conversationId = activeConversationId
      if (!conversationId) {
        const result = await api.createConversation(activeProject.id, model)
        conversationId = result.conversation.id
        setActiveConversationId(conversationId)
      }
      const result = await api.chat(conversationId, activeProject.id, model, mode, content)
      setMessages((current) => [
        ...current.filter((message) => message.id !== optimistic.id),
        result.userMessage,
        result.assistantMessage,
      ])
      await refreshConversations(activeProject.id)
    } catch (reason) {
      setDraft(content)
      setMessages((current) => current.filter((message) => message.id !== optimistic.id))
      setError(reason instanceof Error ? reason.message : 'Le modèle n’a pas répondu')
    } finally {
      setSending(false)
    }
  }

  function handleComposerKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  if (window.location.pathname === '/guide-shot') {
    const step = Number(new URLSearchParams(window.location.search).get('step') || 0)
    return <GuideShot step={Math.min(6, Math.max(0, step))} />
  }

  if (!data) {
    return (
      <main className="loading-screen">
        <div className="loading-mark">L/</div>
        <div><strong>Initialisation locale</strong><span>Ollama · MCP · SQLite</span></div>
        <RefreshCw className="spin" size={20} />
        {error && <p>{error}</p>}
      </main>
    )
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? 'is-open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark">L/</div>
          <div><strong>LASTER</strong><span>LOCAL DEV AGENT</span></div>
          <button className="icon-button sidebar-close" onClick={() => setSidebarOpen(false)} title="Fermer le volet"><PanelLeftClose size={18} /></button>
        </div>

        <button className="project-switcher" onClick={() => setProjectDialogOpen(true)}>
          <span className="project-icon"><FolderOpen size={18} /></span>
          <span><small>PROJET ACTIF</small><strong>{activeProject?.name || 'Aucun projet'}</strong></span>
          <ChevronDown size={16} />
        </button>

        <button className="new-chat" onClick={newConversation}><MessageSquarePlus size={18} /> Nouvelle conversation <span>Ctrl N</span></button>

        <div className="history-heading"><span>HISTORIQUE</span><em>{conversations.length}</em></div>
        <nav className="conversation-list" aria-label="Conversations">
          {!conversations.length && <p className="sidebar-empty">Les conversations de ce projet apparaîtront ici.</p>}
          {conversations.map((conversation) => (
            <div
              key={conversation.id}
              className={`conversation-row ${conversation.id === activeConversationId ? 'is-active' : ''}`}
              onClick={() => openConversation(conversation)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  void openConversation(conversation)
                }
              }}
              role="button"
              tabIndex={0}
            >
              <span><strong>{conversation.title}</strong><small>{formatRelativeDate(conversation.updatedAt)} · {conversation.messageCount} msg</small></span>
              <button className="delete-chat" onClick={(event) => removeConversation(event, conversation)} title="Supprimer"><Trash2 size={14} /></button>
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button onClick={() => setSetupOpen(true)}><Rocket size={17} /><span><strong>Guide de configuration</strong><small>7 étapes</small></span><ArrowRight size={15} /></button>
          <div className="local-only"><Database size={14} /> Données enregistrées localement</div>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setSidebarOpen(true)} title="Ouvrir le volet"><Menu size={20} /></button>
          <div className="thread-title">
            <span>{activeProject?.name}</span>
            <strong>{activeConversation?.title || 'Nouvelle conversation'}</strong>
          </div>
          <div className="runtime-status">
            <StatusDot active={data.status.ollama} label="OLLAMA" />
            <StatusDot active={data.status.copilot} label="COPILOT" />
            <StatusDot active={data.status.mcp} label="MCP" />
            <StatusDot active={data.status.unrealEditor} label="UNREAL" />
          </div>
          <div className="model-select-wrap">
            <Cpu size={16} />
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              aria-label={`Modèle, ${data.models.length} disponibles`}
              title={`${selectedModel?.name || 'Choisir un modèle'} · ${data.models.length} modèles`}
            >
              {localModels.length > 0 && <optgroup label={`Ollama local (${localModels.length})`}>
                {localModels.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.sizeLabel}</option>)}
              </optgroup>}
              {copilotModels.length > 0 && <optgroup label={`GitHub Copilot (${copilotModels.length})`}>
                {copilotModels.map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.name}{item.available ? '' : ' · CLI requis'}</option>)}
              </optgroup>}
            </select>
            <ChevronDown size={15} />
          </div>
          <button className="button history-button" onClick={() => setPromptDrawerOpen(true)}><History size={17} /> Anciens prompts</button>
        </header>

        {error && <div className="error-banner"><CircleAlert size={17} /><span>{error}</span><button onClick={() => setError('')} title="Fermer"><X size={16} /></button></div>}

        <section className={`chat-stage ${messages.length ? 'has-messages' : ''}`}>
          {!messages.length ? (
            <div className="empty-state">
              <div className="empty-sigil"><span>L/</span><i /></div>
              <span className="eyebrow">{activeProject?.name?.toUpperCase()} · PRÊT</span>
              <h1>Qu’est-ce qu’on construit&nbsp;?</h1>
              <p>Le contexte du projet et les outils MCP sont chargés.</p>
              <div className="starter-prompts">
                {starterPrompts.map(({ icon: Icon, label, prompt }) => (
                  <button key={label} onClick={() => { setDraft(prompt); textAreaRef.current?.focus() }}>
                    <Icon size={18} /><span><strong>{label}</strong><small>{prompt}</small></span><ArrowRight size={16} />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-stream">
              {messages.map((message) => <MessageBlock message={message} key={message.id} />)}
              {sending && (
                <div className="thinking-row"><span className="thinking-mark">L/</span><div><strong>Laster travaille</strong><span>Analyse du projet et appels d’outils</span></div><i /><i /><i /></div>
              )}
              <div ref={messageEndRef} />
            </div>
          )}
        </section>

        <section className="composer-zone">
          <div className="composer-toolbar">
            <div className="mode-switch" role="group" aria-label="Mode d'exécution">
              <button className={mode === 'chat' ? 'is-active' : ''} onClick={() => setMode('chat')}><Bot size={15} /> Chat</button>
              <button className={mode === 'agent' ? 'is-active' : ''} onClick={() => setMode('agent')}><SquareTerminal size={15} /> Agent</button>
            </div>
            <span className="mode-note">{mode === 'agent' ? 'Lecture, écriture et commandes autorisées' : 'Inspection en lecture seule'}</span>
            <button className="adapt-trigger" onClick={() => setAdaptDialogOpen(true)} disabled={!draft.trim()}><WandSparkles size={16} /> Adapter le prompt <em>≤ 200 CR</em></button>
          </div>
          <div className="composer">
            <textarea
              ref={textAreaRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder={mode === 'agent' ? 'Décris la modification à réaliser…' : 'Pose une question sur le projet…'}
              rows={3}
              disabled={sending}
            />
            <div className="composer-footer">
              <span><Sparkles size={14} /> {selectedModel?.name || 'Aucun modèle'} · {data.models.length} modèles</span>
              <span>Entrée pour envoyer · Maj Entrée pour une ligne</span>
              <button className="send-button" onClick={sendMessage} disabled={!draft.trim() || !model || sending} title="Envoyer"><Send size={19} /></button>
            </div>
          </div>
        </section>
      </main>

      {sidebarOpen && <button className="sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-label="Fermer le volet" />}
      {projectDialogOpen && <ProjectDialog projects={data.projects} onClose={() => setProjectDialogOpen(false)} onSelect={selectProject} onAdded={addProject} />}
      {promptDrawerOpen && activeProject && <PromptDrawer projectId={activeProject.id} onClose={() => setPromptDrawerOpen(false)} onRestore={(content) => { setDraft(content); setPromptDrawerOpen(false); textAreaRef.current?.focus() }} />}
      {adaptDialogOpen && activeProject && <AdaptDialog projectId={activeProject.id} model={model} prompt={draft} onClose={() => setAdaptDialogOpen(false)} onApply={(content) => { setDraft(content); setAdaptDialogOpen(false); textAreaRef.current?.focus() }} />}
      {setupOpen && <SetupTour onClose={() => setSetupOpen(false)} launcherCommand={data.launcherCommand} />}
    </div>
  )
}

export default App
