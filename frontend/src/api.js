export const BASE = import.meta.env.VITE_API_BASE || 'http://localhost:3101'
export const SETTINGS_KEY = 'world-project-settings'
export const LEGACY_SETTINGS_KEY = 'xuanhuang-settings'

export function fetchStatus() {
  return apiJson('/api/status', { headers: getHeaders() }, '获取状态失败')
}

export function getHeaders() {
  const headers = { 'Content-Type': 'application/json' }
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || localStorage.getItem(LEGACY_SETTINGS_KEY) || '{}')
    if (saved.apiKey) headers['X-API-Key'] = saved.apiKey
    if (saved.baseUrl) headers['X-Base-URL'] = saved.baseUrl
    if (saved.model) headers['X-Model'] = saved.model
  } catch {}
  return headers
}

async function parseError(res, fallback) {
  try {
    const data = await res.json()
    return data.error || fallback
  } catch {
    return fallback
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 120000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, { ...options, signal: controller.signal })
    return res
  } finally {
    clearTimeout(timer)
  }
}

export async function apiJson(path, options = {}, fallback = '请求失败') {
  const res = await fetchWithTimeout(`${BASE}${path}`, options)
  if (!res.ok) {
    const error = new Error(await parseError(res, fallback))
    error.status = res.status
    error.path = path
    throw error
  }
  return res.json()
}

export async function postJson(path, body = {}, options = {}, fallback = '请求失败') {
  return apiJson(path, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(body),
    ...options,
  }, fallback)
}

export async function fetchState(filename) {
  return apiJson(`/api/state/${filename}`, {}, `获取失败: ${filename}`)
}

export async function fetchCharacters() {
  return apiJson('/api/characters', {}, '获取角色失败')
}

export async function fetchChronicle(volume = 'volume-01') {
  return apiJson(`/api/chronicle/${volume}`, {}, '获取正文失败')
}

export async function fetchTimeline() {
  return apiJson('/api/timeline', {}, '获取时间线失败')
}

export async function fetchMemory(type = 'recent', charId = '') {
  const params = new URLSearchParams({ type })
  if (charId) params.set('char', charId)
  return apiJson(`/api/memory?${params}`, {}, '获取记忆失败')
}

export async function fetchRoundsLog() {
  return apiJson('/api/rounds-log', {}, '获取轮次日志失败')
}

export function fetchStoryContext(playerId = '', chapterNo = 0) {
  const params = new URLSearchParams()
  if (playerId) params.set('player', playerId)
  if (chapterNo) params.set('chapter', String(chapterNo))
  const suffix = params.size ? `?${params}` : ''
  return apiJson(`/api/story/context${suffix}`, {}, '获取叙事上下文失败')
}

export function fetchChapterRevisions(status = '') {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiJson(`/api/chapters${suffix}`, {}, '获取章节失败')
}

export function approveChapter(chapterNo, revisionNo) {
  return postJson('/api/chapters/approve', { chapter_no: chapterNo, revision_no: revisionNo }, {}, '批准章节失败')
}

export function saveChapterEdit(chapterNo, revisionNo, content, title) {
  return postJson('/api/chapters/edit', { chapter_no: chapterNo, revision_no: revisionNo, content, title }, {}, '保存章节编辑失败')
}

export function polishChapter(text) {
  return postJson('/api/polish', { text, mode: 'chapter' }, {}, '章节润色失败')
}

export function compileBook(title) {
  return postJson('/api/book/compile', { title }, {}, '编译小说失败')
}

export function bookExportUrl(format = 'html') {
  return `${BASE}/api/book/export?format=${encodeURIComponent(format)}`
}

export async function startRound(onEvent) {
  const res = await fetch(`${BASE}/api/round/start`, {
    method: 'POST',
    headers: getHeaders(),
  })
  if (!res.ok) throw new Error(await parseError(res, '启动轮次失败'))
  return streamSSE(res, onEvent)
}

export async function startAuto(stopConditions, interventionNodes, interactiveMode, onEvent) {
  const res = await fetch(`${BASE}/api/auto/start`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify({
      stop_conditions: stopConditions,
      intervention_nodes: interventionNodes,
      interactive_mode: interactiveMode,
    }),
  })
  if (!res.ok) throw new Error(await parseError(res, '启动自动推演失败'))
  return streamSSE(res, onEvent)
}

export async function pauseAuto() {
  return apiJson('/api/auto/pause', { method: 'POST', headers: getHeaders() }, '暂停失败')
}

export async function resumeAuto() {
  return apiJson('/api/auto/resume', { method: 'POST', headers: getHeaders() }, '继续失败')
}

export function polishAction(text, context = '') {
  return postJson('/api/polish', { text, context }, {}, '润色失败')
}

export function reviewChapter(chapterNo, revisionNo) {
  return postJson('/api/chapters/review', { chapter_no: chapterNo, revision_no: revisionNo }, {}, '章节审核失败')
}

export function fetchForeshadows() {
  return apiJson('/api/foreshadows', {}, '获取伏笔失败')
}

export function saveCheckpoint(label, chapterNo = 0, reason = '') {
  return postJson('/api/checkpoint/save', { label, chapter_no: chapterNo, reason }, {}, '存档失败')
}

export function listCheckpoints() {
  return apiJson('/api/checkpoint/list', {}, '获取存档列表失败')
}

export function fetchChatHistory() {
  return apiJson('/api/chat/history', {}, '获取聊天记录失败')
}

export function clearChatHistory() {
  return postJson('/api/chat/history/clear', {}, {}, '清空聊天记录失败')
}

export async function startInteractive(protagonistAction, onEvent) {
  const res = await fetch(`${BASE}/api/interact/start`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify({ protagonist_action: protagonistAction }),
  })
  if (!res.ok) throw new Error(await parseError(res, '交互请求失败'))
  return streamSSE(res, onEvent)
}

export function fetchWorlds() {
  return apiJson('/api/worlds', {}, '获取世界列表失败')
}

export function fetchCurrentWorld() {
  return apiJson('/api/worlds/current', {}, '获取当前世界失败')
}

export function fetchWorldRealms() {
  return apiJson('/api/world-realms', {}, '获取境界体系失败').catch(() => ({ realms: [], system_name: '' }))
}

export function fetchCanonStatus() {
  return apiJson('/api/canon/status', {}, '获取 Canon 状态失败')
}

export function fetchCanonSource() {
  return apiJson('/api/canon/source', {}, '获取 Canon 原文失败')
}

export function fetchCanonBible() {
  return apiJson('/api/canon/bible', {}, '获取世界圣经失败')
}

export function fetchCanonConflicts() {
  return apiJson('/api/canon/conflicts', {}, '获取 Canon 冲突失败')
}

export function recompileCanon(source = '') {
  return postJson('/api/canon/recompile', source ? { source } : {}, {}, '重新编译 Canon 失败')
}

export function resetCanonWorld(source = '') {
  return postJson('/api/canon/reset-world', source ? { source } : {}, {}, '按 Canon 重开世界失败')
}

export function resolveCanonConflict(id, status = 'resolved', note = '') {
  return postJson('/api/canon/conflicts/resolve', { id, status, note }, {}, '标记冲突失败')
}

export function switchWorld(name) {
  return postJson('/api/worlds/switch', { name }, {}, '切换世界失败')
}

export function createWorld(name, summary, type = '自定义') {
  return postJson('/api/worlds/create', { name, summary, type }, {}, '创建世界失败')
}

export function createWorldV2(name, worldPackage, selectedCharacter) {
  return postJson('/api/worlds/create-v2', {
    name,
    world_package: worldPackage,
    selected_character: selectedCharacter,
  }, {}, '创建世界失败')
}

export function generateWorldDetails(worldPackage, selectedCharacter) {
  return postJson('/api/worlds/generate-details', {
    world_package: worldPackage,
    selected_character: selectedCharacter,
  }, {}, '生成角色详情失败')
}

export function chatWorld(messages) {
  return postJson('/api/worlds/chat', { messages }, {}, '世界助手请求失败')
}

export function restartWorld(name) {
  return postJson('/api/worlds/restart', name ? { name } : {}, {}, '重启世界失败')
}

export function deleteWorld(name) {
  return postJson('/api/worlds/delete', { name }, {}, '删除世界失败')
}

export function generateNPCs() {
  return postJson('/api/npc/generate', {}, {}, '自动创建角色失败')
}

export function injectWorld(text) {
  return postJson('/api/inject', { text }, {}, '注入失败')
}

export function saveFramework(name, content) {
  return postJson('/api/worlds/framework', { name, content, mode: 'save' }, {}, '保存框架失败')
}

export async function uploadDocument(file) {
  const formData = new FormData()
  formData.append('file', file)

  const headers = {}
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || localStorage.getItem(LEGACY_SETTINGS_KEY) || '{}')
    if (saved.apiKey) headers['X-API-Key'] = saved.apiKey
    if (saved.baseUrl) headers['X-Base-URL'] = saved.baseUrl
    if (saved.model) headers['X-Model'] = saved.model
  } catch {}

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 180000)

  try {
    const res = await fetch(`${BASE}/api/worlds/upload-doc`, {
      method: 'POST',
      headers,
      body: formData,
      signal: controller.signal,
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.error || '文档解析失败')
    }

    return res.json()
  } finally {
    clearTimeout(timer)
  }
}

async function streamSSE(res, onEvent) {
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventType = 'message'

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          onEvent({ event: eventType, data })
        } catch {}
        eventType = 'message'
      }
    }
  }
}
