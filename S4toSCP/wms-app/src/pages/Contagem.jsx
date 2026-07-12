import { useEffect, useMemo, useState } from 'react'
import { Card, CardTitle, Btn, StatsBar, Stat } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { countingApi } from '../services/api'
import sharedStyles from './Module2.module.css'
import styles from './Contagem.module.css'

const API = import.meta.env.VITE_API_URL ?? '/api'

function tunnelLabel(tunnel, index) {
  const base = String.fromCharCode(65 + index)
  return tunnel?.tunnel_code ? `${base} - ${tunnel.tunnel_code}` : base
}

function formatTime(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('pt-PT', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(value)
}

export default function Contagem() {
  const toast = useToast()
  const [tunnels, setTunnels] = useState([])
  const [selectedTunnel, setSelectedTunnel] = useState('')
  const [snapshot, setSnapshot] = useState({
    tunnel_id: 0,
    total_tags: 0,
    known_tags: 0,
    new_tags: 0,
    known_items: [],
    new_tag_list: [],
  })
  const [rfidStatus, setRfidStatus] = useState('idle')
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)

  useEffect(() => {
    fetch(`${API}/config/tunnels`)
      .then(r => r.json())
      .then(data => {
        const tunnelList = Array.isArray(data) ? data : []
        setTunnels(tunnelList)
        if (tunnelList[0]?.tunnel_id) {
          setSelectedTunnel(String(tunnelList[0].tunnel_id))
        }
      })
      .catch(() => {
        toast('Erro ao carregar túneis RFID', 'error')
      })
  }, [toast])

  const refreshSnapshot = async (showLoader = false) => {
    if (!selectedTunnel) return
    if (showLoader) setRefreshing(true)
    try {
      const data = await countingApi.snapshot(selectedTunnel)
      setSnapshot(data)
      setLastUpdated(new Date())
    } catch (e) {
      toast(e.message || 'Erro ao atualizar contagem', 'error')
    } finally {
      if (showLoader) setRefreshing(false)
    }
  }

  useEffect(() => {
    refreshSnapshot(true)
  }, [selectedTunnel])

  useEffect(() => {
    if (rfidStatus !== 'reading' || !selectedTunnel) return undefined

    const timer = window.setInterval(() => {
      refreshSnapshot(false)
    }, 1000)

    return () => window.clearInterval(timer)
  }, [rfidStatus, selectedTunnel])

  const runAction = async (action, nextStatus) => {
    if (!selectedTunnel) {
      toast('Seleciona um túnel RFID', 'error')
      return
    }
    setLoading(true)
    try {
      await action(selectedTunnel)
      setRfidStatus(nextStatus)
      await refreshSnapshot(false)
    } catch (e) {
      toast(e.message || 'Erro na operação RFID', 'error')
    } finally {
      setLoading(false)
    }
  }

  const knownPieces = useMemo(
    () => snapshot.known_items.reduce((total, item) => total + (item.qty_counted || 0), 0),
    [snapshot.known_items],
  )

  return (
    <div className={sharedStyles.page}>
      <div className={sharedStyles.pageHeader}>
        <div>
          <h1 className={sharedStyles.pageTitle}>Contagem</h1>
          <p className={sharedStyles.pageDesc}>Contagem RFID no túnel sem criação nem movimentação de stock</p>
        </div>
      </div>

      <Card>
        <div className={sharedStyles.whRow}>
          <div className={sharedStyles.whField}>
            <label>Túnel RFID</label>
            <select
              className={sharedStyles.select}
              value={selectedTunnel}
              onChange={e => setSelectedTunnel(e.target.value)}
            >
              <option value="">Selecionar...</option>
              {tunnels.map((tunnel, index) => (
                <option key={tunnel.tunnel_id} value={tunnel.tunnel_id}>
                  {tunnelLabel(tunnel, index)}{tunnel.tunnel_desc ? ` — ${tunnel.tunnel_desc}` : ''}
                </option>
              ))}
            </select>
          </div>

          <div className={styles.actions}>
            <Btn variant="primary" loading={loading} onClick={() => runAction(countingApi.start, 'reading')}>
              Iniciar leitura
            </Btn>
            <Btn variant="outline" loading={loading} onClick={() => runAction(countingApi.reset, 'reading')}>
              Nova leitura
            </Btn>
            <Btn variant="outline" loading={loading} onClick={() => runAction(countingApi.stop, 'stopped')}>
              Parar
            </Btn>
            <Btn variant="outline" loading={refreshing} onClick={() => refreshSnapshot(true)}>
              Atualizar
            </Btn>
          </div>
        </div>

        <div className={styles.statusRow}>
          <span className={`${styles.statusBadge} ${styles[`status_${rfidStatus}`]}`}>
            {rfidStatus === 'reading' ? 'Leitura ativa' : rfidStatus === 'stopped' ? 'Leitura parada' : 'Pronto para contar'}
          </span>
          <span className={styles.updatedAt}>Última atualização: {formatTime(lastUpdated)}</span>
        </div>
      </Card>

      <StatsBar>
        <Stat label="Peças lidas" value={snapshot.total_tags} />
        <Stat label="Peças conhecidas" value={snapshot.known_tags} color="var(--green)" />
        <Stat label="Peças novas" value={snapshot.new_tags} color="var(--yellow)" />
        <Stat label="Artigos conhecidos" value={snapshot.known_items.length} color="var(--accent)" />
      </StatsBar>

      <div className={styles.summaryGrid}>
        <Card>
          <CardTitle>Resumo das peças conhecidas</CardTitle>
          <div className={styles.summaryIntro}>
            <span>{knownPieces} peça(s) reconhecida(s) na base de dados RFID</span>
          </div>
          <div className={sharedStyles.tableWrap}>
            <table className={sharedStyles.table}>
              <thead>
                <tr>
                  <th>Artigo</th>
                  <th>Descrição</th>
                  <th>Ref. cliente</th>
                  <th>Barcode</th>
                  <th style={{ textAlign: 'right' }}>Qtd. contada</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.known_items.length === 0 ? (
                  <tr>
                    <td colSpan="5" className={styles.emptyCell}>Sem peças conhecidas nesta leitura.</td>
                  </tr>
                ) : (
                  snapshot.known_items.map(item => (
                    <tr key={`${item.item_id}-${item.client_ref}-${item.barcode}`}>
                      <td className={sharedStyles.mono}>{item.item_id || '—'}</td>
                      <td className={sharedStyles.tdDesc}>{item.item_desc || '—'}</td>
                      <td className={sharedStyles.mono}>{item.client_ref || '—'}</td>
                      <td className={sharedStyles.mono}>{item.barcode || '—'}</td>
                      <td style={{ textAlign: 'right' }}>
                        <span className={sharedStyles.qtyGreen}>{item.qty_counted}</span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <CardTitle>Tags novas</CardTitle>
          <div className={styles.summaryIntro}>
            <span>{snapshot.new_tags} tag(s) ainda não conhecidas na base de dados</span>
          </div>
          {snapshot.new_tag_list.length === 0 ? (
            <div className={styles.emptyState}>Nenhuma tag nova nesta leitura.</div>
          ) : (
            <div className={styles.tagList}>
              {snapshot.new_tag_list.map(tag => (
                <div key={tag} className={styles.tagItem}>
                  {tag}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
