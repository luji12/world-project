import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  BookOpen, ChevronLeft, ChevronRight, Edit3, List, Loader2, Menu, Moon, Save, Settings2,
  Sparkles, Sun, X, ZoomIn, ZoomOut,
} from 'lucide-react'
import {
  fetchChapterRevisions, fetchChronicle, fetchForeshadows, fetchStoryContext, polishChapter, saveChapterEdit,
} from '../api'
import { useWorld } from '../App'

const FALLBACK_VOLUMES = [
  { id: 'volume-01', label: '第一卷' },
  { id: 'volume-02', label: '第二卷' },
  { id: 'volume-03', label: '第三卷' },
]

const PAPER = {
  paper: {
    shell: 'bg-[#e9e1d2] text-[#2c2720]',
    surface: 'bg-[#fbf7ee] text-[#2c2720]',
    chrome: 'border-[#d6ccba] bg-[#f5efe3]/95 text-[#4b4236]',
    muted: 'text-[#786e60]',
    line: 'border-[#d6ccba]',
    accent: 'text-[#a13d2f]',
    accentBorder: 'border-[#b45243]',
    active: 'bg-[#e8ded0] text-[#382d22]',
  },
  night: {
    shell: 'bg-[#14130f] text-[#eee5d5]',
    surface: 'bg-[#1b1914] text-[#eee5d5]',
    chrome: 'border-[#453d30] bg-[#181712]/95 text-[#d7cbb6]',
    muted: 'text-[#a69b88]',
    line: 'border-[#453d30]',
    accent: 'text-[#d7a85f]',
    accentBorder: 'border-[#8d6837]',
    active: 'bg-[#302b20] text-[#fff6e8]',
  },
}

function chapterLabel(chapter) {
  return `第 ${chapter.chapter_no} 章`
}

function contentParagraphs(content) {
  const blocks = (content || '').split(/\n{2,}/).map(item => item.trim()).filter(Boolean)
  return blocks
    .filter((item, index) => !(index === 0 && /^#\s+/.test(item)))
    .filter(item => item !== '---')
    .map(item => item
      .replace(/^\s*>\s?/gm, '')
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\*(.*?)\*/g, '$1')
      .trim())
    .filter(Boolean)
}

function ReaderRail({ chapters, selectedId, onSelect, palette, isOpen, onClose }) {
  return (
    <aside className={`absolute inset-y-0 left-0 z-20 w-72 shrink-0 border-r ${palette.line} ${palette.surface} transition-transform lg:static lg:translate-x-0 ${isOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'} lg:shadow-none`}>
      <div className={`flex h-16 items-center justify-between border-b px-5 ${palette.line}`}>
        <div className="flex min-w-0 items-center gap-3">
          <div className={`flex h-8 w-8 items-center justify-center rounded-full border ${palette.accentBorder}`}>
            <BookOpen className={`h-4 w-4 ${palette.accent}`} aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="truncate font-serif text-base font-semibold">作品目录</p>
            <p className={`mt-0.5 text-[11px] ${palette.muted}`}>已定稿章节</p>
          </div>
        </div>
        <button onClick={onClose} className="rounded p-2 lg:hidden" aria-label="关闭目录">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <nav className="h-[calc(100%-4rem)] overflow-y-auto px-3 py-5" aria-label="章节目录">
        <p className={`px-3 pb-3 text-[11px] font-semibold tracking-[0.16em] ${palette.muted}`}>正文</p>
        <div className="space-y-1">
          {chapters.map((chapter, ci) => (
            <button
              key={chapter.id || `ch-${chapter.chapter_no}-${ci}`}
              onClick={() => { onSelect(chapter.id); onClose() }}
              className={`flex min-h-11 w-full items-center rounded-md px-3 text-left text-sm transition-colors ${chapter.id === selectedId ? palette.active : `hover:bg-black/5 dark:hover:bg-white/5 ${palette.muted}`}`}
              aria-current={chapter.id === selectedId ? 'page' : undefined}
            >
              <span className="mr-3 font-serif text-xs opacity-60">{String(chapter.chapter_no).padStart(2, '0')}</span>
              <span className="truncate">{chapter.displayTitle}</span>
            </button>
          ))}
        </div>
      </nav>
    </aside>
  )
}

function ThreadPanel({ context, resolvedForeshadows, palette, visible }) {
  if (!visible) return null
  const threads = context?.open_foreshadows || []
  const facts = context?.facts || []
  const resolved = resolvedForeshadows || []
  return (
    <aside className={`hidden w-72 shrink-0 overflow-y-auto border-l ${palette.line} ${palette.surface} xl:block`} aria-label="故事线索">
      <div className={`border-b px-6 py-5 ${palette.line}`}>
        <p className="font-serif text-lg font-semibold">故事线索</p>
        <p className={`mt-1 text-xs ${palette.muted}`}>仅展示可公开的叙事状态</p>
      </div>
      <section className={`border-b px-6 py-5 ${palette.line}`}>
        <h2 className={`text-[11px] font-semibold tracking-[0.16em] ${palette.muted}`}>未回收伏笔</h2>
        {threads.length ? (
          <ol className="mt-4 space-y-4">
            {threads.slice(0, 5).map((thread, ti) => (
              <li key={thread.id || `thread-${ti}`} className="relative border-l border-current/20 pl-4">
                <span className={`absolute -left-[5px] top-1 h-2 w-2 rounded-full ${thread.overdue ? 'bg-red-500' : 'bg-[#b45243]'}`} />
                <p className="font-serif text-sm font-semibold leading-6">{thread.title}</p>
                <p className={`mt-1 text-xs leading-5 ${palette.muted}`}>{thread.detail}</p>
              </li>
            ))}
          </ol>
        ) : <p className={`mt-4 text-sm leading-6 ${palette.muted}`}>这一卷还没有需要追踪的公开伏笔。</p>}
      </section>
      {resolved.length > 0 && (
        <section className={`border-b px-6 py-5 ${palette.line}`}>
          <h2 className={`text-[11px] font-semibold tracking-[0.16em] ${palette.muted}`}>已回收伏笔</h2>
          <ol className="mt-4 space-y-3">
            {resolved.slice(0, 8).map((thread, ti) => (
              <li key={thread.id || `resolved-${ti}`} className="relative border-l border-emerald-500/30 pl-4 opacity-70">
                <span className="absolute -left-[5px] top-1 h-2 w-2 rounded-full bg-emerald-500" />
                <p className="font-serif text-sm leading-6 line-through">{thread.title}</p>
                <p className={`mt-0.5 text-xs leading-5 ${palette.muted}`}>{thread.detail}</p>
              </li>
            ))}
          </ol>
        </section>
      )}
      <section className="px-6 py-5">
        <h2 className={`text-[11px] font-semibold tracking-[0.16em] ${palette.muted}`}>当前事实</h2>
        <ul className="mt-4 space-y-3">
          {facts.slice(0, 5).map((fact, fi) => (
            <li key={fact.id || fact.subject_id || `fact-${fi}`} className={`text-xs leading-5 ${palette.muted}`}>{fact.metadata?.name || fact.subject_id} · {fact.object_value}</li>
          ))}
          {!facts.length && <li className={`text-sm ${palette.muted}`}>尚未归档事实。</li>}
        </ul>
      </section>
    </aside>
  )
}

export default function Reader() {
  const { volume = 'volume-01' } = useParams()
  const navigate = useNavigate()
  const { currentWorld } = useWorld()
  const [theme, setTheme] = useState('paper')
  const [fontScale, setFontScale] = useState(1)
  const [lineHeight, setLineHeight] = useState(2)
  const [focusMode, setFocusMode] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [railOpen, setRailOpen] = useState(false)
  const [chapters, setChapters] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [fallback, setFallback] = useState('')
  const [context, setContext] = useState(null)
  const [resolvedForeshadows, setResolvedForeshadows] = useState([])
  const [loading, setLoading] = useState(true)
  const [editMode, setEditMode] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [editTitle, setEditTitle] = useState('')
  const [polishing, setPolishing] = useState(false)
  const [savingEdit, setSavingEdit] = useState(false)
  const [polishNotice, setPolishNotice] = useState('')
  const [editError, setEditError] = useState('')

  async function reloadChapters(preferId) {
    try {
      const chapterData = await fetchChapterRevisions('')
      const all = chapterData.chapters || []
      const latestMap = new Map()
      for (const ch of all) {
        const existing = latestMap.get(ch.chapter_no)
        if (!existing || ch.revision_no > existing.revision_no) latestMap.set(ch.chapter_no, ch)
      }
      const latest = Array.from(latestMap.values()).sort((a, b) => a.chapter_no - b.chapter_no).map(ch => ({
        ...ch,
        displayTitle: ch.title || `第 ${ch.chapter_no} 章`,
      }))
      setChapters(latest)
      const target = preferId ? latest.find(c => c.id === preferId) : null
      if (target) {
        setSelectedId(target.id)
      } else {
        setSelectedId(previous => previous || latest[0]?.id || '')
      }
    } catch {
      setChapters([])
    }
  }

  useEffect(() => {
    if (!currentWorld) {
      setChapters([])
      setSelectedId('')
      setFallback('')
      setContext(null)
      setResolvedForeshadows([])
      setLoading(false)
      setEditMode(false)
      return undefined
    }
    let active = true
    setLoading(true)
    Promise.all([
      reloadChapters(),
      fetchChronicle(volume).catch(() => ({ content: '' })),
      fetchStoryContext().catch(() => null),
      fetchForeshadows().catch(() => ({ resolved: [] })),
    ]).then(([, chronicle, storyContext, foreshadows]) => {
      if (!active) return
      setFallback(chronicle.content || '')
      setContext(storyContext)
      setResolvedForeshadows(foreshadows.resolved || [])
    }).finally(() => active && setLoading(false))
    return () => { active = false }
  }, [currentWorld, volume])

  const palette = PAPER[theme]
  const selectedIndex = chapters.findIndex(chapter => chapter.id === selectedId)
  const selected = selectedIndex >= 0 ? chapters[selectedIndex] : null
  const activeContent = selected?.content || fallback
  const paragraphs = useMemo(() => contentParagraphs(activeContent), [activeContent])
  const canGoBack = selectedIndex > 0
  const canGoForward = selectedIndex >= 0 && selectedIndex < chapters.length - 1
  const currentTitle = selected?.title || FALLBACK_VOLUMES.find(item => item.id === volume)?.label || '第一卷'

  const jump = (direction) => {
    if (editMode) return
    const next = chapters[selectedIndex + direction]
    if (next) setSelectedId(next.id)
  }

  function enterEdit() {
    if (!selected) return
    setEditContent(selected.content || '')
    setEditTitle(selected.title || '')
    setEditMode(true)
    setPolishNotice('')
    setEditError('')
    setSettingsOpen(false)
  }

  function cancelEdit() {
    setEditMode(false)
    setEditContent('')
    setEditTitle('')
    setPolishNotice('')
    setEditError('')
  }

  async function doPolish() {
    if (!editContent.trim() || polishing) return
    setPolishing(true)
    setEditError('')
    setPolishNotice('')
    const before = editContent
    try {
      const result = await polishChapter(editContent)
      const polished = result.polished
      if (polished && polished !== editContent) {
        setEditContent(polished)
        setPolishNotice('AI 润色已应用，你可以继续编辑或保存')
      } else {
        setPolishNotice('润色完成，内容变化不大')
      }
    } catch (cause) {
      setEditError(cause.message || '润色失败')
      setEditContent(before)
    } finally {
      setPolishing(false)
    }
  }

  async function saveEdit() {
    if (!selected || savingEdit) return
    const content = editContent.trim()
    if (!content) { setEditError('内容不能为空'); return }
    setSavingEdit(true)
    setEditError('')
    try {
      const result = await saveChapterEdit(selected.chapter_no, selected.revision_no, content, editTitle.trim())
      await reloadChapters(result.revision?.id)
      setEditMode(false)
      setEditContent('')
      setEditTitle('')
      setPolishNotice('')
    } catch (cause) {
      setEditError(cause.message || '保存失败')
    } finally {
      setSavingEdit(false)
    }
  }

  return (
    <div className={`relative flex h-full overflow-hidden ${palette.shell}`}>
      {railOpen && <button className="fixed inset-0 z-10 bg-black/35 lg:hidden" onClick={() => setRailOpen(false)} aria-label="关闭目录遮罩" />}
      {!focusMode && <ReaderRail chapters={chapters} selectedId={selectedId} onSelect={setSelectedId} palette={palette} isOpen={railOpen} onClose={() => setRailOpen(false)} />}

      <section className={`relative flex min-w-0 flex-1 flex-col ${palette.surface}`}>
        <header className={`flex min-h-16 shrink-0 items-center justify-between border-b px-4 md:px-8 ${palette.chrome} ${palette.line}`}>
          {editMode ? (
            <>
              <div className="flex min-w-0 items-center gap-2 md:gap-3">
                <button onClick={cancelEdit} disabled={savingEdit} className="inline-flex items-center gap-1 rounded px-2 py-1.5 text-xs hover:bg-black/5 disabled:opacity-50"><X className="h-3.5 w-3.5" />取消编辑</button>
                <span className={`hidden sm:inline text-xs ${palette.muted}`}>正在编辑第 {selected?.chapter_no} 章 · 修订 {selected?.revision_no}</span>
              </div>
              <div className="flex items-center gap-2">
                {polishNotice && <span className="hidden sm:inline text-xs text-emerald-600 dark:text-emerald-400">{polishNotice}</span>}
                <button onClick={doPolish} disabled={polishing || savingEdit} className={`inline-flex items-center gap-1 rounded border px-3 py-1.5 text-xs ${palette.line} hover:bg-black/5 disabled:opacity-50`}>{polishing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}AI 润色</button>
                <button onClick={saveEdit} disabled={savingEdit || polishing} className="inline-flex items-center gap-1 rounded bg-[#b45243] px-3 py-1.5 text-xs text-white hover:bg-[#9a3f32] disabled:opacity-50">{savingEdit ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}保存为新修订</button>
              </div>
            </>
          ) : (
            <>
              <div className="flex min-w-0 items-center gap-2 md:gap-4">
                <button onClick={() => window.dispatchEvent(new Event('world-nav:open'))} className={`rounded p-2 hover:bg-black/5 ${palette.muted}`} aria-label="打开主导航"><Menu className="h-4 w-4" /></button>
                {!focusMode && <button onClick={() => setRailOpen(true)} className="rounded p-2 hover:bg-black/5 lg:hidden" aria-label="打开目录"><List className="h-4 w-4" /></button>}
                <button onClick={() => navigate('/reader')} className={`hidden rounded p-2 hover:bg-black/5 sm:block ${palette.muted}`} aria-label="返回卷目录"><ChevronLeft className="h-4 w-4" /></button>
                <p className={`truncate font-serif text-sm md:text-base ${palette.muted}`}>{currentTitle}</p>
                <span className={`hidden h-4 border-l sm:block ${palette.line}`} />
                <p className={`truncate font-serif text-sm font-semibold md:text-base`}>{selected?.displayTitle || '编年正文'}</p>
                {selected && selected.status === 'reviewed' && <span className="hidden sm:inline rounded-sm border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">待审批</span>}
              </div>
              <div className="flex items-center gap-1">
                {selected && (
                  <button onClick={enterEdit} className={`inline-flex items-center gap-1 rounded px-2 py-1.5 text-xs hover:bg-black/5 ${palette.muted}`}><Edit3 className="h-3.5 w-3.5" />编辑</button>
                )}
                <button onClick={() => setFocusMode(value => !value)} className={`rounded p-2 text-xs hover:bg-black/5 ${palette.muted}`} aria-pressed={focusMode}>{focusMode ? '退出专注' : '专注'}</button>
                <div className="relative">
                  <button onClick={() => setSettingsOpen(value => !value)} className="rounded p-2 hover:bg-black/5" aria-label="阅读设置" aria-expanded={settingsOpen}><Settings2 className="h-4 w-4" /></button>
                  {settingsOpen && (
                    <div className={`absolute right-0 top-11 z-30 w-60 border p-4 shadow-xl ${palette.surface} ${palette.line}`}>
                      <div className="flex items-center justify-between"><span className="text-xs font-semibold">字体大小</span><div className="flex gap-1"><button className="rounded p-1.5 hover:bg-black/5" onClick={() => setFontScale(value => Math.max(.88, value - .06))} aria-label="减小字体"><ZoomOut className="h-4 w-4" /></button><button className="rounded p-1.5 hover:bg-black/5" onClick={() => setFontScale(value => Math.min(1.22, value + .06))} aria-label="增大字体"><ZoomIn className="h-4 w-4" /></button></div></div>
                      <div className="mt-4"><p className="text-xs font-semibold">行距</p><div className="mt-2 grid grid-cols-3 gap-1">{[1.75, 2, 2.25].map(value => <button key={value} onClick={() => setLineHeight(value)} className={`rounded border px-2 py-1.5 text-xs ${lineHeight === value ? `${palette.active} ${palette.accentBorder}` : palette.line}`}>{value}×</button>)}</div></div>
                      <button onClick={() => setTheme(value => value === 'paper' ? 'night' : 'paper')} className={`mt-4 flex w-full items-center justify-between border-t pt-4 text-xs ${palette.line}`}><span>阅读主题</span>{theme === 'paper' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</button>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </header>

        {editMode && editError && (
          <div className="shrink-0 border-b border-red-400/30 bg-red-500/10 px-6 py-2 text-xs text-red-600 dark:text-red-300">{editError}</div>
        )}
        {editMode && polishNotice && !editError && (
          <div className="shrink-0 border-b border-emerald-400/30 bg-emerald-500/10 px-6 py-2 text-xs text-emerald-700 dark:text-emerald-300 sm:hidden">{polishNotice}</div>
        )}

        <article className={`mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-6 py-12 sm:px-12 md:py-20 ${editMode ? 'pt-6' : ''}`}>
          {editMode ? (
            <div className="space-y-4">
              <label className="block">
                <span className={`text-xs font-semibold tracking-[.12em] ${palette.muted}`}>章节标题</span>
                <input
                  type="text"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  placeholder="输入章节标题"
                  className={`mt-2 w-full border-b bg-transparent pb-2 font-serif text-2xl font-semibold tracking-[0.08em] outline-none ${palette.line} focus:border-[#b45243]`}
                />
              </label>
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                placeholder="在此编辑章节正文……"
                rows={24}
                className={`w-full resize-y rounded-lg border p-4 font-serif text-base leading-8 outline-none transition-colors ${palette.line} ${palette.surface} focus:border-[#b45243]/60 focus:ring-4 focus:ring-[#b45243]/10`}
                style={{ fontSize: `${1.05 * fontScale}rem`, lineHeight }}
              />
              <p className={`text-right text-xs ${palette.muted}`}>{editContent.length} 字</p>
            </div>
          ) : loading ? <p className={`font-serif text-center text-sm ${palette.muted}`}>正在翻开这一页……</p> : paragraphs.length ? (
            <>
              <header className="mb-14 text-center">
                <p className={`text-xs tracking-[0.22em] ${palette.accent}`}>{selected ? `第${selected.chapter_no}章 · ${selected.word_count ? `${selected.word_count}字` : `修订 ${selected.revision_no}`}` : '世界编年'}</p>
                <h1 className="mt-5 font-serif text-3xl font-semibold tracking-[0.12em] sm:text-4xl">{selected?.displayTitle || currentTitle}</h1>
                <div className={`mx-auto mt-7 h-px w-24 ${theme === 'paper' ? 'bg-[#b45243]' : 'bg-[#d7a85f]'}`} />
              </header>
              <div className="font-serif" style={{ fontSize: `${1.125 * fontScale}rem`, lineHeight }}>
                {paragraphs.map((paragraph, index) => <p key={`${index}-${paragraph.slice(0, 12)}`} className="mb-6 text-pretty indent-8 tracking-[0.025em]">{paragraph}</p>)}
              </div>
            </>
          ) : <div className={`pt-24 text-center font-serif ${palette.muted}`}><BookOpen className="mx-auto mb-5 h-7 w-7" /><p>还没有已定稿的章节。</p><p className="mt-2 text-sm">完成推演并通过审校后，故事会在这里展开。</p></div>}
        </article>

        <footer className={`flex min-h-20 shrink-0 items-center justify-between border-t px-6 font-serif text-sm ${palette.line} ${palette.chrome} ${editMode ? 'opacity-60' : ''}`}>
          <button disabled={!canGoBack || editMode} onClick={() => jump(-1)} className="inline-flex min-h-11 items-center gap-2 disabled:opacity-30"><ChevronLeft className="h-4 w-4" />上一章</button>
          <span className={`hidden text-xs sm:block ${palette.muted}`}>{editMode ? '编辑模式' : (selected ? `${selectedIndex + 1} / ${chapters.length}` : '编年正文')}</span>
          <button disabled={!canGoForward || editMode} onClick={() => jump(1)} className="inline-flex min-h-11 items-center gap-2 disabled:opacity-30">下一章<ChevronRight className="h-4 w-4" /></button>
        </footer>
      </section>
      <ThreadPanel context={context} resolvedForeshadows={resolvedForeshadows} palette={palette} visible={!focusMode} />
    </div>
  )
}
