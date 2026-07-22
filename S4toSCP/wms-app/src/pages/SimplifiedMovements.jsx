import { useState, useEffect, useCallback, useRef } from 'react'
import { useToast } from '../context/ToastContext'
import { Card, CardTitle, Btn, Steps, Spinner } from '../components/ui'
import styles from './SimplifiedMovements.module.css'

const API = import.meta.env.VITE_API_URL ?? '/api'
const STATION_STORAGE_KEY = 's4log_station_identifier'

function stationIdentifierHeader() {
  if (typeof window === 'undefined') return {}
  const value = (window.localStorage.getItem(STATION_STORAGE_KEY) || '').trim()
  return value ? { 'X-Station-Identifier': value } : {}
}

function withStationHeaders(opts = {}) {
  return {
    ...opts,
    headers: {
      ...stationIdentifierHeader(),
      ...(opts.headers || {}),
    },
  }
}

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
      const res = await fetch(`${base}${path}`, withStationHeaders(opts))
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

function buildScopeQuery({ whOrig, locOrig, selectedBox }) {
  const params = new URLSearchParams()
  if (whOrig) params.set('wh_id', whOrig)
  if (locOrig) params.set('location_id', locOrig)
  if (selectedBox) params.set('vol_num', selectedBox)
  const query = params.toString()
  return query ? `?${query}` : ''
}

function matchesBoxValue(box, value) {
  const normalized = value.trim().toLowerCase()
  if (!normalized) return false
  return (
    String(box.vol_num).trim().toLowerCase() === normalized ||
    String(box.barcode || '').trim().toLowerCase() === normalized
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
  const requiresPartner = !!(movType?.allow_business_partner && movType?.partner_type)
  const hasOriginDocTypes = !!movType?.has_origin_doc_types
  const requiresOriginDocument = !!movType?.force_orig_doc

  // ── Partner ───────────────────────────────────────────────────────────────────
  const [partners, setPartners]       = useState([])
  const [partner,  setPartner]        = useState(null)
  const [partnerSearch, setPartnerSearch] = useState('')
  const [loadingPartners, setLoadingPartners] = useState(false)
  const partnerDebounce = useRef(null)

  // ── Document ──────────────────────────────────────────────────────────────────
  const [documents, setDocuments]       = useState([])
  const [document,  setDocument]        = useState(null)
  const [documentSearch, setDocumentSearch] = useState('')
  const [loadingDocs, setLoadingDocs]   = useState(false)
  const documentDebounce = useRef(null)

  // ── Items (cart) ──────────────────────────────────────────────────────────────
  const [docLines, setDocLines]         = useState([])     // lines from origin doc
  const [freeItems, setFreeItems]       = useState([])     // search results (no doc)
  const [itemSearch, setItemSearch]     = useState('')
  const [useLinkedFreeItemSearch, setUseLinkedFreeItemSearch] = useState(false)
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

  // Optional RFID quantity capture
  const [rfidEnabled, setRfidEnabled] = useState(false)
  const [rfidTunnels, setRfidTunnels] = useState([])
  const [rfidTunnelId, setRfidTunnelId] = useState('')
  const [rfidReading, setRfidReading] = useState(false)
  const [rfidBusy, setRfidBusy] = useState(false)
  const [rfidCounts, setRfidCounts] = useState({ valid: 0, invalid: 0, total: 0 })

  // ── Warehouse ─────────────────────────────────────────────────────────────────
  const [warehouses, setWarehouses]     = useState([])
  const [locations,  setLocations]      = useState({ orig: [], dest: [] })
  const [whOrig,     setWhOrig]         = useState('')
  const [locOrig,    setLocOrig]        = useState('')
  const [boxes,      setBoxes]          = useState([])
  const [boxInput,   setBoxInput]       = useState('')
  const [selectedBox, setSelectedBox]   = useState('')
  const [boxItems,   setBoxItems]       = useState([])
  const [selectedBoxItemId, setSelectedBoxItemId] = useState('')
  const [whDest,     setWhDest]         = useState('')
  const [locDest,    setLocDest]        = useState('')
  const [loadingWh,  setLoadingWh]      = useState(false)
  const [loadingBoxes, setLoadingBoxes] = useState(false)
  const [loadingBoxItems, setLoadingBoxItems] = useState(false)

  // ── Execute ───────────────────────────────────────────────────────────────────
  const [executing, setExecuting]       = useState(false)
  const [printingLabel, setPrintingLabel] = useState(false)
  const [result,    setResult]          = useState(null)
  const originItemId = activeItem?.item_id || ''
  const selectedBoxData = boxes.find(box => String(box.vol_num) === String(selectedBox)) || null
  const effectiveOriginLocation = selectedBoxData?.location_id || locOrig
  const hasOriginScope = !!(whOrig && (effectiveOriginLocation || selectedBox))
  const allowLinkedFreeItem = !!(document && movType?.link_itemid_as_component)
  const showFreeItemSearch = !document || useLinkedFreeItemSearch
  const currentBoxItems = selectedBox ? boxItems : []
  const boxItemIds = new Set(currentBoxItems.map(item => item.item_id))
  const normalizedItemSearch = itemSearch.trim().toLowerCase()
  const visibleFreeItems = selectedBox
    ? currentBoxItems.filter(item => {
        if (selectedBoxItemId && item.item_id !== selectedBoxItemId) return false
        if (!normalizedItemSearch) return true
        const haystack = `${item.item_id} ${item.item_desc || ''}`.toLowerCase()
        return haystack.includes(normalizedItemSearch)
      })
    : freeItems.filter(item => !selectedBoxItemId || item.item_id === selectedBoxItemId)

  const applyRfidSnapshot = useCallback((snapshot) => {
    const itemId = String(activeItem?.item_id || '').trim().toLowerCase()
    const valid = (snapshot?.known_items || []).reduce(
      (sum, item) => String(item.item_id || '').trim().toLowerCase() === itemId
        ? sum + Number(item.qty_counted || 0)
        : sum,
      0,
    )
    const total = Number(snapshot?.total_tags || 0)
    setRfidCounts({ valid, invalid: Math.max(0, total - valid), total })

    // RFID supplies the quantity only where this screen has one quantity field.
    if (activeItem?.has_volumes) setVolumeQty(String(valid || ''))
    else if (!activeItem?.has_dims && !activeItem?.has_lots) setSimpleQty(String(valid || ''))
  }, [activeItem])

  useEffect(() => {
    if (!rfidEnabled || rfidTunnels.length) return
    apiFetch('/config/tunnels')
      .then(rows => {
        const list = Array.isArray(rows) ? rows : []
        setRfidTunnels(list)
        if (list[0]?.tunnel_id) setRfidTunnelId(String(list[0].tunnel_id))
      })
      .catch(error => toast(`Erro ao carregar túneis RFID: ${error.message}`, 'error'))
  }, [rfidEnabled, rfidTunnels.length, toast])

  useEffect(() => {
    setRfidCounts({ valid: 0, invalid: 0, total: 0 })
  }, [activeItem?.item_id, selectedBox])

  useEffect(() => {
    if (!rfidEnabled || !rfidReading || !rfidTunnelId || !activeItem) return undefined
    let cancelled = false
    const refresh = () => apiFetch(`/counting/tunnels/${rfidTunnelId}/snapshot`)
      .then(snapshot => { if (!cancelled) applyRfidSnapshot(snapshot) })
      .catch(() => {})
    refresh()
    const timer = window.setInterval(refresh, 1000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [rfidEnabled, rfidReading, rfidTunnelId, activeItem, applyRfidSnapshot])

  const runRfidAction = useCallback(async (action) => {
    if (!rfidTunnelId) { toast('Seleciona um túnel RFID', 'error'); return }
    setRfidBusy(true)
    try {
      await apiFetch(`/counting/tunnels/${rfidTunnelId}/${action}`, { method: 'POST' })
      setRfidReading(action !== 'stop')
      if (action === 'reset') {
        setRfidCounts({ valid: 0, invalid: 0, total: 0 })
        if (activeItem?.has_volumes) setVolumeQty('')
        else if (!activeItem?.has_dims && !activeItem?.has_lots) setSimpleQty('')
      }
    } catch (error) {
      toast(error.message || 'Erro na operação RFID', 'error')
    } finally {
      setRfidBusy(false)
    }
  }, [rfidTunnelId, activeItem, toast])

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

  // ── Load documents when entering document step / searching ───────────────────
  useEffect(() => {
    if (step !== 'document' || !movType) return
    clearTimeout(documentDebounce.current)
    documentDebounce.current = setTimeout(() => {
      setLoadingDocs(true)
      const partnerId = partner?.partner_id || ''
      apiFetch(`/simplified-movements/documents?doc_type=${movType.doc_type}&partner_id=${encodeURIComponent(partnerId)}&search=${encodeURIComponent(documentSearch)}`)
        .then(setDocuments)
        .catch(() => toast('Erro ao carregar documentos', 'error'))
        .finally(() => setLoadingDocs(false))
    }, 300)
  }, [step, movType, partner, documentSearch, toast])

  // ── Load document lines when entering items step ──────────────────────────────
  useEffect(() => {
    if (step !== 'items') return
    setDocLines([])
    setFreeItems([])

    if (!whOrig) return

    if (document && movType) {
      setLoadingLines(true)
      const scopeQuery = buildScopeQuery({ whOrig, locOrig, selectedBox })
      apiFetch(
        `/simplified-movements/documents/${document.order_id}/lines${scopeQuery ? `${scopeQuery}&` : '?'}doc_type=${document.doc_type}&with_components=${movType.has_components ? 1 : 0}`
      )
        .then(rows => setDocLines(selectedBox ? rows.filter(r => boxItemIds.has(r.item_id)) : rows))
        .catch(() => toast('Erro ao carregar linhas', 'error'))
        .finally(() => setLoadingLines(false))
    }
  }, [step, document, movType, whOrig, locOrig, selectedBox, toast, boxItems])

  // ── Debounced free-item search ────────────────────────────────────────────────
  useEffect(() => {
    if (step !== 'items' || (document && !useLinkedFreeItemSearch)) return
    clearTimeout(itemDebounce.current)
    if (!whOrig) { setFreeItems([]); return }
    if (selectedBox) {
      setFreeItems([])
      return
    }
    if (!itemSearch || itemSearch.length < 2) { setFreeItems([]); return }
    itemDebounce.current = setTimeout(() => {
      const scopeQuery = buildScopeQuery({ whOrig, locOrig, selectedBox })
      apiFetch(`/simplified-movements/items${scopeQuery ? `${scopeQuery}&` : '?'}search=${encodeURIComponent(itemSearch)}`)
        .then(rows => setFreeItems(selectedBox ? rows.filter(item => boxItemIds.has(item.item_id)) : rows))
        .catch(() => {})
    }, 300)
  }, [itemSearch, step, document, useLinkedFreeItemSearch, whOrig, locOrig, selectedBox, currentBoxItems])

  // ── Load warehouses when entering warehouse step ──────────────────────────────
  useEffect(() => {
    if ((step !== 'items' && step !== 'warehouse') || !movType) return
    setLoadingWh(true)
    apiFetch(`/simplified-movements/warehouses?doc_type=${movType.doc_type}`)
      .then(setWarehouses)
      .catch(() => toast('Erro ao carregar armazéns', 'error'))
      .finally(() => setLoadingWh(false))
  }, [step, movType, toast])

  // ── Load origin locations ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!whOrig) { setLocations(l => ({ ...l, orig: [] })); setLocOrig(''); return }
    const itemQuery = originItemId ? `?item_id=${encodeURIComponent(originItemId)}` : ''
    apiFetch(`/simplified-movements/warehouses/${whOrig}/locations${itemQuery}`)
      .then(rows => setLocations(l => ({ ...l, orig: rows })))
      .catch(() => {})
  }, [whOrig, originItemId])

  useEffect(() => {
    if (!whOrig) {
      setBoxes([])
      setBoxItems([])
      setSelectedBoxItemId('')
      setSelectedBox('')
      setBoxInput('')
      return
    }
    setLoadingBoxes(true)
    const locationQuery = locOrig ? `&location_id=${encodeURIComponent(locOrig)}` : ''
    const itemQuery = originItemId ? `&item_id=${encodeURIComponent(originItemId)}` : ''
    apiFetch(`/simplified-movements/boxes?wh_id=${whOrig}${locationQuery}${itemQuery}`)
      .then(setBoxes)
      .catch(() => setBoxes([]))
      .finally(() => setLoadingBoxes(false))
  }, [whOrig, locOrig, originItemId])

  useEffect(() => {
    if (!selectedBox || !whOrig) {
      setBoxItems([])
      setSelectedBoxItemId('')
      return
    }
    setLoadingBoxItems(true)
    apiFetch(`/simplified-movements/boxes/${encodeURIComponent(selectedBox)}/items?wh_id=${whOrig}`)
      .then(rows => {
        setBoxItems(rows)
        if (rows.length === 1) {
          setSelectedBoxItemId(rows[0].item_id)
        } else if (selectedBoxItemId && !rows.some(item => item.item_id === selectedBoxItemId)) {
          setSelectedBoxItemId('')
        }
      })
      .catch(() => {
        setBoxItems([])
        setSelectedBoxItemId('')
      })
      .finally(() => setLoadingBoxItems(false))
  }, [selectedBox, whOrig, selectedBoxItemId])

  useEffect(() => {
    if (!selectedBoxData) return
    setBoxInput(selectedBoxData.barcode || String(selectedBoxData.vol_num))
  }, [selectedBoxData?.vol_num])

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
    setDocumentSearch('')
    setUseLinkedFreeItemSearch(false)
    setCart([])
    setActiveItem(null)

    if (mt.allow_business_partner && mt.partner_type) {
      setStep('partner')
    } else if (mt.has_origin_doc_types) {
      setStep('document')
    } else {
      setStep('items')
    }
  }, [])

  // ── Select partner ─────────────────────────────────────────────────────────────
  const handleSelectPartner = useCallback((p) => {
    setPartner(p)
    setDocument(null)
    setDocumentSearch('')
    setUseLinkedFreeItemSearch(false)
    setCart([])

    if (movType?.has_origin_doc_types) {
      setStep('document')
    } else {
      setStep('items')
    }
  }, [movType])

  // ── Select document ────────────────────────────────────────────────────────────
  const handleSelectDocument = useCallback((doc) => {
    setDocument(doc)
    setUseLinkedFreeItemSearch(false)
    setCart([])
    setStep('items')
  }, [])

  const handleSkipDocument = useCallback(() => {
    setDocument(null)
    setUseLinkedFreeItemSearch(false)
    setCart([])
    setStep('items')
  }, [])

  // ── Open item detail (dims / lots / volumes / simple qty) ─────────────────────
  const openItemDetail = useCallback(async (item) => {
    if (!whOrig) {
      toast('Seleciona primeiro o armazém de origem', 'error')
      return
    }

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
      const scopeQuery = buildScopeQuery({ whOrig, locOrig, selectedBox })
      if (item.has_dims) {
        const grid = await apiFetch(`/simplified-movements/items/${item.item_id}/dim-stock${scopeQuery}`)
        setItemDimGrid(grid)
      } else if (item.has_lots) {
        const lots = await apiFetch(`/simplified-movements/items/${item.item_id}/lots${scopeQuery}`)
        setItemLots(lots)
      } else if (item.has_volumes) {
        const vols = await apiFetch(`/simplified-movements/items/${item.item_id}/volumes${scopeQuery}`)
        setItemVolumes(vols)
        if (selectedBox && vols.some(v => String(v.vol_num) === String(selectedBox))) {
          setSelectedVols([selectedBox])
        }
      }
    } catch {
      toast('Erro ao carregar detalhe do artigo', 'error')
    } finally {
      setLoadingItemDetail(false)
    }
  }, [toast, whOrig, locOrig, selectedBox])

  const handleBoxInputChange = useCallback((value) => {
    setBoxInput(value)
    if (!value.trim()) {
      setLocOrig('')
      setSelectedBoxItemId('')
      setActiveItem(null)
      setSelectedBox('')
      return
    }

    const match = boxes.find(box => matchesBoxValue(box, value))
    if (match) {
      setSelectedBox(String(match.vol_num))
    } else {
      if (selectedBox || locOrig) {
        setLocOrig('')
        setSelectedBoxItemId('')
        setActiveItem(null)
      }
      setSelectedBox('')
    }
  }, [boxes, locOrig, selectedBox])

  const resolveBoxSelection = useCallback(async (value) => {
    const trimmed = value.trim()
    if (!whOrig || !trimmed) {
      setSelectedBox('')
      return
    }

    const localMatch = boxes.find(box => matchesBoxValue(box, trimmed))
    if (localMatch) {
      setSelectedBox(String(localMatch.vol_num))
      if (localMatch.location_id) {
        setLocOrig(localMatch.location_id)
      }
      return
    }

    try {
      const locationQuery = locOrig ? `&location_id=${encodeURIComponent(locOrig)}` : ''
      const itemQuery = originItemId ? `&item_id=${encodeURIComponent(originItemId)}` : ''
      const rows = await apiFetch(
        `/simplified-movements/boxes?wh_id=${whOrig}${locationQuery}${itemQuery}&search=${encodeURIComponent(trimmed)}`
      )
      if (!rows.length) return

      setBoxes(prev => {
        const merged = [...prev]
        rows.forEach(row => {
          if (!merged.some(box => String(box.vol_num) === String(row.vol_num))) {
            merged.push(row)
          }
        })
        return merged
      })

      const match = rows.find(box => matchesBoxValue(box, trimmed))
      if (match) {
        setSelectedBox(String(match.vol_num))
        if (match.location_id) {
          setLocOrig(match.location_id)
        }
      }
    } catch {
      // ignore lookup errors while scanning/selecting a box
    }
  }, [whOrig, boxes, locOrig, originItemId])

  useEffect(() => {
    if (!selectedBoxItemId) return
    const item = currentBoxItems.find(entry => entry.item_id === selectedBoxItemId)
    if (item) openItemDetail(item)
  }, [selectedBoxItemId, currentBoxItems, openItemDetail])

  useEffect(() => {
    if (step !== 'items' || !activeItem || !whOrig) return
    openItemDetail(activeItem)
  }, [step, activeItem?.item_id, whOrig, locOrig, selectedBox])

  // ── Dim grid cell change ───────────────────────────────────────────────────────
  const handleDimChange = useCallback((color, size, val) => {
    setDimValues(prev => ({ ...prev, [`${color}__${size}`]: val }))
  }, [])

  const handleItemSearchChange = useCallback((value) => {
    setItemSearch(value)
    if (!selectedBox || !selectedBoxItemId) return

    const normalized = value.trim().toLowerCase()
    if (!normalized) {
      setSelectedBoxItemId('')
      return
    }

    const currentMatch = currentBoxItems.find(item => item.item_id === selectedBoxItemId)
    const currentHaystack = currentMatch
      ? `${currentMatch.item_id} ${currentMatch.item_desc || ''}`.toLowerCase()
      : ''

    if (!currentHaystack.includes(normalized)) {
      setSelectedBoxItemId('')
    }
  }, [selectedBox, selectedBoxItemId, currentBoxItems])

  // ── Add item to cart ───────────────────────────────────────────────────────────
  const addToCart = useCallback(() => {
    if (!activeItem) return
    const docRow = activeItem.order_row ?? (allowLinkedFreeItem ? 0 : null)
    const currentOriginLocation = effectiveOriginLocation || ''
    const existingItem = cart.find(item => item.item_id === activeItem.item_id)
    const existingLines = existingItem?.lines || []
    let newLines = []

    if (activeItem.has_dims && itemDimGrid) {
      // Dim grid: one line per color/size with qty > 0
      for (const [key, val] of Object.entries(dimValues)) {
        const qty = parseFloat(val)
        if (!val || isNaN(qty) || qty <= 0) continue
        const [color, size] = key.split('__')
        const cell = itemDimGrid.cells.find(entry => entry.color_id === color && entry.size_id === size)
        const alreadyAdded = existingLines
          .filter(line =>
            line.color_id === color &&
            line.size_id === size &&
            (line.location_id_orig || '') === currentOriginLocation
          )
          .reduce((sum, line) => sum + line.qty, 0)
        const availableQty = cell?.qty_stock ?? 0
        if (qty + alreadyAdded > availableQty) {
          toast(`A quantidade total para ${color} / ${size} não pode exceder o stock disponível (${availableQty})`, 'error')
          return
        }
        newLines.push({ color_id: color, size_id: size, lot_id: '', vol_num: selectedBox || null, qty, doc_row: docRow, location_id_orig: currentOriginLocation })
      }
      if (!newLines.length) { toast('Introduce pelo menos uma quantidade', 'error'); return }
    } else if (activeItem.has_lots) {
      if (!selectedLot) { toast('Seleciona um lote', 'error'); return }
      const qty = parseFloat(lotQty)
      if (!qty || qty <= 0) { toast('Introduce uma quantidade válida', 'error'); return }
      const lot = itemLots.find(entry => entry.lot_id === selectedLot)
      const alreadyAdded = existingLines
        .filter(line => line.lot_id === selectedLot && (line.location_id_orig || '') === currentOriginLocation)
        .reduce((sum, line) => sum + line.qty, 0)
      const availableQty = lot?.qty_stock ?? 0
      if (qty + alreadyAdded > availableQty) {
        toast(`A quantidade total para o lote ${selectedLot} não pode exceder o stock disponível (${availableQty})`, 'error')
        return
      }
      newLines.push({ color_id: '', size_id: '', lot_id: selectedLot, vol_num: selectedBox || null, qty, doc_row: docRow, location_id_orig: currentOriginLocation })
    } else if (activeItem.has_volumes) {
      if (!selectedVols.length) { toast('Seleciona um volume', 'error'); return }
      const vol = itemVolumes.find(v => v.vol_num === selectedVols[0])
      const qty = parseFloat(volumeQty)
      if (!qty || qty <= 0) { toast('Introduce uma quantidade válida', 'error'); return }
      const alreadyAdded = existingLines
        .filter(line =>
          String(line.vol_num) === String(selectedVols[0]) &&
          (line.location_id_orig || '') === currentOriginLocation
        )
        .reduce((sum, line) => sum + line.qty, 0)
      if (vol && qty + alreadyAdded > vol.qty_stock) {
        toast(`A quantidade total não pode exceder o stock do volume (${vol.qty_stock})`, 'error')
        return
      }
      newLines.push({ color_id: '', size_id: '', lot_id: '', vol_num: selectedVols[0], qty, doc_row: docRow, location_id_orig: currentOriginLocation })
    } else {
      const qty = parseFloat(simpleQty)
      if (!qty || qty <= 0) { toast('Introduce uma quantidade válida', 'error'); return }
      const alreadyAdded = existingLines
        .filter(line => (line.location_id_orig || '') === currentOriginLocation)
        .reduce((sum, line) => sum + line.qty, 0)
      if (activeItem.qty_stock != null && qty + alreadyAdded > activeItem.qty_stock) {
        toast(`A quantidade total não pode exceder o stock disponível (${activeItem.qty_stock})`, 'error')
        return
      }
      newLines.push({ color_id: '', size_id: '', lot_id: '', vol_num: selectedBox || null, qty, doc_row: docRow, location_id_orig: currentOriginLocation })
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
        origin_box: selectedBox || '',
        origin_location: effectiveOriginLocation || '',
        lines:     newLines,
      }]
    })

    setActiveItem(null)
    setItemSearch('')
    if (currentBoxItems.length > 1) {
      setSelectedBoxItemId('')
    }
    toast('Artigo adicionado', 'success')
  }, [activeItem, allowLinkedFreeItem, cart, currentBoxItems.length, dimValues, selectedLot, lotQty, selectedVols, volumeQty, simpleQty, itemDimGrid, itemLots, itemVolumes, selectedBox, effectiveOriginLocation, toast])

  // ── Remove cart item ───────────────────────────────────────────────────────────
  const removeFromCart = useCallback((itemId) => {
    setCart(prev => prev.filter(c => c.item_id !== itemId))
  }, [])

  // ── Execute movement ───────────────────────────────────────────────────────────
  const handleExecute = useCallback(async () => {
    if (!whOrig || !effectiveOriginLocation) { toast('Seleciona o armazém e depois a caixa ou a localização de origem', 'error'); return }
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
        location_id_orig: l.location_id_orig || effectiveOriginLocation,
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
          origin_doc_type:  document?.doc_type ?? null,
          partner_id:       partner?.partner_id ?? null,
          wh_id_orig:       parseInt(whOrig),
          location_id_orig: effectiveOriginLocation,
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
  }, [movType, document, partner, whOrig, effectiveOriginLocation, whDest, locDest, cart, toast])

  const reprintMovementLabel = useCallback(async () => {
    if (!result?.label_payload) {
      toast('Nao existem dados de etiqueta para reimpressao', 'error')
      return
    }

    setPrintingLabel(true)
    try {
      const response = await apiFetch('/simplified-movements/print-label', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(result.label_payload),
      })
      toast(response.printer_message || 'Etiqueta reenviada para impressao', 'success')
    } catch (error) {
      toast(error.message || 'Erro ao reimprimir etiqueta', 'error')
    } finally {
      setPrintingLabel(false)
    }
  }, [result, toast])

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
    setBoxes([]); setSelectedBox('')
    setPartnerSearch(''); setItemSearch('')
  }, [])

  // ── Determine visible steps ────────────────────────────────────────────────────
  const visibleSteps = (() => {
    if (!movType) return STEP_LABELS
    const steps = ['Tipo']
    if (requiresPartner) steps.push('Parceiro')
    if (hasOriginDocTypes) steps.push('Documento')
    steps.push('Artigos')
    if (movType?.is_transfer) steps.push('Armazém')
    steps.push('Confirmar')
    return steps
  })()

  // ── Step number for Steps indicator ───────────────────────────────────────────
  const currentStepNum = (() => {
    const map = { type: 1 }
    let n = 2
    if (requiresPartner) { map.partner = n; n++ }
    if (hasOriginDocTypes) { map.document = n; n++ }
    map.items = n; n++
    if (movType?.is_transfer) { map.warehouse = n; n++ }
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
          <CardTitle>
            {requiresOriginDocument ? 'Seleciona o documento de origem' : 'Seleciona o documento de origem (opcional)'}
          </CardTitle>

          {partner && (
            <div className={styles.contextBar}>
              <span className={styles.contextChip}>
                {partner.partner_name}
                <button className={styles.contextChipBtn} onClick={() => { setPartner(null); setStep('partner') }}>×</button>
              </span>
            </div>
          )}

          <div className={styles.searchBar}>
            <input
              className={styles.searchInput}
              value={documentSearch}
              onChange={e => setDocumentSearch(e.target.value)}
              placeholder="Filtrar por documento, tipo, cliente ou observação"
              autoFocus
            />
          </div>

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
            <Btn variant="outline" onClick={() => setStep(requiresPartner ? 'partner' : 'type')}>
              ← Voltar
            </Btn>
            {!requiresOriginDocument && (
              <Btn variant="outline" onClick={handleSkipDocument}>
                Saltar →
              </Btn>
            )}
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

          <Card>
            <CardTitle>Origem do picking</CardTitle>
            {loadingWh ? (
              <div style={{ textAlign: 'center', padding: 24 }}><Spinner /></div>
            ) : (
              <div className={styles.warehouseGrid}>
                <div className={styles.warehouseField}>
                  <label className={styles.warehouseLabel}>Armazém origem *</label>
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
                  <label className={styles.warehouseLabel}>Localização origem</label>
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

                <div className={styles.warehouseField}>
                  <label className={styles.warehouseLabel}>Caixa origem</label>
                  <input
                    className={styles.warehouseSelect}
                    list="simplified-movement-boxes"
                    value={boxInput}
                    onChange={e => handleBoxInputChange(e.target.value)}
                    onBlur={e => { void resolveBoxSelection(e.target.value) }}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        void resolveBoxSelection(e.currentTarget.value)
                      }
                    }}
                    placeholder={loadingBoxes ? 'A carregar caixas...' : 'Ler código de barras ou escolher caixa'}
                    disabled={!whOrig || loadingBoxes}
                  />
                  <datalist id="simplified-movement-boxes">
                    {boxes.map(box => (
                      <option
                        key={box.vol_num}
                        value={box.barcode || String(box.vol_num)}
                        label={`${box.vol_num} · ${box.location_id} · ${box.items_count} art. · ${box.qty_stock} un.`}
                      />
                    ))}
                  </datalist>
                </div>

                {selectedBox && (
                  <div className={styles.warehouseField}>
                    <label className={styles.warehouseLabel}>Artigo da caixa</label>
                    <select
                      className={styles.warehouseSelect}
                      value={selectedBoxItemId}
                      onChange={e => setSelectedBoxItemId(e.target.value)}
                      disabled={loadingBoxItems}
                    >
                      <option value="">{loadingBoxItems ? 'A carregar...' : 'Todos os artigos da caixa'}</option>
                      {currentBoxItems.map(item => (
                        <option key={item.item_id} value={item.item_id}>
                          {item.item_id} · {(item.qty_stock ?? 0)} {item.stk_unit || 'UN'}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            )}
          </Card>

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
                  <div className={styles.cartItemDesc}>
                    {item.item_desc}
                    {item.origin_box ? ` · Caixa ${item.origin_box}` : ''}
                    {item.origin_location ? ` · ${item.origin_location}` : ''}
                  </div>
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
              <div className={styles.itemDetailSub}>
                Quantidade total possível de movimentar: {activeItem.qty_stock ?? 0} {activeItem.stk_unit || 'UN'}
              </div>

              <div className={styles.rfidPanel}>
                <label className={styles.rfidToggle}>
                  <input
                    type="checkbox"
                    checked={rfidEnabled}
                    onChange={e => {
                      setRfidEnabled(e.target.checked)
                      if (!e.target.checked) setRfidReading(false)
                    }}
                  />
                  Indicar quantidade por leitura RFID (opcional)
                </label>
                {rfidEnabled && (
                  <>
                    <div className={styles.rfidControls}>
                      <select value={rfidTunnelId} onChange={e => setRfidTunnelId(e.target.value)}>
                        <option value="">Selecionar túnel RFID...</option>
                        {rfidTunnels.map(tunnel => (
                          <option key={tunnel.tunnel_id} value={tunnel.tunnel_id}>
                            {tunnel.tunnel_code || `Túnel ${tunnel.tunnel_id}`}
                            {tunnel.tunnel_desc ? ` — ${tunnel.tunnel_desc}` : ''}
                          </option>
                        ))}
                      </select>
                      <Btn variant="primary" loading={rfidBusy} onClick={() => runRfidAction('start')}>Iniciar</Btn>
                      <Btn variant="outline" loading={rfidBusy} onClick={() => runRfidAction('reset')}>Nova leitura</Btn>
                      <Btn variant="outline" loading={rfidBusy} onClick={() => runRfidAction('stop')}>Parar</Btn>
                    </div>
                    <div className={styles.rfidCounters}>
                      <div className={styles.rfidValid}><strong>{rfidCounts.valid}</strong><span>TAGs do artigo</span></div>
                      <div className={styles.rfidInvalid}><strong>{rfidCounts.invalid}</strong><span>TAGs não pertencem ao artigo</span></div>
                    </div>
                    {(activeItem.has_dims || activeItem.has_lots) && (
                      <div className={styles.rfidHint}>A validação RFID é apresentada, mas a quantidade deve ser distribuída manualmente pela dimensão ou lote.</div>
                    )}
                  </>
                )}
              </div>

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
                  <CardTitle>{selectedBox ? 'Caixa de origem' : 'Selecionar volume'}</CardTitle>
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
                  <span className={styles.qtyLabel}>
                    Quantidade ({activeItem.stk_unit}){activeItem.qty_stock != null ? ` · stock: ${activeItem.qty_stock}` : ''}:
                  </span>
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
          {!activeItem && document && !useLinkedFreeItemSearch && (
            <Card>
              <CardTitle>Artigos do documento</CardTitle>
              {allowLinkedFreeItem && (
                <div className={styles.actions} style={{ marginTop: 0, marginBottom: 16 }}>
                  <Btn variant="outline" onClick={() => {
                    setUseLinkedFreeItemSearch(true)
                    setItemSearch('')
                    setFreeItems([])
                  }}>
                    Selecionar outro artigo
                  </Btn>
                </div>
              )}
              {(!whOrig) && (
                <div className={styles.empty}>
                  <div className={styles.emptyText}>Seleciona primeiro o armazém para carregar o stock.</div>
                </div>
              )}
              {loadingLines ? (
                <div style={{ textAlign: 'center', padding: 24 }}><Spinner /></div>
              ) : (
                <div className={styles.list}>
                  {docLines.filter(line => !selectedBoxItemId || line.item_id === selectedBoxItemId).map(line => {
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
                          <div style={{ fontSize: 12, color: 'var(--text3)' }}>
                            {line.qty_stock ?? 0} disp.
                          </div>
                        </div>
                        <span className={styles.listItemArrow}>›</span>
                      </button>
                    )
                  })}
                  {docLines.length === 0 && whOrig && hasOriginScope && (
                    <div className={styles.empty}>
                      <div className={styles.emptyText}>
                        {selectedBox ? 'Nenhum artigo deste documento existe na caixa selecionada' : 'Nenhum artigo pendente neste documento'}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </Card>
          )}

          {/* Item list — free search */}
          {!activeItem && showFreeItemSearch && (
            <Card>
              <CardTitle>{allowLinkedFreeItem ? 'Pesquisar outro artigo' : 'Pesquisar artigo'}</CardTitle>
              {allowLinkedFreeItem && (
                <div className={styles.actions} style={{ marginTop: 0, marginBottom: 16 }}>
                  <Btn variant="outline" onClick={() => {
                    setUseLinkedFreeItemSearch(false)
                    setItemSearch('')
                    setFreeItems([])
                  }}>
                    Voltar aos artigos do documento
                  </Btn>
                </div>
              )}
              {(!whOrig) && (
                <div className={styles.empty}>
                  <div className={styles.emptyText}>Seleciona primeiro o armazém para pesquisar stock.</div>
                </div>
              )}
              <div className={styles.searchBar}>
                <input
                  className={styles.searchInput}
                  type="text"
                  list={selectedBox ? 'simplified-movement-box-items' : undefined}
                  placeholder="Código, referência ou descrição..."
                  value={itemSearch}
                  onChange={e => handleItemSearchChange(e.target.value)}
                  disabled={!whOrig}
                  autoFocus
                />
                {selectedBox && (
                  <datalist id="simplified-movement-box-items">
                    {currentBoxItems.map(item => (
                      <option
                        key={item.item_id}
                        value={item.item_id}
                        label={`${item.item_desc} · ${item.qty_stock ?? 0} ${item.stk_unit || 'UN'}`}
                      />
                    ))}
                  </datalist>
                )}
              </div>
              <div className={styles.list}>
                {visibleFreeItems.map(item => (
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
                {selectedBox && !loadingBoxItems && visibleFreeItems.length === 0 && (
                  <div className={styles.empty}>
                    <div className={styles.emptyText}>
                      Nenhum artigo encontrado para a caixa selecionada
                    </div>
                  </div>
                )}
              </div>
            </Card>
          )}

          <div className={styles.actions}>
            <Btn variant="outline" onClick={() => {
              if (hasOriginDocTypes) setStep('document')
              else if (partner) setStep('partner')
              else setStep('type')
            }}>← Voltar</Btn>
            <Btn
              variant="primary"
              disabled={cart.length === 0 || !whOrig || !effectiveOriginLocation}
              onClick={() => setStep(movType?.is_transfer ? 'warehouse' : 'confirm')}
            >
              Continuar ({cart.length} art.) →
            </Btn>
          </div>
        </>
      )}

      {/* ════ STEP: warehouse ════════════════════════════════════════════════════ */}
      {step === 'warehouse' && (
        <Card>
          <CardTitle>Destino da transferência</CardTitle>

          {loadingWh ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spinner /></div>
          ) : (
            <div className={styles.warehouseGrid}>
              <div className={styles.warehouseField}>
                <label className={styles.warehouseLabel}>Origem selecionada</label>
                <div className={styles.warehouseSelect} style={{ display: 'flex', alignItems: 'center' }}>
                  {(warehouses.find(w => String(w.wh_id) === String(whOrig))?.wh_desc || whOrig) || '—'}
                  {effectiveOriginLocation ? ` · ${effectiveOriginLocation}` : ''}
                  {selectedBox ? ` · Caixa ${selectedBox}` : ''}
                </div>
              </div>

              <div className={styles.warehouseField}>
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
            </div>
          )}

          <div className={styles.actions} style={{ marginTop: 20 }}>
            <Btn variant="outline" onClick={() => setStep('items')}>← Voltar</Btn>
            <Btn
              variant="primary"
              disabled={!whDest || !locDest}
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
                  {effectiveOriginLocation ? ` · ${effectiveOriginLocation}` : ''}{selectedBox ? ` · Caixa ${selectedBox}` : ''}
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
            <Btn variant="outline" onClick={() => setStep(movType?.is_transfer ? 'warehouse' : 'items')}>← Voltar</Btn>
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
            {result.print_message && (
              <div style={{ marginBottom: 16, color: result.print_success ? 'var(--green)' : 'var(--text2)' }}>
                {result.print_success ? 'Etiqueta impressa: ' : 'Impressao: '}{result.print_message}
              </div>
            )}
            {result.warnings?.length > 0 && (
              <div style={{ marginBottom: 16, textAlign: 'left' }}>
                {result.warnings.map((w, i) => (
                  <div key={i} style={{ fontSize: 12, color: 'var(--yellow)', padding: '4px 0' }}>⚠ {w}</div>
                ))}
              </div>
            )}
            <div className={styles.actions} style={{ justifyContent: 'center' }}>
              {result.label_payload?.groups?.length > 0 && (
                <Btn variant="outline" loading={printingLabel} onClick={reprintMovementLabel}>
                  Reimprimir etiqueta
                </Btn>
              )}
              <Btn variant="primary" onClick={reset}>Novo movimento</Btn>
            </div>
          </div>
        </Card>
      )}

    </div>
  )
}
