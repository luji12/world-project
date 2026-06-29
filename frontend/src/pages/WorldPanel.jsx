import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, FileText, Globe2, Loader2, MessageSquareText, Plus, Send, Settings2, Trash2, Upload, UserRound } from 'lucide-react'
import { LEGACY_SETTINGS_KEY, SETTINGS_KEY, chatWorld, createWorldV2, deleteWorld, fetchWorlds, generateWorldDetails, switchWorld as switchWorldApi, uploadDocument } from '../api'
import { Button, EmptyState, TextInput, cx } from '../components/UI'
import { InlineLoader, OverlayDialog, SectionTitle, Segmented, StateTag, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'
import { useWorld } from '../App'
import { clearWorldUiCache } from '../worldCache'

const DRAFT_KEY = 'world-create-draft-v2'
const FLOW_STEPS = ['设定世界', '选择角色', '世界灵魂', '生成世界']

const WORLD_TYPE_LABELS = {
  xuanhuan: { name: '东方玄幻', icon: '⚔️', desc: '灵气修真、宗门林立' },
  xianxia: { name: '古典仙侠', icon: '🗡️', desc: '仙道飘渺、飞剑渡劫' },
  western_fantasy: { name: '西方奇幻', icon: '🐉', desc: '魔法骑士、龙与精灵' },
  scifi: { name: '赛博科幻', icon: '🤖', desc: '义体黑客、霓虹都市' },
  modern: { name: '现代都市', icon: '🏙️', desc: '都市悬疑、人间烟火' },
  post_apoc: { name: '末日废土', icon: '☢️', desc: '辐射变异、生存挣扎' },
  custom: { name: '自定义', icon: '✨', desc: '融合创新、独一无二' },
}

function readSettings() {
  try { return JSON.parse(localStorage.getItem(SETTINGS_KEY) || localStorage.getItem(LEGACY_SETTINGS_KEY) || '{}') } catch { return {} }
}
function loadDraft() { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null') } catch { return null } }
function saveDraft(data) { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(data)) } catch {} }
function clearDraft() { try { localStorage.removeItem(DRAFT_KEY) } catch {} }

function createAssistantWelcome(id) {
  return { id, role: 'assistant', content: '请描述你想创建的世界：类型、时代、力量体系，或者一个你想亲眼见到的场景。' }
}

export default function WorldPanel() {
  const navigate = useNavigate()
  const { refresh: refreshWorldStatus } = useWorld()
  const [worlds, setWorlds] = useState([])
  const [view, setView] = useState('shelf')
  const [entryMode, setEntryMode] = useState('chat')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [phase, setPhase] = useState('brief')
  const [worldPackage, setWorldPackage] = useState(null)
  const [selectedCharId, setSelectedCharId] = useState('')
  const [newWorldName, setNewWorldName] = useState('')
  const [agentSystemEnabled, setAgentSystemEnabled] = useState(true)
  const [agentSystemName, setAgentSystemName] = useState('')
  const [docFile, setDocFile] = useState(null)
  const [docUploading, setDocUploading] = useState(false)
  const [error, setError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [hasDraft, setHasDraft] = useState(false)
  const msgId = useRef(0)
  const fileInputRef = useRef(null)
  const chatEndRef = useRef(null)
  const nextId = () => ++msgId.current

  const loadWorlds = useCallback(async () => {
    try { const data = await fetchWorlds(); setWorlds(data.worlds || []); setError('') } catch (cause) { setError(cause.message || '世界列表加载失败') }
  }, [])

  useEffect(() => { loadWorlds(); const draft = loadDraft(); setHasDraft(Boolean(draft?.worldPackage || draft?.messages?.length)) }, [loadWorlds])
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, sending, phase])
  useEffect(() => {
    if (view === 'create' && (messages.length || worldPackage)) saveDraft({ messages, phase, worldPackage, selectedCharId, newWorldName, entryMode, agentSystemEnabled, agentSystemName })
  }, [view, messages, phase, worldPackage, selectedCharId, newWorldName, entryMode, agentSystemEnabled, agentSystemName])

  function resetCreation() {
    setView('create'); setEntryMode('chat'); setMessages([]); setInput(''); setPhase('brief'); setWorldPackage(null); setSelectedCharId(''); setNewWorldName(''); setAgentSystemEnabled(true); setAgentSystemName(''); setDocFile(null); setError(''); clearDraft(); setHasDraft(false)
  }
  function restoreDraft() {
    const draft = loadDraft(); if (!draft) return resetCreation()
    setView('create'); setMessages(draft.messages || []); setPhase(draft.phase || 'brief'); setWorldPackage(draft.worldPackage || null); setSelectedCharId(draft.selectedCharId || ''); setNewWorldName(draft.newWorldName || ''); setEntryMode(draft.entryMode || 'chat'); setAgentSystemEnabled(draft.agentSystemEnabled ?? true); setAgentSystemName(draft.agentSystemName || ''); setHasDraft(false); setError('')
  }
  function startChat() {
    setEntryMode('chat'); setDocFile(null); setError('')
    if (!messages.length) setMessages([createAssistantWelcome(nextId())])
  }
  async function sendMessage(forcePackage = false) {
    const copy = forcePackage ? '请整理为可创建的结构化世界包。' : input.trim()
    if (!copy || sending) return
    const nextMessages = [...messages, { id: nextId(), role: 'user', content: copy }]
    setMessages(nextMessages); setInput(''); setSending(true); setError('')
    try {
      const result = await chatWorld(nextMessages)
      if (result.mode === 'world_package' || result.mode === 'world_package_incomplete') {
        const wp = result.world_package
        setWorldPackage(wp); setNewWorldName(wp?.world_state?.world_name || '')
        const sysCfg = wp?.agent_config?.system || {}
        setAgentSystemEnabled(sysCfg.enabled !== false)
        setAgentSystemName(sysCfg.name || '')
        setPhase('character')
        setMessages(previous => [...previous, { id: nextId(), role: 'assistant', content: '世界框架已收束。现在请选择你要扮演的角色。' }])
      } else if (result.reply) setMessages(previous => [...previous, { id: nextId(), role: 'assistant', content: result.reply }])
    } catch (cause) { setError(cause.message || '世界助手暂时无法回应') } finally { setSending(false) }
  }
  async function handleUpload(file) {
    if (!file || docUploading) return
    setDocFile(file); setDocUploading(true); setError(''); setEntryMode('document')
    try {
      const result = await uploadDocument(file)
      if (result.mode !== 'world_package') throw new Error('文档未能生成有效世界包')
      const wp = result.world_package
      setWorldPackage(wp); setNewWorldName(wp?.world_state?.world_name || file.name.replace(/\.[^.]+$/, ''))
      const sysCfg = wp?.agent_config?.system || {}
      setAgentSystemEnabled(sysCfg.enabled !== false)
      setAgentSystemName(sysCfg.name || '')
      setPhase('character')
      setMessages([{ id: nextId(), role: 'assistant', content: `已从「${file.name}」提取世界设定。请在下一步选择你要扮演的角色。` }])
    } catch (cause) { setError(cause.message || '文档解析失败') } finally { setDocUploading(false) }
  }
  async function createWorld() {
    if (!worldPackage || !selectedCharId || !newWorldName.trim() || sending) return
    setSending(true); setPhase('creating'); setError('')
    try {
      const details = await generateWorldDetails(worldPackage, selectedCharId)
      const merged = JSON.parse(JSON.stringify(worldPackage))
      const ac = merged.agent_config || {}
      const sys = ac.system || {}
      sys.enabled = agentSystemEnabled
      if (agentSystemName.trim()) sys.name = agentSystemName.trim()
      ac.system = sys
      merged.agent_config = ac
      const selected = (merged.playable_characters || []).find(item => (item.id || item.name) === selectedCharId)
      if (selected) {
        selected.has_system = agentSystemEnabled && (selected.has_system !== false)
        if (agentSystemName.trim()) selected.system_name = agentSystemName.trim()
        if (details?.details?.selected_character_detail) Object.assign(selected, details.details.selected_character_detail)
      }
      const detailMap = Object.fromEntries((details?.details?.npc_details || []).map(item => [item.id || item.name, item]))
      for (const npc of merged.npcs || []) Object.assign(npc, detailMap[npc.id || npc.name] || {})
      await createWorldV2(newWorldName.trim(), merged, selectedCharId)
      clearDraft(); setHasDraft(false); await loadWorlds(); await refreshWorldStatus(); setView('shelf'); setMessages([]); setWorldPackage(null); setPhase('brief')
    } catch (cause) { setError(cause.message || '世界创建失败'); setPhase('agent') } finally { setSending(false) }
  }
  function goToAgentConfig() {
    if (!selectedCharId) return
    if (!agentSystemName.trim() && worldPackage?.agent_config?.system?.name) {
      setAgentSystemName(worldPackage.agent_config.system.name)
    }
    setPhase('agent')
  }

  const activeStep = phase === 'brief' ? 0 : phase === 'character' ? 1 : phase === 'agent' ? 2 : phase === 'creating' ? 3 : 3
  async function switchWorld(name) { try { await switchWorldApi(name); await loadWorlds(); await refreshWorldStatus() } catch (cause) { setError(cause.message || '切换世界失败') } }
  async function confirmDelete() {
    if (!deleteTarget || deleting) return
    const deletedName = deleteTarget.name
    setDeleting(true)
    try {
      await deleteWorld(deletedName)
      clearWorldUiCache(deletedName)
      setDeleteTarget(null)
      await loadWorlds()
      await refreshWorldStatus()
      navigate('/worlds', { replace: true })
    } catch (cause) {
      setError(cause.message || '删除世界失败')
    } finally {
      setDeleting(false)
    }
  }

  const apiConfigured = Boolean(readSettings().apiKey)

  return (
    <WorkspacePage className="max-w-6xl">
      <WorkspaceHeader trail="世界书架" title="世界管理" description="创建、切换与保存每一个可以继续推演的故事世界。" actions={<Button tone="primary" icon={Plus} onClick={resetCreation}>新建世界</Button>} />
      <Segmented ariaLabel="世界管理视图" value={view} onChange={next => next === 'create' ? resetCreation() : setView('shelf')} items={[{ value: 'shelf', label: '我的世界' }, { value: 'create', label: '创建世界', icon: Plus }]} />
      {error && <div className="rounded-md border border-red-300/25 bg-red-400/10 px-4 py-3 text-sm text-red-100" role="alert">{error}</div>}

      {view === 'shelf' && <>
        {hasDraft && <button type="button" onClick={restoreDraft} className="flex w-full items-center justify-between rounded-lg border border-[#d3ad65]/28 bg-[#d3ad65]/8 px-4 py-3 text-left transition-colors hover:bg-[#d3ad65]/14"><span><span className="block text-sm font-medium text-[#f0dca9]">有一份未完成的创建草稿</span><span className="mt-1 block text-xs text-[#a99f8c]">恢复后可继续与世界助手对话。</span></span><span className="text-sm text-[#e7c37f]">继续 →</span></button>}
        {worlds.length ? <div className="grid gap-4 md:grid-cols-2">{worlds.map(world => <Surface key={world.name} className={cx('p-5', world.current && 'border-[#d3ad65]/42 bg-[#d3ad65]/[.07]')}><div className="flex items-start justify-between gap-4"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h2 className="atelier-heading truncate text-xl font-semibold text-[#eee7d8]">{world.name}</h2>{world.current && <StateTag tone="brass">当前</StateTag>}</div><p className="mt-2 text-sm text-[#a99f8c]">{world.type || '自定义'} · 已推演 {world.rounds || 0} 轮</p></div><Button aria-label={`删除世界 ${world.name}`} tone="ghost" size="icon" onClick={() => setDeleteTarget(world)}><Trash2 aria-hidden="true" className="h-4 w-4 text-red-200" /></Button></div><div className="mt-6 flex justify-between border-t border-[#d6ccba]/12 pt-4">{world.current ? <span className="text-sm text-[#e7c37f]">正在阅读此世界</span> : <Button tone="secondary" size="sm" onClick={() => switchWorld(world.name)}>切换到此世界</Button>}<span className="text-xs text-[#756e60]">故事卷宗</span></div></Surface>)}</div> : <Surface><EmptyState icon={Globe2} title="书架还是空的" description="从一个场景、一条规则或一份设定文档开始，建立你的第一个叙事世界。" action={<Button tone="primary" icon={Plus} onClick={resetCreation}>开始创建</Button>} /></Surface>}
      </>}

      {view === 'create' && <div className="grid gap-5 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <Surface className="h-fit p-4"><p className="px-2 text-[11px] font-semibold tracking-[.16em] text-[#827a6b]">创建流程</p><ol className="mt-3 space-y-1">{FLOW_STEPS.map((step, index) => <li key={step} className={cx('flex items-center gap-3 rounded-md px-2 py-3 text-sm', index === activeStep ? 'bg-[#d3ad65]/12 text-[#f0dca9]' : index < activeStep ? 'text-[#b8af9e]' : 'text-[#756e60]')}><span className={cx('grid h-6 w-6 place-items-center rounded-full border text-xs', index <= activeStep ? 'border-[#d3ad65]/50 text-[#e7c37f]' : 'border-[#d6ccba]/15')}>{index + 1}</span>{step}</li>)}</ol></Surface>
        <div className="space-y-5">
          {!apiConfigured && <Surface className="border-[#d3ad65]/30 bg-[#d3ad65]/8 p-4"><div className="flex gap-3"><AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 text-[#e7c37f]" /><p className="flex-1 text-sm leading-6 text-[#d7c9aa]">创建世界需要模型连接。请先完成模型配置。</p><Button size="sm" tone="secondary" icon={Settings2} onClick={() => navigate('/settings')}>去配置</Button></div></Surface>}
          {phase === 'brief' && <>
            <Surface className="overflow-hidden"><SectionTitle icon={Globe2}>给世界一个起点</SectionTitle><div className="grid divide-y divide-[#d6ccba]/10 md:grid-cols-2 md:divide-x md:divide-y-0"><button type="button" onClick={startChat} className={cx('p-6 text-left transition-colors hover:bg-[#fbf7ee]/[.04]', entryMode === 'chat' && 'bg-[#d3ad65]/[.06]')}><MessageSquareText aria-hidden="true" className="h-5 w-5 text-[#d3ad65]" /><h2 className="atelier-heading mt-4 text-xl font-semibold text-[#eee7d8]">对话创建</h2><p className="mt-2 text-sm leading-6 text-[#a99f8c]">从一个念头出发，逐步补全世界的规则、角色与矛盾。</p></button><button type="button" onClick={() => fileInputRef.current?.click()} className={cx('p-6 text-left transition-colors hover:bg-[#fbf7ee]/[.04]', entryMode === 'document' && 'bg-[#d3ad65]/[.06]')}><Upload aria-hidden="true" className="h-5 w-5 text-[#d3ad65]" /><h2 className="atelier-heading mt-4 text-xl font-semibold text-[#eee7d8]">导入设定</h2><p className="mt-2 text-sm leading-6 text-[#a99f8c]">读取 .txt、.md 或 .pdf，把已有设定变成可推演世界。</p></button></div><input ref={fileInputRef} type="file" accept=".txt,.md,.pdf" onChange={event => handleUpload(event.target.files?.[0])} className="hidden" /></Surface>
            {entryMode === 'chat' && <Surface className="overflow-hidden"><SectionTitle icon={MessageSquareText}>与世界助手交谈</SectionTitle><div className="max-h-[24rem] min-h-[14rem] space-y-4 overflow-y-auto p-5">{messages.length ? messages.map((message, mi) => <div key={message.id || `chat-${mi}-${message.role}`} className={cx('max-w-2xl rounded-lg px-4 py-3 text-sm leading-7', message.role === 'assistant' ? 'bg-[#fbf7ee]/[.055] text-[#d7cfbf]' : 'ml-auto bg-[#d3ad65]/12 text-[#f0dca9]')}><p className="mb-1 text-[11px] tracking-[.12em] opacity-65">{message.role === 'assistant' ? '世界助手' : '你'}</p>{message.content}</div>) : <p className="pt-10 text-center text-sm text-[#827a6b]">选择“对话创建”后，从一句设定开始。</p>}{sending && <InlineLoader>世界助手正在整理设定…</InlineLoader>}<div ref={chatEndRef} /></div><div className="border-t border-[#d6ccba]/12 p-4"><div className="flex gap-2"><TextInput value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); sendMessage(false) } }} placeholder="描述这个世界的第一件事…" className="min-w-0 flex-1" /><Button tone="primary" size="icon" aria-label="发送设定" icon={Send} onClick={() => sendMessage(false)} disabled={!input.trim() || sending} /></div>{messages.length >= 2 && <Button tone="secondary" size="sm" icon={FileText} onClick={() => sendMessage(true)} disabled={sending} className="mt-3">整理为世界包</Button>}</div></Surface>}
            {docUploading && <Surface className="p-5"><InlineLoader>正在解读 {docFile?.name || '设定文档'}…</InlineLoader></Surface>}
          </>}
          {phase === 'character' && <>
            <Surface className="p-5"><div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-[11px] font-semibold tracking-[.16em] text-[#d3ad65]">第二步</p><h2 className="atelier-heading mt-2 text-2xl font-semibold text-[#eee7d8]">选择你要扮演的人</h2><p className="mt-2 text-sm text-[#a99f8c]">这个选择会决定玩家视角；其余候选将成为世界中的角色。</p></div><label className="block min-w-[14rem]"><span className="atelier-field-label">世界名称</span><TextInput value={newWorldName} onChange={event => setNewWorldName(event.target.value)} placeholder="命名这个世界" className="w-full" /></label></div><div className="mt-6 grid gap-3 md:grid-cols-2">{(worldPackage?.playable_characters || []).map((character, index) => { const id = character.id || character.name || String(index); const selected = selectedCharId === id; return <button type="button" key={id} onClick={() => setSelectedCharId(id)} className={cx('rounded-lg border p-4 text-left transition-colors', selected ? 'border-[#d3ad65]/55 bg-[#d3ad65]/12' : 'border-[#d6ccba]/14 bg-[#fbf7ee]/[.025] hover:border-[#d6ccba]/30')}><div className="flex items-center justify-between gap-3"><span className="atelier-heading text-lg font-semibold text-[#eee7d8]">{character.name}</span>{selected && <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-[#e7c37f]" />}</div><p className="mt-3 text-sm leading-6 text-[#b8af9e]">{character.core_motivation || '尚未写明动机'}</p><p className="mt-3 text-xs text-[#827a6b]">{character.realm || '凡人'} · {character.region || '未知地区'}{character.has_system ? ' · 🔮 有系统/指引者' : ''}</p></button>})}</div><div className="mt-6 flex justify-end border-t border-[#d6ccba]/12 pt-4"><Button tone="primary" icon={Settings2} onClick={goToAgentConfig} disabled={!selectedCharId || !newWorldName.trim()}>下一步：配置世界灵魂</Button></div></Surface>
          </>}
          {phase === 'agent' && <>
            {(() => {
              const wt = worldPackage?.world_type || 'xuanhuan'
              const wtInfo = WORLD_TYPE_LABELS[wt] || WORLD_TYPE_LABELS.custom
              const ac = worldPackage?.agent_config || {}
              const narrator = ac.narrator || {}
              const sysCfg = ac.system || {}
              const selectedPc = (worldPackage?.playable_characters || []).find(c => (c.id || c.name) === selectedCharId)
              return <>
                <Surface className="p-5">
                  <p className="text-[11px] font-semibold tracking-[.16em] text-[#d3ad65]">第三步</p>
                  <h2 className="atelier-heading mt-2 text-2xl font-semibold text-[#eee7d8]">世界灵魂配置</h2>
                  <p className="mt-2 text-sm text-[#a99f8c]">每一个世界都有独特的叙事声音、运行规则和陪伴伙伴。你可以在这里微调。</p>
                  <div className="mt-6 grid gap-4 md:grid-cols-3">
                    <div className="rounded-lg border border-[#d6ccba]/14 bg-[#fbf7ee]/[.025] p-4">
                      <div className="text-2xl">{wtInfo.icon}</div>
                      <h3 className="atelier-heading mt-2 text-base font-semibold text-[#eee7d8]">{wtInfo.name}</h3>
                      <p className="mt-1 text-xs text-[#827a6b]">{wtInfo.desc}</p>
                      {narrator.role && <p className="mt-3 text-xs text-[#b8af9e]"><span className="text-[#d3ad65]">叙事者：</span>{narrator.role}</p>}
                      {narrator.style && <p className="mt-1 text-xs text-[#b8af9e]"><span className="text-[#d3ad65]">风格：</span>{narrator.style}</p>}
                    </div>
                    <div className="rounded-lg border border-[#d6ccba]/14 bg-[#fbf7ee]/[.025] p-4">
                      <UserRound aria-hidden="true" className="h-5 w-5 text-[#d3ad65]" />
                      <h3 className="atelier-heading mt-2 text-base font-semibold text-[#eee7d8]">主角：{selectedPc?.name}</h3>
                      <p className="mt-1 text-xs text-[#827a6b]">{selectedPc?.realm || '凡人'}</p>
                      {selectedPc?.core_motivation && <p className="mt-2 text-xs text-[#b8af9e]">{selectedPc.core_motivation}</p>}
                    </div>
                    <div className="rounded-lg border border-[#d3ad65]/25 bg-[#d3ad65]/[.06] p-4">
                      <Settings2 aria-hidden="true" className="h-5 w-5 text-[#e7c37f]" />
                      <h3 className="atelier-heading mt-2 text-base font-semibold text-[#f0dca9]">系统/指引者</h3>
                      <div className="mt-3 space-y-3">
                        <label className="flex items-center gap-2 text-sm text-[#d7cfbf]">
                          <input type="checkbox" checked={agentSystemEnabled} onChange={e => setAgentSystemEnabled(e.target.checked)} className="h-4 w-4 accent-[#d3ad65]" />
                          启用系统/指引者陪伴
                        </label>
                        {agentSystemEnabled && (
                          <label className="block">
                            <span className="text-xs text-[#a99f8c]">名称</span>
                            <TextInput value={agentSystemName} onChange={e => setAgentSystemName(e.target.value)} placeholder={sysCfg.name || '系统'} className="mt-1 w-full" />
                            {sysCfg.personality && <p className="mt-1 text-xs text-[#827a6b]">性格：{sysCfg.personality}</p>}
                          </label>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="mt-6 flex items-center justify-between border-t border-[#d6ccba]/12 pt-4">
                    <Button tone="ghost" size="sm" onClick={() => setPhase('character')}>← 返回选角</Button>
                    <Button tone="primary" icon={CheckCircle2} onClick={createWorld} disabled={sending}>确认并生成世界</Button>
                  </div>
                </Surface>
              </>
            })()}
          </>}
          {phase === 'creating' && <Surface className="p-8 text-center"><InlineLoader>正在为世界补全角色、记忆和初始关系…</InlineLoader></Surface>}
        </div>
      </div>}

      {deleteTarget && <OverlayDialog onClose={() => !deleting && setDeleteTarget(null)} label="删除世界确认"><div className="p-6 text-center"><div className="mx-auto grid h-12 w-12 place-items-center rounded-full border border-red-300/25 bg-red-400/10"><AlertTriangle aria-hidden="true" className="h-5 w-5 text-red-200" /></div><h2 className="atelier-heading mt-4 text-xl font-semibold text-[#eee7d8]">删除这个世界？</h2><p className="mt-2 text-sm leading-6 text-[#a99f8c]">「{deleteTarget.name}」及其故事记录会被删除，此操作无法撤销。</p><div className="mt-6 flex justify-center gap-3"><Button tone="secondary" onClick={() => setDeleteTarget(null)} disabled={deleting}>取消</Button><Button tone="danger" icon={deleting ? Loader2 : Trash2} className={deleting ? '[&>svg]:animate-spin' : ''} onClick={confirmDelete} disabled={deleting}>确认删除</Button></div></div></OverlayDialog>}
    </WorkspacePage>
  )
}
