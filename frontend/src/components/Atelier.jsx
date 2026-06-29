import { Loader2 } from 'lucide-react'
import { cx } from './UI'

/**
 * Shared interaction primitives for the narrative workspace.
 *
 * They deliberately keep structure separate from page data: pages decide what
 * an action does, while the workspace owns focus, density, states and visual
 * hierarchy.  This is the base layer used by the full UI rebuild.
 */
export function WorkspacePage({ children, className = '' }) {
  return <div className={cx('atelier-page space-y-6 pb-6', className)}>{children}</div>
}

export function WorkspaceHeader({ title, description, trail, actions }) {
  return (
    <header className="border-b border-[#d6ccba]/15 pb-5">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          {trail && <p className="mb-2 text-[11px] font-semibold tracking-[.18em] text-[#a94334]">{trail}</p>}
          <h1 className="atelier-title text-3xl font-semibold tracking-[.08em] text-[#2f2b25] md:text-4xl">{title}</h1>
          {description && <p className="mt-3 max-w-2xl text-sm leading-6 text-[#766e64]">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}

export function Surface({ children, className = '', as: Component = 'section', ...props }) {
  return <Component className={cx('atelier-panel rounded-none', className)} {...props}>{children}</Component>
}

export function SectionTitle({ icon: Icon, children, action }) {
  return (
    <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[#d6ccba]/12 px-5 py-4">
      <h2 className="atelier-heading flex min-w-0 items-center gap-2 text-lg font-semibold tracking-[.06em] text-[#2f2b25]">
        {Icon && <Icon aria-hidden="true" className="h-4.5 w-4.5 shrink-0 text-[#a94334]" />}
        <span className="truncate">{children}</span>
      </h2>
      {action}
    </div>
  )
}

export function Segmented({ value, onChange, items, ariaLabel }) {
  return (
    <div className="inline-flex max-w-full flex-wrap rounded-none border border-[#d6ccba] bg-[#fffdf8] p-1" role="group" aria-label={ariaLabel}>
      {items.map(item => (
        <button
          key={item.value}
          type="button"
          onClick={() => onChange(item.value)}
          aria-pressed={value === item.value}
          className={cx(
            'min-h-9 rounded px-3 text-xs font-medium transition-colors',
            value === item.value ? 'bg-[#f3e5df] text-[#a94334]' : 'text-[#766e64] hover:bg-[#f8f2e8] hover:text-[#2f2b25]',
          )}
        >
          {item.icon && <item.icon aria-hidden="true" className="mr-1.5 inline h-3.5 w-3.5" />}
          {item.label}
        </button>
      ))}
    </div>
  )
}

export function StateTag({ children, tone = 'quiet' }) {
  const tones = {
    quiet: 'border-[#d6ccba] bg-[#fffdf8] text-[#766e64]',
    brass: 'border-[#ad4b3a]/35 bg-[#f5e8e2] text-[#a94334]',
    success: 'border-emerald-300/25 bg-emerald-400/10 text-emerald-200',
    danger: 'border-red-300/25 bg-red-400/10 text-red-200',
  }
  return <span className={cx('inline-flex items-center rounded-sm border px-2 py-1 text-[11px] font-medium', tones[tone] || tones.quiet)}>{children}</span>
}

export function KeyValue({ label, value, className = '' }) {
  return (
    <div className={cx('border-l border-[#ad4b3a]/45 pl-3', className)}>
      <p className="text-[11px] tracking-[.1em] text-[#766e64]">{label}</p>
      <p className="mt-1 truncate text-sm font-medium text-[#3d3831]">{value || '—'}</p>
    </div>
  )
}

export function InlineLoader({ children = '处理中…' }) {
  return <span className="inline-flex items-center gap-2 text-xs text-[#766e64]"><Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin text-[#a94334]" />{children}</span>
}

export function OverlayDialog({ children, onClose, label = '关闭对话框' }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[#2f2b25]/25 p-4 backdrop-blur-sm" role="presentation" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={label} className="w-full max-w-lg rounded-none border border-[#d6ccba] bg-[#fffdf8] shadow-xl" onMouseDown={event => event.stopPropagation()}>
        {children}
      </div>
    </div>
  )
}
