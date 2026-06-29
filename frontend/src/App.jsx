import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { BrowserRouter, Routes, Route, useLocation, useNavigate, Navigate } from 'react-router-dom'
import { BookOpen, ChevronRight, Menu, Settings2 } from 'lucide-react'
import { SettingsProvider } from './SettingsContext'
import Sidebar from './components/Sidebar'
import { Button } from './components/UI'
import Dashboard from './pages/Dashboard'
import Reader from './pages/Reader'
import Manager from './pages/Manager'
import Relations from './pages/Relations'
import Memory from './pages/Memory'
import AutoConfig from './pages/AutoConfig'
import Settings from './pages/Settings'
import WorldPanel from './pages/WorldPanel'
import Play from './pages/Play'
import { fetchStatus } from './api'

// ── Global world context ───────────────────────────────────────────
export const WorldContext = createContext({ hasWorld: false, currentWorld: '', refresh: () => {} })
export function useWorld() { return useContext(WorldContext) }

export default function App() {
  return (
    <SettingsProvider>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </SettingsProvider>
  )
}

function AppShell() {
  const [mode, setMode] = useState('auto')
  const [running, setRunning] = useState(false)
  const [paused, setPaused] = useState(false)
  const [logs, setLogs] = useState([])
  const [progress, setProgress] = useState(0)
  const [navOpen, setNavOpen] = useState(false)
  const [hasWorld, setHasWorld] = useState(null) // null = loading
  const [currentWorld, setCurrentWorld] = useState('')
  const location = useLocation()
  const navigate = useNavigate()
  const isReader = location.pathname.startsWith('/reader')
  const isPlay = location.pathname.startsWith('/play')
  const isDashboard = location.pathname === '/'
  const hasCurrentWorld = Boolean(currentWorld)

  useEffect(() => { setNavOpen(false) }, [location.pathname])

  useEffect(() => {
    const openNavigation = () => setNavOpen(true)
    window.addEventListener('world-nav:open', openNavigation)
    return () => window.removeEventListener('world-nav:open', openNavigation)
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      const s = await fetchStatus()
      setHasWorld(s.has_world)
      setCurrentWorld(s.current_world || '')
      // World data pages require an explicitly selected current world.
      if (!s.current_world && location.pathname !== '/worlds' && location.pathname !== '/settings') {
        navigate('/worlds', { replace: true })
      }
    } catch {
      // Backend not ready — don't redirect, just mark as unknown
      setHasWorld(false)
      setCurrentWorld('')
    }
  }, [location.pathname, navigate])

  useEffect(() => {
    refreshStatus()
  }, []) // only on mount; WorldPanel calls refresh after creation

  // Show loading state while checking
  if (hasWorld === null) {
    return (
      <div className="flex h-dvh items-center justify-center bg-transparent">
        <div className="text-center">
          <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-2 border-primary-500/30 border-t-primary-500" />
          <p className="text-sm text-slate-400">正在连接世界引擎...</p>
        </div>
      </div>
    )
  }

  return (
    <WorldContext.Provider value={{ hasWorld, currentWorld, refresh: refreshStatus }}>
      <div className="atelier-app h-dvh overflow-hidden bg-[#f7f3eb] text-[#2f2b25] font-sans">
        <a href="#main-content" className="skip-link">跳到主要内容</a>
        {navOpen && (
          <button
            type="button"
            aria-label="关闭导航遮罩"
            className="fixed inset-0 z-30 bg-[#2f2b25]/20 backdrop-blur-sm"
            onClick={() => setNavOpen(false)}
          />
        )}
        <div className="flex h-full gap-0 p-0">
          <Sidebar open={navOpen} onClose={() => setNavOpen(false)} hasWorld={hasWorld} hasCurrentWorld={hasCurrentWorld} />
          <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-[#f7f3eb]">
            <header className={`sticky top-0 z-20 flex min-h-16 shrink-0 items-center justify-between border-b border-[#d6ccba] bg-[#f7f3eb] px-4 md:px-6 ${isReader ? 'hidden' : ''}`}>
              <div className="flex min-w-0 items-center gap-3">
                <Button size="icon" tone="ghost" aria-label="打开导航" onClick={() => setNavOpen(true)}>
                  <Menu aria-hidden="true" className="h-5 w-5 text-[#2f2b25]" />
                </Button>
                <button type="button" onClick={() => navigate('/worlds')} className="flex min-w-0 items-center gap-2 text-left" title="打开世界管理">
                  <BookOpen aria-hidden="true" className="h-4 w-4 shrink-0 text-[#a94334]" />
                  <span className="hidden text-xs tracking-[.12em] text-[#766e64] sm:inline">当前世界</span>
                  <span className="truncate font-serif text-sm font-semibold text-[#2f2b25]">{currentWorld || '未选择世界'}</span>
                  <ChevronRight aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-[#9c9388]" />
                </button>
              </div>
              <button type="button" onClick={() => navigate('/settings')} className="inline-flex min-h-9 items-center gap-2 rounded-none px-2 text-xs text-[#766e64] transition-colors hover:bg-[#f1e7df] hover:text-[#a94334]" title="模型配置">
                <Settings2 aria-hidden="true" className="h-4 w-4" />
                <span className="hidden sm:inline">模型配置</span>
              </button>
            </header>
            <main id="main-content" tabIndex={-1} className={`min-w-0 flex-1 flex flex-col ${isReader ? 'overflow-hidden p-0' : (isPlay || isDashboard) ? 'overflow-hidden p-4 md:p-6 lg:p-8' : 'overflow-auto p-4 md:p-6 lg:p-8'} outline-none`}>
              <Routes>
                {/* World management is always accessible */}
                <Route path="/worlds" element={<WorldPanel />} />
                <Route path="/settings" element={<Settings />} />

                {/* All other routes require a world to exist */}
                <Route path="/" element={
                  hasCurrentWorld
                    ? <Dashboard
                        key={currentWorld}
                        mode={mode} onModeChange={setMode}
                        running={running} onRunningChange={setRunning}
                        paused={paused} onPausedChange={setPaused}
                        logs={logs} onLogsChange={setLogs}
                        progress={progress} onProgressChange={setProgress}
                      />
                    : <Navigate to="/worlds" replace />
                } />
                <Route path="/play" element={hasCurrentWorld ? <Play key={currentWorld} /> : <Navigate to="/worlds" replace />} />
                <Route path="/reader/:volume" element={hasCurrentWorld ? <Reader key={currentWorld} /> : <Navigate to="/worlds" replace />} />
                <Route path="/reader" element={hasCurrentWorld ? <Reader key={currentWorld} /> : <Navigate to="/worlds" replace />} />
                <Route path="/manager" element={hasCurrentWorld ? <Manager key={currentWorld} /> : <Navigate to="/worlds" replace />} />
                <Route path="/relations" element={hasCurrentWorld ? <Relations key={currentWorld} /> : <Navigate to="/worlds" replace />} />
                <Route path="/memory" element={hasCurrentWorld ? <Memory key={currentWorld} /> : <Navigate to="/worlds" replace />} />
                <Route path="/auto-config" element={hasCurrentWorld ? <AutoConfig key={currentWorld} /> : <Navigate to="/worlds" replace />} />
              </Routes>
            </main>
          </div>
        </div>
      </div>
    </WorldContext.Provider>
  )
}
