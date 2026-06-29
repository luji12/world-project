import { NavLink } from 'react-router-dom'
import {
  BookOpen,
  Brain,
  CircleGauge,
  Database,
  GitBranch,
  Globe2,
  LayoutDashboard,
  MessageSquare,
  Settings,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { Button, cx } from './UI'

// Links that require a world to exist
const worldLinks = [
  { to: '/play', label: '群聊推演', icon: MessageSquare },
  { to: '/', label: '上帝工作台', icon: LayoutDashboard },
  { to: '/reader', label: '阅读器', icon: BookOpen },
  { to: '/manager', label: '管理器', icon: CircleGauge },
  { to: '/relations', label: '关系图谱', icon: GitBranch },
  { to: '/memory', label: '记忆系统', icon: Brain },
  { to: '/auto-config', label: '自动配置', icon: SlidersHorizontal },
]

// Links always accessible
const globalLinks = [
  { to: '/worlds', label: '世界管理', icon: Globe2 },
  { to: '/settings', label: '模型配置', icon: Settings },
]

export default function Sidebar({ open = false, onClose, hasWorld = true, hasCurrentWorld = hasWorld }) {
  return (
    <aside
      className={cx(
        'fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r border-[#d6ccba] bg-[#fbf8f1] shadow-xl',
        'transition-transform duration-300 ease-out',
        open ? 'translate-x-0' : '-translate-x-full',
      )}
      aria-label="主导航"
    >
      <div className="flex items-center gap-3 border-b border-[#d6ccba] p-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-full border border-[#ad4b3a]/35 bg-[#f5e8e2] text-[#a94334]">
          <Database aria-hidden="true" className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="atelier-title truncate text-base font-semibold tracking-[0.08em] text-[#2f2b25]">世界模拟器</h1>
          <p className="mt-0.5 truncate text-[11px] tracking-[0.12em] text-[#766e64]">多智能体叙事引擎</p>
        </div>
        <Button aria-label="关闭导航" size="icon" tone="ghost" onClick={onClose}>
          <X aria-hidden="true" className="h-5 w-5" />
        </Button>
      </div>

      <nav className="flex-1 space-y-6 overflow-auto p-3">
        <div className="space-y-1">
          <div className="mb-2 px-3 text-[11px] font-semibold tracking-[0.16em] text-[#766e64]">核心视图</div>
          {/* World-dependent links */}
          {worldLinks.map(({ to, label, icon: Icon }) => (
            hasCurrentWorld ? (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  cx(
                    'flex min-h-11 items-center gap-3 rounded-none px-3 text-sm transition-colors duration-200',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/70 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950',
                    isActive
                      ? 'border border-[#ad4b3a]/30 bg-[#f3e5df] text-[#a94334]'
                      : 'border border-transparent text-[#625a50] hover:bg-[#f5eee4] hover:text-[#2f2b25]',
                  )
                }
              >
                <Icon aria-hidden="true" className="h-4.5 w-4.5 shrink-0" />
                <span className="truncate">{label}</span>
              </NavLink>
            ) : (
              <div
                key={to}
                title={hasWorld ? '请先选择当前世界' : '请先创建世界'}
                className="flex min-h-11 cursor-not-allowed items-center gap-3 rounded-md px-3 text-sm text-[#b1a89b] select-none"
              >
                <Icon aria-hidden="true" className="h-4.5 w-4.5 shrink-0" />
                <span className="truncate">{label}</span>
              </div>
            )
          ))}

          {/* Divider */}
          <div className="mx-auto my-4 w-3/4 border-t border-[#d6ccba]" />

          <div className="mb-2 mt-4 px-3 text-[11px] font-semibold tracking-[0.16em] text-[#766e64]">系统设置</div>

          {/* Global links */}
          {globalLinks.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cx(
                  'flex min-h-11 items-center gap-3 rounded-none px-3 text-sm transition-colors duration-200',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/70 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950',
                  isActive
                    ? 'border border-[#ad4b3a]/30 bg-[#f3e5df] text-[#a94334]'
                    : 'border border-transparent text-[#625a50] hover:bg-[#f5eee4] hover:text-[#2f2b25]',
                )
              }
            >
              <Icon aria-hidden="true" className="h-4.5 w-4.5 shrink-0" />
              <span className="truncate">{label}</span>
              {!hasCurrentWorld && to === '/worlds' && (
                <span className="ml-auto rounded-sm bg-[#f3e5df] px-1.5 py-0.5 text-[10px] text-[#a94334]">{hasWorld ? '选择世界' : '从这里开始'}</span>
              )}
            </NavLink>
          ))}
        </div>
      </nav>

      <div className="border-t border-[#d6ccba] p-4 text-xs text-[#766e64]">
        <div className="rounded-none border border-[#d6ccba] bg-[#fffdf8] p-3">
          <p className="font-medium text-[#625a50]">v0.5</p>
          <p className="mt-1 leading-5">
            {hasCurrentWorld ? '推演、阅读、记忆与世界管理统一入口。' : hasWorld ? '请先在「世界管理」选择一个世界继续。' : '请先在「世界管理」创建你的第一个世界。'}
          </p>
        </div>
      </div>
    </aside>
  )
}
