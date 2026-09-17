import { useEffect, useMemo, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import S4LogLogo from '../S4LogLogo'
import styles from './Layout.module.css'

const SIDEBAR_COLLAPSE_WIDTH = 170
const SIDEBAR_MIN_WIDTH = 112
const SIDEBAR_MAX_WIDTH = 520
const SIDEBAR_DEFAULT_WIDTH = 360
const SIDEBAR_TERMINAL_DEFAULT_WIDTH = 420

function IconUpload() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
    </svg>
  )
}

function IconShield() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <path d="M9 12l2 2 4-4"/>
    </svg>
  )
}

function IconInbox() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>
      <path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/>
    </svg>
  )
}

function IconSearch() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8"/>
      <line x1="21" y1="21" x2="16.65" y2="16.65"/>
    </svg>
  )
}

function IconFilter() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" />
    </svg>
  )
}

function IconTag() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/>
      <line x1="7" y1="7" x2="7.01" y2="7"/>
    </svg>
  )
}

function IconDatabase() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3"/>
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
    </svg>
  )
}

function IconSettings() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
    </svg>
  )
}

function IconArrows() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 16V4m0 0L3 8m4-4l4 4"/>
      <path d="M17 8v12m0 0l4-4m-4 4l-4-4"/>
    </svg>
  )
}

function IconFactory() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 21h18" />
      <path d="M5 21V10l5 3V10l5 3V6l4 2v13" />
      <path d="M9 21v-4" />
      <path d="M14 21v-3" />
      <path d="M18 21v-5" />
    </svg>
  )
}

function IconClipboardStack() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3h6l1 2h3a1 1 0 011 1v14a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1h3l1-2z" />
      <path d="M9 12h6" />
      <path d="M9 16h6" />
      <path d="M10 8h4" />
    </svg>
  )
}

function IconScanStack() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 7V5a1 1 0 011-1h2" />
      <path d="M20 7V5a1 1 0 00-1-1h-2" />
      <path d="M4 17v2a1 1 0 001 1h2" />
      <path d="M20 17v2a1 1 0 01-1 1h-2" />
      <path d="M7 12h10" />
      <path d="M9 8h6" />
      <path d="M9 16h6" />
    </svg>
  )
}

function IconTruck() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 17h4V5H2v12h2" />
      <path d="M14 8h4l4 4v5h-2" />
      <circle cx="7" cy="17" r="2" />
      <circle cx="17" cy="17" r="2" />
    </svg>
  )
}

function IconQrBolt() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3h6v6H3zM15 3h6v6h-6zM3 15h6v6H3z" />
      <path d="M17 13l-2 4h3l-1 4 4-6h-3l1-2" />
      <path d="M13 15h1M15 21h1M21 19h-1" />
    </svg>
  )
}

function IconLayers() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l9 4.5-9 4.5-9-4.5L12 3z" />
      <path d="M3 12l9 4.5 9-4.5" />
      <path d="M3 16.5L12 21l9-4.5" />
    </svg>
  )
}

function IconMenu() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6"/>
      <line x1="3" y1="12" x2="21" y2="12"/>
      <line x1="3" y1="18" x2="21" y2="18"/>
    </svg>
  )
}

function IconTerminalMobility() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
      <path d="M10 5.5h4" />
      <path d="M4 9h3M17 15h3" />
      <path d="M4 15l2-2 2 2" />
      <path d="M20 9l-2 2-2-2" />
    </svg>
  )
}

function IconSidebarToggle({ collapsed = false }) {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5h16v14H4z" />
      <path d="M9 5v14" />
      {collapsed ? <path d="M15 9l-3 3 3 3" /> : <path d="M12 9l3 3-3 3" />}
    </svg>
  )
}

const navSections = [
  {
    title: 'Operações',
    items: [
      { to: '/importacao', label: 'Importação', description: 'Entrada e integração de ficheiros', icon: <IconUpload />, accent: 'azure' },
      { to: '/recepcao', label: 'Receção', description: 'Conferência e fecho de entradas', icon: <IconInbox />, accent: 'teal' },
      { to: '/contagem', label: 'Contagem', description: 'Leitura RFID e inventário rápido', icon: <IconScanStack />, accent: 'violet' },
      { to: '/movimentos', label: 'Mov. Simplificados', description: 'Transferências e ajustes diretos', icon: <IconArrows />, accent: 'amber' },
      { to: '/abastecimento', label: 'Abastecimento', description: 'Preparação e apoio à produção', icon: <IconFactory />, accent: 'orange' },
    ],
  },
  {
    title: 'Separação',
    items: [
      { to: '/documento-separacao', label: 'Doc. Separação', description: 'Criar nova ordem de separação', icon: <IconClipboardStack />, accent: 'lime' },
      { to: '/execucao-separacoes', label: 'Execução Separações', description: 'Selecionar e iniciar separações', icon: <IconLayers />, accent: 'blue' },
      { to: '/consulta-separacoes', label: 'Consulta Separações', description: 'Consultar e manter ordens de separação', icon: <IconTruck />, accent: 'slate' },
      { to: '/consulta', label: 'Consulta', description: 'Stock, packing e documentos', icon: <IconSearch />, accent: 'slate' },
      { to: '/etiquetas', label: 'Etiquetas RFID', description: 'Emissão e reimpressão de etiquetas', icon: <IconTag />, accent: 'rose' },
    ],
  },
  {
    title: 'Administração',
    items: [
      { to: '/import-artigos-benfica', label: 'Import Artigos Benfica', description: 'Carga dedicada de catálogo', icon: <IconShield />, accent: 'emerald' },
      { to: '/sap-b1', label: 'SAP B1', description: 'Monitorização e integrador', icon: <IconDatabase />, accent: 'cyan' },
      { to: '/configuracao', label: 'Configuração', description: 'Parâmetros, estação e ambiente', icon: <IconSettings />, accent: 'steel' },
    ],
  },
]

function detectTerminalMode() {
  try {
    const ua = navigator.userAgent || ''
    const smallScreen = window.innerWidth <= 1024
    const coarsePointer = window.matchMedia?.('(pointer: coarse)').matches ?? false
    const shortHeight = window.innerHeight <= 900
    const ruggedHint = /(Zebra|TC21|TC22|TC26|TC27|WT|MC|Android)/i.test(ua)
    return ruggedHint && smallScreen ? true : coarsePointer && smallScreen && shortHeight
  } catch {
    return false
  }
}

function getTerminalModeOverride() {
  try {
    const params = new URLSearchParams(window.location.search)
    const queryValue = params.get('terminal')
    if (queryValue === '1') return true
    if (queryValue === '0') return false

    const storedValue = window.localStorage.getItem('s4log-terminal-override')
    if (storedValue === '1') return true
    if (storedValue === '0') return false
  } catch {
    // ignore access errors
  }
  return null
}

function resolveTerminalMode() {
  const override = getTerminalModeOverride()
  return override == null ? detectTerminalMode() : override
}

export default function Layout({ children }) {
  const location = useLocation()
  const [theme, setTheme] = useState(() => {
    try {
      return window.localStorage.getItem('s4log-theme') || 'dark'
    } catch {
      return 'dark'
    }
  })
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [terminalMode, setTerminalMode] = useState(resolveTerminalMode)
  const [menuQuery, setMenuQuery] = useState('')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('s4log-sidebar-collapsed') === '1'
    } catch {
      return false
    }
  })
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const stored = Number(window.localStorage.getItem('s4log-sidebar-width') || 0)
      if (Number.isFinite(stored) && stored >= SIDEBAR_MIN_WIDTH && stored <= SIDEBAR_MAX_WIDTH) {
        return stored
      }
    } catch {
      // ignore storage errors
    }
    return SIDEBAR_DEFAULT_WIDTH
  })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      window.localStorage.setItem('s4log-theme', theme)
    } catch {
      // ignore storage errors
    }
  }, [theme])

  useEffect(() => {
    try {
      window.localStorage.setItem('s4log-sidebar-collapsed', sidebarCollapsed ? '1' : '0')
    } catch {
      // ignore storage errors
    }
  }, [sidebarCollapsed])

  useEffect(() => {
    try {
      window.localStorage.setItem('s4log-sidebar-width', String(sidebarWidth))
    } catch {
      // ignore storage errors
    }
  }, [sidebarWidth])

  useEffect(() => {
    const applyMode = () => {
      const params = new URLSearchParams(window.location.search)
      const queryValue = params.get('terminal')
      if (queryValue === '1' || queryValue === '0') {
        try {
          window.localStorage.setItem('s4log-terminal-override', queryValue)
        } catch {
          // ignore storage errors
        }
      }
      setTerminalMode(resolveTerminalMode())
    }
    applyMode()
    window.addEventListener('resize', applyMode)
    return () => window.removeEventListener('resize', applyMode)
  }, [])

  useEffect(() => {
    setSidebarWidth(current => {
      if (current) return current
      return terminalMode ? SIDEBAR_TERMINAL_DEFAULT_WIDTH : SIDEBAR_DEFAULT_WIDTH
    })
  }, [terminalMode])

  useEffect(() => {
    if (window.innerWidth <= 900) return
    setSidebarCollapsed(sidebarWidth <= SIDEBAR_COLLAPSE_WIDTH)
  }, [sidebarWidth])

  useEffect(() => {
    document.documentElement.dataset.terminalMode = terminalMode ? 'true' : 'false'
  }, [terminalMode])

  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    setMenuQuery('')
  }, [location.pathname])

  useEffect(() => {
    if (!mobileMenuOpen) return

    const handleResize = () => {
      if (window.innerWidth > 900) {
        setMobileMenuOpen(false)
      }
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('resize', handleResize)

    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('resize', handleResize)
    }
  }, [mobileMenuOpen])

  const nextTheme = theme === 'dark' ? 'light' : 'dark'
  const normalizedQuery = menuQuery.trim().toLowerCase()
  const filteredSections = useMemo(
    () => navSections
      .map(section => ({
        ...section,
        items: section.items.filter(item => {
          if (!normalizedQuery) return true
          const haystack = `${item.label} ${item.description}`.toLowerCase()
          return haystack.includes(normalizedQuery)
        }),
      }))
      .filter(section => section.items.length > 0),
    [normalizedQuery]
  )

  function toggleSidebarCollapsed() {
    if (sidebarCollapsed) {
      const expandedWidth = Math.max(sidebarWidth, terminalMode ? SIDEBAR_TERMINAL_DEFAULT_WIDTH : SIDEBAR_DEFAULT_WIDTH)
      setSidebarWidth(Math.min(expandedWidth, SIDEBAR_MAX_WIDTH))
      setSidebarCollapsed(false)
      return
    }
    setSidebarWidth(SIDEBAR_MIN_WIDTH)
    setSidebarCollapsed(true)
  }

  function startSidebarResize(event) {
    if (window.innerWidth <= 900) return
    event.preventDefault()
    const startX = event.clientX
    const startWidth = sidebarWidth

    const onMove = (moveEvent) => {
      const nextWidth = Math.max(
        SIDEBAR_MIN_WIDTH,
        Math.min(SIDEBAR_MAX_WIDTH, startWidth + (moveEvent.clientX - startX))
      )
      setSidebarWidth(nextWidth)
    }

    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'ew-resize'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  useEffect(() => {
    const handleSidebarToggleRequest = () => {
      if (window.innerWidth <= 1100) {
        setMobileMenuOpen(current => !current)
        return
      }
      toggleSidebarCollapsed()
    }

    window.addEventListener('s4log:toggle-sidebar', handleSidebarToggleRequest)
    return () => window.removeEventListener('s4log:toggle-sidebar', handleSidebarToggleRequest)
  }, [sidebarCollapsed, sidebarWidth, terminalMode])

  const hideMobileMenuButton = location.pathname === '/execucao-separacoes'
  const compactMain = location.pathname === '/execucao-separacoes'

  return (
    <div className={`${styles.shell} ${terminalMode ? styles.terminalShell : ''}`}>
      {!hideMobileMenuButton ? (
        <button
          type="button"
          className={`${styles.mobileMenuButton} ${mobileMenuOpen ? styles.mobileMenuButtonHidden : ''}`}
          onClick={() => setMobileMenuOpen(true)}
          aria-label="Abrir menu"
        >
          <IconMenu />
        </button>
      ) : null}

      {mobileMenuOpen && (
        <button
          type="button"
          className={styles.mobileBackdrop}
          onClick={() => setMobileMenuOpen(false)}
          aria-label="Fechar menu"
        />
      )}

      <aside
        className={`${styles.sidebar} ${mobileMenuOpen ? styles.sidebarOpen : ''} ${terminalMode ? styles.sidebarTerminal : ''} ${sidebarCollapsed ? styles.sidebarCollapsed : ''}`}
        style={{ '--sidebar-width': `${sidebarWidth}px` }}
      >
        <div className={styles.logo}>
          <div className={styles.brandBlock}>
            <div className={styles.brandRow}>
              <S4LogLogo variant={theme === 'light' ? 'light' : 'dark'} size={sidebarCollapsed ? 'icon' : 'full'} />
              {terminalMode ? (
                <span className={styles.terminalBadge} title="Modo terminal" aria-label="Modo terminal">
                  <IconTerminalMobility />
                </span>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            className={styles.sidebarToggle}
            onClick={toggleSidebarCollapsed}
            aria-label={sidebarCollapsed ? 'Expandir menu esquerdo' : 'Recolher menu esquerdo'}
            title={sidebarCollapsed ? 'Expandir menu' : 'Recolher menu'}
          >
            <IconSidebarToggle collapsed={sidebarCollapsed} />
          </button>
          <button
            type="button"
            className={styles.mobileCloseButton}
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Fechar menu"
          >
            ×
          </button>
        </div>
        {!sidebarCollapsed ? (
          <label className={styles.searchPanel}>
            <span className={styles.searchIcon}><IconFilter /></span>
            <input
              type="search"
              value={menuQuery}
              onChange={(event) => setMenuQuery(event.target.value)}
              className={styles.searchInput}
              placeholder="Filtrar opções do menu"
              aria-label="Filtrar opções do menu"
            />
          </label>
        ) : null}
        <nav className={styles.nav}>
          {filteredSections.map(section => (
            <section key={section.title} className={styles.navSection}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>{section.title}</span>
              </div>
              <div className={styles.navGrid}>
                {section.items.map(item => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    title={sidebarCollapsed ? item.label : undefined}
                    data-tooltip={sidebarCollapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      `${styles.navItem} ${styles[`accent${item.accent[0].toUpperCase()}${item.accent.slice(1)}`]} ${isActive ? styles.active : ''}`
                    }
                  >
                    <span className={styles.navIcon}>{item.icon}</span>
                    {!sidebarCollapsed ? (
                      <span className={styles.navCopy}>
                        <span className={styles.navLabel}>{item.label}</span>
                        <span className={styles.navDescription}>{item.description}</span>
                      </span>
                    ) : null}
                  </NavLink>
                ))}
              </div>
            </section>
          ))}
          {filteredSections.length === 0 && (
            <div className={styles.emptyState}>
              <span className={styles.emptyTitle}>Sem resultados</span>
              <span className={styles.emptyHint}>Ajusta o texto para mostrar outras opções do menu.</span>
            </div>
          )}
        </nav>
        <div className={styles.sidebarFooter}>
          <button
            type="button"
            className={styles.themeToggle}
            onClick={() => setTheme(nextTheme)}
            aria-label={theme === 'dark' ? 'Ativar tema claro' : 'Ativar tema escuro'}
            title={theme === 'dark' ? 'Ativar tema claro' : 'Ativar tema escuro'}
          >
            <span className={styles.themeIcon} aria-hidden="true">
              {theme === 'dark' ? (
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
                </svg>
              ) : (
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 12.8A8.5 8.5 0 1111.2 3 6.5 6.5 0 0021 12.8z" />
                </svg>
              )}
            </span>
            <span>{theme === 'dark' ? 'Tema claro' : 'Tema escuro'}</span>
          </button>
          <span className={styles.version}>v1.0.0</span>
        </div>
        <button
          type="button"
          className={styles.resizeHandle}
          onMouseDown={startSidebarResize}
          aria-label="Redimensionar menu esquerdo"
          title="Redimensionar menu"
        />
      </aside>
      <main className={`${styles.main} ${compactMain ? styles.mainCompact : ''}`}>
        {children}
      </main>
    </div>
  )
}
