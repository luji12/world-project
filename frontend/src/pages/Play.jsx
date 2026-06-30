import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, Bot, ChevronDown, ChevronUp, Fingerprint, Globe, Loader2, MessageCircle, MessageSquare, ScrollText, Send, Settings2, Sparkles, Trash2 } from 'lucide-react'
import { useWorld } from '../App'
import { clearChatHistory, fetchCanonStatus, fetchChatHistory, fetchState, startInteractive } from '../api'
import { Button, EmptyState, cx } from '../components/UI'
import { StateTag, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'
import { useSettings } from '../SettingsContext'
import { eventLabel, eventToMessage } from '../chatEvents'
import { playChatCacheKey } from '../worldCache'

function restore(worldName) { try { return JSON.parse(localStorage.getItem(playChatCacheKey(worldName)) || '[]') } catch { return [] } }
function persist(worldName, messages) { try { localStorage.setItem(playChatCacheKey(worldName), JSON.stringify(messages.slice(-1000))) } catch {} }

function avatarInitial(name = '?') {
  return String(name || '?').trim().slice(0, 1) || '?'
}

export default function Play() {
  const navigate = useNavigate()
  const { currentWorld } = useWorld()
  const { settings } = useSettings()
  const [messages, setMessages] = useState([])
  const [playerName, setPlayerName] = useState('你')
  const [input, setInput] = useState('')
  const [started, setStarted] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [typingAgent, setTypingAgent] = useState('')
  const [error, setError] = useState('')
  const [expandedCards, setExpandedCards] = useState({})
  const [chatSummary, setChatSummary] = useState('')
  const [summaryExpanded, setSummaryExpanded] = useState(false)
  const [currentRound, setCurrentRound] = useState(0)
  const [canon, setCanon] = useState(null)
  const [confirmingClear, setConfirmingClear] = useState(false)
  const hasRestored = useRef(false)
  const feedRef = useRef(null)
  const apiConfigured = Boolean(settings?.apiKey?.trim())

  useEffect(() => {
    if (!currentWorld) {
      hasRestored.current = false
      setMessages([])
      setChatSummary('')
      setStarted(false)
      setWaiting(false)
      setTypingAgent('')
      setError('')
      setCurrentRound(0)
      setCanon(null)
      return undefined
    }
    let active = true
    hasRestored.current = false
    setMessages([])
    setChatSummary('')
    setStarted(false)

    Promise.all([
      fetchChatHistory().catch(() => null),
      fetchState('world.json').catch(() => null),
      fetchState('protagonist.json').catch(() => null),
      fetchCanonStatus().catch(() => null),
    ]).then(([hist, world, protagonist, nextCanon]) => {
      if (!active) return
      setCanon(nextCanon)
      const nextPlayerName = protagonist?.name || protagonist?.meta?.name || '你'
      setPlayerName(nextPlayerName)
      if (world?.meta?.current_round !== undefined) setCurrentRound(world.meta.current_round)

      const backendMsgs = Array.isArray(hist?.events)
        ? hist.events.map(evt => eventToMessage(evt, nextPlayerName)).filter(Boolean).map((msg, index) => ({ id: `hist-${index}`, ...msg }))
        : []
      if (backendMsgs.length > 0) {
        setMessages(backendMsgs)
        setStarted(true)
        persist(currentWorld, backendMsgs)
      } else {
        const cached = restore(currentWorld)
        setMessages(cached)
        setStarted(cached.length > 0)
      }
      setChatSummary(hist?.summary || '')
      hasRestored.current = true
    }).catch(() => {
      if (!active) return
      const cached = restore(currentWorld)
      setMessages(cached)
      setStarted(cached.length > 0)
      hasRestored.current = true
    })

    return () => { active = false }
  }, [currentWorld])

  useEffect(() => {
    if (currentWorld && hasRestored.current) persist(currentWorld, messages)
  }, [currentWorld, messages])

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, waiting, typingAgent])

  const toggleCard = useCallback((msgId) => {
    setExpandedCards(prev => ({ ...prev, [msgId]: !prev[msgId] }))
  }, [])

  const addMessage = useCallback(message => {
    setMessages(previous => [...previous, { id: `${Date.now()}-${Math.random()}`, ...message }])
  }, [])

  const receive = useCallback(({ event, data }) => {
    if (data?.round) setCurrentRound(data.round)
    if (event === 'agent-start') {
      const labels = {
        'world-engine': '世界正在推演…',
        'system-agent': '系统正在回应…',
        protagonist: '主角正在行动…',
        'npc-agents': '群像正在活动…',
        'npc-designer': '正在创建新角色…',
        chronicler: '正在记录叙事…',
      }
      setTypingAgent(labels[data.agent] || `${eventLabel(data.agent)} 工作中…`)
      return
    }

    const message = eventToMessage({ event, data }, playerName)
    if (message) {
      if (message.type !== 'player_action') setTypingAgent('')
      addMessage(message)
    }
    if (event === 'agent-error') {
      setTypingAgent('')
      setError(`${eventLabel(data.agent)}：${data.error}`)
    }
    if (event === 'intervention-required' || event === 'story-end' || event === 'close' || event === 'auto-stop') {
      setTypingAgent('')
      setWaiting(false)
    }
  }, [addMessage, playerName])

  const runRound = useCallback(async (action) => {
    setWaiting(true)
    setError('')
    setInput('')
    try {
      await startInteractive(action, receive)
    } catch (cause) {
      setError(cause.message || '行动提交失败')
      setWaiting(false)
    }
  }, [receive])

  const start = useCallback(() => {
    setStarted(true)
    if (currentRound > 0 || messages.length > 0) return
    runRound('睁开眼睛，观察周围的环境，确认自己身在何处。')
  }, [runRound, currentRound, messages.length])

  const submit = useCallback(() => {
    const action = input.trim()
    if (!action || waiting) return
    runRound(action)
  }, [input, waiting, runRound])

  const handleKeyDown = useCallback((event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }, [submit])

  const handleClearChat = useCallback(async () => {
    if (!confirmingClear) {
      setConfirmingClear(true)
      window.setTimeout(() => setConfirmingClear(false), 3000)
      return
    }
    setConfirmingClear(false)
    try { await clearChatHistory() } catch {}
    if (currentWorld) {
      try { localStorage.removeItem(playChatCacheKey(currentWorld)) } catch {}
    }
    setMessages([])
    setChatSummary('')
    setStarted(false)
    setError('')
  }, [confirmingClear, currentWorld])

  const renderMessage = (message, index) => {
    const key = message.id || `msg-${index}`
    const round = message.round ? <span className="text-[11px] text-[#9c9388]">第 {message.round} 轮</span> : null

    if (message.type === 'player_action') {
      return (
        <article key={key} className="ml-auto flex max-w-[82%] flex-col items-end gap-1">
          <div className="flex items-center gap-1.5 text-[11px] tracking-[.1em]">
            {round}<span className="font-medium text-[#a94334]">{playerName}</span><span className="text-[#766e64]">说</span>
          </div>
          <div className="rounded-xl rounded-br-sm border border-[#ad4b3a]/28 bg-[#f5e8e2]/70 px-4 py-2.5">
            <p className="whitespace-pre-wrap text-sm leading-7 text-[#3d3831]">{message.text}</p>
          </div>
        </article>
      )
    }

    if (message.type === 'system_chat') {
      return (
        <article key={key} className="mr-auto flex max-w-[86%] gap-2.5">
          <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[#ad4b3a]/22 bg-[#f8f2e8]">
            <Sparkles className="h-3.5 w-3.5 text-[#a94334]" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-1.5">
              <span className="text-[11px] font-medium tracking-[.1em] text-[#a94334]">命运系统</span>{round}
            </div>
            <div className="rounded-xl rounded-bl-sm border border-[#d6ccba]/70 bg-[#fffdf8] px-4 py-2.5">
              <p className="whitespace-pre-wrap text-sm leading-7 text-[#3d3831]">{message.text}</p>
            </div>
          </div>
        </article>
      )
    }

    if (message.type === 'npc_chat') {
      const hasDialogue = message.text && !message.text.startsWith('（')
      return (
        <article key={key} className="group mr-auto flex max-w-[82%] gap-2.5">
          <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[#d6ccba] bg-[#f8f2e8] text-[11px] font-semibold text-[#766e64]">
            {avatarInitial(message.name)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-1.5">
              <span className="text-[11px] font-medium tracking-[.1em] text-[#625a50]">{message.name}</span>
              {hasDialogue ? <MessageSquare className="h-3 w-3 text-[#9c9388]" /> : <Bot className="h-3 w-3 text-[#9c9388]" />}
              {round}
            </div>
            <div className="rounded-xl rounded-bl-sm border border-[#d6ccba]/70 bg-[#fffdf8] px-4 py-2.5">
              <p className="whitespace-pre-wrap text-sm leading-7 text-[#3d3831]">{message.text}</p>
            </div>
          </div>
        </article>
      )
    }

    if (message.type === 'world') {
      return (
        <article key={key} className="mx-auto my-3 flex max-w-[92%]">
          <div className="w-full rounded-none border-y border-[#d6ccba]/75 bg-[#faf7f0] px-4 py-3">
            <div className="mb-1.5 flex items-center justify-center gap-1.5">
              <Globe className="h-3.5 w-3.5 text-[#766e64]" />
              <span className="text-[11px] font-medium tracking-[.16em] text-[#766e64]">世界变化</span>
              {round}
            </div>
            <p className="whitespace-pre-wrap text-center font-serif text-sm italic leading-7 text-[#3d3831]">{message.text}</p>
          </div>
        </article>
      )
    }

    if (message.type === 'chapter_card') {
      const isExpanded = expandedCards[message.id]
      const text = message.text || ''
      const lines = text.split('\n')
      const preview = lines.slice(0, 3).join('\n')
      const hasMore = lines.length > 3 || text.length > 200

      return (
        <article key={key} className="mx-auto my-4 flex max-w-[92%]">
          <div className="w-full overflow-hidden rounded-none border border-[#d6ccba] bg-[#fffdf8]">
            <button
              type="button"
              onClick={() => hasMore && toggleCard(message.id)}
              className={cx('flex w-full items-center justify-between px-4 py-3 text-left', hasMore && 'cursor-pointer hover:bg-[#f8f2e8]')}
            >
              <div className="flex items-center gap-1.5">
                <ScrollText className="h-3.5 w-3.5 text-[#a94334]" />
                <span className="text-[11px] font-medium tracking-[.14em] text-[#a94334]">叙事正文</span>
                {round}
              </div>
              {hasMore && (isExpanded ? <ChevronUp className="h-3.5 w-3.5 text-[#766e64]" /> : <ChevronDown className="h-3.5 w-3.5 text-[#766e64]" />)}
            </button>
            <div className={cx('px-4 pb-3', !isExpanded && hasMore && 'max-h-24 overflow-hidden')}>
              <p className="whitespace-pre-wrap font-serif text-sm leading-8 text-[#3d3831]">{isExpanded ? text : preview}</p>
              {!isExpanded && hasMore && (
                <button type="button" className="mt-2 w-full text-center text-xs text-[#766e64] hover:text-[#a94334]" onClick={() => toggleCard(message.id)}>
                  — 点击展开全文（约{text.length}字）—
                </button>
              )}
            </div>
          </div>
        </article>
      )
    }

    if (message.type === 'error_msg') {
      return (
        <article key={key} className="mx-auto my-2 flex max-w-[86%]">
          <div className="rounded-md border border-[#b24c43]/25 bg-[#f5e8e2] px-3 py-1.5">
            <p className="text-xs text-[#9f3e31]">{message.text}</p>
          </div>
        </article>
      )
    }

    return null
  }

  const showEmpty = !started && messages.length === 0 && !waiting
  const startButtonLabel = currentRound > 0 ? '继续故事' : '开始故事'

  return (
    <WorkspacePage className="flex h-full max-w-4xl flex-col overflow-hidden pb-0">
      <WorkspaceHeader
        trail="玩家视角"
        title="群聊推演"
        description="像聊天室一样推进你的故事——角色们会实时对话，世界会实时变化。"
        actions={!apiConfigured ? <Button tone="primary" icon={Settings2} onClick={() => navigate('/settings')}>连接模型</Button> : null}
      />
      {!apiConfigured && <div className="border-l border-[#ad4b3a]/45 bg-[#f5e8e2]/55 px-4 py-3 text-sm leading-6 text-[#625a50]" role="status">先连接模型，再开始你的故事。</div>}
      {error && <div role="alert" className="rounded-md border border-[#b24c43]/25 bg-[#f5e8e2]/60 px-4 py-3 text-sm text-[#9f3e31]">{error}</div>}

      <Surface className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[#d6ccba] bg-[#fffdf8] px-5 py-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Fingerprint aria-hidden="true" className="h-4 w-4 text-[#a94334]" />
            <span className="text-xs font-semibold tracking-[.14em] text-[#a94334]">操控角色</span>
            <span className="font-serif text-sm font-semibold text-[#2f2b25]">{playerName}</span>
            {currentRound > 0 && <span className="text-[11px] text-[#766e64]">· 第 {currentRound} 轮</span>}
            {canon?.current_arc?.name && <span className="text-[11px] text-[#766e64]">· {canon.current_arc.name}</span>}
            {messages.length > 0 && <span className="text-[11px] text-[#766e64]">· {messages.length} 条消息</span>}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <StateTag tone={waiting ? 'brass' : 'quiet'}>{waiting && typingAgent ? typingAgent : waiting ? '处理中…' : started ? '等待你的行动' : '尚未开始'}</StateTag>
            {messages.length > 0 && (
              <button
                type="button"
                onClick={handleClearChat}
                className={cx(
                  'flex h-7 w-7 items-center justify-center rounded-sm border transition-colors',
                  confirmingClear
                    ? 'border-[#b24c43]/40 bg-[#f5e8e2] text-[#9f3e31]'
                    : 'border-[#d6ccba] text-[#766e64] hover:border-[#b24c43]/35 hover:text-[#9f3e31]',
                )}
                title={confirmingClear ? '再次点击确认清空' : '清空聊天记录'}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        <div ref={feedRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-[#f7f3eb] p-4 sm:p-5">
          {chatSummary && (
            <article className="mx-auto my-2 flex max-w-[92%]">
              <div className="w-full overflow-hidden rounded-none border border-[#ad4b3a]/22 bg-[#f5e8e2]/35">
                <button type="button" onClick={() => setSummaryExpanded(!summaryExpanded)} className="flex w-full cursor-pointer items-center justify-between px-4 py-2.5 text-left hover:bg-[#f5e8e2]/60">
                  <div className="flex items-center gap-1.5">
                    <ScrollText className="h-3.5 w-3.5 text-[#a94334]" />
                    <span className="text-[11px] font-medium tracking-[.1em] text-[#a94334]">过往故事摘要</span>
                  </div>
                  {summaryExpanded ? <ChevronUp className="h-3.5 w-3.5 text-[#766e64]" /> : <ChevronDown className="h-3.5 w-3.5 text-[#766e64]" />}
                </button>
                {summaryExpanded ? <div className="px-4 pb-3"><p className="whitespace-pre-wrap font-serif text-xs leading-6 text-[#625a50]">{chatSummary}</p></div> : <div className="px-4 pb-2"><p className="text-xs text-[#766e64]">点击展开查看压缩的历史剧情摘要</p></div>}
              </div>
            </article>
          )}

          {showEmpty ? (
            <div className="flex h-full min-h-[24rem] items-center justify-center">
              <EmptyState
                icon={MessageCircle}
                title="故事尚未开始"
                description={currentRound > 0 ? `世界已推演至第 ${currentRound} 轮，继续你的冒险。` : '点击下方按钮，踏入这个世界。'}
                action={<Button tone="primary" icon={BookOpen} onClick={start} disabled={!apiConfigured}>{startButtonLabel}</Button>}
              />
            </div>
          ) : (
            <>
              {messages.map((message, index) => renderMessage(message, index))}
              {waiting && typingAgent && (
                <div className="flex items-center gap-2 px-2 py-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-[#a94334]" />
                  <span className="text-xs text-[#766e64]">{typingAgent}</span>
                </div>
              )}
            </>
          )}
        </div>

        <div className="shrink-0 border-t border-[#d6ccba] bg-[#fffdf8] p-3 sm:p-4">
          {!started ? (
            <div className="flex items-center justify-center py-2">
              <Button tone="primary" icon={BookOpen} onClick={start} disabled={!apiConfigured}>{startButtonLabel}</Button>
            </div>
          ) : (
            <div className="flex items-end gap-2 sm:gap-3">
              <label className="flex-1">
                <textarea
                  value={input}
                  onChange={event => setInput(event.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={waiting ? '剧情推演中，稍候…' : '你想做什么？说什么？去哪里？（Enter 发送，Shift+Enter 换行）'}
                  rows={2}
                  disabled={waiting || !apiConfigured}
                  className="min-h-[3rem] w-full resize-none rounded-none border border-[#d6ccba] bg-[#fffdf8] px-4 py-3 text-sm leading-6 text-[#2f2b25] placeholder:text-[#9c9388] focus:border-[#ad4b3a]/60 focus:outline-none focus:ring-4 focus:ring-[#ad4b3a]/10 disabled:opacity-50"
                />
              </label>
              <Button tone="primary" icon={waiting ? Loader2 : Send} className={waiting ? '[&>svg]:animate-spin' : ''} disabled={!input.trim() || waiting || !apiConfigured} onClick={submit}>发送</Button>
            </div>
          )}
        </div>
      </Surface>
    </WorkspacePage>
  )
}
