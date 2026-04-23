import styles from './ui.module.css'

/* ── Button ── */
export function Btn({ children, variant = 'primary', disabled, onClick, loading }) {
  return (
    <button
      className={`${styles.btn} ${styles[variant]}`}
      disabled={disabled || loading}
      onClick={onClick}
    >
      {loading && <span className={styles.spinner} />}
      {children}
    </button>
  )
}

/* ── Card ── */
export function Card({ children, className = '' }) {
  return <div className={`${styles.card} ${className}`}>{children}</div>
}

/* ── Card title ── */
export function CardTitle({ children }) {
  return <div className={styles.cardTitle}>{children}</div>
}

/* ── Badge ── */
export function Badge({ type = 'default', children }) {
  return <span className={`${styles.badge} ${styles[`badge_${type}`]}`}>{children}</span>
}

/* ── Stat ── */
export function Stat({ label, value, color }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statVal} style={color ? { color } : {}}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  )
}

/* ── Stats bar ── */
export function StatsBar({ children }) {
  return <div className={styles.statsBar}>{children}</div>
}

/* ── Steps ── */
export function Steps({ steps, current }) {
  return (
    <div className={styles.steps}>
      {steps.map((s, i) => {
        const n = i + 1
        const state = n < current ? 'done' : n === current ? 'active' : 'idle'
        return (
          <div key={i} className={`${styles.step} ${styles[`step_${state}`]}`}>
            <div className={styles.stepNum}>
              {state === 'done' ? '✓' : n}
            </div>
            <span>{s}</span>
          </div>
        )
      })}
    </div>
  )
}

/* ── Info field ── */
export function InfoField({ label, value, mono }) {
  return (
    <div className={styles.infoField}>
      <label>{label}</label>
      <span className={mono ? styles.mono : ''}>{value ?? '—'}</span>
    </div>
  )
}

/* ── Info grid ── */
export function InfoGrid({ children }) {
  return <div className={styles.infoGrid}>{children}</div>
}

/* ── Result banner ── */
export function ResultBanner({ ok, title, detail }) {
  return (
    <div className={`${styles.resultBanner} ${ok ? styles.bannerOk : styles.bannerWarn}`}>
      <div className={styles.resultIcon}>{ok ? '✅' : '⚠️'}</div>
      <div>
        <div className={styles.resultTitle}>{title}</div>
        {detail && <div className={styles.resultDetail}>{detail}</div>}
      </div>
    </div>
  )
}

/* ── Spinner ── */
export function Spinner({ size = 20 }) {
  return (
    <span
      className={styles.spinner}
      style={{ width: size, height: size }}
    />
  )
}

/* ── Toast hook (global) ── */
let _addToast = null
export function setToastHandler(fn) { _addToast = fn }
export function toast(msg, type = 'success') { _addToast?.(msg, type) }

export function ToastContainer() {
  const [toasts, setToasts] = import('react').then ? [] : []
  // implemented in ToastProvider
  return null
}
