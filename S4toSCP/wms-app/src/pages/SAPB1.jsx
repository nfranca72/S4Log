import { useEffect, useMemo, useState } from 'react'
import { sapB1Api } from '../services/api'
import { useToast } from '../context/ToastContext'
import styles from './SAPB1.module.css'

const integrationMeta = {
  items: { label: 'Artigos SAP -> WMS', accent: 'blue' },
  wms_items: { label: 'Artigos WMS -> SAP', accent: 'green' },
  partners: { label: 'Clientes e fornecedores', accent: 'amber' },
  transfers: { label: 'Transferencias de stock', accent: 'green' },
  stock_movements: { label: 'Entradas e saidas', accent: 'red' },
  purchase_orders: { label: 'Ordens de compra', accent: 'amber' },
  dashboard_movements: { label: 'Acumulados DocMovs', accent: 'blue' },
}

const initialConfig = {
  sap_sl_host: '',
  sap_sl_company: '',
  sap_sl_user: '',
  sap_sl_password: '',
  sap_sl_verify_ssl: false,
  wms_db_server: '',
  wms_db_name: '',
  wms_db_user: '',
  wms_db_password: '',
  wms_db_driver: 'ODBC Driver 17 for SQL Server',
  dashboard_db_name: 'Ons3_Dash',
  interval_items: 1800,
  interval_wms_items: 1800,
  interval_partners: 1800,
  interval_transfers: 120,
  interval_stock_movements: 120,
  interval_purchase_orders: 120,
  interval_dashboard_movements: 120,
  sap_transfer_series: '',
  sap_goods_receipt_series: '',
  sap_goods_issue_series: '',
  sap_purchase_order_series: '',
  sap_purchase_order_warehouse_code: '001',
  sap_purchase_order_line_ref_field: 'SEI_DocONS3',
}

function fmtDate(value) {
  if (!value) return 'Sem registo'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Sem registo'
  return new Intl.DateTimeFormat('pt-PT', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(date)
}

function fmtRelative(value) {
  if (!value) return 'Sem registo'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Sem registo'
  const diffMs = date.getTime() - Date.now()
  const absSeconds = Math.round(Math.abs(diffMs) / 1000)
  const units = [
    ['dia', 86400],
    ['hora', 3600],
    ['min', 60],
  ]

  for (const [label, step] of units) {
    if (absSeconds >= step) {
      const amount = Math.round(absSeconds / step)
      return diffMs >= 0 ? `em ${amount} ${label}` : `ha ${amount} ${label}`
    }
  }
  return diffMs >= 0 ? 'em segundos' : 'agora mesmo'
}

function statusText(status) {
  if (status === 'running') return 'A sincronizar'
  if (status === 'error') return 'Com erro'
  return 'Em espera'
}

function HealthCard({ title, health }) {
  const connected = health?.connected
  return (
    <div className={styles.healthCard}>
      <div className={styles.healthHeader}>
        <span>{title}</span>
        <span className={`${styles.healthBadge} ${connected ? styles.ok : styles.fail}`}>
          {connected ? 'Ligado' : 'Pendente'}
        </span>
      </div>
      <strong>{health?.host || health?.server || 'Por configurar'}</strong>
      <p>{health?.database || health?.error || 'Sem detalhes adicionais.'}</p>
    </div>
  )
}

function IntegrationCard({ name, state, onToggle, onRunNow, busy }) {
  const meta = integrationMeta[name]
  const enabled = Boolean(state?.enabled)
  const status = state?.status || 'idle'

  return (
    <article className={`${styles.integrationCard} ${styles[meta.accent]}`}>
      <div className={styles.integrationTop}>
        <div>
          <p className={styles.eyebrow}>{name.replace('_', ' ')}</p>
          <h3>{meta.label}</h3>
        </div>
        <button
          type="button"
          className={`${styles.toggle} ${enabled ? styles.toggleOn : ''}`}
          onClick={() => onToggle(name, !enabled)}
          disabled={busy}
        >
          <span />
        </button>
      </div>

      <div className={styles.statusRow}>
        <span className={`${styles.statusDot} ${styles[`status_${status}`]}`} />
        <strong>{statusText(status)}</strong>
        <span>{enabled ? 'Ativo' : 'Desligado'}</span>
      </div>

      <dl className={styles.metrics}>
        <div>
          <dt>Ultimo ciclo</dt>
          <dd>{state?.last_cycle_synced ?? 0}</dd>
        </div>
        <div>
          <dt>Erros pendentes</dt>
          <dd>{state?.pending_errors ?? 0}</dd>
        </div>
        <div>
          <dt>Ultimo sucesso</dt>
          <dd>{fmtRelative(state?.last_success_at)}</dd>
        </div>
        <div>
          <dt>Proxima execucao</dt>
          <dd>{fmtRelative(state?.next_run)}</dd>
        </div>
      </dl>

      <p className={styles.taskLine}>{state?.current_task || 'Sem atividade em curso.'}</p>

      <button
        type="button"
        className={styles.secondaryButton}
        onClick={() => onRunNow(name)}
        disabled={!enabled || busy}
      >
        Executar agora
      </button>
    </article>
  )
}

export default function SAPB1() {
  const toast = useToast()
  const [status, setStatus] = useState({})
  const [health, setHealth] = useState(null)
  const [errors, setErrors] = useState([])
  const [logs, setLogs] = useState([])
  const [config, setConfig] = useState(initialConfig)
  const [accessKey, setAccessKey] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [busyKey, setBusyKey] = useState('')

  const pendingErrors = useMemo(
    () => errors.filter(error => error.status === 'pending'),
    [errors],
  )

  async function refreshDashboard({ withConfig = false } = {}) {
    const [statusData, healthData, errorData, logData, configData] = await Promise.all([
      sapB1Api.status(),
      sapB1Api.health(),
      sapB1Api.errors(),
      sapB1Api.logs(),
      withConfig ? sapB1Api.config() : Promise.resolve(null),
    ])

    setStatus(statusData.integrations || {})
    setHealth(healthData)
    setErrors(errorData)
    setLogs(logData)
    if (configData) {
      setConfig(current => ({
        ...current,
        ...configData,
        sap_sl_password: '',
        wms_db_password: '',
      }))
    }
  }

  useEffect(() => {
    let active = true

    async function load() {
      try {
        await refreshDashboard({ withConfig: true })
      } catch (error) {
        if (active) toast(error.message, 'error')
      } finally {
        if (active) setLoading(false)
      }
    }

    load()
    const timer = window.setInterval(() => {
      refreshDashboard().catch(() => {})
    }, 8000)

    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [toast])

  async function handleToggle(name, enabled) {
    setBusyKey(name)
    try {
      await sapB1Api.toggle(name, enabled)
      await refreshDashboard()
      toast(`Integracao ${enabled ? 'ativada' : 'desativada'}.`)
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setBusyKey('')
    }
  }

  async function handleRunNow(name) {
    setBusyKey(`run-${name}`)
    try {
      await sapB1Api.runNow(name)
      await refreshDashboard()
      toast('Execucao manual iniciada.')
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setBusyKey('')
    }
  }

  async function handleSaveConfig(event) {
    event.preventDefault()
    setSaving(true)

    const payload = {
      access_key: accessKey,
      sap_sl_host: config.sap_sl_host,
      sap_sl_company: config.sap_sl_company,
      sap_sl_user: config.sap_sl_user,
      sap_sl_verify_ssl: config.sap_sl_verify_ssl,
      wms_db_server: config.wms_db_server,
      wms_db_name: config.wms_db_name,
      wms_db_user: config.wms_db_user,
      wms_db_driver: config.wms_db_driver,
      dashboard_db_name: config.dashboard_db_name,
      interval_items: Number(config.interval_items),
      interval_wms_items: Number(config.interval_wms_items),
      interval_partners: Number(config.interval_partners),
      interval_transfers: Number(config.interval_transfers),
      interval_stock_movements: Number(config.interval_stock_movements),
      interval_purchase_orders: Number(config.interval_purchase_orders),
      interval_dashboard_movements: Number(config.interval_dashboard_movements),
      sap_transfer_series: config.sap_transfer_series,
      sap_goods_receipt_series: config.sap_goods_receipt_series,
      sap_goods_issue_series: config.sap_goods_issue_series,
      sap_purchase_order_series: config.sap_purchase_order_series,
      sap_purchase_order_warehouse_code: config.sap_purchase_order_warehouse_code,
      sap_purchase_order_line_ref_field: config.sap_purchase_order_line_ref_field,
    }

    if (config.sap_sl_password) payload.sap_sl_password = config.sap_sl_password
    if (config.wms_db_password) payload.wms_db_password = config.wms_db_password

    try {
      await sapB1Api.updateConfig(payload)
      await refreshDashboard({ withConfig: true })
      toast('Configuracao SAP B1 atualizada.')
      setConfig(current => ({ ...current, sap_sl_password: '', wms_db_password: '' }))
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleErrorAction(id, action) {
    try {
      if (action === 'retry') {
        await sapB1Api.retryError(id)
      } else {
        await sapB1Api.resolveError(id, { status: action, resolved_by: 'operador' })
      }
      await refreshDashboard()
      toast('Fila de erros atualizada.')
    } catch (error) {
      toast(error.message, 'error')
    }
  }

  if (loading) {
    return <section className={styles.loading}>A carregar integracao SAP B1...</section>
  }

  return (
    <section className={styles.page}>
      <header className={styles.hero}>
        <div>
          <p className={styles.kicker}>S4-Log x SAP Business One</p>
          <h1>Centro de integracao SAP B1</h1>
          <p className={styles.subtitle}>
            Monitoriza sincronizacoes, executa ciclos manuais e ajusta configuracao sem sair do ambiente principal.
          </p>
        </div>
        <button type="button" className={styles.primaryButton} onClick={() => refreshDashboard({ withConfig: true })}>
          Atualizar agora
        </button>
      </header>

      <div className={styles.healthGrid}>
        <HealthCard title="SAP Service Layer" health={health?.sap} />
        <HealthCard title="Base SQL WMS" health={health?.wms} />
        <div className={styles.healthCard}>
          <div className={styles.healthHeader}>
            <span>Ultima verificacao</span>
            <span className={styles.neutralBadge}>{pendingErrors.length} erros</span>
          </div>
          <strong>{fmtDate(health?.timestamp)}</strong>
          <p>Os estados sao atualizados automaticamente a cada 8 segundos.</p>
        </div>
      </div>

      <div className={styles.integrationGrid}>
        {Object.keys(integrationMeta).map(name => (
          <IntegrationCard
            key={name}
            name={name}
            state={status[name]}
            busy={busyKey === name || busyKey === `run-${name}`}
            onToggle={handleToggle}
            onRunNow={handleRunNow}
          />
        ))}
      </div>

      <div className={styles.columns}>
        <form className={styles.panel} onSubmit={handleSaveConfig}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.eyebrow}>Configuracao</p>
              <h2>Ligacoes e agendamentos</h2>
            </div>
            <span className={styles.panelTag}>Protegido por chave</span>
          </div>

          <div className={styles.formGrid}>
            <label>
              <span>Host SAP</span>
              <input value={config.sap_sl_host} onChange={e => setConfig({ ...config, sap_sl_host: e.target.value })} />
            </label>
            <label>
              <span>Empresa SAP</span>
              <input value={config.sap_sl_company} onChange={e => setConfig({ ...config, sap_sl_company: e.target.value })} />
            </label>
            <label>
              <span>Utilizador SAP</span>
              <input value={config.sap_sl_user} onChange={e => setConfig({ ...config, sap_sl_user: e.target.value })} />
            </label>
            <label>
              <span>Password SAP</span>
              <input type="password" value={config.sap_sl_password} onChange={e => setConfig({ ...config, sap_sl_password: e.target.value })} placeholder="Manter atual se vazio" />
            </label>
            <label>
              <span>Servidor SQL</span>
              <input value={config.wms_db_server} onChange={e => setConfig({ ...config, wms_db_server: e.target.value })} />
            </label>
            <label>
              <span>Base de dados</span>
              <input value={config.wms_db_name} onChange={e => setConfig({ ...config, wms_db_name: e.target.value })} />
            </label>
            <label>
              <span>Base dashboard</span>
              <input value={config.dashboard_db_name} onChange={e => setConfig({ ...config, dashboard_db_name: e.target.value })} />
            </label>
            <label>
              <span>Utilizador SQL</span>
              <input value={config.wms_db_user} onChange={e => setConfig({ ...config, wms_db_user: e.target.value })} />
            </label>
            <label>
              <span>Password SQL</span>
              <input type="password" value={config.wms_db_password} onChange={e => setConfig({ ...config, wms_db_password: e.target.value })} placeholder="Manter atual se vazio" />
            </label>
            <label>
              <span>Intervalo artigos</span>
              <input type="number" min="10" value={config.interval_items} onChange={e => setConfig({ ...config, interval_items: e.target.value })} />
            </label>
            <label>
              <span>Intervalo artigos WMS para SAP</span>
              <input type="number" min="10" value={config.interval_wms_items} onChange={e => setConfig({ ...config, interval_wms_items: e.target.value })} />
            </label>
            <label>
              <span>Intervalo parceiros</span>
              <input type="number" min="10" value={config.interval_partners} onChange={e => setConfig({ ...config, interval_partners: e.target.value })} />
            </label>
            <label>
              <span>Intervalo transferencias</span>
              <input type="number" min="10" value={config.interval_transfers} onChange={e => setConfig({ ...config, interval_transfers: e.target.value })} />
            </label>
            <label>
              <span>Intervalo movimentos</span>
              <input type="number" min="10" value={config.interval_stock_movements} onChange={e => setConfig({ ...config, interval_stock_movements: e.target.value })} />
            </label>
            <label>
              <span>Intervalo ordens compra</span>
              <input type="number" min="10" value={config.interval_purchase_orders} onChange={e => setConfig({ ...config, interval_purchase_orders: e.target.value })} />
            </label>
            <label>
              <span>Intervalo DocMovs</span>
              <input type="number" min="10" value={config.interval_dashboard_movements} onChange={e => setConfig({ ...config, interval_dashboard_movements: e.target.value })} />
            </label>
            <label>
              <span>Series transferencias</span>
              <input value={config.sap_transfer_series} onChange={e => setConfig({ ...config, sap_transfer_series: e.target.value })} placeholder="1,2,3" />
            </label>
            <label>
              <span>Series entradas</span>
              <input value={config.sap_goods_receipt_series} onChange={e => setConfig({ ...config, sap_goods_receipt_series: e.target.value })} placeholder="10,11" />
            </label>
            <label>
              <span>Series saidas</span>
              <input value={config.sap_goods_issue_series} onChange={e => setConfig({ ...config, sap_goods_issue_series: e.target.value })} placeholder="20,21" />
            </label>
            <label>
              <span>Serie ordens compra</span>
              <input value={config.sap_purchase_order_series} onChange={e => setConfig({ ...config, sap_purchase_order_series: e.target.value })} placeholder="30" />
            </label>
            <label>
              <span>Armazem ordens compra</span>
              <input value={config.sap_purchase_order_warehouse_code} onChange={e => setConfig({ ...config, sap_purchase_order_warehouse_code: e.target.value })} placeholder="001" />
            </label>
            <label>
              <span>Campo linha SAP</span>
              <input value={config.sap_purchase_order_line_ref_field} onChange={e => setConfig({ ...config, sap_purchase_order_line_ref_field: e.target.value })} placeholder="SEI_DocONS3" />
            </label>
            <label>
              <span>Chave de acesso</span>
              <input type="password" value={accessKey} onChange={e => setAccessKey(e.target.value)} />
            </label>
          </div>

          <label className={styles.checkbox}>
            <input
              type="checkbox"
              checked={config.sap_sl_verify_ssl}
              onChange={e => setConfig({ ...config, sap_sl_verify_ssl: e.target.checked })}
            />
            <span>Validar certificado SSL do SAP</span>
          </label>

          <button type="submit" className={styles.primaryButton} disabled={saving}>
            {saving ? 'A guardar...' : 'Guardar configuracao'}
          </button>
        </form>

        <div className={styles.stack}>
          <section className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.eyebrow}>Operacao</p>
                <h2>Erros por resolver</h2>
              </div>
              <span className={styles.panelTag}>{pendingErrors.length} pendentes</span>
            </div>

            <div className={styles.list}>
              {pendingErrors.length === 0 && <p className={styles.empty}>Sem erros pendentes neste momento.</p>}
              {pendingErrors.map(error => (
                <article key={error.id} className={styles.listCard}>
                  <div className={styles.listHeader}>
                    <strong>{integrationMeta[error.integration]?.label || error.integration}</strong>
                    <span>{error.sap_key || 'Sem chave SAP'}</span>
                  </div>
                  <p>{error.error_msg}</p>
                  <small>{fmtDate(error.created_at)}</small>
                  <div className={styles.actions}>
                    <button type="button" className={styles.secondaryButton} onClick={() => handleErrorAction(error.id, 'retry')}>
                      Repetir
                    </button>
                    <button type="button" className={styles.ghostButton} onClick={() => handleErrorAction(error.id, 'resolved')}>
                      Resolver
                    </button>
                    <button type="button" className={styles.ghostButton} onClick={() => handleErrorAction(error.id, 'ignored')}>
                      Ignorar
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.eyebrow}>Auditoria</p>
                <h2>Ultimos eventos</h2>
              </div>
              <span className={styles.panelTag}>{logs.length} linhas</span>
            </div>

            <div className={styles.logList}>
              {logs.length === 0 && <p className={styles.empty}>Sem logs disponiveis.</p>}
              {logs.map(log => (
                <article key={log.id} className={styles.logItem}>
                  <div className={styles.logMeta}>
                    <strong>{log.integration}</strong>
                    <span>{log.level}</span>
                    <time>{fmtDate(log.created_at)}</time>
                  </div>
                  <p>{log.message}</p>
                </article>
              ))}
            </div>
          </section>
        </div>
      </div>
    </section>
  )
}
