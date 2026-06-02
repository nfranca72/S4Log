import { useId } from 'react'

const DIMENSIONS = {
  full: { width: 148, height: 44, viewBox: '0 0 148 44' },
  compact: { width: 80, height: 24, viewBox: '0 0 148 44' },
  icon: { width: 32, height: 32, viewBox: '0 0 44 44' },
}

export default function S4LogLogo({ variant = 'dark', size = 'full' }) {
  const gradientId = `${useId().replace(/:/g, '')}-s4-icon-bg`
  const dims = DIMENSIONS[size] ?? DIMENSIONS.full
  const wordColor = variant === 'light' ? '#0C1830' : '#FFFFFF'
  const taglineColor = variant === 'light' ? '#7090B0' : '#3A5070'
  const showWordmark = size !== 'icon'
  const showTagline = size === 'full'

  return (
    <svg
      width={dims.width}
      height={dims.height}
      viewBox={dims.viewBox}
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="S4-Log by OnSearch"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#1E3468" />
          <stop offset="100%" stopColor="#0A1428" />
        </linearGradient>
      </defs>
      <rect width="44" height="44" rx="10" fill={`url(#${gradientId})`} />
      <rect x="6" y="7" width="22" height="30" rx="3.5" fill="#FFFFFF" />
      <circle cx="17" cy="7" r="2.5" fill="#0A1428" />
      <circle cx="17" cy="7" r="1.2" fill="#263870" />
      <rect x="10" y="13.5" width="14" height="1.5" rx="0.7" fill="#DDE1F0" />
      <rect x="10" y="17.5" width="10" height="1.2" rx="0.6" fill="#E8EBF6" />
      <text
        x="17"
        y="31"
        textAnchor="middle"
        fill="#0A1428"
        fontFamily="'Arial Black', sans-serif"
        fontSize="10"
        fontWeight="900"
      >
        S4
      </text>
      <circle cx="29" cy="22" r="1.8" fill="#FF6B00" />
      <path d="M29,18 Q32.5,22 29,26" stroke="#FF6B00" fill="none" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M29,14 Q36,22 29,30" stroke="#FF6B00" fill="none" strokeWidth="1.3" strokeLinecap="round" opacity="0.75" />
      <path d="M29,10 Q42,22 29,34" stroke="#FF6B00" fill="none" strokeWidth="0.9" strokeLinecap="round" opacity="0.45" />

      {showWordmark && (
        <text x="54" y="27" fontFamily="'Segoe UI', Arial, sans-serif" fontSize="22" letterSpacing="0">
          <tspan fontWeight="800" fill="#FF6B00">S4</tspan>
          <tspan fontWeight="600" fill={wordColor}>-Log</tspan>
        </text>
      )}
      {showTagline && (
        <text x="54" y="39" fontFamily="'Segoe UI', Arial, sans-serif" fontSize="10" fill={taglineColor} letterSpacing="0.4">
          by OnSearch
        </text>
      )}
    </svg>
  )
}
