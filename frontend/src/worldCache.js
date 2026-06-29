export const PLAY_CHAT_CACHE_VERSION = 'world_play_chat_v6'
export const DASHBOARD_CACHE_VERSION = 'world_dashboard_cache_v2'

export function playChatCacheKey(worldName) {
  return `${PLAY_CHAT_CACHE_VERSION}:${worldName}`
}

export function dashboardCacheKey(worldName) {
  return `${DASHBOARD_CACHE_VERSION}:${worldName}`
}

export function clearWorldUiCache(worldName) {
  if (!worldName) return
  try {
    localStorage.removeItem(playChatCacheKey(worldName))
    localStorage.removeItem(dashboardCacheKey(worldName))
  } catch {}
}
