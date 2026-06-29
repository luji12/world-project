import { useEffect, useState } from 'react'
import { CalendarDays, Gauge, PauseCircle, SlidersHorizontal } from 'lucide-react'
import { TextInput } from '../components/UI'
import { KeyValue, Segmented, StateTag, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'
import { loadAutoConfig, saveAutoConfig } from '../autoConfig'
import { fetchWorldRealms } from '../api'
import { useWorld } from '../App'

const INTERVENTIONS = [
  { key: 'on_realm_breakthrough', label: '境界突破', desc: '主角进入新的修为层级' },
  { key: 'on_world_event', label: '世界事件', desc: '重要世界事件被激活' },
  { key: 'on_quest_complete', label: '任务变化', desc: '关键任务完成或失败' },
  { key: 'on_relationship_change', label: '关系转折', desc: '重要角色关系发生变化' },
]

export default function AutoConfig() {
  const { currentWorld } = useWorld()
  const initial = loadAutoConfig()
  const [stopConditions, setStopConditions] = useState(initial.stopConditions)
  const [interventionNodes, setInterventionNodes] = useState(initial.interventionNodes)
  const [realms, setRealms] = useState([])
  const [realmSystemName, setRealmSystemName] = useState('')

  useEffect(() => {
    if (!currentWorld) {
      setRealms([])
      setRealmSystemName('')
      return
    }
    fetchWorldRealms().then(data => {
      const realmList = data.realms || []
      setRealms(realmList.length ? ['不限', ...realmList] : [])
      setRealmSystemName(data.system_name || '修为')
    })
  }, [currentWorld])

  useEffect(() => { saveAutoConfig({ stopConditions, interventionNodes }) }, [stopConditions, interventionNodes])
  const selectedNodes = INTERVENTIONS.filter(item => interventionNodes[item.key])

  return (
    <WorkspacePage className="max-w-5xl">
      <WorkspaceHeader trail="推演规则" title="自动推演配置" description="定义自动推进的边界，以及故事应把控制权交还给你的时刻。" />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="space-y-5">
          <Surface className="p-5 md:p-6">
            <div className="flex items-center gap-2"><Gauge aria-hidden="true" className="h-4.5 w-4.5 text-[#d3ad65]" /><h2 className="atelier-heading text-xl font-semibold text-[#eee7d8]">停止条件</h2></div>
            <p className="mt-2 text-sm text-[#a99f8c]">命中任一条件时，自动推演会安全地停在当前叙事节点。</p>
            <div className="mt-6 grid gap-5 sm:grid-cols-2">
              <label><span className="atelier-field-label">最大轮数</span><TextInput type="number" value={stopConditions.max_rounds} onChange={event => setStopConditions(previous => ({ ...previous, max_rounds: Number(event.target.value) || 0 }))} min="1" max="1000" className="w-full" /></label>
              <label><span className="atelier-field-label">目标世界日期</span><TextInput value={stopConditions.target_date} onChange={event => setStopConditions(previous => ({ ...previous, target_date: event.target.value }))} placeholder="例如 1428年1月" className="w-full" /></label>
            </div>
            <div className="mt-5">
              <span className="atelier-field-label">目标{realmSystemName || '修为'}</span>
              {realms.length > 1 ? (
                <Segmented ariaLabel={`目标${realmSystemName || '修为'}`} value={stopConditions.target_realm || '不限'} onChange={value => setStopConditions(previous => ({ ...previous, target_realm: value === '不限' ? '' : value }))} items={realms.map(value => ({ value, label: value }))} />
              ) : (
                <p className="mt-2 text-xs text-[#827a6b]">当前世界未定义明确的等级体系，此条件不可用。可在世界框架中设定修炼/力量等级后使用。</p>
              )}
            </div>
          </Surface>

          <Surface className="overflow-hidden">
            <div className="flex items-center gap-2 border-b border-[#d6ccba]/12 px-5 py-4"><PauseCircle aria-hidden="true" className="h-4.5 w-4.5 text-[#d3ad65]" /><h2 className="atelier-heading text-xl font-semibold text-[#eee7d8]">交还控制权</h2></div>
            <div className="divide-y divide-[#d6ccba]/10">
              {INTERVENTIONS.map(item => (
                <label key={item.key} className="flex cursor-pointer items-center gap-4 px-5 py-4 transition-colors hover:bg-[#fbf7ee]/[.035]">
                  <input type="checkbox" checked={Boolean(interventionNodes[item.key])} onChange={() => setInterventionNodes(previous => ({ ...previous, [item.key]: !previous[item.key] }))} className="h-4 w-4 shrink-0 rounded border-[#d6ccba]/40 bg-[#10110d]" />
                  <span className="min-w-0 flex-1"><span className="block text-sm font-medium text-[#e6ddcd]">{item.label}</span><span className="mt-1 block text-xs text-[#827a6b]">{item.desc}</span></span>
                  <StateTag tone={interventionNodes[item.key] ? 'brass' : 'quiet'}>{interventionNodes[item.key] ? '已启用' : '跳过'}</StateTag>
                </label>
              ))}
            </div>
          </Surface>
        </div>

        <Surface className="h-fit p-5">
          <div className="flex items-center gap-2 text-[#d3ad65]"><SlidersHorizontal aria-hidden="true" className="h-4 w-4" /><span className="text-xs font-semibold tracking-[.14em]">本次规则</span></div>
          <div className="mt-5 space-y-5"><KeyValue label="最大轮数" value={`${stopConditions.max_rounds || '—'} 轮`} /><KeyValue label={`目标${realmSystemName || '修为'}`} value={stopConditions.target_realm || '不限定'} /><KeyValue label="交还节点" value={selectedNodes.length ? selectedNodes.map(item => item.label).join('、') : '无'} /></div>
          <div className="mt-6 flex items-center gap-2 border-t border-[#d6ccba]/12 pt-4 text-xs text-[#827a6b]"><CalendarDays aria-hidden="true" className="h-3.5 w-3.5" />保存后立即应用于下一次自动推演</div>
        </Surface>
      </div>
    </WorkspacePage>
  )
}
