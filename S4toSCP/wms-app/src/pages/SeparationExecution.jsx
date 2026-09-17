import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import TouchKeypad from '../components/TouchKeypad'
import { Card, ResultBanner } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { separationApi } from '../services/api'
import styles from './SeparationExecutionRun.module.css'

const LOCATION_STATUS_LABEL = {
  0: 'Localização Inativa',
  2: 'Localização Bloqueada',
}

export default function SeparationExecution() {
  const { orderPickingId } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const [loading, setLoading] = useState(true)
  const [header, setHeader] = useState(null)
  const [lines, setLines] = useState([])
  const [volTypeOptions, setVolTypeOptions] = useState([])
  const [defaultVolTypeId, setDefaultVolTypeId] = useState('CX_STNDRD')
  const [params, setParams] = useState({
    allow_pick_more_qty_than_requested: false,
    box_auto_creation: false,
    local_confirm: false,
    lot_confirm: false,
    picking_confirm_mode: 'NONE',
    prevent_pick_notpick_loc: false,
  })

  const [currentIndex, setCurrentIndex] = useState(0)
  const [destinationVolumes, setDestinationVolumes] = useState([])
  const [activeVolumeId, setActiveVolumeId] = useState(null)
  const [contentsOpen, setContentsOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const autoCreateRequested = useRef(false)

  const [locationInput, setLocationInput] = useState('')
  const [locationConfirmed, setLocationConfirmed] = useState(false)
  const [boxConfirmed, setBoxConfirmed] = useState(false)
  const [boxAvailableQty, setBoxAvailableQty] = useState(null)
  const [checkingBox, setCheckingBox] = useState(false)
  const [lotInput, setLotInput] = useState('')
  const [lotConfirmed, setLotConfirmed] = useState(false)
  const [volTypeInput, setVolTypeInput] = useState('')
  const [volNumInput, setVolNumInput] = useState('')
  const [itemScanInput, setItemScanInput] = useState('')
  const [itemConfirmed, setItemConfirmed] = useState(false)
  const [qtyInput, setQtyInput] = useState('')

  const [activeField, setActiveField] = useState(null)
  const [keypad, setKeypad] = useState(null)

  const fieldRefs = {
    location: useRef(null),
    lot: useRef(null),
    item: useRef(null),
    qty: useRef(null),
    volNum: useRef(null),
  }

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const [detail, paramValues] = await Promise.all([
          separationApi.executionDetail(orderPickingId),
          separationApi.executionParameters(),
        ])
        if (cancelled) return
        setHeader({
          order_picking_id: detail.order_picking_id,
          related_doc_type: detail.related_doc_type,
          related_order_id: detail.related_order_id,
          source_label: detail.source_label,
        })
        const linesArr = Array.isArray(detail.lines) ? detail.lines : []
        setLines(linesArr)
        setVolTypeOptions(Array.isArray(detail.vol_type_options) ? detail.vol_type_options : [])
        setDefaultVolTypeId(detail.default_vol_type_id || 'CX_STNDRD')
        setParams(paramValues)

        // Reconstroi os volumes destino já existentes (gerados em sessões anteriores)
        // a partir do que o backend tem persistido, para nada se perder ao sair/voltar.
        const backendVolumes = Array.isArray(detail.destination_volumes) ? detail.destination_volumes : []
        const volumesMap = new Map(
          backendVolumes.map(vol => [
            String(vol.vol_num),
            { id: String(vol.vol_num), label: String(vol.label || vol.vol_num), vol_type_id: vol.vol_type_id },
          ])
        )
        linesArr.forEach(line => {
          const dest = String(line.vol_num_dest || '').trim()
          if (dest && !volumesMap.has(dest)) {
            volumesMap.set(dest, { id: dest, label: dest, vol_type_id: line.vol_type_id_dest || '', existing: true })
          }
        })
        const mergedVolumes = Array.from(volumesMap.values())
        setDestinationVolumes(mergedVolumes)

        // Salta automaticamente para a primeira linha ainda não separada.
        const firstIncomplete = linesArr.findIndex(line => !line.picking_completed)
        const initialIndex = firstIncomplete >= 0 ? firstIncomplete : Math.max(linesArr.length - 1, 0)
        setCurrentIndex(initialIndex)

        const initialLine = linesArr[initialIndex]
        const preferredVolNum = initialLine?.vol_num_dest
          ? String(initialLine.vol_num_dest)
          : (mergedVolumes.length ? mergedVolumes[mergedVolumes.length - 1].id : null)
        setActiveVolumeId(preferredVolNum || null)
      } catch (error) {
        toast(error.message || 'Erro ao carregar execução da separação', 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [orderPickingId, toast])

  useEffect(() => {
    if (loading) return
    if (params.box_auto_creation && destinationVolumes.length === 0 && !autoCreateRequested.current) {
      autoCreateRequested.current = true
      createVolume(defaultVolTypeId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, params.box_auto_creation, destinationVolumes.length])

  const currentLine = lines[currentIndex] || null

  useEffect(() => {
    if (!currentLine) return
    if (currentLine.picking_completed) {
      setLocationInput(currentLine.location_origin || '')
      setLocationConfirmed(true)
      setLotInput(currentLine.lot || '')
      setLotConfirmed(true)
      setVolTypeInput(currentLine.vol_type_id_dest || currentLine.vol_type_id || defaultVolTypeId)
      setVolNumInput(currentLine.vol_num || '')
      setBoxConfirmed(true)
      setBoxAvailableQty(null)
      setItemScanInput(currentLine.item_id || '')
      setItemConfirmed(true)
      setQtyInput(String(currentLine.qty_picked ?? 0))
      closeKeypad()
      if (currentLine.vol_num_dest) {
        setActiveVolumeId(current => {
          const match = destinationVolumes.find(vol => vol.label === String(currentLine.vol_num_dest))
          return match ? match.id : current
        })
      }
      return
    }
    resetPendingLineFields(currentLine)
    closeKeypad()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentLine?.row_number, currentLine?.picking_completed, params.local_confirm, params.lot_confirm, params.picking_confirm_mode, defaultVolTypeId])

  function resetPendingLineFields(line) {
    const hasStoredLocation = Boolean(line.location_origin) && !line.location_is_suggested
    setLocationInput(line.location_origin || '')
    setLocationConfirmed(hasStoredLocation && !params.local_confirm)
    setLotInput(line.lot || '')
    setLotConfirmed(Boolean(line.lot) && !params.lot_confirm)
    setVolTypeInput(line.vol_type_id || defaultVolTypeId)
    setVolNumInput('')
    setBoxConfirmed(!line.has_volumes)
    setBoxAvailableQty(null)
    setItemScanInput('')
    setItemConfirmed(params.picking_confirm_mode === 'NONE')
    setQtyInput(params.picking_confirm_mode === 'READ_ALL' ? '0' : '')
  }

  const remainingQty = currentLine ? Math.max(currentLine.qty_to_pick - currentLine.qty_picked, 0) : 0
  // O limite de existência na caixa é sempre rígido - "allow_pick_more_qty_than_requested" só
  // dispensa o limite do que foi pedido no documento, nunca o que a caixa tem fisicamente.
  const requestCeiling = params.allow_pick_more_qty_than_requested ? Infinity : remainingQty
  const pickCeiling = boxAvailableQty != null ? Math.min(requestCeiling, boxAvailableQty) : requestCeiling
  const locationEditable = !(locationConfirmed && !params.local_confirm)
  const lotEditable = !(lotConfirmed && !params.lot_confirm)
  const qtyExceedsStock = boxAvailableQty != null && Number(qtyInput || 0) > boxAvailableQty
  const qtyExceedsRequested = !qtyExceedsStock && !params.allow_pick_more_qty_than_requested && Number(qtyInput || 0) > remainingQty
  const qtyExceeds = qtyExceedsStock || qtyExceedsRequested
  const locationStatusLabel = currentLine ? LOCATION_STATUS_LABEL[currentLine.location_status_id] : null
  const activeVolume = destinationVolumes.find(vol => vol.id === activeVolumeId) || null
  const activeVolumeEntries = activeVolume
    ? lines.filter(line => line.picking_completed && String(line.vol_num_dest || '') === String(activeVolume.label))
    : []

  let step = null
  if (currentLine) {
    if (currentLine.location_blocked) {
      step = { key: 'blocked', icon: '⛔', label: locationStatusLabel || 'Localização bloqueada', value: null }
    } else if (!activeVolume) {
      step = { key: 'volume', icon: '🆕', label: 'Cria um volume novo para começares', value: null }
    } else if (!locationConfirmed) {
      step = { key: 'location', icon: '📍', label: 'Dirige-te à localização', value: locationInput || currentLine.location_origin || '—' }
    } else if (currentLine.has_volumes && !boxConfirmed) {
      step = { key: 'box', icon: '📦', label: 'Lê a caixa de origem', value: currentLine.vol_num || 'sem nº atribuído' }
    } else if (currentLine.has_lots && !lotConfirmed) {
      step = { key: 'lot', icon: '🏷️', label: 'Lê o lote do artigo', value: lotInput || null }
    } else if (!itemConfirmed) {
      step = { key: 'item', icon: '🔎', label: 'Lê o artigo', value: currentLine.item_id }
    } else if (!(Number(qtyInput || 0) > 0) || qtyExceeds) {
      step = { key: 'qty', icon: '🔢', label: 'Introduz a quantidade separada', value: `Pedido: ${currentLine.qty_to_pick}` }
    } else {
      step = { key: 'ready', icon: '✅', label: 'Linha pronta — avança', value: null }
    }
  }

  // Auto-focus: whenever the required step changes, send input focus straight to that
  // field's keypad instead of waiting for the operator to tap it manually.
  useEffect(() => {
    if (!step) return
    if (step.key === 'location' && locationEditable) {
      openKeypad('location', 'text', 'Localização origem')
    } else if (step.key === 'box') {
      // Não abre o teclado sozinho ao chegar a este passo - o operador toca no cartão
      // "Lê a caixa de origem" e só aí é que o teclado aparece (handleCalloutTap/onFocus).
      closeKeypad()
    } else if (step.key === 'lot' && lotEditable) {
      openKeypad('lot', 'text', 'Lote')
    } else if (step.key === 'item') {
      openKeypad('item', 'text', 'Ler código de artigo')
    } else if (step.key === 'qty' && params.picking_confirm_mode === 'NONE') {
      openKeypad('qty', 'numeric', 'Quantidade')
    } else {
      closeKeypad()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step?.key, currentLine?.row_number])

  function confirmItemScan(value) {
    if (!currentLine) return
    const normalized = String(value || '').trim().toUpperCase()
    if (!normalized) return
    if (normalized !== String(currentLine.item_id).trim().toUpperCase()) {
      toast('Código de artigo não corresponde à linha atual.', 'error')
      setItemScanInput('')
      return
    }
    setItemConfirmed(true)
    if (params.picking_confirm_mode === 'ONLY_ONE') {
      setQtyInput(String(pickCeiling))
    } else if (params.picking_confirm_mode === 'READ_ALL') {
      setQtyInput(current => {
        const next = Number(current || 0) + 1
        const limit = params.allow_pick_more_qty_than_requested ? Infinity : pickCeiling
        return String(Math.min(next, limit))
      })
    }
    setItemScanInput('')
    setKeypad(current => (current?.field === 'item' ? null : current))
    setActiveField(current => (current === 'item' ? null : current))
  }

  function confirmLocation(value) {
    const normalized = String(value ?? locationInput).trim()
    setLocationInput(normalized)
    setLocationConfirmed(Boolean(normalized))
    if (normalized) {
      setKeypad(current => (current?.field === 'location' ? null : current))
      setActiveField(current => (current === 'location' ? null : current))
    }
  }

  async function confirmBox(value) {
    if (!currentLine || checkingBox) return
    const normalized = String(value ?? volNumInput).trim()
    setVolNumInput(normalized)
    if (!normalized) return
    const expected = String(currentLine.vol_num || '').trim()
    if (expected && normalized !== expected) {
      toast('Número de caixa não corresponde à linha atual.', 'error')
      return
    }
    if (!expected) {
      setCheckingBox(true)
      let result
      try {
        result = await separationApi.executionCheckBox(orderPickingId, currentLine.row_number, normalized)
      } catch (error) {
        setCheckingBox(false)
        toast(error.message || 'Erro ao validar a caixa', 'error')
        return
      }
      setCheckingBox(false)
      if (!result.valid) {
        toast(result.message || `A caixa ${normalized} não tem este artigo.`, 'error')
        setVolNumInput('')
        return
      }
      setBoxAvailableQty(result.available_qty)
      if (result.available_qty < remainingQty) {
        toast(`A caixa ${normalized} só tem ${result.available_qty} unidades disponíveis — vais separar o que houver e a linha fica com falta.`, 'success')
      }
    }
    setBoxConfirmed(true)
    setKeypad(current => (current?.field === 'volNum' ? null : current))
    setActiveField(current => (current === 'volNum' ? null : current))
  }

  function confirmLot(value) {
    const normalized = String(value ?? lotInput).trim()
    setLotInput(normalized)
    setLotConfirmed(Boolean(normalized))
    if (normalized) {
      setKeypad(current => (current?.field === 'lot' ? null : current))
      setActiveField(current => (current === 'lot' ? null : current))
    }
  }

  async function createVolume(volTypeId) {
    setSubmitting(true)
    try {
      const created = await separationApi.executionCreateVolume(orderPickingId, volTypeId || defaultVolTypeId)
      const vol = { id: String(created.vol_num), label: String(created.label || created.vol_num), vol_type_id: created.vol_type_id }
      setDestinationVolumes(current => [...current, vol])
      setActiveVolumeId(vol.id)
      return vol
    } catch (error) {
      toast(error.message || 'Erro ao criar novo volume', 'error')
      return null
    } finally {
      setSubmitting(false)
    }
  }

  function addVolume() {
    createVolume(defaultVolTypeId)
  }

  function includeDrainableBox(volNum) {
    const label = String(volNum || '').trim()
    if (!label) return
    const existing = destinationVolumes.find(vol => vol.label === label)
    if (existing) {
      setActiveVolumeId(existing.id)
      return
    }
    setDestinationVolumes(current => [
      ...current,
      { id: label, label, vol_type_id: currentLine?.vol_type_id || '', existing: true },
    ])
    setActiveVolumeId(label)
    toast(`Caixa ${label} incluída como volume destino — vai ser esvaziada nesta separação.`, 'success')
  }

  function openKeypad(field, mode, label) {
    setActiveField(field)
    setKeypad({ field, mode, label })
    fieldRefs[field]?.current?.focus()
  }

  function keypadHintFor(field) {
    if (!currentLine) return null
    if (field === 'volNum') return `Caixa a procurar: ${currentLine.vol_num || '—'}`
    if (field === 'item') return `Artigo a procurar: ${currentLine.item_id}`
    if (field === 'qty') {
      if (currentLine.qty_picked > 0) {
        return `Pedido: ${currentLine.qty_to_pick} — já separaste ${currentLine.qty_picked} — falta ${pickCeiling}`
      }
      return boxAvailableQty != null
        ? `Quantidade pedida: ${currentLine.qty_to_pick} (caixa tem ${boxAvailableQty})`
        : `Quantidade pedida: ${currentLine.qty_to_pick}`
    }
    return null
  }

  function keypadNoticeFor(field) {
    if (field !== 'volNum' || !currentLine) return null
    const alreadyIncluded = destinationVolumes.some(vol => vol.label === currentLine.vol_num)
    if (!currentLine.box_fully_drainable || alreadyIncluded) return null
    return {
      icon: '♻️',
      text: `Caixa ${currentLine.vol_num} fica vazia — toca para a usar como volume destino`,
      onAction: () => includeDrainableBox(currentLine.vol_num),
    }
  }

  function closeKeypad() {
    setKeypad(null)
    setActiveField(null)
  }

  function handleKeypadInput(char) {
    if (!keypad) return
    if (keypad.field === 'location') setLocationInput(current => current + char)
    if (keypad.field === 'lot') setLotInput(current => current + char)
    if (keypad.field === 'volNum') setVolNumInput(current => current + char)
    if (keypad.field === 'qty') setQtyInput(current => (current === '0' ? char : current + char))
    if (keypad.field === 'item') setItemScanInput(current => current + char)
  }

  function handleKeypadBackspace() {
    if (!keypad) return
    if (keypad.field === 'location') setLocationInput(current => current.slice(0, -1))
    if (keypad.field === 'lot') setLotInput(current => current.slice(0, -1))
    if (keypad.field === 'volNum') setVolNumInput(current => current.slice(0, -1))
    if (keypad.field === 'qty') setQtyInput(current => current.slice(0, -1))
    if (keypad.field === 'item') setItemScanInput(current => current.slice(0, -1))
  }

  function keypadValue() {
    if (!keypad) return ''
    switch (keypad.field) {
      case 'location': return locationInput
      case 'lot': return lotInput
      case 'volNum': return volNumInput
      case 'qty': return qtyInput
      case 'item': return itemScanInput
      default: return ''
    }
  }

  function handleKeypadConfirm() {
    if (!keypad) return
    if (keypad.field === 'location') { confirmLocation(); closeKeypad() }
    else if (keypad.field === 'volNum') { confirmBox() }
    else if (keypad.field === 'lot') { confirmLot(); closeKeypad() }
    else if (keypad.field === 'item') { confirmItemScan(itemScanInput); closeKeypad() }
  }

  function goPrevLine() {
    if (currentIndex === 0) return
    setCurrentIndex(current => current - 1)
  }

  async function goNextLine() {
    if (currentLine && step?.key === 'ready' && activeVolume && !currentLine.picking_completed) {
      setSubmitting(true)
      let result
      try {
        result = await separationApi.executionPickLine(orderPickingId, currentLine.row_number, {
          location_origin: locationInput,
          vol_num: currentLine.has_volumes ? volNumInput : '',
          lot: currentLine.has_lots ? lotInput : '',
          qty_picked: Number(qtyInput || 0),
          vol_type_id_dest: activeVolume.vol_type_id,
          vol_num_dest: activeVolume.label,
        })
      } catch (error) {
        toast(error.message || 'Erro ao gravar separação da linha', 'error')
        setSubmitting(false)
        return
      }
      setSubmitting(false)
      const rowNumber = currentLine.row_number
      const hasVolumes = currentLine.has_volumes
      const hasLots = currentLine.has_lots
      const qtyPickedTotal = result.qty_picked_total ?? Number(qtyInput || 0)
      const isComplete = Boolean(result.picking_completed)
      const updatedLine = {
        ...currentLine,
        qty_picked: qtyPickedTotal,
        picking_completed: isComplete,
        vol_type_id_dest: activeVolume.vol_type_id,
        vol_num_dest: activeVolume.label,
        location_origin: locationInput || currentLine.location_origin,
        vol_num: hasVolumes ? (volNumInput || currentLine.vol_num) : currentLine.vol_num,
        lot: hasLots ? lotInput : currentLine.lot,
      }
      setLines(current => current.map(line => (line.row_number === rowNumber ? updatedLine : line)))

      if (!isComplete) {
        const missing = Math.max(0, currentLine.qty_to_pick - qtyPickedTotal)
        toast(`Já separaste ${qtyPickedTotal} de ${currentLine.qty_to_pick} — faltam ${missing} unidades. Indica outra caixa.`, 'success')
        resetPendingLineFields(updatedLine)
        return
      }
    }
    if (currentIndex + 1 >= lines.length) {
      toast('Chegaste à última linha desta ordem.', 'success')
      return
    }
    setCurrentIndex(current => current + 1)
  }

  async function deleteEntry(entry) {
    setSubmitting(true)
    try {
      await separationApi.executionUnpickLine(orderPickingId, entry.row_number)
    } catch (error) {
      toast(error.message || 'Erro ao remover artigo da caixa', 'error')
      setSubmitting(false)
      return
    }
    setSubmitting(false)
    setLines(current => current.map(line => (
      line.row_number === entry.row_number
        ? { ...line, qty_picked: 0, picking_completed: false, vol_type_id_dest: '', vol_num_dest: '' }
        : line
    )))
    const idx = lines.findIndex(line => line.row_number === entry.row_number)
    if (idx >= 0) setCurrentIndex(idx)
    setContentsOpen(false)
    toast(`${entry.item_id} removido da caixa — linha disponível para nova separação.`, 'success')
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.loading}>A carregar separação…</div>
      </div>
    )
  }

  if (!currentLine) {
    return (
      <div className={styles.page}>
        <button type="button" className={styles.backBtn} onClick={() => navigate('/execucao-separacoes')}>← Voltar</button>
        <ResultBanner ok title="Sem linhas" detail="Esta ordem não tem linhas para separar." />
      </div>
    )
  }

  function fieldClass(stepKey, fieldKey = stepKey) {
    return `${styles.field} ${(activeField === fieldKey || step.key === stepKey) ? styles.fieldActive : ''}`
  }

  function handleCalloutTap() {
    if (step.key === 'location' && locationEditable) openKeypad('location', 'text', 'Localização origem')
    else if (step.key === 'box') openKeypad('volNum', 'numeric', 'Nº de volume (caixa de origem)')
    else if (step.key === 'lot' && lotEditable) openKeypad('lot', 'text', 'Lote')
    else if (step.key === 'item') openKeypad('item', 'text', 'Ler código de artigo')
    else if (step.key === 'qty' && params.picking_confirm_mode === 'NONE') openKeypad('qty', 'numeric', 'Quantidade')
  }

  return (
    <div className={styles.page}>
      <div className={styles.stickyHeader}>
        <div className={styles.topBar}>
          <button type="button" className={styles.backBtn} onClick={() => navigate('/execucao-separacoes')} aria-label="Voltar">←</button>
          <div className={styles.docLabel}>
            <strong>{header?.related_doc_type ? `${header.related_doc_type}.${header.related_order_id}` : `OP ${header?.order_picking_id}`}</strong>
          </div>
          {currentLine.equip_id_origin && (
            <span className={styles.equipBadge} title="Tipo de equipamento">{currentLine.equip_id_origin}</span>
          )}
        </div>

        <div className={`${styles.volumePanel} ${step.key === 'volume' ? styles.volumePanelRequired : ''}`}>
          <div className={styles.volumePanelHeader}>
            <span className={styles.volumePanelLabel}>Volume novo</span>
            {activeVolume?.vol_type_id && <span className={styles.volumePanelType}>{activeVolume.vol_type_id}</span>}
          </div>
          <div className={styles.volumePanelMain}>
            <div className={styles.volumePanelBig}>{activeVolume ? activeVolume.label : 'Sem volume'}</div>
            <div className={styles.volumePanelSide}>
              <div className={styles.volumePanelLineCounter}>L: {currentIndex + 1}/{lines.length}</div>
              {activeVolume && (
                <button type="button" className={styles.contentsBtn} onClick={() => setContentsOpen(true)}>
                  📋 Conteúdo ({activeVolumeEntries.length})
                </button>
              )}
            </div>
          </div>
          <div className={styles.volumesChips}>
            {destinationVolumes.map(vol => (
              <button
                key={vol.id}
                type="button"
                className={`${styles.volChip} ${activeVolumeId === vol.id ? styles.volChipActive : ''}`}
                onClick={() => setActiveVolumeId(vol.id)}
              >
                {vol.existing ? '📦 ' : ''}{vol.label}
              </button>
            ))}
            <button type="button" className={styles.addVolBtn} onClick={addVolume} disabled={submitting}>+ Novo volume</button>
          </div>
        </div>

        <div className={styles.infoRow}>
          {currentLine.has_volumes && (
            <div className={styles.infoTile}>
              <span className={styles.infoTileLabel}>📦 Caixa origem</span>
              <span className={styles.infoTileValue}>{currentLine.vol_num || '—'}</span>
            </div>
          )}
          <div className={styles.infoTile}>
            <span className={styles.infoTileLabel}>📍 Localização {currentLine.location_is_suggested && <em>(sugerida)</em>}</span>
            <span className={styles.infoTileValue}>{currentLine.location_origin || '—'}</span>
          </div>
        </div>

        <Card className={styles.itemInfoTile}>
          <span className={styles.infoTileLabel}>🔎 Artigo a buscar</span>
          <div className={styles.itemCode}>{currentLine.item_id}</div>
          <div className={styles.itemDesc}>{currentLine.item_desc}</div>
          {currentLine.qty_picked > 0 && !currentLine.picking_completed && (
            <div className={styles.partialProgress}>
              ⚠️ Já separaste {currentLine.qty_picked} de {currentLine.qty_to_pick} — faltam {remainingQty} unidades
            </div>
          )}
        </Card>

        <button type="button" className={`${styles.stepCallout} ${styles[`stepCallout_${step.key}`] || ''}`} onClick={handleCalloutTap}>
          <span className={styles.stepIcon}>{step.icon}</span>
          <span className={styles.stepText}>
            <strong>{step.label}</strong>
            {step.value && <span className={styles.stepValue}>{step.value}</span>}
          </span>
        </button>

        {step.key === 'volume' && (
          <div className={styles.volumeGate}>
            <p>Cria um <strong>volume novo</strong> acima para poderes iniciar a separação desta ordem.</p>
          </div>
        )}
      </div>

      {step.key !== 'volume' && (
      <div className={styles.scrollBody}>
      <div className={styles.fieldsGrid}>
        <label className={`${fieldClass('location')} ${styles.locationField}`}>
          <span className={styles.locationLabel}>📍 Localização origem {currentLine.location_is_suggested && <em>(sugerida)</em>}</span>
          <input
            ref={fieldRefs.location}
            className={styles.locationInput}
            value={locationInput}
            readOnly={!locationEditable}
            onFocus={() => locationEditable && openKeypad('location', 'text', 'Localização origem')}
            onChange={(event) => setLocationInput(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && confirmLocation(event.currentTarget.value)}
            onBlur={(event) => confirmLocation(event.target.value)}
          />
        </label>

        {currentLine.has_volumes && (
          <div className={styles.boxGroup}>
            <span className={styles.groupLabel}>Caixa a separar (origem)</span>
            <div className={styles.boxGroupRow}>
              <label className={styles.field}>
                <span>Tipo</span>
                <select value={volTypeInput} onChange={(event) => setVolTypeInput(event.target.value)}>
                  {volTypeOptions.length ? (
                    volTypeOptions.map(option => (
                      <option key={option.vol_type_id} value={option.vol_type_id}>{option.vol_doc_cod}</option>
                    ))
                  ) : (
                    <option value={volTypeInput}>{volTypeInput}</option>
                  )}
                </select>
              </label>
              <label className={fieldClass('box', 'volNum')}>
                <span>Nº de volume{boxConfirmed ? ' ✓' : ''}</span>
                <input
                  ref={fieldRefs.volNum}
                  value={volNumInput}
                  placeholder={currentLine.vol_num || ''}
                  onFocus={() => openKeypad('volNum', 'numeric', 'Nº de volume (caixa de origem)')}
                  onChange={(event) => setVolNumInput(event.target.value)}
                  onKeyDown={(event) => event.key === 'Enter' && confirmBox(event.currentTarget.value)}
                  onBlur={(event) => confirmBox(event.target.value)}
                />
              </label>
            </div>
            {currentLine.box_fully_drainable && !destinationVolumes.some(vol => vol.label === currentLine.vol_num) && (
              <div className={styles.drainableHint}>
                <span>✅ Esta caixa fica vazia com esta separação — podes usá-la como volume destino (opcional).</span>
                <button type="button" className={styles.drainableBtn} onClick={() => includeDrainableBox(currentLine.vol_num)}>
                  Incluir caixa {currentLine.vol_num}
                </button>
              </div>
            )}
          </div>
        )}

        {currentLine.has_lots && (
          <label className={fieldClass('lot')}>
            <span>Lote</span>
            <input
              ref={fieldRefs.lot}
              value={lotInput}
              readOnly={!lotEditable}
              onFocus={() => lotEditable && openKeypad('lot', 'text', 'Lote')}
              onChange={(event) => setLotInput(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && confirmLot(event.currentTarget.value)}
              onBlur={(event) => confirmLot(event.target.value)}
            />
          </label>
        )}

        <label className={fieldClass('item')}>
          <span>Ler artigo{itemConfirmed ? ' ✓' : ''}</span>
          <input
            ref={fieldRefs.item}
            value={itemScanInput}
            placeholder={currentLine.item_id}
            disabled={itemConfirmed && params.picking_confirm_mode !== 'READ_ALL'}
            onFocus={() => openKeypad('item', 'text', 'Ler código de artigo')}
            onChange={(event) => setItemScanInput(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && confirmItemScan(event.currentTarget.value)}
          />
        </label>

        <label className={fieldClass('qty')}>
          <span>
            Quantidade a separar (pedida: {currentLine.qty_to_pick}
            {currentLine.qty_picked > 0 ? `, já separada: ${currentLine.qty_picked}, falta: ${remainingQty}` : ''}
            {boxAvailableQty != null ? `, disponível na caixa: ${boxAvailableQty}` : ''})
          </span>
          <input
            ref={fieldRefs.qty}
            type={params.picking_confirm_mode === 'NONE' ? 'number' : 'text'}
            value={qtyInput}
            max={Number.isFinite(pickCeiling) ? pickCeiling : undefined}
            readOnly={params.picking_confirm_mode !== 'NONE'}
            onFocus={() => params.picking_confirm_mode === 'NONE' && openKeypad('qty', 'numeric', 'Quantidade')}
            onChange={(event) => setQtyInput(event.target.value)}
          />
          {qtyExceedsStock && <small className={styles.fieldError}>Quantidade acima da existência na caixa não é permitida.</small>}
          {qtyExceedsRequested && <small className={styles.fieldError}>Quantidade acima do pedido não é permitida.</small>}
        </label>
      </div>
      </div>
      )}

      <div className={styles.navRow}>
        <button type="button" className={styles.prevBtn} disabled={currentIndex === 0} onClick={goPrevLine}>
          ◀ Anterior
        </button>
        <button type="button" className={styles.nextBtn} disabled={currentIndex + 1 >= lines.length || submitting} onClick={goNextLine}>
          Seguinte ▶
        </button>
      </div>

      {keypad && (
        <TouchKeypad
          mode={keypad.mode}
          label={keypad.label}
          hint={keypadHintFor(keypad.field)}
          notice={keypadNoticeFor(keypad.field)}
          value={keypadValue()}
          placeholder={keypad.field === 'item' ? currentLine.item_id : ''}
          onKey={handleKeypadInput}
          onBackspace={handleKeypadBackspace}
          onConfirm={handleKeypadConfirm}
          onClose={closeKeypad}
        />
      )}

      {contentsOpen && activeVolume && (
        <div className={styles.contentsOverlay} role="dialog" aria-label="Conteúdo da caixa">
          <div className={styles.contentsPanel}>
            <div className={styles.contentsHeader}>
              <span>Conteúdo — {activeVolume.label}</span>
              <button type="button" className={styles.closeBtn} onClick={() => setContentsOpen(false)} aria-label="Fechar">×</button>
            </div>
            <div className={styles.contentsList}>
              {activeVolumeEntries.length === 0 && (
                <div className={styles.contentsEmpty}>Ainda sem artigos separados para esta caixa.</div>
              )}
              {activeVolumeEntries.map(entry => (
                <div key={entry.row_number} className={styles.contentsRow}>
                  <div className={styles.contentsRowInfo}>
                    <strong>{entry.item_id}</strong>
                    <span>{entry.item_desc}</span>
                  </div>
                  <div className={styles.contentsRowQty}>{entry.qty_picked}</div>
                  <button type="button" className={styles.contentsDeleteBtn} onClick={() => deleteEntry(entry)} disabled={submitting} aria-label={`Remover ${entry.item_id}`}>
                    🗑️
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
