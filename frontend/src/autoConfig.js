export const AUTO_CONFIG_KEY = 'world-project-auto-config'
export const LEGACY_AUTO_CONFIG_KEY = 'xuanhuang-auto-config'

export const DEFAULT_AUTO_CONFIG = {
  stopConditions: {
    max_rounds: 50,
    target_realm: '',
    target_date: '',
  },
  interventionNodes: {
    on_realm_breakthrough: true,
    on_world_event: true,
    on_quest_complete: false,
    on_relationship_change: false,
  },
}

export function loadAutoConfig() {
  try {
    const saved = JSON.parse(localStorage.getItem(AUTO_CONFIG_KEY) || localStorage.getItem(LEGACY_AUTO_CONFIG_KEY) || '{}')
    return {
      stopConditions: { ...DEFAULT_AUTO_CONFIG.stopConditions, ...(saved.stopConditions || {}) },
      interventionNodes: { ...DEFAULT_AUTO_CONFIG.interventionNodes, ...(saved.interventionNodes || {}) },
    }
  } catch {
    return DEFAULT_AUTO_CONFIG
  }
}

export function saveAutoConfig(config) {
  localStorage.setItem(AUTO_CONFIG_KEY, JSON.stringify(config))
}
