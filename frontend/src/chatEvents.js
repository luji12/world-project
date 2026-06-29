const AGENT_NAMES = {
  'world-engine': '世界引擎',
  'system-agent': '命运系统',
  protagonist: '主角',
  'npc-agents': '群像角色',
  chronicler: '记录员',
}

export function eventLabel(event) {
  return AGENT_NAMES[event] || event || '系统'
}

function eventPayload(input) {
  if (!input) return { event: '', data: {} }
  if (input.event) return { event: input.event, data: input.data || {} }
  return { event: input.type || '', data: input.data || {}, projected: input }
}

const PRIVATE_VISIBILITIES = new Set(['private', 'secret', 'internal', 'background', 'offscreen'])
const VISIBLE_VISIBILITIES = new Set(['direct', 'overheard', 'public_observed', 'public'])
const PRIVATE_TEXT_HINTS = ['暗中', '心中', '心想', '默想', '隐于', '云端', '窥视', '推算', '密谋', '秘密', '背地', '无人知', '未被察觉', '远处', '内心', '独自', '自言自语']
const DIRECT_TEXT_HINTS = ['你', '您', '叶然', '叶公子', '叶大哥', '病秧子', '道友', '公子', '少侠']

function hasPrivateHint(text = '') {
  return PRIVATE_TEXT_HINTS.some(hint => String(text).includes(hint))
}

function shouldShowNpcEvent(data, text = '') {
  if (data.exposed_to_player === false || data.observed_by_player === false) return false
  const visibility = String(data.visibility || '').toLowerCase()
  if (PRIVATE_VISIBILITIES.has(visibility)) return false
  if (VISIBLE_VISIBILITIES.has(visibility)) return true

  const dialogue = String(data.dialogue || '')
  const action = String(data.action_desc || '')
  const combined = `${dialogue}\n${action}\n${text || ''}`
  if (hasPrivateHint(combined)) return false
  if (!dialogue) return false
  return DIRECT_TEXT_HINTS.some(hint => dialogue.includes(hint))
}

export function eventToMessage(input, playerName = '你') {
  const { event, data, projected = {} } = eventPayload(input)
  const round = projected.round ?? data.round
  const text = projected.text

  if (event === 'system-message' && (data.dialogue || text)) {
    return { type: 'system_chat', text: data.dialogue || text, round, bubble_type: data.bubble_type || 'system' }
  }
  if (event === 'narration' && (data.text || text)) {
    return { type: 'world', text: data.text || text, round, bubble_type: data.bubble_type || 'narration' }
  }
  if (event === 'npc-message' && (data.dialogue || data.action_desc || text)) {
    if (!shouldShowNpcEvent(data, text)) return null
    const name = data.npc_name || projected.actor || '路人'
    return { type: 'npc_chat', name, text: data.dialogue || data.action_desc || text, round, bubble_type: data.bubble_type || 'dialog' }
  }
  if (event === 'player-action-recorded' && (data.action || text)) {
    return { type: 'player_action', name: playerName, text: data.action || text, round, bubble_type: data.bubble_type || 'player' }
  }
  if (event === 'agent-output' && data.agent === 'chronicler' && (data.summary || text)) {
    return { type: 'chapter_card', text: data.summary || text, round, bubble_type: data.bubble_type || 'chapter' }
  }
  if (event === 'agent-error') {
    return { type: 'error_msg', text: `⚠️ ${eventLabel(data.agent)} 出错：${data.error || text || '未知错误'}` }
  }
  if (event === 'story-end') {
    return { type: 'system_chat', text: data.message || text || '故事已结束。', bubble_type: 'system' }
  }
  return null
}

export function eventToDashboardEntry(input) {
  const { event, data, projected = {} } = eventPayload(input)
  const round = projected.round ?? data.round
  const text = projected.text

  if (event === 'round-start') return { type: 'round', text: `第 ${data.round} 轮开始` }
  if (event === 'narration') return { type: 'narration', text: data.text || text, round }
  if (event === 'protagonist-auto') return { type: 'action', actor: '主角', text: data.action || text, round }
  if (event === 'npc-message') {
    if (!shouldShowNpcEvent(data, text)) return null
    return { type: 'npc', actor: data.npc_name || projected.actor || '角色', text: data.dialogue || data.action_desc || text, round }
  }
  if (event === 'system-message') return { type: 'system', text: data.dialogue || text, round }
  if (event === 'agent-output' && data.agent === 'chronicler' && (data.summary || text)) return { type: 'chronicle', text: data.summary || text, round }
  if (event === 'player-action-recorded') return { type: 'action', actor: '你', text: data.action || text, round }
  return null
}
