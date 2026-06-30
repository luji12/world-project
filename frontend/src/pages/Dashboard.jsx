import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, BookOpen, Bot, CircleGauge, Globe2, Landmark, Loader2, Pause, Play, RotateCcw, Send, Settings2, Sparkles } from 'lucide-react'
import { fetchCanonStatus, fetchCurrentWorld, fetchState, injectWorld, pauseAuto, restartWorld, resumeAuto, startAuto, startInteractive } from '../api'
import { Button, EmptyState, cx } from '../components/UI'
import { InlineLoader, KeyValue, OverlayDialog, SectionTitle, Segmented, StateTag, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'
import { loadAutoConfig } from '../autoConfig'
import { useSettings } from '../SettingsContext'
import { eventLabel, eventToDashboardEntry } from '../chatEvents'
import { useWorld } from '../App'
import { dashboardCacheKey } from '../worldCache'

function restoreDashboardEntries(worldName) {
  try { return JSON.parse(localStorage.getItem(dashboardCacheKey(worldName)) || '[]') } catch { return [] }
}
function persistDashboardEntries(worldName, entries) {
  try { localStorage.setItem(dashboardCacheKey(worldName), JSON.stringify(entries.slice(-300))) } catch {}
}

function regionName(world) {
  const geography = world?.geography || {}
  const regions = geography.regions
  const current = geography.current_region || geography.current_region_id
  if (Array.isArray(regions)) {
    const found = regions.find(region => region?.id === current || region?.name === current) || regions[0]
    return found?.name || current || '未知'
  }
  return regions?.[current]?.name || current || '未知'
}

export default function Dashboard({ mode, onModeChange, running, onRunningChange, paused, onPausedChange, logs, onLogsChange, progress, onProgressChange }) {
  const navigate = useNavigate()
  const { settings } = useSettings()
  const { currentWorld } = useWorld()
  const [world, setWorld] = useState(null)
  const [canon, setCanon] = useState(null)
  const [worldName, setWorldName] = useState('')
  const [entries, setEntries] = useState([])
  const [actionInput, setActionInput] = useState('')
  const [injectionInput, setInjectionInput] = useState('')
  const [intervention, setIntervention] = useState(null)
  const [sending, setSending] = useState(false)
  const [injecting, setInjecting] = useState(false)
  const [storyEnded, setStoryEnded] = useState(null)
  const [error, setError] = useState('')
  const feedRef = useRef(null)
  const currentRound = world?.meta?.current_round || progress || 0
  const apiConfigured = Boolean(settings?.apiKey?.trim())

  const refreshWorld = useCallback(async () => {
    try {
      const current = await fetchCurrentWorld()
      if (!current.name) return navigate('/worlds', { replace: true })
      setWorldName(current.name)
      const [nextWorld, nextCanon] = await Promise.all([
        fetchState('world.json'),
        fetchCanonStatus().catch(() => null),
      ])
      setWorld(nextWorld)
      setCanon(nextCanon)
    } catch { navigate('/worlds', { replace: true }) }
  }, [navigate])

  useEffect(() => {
    if (!currentWorld) {
      setWorld(null)
      setCanon(null)
      setWorldName('')
      setEntries([])
      setIntervention(null)
      setError('')
      navigate('/worlds', { replace: true })
      return
    }
    refreshWorld()
  }, [currentWorld, navigate, refreshWorld])
  useEffect(() => { if (worldName) setEntries(restoreDashboardEntries(worldName)) }, [worldName])
  useEffect(() => { if (worldName) persistDashboardEntries(worldName, entries) }, [worldName, entries])
  useEffect(() => { if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight }, [entries, intervention])
  useEffect(() => {
    if (!running) return undefined
    const timer = window.setInterval(() => { fetchState('world.json').then(setWorld).catch(() => {}) }, 5000)
    return () => window.clearInterval(timer)
  }, [running])

  const appendEntry = useCallback((entry) => setEntries(previous => [...previous, { id: `${Date.now()}-${Math.random()}`, ...entry }]), [])
  const handleStream = useCallback(({ event, data }) => {
    onLogsChange(previous => [...previous, { event, data, ts: Date.now() }])
    const entry = eventToDashboardEntry({ event, data })
    if (entry) appendEntry(entry)
    if (event === 'agent-error') setError(`${eventLabel(data.agent)}：${data.error}`)
    if (event === 'round-complete') { onProgressChange(previous => previous + 1); refreshWorld() }
    if (event === 'intervention-required') { setIntervention(data); onPausedChange(true); onRunningChange(false) }
    if (event === 'story-end') { setStoryEnded(data); onRunningChange(false); onPausedChange(false) }
    if (event === 'close' || event === 'auto-stop') { onRunningChange(false); if (!intervention) onPausedChange(false); refreshWorld() }
  }, [appendEntry, intervention, onLogsChange, onPausedChange, onProgressChange, onRunningChange, refreshWorld])

  async function startSimulation() {
    setError(''); setIntervention(null); onRunningChange(true); onPausedChange(false); onProgressChange(0)
    try {
      const config = loadAutoConfig()
      await startAuto(config.stopConditions, config.interventionNodes, mode === 'interactive', handleStream)
    } catch (cause) { onRunningChange(false); setError(cause.message || '推演启动失败') }
  }
  async function submitAction() {
    const action = actionInput.trim(); if (!action || sending) return
    setSending(true); setActionInput(''); setIntervention(null); onRunningChange(true); onPausedChange(false)
    try { await startInteractive(action, handleStream) } catch (cause) { setError(cause.message || '行动提交失败'); onRunningChange(false) } finally { setSending(false) }
  }
  async function inject() {
    const input = injectionInput.trim(); if (!input || injecting) return
    setInjecting(true)
    try { await injectWorld(input); appendEntry({ type: 'system', text: `已注入世界变化：${input}` }); setInjectionInput('') } catch (cause) { setError(cause.message || '注入失败') } finally { setInjecting(false) }
  }
  async function continueSimulation() { try { await resumeAuto(); onPausedChange(false); onRunningChange(true) } catch (cause) { setError(cause.message || '继续失败') } }
  async function pauseSimulation() { try { await pauseAuto(); onPausedChange(true) } catch (cause) { setError(cause.message || '暂停失败') } }

  const worldFacts = useMemo(() => [
    ['当前轮次', `${currentRound} 轮`], ['世界时间', world?.time ? `${world.time.year || ''}年 ${world.time.month || ''}月` : '—'], ['所在区域', regionName(world)],
  ], [currentRound, world])

  return (
    <WorkspacePage className="flex h-full min-h-0 max-w-[1320px] flex-col space-y-4 overflow-hidden pb-0">
      <WorkspaceHeader trail={worldName || '推演工作台'} title="世界推演" description="让智能体推进世界；在关键节点，你的选择将成为后续叙事的因。" actions={<><Segmented ariaLabel="推演模式" value={mode} onChange={onModeChange} items={[{ value: 'auto', label: '自动推演' }, { value: 'interactive', label: '玩家介入' }]} />{!apiConfigured ? <Button tone="primary" icon={Settings2} onClick={() => navigate('/settings')}>连接模型</Button> : !running ? <Button tone="primary" icon={Play} onClick={startSimulation}>开始推演</Button> : paused ? <Button tone="primary" icon={Play} onClick={continueSimulation}>继续</Button> : <Button tone="secondary" icon={Pause} onClick={pauseSimulation}>暂停</Button>}</>} />
      {!apiConfigured && <div className="border-l border-[#ad4b3a]/45 bg-[#f5e8e2]/55 px-4 py-3 text-sm leading-6 text-[#625a50]" role="status">推演需要先连接模型；你的世界、角色和阅读记录已经就绪，不会因此丢失。</div>}
      {error && <div role="alert" className="rounded-md border border-[#b24c43]/25 bg-[#f5e8e2]/60 px-4 py-3 text-sm text-[#9f3e31]">{error}</div>}
      <div className="grid min-h-0 flex-1 gap-5 overflow-hidden xl:grid-cols-[minmax(0,1fr)_18rem]">
        <Surface className="flex min-h-0 flex-col overflow-hidden">
          <SectionTitle icon={BookOpen} action={<StateTag tone={running ? 'brass' : paused ? 'quiet' : 'quiet'}>{running ? '推演中' : paused ? '等待决策' : '静候开篇'}</StateTag>}>叙事流</SectionTitle>
          <div ref={feedRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-[#f7f3eb] px-5 pb-8 pt-5">
            {entries.map((entry, ei) => <article key={entry.id || `entry-${ei}-${entry.round || 0}-${entry.type || 'evt'}`} className={cx('border-l pl-4', entry.type === 'chronicle' ? 'border-[#d3ad65]/70' : entry.type === 'action' ? 'border-emerald-300/60' : 'border-[#d6ccba]/22')}><div className="flex flex-wrap items-center gap-2"><span className="text-[11px] font-semibold tracking-[.13em] text-[#d3ad65]">{entry.actor || (entry.type === 'chronicle' ? '记录员' : entry.type === 'system' ? '命运系统' : '世界')}</span>{entry.round && <span className="text-[11px] text-[#756e60]">第 {entry.round} 轮</span>}</div><p className={cx('mt-2 whitespace-pre-wrap text-sm leading-7', entry.type === 'chronicle' ? 'font-serif text-[#e5dccd]' : 'text-[#bdb3a1]')}>{entry.text}</p></article>)}
            {!entries.length && <EmptyState icon={Sparkles} title="世界等待第一束因果" description="启动自动推演，或切换到玩家介入模式，从你的行动开始故事。" />}
            {running && <InlineLoader>世界正在推演下一段变化…</InlineLoader>}
          </div>
          {intervention && mode === 'interactive' && <div className="shrink-0 border-t border-[#d3ad65]/28 bg-[#d3ad65]/[.07] p-5"><div className="flex items-start gap-3"><Sparkles aria-hidden="true" className="mt-0.5 h-4 w-4 text-[#e7c37f]" /><div><p className="text-sm font-semibold text-[#f0dca9]">故事正在等你决定</p><p className="mt-1 text-sm leading-6 text-[#c9bea9]">{intervention.reason || '下一步将如何行动？'}</p></div></div></div>}
        </Surface>
        <aside className="min-h-0 space-y-5 overflow-y-auto">
          <Surface className="p-5"><div className="flex items-center gap-2 text-[#d3ad65]"><Landmark aria-hidden="true" className="h-4 w-4" /><span className="text-xs font-semibold tracking-[.14em]">当前页</span></div><div className="mt-5 space-y-5">{worldFacts.map(([label, value]) => <KeyValue key={label} label={label} value={value} />)}</div></Surface>
          <Surface className="p-5">
            <div className="flex items-center gap-2 text-[#d3ad65]"><CircleGauge aria-hidden="true" className="h-4 w-4" /><span className="text-xs font-semibold tracking-[.14em]">Canon 轨道</span></div>
            <div className="mt-5 space-y-5">
              <KeyValue label="当前阶段" value={canon?.current_arc?.name || (canon?.exists ? '开篇阶段' : '未编译')} />
              <KeyValue label="起始地区" value={canon?.starting_region || '—'} />
              <KeyValue label="开放冲突" value={`${canon?.conflicts_count || 0} 条`} />
            </div>
          </Surface>
          <Surface className="p-5"><div className="flex items-center gap-2 text-[#d3ad65]"><Bot aria-hidden="true" className="h-4 w-4" /><span className="text-xs font-semibold tracking-[.14em]">协作记录</span></div><p className="mt-4 text-sm leading-6 text-[#a99f8c]">本轮已接收 {logs.length} 条引擎事件。记录员的输出会沉淀到章节与记忆系统。</p></Surface>
        </aside>
      </div>
      <Surface className="shrink-0 overflow-hidden border-[#d6ccba] bg-[#fffdf8]">
        <div className="grid gap-px bg-[#d6ccba]/35 lg:grid-cols-2">
          <div className="min-w-0 bg-[#fffdf8] p-3 md:p-4">
            <div className="mb-3 flex items-center gap-2 text-[#a94334]">
              <Send aria-hidden="true" className="h-4 w-4" />
              <span className="text-xs font-semibold tracking-[.14em]">玩家行动{mode === 'interactive' && paused ? ' · 等待决策' : ''}</span>
            </div>
            <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_6.25rem]">
              <label className="min-w-0 flex-1">
                <textarea value={actionInput} onChange={event => setActionInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submitAction() } }} placeholder={apiConfigured ? '描述角色会怎么做、说什么，或刻意不做什么…' : '连接模型后即可写下角色行动…'} rows={2} disabled={sending || !apiConfigured || mode !== 'interactive'} className="min-h-[4rem] w-full resize-none rounded-none border border-[#d6ccba] bg-[#fffdf8] px-4 py-3 text-sm leading-6 text-[#2f2b25] placeholder:text-[#9c9388] focus:border-[#ad4b3a]/60 focus:outline-none focus:ring-4 focus:ring-[#ad4b3a]/10 disabled:opacity-50" />
              </label>
              <Button tone="primary" icon={sending ? Loader2 : Send} className={cx('h-16 self-stretch', sending && '[&>svg]:animate-spin')} disabled={!actionInput.trim() || sending || !apiConfigured || mode !== 'interactive'} onClick={submitAction}>提交</Button>
            </div>
          </div>
          <div className="min-w-0 bg-[#fffdf8] p-3 md:p-4">
            <div className="mb-3 flex items-center gap-2 text-[#a94334]">
              <Globe2 aria-hidden="true" className="h-4 w-4" />
              <span className="text-xs font-semibold tracking-[.14em]">世界干预（上帝权限）</span>
            </div>
            <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_5rem]">
              <label className="min-w-0 flex-1">
                <input value={injectionInput} onChange={event => setInjectionInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); inject() } }} placeholder="注入世界事实：城外来了一支陌生商队…" className="min-h-[4rem] w-full rounded-none border border-[#d6ccba] bg-[#fffdf8] px-4 text-sm text-[#2f2b25] placeholder:text-[#9c9388] focus:border-[#ad4b3a]/60 focus:outline-none focus:ring-4 focus:ring-[#ad4b3a]/10 disabled:opacity-50" disabled={!apiConfigured} />
              </label>
              <Button tone="secondary" className="h-16 self-stretch" disabled={!injectionInput.trim() || injecting || !apiConfigured} onClick={inject}>{injecting ? '注入中' : '注入'}</Button>
            </div>
          </div>
        </div>
      </Surface>
      {storyEnded && <OverlayDialog onClose={() => setStoryEnded(null)} label="故事结束"><div className="p-7 text-center"><AlertTriangle aria-hidden="true" className="mx-auto h-6 w-6 text-red-200" /><h2 className="atelier-heading mt-4 text-2xl font-semibold text-[#eee7d8]">故事暂告一段落</h2><p className="mt-3 text-sm leading-6 text-[#a99f8c]">{storyEnded.message}</p><div className="mt-6 flex justify-center gap-3"><Button tone="secondary" onClick={() => { setStoryEnded(null); navigate('/worlds') }}>查看世界</Button><Button tone="primary" icon={RotateCcw} onClick={async () => { await restartWorld(); setStoryEnded(null); setEntries([]); refreshWorld() }}>重新开始</Button></div></div></OverlayDialog>}
    </WorkspacePage>
  )
}
