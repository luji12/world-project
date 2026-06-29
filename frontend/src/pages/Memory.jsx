import { useEffect, useMemo, useState } from 'react'
import { Brain, Star } from 'lucide-react'
import { EmptyState, cx } from '../components/UI'
import { Segmented, StateTag, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'
import { fetchMemory } from '../api'
import { useWorld } from '../App'

const MEMORY_TYPES = [
  { value: 'all', label: '全部' }, { value: 'recent', label: '近期' }, { value: 'milestones', label: '里程碑' }, { value: 'compressed', label: '压缩记忆' },
]

export default function Memory() {
  const { currentWorld } = useWorld()
  const [data, setData] = useState(null)
  const [selectedChar, setSelectedChar] = useState('protagonist')
  const [memType, setMemType] = useState('all')
  useEffect(() => {
    if (!currentWorld) {
      setData(null)
      setSelectedChar('protagonist')
      return
    }
    fetchMemory(memType, selectedChar).then(setData).catch(() => setData(null))
  }, [currentWorld, memType, selectedChar])
  const characters = data?.characters || {}
  const entries = characters[selectedChar]?.entries || []
  const retention = useMemo(() => [100, 88, 72, 55, 40, 28, 18, 12, 7, 3], [])

  return (
    <WorkspacePage className="max-w-6xl">
      <WorkspaceHeader trail="叙事账本" title="记忆系统" description="查看角色经历如何被保留、压缩和重新调取。" />
      <Surface className="p-4 md:p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 flex-wrap gap-2">
            {Object.entries(characters).map(([id, character]) => <button key={id} type="button" onClick={() => setSelectedChar(id)} className={cx('min-h-10 rounded-md border px-3 text-sm transition-colors', selectedChar === id ? 'border-[#d3ad65]/45 bg-[#d3ad65]/12 text-[#f0dca9]' : 'border-[#d6ccba]/14 text-[#a99f8c] hover:bg-[#fbf7ee]/[.05] hover:text-[#eee7d8]')}>{character.name}<span className="ml-1.5 text-xs opacity-65">{character.total || 0}</span></button>)}
            {!Object.keys(characters).length && <span className="px-1 py-2 text-sm text-[#827a6b]">暂无角色记忆</span>}
          </div>
          <Segmented ariaLabel="记忆层级" value={memType} onChange={setMemType} items={MEMORY_TYPES} />
        </div>
      </Surface>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <Surface className="min-h-[28rem] overflow-hidden">
          <div className="border-b border-[#d6ccba]/12 px-5 py-4"><h2 className="atelier-heading text-xl font-semibold text-[#eee7d8]">{characters[selectedChar]?.name || '角色'}的经历</h2></div>
          {entries.length ? <ol className="divide-y divide-[#d6ccba]/10">{entries.map((entry, index) => <li key={`memory-${entry.round || 'unknown'}-${index}`} className="px-5 py-4"><div className="flex items-center justify-between gap-3"><span className="text-xs tracking-[.12em] text-[#827a6b]">第 {entry.round || '？'} 轮</span>{entry.importance >= 4 && <StateTag tone="brass"><Star aria-hidden="true" className="mr-1 h-3 w-3" />重要</StateTag>}</div><p className="mt-3 text-sm leading-7 text-[#d7cfbf]">{entry.content || entry.summary || JSON.stringify(entry)}</p></li>)}</ol> : <EmptyState icon={Brain} title="这一层还没有可读记忆" description="推演开始后，角色经历会在这里沉淀。" />}
        </Surface>
        <Surface className="h-fit p-5"><div className="flex items-center gap-2 text-[#d3ad65]"><Brain aria-hidden="true" className="h-4 w-4" /><span className="text-xs font-semibold tracking-[.14em]">留存曲线</span></div><div className="mt-6 flex h-36 items-end gap-1.5 border-b border-[#d6ccba]/20 pb-3">{retention.map((value, index) => <div key={`ret-${index}-${value}`} className="flex flex-1 flex-col items-center justify-end gap-1"><div className="w-full min-w-1 rounded-t bg-[#d3ad65]/70" style={{ height: `${value}%` }} /><span className="text-[9px] text-[#756e60]">{index + 1}</span></div>)}</div><p className="mt-4 text-xs leading-5 text-[#827a6b]">日常细节随时间压缩，关键节点将长期保留。</p></Surface>
      </div>
    </WorkspacePage>
  )
}
