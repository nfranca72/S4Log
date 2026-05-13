import { useState, useEffect, useRef, useCallback } from 'react'
import { useToast } from '../context/ToastContext'
import { Card, CardTitle, Btn, Spinner } from '../components/ui'
import styles from './Module2.module.css'

const API = import.meta.env.VITE_API_URL ?? '/api'

function rfidWebSocketBase() {
  const base = import.meta.env.VITE_API_URL ?? `${window.location.protocol}//${window.location.host}/api`
  return base.replace(/^http/, 'ws').replace(/\/$/, '')
}

function statusInfo(s) {
  if (s === 'conferida')  return { label: 'Conferida',       color: 'var(--green)',  bg: 'rgba(52,211,153,.12)' }
  if (s === 'incidencia') return { label: 'Com incidências', color: 'var(--yellow)', bg: 'rgba(251,191,36,.12)' }
  if (s === 'parcial')    return { label: 'Parcial',         color: 'var(--accent)', bg: 'rgba(79,142,247,.12)' }
  return                          { label: 'Pendente',       color: 'var(--text3)',  bg: 'transparent' }
}

function tunnelLabel(tunnel, index) {
  const base = String.fromCharCode(65 + index)
  return tunnel?.tunnel_code ? `${base} - ${tunnel.tunnel_code}` : base
}

export default function Module2() {
  const toast = useToast()

  // ── Fase 1: leitura inicial ───────────────────────────────────────────────
  const [phase, setPhase]           = useState('scan')   // scan | conference
  const [scanInput, setScanInput]   = useState('')
  const [scanning, setScanning]     = useState(false)
  const scanInputRef                = useRef(null)

  // ── Packing + boxes ───────────────────────────────────────────────────────
  const [packing, setPacking]       = useState(null)
  const [boxes, setBoxes]           = useState([])
  const [activeBox, setActiveBox]   = useState(null)
  const [activeVolNum, setActiveVolNum] = useState(null)
  const boxRefs                     = useRef({})

  // ── Warehouse / location ──────────────────────────────────────────────────
  const [warehouses, setWarehouses] = useState([])
  const [locations, setLocations]   = useState([])
  const [whId, setWhId]             = useState('')
  const [locationId, setLocationId] = useState('')

  // ── Conference ────────────────────────────────────────────────────────────
  const [activeItem, setActiveItem] = useState(null)
  const [itemQtys, setItemQtys]     = useState({})
  const [itemTags, setItemTags]     = useState({})
  const [confirming, setConfirming] = useState(false)
  const [canceling, setCanceling]   = useState(false)
  const [testMode, setTestMode]     = useState(false)
  const [manualQty, setManualQty]   = useState('')
  const [rfidCount, setRfidCount]   = useState(0)
  const rfidTagsRef = useRef([])      // tags do ciclo actual
  const wsRef                       = useRef(null)

  // ── Load warehouses on mount ──────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API}/warehouses`).then(r => r.json()).then(setWarehouses).catch(() => {})
    // Focus scan input
    setTimeout(() => scanInputRef.current?.focus(), 100)
  }, [])

  useEffect(() => {
    if (!whId) { setLocations([]); setLocationId(''); return }
    fetch(`${API}/warehouses/${whId}/locations`).then(r => r.json()).then(setLocations).catch(() => {})
  }, [whId])

  // ── Scroll to active box ──────────────────────────────────────────────────
  useEffect(() => {
    if (activeVolNum && boxRefs.current[activeVolNum]) {
      boxRefs.current[activeVolNum].scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [activeVolNum, boxes])

  // ── Scan barcode → find packing ───────────────────────────────────────────
  const handleScan = async (barcode) => {
    if (!barcode.trim()) return
    setScanning(true)
    try {
      const found = await fetch(`${API}/packing/by-barcode/${barcode.trim()}`).then(r => {
        if (!r.ok) throw new Error()
        return r.json()
      })

      // Load boxes
      const boxList = await fetch(`${API}/packing/${found.order_id}/boxes`).then(r => r.json())

      setPacking(found)
      setBoxes(boxList)
      setActiveVolNum(found.vol_num)
      setPhase('conference')

      // Auto-open the scanned box
      await openBox(found.order_id, found.vol_num)

    } catch {
      toast(`Caixa "${barcode}" não encontrada em nenhum packing`, 'error')
      setScanInput('')
      scanInputRef.current?.focus()
    } finally {
      setScanning(false)
    }
  }

  // ── Open box detail ───────────────────────────────────────────────────────
  const openBox = async (orderId, volNum) => {
    // Não faz reset do RFID — o leitor continua a ler continuamente
    setActiveBox(null)
    setActiveItem(null)
    setItemQtys({})
    setItemTags({})

    try {
      const detail = await fetch(`${API}/packing/${orderId}/boxes/${volNum}`).then(r => r.json())

      setActiveVolNum(volNum)
      setActiveBox(detail)

      // Bloqueia caixas já verificadas
      if (detail.verified) {
        setActiveItem(null)
        toast('Caixa já verificada — apenas consulta disponível', 'error')
        return
      }

      if (detail.items.length === 1) {
        setActiveItem(detail.items[0])
        // Não inicia leitura — operador carrega "Nova leitura"
      } else {
        setActiveItem(null)
      }
    } catch { toast('Erro ao carregar caixa', 'error') }
  }

  // ── RFID ──────────────────────────────────────────────────────────────────
  const [rfidActive, setRfidActive] = useState(false)
  const rfidActiveRef = useRef(false)
  const [rfidStatus, setRfidStatus] = useState('idle')  // idle | reading | stopped
  const [selectedTunnel, setSelectedTunnel] = useState(1)
  const [tunnels, setTunnels] = useState([])

  useEffect(() => {
    rfidActiveRef.current = rfidActive
  }, [rfidActive])

  // Carrega túneis disponíveis ao iniciar
  useEffect(() => {
    fetch(`${API}/config/tunnels`).then(r => r.json()).then(d => {
      if (Array.isArray(d) && d.length) {
        setTunnels(d)
        setSelectedTunnel(d[0].tunnel_id)
      }
    }).catch(() => {})
  }, [])

  // Conecta WebSocket ao backend — não inicia leitura, só estabelece canal
  const connectRfid = (tunnelId) => {
    if (testMode) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return  // já ligado
    wsRef.current?.close()
    const wsBase = rfidWebSocketBase()
    const ws = new WebSocket(`${wsBase}/ws/rfid?tunnel_id=${tunnelId ?? selectedTunnel}`)
    ws.onopen = () => {
      setRfidStatus('idle')
    }
    ws.onmessage = e => {
      const d = JSON.parse(e.data)
      // "ready" = backend confirmou ligação
      // "reset" = backend confirmou nova leitura
      // "tags"  = tags novas detectadas — só actualiza se leitura activa
      if (d.type === 'tags' && rfidActiveRef.current) {
        setRfidCount(d.count ?? 0)
        rfidTagsRef.current = d.tags || []
      } else if (d.type === 'reset') {
        setRfidCount(0)
        rfidTagsRef.current = []
      }
    }
    ws.onerror = () => { toast('Erro na ligação RFID', 'error'); setRfidStatus('idle') }
    ws.onclose = () => { wsRef.current = null; setRfidStatus('idle') }
    wsRef.current = ws
  }

  // Garante WebSocket ligado — não reinicia leitura
  const startRfid = () => {
    if (testMode) return
    connectRfid(selectedTunnel)
  }

  // Nova Leitura — botão do operador
  // Limpa contagem local e envia "start" ao backend que reinicia os processos sllurp
  const hardResetRfid = () => {
    setRfidCount(0)
    setManualQty('')
    rfidTagsRef.current = []
    setRfidActive(true)
    setRfidStatus('reading')
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'reset' }))
    } else {
      // Conecta e envia start assim que ligar
      const wsBase = rfidWebSocketBase()
      const ws = new WebSocket(`${wsBase}/ws/rfid?tunnel_id=${selectedTunnel}`)
      ws.onopen = () => {
        ws.send(JSON.stringify({ action: 'reset' }))
        setRfidStatus('reading')
      }
      ws.onmessage = e => {
        const d = JSON.parse(e.data)
        if ((d.type === 'tags') && rfidActiveRef.current) {
          setRfidCount(d.count ?? 0)
          rfidTagsRef.current = d.tags || []
        } else if (d.type === 'reset') {
          setRfidCount(0)
          rfidTagsRef.current = []
        }
      }
      ws.onerror = () => { toast('Erro RFID', 'error'); setRfidStatus('idle') }
      ws.onclose = () => { wsRef.current = null; setRfidStatus('idle') }
      wsRef.current = ws
    }
  }

  // Para leitura — enviado quando operador confirma caixa
  const stopRfid = () => {
    setRfidActive(false)
    setRfidStatus('stopped')
    wsRef.current?.send(JSON.stringify({ action: 'stop' }))
  }


  const currentQty = testMode ? (parseInt(manualQty) || 0) : rfidCount

  // ── Select item to count ──────────────────────────────────────────────────
  const selectItem = (item) => {
    setActiveItem(item)
    // Não inicia leitura automaticamente — operador carrega "Nova leitura"
    startRfid()  // apenas garante WebSocket ligado
  }

  // ── Validate single item count ────────────────────────────────────────────
  const validateItem = () => {
    if (!activeItem) return
    const qty = currentQty
    const tags = [...rfidTagsRef.current]
    stopRfid()
    setItemQtys(prev => ({ ...prev, [activeItem.item_id]: qty }))
    setItemTags(prev => ({
      ...prev,
      [activeItem.item_id]: testMode ? [] : tags,
    }))
    setRfidStatus('idle')
    setRfidCount(0)
    setManualQty('')
    rfidTagsRef.current = []

    const remaining = activeBox.items.filter(
      i => i.item_id !== activeItem.item_id && !(i.item_id in itemQtys)
    )
    if (remaining.length > 0) {
      setActiveItem(remaining[0])
      // Não reinicia leitura — operador carrega "Nova leitura" para o próximo artigo
    } else {
      setActiveItem(null)
    }
  }

  const allDone = activeBox
    ? activeBox.items.every(i => i.item_id in { ...itemQtys, ...(activeItem ? { [activeItem.item_id]: currentQty } : {}) })
    : false

  // ── Confirm box ───────────────────────────────────────────────────────────
  const confirmBox = async () => {
    if (!whId || !locationId) { toast('Seleciona armazém e localização', 'error'); return }
    stopRfid()  // para leitura antes de confirmar
    setConfirming(true)
    const finalQtys = { ...itemQtys }
    if (activeItem) finalQtys[activeItem.item_id] = currentQty
    const finalItemTags = { ...itemTags }
    if (activeItem && !testMode) {
      finalItemTags[activeItem.item_id] = [...rfidTagsRef.current]
    }

    try {
      const res = await fetch(
        `${API}/packing/${packing.order_id}/boxes/${activeBox.vol_num}/confirm`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            wh_id: parseInt(whId),
            location_id: locationId,
            item_quantities: finalQtys,
            escp_order_id: packing?.escp_order_id || null,
            rfid_tags: rfidTagsRef.current,
            item_tags: finalItemTags,
          }),
        }
      ).then(r => r.json())

      toast(res.has_incident ? 'Caixa confirmada com incidências' : 'Caixa conferida com sucesso',
            res.has_incident ? 'error' : 'success')

      // Reload boxes
      const boxList = await fetch(`${API}/packing/${packing.order_id}/boxes`).then(r => r.json())
      setBoxes(boxList)
      setActiveBox(null)
      setActiveItem(null)
      setItemQtys({})
      setItemTags({})
      setRfidCount(0)

    } catch { toast('Erro ao confirmar caixa', 'error') }
    finally { setConfirming(false) }
  }

  // ── New scan ──────────────────────────────────────────────────────────────
  const cancelBoxConfirmation = async () => {
    if (!packing || !activeBox?.verified) return
    const ok = window.confirm('Anular a entrada desta caixa e retirar o stock associado?')
    if (!ok) return

    setCanceling(true)
    try {
      const res = await fetch(
        `${API}/packing/${packing.order_id}/boxes/${activeBox.vol_num}/cancel-confirmation`,
        { method: 'POST' }
      )
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Erro no servidor' }))
        throw new Error(err.detail || 'Erro ao anular entrada')
      }

      toast('Entrada da caixa anulada com sucesso', 'success')
      const boxList = await fetch(`${API}/packing/${packing.order_id}/boxes`).then(r => r.json())
      setBoxes(boxList)
      await openBox(packing.order_id, activeBox.vol_num)
      setItemQtys({})
      setItemTags({})
      setRfidCount(0)
    } catch (e) {
      toast(e.message || 'Erro ao anular entrada da caixa', 'error')
    } finally {
      setCanceling(false)
    }
  }

  const newScan = () => {
    setPhase('scan')
    setPacking(null)
    setBoxes([])
    setActiveBox(null)
    setActiveItem(null)
    setItemQtys({})
    setItemTags({})
    setScanInput('')
    setTimeout(() => scanInputRef.current?.focus(), 100)
  }

  // ── Packing totals ────────────────────────────────────────────────────────
  const verifiedBoxes = boxes.filter(b => b.status === 'conferida' || b.status === 'incidencia').length
  const totalQtyReceived = boxes
    .filter(b => b.status === 'conferida' || b.status === 'incidencia')
    .reduce((s, b) => s + (b.qty_received || 0), 0)
  const isFullyDone = boxes.length > 0 && verifiedBoxes === boxes.length

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className={styles.page}>

      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>Receção de Packing List</h1>
          <p className={styles.pageDesc}>Conferência de caixas com leitura RFID — Zebra 7500</p>
        </div>
      </div>

      {/* ── Barra de leitura — sempre visível no topo ── */}
      <Card>
        <div className={styles.topScanBar}>
          <div className={styles.topScanLabel}>
            <span className={styles.topScanIcon}>⬛</span>
            <span>Leitura de caixa</span>
          </div>
          <div className={styles.topScanInput}>
            <input
              ref={scanInputRef}
              className={styles.scanInputTop}
              type="text"
              placeholder="Lê o código de barras ou número interno da caixa..."
              value={scanInput}
              onChange={e => setScanInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleScan(scanInput)}
            />
            <Btn variant="primary" loading={scanning} onClick={() => handleScan(scanInput)}>
              {scanning ? '' : 'Pesquisar'}
            </Btn>
          </div>
        </div>
      </Card>

      {/* ── FASE 1: sem packing selecionado ── */}
      {phase === 'scan' && (
        <div className={styles.scanHintBox}>
          <div className={styles.scanIcon}>📦</div>
          <p className={styles.scanDesc}>Aponta o scanner para o código de barras na caixa para iniciar a conferência.<br/>Podes usar o número interno (VolNum) ou o código do cliente (VolNum2N).</p>
        </div>
      )}

      {/* ── FASE 2: Conference ── */}
      {phase === 'conference' && packing && (
        <>
          {/* Warehouse + Location + test mode */}
          <Card>
            <CardTitle>Armazém e localização</CardTitle>
            <div className={styles.whRow}>
              <div className={styles.whField}>
                <label>Armazém *</label>
                <select value={whId} onChange={e => setWhId(e.target.value)} className={styles.select}>
                  <option value="">Selecionar...</option>
                  {warehouses.map(w => <option key={w.wh_id} value={w.wh_id}>{w.wh_desc}</option>)}
                </select>
              </div>
              <div className={styles.whField}>
                <label>Localização *</label>
                <select value={locationId} onChange={e => setLocationId(e.target.value)} className={styles.select} disabled={!whId}>
                  <option value="">Selecionar...</option>
                  {locations.map(l => <option key={l.location_id} value={l.location_id}>{l.location_id} — {l.location_desc}</option>)}
                </select>
              </div>
              <label className={styles.testToggle}>
                <input type="checkbox" checked={testMode} onChange={e => setTestMode(e.target.checked)} />
                <span>Modo teste</span>
              </label>
            </div>
          </Card>

          {/* Totals banner */}
          <div className={`${styles.totalsBanner} ${isFullyDone ? styles.totalsDone : ''}`}>
            {isFullyDone ? (
              <div className={styles.conferidoLabel}>PACKING CONFERIDO ✓</div>
            ) : (
              <>
                <div className={styles.totalsBlock}>
                  <span className={styles.totalsVal}>{packing.total_qty}</span>
                  <span className={styles.totalsLabel}>peças no packing</span>
                </div>
                <div className={styles.totalsDivider} />
                <div className={styles.totalsBlock}>
                  <span className={styles.totalsVal} style={{ color: 'var(--green)' }}>{totalQtyReceived}</span>
                  <span className={styles.totalsLabel}>peças recebidas</span>
                </div>
                <div className={styles.totalsDivider} />
                <div className={styles.totalsBlock}>
                  <span className={styles.totalsVal}>{verifiedBoxes}<span style={{fontSize:24,color:'var(--text3)'}}> / {boxes.length}</span></span>
                  <span className={styles.totalsLabel}>caixas conferidas</span>
                </div>
                <div className={styles.packingInfo}>
                  <span className={styles.packingId}>Packing #{packing.order_id}</span>
                  <span className={styles.packingClient}>{packing.client_id}</span>
                  {packing.delivery_date && <span className={styles.packingDate}>{packing.delivery_date}</span>}
                </div>
              </>
            )}
          </div>

          <div className={styles.layout}>

            {/* LEFT: boxes list */}
            <div className={styles.leftPanel}>
              <Card>
                <CardTitle>Caixas do packing</CardTitle>
                <div className={styles.boxList}>
                  {boxes.map(b => {
                    const s = statusInfo(b.status)
                    const isActive = activeBox?.vol_num === b.vol_num
                    return (
                      <div
                        key={b.vol_num}
                        ref={el => boxRefs.current[b.vol_num] = el}
                        className={`${styles.boxItem} ${isActive ? styles.boxActive : ''}`}
                        style={{ borderLeft: `3px solid ${isActive ? 'var(--accent)' : s.color}` }}
                        onClick={() => openBox(packing.order_id, b.vol_num)}
                      >
                        <div className={styles.boxTop}>
                          <span className={styles.boxBarcode}>{b.barcode}</span>
                          <span className={styles.boxStatusBadge} style={{ background: s.bg, color: s.color }}>
                            {s.label}
                          </span>
                        </div>
                        <div className={styles.boxMeta}>
                          {b.total_items} art. · {b.qty_expected} pcs
                        </div>
                      </div>
                    )
                  })}
                </div>
              </Card>
            </div>

            {/* RIGHT: box detail + conference */}
            <div className={styles.rightPanel}>

              {!activeBox && (
                <div className={styles.emptyBox}>
                  <div className={styles.emptyIcon}>📦</div>
                  <p>Seleciona uma caixa ou lê o código de barras</p>
                </div>
              )}

              {activeBox && (
                <>
                  {/* Box header */}
                  <Card>
                    <div className={styles.boxHeader}>
                      <div>
                        <div className={styles.boxHeaderTitle}>Caixa {activeBox.barcode}</div>
                        <div className={styles.boxHeaderSub}>
                          {activeBox.items.length} artigo(s) — Vol. {activeBox.vol_num}
                        </div>
                      </div>
                      {activeBox.verified && (
                        <span className={styles.verifiedBadge}>
                          {activeBox.status.includes('INCIDENCIA') ? '⚠ Com incidências' : '✓ Conferida'}
                        </span>
                      )}
                    </div>
                  </Card>

                  {activeBox.verified && (
                    <div style={{marginTop:-12,marginBottom:12,display:'flex',justifyContent:'flex-end'}}>
                      <Btn variant="outline" loading={canceling} onClick={cancelBoxConfirmation}>
                        Anular entrada da caixa
                      </Btn>
                    </div>
                  )}

                  {/* Multi-article alert */}
                  {activeBox.items.length > 1 && !activeItem && Object.keys(itemQtys).length < activeBox.items.length && (
                    <div className={styles.multiAlert}>
                      Esta caixa tem <strong>{activeBox.items.length}</strong> artigos diferentes.
                      Seleciona um artigo para iniciar a contagem.
                    </div>
                  )}

                  {/* Articles table */}
                  <Card>
                    <CardTitle>Conteúdo da caixa</CardTitle>
                    <div className={styles.tableWrap}>
                      <table className={styles.table}>
                        <thead>
                          <tr>
                            <th>Artigo</th>
                            <th>Descrição</th>
                            <th>Tam.</th>
                            <th style={{textAlign:'right'}}>Qtd. inicial</th>
                            <th style={{textAlign:'right'}}>Qtd. conferida</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {activeBox.items.map(item => {
                            const isDone   = item.item_id in itemQtys
                            const isActive = activeItem?.item_id === item.item_id
                            const qtyDone  = itemQtys[item.item_id]
                            const qtyOk    = isDone && qtyDone >= item.qty_expected

                            return (
                              <tr
                                key={item.item_id}
                                className={`${isActive ? styles.rowActive : ''} ${isDone ? styles.rowDone : ''}`}
                                onClick={() => !isDone && !activeBox.verified && selectItem(item)}
                                style={{ cursor: isDone || activeBox.verified ? 'default' : 'pointer' }}
                              >
                                <td className={styles.mono} style={{fontSize:15}}>{item.item_id}</td>
                                <td className={styles.tdDesc}>{item.item_desc}</td>
                                <td className={styles.mono} style={{fontSize:15}}>{item.size_id}</td>
                                <td className={styles.mono} style={{textAlign:'right',fontSize:18,fontWeight:600}}>{item.qty_expected}</td>
                                <td style={{textAlign:'right'}}>
                                  {isDone
                                    ? <span className={`${styles.mono} ${qtyOk ? styles.qtyGreen : styles.qtyYellow}`}>
                                        {qtyDone}
                                      </span>
                                    : activeBox.verified
                                      ? <span className={`${styles.mono} ${item.qty_read >= item.qty_expected ? styles.qtyGreen : styles.qtyYellow}`}>
                                          {item.qty_read}
                                        </span>
                                    : isActive
                                      ? <span className={`${styles.mono} ${styles.qtyReading}`}>{currentQty}</span>
                                      : <span className={styles.mono} style={{color:'var(--text3)'}}>—</span>
                                  }
                                </td>
                                <td>
                                  {isActive && <span className={styles.activePill}>A contar</span>}
                                  {isDone && <span className={styles.donePill}>✓</span>}
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  </Card>

                  {/* RFID counter (só quando há artigo ativo) */}
                  {activeItem && !activeBox.verified && (
                    <Card>
                      <CardTitle>A contar — {activeItem.item_id}</CardTitle>
                      <div className={styles.rfidPanel}>
                        <div className={`${styles.rfidCount} ${
                          currentQty === 0                          ? styles.rfidZero    :
                          currentQty > activeItem.qty_expected      ? styles.rfidExcess  :
                          currentQty === activeItem.qty_expected    ? styles.rfidOk      : styles.rfidReading
                        }`}>
                          {currentQty}
                        </div>
                        <div className={styles.rfidExpected}>
                          esperado: <strong>{activeItem.qty_expected}</strong>
                        </div>

                        {testMode ? (
                          <input
                            type="number" min="0"
                            className={styles.manualField}
                            placeholder="Introduzir quantidade..."
                            value={manualQty}
                            onChange={e => setManualQty(e.target.value)}
                            autoFocus
                          />
                        ) : (
                          <>
                          <div className={styles.rfidStatus}>
                            {currentQty === 0
                              ? 'Coloca os artigos no tapete RFID...'
                              : currentQty >= activeItem.qty_expected
                                ? '✓ Quantidade atingida'
                                : 'A ler tags RFID...'}
                          </div>

                        </>
                        )}

                        <div className={styles.rfidActions}>
                          {tunnels.length > 1 && (
                            <select
                              value={selectedTunnel}
                              onChange={e => setSelectedTunnel(parseInt(e.target.value))}
                              style={{padding:'6px 10px',border:'1px solid var(--border)',borderRadius:'6px',background:'var(--bg)',color:'var(--text1)',fontSize:'13px'}}
                            >
                              {tunnels.map((t, index) => (
                                <option key={t.tunnel_id} value={t.tunnel_id}>
                                  {tunnelLabel(t, index)}
                                </option>
                              ))}
                            </select>
                          )}
                        <div style={{display:'flex',alignItems:'center',gap:'8px',flexWrap:'wrap'}}>
                          <Btn variant="outline" onClick={hardResetRfid}>▶ Nova leitura</Btn>
                          <span style={{
                            fontSize:'12px', fontWeight:500,
                            color: rfidStatus==='reading' ? '#16a34a' : rfidStatus==='stopped' ? '#d97706' : 'var(--text3)'
                          }}>
                            {rfidStatus==='reading' ? '● A ler...' : rfidStatus==='stopped' ? '■ Parado' : '○ Aguarda'}
                          </span>
                        </div>
                          <Btn
                            variant={currentQty >= activeItem.qty_expected ? 'success' : 'primary'}
                            onClick={validateItem}
                            disabled={currentQty === 0}
                          >
                            {currentQty >= activeItem.qty_expected ? '✓ Confirmar artigo' : 'Aceitar com incidência'}
                          </Btn>
                        </div>
                      </div>
                    </Card>
                  )}

                  {/* Confirm box */}
                  {allDone && !activeItem && !activeBox.verified && (
                    <div className={styles.confirmRow}>
                      <Btn
                        variant="success"
                        loading={confirming}
                        onClick={confirmBox}
                        disabled={!whId || !locationId}
                      >
                        Confirmar caixa e dar entrada em stock →
                      </Btn>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
