import { useEffect, useMemo, useState } from 'react'
import { Btn, Card, CardTitle, ResultBanner, Stat, StatsBar, Steps } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { separationApi } from '../services/api'
import styles from './SeparationDocument.module.css'

function lineKey(line) {
  return `${line.origin_doc_type}:${line.origin_order_id}:${line.origin_order_row}:${line.origin_size_id || ''}:${line.origin_color_id || ''}:${line.origin_grid_id || ''}`
}

function lineGroupKey(line) {
  return `${line.origin_doc_type}:${line.origin_order_id}:${line.origin_order_row}:${line.item_id}`
}

function todayString() {
  return new Date().toISOString().slice(0, 10)
}

function sumAllocations(allocations = []) {
  return allocations.reduce((sum, allocation) => sum + Number(allocation.qty || 0), 0)
}

function clampAllocationQty(value, maxAllowed) {
  const numeric = Number(value || 0)
  if (!Number.isFinite(numeric) || numeric <= 0) return 0
  return Math.min(numeric, Math.max(0, maxAllowed))
}

function safeText(value) {
  return String(value ?? '')
}

function formatQty(value) {
  const numeric = Number(value || 0)
  if (!Number.isFinite(numeric)) return '0'
  return Number.isInteger(numeric) ? String(numeric) : numeric.toLocaleString('pt-PT')
}

function boxSizeFilter(line, itemId) {
  return itemId === line.item_id ? (line.origin_size_id || '') : ''
}

export default function SeparationDocument() {
  const toast = useToast()

  const [config, setConfig] = useState(null)
  const [warehouses, setWarehouses] = useState([])
  const [docTypes, setDocTypes] = useState([])
  const [partners, setPartners] = useState([])
  const [documents, setDocuments] = useState([])
  const [documentLines, setDocumentLines] = useState([])
  const [lineState, setLineState] = useState({})

  const [docType, setDocType] = useState('')
  const [partnerSearch, setPartnerSearch] = useState('')
  const [selectedPartner, setSelectedPartner] = useState(null)
  const [documentSearch, setDocumentSearch] = useState('')
  const [itemSearch, setItemSearch] = useState('')
  const [documentSort, setDocumentSort] = useState('date_desc')
  const [selectedOrderIds, setSelectedOrderIds] = useState([])
  const [whOrigs, setWhOrigs] = useState([])
  const [obs, setObs] = useState('')
  const [executionDate, setExecutionDate] = useState(todayString())
  const [result, setResult] = useState(null)
  const [phase, setPhase] = useState(1)

  const [loadingBase, setLoadingBase] = useState(true)
  const [loadingDocuments, setLoadingDocuments] = useState(false)
  const [loadingLines, setLoadingLines] = useState(false)
  const [loadingPartners, setLoadingPartners] = useState(false)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function loadBase() {
      setLoadingBase(true)
      try {
        const [cfg, whRows, docRows] = await Promise.all([
          separationApi.config(),
          separationApi.warehouses(),
          separationApi.documentTypes(),
        ])
        if (cancelled) return
        setConfig(cfg)
        setWarehouses(whRows)
        // Pre-seleciona os armazens marcados por defeito (DocumentWarehouses); sem nenhum
        // marcado, usa todos os que já vêm restritos à configuração deste documento -
        // evita o operador ter de escolher os mesmos armazens sempre que separa.
        const defaultWhs = whRows.filter(w => w.is_default).map(w => String(w.wh_id))
        setDocTypes(docRows)
        setDocType(docRows[0]?.doc_type || '')
        setWhOrigs(defaultWhs.length ? defaultWhs : whRows.map(w => String(w.wh_id)))
      } catch (error) {
        toast(error.message || 'Erro ao carregar configuracao base', 'error')
      } finally {
        if (!cancelled) setLoadingBase(false)
      }
    }
    loadBase()
    return () => { cancelled = true }
  }, [toast])

  useEffect(() => {
    if (!docType) {
      setPartners([])
      setSelectedPartner(null)
      return
    }

    let cancelled = false
    setLoadingPartners(true)
    const timer = setTimeout(async () => {
      try {
        const rows = await separationApi.partners(docType, partnerSearch)
        if (!cancelled) setPartners(rows)
      } catch {
        if (!cancelled) setPartners([])
      } finally {
        if (!cancelled) setLoadingPartners(false)
      }
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [docType, partnerSearch])

  useEffect(() => {
    setSelectedPartner(null)
    setDocuments([])
    setDocumentSearch('')
    setItemSearch('')
    setDocumentSort('date_desc')
    setSelectedOrderIds([])
    setDocumentLines([])
    setLineState({})
    setResult(null)
    setPhase(1)
  }, [docType])

  const filteredDocuments = useMemo(() => {
    const term = documentSearch.trim().toLowerCase()
    const itemTerm = itemSearch.trim().toLowerCase()
    const filtered = documents.filter(document => {
      const matchesGeneral = !term || [
        document.doc_type,
        document.order_id,
        document.partner_id,
        document.partner_name,
        document.item_id,
        document.obs,
        document.order_date,
        document.due_date,
      ].some(value => String(value || '').toLowerCase().includes(term))

      const matchesItem = !itemTerm || String(document.item_id || '').toLowerCase().includes(itemTerm)
      return matchesGeneral && matchesItem
    })

    const sorted = [...filtered]
    sorted.sort((left, right) => {
      const leftTime = left.order_date ? new Date(left.order_date).getTime() : 0
      const rightTime = right.order_date ? new Date(right.order_date).getTime() : 0

      if (documentSort === 'date_asc') {
        if (leftTime !== rightTime) return leftTime - rightTime
        return Number(left.order_id || 0) - Number(right.order_id || 0)
      }

      if (rightTime !== leftTime) return rightTime - leftTime
      return Number(right.order_id || 0) - Number(left.order_id || 0)
    })

    return sorted
  }, [documents, documentSearch, itemSearch, documentSort])

  const enrichedLines = useMemo(() => {
    return documentLines.map(line => {
      const state = lineState[lineKey(line)] || {}
      return {
        ...line,
        state,
        selected_item_id: state.selected_item_id || line.item_id,
        selected_item_desc: state.selected_item_desc || line.item_desc,
        qty_to_separate: Number(state.qty_to_separate ?? line.qty_pending),
        allocated_qty: sumAllocations(state.allocations || []),
        qty_to_allocate: Math.max(
          0,
          Number(state.qty_to_separate ?? line.qty_pending) - sumAllocations(state.allocations || [])
        ),
      }
    })
  }, [documentLines, lineState])

  const summary = useMemo(() => {
    const activeLines = enrichedLines.filter(line => Number(line.qty_to_separate || 0) > 0)
    return {
      lines: activeLines.length,
      qty_requested: activeLines.reduce((sum, line) => sum + Number(line.qty_requested || 0), 0),
      qty_to_separate: activeLines.reduce((sum, line) => sum + Number(line.qty_to_separate || 0), 0),
      allocated_qty: activeLines.reduce((sum, line) => sum + Number(line.allocated_qty || 0), 0),
      boxes: activeLines.reduce((sum, line) => sum + Number(line.state.allocations?.length || 0), 0),
    }
  }, [enrichedLines])

  const groupedLines = useMemo(() => {
    const groups = new Map()
    enrichedLines.forEach(line => {
      const key = lineGroupKey(line)
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          item_id: line.item_id,
          item_desc: line.item_desc,
          origin_doc_type: line.origin_doc_type,
          origin_order_id: line.origin_order_id,
          origin_order_row: line.origin_order_row,
          lines: [],
        })
      }
      groups.get(key).lines.push(line)
    })
    return Array.from(groups.values()).map(group => ({
      ...group,
      lines: [...group.lines].sort((left, right) => Number(left.origin_size_order_num || 0) - Number(right.origin_size_order_num || 0)),
    }))
  }, [enrichedLines])

  async function fetchDocuments() {
    if (!docType) {
      toast('Seleciona o tipo de documento origem', 'error')
      return
    }
    if (!selectedPartner?.partner_id) {
      toast('Seleciona o parceiro a filtrar', 'error')
      return
    }
    setLoadingDocuments(true)
    try {
      const rows = await separationApi.documents(docType, selectedPartner.partner_id, documentSearch)
      setDocuments(rows)
      setSelectedOrderIds([])
      setDocumentLines([])
      setLineState({})
      if (rows.length) setPhase(2)
      if (!rows.length) {
        toast('Nao foram encontrados documentos para os filtros selecionados', 'error')
      }
    } catch (error) {
      toast(error.message || 'Erro ao carregar documentos', 'error')
      setDocuments([])
    } finally {
      setLoadingDocuments(false)
    }
  }

  async function fetchLines() {
    if (!selectedOrderIds.length) {
      toast('Seleciona pelo menos um documento origem', 'error')
      return
    }
    if (!whOrigs.length) {
      toast('Seleciona pelo menos um armazem origem', 'error')
      return
    }
    setLoadingLines(true)
    try {
      const response = await separationApi.lines({
        doc_type: docType,
        order_ids: selectedOrderIds,
        wh_ids: whOrigs.map(Number),
      })
      const lines = Array.isArray(response.lines) ? response.lines : []
      const nextState = {}
      lines.forEach(line => {
        nextState[lineKey(line)] = {
          qty_to_separate: String(line.qty_pending || 0),
          selected_item_id: line.item_id,
          selected_item_desc: line.item_desc,
          allow_without_boxes: true,
          wh_id_orig: whOrigs[0] || '',
          expanded: false,
          substitute_search: '',
          substitute_results: [],
          loading_substitutes: false,
          boxes: [],
          loading_boxes: false,
          allocations: [],
        }
      })
      setDocumentLines(lines)
      setLineState(nextState)
      setResult(null)
      if (lines.length) setPhase(3)
      toast(`${lines.length} linha(s) carregada(s) para separacao`)
    } catch (error) {
      toast(error.message || 'Erro ao carregar linhas', 'error')
      setDocumentLines([])
      setLineState({})
    } finally {
      setLoadingLines(false)
    }
  }

  function toggleWarehouse(whId) {
    const value = String(whId)
    setWhOrigs(current =>
      current.includes(value)
        ? current.filter(id => id !== value)
        : [...current, value]
    )
  }

  function toggleOrder(orderId) {
    setSelectedOrderIds(current =>
      current.includes(orderId)
        ? current.filter(value => value !== orderId)
        : [...current, orderId]
    )
  }

  function updateLineState(key, updater) {
    setLineState(current => ({
      ...current,
      [key]: {
        ...(current[key] || {}),
        ...(typeof updater === 'function' ? updater(current[key] || {}) : updater),
      },
    }))
  }

  function updateGroupLineState(line, updater) {
    const targetGroupKey = lineGroupKey(line)
    setLineState(current => {
      const nextState = { ...current }
      documentLines.forEach(candidate => {
        if (lineGroupKey(candidate) !== targetGroupKey) return
        const key = lineKey(candidate)
        const currentValue = current[key] || {}
        nextState[key] = {
          ...currentValue,
          ...(typeof updater === 'function' ? updater(currentValue, candidate) : updater),
        }
      })
      return nextState
    })
  }

  function remainingQtyForLine(line, excludeVolNum = '') {
    const key = lineKey(line)
    const current = lineState[key] || {}
    const allocations = Array.isArray(current.allocations) ? current.allocations : []
    const allocated = allocations.reduce((sum, allocation) => {
      if (excludeVolNum && allocation.vol_num === excludeVolNum) return sum
      return sum + Number(allocation.qty || 0)
    }, 0)
    return Math.max(0, Number(current.qty_to_separate ?? line.qty_pending ?? 0) - allocated)
  }

  async function searchSubstitutes(line) {
    const key = lineKey(line)
    const current = lineState[key] || {}
    const term = String(current.substitute_search || '').trim()
    if (!term || term.length < 2) {
      toast('Indica pelo menos 2 caracteres para procurar artigo substituto', 'error')
      return
    }

    updateGroupLineState(line, { loading_substitutes: true })
    try {
      const rows = await separationApi.searchItems(whOrigs[0], term)
      updateGroupLineState(line, { substitute_results: rows })
    } catch (error) {
      toast(error.message || 'Erro ao procurar artigos', 'error')
      updateGroupLineState(line, { substitute_results: [] })
    } finally {
      updateGroupLineState(line, { loading_substitutes: false })
    }
  }

  async function loadBoxes(line) {
    const key = lineKey(line)
    const current = lineState[key] || {}
    const itemId = current.selected_item_id || line.item_id
    const sizeId = boxSizeFilter(line, itemId)
    updateLineState(key, { loading_boxes: true })
    try {
      const rows = await separationApi.itemBoxes(itemId, whOrigs.map(Number), sizeId)
      updateLineState(key, { boxes: rows })
    } catch (error) {
      toast(error.message || 'Erro ao carregar caixas', 'error')
      updateLineState(key, { boxes: [] })
    } finally {
      updateLineState(key, { loading_boxes: false })
    }
  }

  async function selectSubstitute(line, item) {
    const key = lineKey(line)
    const sizeId = boxSizeFilter(line, item.item_id)
    updateLineState(key, {
      selected_item_id: item.item_id,
      selected_item_desc: item.item_desc,
      boxes: [],
      allocations: [],
    })
    try {
      updateLineState(key, { loading_boxes: true })
      const rows = await separationApi.itemBoxes(item.item_id, whOrigs.map(Number), sizeId)
      updateLineState(key, { boxes: rows })
    } catch (error) {
      toast(error.message || 'Erro ao carregar caixas', 'error')
      updateLineState(key, { boxes: [] })
    } finally {
      updateLineState(key, { loading_boxes: false })
    }
  }

  async function toggleLineExpanded(line) {
    const key = lineKey(line)
    const current = lineState[key] || {}
    const nextExpanded = !current.expanded
    updateLineState(key, { expanded: nextExpanded })
    if (nextExpanded && !current.loading_boxes && (!Array.isArray(current.boxes) || current.boxes.length === 0)) {
      await loadBoxes(line)
    }
  }

  function updateAllocation(line, box, qtyValue) {
    const key = lineKey(line)
    const remaining = remainingQtyForLine(line, box.vol_num)
    const maxAllowed = Math.min(Number(box.qty_stock || 0), remaining)
    const qty = clampAllocationQty(qtyValue, maxAllowed)
    updateLineState(key, current => {
      const allocations = Array.isArray(current.allocations) ? [...current.allocations] : []
      const existingIndex = allocations.findIndex(allocation => allocation.vol_num === box.vol_num)
      if (qty <= 0) {
        if (existingIndex >= 0) allocations.splice(existingIndex, 1)
      } else {
        const otherWh = allocations.find(allocation => allocation.vol_num !== box.vol_num && Number(allocation.wh_id) !== Number(box.wh_id))
        if (otherWh) {
          toast('Esta linha já tem caixas de outro armazém selecionadas — usa apenas caixas do mesmo armazém nesta linha.', 'error')
          return current
        }
        const next = {
          vol_num: safeText(box.vol_num),
          barcode: safeText(box.barcode),
          location_id: safeText(box.location_id),
          wh_id: Number(box.wh_id || 0),
          qty,
        }
        if (existingIndex >= 0) allocations[existingIndex] = next
        else allocations.push(next)
      }
      return { allocations }
    })
  }

  function focusBoxQtyInput(line, box) {
    const inputId = `box-qty-${lineKey(line).replace(/[^a-zA-Z0-9_-]/g, '-')}-${String(box.vol_num)}`
    window.setTimeout(() => {
      const input = document.getElementById(inputId)
      if (input) {
        input.focus()
        input.select?.()
      }
    }, 0)
  }

  function toggleBoxSelection(line, box, checked) {
    const remaining = remainingQtyForLine(line, box.vol_num)
    const proposedQty = Math.min(Number(box.qty_stock || 0), remaining)
    if (checked) {
      updateAllocation(line, box, proposedQty)
      focusBoxQtyInput(line, box)
      return
    }
    updateAllocation(line, box, 0)
  }

  async function createDocument() {
    const activeLines = enrichedLines.filter(line => Number(line.qty_to_separate || 0) > 0)
    if (!activeLines.length) {
      toast('Nao existem linhas com quantidade para separar', 'error')
      return
    }
    if (!whOrigs.length) {
      toast('Seleciona pelo menos um armazem origem', 'error')
      return
    }
    if (!selectedPartner?.partner_id) {
      toast('Seleciona o parceiro', 'error')
      return
    }
    if (!executionDate) {
      toast('Indica a data de execucao da separacao', 'error')
      return
    }

    for (const line of activeLines) {
      const qtyToSeparate = Number(line.qty_to_separate || 0)
      const allocatedQty = Number(line.allocated_qty || 0)
      if (qtyToSeparate > Number(line.qty_pending || 0)) {
        toast(`A linha ${line.origin_order_id}/${line.origin_order_row} excede o saldo disponivel`, 'error')
        return
      }
      if (allocatedQty > qtyToSeparate) {
        toast(`A linha ${line.origin_order_id}/${line.origin_order_row} tem mais quantidade em caixas do que a quantidade a separar`, 'error')
        return
      }
      if (!line.state.allow_without_boxes && allocatedQty <= 0) {
        toast(`A linha ${line.origin_order_id}/${line.origin_order_row} precisa de caixas ou validacao sem caixas`, 'error')
        return
      }
      if (!line.state.allocations?.length && !line.state.wh_id_orig) {
        toast(`A linha ${line.origin_order_id}/${line.origin_order_row} precisa de um armazem de origem`, 'error')
        return
      }
    }

    setCreating(true)
    try {
      const response = await separationApi.create({
        origin_doc_type: docType,
        partner_id: selectedPartner.partner_id,
        execution_date: executionDate,
        obs,
        lines: activeLines.map(line => {
          const allocations = line.state.allocations || []
          // O armazem da linha vem das caixas escolhidas (todas da mesma origem, ja
          // validado em updateAllocation); sem caixas, usa o armazem escolhido para a linha.
          const lineWhId = allocations.length ? allocations[0].wh_id : Number(line.state.wh_id_orig || whOrigs[0])
          return {
            origin_doc_type: line.origin_doc_type,
            origin_order_id: line.origin_order_id,
            origin_order_row: line.origin_order_row,
            origin_part_num: 0,
            origin_color_id: line.origin_color_id || '',
            origin_grid_id: line.origin_grid_id || '',
            origin_size_id: line.origin_size_id || '',
            origin_size_order_num: Number(line.origin_size_order_num || 0),
            item_id: line.item_id,
            substitute_item_id: line.selected_item_id !== line.item_id ? line.selected_item_id : '',
            qty_requested: line.qty_requested,
            qty_done: line.qty_done,
            qty_pending: line.qty_pending,
            qty_to_separate: line.qty_to_separate,
            allow_without_boxes: Boolean(line.state.allow_without_boxes),
            wh_id_orig: lineWhId,
            allocations: allocations.map(allocation => ({
              vol_num: safeText(allocation.vol_num),
              barcode: safeText(allocation.barcode),
              location_id: safeText(allocation.location_id),
              qty: Number(allocation.qty || 0),
            })),
          }
        }),
      })
      setResult(response)
      window.scrollTo({ top: 0, behavior: 'smooth' })
      const separations = response.separations || []
      if (response.linked && separations.length > 1) {
        toast(`${separations.length} documentos de separação criados e interligados (${separations.map(s => `#${s.order_id}`).join(', ')})`)
      } else if (separations.length) {
        toast(`Documento ${separations[0].doc_type} #${separations[0].order_id} criado com sucesso`)
      }
    } catch (error) {
      toast(error.message || 'Erro ao criar documento de separacao', 'error')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Criação de Documento de Separação</h1>
        <p className={styles.pageDesc}>
          Seleciona o armazém, os documentos origem e as linhas a preparar para gerar um documento-guia de separação.
        </p>
      </div>

      <StatsBar>
        <Stat label="Documentos" value={selectedOrderIds.length} color="var(--accent)" />
        <Stat label="Linhas" value={summary.lines} color="var(--green)" />
        <Stat label="Qtd. separar" value={summary.qty_to_separate} color="var(--yellow)" />
        <Stat label="Caixas" value={summary.boxes} color="var(--red)" />
      </StatsBar>

      <div className={styles.stepsWrap}>
        <Steps
          steps={[
            'Filtros',
            'Documentos origem',
            'Artigos e caixas',
          ]}
          current={phase}
        />
      </div>

      {result && (result.separations || []).map(separation => (
        <ResultBanner
          key={separation.picking_order_id}
          ok
          title={`${separation.title || separation.doc_type} #${separation.order_id} criado${result.linked ? ' 🔗 (armazém ' + separation.wh_id_orig + ')' : ''}`}
          detail={`Linhas: ${separation.total_lines}. Quantidade: ${separation.total_qty}. Caixas selecionadas: ${separation.total_boxes}. Execução: ${result.execution_date}.${result.linked ? ` Interligada ao grupo ${result.order_picking_group}.` : ''}`}
        />
      ))}

      {config && !config.exists && (
        <ResultBanner
          ok={false}
          title="DocType de separação não configurado"
          detail={`O backend está preparado para usar '${config.doc_type}', mas esse DocType ainda não existe em DocumentConfig.`}
        />
      )}

      {phase === 1 && (
        <Card>
          <CardTitle>Fase 1 · Filtros</CardTitle>
          {loadingBase ? (
            <div className={styles.empty}>A carregar configuração base...</div>
          ) : (
            <>
              <div className={styles.grid}>
                <div className={`${styles.field} ${styles.fieldSpan}`}>
                  <label>Armazém(ns) origem {whOrigs.length > 1 && <em>— separações interligadas por armazém</em>}</label>
                  <div className={styles.warehouseList}>
                    {warehouses.map(warehouse => (
                      <label key={warehouse.wh_id} className={styles.warehouseOption}>
                        <input
                          type="checkbox"
                          checked={whOrigs.includes(String(warehouse.wh_id))}
                          onChange={() => toggleWarehouse(warehouse.wh_id)}
                        />
                        {warehouse.wh_id} - {warehouse.wh_desc}
                      </label>
                    ))}
                  </div>
                </div>

                <div className={styles.field}>
                  <label>Tipo documento origem</label>
                  <select className={styles.select} value={docType} onChange={e => setDocType(e.target.value)}>
                    {docTypes.map(type => (
                      <option key={type.doc_type} value={type.doc_type}>
                        {type.doc_type} - {type.title}
                      </option>
                    ))}
                  </select>
                </div>

                <div className={`${styles.field} ${styles.fieldSpan}`}>
                  <label>Business partner</label>
                  {selectedPartner ? (
                    <div className={styles.selectedPartner}>
                      <div>
                        <strong>{selectedPartner.partner_id}</strong> {selectedPartner.partner_name}
                        {(selectedPartner.city || selectedPartner.vat_no) && (
                          <span className={styles.partnerMeta}>
                            {[selectedPartner.city, selectedPartner.vat_no && `NIF ${selectedPartner.vat_no}`]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                        )}
                      </div>
                      <Btn variant="outline" onClick={() => setSelectedPartner(null)}>Trocar</Btn>
                    </div>
                  ) : (
                    <>
                      <input
                        className={styles.input}
                        value={partnerSearch}
                        onChange={e => setPartnerSearch(e.target.value)}
                        placeholder="Pesquisar por nome, número ou NIF"
                        autoFocus
                      />
                      <div className={styles.pickList}>
                        {loadingPartners ? (
                          <div className={styles.pickHint}>A procurar...</div>
                        ) : partners.length === 0 ? (
                          <div className={styles.pickHint}>
                            {partnerSearch.trim()
                              ? `Nenhum parceiro encontrado para "${partnerSearch.trim()}".`
                              : 'Sem parceiros para este tipo de documento.'}
                          </div>
                        ) : (
                          partners.map(partner => (
                            <button
                              key={partner.partner_id}
                              type="button"
                              className={styles.pickItem}
                              onClick={() => setSelectedPartner(partner)}
                            >
                              <strong>{partner.partner_id}</strong> {partner.partner_name}
                              {(partner.city || partner.vat_no) && (
                                <span className={styles.partnerMeta}>
                                  {[partner.city, partner.vat_no && `NIF ${partner.vat_no}`]
                                    .filter(Boolean)
                                    .join(' · ')}
                                </span>
                              )}
                            </button>
                          ))
                        )}
                        {partners.length >= 50 && (
                          <div className={styles.pickHint}>
                            Mostrando os primeiros 50 resultados — refine a pesquisa para encontrar mais depressa.
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>

                <div className={styles.field}>
                  <label>Data de execução</label>
                  <input className={styles.input} type="date" value={executionDate} onChange={e => setExecutionDate(e.target.value)} />
                </div>

                <div className={`${styles.field} ${styles.fieldSpan}`}>
                  <label>Observação / identificação</label>
                  <textarea
                    className={styles.textarea}
                    value={obs}
                    onChange={e => setObs(e.target.value)}
                    placeholder="Texto que ficará no campo ClientOrders.Obs"
                  />
                </div>
              </div>

              <div className={styles.phaseFooter}>
                <div className={styles.phaseHint}>
                  Define os filtros e carrega só os documentos relevantes para a fase seguinte.
                </div>
                <Btn onClick={fetchDocuments} loading={loadingDocuments}>
                  Avançar para Fase 2
                </Btn>
              </div>
            </>
          )}
        </Card>
      )}

      {phase === 2 && (
        <Card>
          <CardTitle>Fase 2 · Seleção dos documentos origem</CardTitle>
          <div className={styles.toolbar}>
            <input
              className={styles.input}
              value={documentSearch}
              onChange={e => setDocumentSearch(e.target.value)}
              placeholder="Filtrar por número, artigo, parceiro, data ou observação"
            />
            <input
              className={styles.input}
              value={itemSearch}
              onChange={e => setItemSearch(e.target.value)}
              placeholder="Filtrar por artigo"
            />
            <select
              className={styles.select}
              value={documentSort}
              onChange={e => setDocumentSort(e.target.value)}
            >
              <option value="date_desc">Data descrescente</option>
              <option value="date_asc">Data crescente</option>
            </select>
            <Btn variant="outline" onClick={() => setPhase(1)}>← Voltar aos filtros</Btn>
            <Btn onClick={fetchDocuments} loading={loadingDocuments}>Atualizar documentos</Btn>
            <Btn variant="outline" onClick={fetchLines} loading={loadingLines}>Avançar para Fase 3</Btn>
          </div>
          <div className={styles.phaseSummary}>
            <span>Parceiro: {selectedPartner?.partner_name || selectedPartner?.partner_id || '—'}</span>
            <span>Tipo: {docType || '—'}</span>
            <span>Selecionados: {selectedOrderIds.length}</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th />
                  <th>Tipo</th>
                  <th>Número</th>
                  <th>Artigo</th>
                  <th>Parceiro</th>
                  <th>Data</th>
                  <th>Prevista</th>
                  <th>Saldo a separar</th>
                  <th>Linhas</th>
                  <th>Obs.</th>
                </tr>
              </thead>
              <tbody>
                {filteredDocuments.length === 0 && (
                  <tr>
                    <td colSpan="10" className={styles.emptyCell}>Sem documentos carregados.</td>
                  </tr>
                )}
                {filteredDocuments.map(document => (
                  <tr key={`${document.doc_type}-${document.order_id}`}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedOrderIds.includes(document.order_id)}
                        onChange={() => toggleOrder(document.order_id)}
                      />
                    </td>
                    <td>{document.doc_type}</td>
                    <td>{document.order_id}</td>
                    <td>{document.item_id || '-'}</td>
                    <td>{document.partner_name || document.partner_id}</td>
                    <td>{document.order_date || '-'}</td>
                    <td>{document.due_date || '-'}</td>
                    <td><strong>{formatQty(document.total_qty)}</strong></td>
                    <td>{document.total_lines}</td>
                    <td>{document.obs || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {phase === 3 && (
        <Card>
          <CardTitle>Fase 3 · Artigos e caixas da ordem de separação</CardTitle>
          <div className={styles.toolbar}>
            <Btn variant="outline" onClick={() => setPhase(2)}>← Voltar aos documentos</Btn>
          </div>
        {enrichedLines.length === 0 && (
          <div className={styles.empty}>Sem linhas carregadas.</div>
        )}
        {groupedLines.map(group => (
          <div key={group.key} className={styles.lineCard}>
            <div className={styles.lineHeader}>
              <div>
                <div className={styles.lineTitle}>
                  {group.item_id} <span className={styles.lineSub}>{group.item_desc}</span>
                </div>
                <div className={styles.lineMeta}>
                  Doc. {group.origin_doc_type} #{group.origin_order_id} · Linha {group.origin_order_row}
                  {group.lines.length > 1 ? ` · ${group.lines.length} tamanhos` : ''}
                </div>
              </div>
            </div>

            <div className={styles.sizeList}>
              <div className={styles.sizeListHeader}>
                <span>Tamanho</span>
                <span>Qtd. pedida</span>
                <span>Já tratada</span>
                <span>Saldo</span>
                <span>Stock</span>
                <span>Qtd. separar</span>
                <span>Falta atribuir</span>
                <span>Validar sem caixas</span>
                <span>Ações</span>
              </div>

              {group.lines.map(line => {
                const key = lineKey(line)
                const state = line.state || {}
                const allocations = state.allocations || []
                const isLineCompleted = Number(line.qty_to_separate || 0) > 0 && Number(line.qty_to_allocate || 0) === 0

                return (
                  <div key={key} className={styles.sizeRowWrap}>
                    <div className={styles.sizeRow}>
                      <div className={styles.sizeCell}>
                        <span className={styles.sizeBadge}>{line.origin_size_id || 'UN'}</span>
                      </div>
                      <div className={styles.sizeCell}><strong>{line.qty_requested}</strong></div>
                      <div className={styles.sizeCell}><strong>{line.qty_done}</strong></div>
                      <div className={styles.sizeCell}><strong>{line.qty_pending}</strong></div>
                      <div className={styles.sizeCell}><strong>{line.qty_stock}</strong></div>
                      <div className={styles.sizeCell}>
                        <input
                          className={styles.inlineInput}
                          type="number"
                          min="0"
                          max={line.qty_pending}
                          value={state.qty_to_separate ?? line.qty_pending}
                          onChange={e => updateLineState(key, { qty_to_separate: e.target.value })}
                        />
                      </div>
                      <div className={styles.sizeCell}>
                        <div className={styles.qtyStatus}>
                          <strong>{line.qty_to_allocate}</strong>
                          {isLineCompleted && <span className={styles.completedBadge} title="Linha tratada">V</span>}
                        </div>
                      </div>
                      <label className={styles.sizeCheck}>
                        <input
                          type="checkbox"
                          checked={Boolean(state.allow_without_boxes)}
                          onChange={e => updateLineState(key, { allow_without_boxes: e.target.checked })}
                        />
                        <span>Validar</span>
                      </label>
                      <div className={styles.sizeActions}>
                        <Btn variant="outline" onClick={() => toggleLineExpanded(line)}>
                          {state.expanded ? 'Ocultar detalhe' : 'Gerir caixas / substituto'}
                        </Btn>
                      </div>
                    </div>

                    {whOrigs.length > 1 && state.allow_without_boxes && !allocations.length && (
                      <div className={styles.lineWarehouseRow}>
                        <span>Armazém desta linha:</span>
                        <select
                          className={styles.select}
                          value={state.wh_id_orig || whOrigs[0]}
                          onChange={e => updateLineState(key, { wh_id_orig: e.target.value })}
                        >
                          {whOrigs.map(id => {
                            const warehouse = warehouses.find(w => String(w.wh_id) === id)
                            return <option key={id} value={id}>{warehouse ? warehouse.wh_desc : id}</option>
                          })}
                        </select>
                      </div>
                    )}

                    {state.expanded && (
                      <div className={styles.expandArea}>
                        <div className={styles.stickyLineSummary}>
                          <div className={styles.summaryPill}>
                            <span>Tamanho</span>
                            <strong>{line.origin_size_id || 'UN'}</strong>
                          </div>
                          <div className={styles.summaryPill}>
                            <span>Artigo</span>
                            <strong>{line.selected_item_id}</strong>
                          </div>
                          <div className={styles.summaryPill}>
                            <span>Qtd. separar</span>
                            <strong>{line.qty_to_separate}</strong>
                          </div>
                          <div className={styles.summaryPill}>
                            <span>Falta atribuir</span>
                            <strong>{line.qty_to_allocate}</strong>
                          </div>
                        </div>
                        <div className={styles.expandGrid}>
                          <div className={styles.field}>
                            <label>Procurar artigo substituto</label>
                            <div className={styles.inlineBar}>
                              <input
                                className={styles.input}
                                value={state.substitute_search || ''}
                                onChange={e => updateGroupLineState(line, { substitute_search: e.target.value })}
                                placeholder="Código ou descrição"
                              />
                              <Btn variant="outline" onClick={() => searchSubstitutes(line)} loading={state.loading_substitutes}>
                                Procurar
                              </Btn>
                            </div>
                            <div className={styles.chipList}>
                              <button
                                type="button"
                                className={styles.chip}
                                onClick={() => selectSubstitute(line, { item_id: line.item_id, item_desc: line.item_desc })}
                              >
                                Usar artigo original
                              </button>
                            </div>
                            <div className={styles.selectedItem}>
                              <span>Artigo para separar:</span>
                              <strong>{line.selected_item_id}</strong>
                              <span>{line.selected_item_desc}</span>
                            </div>
                            <div className={`${styles.tableWrap} ${styles.compactTableWrap}`}>
                              <table className={styles.table}>
                                <thead>
                                  <tr>
                                    <th />
                                    <th>Código</th>
                                    <th>Descrição</th>
                                    <th>Stock</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {(state.substitute_results || []).length === 0 && (
                                    <tr>
                                      <td colSpan="4" className={styles.emptyCell}>Sem artigos carregados para este filtro.</td>
                                    </tr>
                                  )}
                                  {(state.substitute_results || []).map(item => (
                                    <tr key={item.item_id}>
                                      <td>
                                        <input
                                          type="radio"
                                          name={`substitute-${key}`}
                                          checked={line.selected_item_id === item.item_id}
                                          onChange={() => selectSubstitute(line, item)}
                                        />
                                      </td>
                                      <td>{item.item_id}</td>
                                      <td>{item.item_desc || '-'}</td>
                                      <td>{item.qty_stock}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>

                          <div className={styles.field}>
                            <label>Caixas em stock no armazém</label>
                            <div className={styles.inlineBar}>
                              <Btn variant="outline" onClick={() => loadBoxes(line)} loading={state.loading_boxes}>
                                Atualizar caixas
                              </Btn>
                            </div>
                            <div className={`${styles.tableWrap} ${styles.compactTableWrap}`}>
                              <table className={styles.table}>
                                <thead>
                                  <tr>
                                    <th />
                                    <th>Caixa</th>
                                    <th>Barcode</th>
                                    {whOrigs.length > 1 && <th>Armazém</th>}
                                    <th>Localização</th>
                                    <th>Stock</th>
                                    <th>Qtd. separar</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {(state.boxes || []).length === 0 && (
                                    <tr>
                                      <td colSpan={whOrigs.length > 1 ? 7 : 6} className={styles.emptyCell}>Sem caixas carregadas para este artigo.</td>
                                    </tr>
                                  )}
                                  {(state.boxes || []).map(box => {
                                    const allocation = allocations.find(entry => entry.vol_num === box.vol_num)
                                    const remaining = remainingQtyForLine(line, box.vol_num)
                                    const maxAllowed = Math.min(Number(box.qty_stock || 0), remaining)
                                    const inputId = `box-qty-${lineKey(line).replace(/[^a-zA-Z0-9_-]/g, '-')}-${String(box.vol_num)}`
                                    return (
                                      <tr key={box.vol_num}>
                                        <td>
                                          <input
                                            type="checkbox"
                                            checked={Boolean(allocation && Number(allocation.qty || 0) > 0)}
                                            onChange={e => toggleBoxSelection(line, box, e.target.checked)}
                                          />
                                        </td>
                                        <td>{box.vol_num}</td>
                                        <td>{box.barcode || '-'}</td>
                                        {whOrigs.length > 1 && <td>{box.wh_id}</td>}
                                        <td>{box.location_id || '-'}</td>
                                        <td>{box.qty_stock}</td>
                                        <td>
                                          <input
                                            id={inputId}
                                            className={styles.inlineInput}
                                            type="number"
                                            min="0"
                                            max={maxAllowed}
                                            disabled={!allocation}
                                            value={allocation?.qty ?? ''}
                                            onChange={e => updateAllocation(line, box, e.target.value)}
                                          />
                                          <div className={styles.inputHint}>Máx. {maxAllowed}</div>
                                        </td>
                                      </tr>
                                    )
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ))}

        <div className={styles.footerBar}>
          <div className={styles.footerMeta}>
            Documento destino: <strong>{config?.doc_type || '—'}</strong>
          </div>
          {!result && (
            <Btn onClick={createDocument} loading={creating}>Criar documento de separação</Btn>
          )}
        </div>
        </Card>
      )}
    </div>
  )
}
