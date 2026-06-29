import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, CircleGauge, ClipboardList, ClipboardCheck, FileCheck2, History, Loader2, Play, Settings2, UsersRound } from 'lucide-react'
import { approveChapter, bookExportUrl, compileBook, fetchChapterRevisions, fetchCharacters, fetchState, listCheckpoints, reviewChapter, saveCheckpoint, startRound } from '../api'
import { Button, EmptyState, LoadingState, cx } from '../components/UI'
import { KeyValue, SectionTitle, StateTag, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'
import { useSettings } from '../SettingsContext'
import { useWorld } from '../App'

function chapterTone(status) { return status === 'approved' ? 'success' : status === 'reviewed' ? 'brass' : 'quiet' }
function chapterLabel(status) { return status === 'approved' ? '已批准' : status === 'reviewed' ? '待批准' : '草稿' }

export default function Manager() {
  const navigate = useNavigate()
  const { settings } = useSettings()
  const { currentWorld } = useWorld()
  const [world, setWorld] = useState(null)
  const [characters, setCharacters] = useState([])
  const [quests, setQuests] = useState([])
  const [chapters, setChapters] = useState([])
  const [selectedNPC, setSelectedNPC] = useState(null)
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState([])
  const [approving, setApproving] = useState('')
  const [compiling, setCompiling] = useState(false)
  const [book, setBook] = useState(null)
  const [error, setError] = useState('')
  const [reviewing, setReviewing] = useState('')
  const [reviewReports, setReviewReports] = useState({})
  const [checkpoints, setCheckpoints] = useState([])
  const [savingCheckpoint, setSavingCheckpoint] = useState(false)
  const apiConfigured = Boolean(settings?.apiKey?.trim())

  async function refresh() {
    const [worldData, characterData, questData, chapterData, checkpointData] = await Promise.all([
      fetchState('world.json').catch(() => null), fetchCharacters().catch(() => ({ characters: [] })), fetchState('quests.json').catch(() => ({ active: [] })), fetchChapterRevisions().catch(() => ({ chapters: [] })), listCheckpoints().catch(() => ({ checkpoints: [] })),
    ])
    setWorld(worldData); setCharacters(characterData.characters || []); setQuests(questData.active || []); setChapters(chapterData.chapters || []); setCheckpoints(checkpointData.checkpoints || [])
  }
  useEffect(() => {
    if (!currentWorld) {
      setWorld(null); setCharacters([]); setQuests([]); setChapters([]); setSelectedNPC(null); setEvents([]); setBook(null); setCheckpoints([])
      return
    }
    refresh()
  }, [currentWorld])
  async function advanceRound() { setRunning(true); setEvents([]); setError(''); try { await startRound(event => setEvents(previous => [...previous, event])); await refresh() } catch (cause) { setError(cause.message || '推演启动失败') } finally { setRunning(false) } }
  async function approve(chapter) { setApproving(chapter.id); setError(''); try { await approveChapter(chapter.chapter_no, chapter.revision_no); await refresh() } catch (cause) { setError(cause.message || '章节审批失败') } finally { setApproving('') } }
  async function compile() { setCompiling(true); setError(''); try { const result = await compileBook(world?.meta?.world_name || '未命名长篇'); setBook(result.book) } catch (cause) { setError(cause.message || '小说编译失败') } finally { setCompiling(false) } }
  async function reviewCh(chapter) { setReviewing(chapter.id); setError(''); try { const result = await reviewChapter(chapter.chapter_no, chapter.revision_no); setReviewReports(prev => ({ ...prev, [chapter.id]: result.quality_report })) } catch (cause) { setError(cause.message || '章节审核失败') } finally { setReviewing('') } }
  async function handleSaveCheckpoint() { setSavingCheckpoint(true); setError(''); try { const label = `手动存档 · 第${world?.meta?.current_round ?? 0}轮`; await saveCheckpoint(label); await refresh() } catch (cause) { setError(cause.message || '存档失败') } finally { setSavingCheckpoint(false) } }
  if (!world) return <LoadingState label="正在翻阅世界卷宗…" />

  const facts = [['当前世界', world.meta?.world_name], ['当前轮次', `${world.meta?.current_round ?? 0} 轮`], ['世界时间', `${world.time?.era || ''} ${world.time?.year || ''}年`], ['当前区域', world.geography?.regions?.[world.geography?.current_region]?.name]]
  return <WorkspacePage className="max-w-6xl">
    <WorkspaceHeader trail="世界卷宗" title="管理与成书" description="检查世界状态、审校章节，并把批准的叙事编译为完整小说。" actions={apiConfigured ? <Button tone="primary" icon={running ? Loader2 : Play} className={running ? '[&>svg]:animate-spin' : ''} disabled={running} onClick={advanceRound}>{running ? '正在推进' : '手动推进一轮'}</Button> : <Button tone="primary" icon={Settings2} onClick={() => navigate('/settings')}>连接模型</Button>} />
    {!apiConfigured && <div className="border-l border-[#ad4b3a]/45 bg-[#f5e8e2]/55 px-4 py-3 text-sm leading-6 text-[#625a50]" role="status">连接模型后即可手动推进世界；现有章节仍可在这里审校与编译。</div>}
    {error && <div role="alert" className="rounded-md border border-red-300/25 bg-red-400/10 px-4 py-3 text-sm text-red-100">{error}</div>}
    <Surface className="overflow-hidden"><SectionTitle icon={CircleGauge}>世界状态</SectionTitle><div className="grid gap-5 p-5 sm:grid-cols-2 lg:grid-cols-4">{facts.map(([label, value]) => <KeyValue key={label} label={label} value={value} />)}</div>{events.length > 0 && <div className="max-h-40 overflow-y-auto border-t border-[#d6ccba]/12 bg-[#10110d]/35 px-5 py-4">{events.slice(-12).map((item, index) => <p key={`${item.event}-${index}`} className="py-1 text-xs leading-5 text-[#a99f8c]"><span className="mr-2 text-[#d3ad65]">{item.event}</span>{JSON.stringify(item.data).slice(0, 180)}</p>)}</div>}</Surface>
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <Surface className="overflow-hidden"><SectionTitle icon={FileCheck2} action={<Button tone="primary" size="sm" icon={compiling ? Loader2 : BookOpen} className={compiling ? '[&>svg]:animate-spin' : ''} disabled={compiling || !chapters.some(chapter => chapter.status === 'approved')} onClick={compile}>{compiling ? '编译中' : '编译小说'}</Button>}>章节审校</SectionTitle><div className="divide-y divide-[#d6ccba]/10">{chapters.map((chapter, ci) => <div key={chapter.id || `ch-${chapter.chapter_no}-${chapter.revision_no}-${ci}`} className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex items-center gap-2"><h3 className="atelier-heading text-lg font-semibold text-[#eee7d8]">第 {chapter.chapter_no} 章</h3><StateTag tone={chapterTone(chapter.status)}>{chapterLabel(chapter.status)}</StateTag><span className="text-xs text-[#756e60]">修订 {chapter.revision_no}</span></div><p className="mt-2 truncate text-xs leading-5 text-[#827a6b]">质量信号 {chapter.quality_report?.score ?? '—'} · {chapter.content.slice(0, 110)}</p>{reviewReports[chapter.id] && <p className="mt-1 text-xs leading-5 text-[#a99f8c]">审核报告：分数 {reviewReports[chapter.id].score} · {reviewReports[chapter.id].flags?.length ? reviewReports[chapter.id].flags.join('、') : '无标记问题'}{reviewReports[chapter.id].cliches?.length > 0 && ` · 套话${reviewReports[chapter.id].cliches.length}处`}</p>}</div><div className="flex shrink-0 gap-2"><Button tone="secondary" size="sm" icon={reviewing === chapter.id ? Loader2 : ClipboardCheck} className={reviewing === chapter.id ? '[&>svg]:animate-spin' : ''} disabled={reviewing === chapter.id} onClick={() => reviewCh(chapter)}>{reviewing === chapter.id ? '审核中' : '质量审核'}</Button>{chapter.status !== 'approved' && <Button tone="secondary" size="sm" icon={approving === chapter.id ? Loader2 : FileCheck2} className={approving === chapter.id ? '[&>svg]:animate-spin' : ''} disabled={approving === chapter.id} onClick={() => approve(chapter)}>批准入书</Button>}</div></div>)}{!chapters.length && <EmptyState icon={FileCheck2} title="还没有待审章节" description="场景封口后，章节修订会在这里出现。" />}</div>{book && <div className="flex flex-col gap-3 border-t border-emerald-300/15 bg-emerald-400/[.07] p-5 text-sm text-emerald-100 sm:flex-row sm:items-center sm:justify-between"><span>已编译 {book.chapters} 章，可导出阅读版与稿件。</span><span className="flex gap-2"><a className="rounded-md border border-emerald-200/25 px-3 py-2 text-xs hover:bg-emerald-200/10" href={bookExportUrl('html')}>下载 HTML</a><a className="rounded-md border border-emerald-200/25 px-3 py-2 text-xs hover:bg-emerald-200/10" href={bookExportUrl('md')}>下载 Markdown</a></span></div>}</Surface>
      <Surface className="h-fit overflow-hidden"><SectionTitle icon={UsersRound}>角色索引</SectionTitle><div className="max-h-[28rem] divide-y divide-[#d6ccba]/10 overflow-y-auto">{characters.map((character, ci) => <button key={character.id || character.name || `char-${ci}`} type="button" onClick={() => setSelectedNPC(character)} className={cx('w-full px-5 py-4 text-left transition-colors hover:bg-[#fbf7ee]/[.04]', (selectedNPC?.id === character.id || (selectedNPC && !selectedNPC.id && selectedNPC.name === character.name)) && 'bg-[#d3ad65]/[.08]')}><p className="text-sm font-medium text-[#e8dfd0]">{character.name}</p><p className="mt-1 text-xs text-[#827a6b]">{character.role || character.type || '未知身份'} · {character.location || '未知地点'}</p></button>)}{!characters.length && <div className="p-5"><EmptyState icon={UsersRound} title="暂无角色" description="推演开始后会生成角色。" /></div>}</div>{selectedNPC && <div className="border-t border-[#d6ccba]/12 p-5"><p className="atelier-heading text-lg font-semibold text-[#eee7d8]">{selectedNPC.name}</p><dl className="mt-4 space-y-2 text-sm"><div><dt className="inline text-[#827a6b]">身份 · </dt><dd className="inline text-[#d7cfbf]">{selectedNPC.role || selectedNPC.type || '未知'}</dd></div><div><dt className="inline text-[#827a6b]">位置 · </dt><dd className="inline text-[#d7cfbf]">{selectedNPC.location || '未知'}</dd></div><div><dt className="inline text-[#827a6b]">状态 · </dt><dd className="inline text-[#d7cfbf]">{selectedNPC.status || '活跃'}</dd></div></dl></div>}</Surface>
    </div>
    <Surface className="overflow-hidden"><SectionTitle icon={ClipboardList}>任务索引</SectionTitle><div className="divide-y divide-[#d6ccba]/10">{quests.map((quest, qi) => <div key={quest.id || quest.name || quest.title || `quest-${qi}`} className="px-5 py-4"><h3 className="text-sm font-medium text-[#e7decf]">{quest.name || quest.title}</h3><p className="mt-1 text-xs leading-5 text-[#827a6b]">{quest.description}</p></div>)}{!quests.length && <div className="p-5"><EmptyState icon={ClipboardList} title="暂无活跃任务" description="当世界生成任务线后，会在这里出现。" /></div>}</div></Surface>
    <Surface className="overflow-hidden"><SectionTitle icon={History} action={<Button tone="secondary" size="sm" icon={savingCheckpoint ? Loader2 : History} className={savingCheckpoint ? '[&>svg]:animate-spin' : ''} disabled={savingCheckpoint} onClick={handleSaveCheckpoint}>{savingCheckpoint ? '存档中' : '创建存档'}</Button>}>存档管理</SectionTitle><div className="max-h-72 divide-y divide-[#d6ccba]/10 overflow-y-auto">{checkpoints.map((cp, ci) => <div key={cp.id || `cp-${ci}`} className="px-5 py-3"><div className="flex items-center justify-between"><p className="text-sm font-medium text-[#e7decf]">{cp.label}</p><span className="text-xs text-[#756e60]">事件 #{cp.event_sequence}</span></div><p className="mt-1 text-xs text-[#827a6b]">{cp.created_at ? new Date(cp.created_at * 1000).toLocaleString('zh-CN') : ''}</p></div>)}{!checkpoints.length && <div className="p-5"><EmptyState icon={History} title="暂无存档" description="推演时会自动创建存档，也可手动创建。" /></div>}</div></Surface>
  </WorkspacePage>
}
