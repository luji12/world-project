import { useCallback, useEffect, useMemo, useState } from 'react'
import { BookMarked, CheckCircle2, FileText, GitBranch, Loader2, RefreshCcw, RotateCcw, ShieldAlert } from 'lucide-react'
import { fetchCanonBible, fetchCanonConflicts, fetchCanonSource, fetchCanonStatus, recompileCanon, resetCanonWorld, resolveCanonConflict } from '../api'
import { Button, EmptyState, cx } from '../components/UI'
import { KeyValue, SectionTitle, StateTag, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'

function safeList(value) {
  return Array.isArray(value) ? value : value ? [value] : []
}

function JsonBlock({ value }) {
  return (
    <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap bg-[#fffdf8] p-4 text-xs leading-6 text-[#3d3831]">
      {JSON.stringify(value || {}, null, 2)}
    </pre>
  )
}

export default function Canon() {
  const [status, setStatus] = useState(null)
  const [source, setSource] = useState('')
  const [bible, setBible] = useState(null)
  const [conflicts, setConflicts] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [nextStatus, nextSource, nextBible, nextConflicts] = await Promise.all([
        fetchCanonStatus(),
        fetchCanonSource().catch(() => ({ source: '' })),
        fetchCanonBible().catch(() => null),
        fetchCanonConflicts().catch(() => ({ conflicts: [] })),
      ])
      setStatus(nextStatus)
      setSource(nextSource?.source || '')
      setBible(nextBible)
      setConflicts(nextConflicts?.conflicts || [])
    } catch (cause) {
      setError(cause.message || 'Canon 加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const arcs = useMemo(() => safeList(bible?.story_arcs?.arcs), [bible])
  const hardFacts = useMemo(() => safeList(bible?.constraints?.hard_facts), [bible])
  const openConflicts = conflicts.filter(item => item?.status !== 'resolved' && item?.status !== 'ignored')

  async function recompile() {
    setBusy('recompile')
    setError('')
    try {
      await recompileCanon()
      await load()
    } catch (cause) {
      setError(cause.message || '重新编译失败')
    } finally {
      setBusy('')
    }
  }

  async function resetWorld() {
    setBusy('reset')
    setError('')
    try {
      await resetCanonWorld()
      await load()
    } catch (cause) {
      setError(cause.message || '按 Canon 重开失败')
    } finally {
      setBusy('')
    }
  }

  async function resolve(id) {
    setBusy(id)
    try {
      await resolveCanonConflict(id, 'resolved')
      await load()
    } catch (cause) {
      setError(cause.message || '冲突标记失败')
    } finally {
      setBusy('')
    }
  }

  return (
    <WorkspacePage>
      <WorkspaceHeader
        trail="Canon Engine"
        title="世界圣经"
        description="这里保存原始脚本、结构化设定、主线轨道和冲突记录。后续所有 Agent 推演都会先服从这些约束。"
        actions={(
          <>
            <Button tone="secondary" icon={busy === 'recompile' ? Loader2 : RefreshCcw} className={busy === 'recompile' ? '[&>svg]:animate-spin' : ''} disabled={Boolean(busy)} onClick={recompile}>重新编译</Button>
            <Button tone="primary" icon={busy === 'reset' ? Loader2 : RotateCcw} className={busy === 'reset' ? '[&>svg]:animate-spin' : ''} disabled={Boolean(busy)} onClick={resetWorld}>按 Canon 重开</Button>
          </>
        )}
      />

      {error && <Surface className="border-[#ad4b3a]/30 bg-[#f5e8e2] p-4 text-sm text-[#8f382d]">{error}</Surface>}
      {loading ? (
        <Surface><EmptyState icon={Loader2} title="正在读取世界圣经" description="Canon 正在从当前世界目录加载。" /></Surface>
      ) : !status?.exists ? (
        <Surface>
          <EmptyState
            icon={ShieldAlert}
            title="这个世界还没有 Canon"
            description="可以点击“按 Canon 重开”，系统会先备份旧世界，再从现有框架重建可约束的运行状态。"
            action={<Button tone="primary" icon={RotateCcw} disabled={Boolean(busy)} onClick={resetWorld}>备份并重开</Button>}
          />
        </Surface>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(22rem,.8fr)]">
          <div className="space-y-6">
            <Surface className="overflow-hidden">
              <SectionTitle icon={GitBranch} action={<StateTag tone="brass">{status.current_arc?.name || '当前阶段'}</StateTag>}>主线轨道</SectionTitle>
              <div className="grid gap-4 p-5 md:grid-cols-3">
                <KeyValue label="起始地区" value={status.starting_region} />
                <KeyValue label="阶段数量" value={`${status.arc_count || 0} 个`} />
                <KeyValue label="硬约束" value={`${status.hard_constraints || 0} 条`} />
              </div>
              <ol className="divide-y divide-[#d6ccba]/70 border-t border-[#d6ccba]/70">
                {arcs.map((arc, index) => (
                  <li key={arc.id || arc.name || index} className={cx('p-5', arc.id === status.current_arc?.id && 'bg-[#f5e8e2]/65')}>
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-[11px] tracking-[.16em] text-[#a94334]">阶段 {arc.order || index + 1}</span>
                      <h3 className="atelier-heading text-lg font-semibold text-[#2f2b25]">{arc.name}</h3>
                      <StateTag tone={arc.status === 'active' ? 'brass' : 'quiet'}>{arc.status || 'locked'}</StateTag>
                    </div>
                    <div className="mt-3 grid gap-3 text-sm leading-6 text-[#625a50] md:grid-cols-2">
                      <p>进入条件：{safeList(arc.entry_conditions).join('；') || '—'}</p>
                      <p>退出条件：{safeList(arc.exit_conditions).join('；') || '—'}</p>
                    </div>
                    <ul className="mt-3 space-y-1 text-sm text-[#766e64]">
                      {safeList(arc.required_milestones).map((item, mi) => <li key={mi}>· {item.name || String(item)}</li>)}
                    </ul>
                  </li>
                ))}
              </ol>
            </Surface>

            <Surface className="overflow-hidden">
              <SectionTitle icon={BookMarked}>结构化世界圣经</SectionTitle>
              <JsonBlock value={bible?.world_bible} />
            </Surface>

            <Surface className="overflow-hidden">
              <SectionTitle icon={FileText}>原始脚本</SectionTitle>
              <pre className="max-h-[34rem] overflow-auto whitespace-pre-wrap p-5 text-sm leading-7 text-[#3d3831]">{source || '暂无原文。'}</pre>
            </Surface>
          </div>

          <aside className="space-y-6">
            <Surface className="overflow-hidden">
              <SectionTitle icon={ShieldAlert} action={<StateTag tone={openConflicts.length ? 'danger' : 'success'}>{openConflicts.length} 未处理</StateTag>}>约束冲突</SectionTitle>
              {conflicts.length ? (
                <div className="max-h-[28rem] divide-y divide-[#d6ccba]/70 overflow-auto">
                  {conflicts.map((item, index) => (
                    <div key={item.id || index} className="p-4">
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-sm font-medium text-[#2f2b25]">{item.message || item.type || 'Canon 冲突'}</p>
                        <StateTag tone={item.status === 'resolved' ? 'success' : 'brass'}>{item.status || 'open'}</StateTag>
                      </div>
                      <p className="mt-2 text-xs leading-5 text-[#766e64]">{item.agent || 'unknown'} · {item.created_at || ''}</p>
                      {item.status !== 'resolved' && <Button size="sm" tone="secondary" icon={busy === item.id ? Loader2 : CheckCircle2} className={cx('mt-3', busy === item.id && '[&>svg]:animate-spin')} disabled={Boolean(busy)} onClick={() => resolve(item.id)}>标记已处理</Button>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-5"><EmptyState icon={CheckCircle2} title="暂无冲突" description="推演输出仍在 Canon 轨道内。" /></div>
              )}
            </Surface>

            <Surface className="overflow-hidden">
              <SectionTitle icon={ShieldAlert}>硬约束索引</SectionTitle>
              <div className="max-h-[28rem] space-y-2 overflow-auto p-5">
                {hardFacts.map((fact, index) => (
                  <div key={`${fact.key}-${index}`} className="border-l border-[#ad4b3a]/45 pl-3 text-sm">
                    <p className="font-medium text-[#2f2b25]">{fact.key}</p>
                    <p className="mt-1 text-[#766e64]">{String(fact.value || '')}</p>
                  </div>
                ))}
                {!hardFacts.length && <p className="text-sm text-[#766e64]">暂无硬约束。</p>}
              </div>
            </Surface>
          </aside>
        </div>
      )}
    </WorkspacePage>
  )
}
