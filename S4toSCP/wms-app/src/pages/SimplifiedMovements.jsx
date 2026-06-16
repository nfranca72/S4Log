import { useState, useEffect, useCallback, useRef } from 'react'
import { useToast } from '../context/ToastContext'
import { Card, CardTitle, Btn, Steps, Spinner } from '../components/ui'
import styles from './SimplifiedMovements.module.css'

const API = import.meta.env.VITE_API_URL ?? '/api'

function resolveApiBases() {
  const bases = [API]

  // In local development, fall back to the backend directly if the Vite proxy fails.
  if (
    API === '/api' &&
    typeof window !== 'undefined' &&
    ['localhost', '127.0.0.1'].includes(window.location.hostname)
  ) {
    bases.push('http://127.0.0.1:8000/api')
  }

  return [...new Set(bases)]
}

async function readError(res) {
  const body = await res.json().catch(() => ({ detail: `Erro HTTP ${res.status}` }))
  return new Error(body.detail || 'Erro no servidor')
}

async function apiFetch(path, opts = {}) {
  let lastError = null

  for (const base of resolveApiBases()) {
    try {
      const res = await fetch(`${base}${path}`, opts)
      if (!res.ok) {
        lastError = await readError(res)
        continue
      }
      return res.json()
    } catch (error) {
      lastError = error
    }
  }

  throw lastError || new Error('Erro no servidor')
}

// ── Step labels ────────────────────────────────────────────────────────────────
const STEP_LABELS = ['Tipo', 'Parceiro', 'Documento', 'Artigos', 'Armazém', 'Confirmar']
const STEP_IDS    = ['type', 'partner',  'document',  'items',   'warehouse', 'confirm']

// ── Movement type badge ────────────────────────────────────────────────────────
function MovTypeBadge({ movType }) {
  if (!movType) return null
  const isTransfer = movType.is_transfer
  const cls = isTransfer ? styles.badgeTransfer : styles.badgeExit
  const label = isTransfer ? 'Transferência' : 'Saída'
  return <span className={`${styles.typeBadge} ${cls}`}>{label}</span>
}

// ── Dimension grid component ───────────────────────────────────────────────────
function DimGrid({ grid, values, onChange }) {
  if (!grid || !grid.colors?.length) return null
  return (
    <div className={styles.dimGrid}>
      <table className={styles.dimTable}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left' }}>Cor \ Tam.</th>
            {grid.sizes.map(s => <th key={s}>{s}</th>)}
          </tr>
        </thead>
        <tbody>
          {grid.colors.map(color => (
            <tr key={color}>
              <td className={styles.dimColorLabel}>{color}</td>
              {grid.sizes.map(size => {
                const cell = grid.cells.find(c => c.color_id === color && c.size_id === size)
                const stock = cell?.qty_stock ?? 0
                const val   = values?.[`${color}__${size}`] ?? ''
                return (
                  <td key={size} className={styles.dimCell}>
                    <input
                      className={styles.dimCellInput}
                      type="number"
                      min="0"
                      max={stock}
                      value={val}
                      placeholder={stock > 0 ? String(Math.floor(stock)) : '—'}
                      disabled={stock <= 0}
                      onChange={e => onChange(color, size, e.target.value)}
                    />
                    <span className={styles.dimStockLabel}>{stock > 0 ? `est: ${stock}` : '—'}</span>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Lot selector ───────────────────────────────────────────────────────────────
function LotSelector({ lots, selectedLot, lotQty, onSelect, onQtyChange }) {
  return (
    <div className={styles.lotList}>
      {lots.length === 0 && (
        <div className={styles.empty}>
          <div className={styles.emptyText}>Nenhum lote com stock disponível</div>
        </div>
      )}
      {lots.map(lot => {
        const sel = selectedLot === lot.lot_id
        return (
          <div
            key={lot.lot_id}
            className={`${styles.lotItem} ${sel ? styles.selected : ''}`}
            onClick={() => onSelect(lot.lot_id)}
          >
            <div style={{ flex: 1 }}>
              <div className={styles.lotId}>{lot.lot_id}</div>
              <div className={styles.lotStock}>
                {lot.wh_desc || `Arm. ${lot.wh_id}`} · {lot.location_id} · {lot.qty_stock} un.
              </div>
            </div>
            {sel && (
              <input
                className={styles.lotQtyInput}
                type="number"
                min="1"
                max={lot.qty_stock}
                value={lotQty}
                placeholder="Qtd"
                onClick={e => e.stopPropagation()}
                onChange={e => onQtyChange(e.target.value)}
                autoFocus
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Volume selector ────────────────────────────────────────────────────────────
function VolumeSelector({ volumes, selected, onToggle }) {
  return (
    <div className={styles.lotList}>
      {volumes.length === 0 && (
        <div className={styles.empty}>
          <div className={styles.emptyText}>Nenhum volume com stock disponível</div>
        </div>
      )}
      {volumes.map(vol => {
        const sel = selected.includes(vol.vol_num)
        return (
          <div
            key={vol.vol_num}
            className={`${styles.volItem} ${sel ? styles.selected : ''}`}
            onClick={() => onToggle(vol.vol_num)}
          >
            <div className={styles.volCheckbox}>
              {sel && '✓'}
            </div>
            <div className={styles.volInfo}>
              <div className={styles.volNum}>
                Vol. {vol.vol_num}{vol.barcode ? ` · ${vol.barcode}` : ''}
              </div>
              <div className={styles.volMeta}>
                {vol.wh_desc || `Arm. ${vol.wh_id}`} · {vol.location_id} · {vol.qty_stock} un.
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function VolumeQtyEditor({ volume, value, onChange }) {
  if (!volume) return null

  return (
    <div className={styles.qtyRow} style={{ marginTop: 14 }}>
      <span className={styles.qtyLabel}>
        Quantidade para o volume {volume.vol_num} ({volume.qty_stock} em stock):
      </span>
      <input
        className={styles.qtyInput}
        type="number"
        min="0"
        max={volume.qty_stock}
        step="1"
        value={value}
        onChange={e => onChange(e.target.value)}
        autoFocus
      />
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function SimplifiedMovements() {
  const toast = useToast()

  // ── Wizard state ──────────────────────────────────────────────────────────────
  const [step, setStep] = useState('type')   // type | partner | document | items | warehouse | confirm | done

  // ── Type ──────────────────────────────────────────────────────────────────────
  const [movTypes, setMovTypes]   = useState([])
  const [movType,  setMovType]    = useState(null)
  const [loadingTypes, setLoadingTypes] = useState(true)

  // ── Partner ───────────────────────────────────────────────────────────────────
  const [partners, setPartners]       = useState([])
  const [partner,  setPartner]        = useState(null)
  const [partnerSearch, setPartnerSearch] = useState('')
  const [loadingPartners, setLoadingPartners] = useState(false)
  const partnerDebounce = useRef(null)

  // ── Document ──────────────────────────────────────────────────────────────────
  const [documents, setDocuments]       = useState([])
  const [document,  setDocument]        = useState(null)
  const [loadingDocs, setLoadingDocs]   = useState(false)

  // ── Items (cart) ──────────────────────────────────────────────────────────────
  const [docLines, setDocLines]         = useState([])     // lines from origin doc
  const [freeItems, setFreeItems]       = useState([])     // search results (no doc)
  const [itemSearch, setItemSearch]     = useState('')
  const [loadingLines, setLoadingLines] = useState(false)
  const itemDebounce = useRef(null)

  // Cart: [{item_id, item_desc, stk_unit, lines: [{color, size, lot, vol_num, qty, doc_row}]}]
  const [cart, setCart] = useState([])

  // Current item being configured
  const [activeItem, setActiveItem]     = useState(null)  // item info
  const [itemDimGrid, setItemDimGrid]   = useState(null)
  const [itemLots,    setItemLots]      = useState([])
  const [itemVolumes, setItemVolumes]   = useState([])
  const [loadingItemDetail, setLoadingItemDetail] = useState(false)

  // Dim grid values: {color__size: qty_string}
  const [dimValues, setDimValues] = useState({})
  // Lot selection
  const [selectedLot, setSelectedLot]   = useState('')
  const [lotQty,      setLotQty]        = useState('')
  // Volume selection
  const [selectedVols, setSelectedVols] = useState([])
  const [volumeQty, setVolumeQty]       = useState('')
  // Simple qty
  const [simpleQty, setSimpleQty]       = useState('')

  // ── Warehouse ─────────────────────────────────────────────────────────────────
  const [warehouses, setWarehouses]     = useState([])
  const [locations,  setLocations]      = useState({ orig: [], dest: [] })
  const [whOrig,     setWhOrig]         = useState('')
  const [locOrig,    setLocOrig]        = useState('')
  const [whDest,     setWhDest]         = useState('')
  const [locDest,    setLocDest]        = useState('')
  const [loadingWh,  setLoadingWh]      = useState(false)

  // ── Execute ───────────────────────────────────────────────────────────────────
  const [executing, setExecuting]       = useState(false)
  const [result,    setResult]          = useState(null)

  // ── Step index for Steps component ───────────────────────────────────────────
  const stepIndex = STEP_IDS.indexOf(step) + 1

  // ── Load movement types on mount ──────────────────────────────────────────────
  useEffect(() => {
    apiFetch('/simplified-movements/types')
      .then(setMovTypes)
      .catch((error) => toast(`Erro ao carregar tipos de movimento: ${error.message}`, 'error'))
      .finally(() => setLoadingTypes(false))
  }, [])

  // ── Load partners when entering partner step ──────────────────────────────────
  useEffect(() => {
    if (step !== 'partner' || !movType) return
    setLoadingPartners(true)
    apiFetch(`/simplified-movements/partners?partner_type=${movType.partner_type || 'C'}&search=`)
      .then(setPartners)
      .catch(() => toast('Erro ao carregar parceiros', 'error'))
      .finally(() => setLoadingPartners(false))
  }, [step, movType])

  // ── Debounced partner search ───────────────────────────────────────────────────
  useEffect(() => {
    if (step !== 'partner' || !movType) return
    clearTimeout(partnerDebounce.current)
    partnerDebounce.current = setTimeout(() => {
      setLoadingPartners(true)
      apiFetch(`/simplified-movements/partners?partner_type=${movType.partner_type || 'C'}&search=${encodeURIComponent(partnerSearch)}`)
        .then(setPartners)
        .catch(() => {})
        .finally(() => setLoadingPartners(false))
    }, 300)
  }, [partnerSearch])

  // ── Load documents when entering document step ────────────────────────────────
  useEffect(() => {
    if (step !== 'document' || !movType) return
    setLoadingDocs(true)
    const partnerId = partner?.partner_id || ''
    apiFetch(`/simplified-movements/documents?doc_type=${movType.doc_type}&partner_id=${encodeURIComponent(partnerId)}`)
      .then(setDocuments)
      .catch(() => toast('Erro ao carregar documentos', 'error'))
      .finally(() => setLoadingDocs(false))
  }, [step, movType, partner])

  // ── Load document lines when entering items step ──────────────────────────────
  useEffect(() => {
    if (step !== 'items') return
    setDocLines([])
    setFreeItems([])
    setActiveItem(null)

    if (document && movType) {
      setLoadingLines(true)
      apiFetch(
        `/simplified-movements/documents/${document.order_id}/lines?doc_type=${movType.doc_type}&with_components=${movType.has_components ? 1 : 0}`
      )
        .then(setDocLines)
        .catch(() => toast('Erro ao carregar linhas', 'error'))
        .finally(() => setLoadingLines(false))
    }
  }, [step, document, movType])

  // ── Debounced free-item search ────────────────────────────────────────────────
  useEffect(() => {
    if (step !== 'items' || document) return
    clearTimeout(itemDebounce.current)
    if (!itemSearch || itemSearch.length < 2) { setFreeItems([]); return }
    itemDebounce.current = setTimeout(() => {
      apiFetch(`/simplified-movements/items?search=${encodeURIComponent(itemSearch)}`)
        .then(setFreeItems)
        .catch(() => {})
    }, 300)
  }, [itemSearch, step, document])

  // ── Load warehouses when entering warehouse step ──────────────────────────────
  useEffect(() => {
    if (step !== 'warehouse' || !movType) return
    setLoadingWh(true)
    apiFetch(`/simplified-movements/warehouses?doc_type=${movType.doc_type}`)
      .then(setWarehouses)
      .catch(() => toast('Erro ao carregar armazéns', 'error'))
      .finally(() => setLoadingWh(false))
  }, [step, movType])

  // ── Load origin locations ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!whOrig) { setLocations(l => ({ ...l, orig: [] })); setLocOrig(''); return }
    apiFetch(`/simplified-movements/warehouses/${whOrig}/locations`)
      .then(rows => setLocations(l => ({ ...l, orig: rows })))
      .catch(() => {})
  }, [whOrig])

  // ── Load destination locations ────────────────────────────────────────────────
  useEffect(() => {
    if (!whDest) { setLocations(l => ({ ...l, dest: [] })); setLocDest(''); return }
    apiFetch(`/simplified-movements/warehouses/${whDest}/locations`)
      .then(rows => setLocations(l => ({ ...l, dest: rows })))
      .catch(() => {})
  }, [whDest])

  // ── Select a movement type ─────────────────────────────────────────────────────
  const handleSelectType = useCallback((mt) => {
    setMovType(mt)
    setPartner(null)
    setDocument(null)
    setCart([])
    setActiveItem(null)

    if (mt.allow_business_partner && mt.partner_type) {
      setStep('partner')
    } else if (mt.force_orig_doc) {
      setStep('document')
    } else {
      setStep('items')
    }
  }, [])

  // ── Select partner ─────────────────────────────────────────────────────────────
  const handleSelectPartner = useCallback((p) => {
    setPartner(p)
    setDocument(null)
    setCart([])

    if (movType?.force_orig_doc) {
      setStep('document')
    } else {
      setStep('items')
    }
  }, [movType])

  // ── Select document ────────────────────────────────────────────────────────────
  const handleSelectDocument = useCallback((doc) => {
    setDocument(doc)
    setCart([])
    setStep('items')
  }, [])

  // ── Open item detail (dims / lots / volumes / simple qty) ─────────────────────
  const openItemDetail = useCallback(async (item) => {
    setActiveItem(item)
    setDimValues({})
    setSelectedLot('')
    setLotQty('')
    setSelectedVols([])
    setVolumeQty('')
    setSimpleQty('')
    setItemDimGrid(null)
    setItemLots([])
    setItemVolumes([])

    setLoadingItemDetail(true)
    try {
      if (item.has_dims) {
        const grid = await apiFetch(`/simplified-movements/items/${item.item_id}/dim-stock`)
        setItemDimGrid(grid)
      } else if (item.has_lots) {
        const lots = await apiFetch(`/simplified-movements/items/${item.item_id}/lots`)
        setItemLots(lots)
      } else if (item.has_volumes) {
        const vols = await apiFetch(`/simplified-movements/items/${item.item_id}/volumes`)
        setItemVolumes(vols)
      }
    } catch {
      toast('Erro ao carregar detalhe do artigo', 'error')
    } finally {
      setLoadingItemDetail(false)
    }
  }, [toast])

  // ── Dim grid cell change ───────────────────────────────────────────────────────
  const handleDimChange = useCallback((color, size, val) => {
    setDimValues(prev => ({ ...prev, [`${color}__${size}`]: val }))
  }, [])

  // ── Add item to cart ───────────────────────────────────────────────────────────
  const addToCart = useCallback(() => {
    if (!activeItem) return
    const docRow = activeItem.order_row ?? null
    let newLines = []

    if (activeItem.has_dims && itemDimGrid) {
      // Dim grid: one line per color/size with qty > 0
      for (const [key, val] of Object.entries(dimValues)) {
        const qty = parseFloat(val)
        if (!val || isNaN(qty) || qty <= 0) continue
        const [color, size] = key.split('__')
        newLines.push({ color_id: color, size_id: size, lot_id: '', vol_num: null, qty, doc_row: docRow })
      }
      if (!newLines.length) { toast('Introduce pelo menos uma quantidade', 'error'); return }
    } else if (activeItem.has_lots) {
      if (!selectedLot) { toast('Seleciona um lote', 'error'); return }
      const qty = parseFloat(lotQty)
      if (!qty || qty <= 0) { toast('Introduce uma quantidade válida', 'error'); return }
      newLines.push({ color_id: '', size_id: '', lot_id: selectedLot, vol_num: null, qty, doc_row: docRow })
    } else if (activeItem.has_volumes) {
      if (!selectedVols.length) { toast('Seleciona um volume', 'error'); return }
      const vol = itemVolumes.find(v => v.vol_num === selectedVols[0])
      const qty = parseFloat(volumeQty)
      if (!qty || qty <= 0) { toast('Introduce uma quantidade válida', 'error'); return }
      if (vol && qty > vol.qty_stock) {
        toast(`A quantidade não pode exceder o stock do volume (${vol.qty_stock})`, 'error')
        return
      }
      newLines.push({ color_id: '', size_id: '', lot_id: '', vol_num: selectedVols[0], qty, doc_row: docRow })
    } else {
      const qty = parseFloat(simpleQty)
      if (!qty || qty <= 0) { toast('Introduce uma quantidade válida', 'error'); return }
      newLines.push({ color_id: '', size_id: '', lot_id: '', vol_num: null, qty, doc_row: docRow })
    }

    setCart(prev => {
      const existing = prev.findIndex(c => c.item_id === activeItem.item_id)
      if (existing >= 0) {
        const updated = [...prev]
        updated[existing] = { ...updated[existing], lines: [...updated[existing].lines, ...newLines] }
        return updated
      }
      return [...prev, {
        item_id:   activeItem.item_id,
        item_desc: activeItem.item_desc || '',
        stk_unit:  activeItem.stk_unit || 'UN',
        lines:     newLines,
      }]
    })

    setActiveItem(null)
    toast('Artigo adicionado', 'success')
  }, [activeItem, dimValues, selectedLot, lotQty, selectedVols, volumeQty, simpleQty, itemDimGrid, itemVolumes, toast])

  // ── Remove cart item ───────────────────────────────────────────────────────────
  const removeFromCart = useCallback((itemId) => {
    setCart(prev => prev.filter(c => c.item_id !== itemId))
  }, [])

  // ── Execute movement ───────────────────────────────────────────────────────────
  const handleExecute = useCallback(async () => {
    if (!whOrig || !locOrig) { toast('Seleciona armazém e localização de origem', 'error'); return }
    if (movType?.is_transfer && (!whDest || !locDest)) {
      toast('Seleciona armazém e localização de destino', 'error'); return
    }
    if (!cart.length) { toast('Nenhum artigo no movimento', 'error'); return }

    const lines = cart.flatMap(item =>
      item.lines.map(l => ({
        item_id:     item.item_id,
        color_id:    l.color_id || '',
        size_id:     l.size_id  || '',
        lot_id:      l.lot_id   || '',
        vol_num:     l.vol_num  ?? null,
        qty:         l.qty,
        unit_value:  0,
        doc_row:     l.doc_row  ?? null,
      }))
    )

    setExecuting(true)
    try {
      const res = await apiFetch('/simplified-movements/execute', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          doc_type:         movType.doc_type,
          order_id:         document?.order_id ?? null,
          partner_id:       partner?.partner_id ?? null,
          wh_id_orig:       parseInt(whOrig),
          location_id_orig: locOrig,
          wh_id_dest:       movType.is_transfer ? parseInt(whDest) : null,
          location_id_dest: movType.is_transfer ? locDest : null,
          obs:              '',
          lines,
        }),
      })
      setResult(res)
      setStep('done')
    } catch (e) {
      toast(e.message || 'Erro ao executar movimento', 'error')
    } finally {
      setExecuting(false)
    }
  }, [movType, document, partner, whOrig, locOrig, whDest, locDest, cart, toast])

  // ── Reset ──────────────────────────────────────────────────────────────────────
  const reset = useCallback(() => {
    setStep('type')
    setMovType(null)
    setPartner(null)
    setDocument(null)
    setCart([])
    setActiveItem(null)
    setResult(null)
    setWhOrig(''); setLocOrig(''); setWhDest(''); setLocDest('')
    setPartnerSearch(''); setItemSearch('')
  }, [])

  // ── Determine visible steps ────────────────────────────────────────────────────
  const visibleSteps = (() => {
    if (!movType) return STEP_LABELS
    const steps = ['Tipo']
    if (movType.allow_business_partner && movType.partner_type) steps.push('Parceiro')
    if (movType.force_orig_doc) steps.push('Documento')
    steps.push('Artigos', 'Armazém', 'Confirmar')
    return steps
  })()

  // ── Step number for Steps indicator ───────────────────────────────────────────
  const currentStepNum = (() => {
    const map = { type: 1 }
    let n = 2
    if (movType?.allow_business_partner && movType?.partner_type) { map.partner = n; n++ }
    if (movType?.force_orig_doc) { map.document = n; n++ }
    map.items = n; n++
    map.warehouse = n; n++
    map.confirm = n
    return map[step] ?? 1
  })()

  // ── Total cart qty ─────────────────────────────────────────────────────────────
  const cartTotal = cart.reduce((s, c) => s + c.lines.reduce((ls, l) => ls + l.qty, 0), 0)

  // ──────────────────────────────────────────────────────────────────────────────
  return (
    <div className={styles.page}>

      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Movimentos Simplificados</h1>
        <p className={styles.pageDesc}>Saídas e transferências de stock</p>
      </div>

      {/* ── Steps indicator (hidden on type selection and done) ── */}
      {step !== 'type' && step !== 'done' && (
        <Steps steps={visibleSteps} current={currentStepNum} />
      )}

      {/* ════ STEP: type ════════════════════════════════════════════════════════ */}
      {step === 'type' && (
        <Card>
          <CardTitle>Seleciona o tipo de movimento</CardTitle>
          {loadingTypes ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spinner /></div>
          ) : movTypes.length === 0 ? (
            <div className={styles.empty}>
              <div className={styles.emptyIcon}>⚙️</div>
              <div className={styles.emptyText}>
                Nenhum tipo de movimento configurado.<br />
                Ativa <code>IsSimplifiedMovement = 1</code> em <strong>DocumentConfig</strong>.
              </div>
            </div>
          ) : (
            <div className={styles.typeGrid}>
              {movTypes.map(mt => (
                <button
                  key={mt.doc_type}
                  className={styles.typeCard}
                  onClick={() => handleSelectType(mt)}
                >
                  <div className={styles.typeCardIcon}>
                    {mt.is_transfer ? '↔️' : '📤'}
                  </div>
                  <div className={styles.typeCardTitle}>{mt.title}</div>
                  {mt.doc_desc && (
                    <div className={styles.typeCardDesc}>{mt.doc_desc}</div>
                  )}
                  <MovTypeBadge movType={mt} />
                </button>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ════ STEP: partner ═════════════════════════════════════════════════════ */}
      {step === 'partner' && (
        <Card>
          <CardTitle>
            {movType?.partner_type === 'F' ? 'Seleciona fornecedor' :
             movType?.partner_type === 'S' ? 'Seleciona subcontratado' : 'Seleciona cliente'}
          </CardTitle>
          <div className={styles.searchBar}>
            <input
              className={styles.searchInput}
              type="text"
              placeholder="Pesquisar por nome ou código..."
              value={partnerSearch}
              onChange={e => setPartnerSearch(e.target.value)}
              autoFocus
            />
          </div>
          {loadingPartners ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spinner /></div>
          ) : (
            <div className={styles.list}>
              {partners.map(p => (
                <button
                  key={p.partner_id}
                  className={styles.listItem}
                  onClick={() => handleSelectPartner(p)}
                >
                  <div className={styles.listItemMain}>
                    <div className={styles.listItemTitle}>{p.partner_name}</div>
                    <div className={styles.listItemSub}>{p.partner_id}</div>
                  </div>
                  <span className={styles.listItemArrow}>›</span>
                </button>
              ))}
              {partners.length === 0 && !loadingPartners && (
                <div className={styles.empty}>
                  <div className={styles.emptyText}>Nenhum resultado</div>
                </div>
              )}
            </div>
          )}
          <div className={styles.actions} style={{ marginTop: 16 }}>
            <Btn variant="outline" onClick={() => setStep('type')}>← Voltar</Btn>
          </div>
        </Card>
      )}

      {/* ════ STEP: document ════════════════════════════════════════════════════ */}
      {step === 'document' && (
        <Card>
          <CardTitle>Seleciona o documento de origem</CardTitle>

          {partner && (
            <div className={styles.contextBar}>
              <span className={styles.contextChip}>
                {partner.partner_name}
                <button className={styles.contextChipBtn} onClick={() => { setPartner(null); setStep('partner') }}>×</button>
              </span>
            </div>
          )}

          {loadingDocs ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spinner /></div>
          ) : (
            <div className={styles.list}>
              {documents.map(doc => (
                <button
                  key={doc.order_id}
                  className={styles.listItem}
                  onClick={() => handleSelectDocument(doc)}
                >
                  <div className={styles.listItemMain}>
                    <div className={styles.listItemTitle}>
                      {doc.doc_type} #{doc.order_id}
                      {doc.obs ? ` · ${doc.obs}` : ''}
                    </div>
                    <div className={styles.listItemSub}>
                      {doc.order_date || '—'} · {doc.pending_lines} linha(s) pendente(s)
                    </div>
                  </div>
                  <span className={styles.listItemArrow}>›</span>
                </button>
              ))}
              {documents.length === 0 && !loadingDocs && (
                <div className={styles.empty}>
                  <div className={styles.emptyText}>Nenhum documento com pendentes</div>
                </div>
              )}
            </div>
          )}

          <div className={styles.actions} style={{ marginTop: 16 }}>
            <Btn variant="outline" onClick={() => setStep(movType?.allow_business_partner ? 'partner' : 'type')}>
              ← Voltar
            </Btn>
          </div>
        </Card>
      )}

      {/* ════ STEP: items ═══════════════════════════════════════════════════════ */}
      {step === 'items' && (
        <>
          {/* Context bar */}
          <div className={styles.contextBar}>
            {partner && (
              <span className={styles.contextChip}>{partner.partner_name}</span>
            )}
            {document && (
              <span className={styles.contextChip}>
                {document.doc_type} #{document.order_id}
              </span>
            )}
          </div>

          {/* Cart */}
          {cart.length > 0 && (
            <div className={styles.cartSection}>
              <div className={styles.cartHeader}>
                <span className={styles.cartTitle}>Artigos adicionados</span>
                <span className={styles.cartCount}>{cart.length} art. · {cartTotal} un.</span>
              </div>
              {cart.map(item => (
                <div key={item.item_id} className={styles.cartItem}>
                  <div className={styles.cartItemId}>{item.item_id}</div>
                  <div className={styles.cartItemDesc}>{item.item_desc}</div>
                  <div className={styles.cartItemQty}>
                    {item.lines.reduce((s, l) => s + l.qty, 0)} {item.stk_unit}
                  </div>
                  <button
                    className={styles.cartItemRemove}
                    onClick={() => removeFromCart(item.item_id)}
                    title="Remover"
                  >✕</button>
                </div>
              ))}
            </div>
          )}

          {/* Active item detail */}
          {activeItem && (
            <div className={styles.itemDetailCard}>
              <div className={styles.itemDetailTitle}>
                {activeItem.item_id}
                {activeItem.has_dims && <span className={styles.itemStockBadge}>Dimensões</span>}
                {activeItem.has_lots && <span className={styles.itemStockBadge}>Lotes</span>}
                {activeItem.has_volumes && <span className={styles.itemStockBadge}>Volumes</span>}
              </div>
              <div className={styles.itemDetailSub}>{activeItem.item_desc}</div>

              {loadingItemDetail ? (
                <div style={{ textAlign: 'center', padding: 20 }}><Spinner /></div>
              ) : activeItem.has_dims ? (
                <>
                  <CardTitle>Grelha Cor × Tamanho</CardTitle>
                  <DimGrid
                    grid={itemDimGrid}
                    values={dimValues}
                    onChange={handleDimChange}
                  />
                </>
              ) : activeItem.has_lots ? (
                <>
                  <CardTitle>Selecionar lote</CardTitle>
                  <LotSelector
                    lots={itemLots}
                    selectedLot={selectedLot}
                    lotQty={lotQty}
                    onSelect={setSelectedLot}
                    onQtyChange={setLotQty}
                  />
                </>
              ) : activeItem.has_volumes ? (
                <>
                  <CardTitle>Selecionar volume</CardTitle>
                  <VolumeSelector
                    volumes={itemVolumes}
                    selected={selectedVols}
                    onToggle={v => setSelectedVols(prev =>
                      prev.includes(v) ? [] : [v]
                    )}
                  />
                  <VolumeQtyEditor
                    volume={itemVolumes.find(v => v.vol_num === selectedVols[0])}
                    value={volumeQty}
                    onChange={setVolumeQty}
                  />
                </>
              ) : (
                <div className={styles.qtyRow}>
                  <span className={styles.qtyLabel}>Quantidade ({activeItem.stk_unit}):</span>
                  <input
                    className={styles.qtyInput}
                    type="number"
                    min="0"
                    step="1"
                    value={simpleQty}
                    onChange={e => setSimpleQty(e.target.value)}
                    autoFocus
                    onKeyDown={e => e.key === 'Enter' && addToCart()}
                  />
                </div>
              )}

              <div className={styles.actions} style={{ marginTop: 16 }}>
                <Btn variant="outline" onClick={() => setActiveItem(null)}>Cancelar</Btn>
                <Btn variant="primary" onClick={addToCart}>Adicionar ao movimento →</Btn>
              </div>
            </div>
          )}

          {/* Item list — from document */}
          {!activeItem && document && (
            <Card>
              <CardTitle>Artigos do documento</CardTitle>
              {loadingLines ? (
                <div style={{ textAlign: 'center', padding: 24 }}><Spinner /></div>
              ) : (
                <div className={styles.list}>
                  {docLines.map(line => {
                    const inCart = cart.some(c => c.item_id === line.item_id)
                    return (
                      <button
                        key={`${line.item_id}-${line.order_row}`}
                        className={styles.listItem}
                        onClick={() => openItemDetail(line)}
                        style={inCart ? { borderColor: 'var(--green)' } : {}}
                      >
                        <div className={styles.listItemMain}>
                          <div className={styles.listItemTitle}>
                            {inCart && '✓ '}{line.item_id}
                          </div>
                          <div className={styles.listItemSub}>
                            {line.item_desc}
                            {line.has_dims && ' · Dims'}{line.has_lots && ' · Lotes'}{line.has_volumes && ' · Volumes'}
                          </div>
                        </div>
                        <div style={{ textAlign: 'right', flexShrink: 0 }}>
                          <div style={{ fontSize: 13, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                            {line.qty_pending} pend.
                          </div>
                        </div>
                        <span className={styles.listItemArrow}>›</span>
                      </button>
                    )
                  })}
                  {docLines.length === 0 && (
                    <div className={styles.empty}>
                      <div className={styles.emptyText}>Nenhum artigo pendente neste documento</div>
                    </div>
                  )}
                </div>
              )}
            </Card>
          )}

          {/* Item list — free search (no document) */}
          {!activeItem && !document && (
            <Card>
              <CardTitle>Pesquisar artigo</CardTitle>
              <div className={styles.searchBar}>
                <input
                  className={styles.searchInput}
                  type="text"
                  placeholder="Código, referência ou descrição..."
                  value={itemSearch}
                  onChange={e => setItemSearch(e.target.value)}
                  autoFocus
                />
              </div>
              <div className={styles.list}>
                {freeItems.map(item => (
                  <button
                    key={item.item_id}
                    className={styles.listItem}
                    onClick={() => openItemDetail(item)}
                  >
                    <div className={styles.listItemMain}>
                      <div className={styles.listItemTitle}>{item.item_id}</div>
                      <div className={styles.listItemSub}>
                        {item.item_desc}
                        {item.has_dims && ' · Dims'}{item.has_lots && ' · Lotes'}{item.has_volumes && ' · Volumes'}
                      </div>
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text3)', flexShrink: 0 }}>
                      {item.qty_stock} em stock
                    </div>
                    <span className={styles.listItemArrow}>›</span>
                  </button>
                ))}
              </div>
            </Card>
          )}

          <div className={styles.actions}>
            <Btn variant="outline" onClick={() => {
              if (document) setStep('document')
              else if (partner) setStep('partner')
              else setStep('type')
            }}>← Voltar</Btn>
            <Btn
              variant="primary"
              disabled={cart.length === 0}
              onClick={() => setStep('warehouse')}
            >
              Continuar ({cart.length} art.) →
            </Btn>
          </div>
        </>
      )}

      {/* ════ STEP: warehouse ════════════════════════════════════════════════════ */}
      {step === 'warehouse' && (
        <Card>
          <CardTitle>Armazéns e localizações</CardTitle>

          {loadingWh ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spinner /></div>
          ) : (
            <div className={styles.warehouseGrid}>
              <div className={styles.warehouseField}>
                <label className={styles.warehouseLabel}>
                  {movType?.is_transfer ? 'Armazém Origem *' : 'Armazém *'}
                </label>
                <select
                  className={styles.warehouseSelect}
                  value={whOrig}
                  onChange={e => setWhOrig(e.target.value)}
                >
                  <option value="">Selecionar...</option>
                  {warehouses
                    .filter(w => !w.wh_role || w.wh_role === 'O' || w.wh_role === '')
                    .map(w => (
                      <option key={w.wh_id} value={w.wh_id}>{w.wh_desc}</option>
                    ))}
                </select>
              </div>

              <div className={styles.warehouseField}>
                <label className={styles.warehouseLabel}>Localização *</label>
                <select
                  className={styles.warehouseSelect}
                  value={locOrig}
                  onChange={e => setLocOrig(e.target.value)}
                  disabled={!whOrig}
                >
                  <option value="">Selecionar...</option>
                  {locations.orig.map(l => (
                    <option key={l.location_id} value={l.location_id}>
                      {l.location_id} — {l.location_desc}
                    </option>
                  ))}
                </select>
              </div>

              {movType?.is_transfer && (
                <>
                  <div className={styles.warehouseField} style={{ marginTop: 8 }}>
                    <label className={styles.warehouseLabel}>Armazém Destino *</label>
                    <select
                      className={styles.warehouseSelect}
                      value={whDest}
                      onChange={e => setWhDest(e.target.value)}
                    >
                      <option value="">Selecionar...</option>
                      {warehouses
                        .filter(w => !w.wh_role || w.wh_role === 'D' || w.wh_role === '')
                        .map(w => (
                          <option key={w.wh_id} value={w.wh_id}>{w.wh_desc}</option>
                        ))}
                    </select>
                  </div>

                  <div className={styles.warehouseField}>
                    <label className={styles.warehouseLabel}>Localização Destino *</label>
                    <select
                      className={styles.warehouseSelect}
                      value={locDest}
                      onChange={e => setLocDest(e.target.value)}
                      disabled={!whDest}
                    >
                      <option value="">Selecionar...</option>
                      {locations.dest.map(l => (
                        <option key={l.location_id} value={l.location_id}>
                          {l.location_id} — {l.location_desc}
                        </option>
                      ))}
                    </select>
                  </div>
                </>
              )}
            </div>
          )}

          <div className={styles.actions} style={{ marginTop: 20 }}>
            <Btn variant="outline" onClick={() => setStep('items')}>← Voltar</Btn>
            <Btn
              variant="primary"
              disabled={!whOrig || !locOrig || (movType?.is_transfer && (!whDest || !locDest))}
              onClick={() => setStep('confirm')}
            >
              Rever e confirmar →
            </Btn>
          </div>
        </Card>
      )}

      {/* ════ STEP: confirm ══════════════════════════════════════════════════════ */}
      {step === 'confirm' && (
        <>
          <Card>
            <CardTitle>Resumo do movimento</CardTitle>
            <div className={styles.summary}>
              <div className={styles.summaryRow}>
                <span className={styles.summaryKey}>Tipo</span>
                <span className={styles.summaryValue}>{movType?.title}</span>
              </div>
              {partner && (
                <div className={styles.summaryRow}>
                  <span className={styles.summaryKey}>Parceiro</span>
                  <span className={styles.summaryValue}>{partner.partner_name}</span>
                </div>
              )}
              {document && (
                <div className={styles.summaryRow}>
                  <span className={styles.summaryKey}>Documento</span>
                  <span className={styles.summaryValue}>{document.doc_type} #{document.order_id}</span>
                </div>
              )}
              <div className={styles.summaryRow}>
                <span className={styles.summaryKey}>Armazém origem</span>
                <span className={styles.summaryValue}>
                  {warehouses.find(w => String(w.wh_id) === String(whOrig))?.wh_desc || whOrig}
                  {locOrig ? ` · ${locOrig}` : ''}
                </span>
              </div>
              {movType?.is_transfer && (
                <div className={styles.summaryRow}>
                  <span className={styles.summaryKey}>Armazém destino</span>
                  <span className={styles.summaryValue}>
                    {warehouses.find(w => String(w.wh_id) === String(whDest))?.wh_desc || whDest}
                    {locDest ? ` · ${locDest}` : ''}
                  </span>
                </div>
              )}
              <div className={styles.summaryRow}>
                <span className={styles.summaryKey}>Total</span>
                <span className={styles.summaryValue}>{cartTotal} unidades · {cart.length} art.</span>
              </div>
            </div>
          </Card>

          <Card>
            <CardTitle>Linhas do movimento</CardTitle>
            <div className={styles.summaryLines}>
              {cart.flatMap(item =>
                item.lines.map((line, i) => (
                  <div key={`${item.item_id}-${i}`} className={styles.summaryLine}>
                    <span className={styles.summaryLineId}>{item.item_id}</span>
                    <span className={styles.summaryLineDesc}>
                      {item.item_desc}
                      {line.color_id ? ` · ${line.color_id}` : ''}
                      {line.size_id  ? ` / ${line.size_id}`  : ''}
                      {line.lot_id   ? ` · L: ${line.lot_id}` : ''}
                    </span>
                    <span className={styles.summaryLineQty}>{line.qty} {item.stk_unit}</span>
                  </div>
                ))
              )}
            </div>
          </Card>

          <div className={styles.actions}>
            <Btn variant="outline" onClick={() => setStep('warehouse')}>← Voltar</Btn>
            <Btn variant="success" loading={executing} onClick={handleExecute}>
              ✓ Confirmar e executar
            </Btn>
          </div>
        </>
      )}

      {/* ════ STEP: done ════════════════════════════════════════════════════════ */}
      {step === 'done' && result && (
        <Card>
          <div className={styles.successBox}>
            <div className={styles.successIcon}>✅</div>
            <div className={styles.successTitle}>Movimento executado!</div>
            <div className={styles.successDetail}>{result.message}</div>
            {result.warnings?.length > 0 && (
              <div style={{ marginBottom: 16, textAlign: 'left' }}>
                {result.warnings.map((w, i) => (
                  <div key={i} style={{ fontSize: 12, color: 'var(--yellow)', padding: '4px 0' }}>⚠ {w}</div>
                ))}
              </div>
            )}
            <Btn variant="primary" onClick={reset}>Novo movimento</Btn>
          </div>
        </Card>
      )}

    </div>
  )
}
