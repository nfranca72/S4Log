import { Fragment, useEffect, useMemo, useState } from 'react'
import { Btn, Card, CardTitle, ResultBanner, Stat, StatsBar } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { separationApi } from '../services/api'
import styles from './SeparationOrdersConsultation.module.css'

function todayString() {
  return new Date().toISOString().slice(0, 10)
}

const EMPTY_FILTERS = {
  source: '',
  relatedDocType: '',
  relatedOrderID: '',
  stateLabel: '',
  creationDate: '',
  requestedExecutionDate: '',
  customerID: '',
  customerName: '',
  assignedUser: '',
  urgencyStatusID: '',
  totalLines: '',
  totalBoxes: '',
  totalQuantityToPick: '',
  totalQuantityPicked: '',
  progressPercentage: '',
}

function matchesFilter(value, filter) {
  const criterion = String(filter || '').trim().toLowerCase()
  if (!criterion) return true
  return String(value ?? '').toLowerCase().includes(criterion)
}

function statusTone(stateCode) {
  if (stateCode === 'separated' || stateCode === 'conferenced') return 'ok'
  if (stateCode === 'in_progress') return 'warn'
  if (stateCode === 'cancelled') return 'danger'
  return 'muted'
}

function documentLabel(row) {
  if (row.related_doc_type) return `${row.related_doc_type}.${row.related_order_id}`
  return row.wave_id || '-'
}

function mapOrderSummary(row) {
  return {
    order_picking_id: row?.OrderPickingID ?? row?.order_picking_id ?? 0,
    wave_id: row?.WaveID ?? row?.wave_id ?? null,
    source: row?.Source ?? row?.source ?? '',
    source_label: row?.SourceLabel ?? row?.source_label ?? '',
    related_doc_type: row?.RelatedDocType ?? row?.related_doc_type ?? null,
    related_order_id: row?.RelatedOrderID ?? row?.related_order_id ?? null,
    state_code: row?.StateCode ?? row?.state_code ?? '',
    state_symbol: row?.StateSymbol ?? row?.state_symbol ?? '',
    state_label: row?.StateLabel ?? row?.state_label ?? '',
    creation_date: row?.CreationDate ?? row?.creation_date ?? null,
    requested_execution_date: row?.RequestedExecutionDate ?? row?.requested_execution_date ?? null,
    customer_id: row?.CustomerID ?? row?.customer_id ?? null,
    customer_name: row?.CustomerName ?? row?.customer_name ?? null,
    assigned_user: row?.AssignedUser ?? row?.assigned_user ?? '',
    urgency_status_id: row?.UrgencyStatusID ?? row?.urgency_status_id ?? null,
    production_status: row?.ProductionStatus ?? row?.production_status ?? '',
    total_lines: Number(row?.TotalLines ?? row?.total_lines ?? 0),
    total_boxes: Number(row?.TotalBoxes ?? row?.total_boxes ?? 0),
    total_quantity_to_pick: Number(row?.TotalQuantityToPick ?? row?.total_quantity_to_pick ?? 0),
    total_quantity_picked: Number(row?.TotalQuantityPicked ?? row?.total_quantity_picked ?? 0),
    completed_rows: Number(row?.CompletedRows ?? row?.completed_rows ?? 0),
    progress_percentage: Number(row?.ProgressPercentage ?? row?.progress_percentage ?? 0),
  }
}

function mapOrderDetail(response) {
  const header = mapOrderSummary(response?.header || {})
  const lines = Array.isArray(response?.lines) ? response.lines : []
  return { header, lines }
}

export default function SeparationOrdersConsultation() {
  const toast = useToast()
  const [filters, setFilters] = useState({
    fromDate: '',
    toDate: '',
    showExecuted: false,
  })
  const [columnFilters, setColumnFilters] = useState(EMPTY_FILTERS)
  const [rows, setRows] = useState([])
  const [metadata, setMetadata] = useState({ users: [], urgency_statuses: [] })
  const [expandedId, setExpandedId] = useState(null)
  const [detailById, setDetailById] = useState({})
  const [formById, setFormById] = useState({})
  const [resultById, setResultById] = useState({})
  const [loading, setLoading] = useState(false)
  const [loadingDetailId, setLoadingDetailId] = useState(null)
  const [savingId, setSavingId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  const urgencyLabelByValue = useMemo(
    () => Object.fromEntries((metadata.urgency_statuses || []).map(status => [String(status.value), status.label])),
    [metadata.urgency_statuses]
  )

  useEffect(() => {
    let cancelled = false
    async function loadMetadata() {
      try {
        const response = await separationApi.consultationMetadata()
        if (!cancelled) setMetadata(response)
      } catch (error) {
        toast(error.message || 'Erro ao carregar metadados', 'error')
      }
    }
    loadMetadata()
    return () => { cancelled = true }
  }, [toast])

  async function search() {
    setLoading(true)
    try {
      const response = await separationApi.consultation({
        fromDate: filters.fromDate,
        toDate: filters.toDate,
        onlyOpen: !filters.showExecuted,
      })
      const items = Array.isArray(response.items) ? response.items.map(mapOrderSummary) : []
      setRows(items)
      if (expandedId && !items.some(row => row.order_picking_id === expandedId)) {
        setExpandedId(null)
      }
    } catch (error) {
      toast(error.message || 'Erro ao consultar separações', 'error')
      setRows([])
      setExpandedId(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    search()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function loadDetail(orderPickingId) {
    setLoadingDetailId(orderPickingId)
    setResultById(current => ({ ...current, [orderPickingId]: null }))
    try {
      const response = mapOrderDetail(await separationApi.consultationDetail(orderPickingId))
      setDetailById(current => ({ ...current, [orderPickingId]: response }))
      setFormById(current => ({
        ...current,
        [orderPickingId]: {
          assignedUser: response.header.assigned_user || '',
          urgencyStatusID: response.header.urgency_status_id == null ? '' : String(response.header.urgency_status_id),
        },
      }))
      setExpandedId(current => current === orderPickingId ? null : orderPickingId)
    } catch (error) {
      toast(error.message || 'Erro ao carregar detalhe da separação', 'error')
    } finally {
      setLoadingDetailId(null)
    }
  }

  function toggleRow(orderPickingId) {
    if (expandedId === orderPickingId) {
      setExpandedId(null)
      return
    }
    if (detailById[orderPickingId]) {
      setExpandedId(orderPickingId)
      return
    }
    loadDetail(orderPickingId)
  }

  const filteredRows = useMemo(
    () => rows.filter(row =>
      matchesFilter(row.source_label, columnFilters.source)
      && matchesFilter(row.related_doc_type, columnFilters.relatedDocType)
      && matchesFilter(row.related_order_id, columnFilters.relatedOrderID)
      && matchesFilter(row.state_label, columnFilters.stateLabel)
      && matchesFilter(row.creation_date, columnFilters.creationDate)
      && matchesFilter(row.requested_execution_date, columnFilters.requestedExecutionDate)
      && matchesFilter(row.customer_id, columnFilters.customerID)
      && matchesFilter(row.customer_name, columnFilters.customerName)
      && matchesFilter(row.assigned_user, columnFilters.assignedUser)
      && matchesFilter(row.urgency_status_id, columnFilters.urgencyStatusID)
      && matchesFilter(row.total_lines, columnFilters.totalLines)
      && matchesFilter(row.total_boxes, columnFilters.totalBoxes)
      && matchesFilter(row.total_quantity_to_pick, columnFilters.totalQuantityToPick)
      && matchesFilter(row.total_quantity_picked, columnFilters.totalQuantityPicked)
      && matchesFilter(row.progress_percentage, columnFilters.progressPercentage)
    ),
    [rows, columnFilters]
  )

  async function saveMaintenance(orderPickingId) {
    const form = formById[orderPickingId] || { assignedUser: '', urgencyStatusID: '' }
    setSavingId(orderPickingId)
    setResultById(current => ({ ...current, [orderPickingId]: null }))
    try {
      const response = await separationApi.consultationUpdate(orderPickingId, {
        assigned_user: form.assignedUser || null,
        urgency_status_id: form.urgencyStatusID || null,
      })
      setResultById(current => ({ ...current, [orderPickingId]: { ok: true, title: 'Ordem atualizada', detail: response.message } }))
      await loadDetail(orderPickingId)
      await search()
    } catch (error) {
      setResultById(current => ({ ...current, [orderPickingId]: { ok: false, title: 'Falha na atualização', detail: error.message || 'Erro' } }))
    } finally {
      setSavingId(null)
    }
  }

  async function deleteOrder(orderPickingId) {
    if (!window.confirm('Pretendes eliminar esta ordem de separação? Só é possível se ainda não tiver nenhuma linha separada.')) return
    setDeletingId(orderPickingId)
    setResultById(current => ({ ...current, [orderPickingId]: null }))
    try {
      const response = await separationApi.consultationDelete(orderPickingId, {})
      setResultById(current => ({ ...current, [orderPickingId]: { ok: true, title: 'Ordem eliminada', detail: response.message } }))
      await loadDetail(orderPickingId)
      await search()
    } catch (error) {
      setResultById(current => ({ ...current, [orderPickingId]: { ok: false, title: 'Falha na eliminação', detail: error.message || 'Erro' } }))
    } finally {
      setDeletingId(null)
    }
  }

  const totals = useMemo(() => ({
    orders: filteredRows.length,
    qtyToPick: filteredRows.reduce((sum, row) => sum + Number(row.total_quantity_to_pick || 0), 0),
    qtyPicked: filteredRows.reduce((sum, row) => sum + Number(row.total_quantity_picked || 0), 0),
    boxes: filteredRows.reduce((sum, row) => sum + Number(row.total_boxes || 0), 0),
  }), [filteredRows])

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.pageTitle}>Consulta de Ordens de Separação</h1>
          <p className={styles.pageIntro}>Consulta unificada de separações BY-PTL e manuais SEP/SSCP.</p>
        </div>
        <div className={styles.actions}>
          <Btn variant="primary" onClick={search} loading={loading}>Atualizar</Btn>
        </div>
      </div>

      <StatsBar>
        <Stat label="Ordens" value={totals.orders} />
        <Stat label="Caixas" value={totals.boxes} />
        <Stat label="Qtd. separar" value={totals.qtyToPick.toFixed(2)} />
        <Stat label="Qtd. separada" value={totals.qtyPicked.toFixed(2)} />
      </StatsBar>

      <Card>
        <CardTitle>Filtros</CardTitle>
        <div className={styles.filterGrid}>
          <label>
            <span>De</span>
            <input type="date" value={filters.fromDate} max={todayString()} onChange={(event) => setFilters(current => ({ ...current, fromDate: event.target.value }))} />
          </label>
          <label>
            <span>Até</span>
            <input type="date" value={filters.toDate} max={todayString()} onChange={(event) => setFilters(current => ({ ...current, toDate: event.target.value }))} />
          </label>
          <label className={styles.toggle}>
            <input type="checkbox" checked={filters.showExecuted} onChange={(event) => setFilters(current => ({ ...current, showExecuted: event.target.checked }))} />
            <span>Ver separações já executadas</span>
          </label>
        </div>
      </Card>

      <Card className={styles.listCard}>
        <CardTitle>Lista</CardTitle>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.expandCol}></th>
                <th>Origem</th>
                <th>Doc.</th>
                <th>Estado</th>
                <th>Criação</th>
                <th>Execução</th>
                <th>Cliente</th>
                <th>Utilizador</th>
                <th>Urgência</th>
                <th>Linhas</th>
                <th>Caixas</th>
                <th>Qtd. sep.</th>
                <th>Qtd. feita</th>
                <th>%</th>
              </tr>
              <tr>
                <th></th>
                <th><input value={columnFilters.source} onChange={(event) => setColumnFilters(current => ({ ...current, source: event.target.value }))} /></th>
                <th><input value={columnFilters.relatedDocType} onChange={(event) => setColumnFilters(current => ({ ...current, relatedDocType: event.target.value }))} /></th>
                <th><input value={columnFilters.stateLabel} onChange={(event) => setColumnFilters(current => ({ ...current, stateLabel: event.target.value }))} /></th>
                <th><input value={columnFilters.creationDate} onChange={(event) => setColumnFilters(current => ({ ...current, creationDate: event.target.value }))} /></th>
                <th><input value={columnFilters.requestedExecutionDate} onChange={(event) => setColumnFilters(current => ({ ...current, requestedExecutionDate: event.target.value }))} /></th>
                <th><input value={columnFilters.customerName} onChange={(event) => setColumnFilters(current => ({ ...current, customerName: event.target.value }))} /></th>
                <th><input value={columnFilters.assignedUser} onChange={(event) => setColumnFilters(current => ({ ...current, assignedUser: event.target.value }))} /></th>
                <th><input value={columnFilters.urgencyStatusID} onChange={(event) => setColumnFilters(current => ({ ...current, urgencyStatusID: event.target.value }))} /></th>
                <th><input value={columnFilters.totalLines} onChange={(event) => setColumnFilters(current => ({ ...current, totalLines: event.target.value }))} /></th>
                <th><input value={columnFilters.totalBoxes} onChange={(event) => setColumnFilters(current => ({ ...current, totalBoxes: event.target.value }))} /></th>
                <th><input value={columnFilters.totalQuantityToPick} onChange={(event) => setColumnFilters(current => ({ ...current, totalQuantityToPick: event.target.value }))} /></th>
                <th><input value={columnFilters.totalQuantityPicked} onChange={(event) => setColumnFilters(current => ({ ...current, totalQuantityPicked: event.target.value }))} /></th>
                <th><input value={columnFilters.progressPercentage} onChange={(event) => setColumnFilters(current => ({ ...current, progressPercentage: event.target.value }))} /></th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map(row => {
                const isExpanded = expandedId === row.order_picking_id
                const detail = detailById[row.order_picking_id]
                const form = formById[row.order_picking_id] || { assignedUser: '', urgencyStatusID: '' }
                const result = resultById[row.order_picking_id]

                return (
                  <Fragment key={row.order_picking_id}>
                    <tr
                      className={isExpanded ? styles.activeRow : ''}
                      onClick={() => toggleRow(row.order_picking_id)}
                    >
                      <td className={styles.expandCell}>{isExpanded ? '-' : '+'}</td>
                      <td>{row.source_label}</td>
                      <td>{documentLabel(row)}</td>
                      <td><span className={`${styles.state} ${styles[`state_${statusTone(row.state_code)}`]}`}>{row.state_symbol} {row.state_label}</span></td>
                      <td>{row.creation_date?.slice(0, 10) || '-'}</td>
                      <td>{row.requested_execution_date?.slice(0, 10) || '-'}</td>
                      <td>{row.customer_name || row.customer_id || '-'}</td>
                      <td>{row.assigned_user || '-'}</td>
                      <td>{urgencyLabelByValue[String(row.urgency_status_id ?? '')] || row.urgency_status_id || '-'}</td>
                      <td>{row.total_lines}</td>
                      <td>{row.total_boxes}</td>
                      <td>{Number(row.total_quantity_to_pick || 0).toFixed(2)}</td>
                      <td>{Number(row.total_quantity_picked || 0).toFixed(2)}</td>
                      <td>
                        <div className={styles.progressCell}>
                          <div className={styles.progressBar}><span style={{ width: `${Math.min(100, Number(row.progress_percentage || 0))}%` }} /></div>
                          <small>{Number(row.progress_percentage || 0).toFixed(0)}%</small>
                        </div>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className={styles.expandedRow}>
                        <td colSpan="14" className={styles.expandedCell}>
                          {loadingDetailId === row.order_picking_id && <div className={styles.empty}>A carregar detalhe...</div>}
                          {result && <ResultBanner ok={result.ok} title={result.title} detail={result.detail} />}
                          {detail && (
                            <div className={styles.expandedContent}>
                              <div className={styles.detailSummary}>
                                <div className={styles.summaryItem}><strong>Origem:</strong> {detail.header.source_label}</div>
                                <div className={styles.summaryItem}><strong>Documento:</strong> {documentLabel(detail.header)}</div>
                                <div className={styles.summaryItem}><strong>Estado:</strong> {detail.header.state_symbol} {detail.header.state_label}</div>
                              </div>

                              <div className={styles.detailControls}>
                                <div className={styles.maintenanceGrid}>
                                  <label className={styles.userField}>
                                    <span>Utilizador atribuído</span>
                                    <select value={form.assignedUser} onChange={(event) => setFormById(current => ({ ...current, [row.order_picking_id]: { ...form, assignedUser: event.target.value } }))}>
                                      <option value="">Sem utilizador</option>
                                      {metadata.users.map(user => <option key={user.value} value={user.value}>{user.label}</option>)}
                                    </select>
                                  </label>
                                  <label className={styles.urgencyField}>
                                    <span>Urgência</span>
                                    <select value={form.urgencyStatusID} onChange={(event) => setFormById(current => ({ ...current, [row.order_picking_id]: { ...form, urgencyStatusID: event.target.value } }))}>
                                      <option value="">Sem urgência</option>
                                      {metadata.urgency_statuses.map(status => <option key={status.value} value={status.value}>{status.label}</option>)}
                                    </select>
                                  </label>
                                </div>

                                <div className={styles.detailActions}>
                                  <Btn variant="primary" onClick={() => saveMaintenance(row.order_picking_id)} loading={savingId === row.order_picking_id}>Guardar manutenção</Btn>
                                  <span title={Number(row.total_quantity_picked || 0) > 0 ? 'Já tem linhas separadas — remove-as na execução antes de eliminar' : 'Eliminar ordem (só possível sem nenhuma linha separada)'}>
                                    <Btn
                                      variant="danger"
                                      onClick={() => deleteOrder(row.order_picking_id)}
                                      loading={deletingId === row.order_picking_id}
                                      disabled={Number(row.total_quantity_picked || 0) > 0}
                                    >
                                      Eliminar ordem
                                    </Btn>
                                  </span>
                                </div>
                              </div>

                              <div className={styles.linesList}>
                                {detail.lines.map(line => (
                                  <div className={styles.lineCard} key={`${line.row_number}-${line.origin_order_row}`}>
                                    <div className={styles.lineTop}>
                                      <div className={styles.lineHeading}>
                                        <strong>{line.item_id}</strong>
                                        <span>{line.item_desc}</span>
                                      </div>
                                      <span className={`${styles.state} ${styles[`state_${statusTone(line.state_code)}`]}`}>{line.state_symbol} {line.state_label}</span>
                                    </div>
                                    <div className={styles.lineMeta}>
                                      <span>Origem: {line.origin_doc_type}.{line.origin_order_id}/{line.origin_order_row}</span>
                                      <span>Qtd: {Number(line.quantity_picked || 0).toFixed(2)} / {Number(line.quantity_to_pick || 0).toFixed(2)}</span>
                                      <span>Loc.: {line.location_origin || '-'} → {line.location_dest || '-'}</span>
                                    </div>
                                    <div className={styles.boxesGrid}>
                                      <div>
                                        <strong>Caixas indicadas</strong>
                                        <ul>
                                          {line.planned_boxes.map(box => <li key={`p-${box.vol_doc_cod}-${box.vol_num}-${box.item_id}`}>{box.vol_num || '-'} · {box.item_id || '-'} · {Number(box.quantity || 0).toFixed(2)}</li>)}
                                          {!line.planned_boxes.length && <li>Sem caixas planeadas</li>}
                                        </ul>
                                      </div>
                                      <div>
                                        <strong>Caixas separadas</strong>
                                        <ul>
                                          {line.picked_boxes.map(box => <li key={`e-${box.vol_doc_cod}-${box.vol_num}-${box.item_id}`}>{box.vol_num || '-'} · {box.item_id || '-'} · {Number(box.quantity || 0).toFixed(2)}</li>)}
                                          {!line.picked_boxes.length && <li>Sem caixas executadas</li>}
                                        </ul>
                                      </div>
                                    </div>
                                  </div>
                                ))}
                                {!detail.lines.length && <div className={styles.empty}>Esta ordem não tem linhas.</div>}
                              </div>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
              {!filteredRows.length && (
                <tr>
                  <td colSpan="14" className={styles.empty}>Sem ordens para apresentar.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
