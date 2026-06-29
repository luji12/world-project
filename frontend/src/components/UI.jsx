export function cx(...classes) {
  return classes.filter(Boolean).join(' ')
}

const buttonTone = {
  primary: 'border border-[#9f3e31] bg-[#ad4b3a] text-[#fffdf8] shadow-none hover:bg-[#913b2e] active:translate-y-px focus-visible:ring-[#ad4b3a]',
  secondary: 'border border-[#cfc5b7] bg-[#fffdf8] text-[#403a32] hover:border-[#ad4b3a]/55 hover:bg-[#f8f2e8] focus-visible:ring-[#ad4b3a]',
  success: 'border border-emerald-300/25 bg-emerald-500/80 text-[#f4f0e5] hover:bg-emerald-400/85 focus-visible:ring-emerald-200',
  danger: 'border border-red-300/25 bg-red-500/75 text-[#fff4ea] hover:bg-red-400/85 focus-visible:ring-red-200',
  ghost: 'text-[#766e64] hover:bg-[#f5eee4] hover:text-[#2f2b25] focus-visible:ring-[#ad4b3a]',
}

export function Button({
  as: Component = 'button',
  tone = 'secondary',
  size = 'md',
  className = '',
  children,
  icon: Icon,
  ...props
}) {
  const sizeClass = size === 'sm'
    ? 'min-h-10 px-3 text-xs'
    : size === 'icon'
      ? 'h-11 w-11 justify-center px-0'
      : 'min-h-11 px-4 text-sm'

  return (
    <Component
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-sm font-semibold tracking-[0.01em] transition-all duration-200 ease-out',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent',
        'disabled:cursor-not-allowed disabled:opacity-45',
        buttonTone[tone],
        sizeClass,
        className,
      )}
      {...props}
    >
      {Icon && <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />}
      {children}
    </Component>
  )
}

export function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center rounded-none border border-dashed border-[#d6ccba]/70 bg-[#fffdf8] p-8 text-center animate-fade-in-up">
      {Icon && <div className="mb-4 rounded-full border border-[#ad4b3a]/25 bg-[#f5e8e2] p-4"><Icon aria-hidden="true" className="h-8 w-8 text-[#ad4b3a]" /></div>}
      <p className="text-base font-semibold text-slate-200">{title}</p>
      {description && <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-500">{description}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

export function LoadingState({ label = '加载中...' }) {
  return (
    <div className="flex min-h-48 items-center justify-center text-sm font-medium text-slate-400 animate-fade-in" role="status" aria-live="polite">
      <span className="mr-3 h-5 w-5 animate-spin rounded-full border-2 border-primary-500/20 border-t-primary-500 shadow-[0_0_10px_rgba(245,158,11,0.3)]" />
      {label}
    </div>
  )
}

export function TextInput({ className = '', ...props }) {
  return (
    <input
      className={cx(
        'min-h-12 rounded-none border border-[#d6ccba] bg-[#fffdf8] px-4 text-sm text-[#2f2b25] placeholder:text-[#9c9388] transition-all duration-200',
        'focus:border-[#ad4b3a]/65 focus:bg-[#fffdf8] focus:outline-none focus:ring-4 focus:ring-[#ad4b3a]/10',
        className,
      )}
      {...props}
    />
  )
}
