import { NavLink } from 'react-router-dom'
import styles from './Layout.module.css'

const nav = [
  { to: '/importacao',   label: 'Importação',     icon: '⬆' },
  { to: '/recepcao',     label: 'Receção',         icon: '📦' },
  { to: '/consulta',     label: 'Consulta',         icon: '🔍' },
  { to: '/configuracao', label: 'Configuração',    icon: '⚙' },
]

export default function Layout({ children }) {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.logo}>
          <span className={styles.logoMark}>WMS</span>
          <span className={styles.logoSub}>Armazém</span>
        </div>
        <nav className={styles.nav}>
          {nav.map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `${styles.navItem} ${isActive ? styles.active : ''}`
              }
            >
              <span className={styles.navIcon}>{n.icon}</span>
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className={styles.sidebarFooter}>
          <span className={styles.version}>v1.0.0</span>
        </div>
      </aside>
      <main className={styles.main}>
        {children}
      </main>
    </div>
  )
}
