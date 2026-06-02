import { useEffect, useId, useState } from 'react'
import styles from './SplashScreen.module.css'

export default function SplashScreen({ onComplete, duration = 4500 }) {
  const gradientId = `${useId().replace(/:/g, '')}-sp-bg`
  const [fading, setFading] = useState(false)

  useEffect(() => {
    const fadeDelay = Math.max(0, duration - 400)
    const fadeTimer = window.setTimeout(() => setFading(true), fadeDelay)
    const completeTimer = window.setTimeout(() => onComplete(), duration)

    return () => {
      window.clearTimeout(fadeTimer)
      window.clearTimeout(completeTimer)
    }
  }, [duration, onComplete])

  return (
    <div className={`${styles.splash} ${fading ? styles.fading : ''}`} aria-label="S4-Log a iniciar">
      <div className={styles.grid} />
      <div className={styles.content}>
        <div className={styles.iconWrap}>
          <span className={`${styles.ring} ${styles.ringOne}`} />
          <span className={`${styles.ring} ${styles.ringTwo}`} />
          <svg width="100" height="100" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="S4-Log">
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#203570" />
                <stop offset="100%" stopColor="#0A1428" />
              </linearGradient>
            </defs>
            <rect width="100" height="100" rx="23" fill={`url(#${gradientId})`} />
            <rect x="14" y="20" width="48" height="64" rx="7" fill="#FFFFFF" />
            <circle cx="38" cy="20" r="5.5" fill="#0A1428" />
            <circle cx="38" cy="20" r="2.5" fill="#263870" />
            <rect x="22" y="32" width="30" height="2.5" rx="1.2" fill="#DDE1F0" />
            <rect x="22" y="38" width="22" height="1.8" rx="0.9" fill="#E8EBF6" />
            <rect x="22" y="43" width="26" height="1.8" rx="0.9" fill="#E8EBF6" />
            <text
              x="38"
              y="72"
              textAnchor="middle"
              fill="#0A1428"
              fontFamily="'Arial Black', 'Helvetica Neue', Arial, sans-serif"
              fontSize="21"
              fontWeight="900"
              letterSpacing="0"
            >
              S4
            </text>
            <circle cx="62" cy="52" r="3.8" fill="#FF6B00" />
            <path d="M62,43.5 Q69.5,52 62,60.5" stroke="#FF6B00" fill="none" strokeWidth="3.5" strokeLinecap="round" />
            <path d="M62,35 Q79,52 62,69" stroke="#FF6B00" fill="none" strokeWidth="2.5" strokeLinecap="round" opacity="0.75" />
            <path d="M62,25.5 Q91,52 62,78.5" stroke="#FF6B00" fill="none" strokeWidth="1.8" strokeLinecap="round" opacity="0.45" />
          </svg>
        </div>

        <div className={styles.logoTitle}>
          <span className={styles.s4}>S4</span>
          <span className={styles.log}><span className={styles.dotAccent}>.</span>Log</span>
        </div>
        <div className={styles.subtitle}>SERVICOS PARA LOGISTICA</div>
        <div className={styles.promise}>
          <span>ENCONTRA</span>
          <span className={styles.separator}>.</span>
          <span>RASTREIA</span>
          <span className={styles.separator}>.</span>
          <span>ENTREGA</span>
        </div>
        <div className={styles.brand}>by OnSearch</div>
        <div className={styles.dots} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  )
}
