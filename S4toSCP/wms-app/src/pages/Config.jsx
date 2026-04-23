import { useState, useEffect } from 'react'
import { useToast } from '../context/ToastContext'
import { Card, CardTitle, Btn, Spinner } from '../components/ui'
import styles from './Config.module.css'

const API = '/api'

export default function Config() {
  const toast   = useToast()
  const [cfg, setCfg]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)

  useEffect(() => {
    fetch(`${API}/config/rfid`)
      .then(r => r.json())
      .then(setCfg)
      .catch(() => toast('Erro ao carregar configuração', 'error'))
      .finally(() => setLoading(false))
  }, [])

  const updateAntenna = (idx, field, value) => {
    setCfg(prev => ({
      ...prev,
      antennas: prev.antennas.map((a, i) =>
        i === idx ? { ...a, [field]: value } : a
      )
    }))
  }

  const save = async () => {
    setSaving(true)
    try {
      await fetch(`${API}/config/rfid`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      })
      toast('Configuração guardada — reinicia o backend para aplicar')
    } catch { toast('Erro ao guardar configuração', 'error') }
    finally { setSaving(false) }
  }

  if (loading) return <div className={styles.center}><Spinner size={32} /></div>
  if (!cfg)    return null

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Configuração RFID</h1>
        <p className={styles.pageDesc}>Zebra FX7500 — {cfg.host}:{cfg.port}</p>
      </div>

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
        <p className={styles.saveNote}>Após guardar reinicia o backend para aplicar as alterações</p>
      </div>
    </div>
  )
}
