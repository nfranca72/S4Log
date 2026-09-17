import styles from './TouchKeypad.module.css'

const NUMERIC_KEYS = ['7', '8', '9', '4', '5', '6', '1', '2', '3', '-', '0', '.', '⌫']
const TEXT_ROWS = [
  ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
  ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
  ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L'],
  ['Z', 'X', 'C', 'V', 'B', 'N', 'M', '-', '⌫'],
]

// Every button here uses onMouseDown/preventDefault so tapping a key never steals DOM focus
// away from the real underlying <input> - that input must stay focused the whole time so a
// physical keyboard or a hardware barcode scanner (which types into whatever is focused) keeps
// working alongside the on-screen keys, instead of only the last-clicked key receiving input.
function noStealFocus(event) {
  event.preventDefault()
}

export default function TouchKeypad({ mode = 'numeric', label, hint, notice, value = '', placeholder = '', onKey, onBackspace, onConfirm, onClose }) {
  function press(key) {
    if (key === '⌫') {
      onBackspace?.()
      return
    }
    onKey?.(key)
  }

  return (
    <div className={styles.overlay} role="dialog" aria-label={label || 'Teclado'} onMouseDown={noStealFocus}>
      <div className={styles.panel}>
        <div className={styles.panelHeader}>
          <span>{label || 'Introduzir valor'}</span>
          <button type="button" className={styles.closeBtn} onMouseDown={noStealFocus} onClick={onClose} aria-label="Fechar teclado">×</button>
        </div>

        {hint && <div className={styles.hintBar}>{hint}</div>}

        {notice && (
          <button type="button" className={styles.noticeBar} onMouseDown={noStealFocus} onClick={notice.onAction}>
            <span className={styles.noticeIcon}>{notice.icon}</span>
            <span>{notice.text}</span>
          </button>
        )}

        <div className={styles.valueDisplay}>
          {value ? (
            <span>{value}</span>
          ) : (
            <span className={styles.valuePlaceholder}>{placeholder || '—'}</span>
          )}
          <span className={styles.cursor} />
        </div>

        {mode === 'numeric' ? (
          <div className={styles.numGrid}>
            {NUMERIC_KEYS.map(key => (
              <button
                key={key}
                type="button"
                className={key === '⌫' ? `${styles.key} ${styles.keyWide}` : styles.key}
                onMouseDown={noStealFocus}
                onClick={() => press(key)}
              >{key}</button>
            ))}
          </div>
        ) : (
          <div className={styles.textGrid}>
            {TEXT_ROWS.map((row, index) => (
              <div key={index} className={styles.textRow}>
                {row.map(key => (
                  <button key={key} type="button" className={styles.key} onMouseDown={noStealFocus} onClick={() => press(key)}>{key}</button>
                ))}
              </div>
            ))}
          </div>
        )}

        <button type="button" className={styles.confirmBtn} onMouseDown={noStealFocus} onClick={onConfirm}>OK</button>
      </div>
    </div>
  )
}
