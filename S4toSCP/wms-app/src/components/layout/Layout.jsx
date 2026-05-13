import { NavLink } from 'react-router-dom'
import styles from './Layout.module.css'

const nav = [
  { to: '/importacao', label: 'Importacao', icon: 'IMP' },
  { to: '/recepcao', label: 'Rececao', icon: 'REC' },
  { to: '/consulta', label: 'Consulta', icon: 'CON' },
  { to: '/etiquetas', label: 'Etiquetas RFID', icon: 'RF' },
  { to: '/configuracao', label: 'Configuracao', icon: 'CFG' },
]

export default function Layout({ children }) {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.logo}>
          <span className={styles.logoMark}>WMS</span>
          <span className={styles.logoSub}>Armazem</span>
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
