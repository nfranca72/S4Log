import { useState, useEffect } from 'react'
import { useToast } from '../context/ToastContext'
import { Card, CardTitle, Btn, Spinner } from '../components/ui'
import styles from './Config.module.css'
import { STATION_STORAGE_KEY } from '../services/api'

const API = '/api'

export default function Config() {
  const toast   = useToast()
  const [cfg, setCfg]       = useState(null)
  const [tunnels, setTunnels] = useState([])
  const [selectedTunnel, setSelectedTunnel] = useState('')
  const [stationCfg, setStationCfg] = useState({ station_identifier: '' })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)

  useEffect(() => {
    Promise.all([
      fetch(`${API}/config/tunnels`).then(async r => {
        if (!r.ok) throw new Error()
        return r.json()
      }),
      Promise.resolve({
        station_identifier: window.localStorage.getItem(STATION_STORAGE_KEY) || '',
      }),
    ])
      .then(([tunnelList, station]) => {
        const nextTunnels = Array.isArray(tunnelList) ? tunnelList : []
        setTunnels(nextTunnels)
        setSelectedTunnel(nextTunnels[0]?.tunnel_id ? String(nextTunnels[0].tunnel_id) : '')
        setStationCfg(station)
      })
      .catch(() => toast('Erro ao carregar configuração', 'error'))
      .finally(() => setLoading(false))
  }, [toast])

  useEffect(() => {
    if (!selectedTunnel) {
      setCfg(null)
      return
    }

    let cancelled = false
    setLoading(true)

    fetch(`${API}/config/tunnels/${selectedTunnel}/rfid`)
      .then(async r => {
        if (!r.ok) throw new Error()
        return r.json()
      })
      .then(rfidCfg => {
        if (!cancelled) setCfg(rfidCfg)
      })
      .catch(() => {
        if (!cancelled) {
          setCfg(null)
          toast('Erro ao carregar configuração do túnel', 'error')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [selectedTunnel, toast])

  const updateAntenna = (idx, field, value) => {
    setCfg(prev => ({
      ...prev,
      antennas: prev.antennas.map((a, i) =>
        i === idx ? { ...a, [field]: value } : a
      )
    }))
  }

  const save = async () => {
    if (!cfg || !selectedTunnel) return

    setSaving(true)
    try {
      const saveConfigRequest = fetch(`${API}/config/tunnels/${selectedTunnel}/rfid`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      }).then(async r => {
        if (!r.ok) throw new Error()
        return r.json()
      })

      const [savedConfig] = await Promise.all([
        saveConfigRequest,
        Promise.resolve(window.localStorage.setItem(STATION_STORAGE_KEY, stationCfg.station_identifier || '')),
      ])
      setCfg(savedConfig)
      toast('Configuração guardada')
    } catch { toast('Erro ao guardar configuração', 'error') }
    finally { setSaving(false) }
  }

  if (loading) return <div className={styles.center}><Spinner size={32} /></div>
  if (!tunnels.length) {
    return (
      <div>
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>Configuração RFID</h1>
          <p className={styles.pageDesc}>Não existem túneis RFID ativos para configurar.</p>
        </div>
      </div>
    )
  }
  if (!cfg) return null

  const tunnelMeta = tunnels.find(tunnel => String(tunnel.tunnel_id) === String(selectedTunnel))

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Configuração RFID</h1>
        <p className={styles.pageDesc}>
          {tunnelMeta?.tunnel_code ? `${tunnelMeta.tunnel_code} — ` : ''}
          Zebra FX7500 — {cfg.host}:{cfg.port}
        </p>
      </div>

      <Card>
        <CardTitle>Túnel RFID</CardTitle>
        <div className={styles.row}>
          <div className={styles.field}>
            <label>Túnel configurado</label>
            <select
              className={styles.input}
              value={selectedTunnel}
              onChange={e => setSelectedTunnel(e.target.value)}
            >
              {tunnels.map(tunnel => (
                <option key={tunnel.tunnel_id} value={tunnel.tunnel_id}>
                  {tunnel.tunnel_code ? `${tunnel.tunnel_code} — ` : ''}{tunnel.tunnel_desc || `Túnel ${tunnel.tunnel_id}`}
                </option>
              ))}
            </select>
            <span className={styles.inputNote}>
              A configuração das antenas é guardada na tabela `RFIDTunnels` do túnel selecionado.
            </span>
          </div>
        </div>
      </Card>

      {/* Ligação */}
      <Card>
        <CardTitle>Ligação ao leitor</CardTitle>
        <div className={styles.row}>
          <div className={styles.field}>
            <label>IP do leitor</label>
            <input
              className={styles.input}
              value={cfg.host}
              onChange={e => setCfg(p => ({ ...p, host: e.target.value }))}
            />
          </div>
          <div className={styles.field} style={{maxWidth:140}}>
            <label>Porta TCP</label>
            <input
              className={styles.input}
              type="number"
              value={cfg.port}
              onChange={e => setCfg(p => ({ ...p, port: parseInt(e.target.value) || 5084 }))}
            />
          </div>
        </div>
      </Card>

      <Card>
        <CardTitle>Identificação do posto</CardTitle>
        <div className={styles.row}>
          <div className={styles.field}>
            <label>MAC / identificador do posto</label>
            <input
              className={styles.input}
              value={stationCfg.station_identifier}
              onChange={e => setStationCfg({ station_identifier: e.target.value })}
              placeholder="Ex: 00-1A-2B-3C-4D-5E"
            />
            <span className={styles.inputNote}>
              Introduz o valor de `Posts.Post` deste posto. Fica guardado neste browser/posto e é enviado ao backend em cada impressão.
            </span>
          </div>
        </div>
      </Card>

      {/* Antenas */}
      <Card>
        <CardTitle>Configuração das antenas</CardTitle>
        <p className={styles.hint}>
          Potência TX em dBm × 100 — ex: 3000 = 30.00 dBm · 0 = máximo do leitor
        </p>
        <div className={styles.antennaGrid}>
          {cfg.antennas.map((ant, idx) => (
            <div key={ant.antenna} className={`${styles.antennaCard} ${ant.enabled ? styles.antennaEnabled : styles.antennaDisabled}`}>
              <div className={styles.antennaHeader}>
                <span className={styles.antennaTitle}>Antena {ant.antenna}</span>
                <label className={styles.toggle}>
                  <input
                    type="checkbox"
                    checked={ant.enabled}
                    onChange={e => updateAntenna(idx, 'enabled', e.target.checked)}
                  />
                  <span className={styles.toggleTrack}>
                    <span className={styles.toggleThumb} />
                  </span>
                  <span className={styles.toggleLabel}>{ant.enabled ? 'Ativa' : 'Inativa'}</span>
                </label>
              </div>

              <div className={styles.antennaFields}>
                <div className={styles.field}>
                  <label>Potência TX (dBm × 100)</label>
                  <input
                    className={styles.input}
                    type="number"
                    min="0"
                    max="9000"
                    step="100"
                    value={ant.tx_power}
                    disabled={!ant.enabled}
                    onChange={e => updateAntenna(idx, 'tx_power', parseInt(e.target.value) || 0)}
                  />
                  <span className={styles.inputNote}>
                    {ant.tx_power > 0 ? `${(ant.tx_power / 100).toFixed(2)} dBm` : 'Máximo do leitor'}
                  </span>
                </div>

                <div className={styles.field}>
                  <label>Sensibilidade RX</label>
                  <input
                    className={styles.input}
                    type="number"
                    min="0"
                    max="100"
                    value={ant.rx_sensitivity}
                    disabled={!ant.enabled}
                    onChange={e => updateAntenna(idx, 'rx_sensitivity', parseInt(e.target.value) || 0)}
                  />
                  <span className={styles.inputNote}>
                    {ant.rx_sensitivity === 0 ? 'Valor por defeito' : `Índice ${ant.rx_sensitivity}`}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <div className={styles.actions}>
        <Btn variant="success" loading={saving} onClick={save}>
          Guardar configuração
        </Btn>
        <p className={styles.saveNote}>O identificador do posto fica guardado localmente neste browser.</p>
      </div>
    </div>
  )
}
