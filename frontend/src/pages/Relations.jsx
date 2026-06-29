import { useState, useEffect, useMemo, useRef } from 'react'
import * as d3 from 'd3'
import { Brain, GitBranch, Move, Network, UserRound } from 'lucide-react'
import { fetchState, fetchMemory } from '../api'
import { EmptyState, cx } from '../components/UI'
import { SectionTitle, StateTag, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'
import { useWorld } from '../App'

const TYPE_COLORS = {
  '主角': '#ad4b3a', '官方势力': '#627f98', '商业势力': '#6e8b77', '民间势力': '#8a7395', '修仙宗门': '#a46d7d', '黑暗势力': '#b24c43', '敌人': '#b24c43', '盟友': '#6e8b77', '中立': '#8b8174',
}

function getNodeColor(node) {
  if (node.type === 'protagonist') return TYPE_COLORS['主角']
  if (node.factionType && TYPE_COLORS[node.factionType]) return TYPE_COLORS[node.factionType]
  if (node.relationType === '敌人' || node.relationType === '敌对') return TYPE_COLORS['敌人']
  if (node.relationType === '盟友' || node.relationType === '朋友') return TYPE_COLORS['盟友']
  return '#8b8174'
}

function getNodeRadius(node) {
  if (node.type === 'protagonist') return 22
  if (node.importance === 'major') return 18
  return 14
}

function mergeRelations(relationsData, memoryData, charactersData) {
  const nodes = {}
  const links = []

  if (charactersData?.characters) {
    for (const c of charactersData.characters) {
      nodes[c.id || c.name] = {
        id: c.id || c.name,
        name: c.name,
        type: c.player_controlled ? 'protagonist' : 'character',
        realm: c.realm || '未知',
        role: c.role || '',
        lastAction: c._last_action || '',
        lastDialogue: c._last_dialogue || '',
        lastVisibility: c._last_visibility || '',
      }
    }
  }

  const protagonist = charactersData?.characters?.find(c => c.player_controlled)
  const protagonistName = protagonist?.name || '主角'

  const addLink = (source, target, relType, desc) => {
    if (!source || !target || source === target) return
    const key = `${source}|${target}|${relType}`
    if (links.some(l => l.key === key)) return
    links.push({ key, source, target, type: relType, description: desc || '' })
  }

  if (relationsData?.relations) {
    for (const r of relationsData.relations) {
      addLink(r.source, r.target, r.type || r.relation, r.description || r.relation)
    }
  }

  if (charactersData?.characters) {
    for (const c of charactersData.characters) {
      if (c.relationships) {
        for (const r of c.relationships) {
          addLink(c.name, r.target || r.name, r.type, r.description || r.note)
        }
      }
    }
  }

  if (memoryData?.characters) {
    for (const [charId, info] of Object.entries(memoryData.characters)) {
      const charName = info.name || charId
      if (info.relationships) {
        for (const [targetName, relInfo] of Object.entries(info.relationships)) {
          let desc = relInfo.last_update || ''
          if (desc.length > 40) desc = desc.slice(0, 40) + '…'
          addLink(charName, targetName, '关联', desc)
        }
      }
    }
  }

  for (const l of links) {
    if (!nodes[l.source]) nodes[l.source] = { id: l.source, name: l.source, type: 'character' }
    if (!nodes[l.target]) nodes[l.target] = { id: l.target, name: l.target, type: 'character' }
  }

  return { nodes: Object.values(nodes), links, memoryData, charactersData }
}

function nodeName(value) {
  return value?.name || value?.id || value || ''
}

function resolveProfile(selectedId, graphData) {
  if (!graphData) return null
  const node = graphData.nodes.find(item => item.id === selectedId || item.name === selectedId) || graphData.nodes.find(item => item.type === 'protagonist') || graphData.nodes[0]
  if (!node) return null
  const memories = graphData.memoryData?.characters || {}
  const memory = memories[node.id] || Object.values(memories).find(item => item?.name === node.name) || {}
  const related = graphData.links.filter(link => nodeName(link.source) === node.id || nodeName(link.source) === node.name || nodeName(link.target) === node.id || nodeName(link.target) === node.name)
  const entries = memory.entries || []
  return { node, memory, related, entries }
}

export default function Relations() {
  const svgRef = useRef(null)
  const containerRef = useRef(null)
  const tooltipRef = useRef(null)
  const { currentWorld } = useWorld()
  const [graphData, setGraphData] = useState(null)
  const [selectedCharId, setSelectedCharId] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!currentWorld) {
      setGraphData(null)
      setSelectedCharId('')
      setLoading(false)
      return
    }
    setLoading(true)
    Promise.all([
      fetchState('relationships.json').catch(() => ({})),
      fetchMemory('all', '').catch(() => ({})),
      fetchState('characters.json').catch(() => ({})),
    ]).then(([rels, mem, chars]) => {
      const next = mergeRelations(rels, mem, chars)
      setGraphData(next)
      setSelectedCharId(next.nodes.find(node => node.type === 'protagonist')?.id || next.nodes[0]?.id || '')
      setLoading(false)
    })
  }, [currentWorld])

  const selectedProfile = useMemo(() => resolveProfile(selectedCharId, graphData), [selectedCharId, graphData])

  useEffect(() => {
    if (!graphData || !svgRef.current) return
    const { nodes, links } = graphData
    if (nodes.length === 0) return

    let destroyed = false
    let simulation = null

    const initGraph = () => {
      if (destroyed || !svgRef.current) return
      const container = containerRef.current || svgRef.current.parentElement
      const width = Math.max(container?.clientWidth || 0, 600)
      const height = 550

      const svg = d3.select(svgRef.current)
      svg.selectAll('*').remove()
      svg.attr('viewBox', `0 0 ${width} ${height}`)

      const g = svg.append('g')

      const zoom = d3.zoom().scaleExtent([0.3, 3]).on('zoom', (e) => {
        g.attr('transform', e.transform)
      })
      svg.call(zoom)

      simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-350))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide(30))

      const linkGroup = g.append('g').selectAll('g')
        .data(links)
        .join('g')

      linkGroup.append('line')
        .attr('stroke', d => {
          if (d.type === '敌人' || d.type === '敌对') return 'rgba(178,76,67,0.58)'
          if (d.type === '朋友' || d.type === '盟友') return 'rgba(110,139,119,0.62)'
          return 'rgba(117,110,100,0.46)'
        })
        .attr('stroke-width', 1.5)
        .attr('stroke-dasharray', d => d.type === '关联' ? '4,3' : null)

      linkGroup.append('text')
        .text(d => d.type || '')
        .attr('font-size', 9)
        .attr('fill', '#766e64')
        .attr('text-anchor', 'middle')
        .attr('dy', -5)

      const nodeGroup = g.append('g').selectAll('g')
        .data(nodes)
        .join('g')
        .attr('cursor', 'pointer')
        .call(d3.drag()
          .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
          .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
          .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null })
        )

      nodeGroup.append('circle')
        .attr('r', d => getNodeRadius(d))
        .attr('fill', d => getNodeColor(d))
        .attr('stroke', '#2f2b25')
        .attr('stroke-width', 1.5)
        .style('filter', d => d.type === 'protagonist' ? 'drop-shadow(0 0 6px rgba(173,75,58,0.28))' : null)

      nodeGroup.append('text')
        .text(d => d.name)
        .attr('text-anchor', 'middle')
        .attr('dy', d => getNodeRadius(d) + 14)
        .attr('fill', '#2f2b25')
        .attr('font-size', d => d.type === 'protagonist' ? 13 : 11)
        .attr('font-weight', d => d.type === 'protagonist' ? 'bold' : 'normal')

      const tooltip = d3.select(tooltipRef.current)
      nodeGroup.on('mouseenter', (e, d) => {
        const connectedLinks = links.filter(l => {
          const srcId = l.source?.id || l.source
          const tgtId = l.target?.id || l.target
          return srcId === d.id || tgtId === d.id
        })
        tooltip.style('display', 'block')
          .html(`
            <div class="font-bold text-sm">${d.name}</div>
            <div class="text-xs text-slate-400 mt-1">${d.realm || ''} ${d.role || ''}</div>
            <div class="text-xs text-slate-500 mt-1">关联 ${connectedLinks.length} 个角色</div>
          `)
        d3.select(e.currentTarget).select('circle')
          .transition().duration(150).attr('r', getNodeRadius(d) + 4)
      })
      nodeGroup.on('click', (e, d) => {
        setSelectedCharId(d.id)
      })
      nodeGroup.on('mousemove', (e) => {
        const rect = svgRef.current.getBoundingClientRect()
        tooltip.style('left', (e.clientX - rect.left + 12) + 'px')
          .style('top', (e.clientY - rect.top - 10) + 'px')
      })
      nodeGroup.on('mouseleave', (e, d) => {
        tooltip.style('display', 'none')
        d3.select(e.currentTarget).select('circle')
          .transition().duration(150).attr('r', getNodeRadius(d))
      })

      simulation.on('tick', () => {
        linkGroup.select('line')
          .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
        linkGroup.select('text')
          .attr('x', d => (d.source.x + d.target.x) / 2)
          .attr('y', d => (d.source.y + d.target.y) / 2)
        nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`)
      })
    }

    requestAnimationFrame(() => {
      requestAnimationFrame(initGraph)
    })

    return () => {
      destroyed = true
      if (simulation) simulation.stop()
    }
  }, [graphData])

  return (
    <WorkspacePage className="max-w-6xl">
      <WorkspaceHeader trail="角色与势力" title="关系图谱" description="拖拽节点、缩放视图，查看角色之间如何彼此牵动。" />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <Surface className="relative overflow-hidden">
          <SectionTitle icon={Network} action={<StateTag tone="quiet"><Move aria-hidden="true" className="mr-1 h-3 w-3" />可拖拽 / 可缩放</StateTag>}>关系网络</SectionTitle>
          {loading ? (
            <div className="flex h-96 items-center justify-center text-[#827a6b]">加载中...</div>
          ) : graphData?.nodes?.length === 0 ? (
            <EmptyState icon={GitBranch} title="关系尚未形成" description="开始推演后，角色之间的互动会在这里凝成网络。" />
          ) : (
            <div ref={containerRef} className="w-full">
              <svg ref={svgRef} width="100%" height="550" className="block w-full bg-[#fffdf8]" />
              <div ref={tooltipRef} className="pointer-events-none absolute hidden rounded-none border border-[#d6ccba] bg-[#fffdf8] px-3 py-2 shadow-xl" style={{ maxWidth: 200 }} />
            </div>
          )}
        </Surface>

        <Surface className="overflow-hidden">
          <SectionTitle icon={UserRound} action={<StateTag tone="quiet">{selectedProfile?.memory?.total || 0} 条记忆</StateTag>}>角色档案</SectionTitle>
          {selectedProfile ? (
            <div className="max-h-[36rem] overflow-y-auto p-5">
              <div className="border-l border-[#ad4b3a]/45 pl-4">
                <p className="font-serif text-2xl font-semibold text-[#2f2b25]">{selectedProfile.node.name}</p>
                <p className="mt-2 text-sm leading-6 text-[#766e64]">{selectedProfile.node.role || '身份未明'} · {selectedProfile.node.realm || '境界未知'}</p>
              </div>
              {(selectedProfile.node.lastAction || selectedProfile.node.lastDialogue) && (
                <div className="mt-5 rounded-none border border-[#d6ccba] bg-[#faf7f0] p-4">
                  <div className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-[.12em] text-[#a94334]">
                    <Brain aria-hidden="true" className="h-3.5 w-3.5" />
                    最近行动{selectedProfile.node.lastVisibility ? ` · ${selectedProfile.node.lastVisibility}` : ''}
                  </div>
                  {selectedProfile.node.lastAction && <p className="text-sm leading-6 text-[#3d3831]">{selectedProfile.node.lastAction}</p>}
                  {selectedProfile.node.lastDialogue && <p className="mt-2 text-sm leading-6 text-[#625a50]">「{selectedProfile.node.lastDialogue}」</p>}
                </div>
              )}
              <div className="mt-5">
                <p className="mb-3 text-xs font-semibold tracking-[.12em] text-[#a94334]">关系</p>
                <div className="space-y-2">
                  {selectedProfile.related.slice(0, 8).map((rel, index) => (
                    <button key={rel.key || `rel-${index}`} type="button" onClick={() => setSelectedCharId(nodeName(rel.source) === selectedProfile.node.name || nodeName(rel.source) === selectedProfile.node.id ? nodeName(rel.target) : nodeName(rel.source))} className="block w-full border border-[#d6ccba]/70 bg-[#fffdf8] px-3 py-2 text-left text-xs leading-5 text-[#625a50] hover:border-[#ad4b3a]/35 hover:bg-[#f8f2e8]">
                      <span className="font-medium text-[#2f2b25]">{nodeName(rel.source)} → {nodeName(rel.target)}</span>
                      <span className="ml-2 text-[#a94334]">{rel.type}</span>
                      {rel.description && <span className="mt-1 block text-[#766e64]">{rel.description}</span>}
                    </button>
                  ))}
                  {!selectedProfile.related.length && <p className="text-sm text-[#9c9388]">暂无明确关系。</p>}
                </div>
              </div>
              <div className="mt-5">
                <p className="mb-3 text-xs font-semibold tracking-[.12em] text-[#a94334]">记忆探查</p>
                <ol className="space-y-3">
                  {selectedProfile.entries.slice(0, 8).map((entry, index) => (
                    <li key={`profile-memory-${entry.round || 'unknown'}-${index}`} className="border-l border-[#d6ccba] pl-3">
                      <p className="text-[11px] text-[#9c9388]">第 {entry.round || '？'} 轮</p>
                      <p className="mt-1 text-sm leading-6 text-[#3d3831]">{entry.content || entry.summary || JSON.stringify(entry)}</p>
                    </li>
                  ))}
                  {!selectedProfile.entries.length && <p className="text-sm text-[#9c9388]">还没有可探查记忆。</p>}
                </ol>
              </div>
            </div>
          ) : (
            <EmptyState icon={UserRound} title="尚未选择角色" description="点击关系图节点查看角色记忆。" />
          )}
        </Surface>
      </div>

      <Surface className="p-5">
        <h2 className="atelier-heading text-xl font-semibold text-[#eee7d8]">图例</h2>
        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-3">
          {Object.entries(TYPE_COLORS).map(([key, color]) => (
            <div key={key} className="flex items-center gap-2 text-xs text-[#a99f8c]">
              <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: color }} />
              {key}
            </div>
          ))}
          <div className="flex items-center gap-2 text-xs text-[#a99f8c]">
            <span className="inline-block h-3 w-3 rounded-full bg-[#8b8174]" />
            连线：<span className="text-[#b24c43]">朱砂=敌对</span> · <span className="text-[#6e8b77]">青绿=盟友</span> · <span>灰=中立</span>
          </div>
        </div>
      </Surface>

      {graphData?.links?.length > 0 && (
        <Surface className="overflow-hidden">
          <SectionTitle icon={GitBranch}>关系索引</SectionTitle>
          <div className="grid gap-px bg-[#d6ccba]/10 sm:grid-cols-2">
            {graphData.links.map((r, i) => (
              <button key={r.key || `${r.source?.name || r.source}-${r.target?.name || r.target}-${r.type}-${i}`} type="button" onClick={() => setSelectedCharId(nodeName(r.target))} className="bg-[#fffdf8] p-4 text-left text-sm transition-colors hover:bg-[#f8f2e8]">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-[#e3dbcb]">{nodeName(r.source)} → {nodeName(r.target)}</span>
                  <span className="shrink-0 rounded-sm bg-[#fbf7ee]/[.05] px-1.5 py-0.5 text-xs text-[#a99f8c]">{r.type}</span>
                </div>
                {r.description && <p className="mt-2 text-xs leading-5 text-[#827a6b]">{r.description}</p>}
              </button>
            ))}
          </div>
        </Surface>
      )}
    </WorkspacePage>
  )
}
