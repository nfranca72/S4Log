import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import S4LogLogo from '../components/S4LogLogo'
import { Card, ResultBanner } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { separationApi } from '../services/api'
import styles from './SeparationExecution.module.css'

const COLUMN_CONFIGS = [
  { key: 'urgency', label: '', width: 22, minWidth: 18, resizable: false },
  { key: 'document', label: 'Separação', width: 150, minWidth: 110, resizable: true },
  { key: 'obs', label: 'Obs.', width: 72, minWidth: 56, resizable: true },
  { key: 'customer', label: 'Cliente', width: 140, minWidth: 90, resizable: true },
  { key: 'user', label: 'Util.', width: 92, minWidth: 72, resizable: true },
  { key: 'lines', label: 'Linhas', width: 72, minWidth: 56, resizable: true },
  { key: 'state', label: 'Estado', width: 120, minWidth: 88, resizable: true },
]

function IconMenu() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  )
}

function IconRefresh() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 2v6h-6" />
      <path d="M3 12a9 9 0 0115-6.7L21 8" />
      <path d="M3 22v-6h6" />
      <path d="M21 12a9 9 0 01-15 6.7L3 16" />
    </svg>
  )
}

function IconPick() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l7 4v10l-7 4-7-4V7l7-4z" />
      <path d="M12 12l7-4" />
      <path d="M12 12v9" />
      <path d="M12 12L5 8" />
    </svg>
  )
}

function IconCheck() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3h6a1 1 0 011 1v1h1a1 1 0 011 1v14a1 1 0 01-1 1H7a1 1 0 01-1-1V6a1 1 0 011-1h1V4a1 1 0 011-1z" />
      <path d="M9 4h6v2H9z" />
      <path d="M8.5 13l2 2 4-4.5" />
    </svg>
  )
}

function statusTone(stateCode) {
  if (stateCode === 'separated' || stateCode === 'conferenced') return 'ok'
  if (stateCode === 'in_progress') return 'warn'
  if (stateCode === 'cancelled') return 'danger'
  return 'muted'
}

function urgencyTone(value) {
  const normalized = String(value || '').trim().toUpperCase()
  if (!normalized) return 'muted'
  if (['A', '1', 'HIGH', 'ALTA', 'URGENTE'].includes(normalized)) return 'high'
  if (['B', '2', 'MEDIUM', 'MEDIA', 'MÉDIA'].includes(normalized)) return 'medium'
  if (['C', '3', 'LOW', 'BAIXA'].includes(normalized)) return 'low'
  return 'accent'
}

function documentLabel(row) {
  if (row.related_doc_type && row.related_order_id) return `${row.related_doc_type}.${row.related_order_id}`
  return `OP ${row.order_picking_id}`
}

function mapExecutionRow(row) {
  return {
    order_picking_id: row?.OrderPickingID ?? row?.order_picking_id ?? 0,
    related_doc_type: row?.RelatedDocType ?? row?.related_doc_type ?? '',
    related_order_id: row?.RelatedOrderID ?? row?.related_order_id ?? null,
    source_label: row?.SourceLabel ?? row?.source_label ?? '',
    state_code: row?.StateCode ?? row?.state_code ?? '',
    state_symbol: row?.StateSymbol ?? row?.state_symbol ?? '',
    state_label: row?.StateLabel ?? row?.state_label ?? '',
    observation: row?.Observation ?? row?.observation ?? '',
    creation_date: row?.CreationDate ?? row?.creation_date ?? null,
    requested_execution_date: row?.RequestedExecutionDate ?? row?.requested_execution_date ?? null,
    planned_date: row?.PlannedDate ?? row?.planned_date ?? null,
    customer_name: row?.CustomerName ?? row?.customer_name ?? '',
    assigned_user: row?.AssignedUser ?? row?.assigned_user ?? '',
    urgency_status_id: row?.UrgencyStatusID ?? row?.urgency_status_id ?? '',
    completed_lines: Number(row?.CompletedLines ?? row?.completed_lines ?? 0),
    total_lines: Number(row?.TotalLines ?? row?.total_lines ?? 0),
    total_quantity_to_pick: Number(row?.TotalQuantityToPick ?? row?.total_quantity_to_pick ?? 0),
    total_quantity_picked: Number(row?.TotalQuantityPicked ?? row?.total_quantity_picked ?? 0),
    can_separate: Boolean(row?.CanSeparate ?? row?.can_separate),
    can_check: Boolean(row?.CanCheck ?? row?.can_check),
    link_group: row?.LinkGroup ?? row?.link_group ?? null,
  }
}

function compactText(value) {
  return String(value || '').trim() || '-'
}

export default function SeparationOrdersConsultationExecution() {
  const toast = useToast()
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [docTypes, setDocTypes] = useState([])
  const [selectedDocType, setSelectedDocType] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [resultById, setResultById] = useState({})
  const [loading, setLoading] = useState(false)
  const [columnWidths, setColumnWidths] = useState(() => Object.fromEntries(COLUMN_CONFIGS.map(column => [column.key, column.width])))
  const resizeStateRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    async function loadBase() {
      try {
        const types = await separationApi.executionDocumentTypes()
        if (cancelled) return
        const normalizedTypes = Array.isArray(types) ? types : []
        setDocTypes(normalizedTypes)
        setSelectedDocType(current => current || normalizedTypes[0]?.doc_type || '')
      } catch (error) {
        toast(error.message || 'Erro ao carregar configuração da execução', 'error')
      }
    }
    loadBase()
    return () => { cancelled = true }
  }, [toast])

  async function search() {
    setLoading(true)
    try {
      const response = await separationApi.executionOrders(selectedDocType ? [selectedDocType] : [])
      const items = Array.isArray(response.items) ? response.items.map(mapExecutionRow) : []
      setRows(items)
      if (selectedId && !items.some(row => row.order_picking_id === selectedId)) {
        setSelectedId(items[0]?.order_picking_id ?? null)
      } else if (!selectedId && items.length) {
        setSelectedId(items[0].order_picking_id)
      }
    } catch (error) {
      toast(error.message || 'Erro ao consultar separações em execução', 'error')
      setRows([])
      setSelectedId(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    search()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDocType])

  useEffect(() => {
    function stopResize() {
      resizeStateRef.current = null
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    function handlePointerMove(event) {
      const state = resizeStateRef.current
      if (!state) return
      const delta = event.clientX - state.startX
      setColumnWidths(current => ({
        ...current,
        [state.columnKey]: Math.max(state.minWidth, state.startWidth + delta),
      }))
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopResize)
    window.addEventListener('pointercancel', stopResize)
    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopResize)
      window.removeEventListener('pointercancel', stopResize)
    }
  }, [])

  function selectRow(orderPickingId) {
    setSelectedId(orderPickingId)
  }

  function toggleMenu() {
    window.dispatchEvent(new Event('s4log:toggle-sidebar'))
  }

  function startColumnResize(event, columnKey, minWidth) {
    event.preventDefault()
    event.stopPropagation()
    resizeStateRef.current = {
      columnKey,
      minWidth,
      startX: event.clientX,
      startWidth: columnWidths[columnKey] ?? minWidth,
    }
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }

  async function openAction(row, action) {
    if (action === 'separate') {
      navigate(`/execucao-separacoes/${row.order_picking_id}`)
      return
    }
    setResultById(current => ({
      ...current,
      [row.order_picking_id]: {
        ok: true,
        title: 'Conferência selecionada',
        detail: 'Ordem pronta para conferência RFID.',
      },
    }))
  }

  const selectedRow = useMemo(
    () => rows.find(row => row.order_picking_id === selectedId) || rows[0] || null,
    [rows, selectedId]
  )

  const selectedResult = selectedRow ? resultById[selectedRow.order_picking_id] : null

  const totals = useMemo(() => ({
    orders: rows.length,
    inProgress: rows.filter(row => row.state_code === 'in_progress').length,
    separated: rows.filter(row => row.state_code === 'separated').length,
    lines: rows.reduce((sum, row) => sum + Number(row.total_lines || 0), 0),
  }), [rows])

  const tableMinWidth = useMemo(
    () => COLUMN_CONFIGS.reduce((sum, column) => sum + Number(columnWidths[column.key] || column.width), 0),
    [columnWidths]
  )

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <button type="button" className={styles.iconButton} onClick={toggleMenu} aria-label="Menu">
          <IconMenu />
        </button>
        <div className={styles.brand}>
          <S4LogLogo size="compact" />
        </div>
        <button type="button" className={styles.iconButton} onClick={search} aria-label="Atualizar" disabled={loading}>
          <IconRefresh />
        </button>
        <label className={styles.docTypeSelect}>
          <select value={selectedDocType} onChange={(event) => setSelectedDocType(event.target.value)} disabled={!docTypes.length}>
            {docTypes.map(docType => (
              <option key={docType.doc_type} value={docType.doc_type}>{docType.doc_type}</option>
            ))}
          </select>
        </label>
      </div>

      <div className={styles.statsWrap}>
        <div className={styles.summaryBar}>
          <div className={styles.summaryItem}>
            <strong>{totals.orders}</strong>
            <span>Pedidos</span>
          </div>
          <div className={styles.summaryItem}>
            <strong>{totals.inProgress}</strong>
            <span>Em preparação</span>
          </div>
          <div className={styles.summaryItem}>
            <strong>{totals.separated}</strong>
            <span>Separadas</span>
          </div>
          <div className={styles.summaryItem}>
            <strong>{totals.lines}</strong>
            <span>Linhas</span>
          </div>
        </div>
      </div>

      <Card className={styles.listCard}>
        <div className={styles.tableWrap}>
          <table className={styles.table} style={{ minWidth: `${tableMinWidth}px` }}>
            <colgroup>
              {COLUMN_CONFIGS.map(column => (
                <col key={column.key} style={{ width: `${columnWidths[column.key] || column.width}px` }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                {COLUMN_CONFIGS.map(column => (
                  <th key={column.key} className={column.key === 'urgency' ? styles.dotCol : ''}>
                    <span className={styles.headerLabel}>{column.label}</span>
                    {column.resizable ? (
                      <button
                        type="button"
                        className={styles.resizeHandle}
                        aria-label={`Redimensionar coluna ${column.label}`}
                        onPointerDown={(event) => startColumnResize(event, column.key, column.minWidth)}
                      />
                    ) : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr
                  key={row.order_picking_id}
                  className={selectedRow?.order_picking_id === row.order_picking_id ? styles.activeRow : ''}
                  onClick={() => selectRow(row.order_picking_id)}
                >
                  <td className={styles.dotCol}>
                    <span
                      className={`${styles.urgencyDot} ${styles[`urgencyDot_${urgencyTone(row.urgency_status_id)}`]}`}
                      title={row.urgency_status_id ? `Urgência ${row.urgency_status_id}` : 'Sem urgência'}
                    />
                  </td>
                  <td title={row.link_group ? `${documentLabel(row)} — interligada (grupo ${row.link_group})` : documentLabel(row)}>
                    {compactText(documentLabel(row))}
                    {row.link_group && <span title={`Separação interligada — grupo ${row.link_group}`}> 🔗</span>}
                  </td>
                  <td title={row.observation || ''}>{compactText(row.observation)}</td>
                  <td title={row.customer_name || ''}>{compactText(row.customer_name || '-')}</td>
                  <td title={row.assigned_user || ''}>{compactText(row.assigned_user || '-')}</td>
                  <td title={`A executar: ${row.total_lines} — Já executadas: ${row.completed_lines}`}>{row.total_lines}/{row.completed_lines}</td>
                  <td>
                    <span className={`${styles.state} ${styles[`state_${statusTone(row.state_code)}`]}`} title={row.state_label}>
                      {row.state_symbol} {row.state_label}
                    </span>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan="7" className={styles.empty}>Sem ordens para apresentar.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {selectedRow && (
        <div className={styles.detailPanel}>
          {selectedResult && <ResultBanner ok={selectedResult.ok} title={selectedResult.title} detail={selectedResult.detail} />}
          <div className={styles.inlineActions}>
            <button
              type="button"
              className={`${styles.actionTile} ${!selectedRow?.can_separate ? styles.actionTileDisabled : ''}`}
              onClick={() => selectedRow && openAction(selectedRow, 'separate')}
              disabled={!selectedRow?.can_separate}
            >
              <span className={styles.actionIcon}><IconPick /></span>
              <span className={styles.actionCopy}>
                <strong>Separar</strong>
                <small>Executar separação</small>
              </span>
            </button>
            <button
              type="button"
              className={`${styles.actionTile} ${styles.actionTileAlt} ${!selectedRow?.can_check ? styles.actionTileDisabled : ''}`}
              onClick={() => selectedRow && openAction(selectedRow, 'check')}
              disabled={!selectedRow?.can_check}
            >
              <span className={styles.actionIcon}><IconCheck /></span>
              <span className={styles.actionCopy}>
                <strong>Conferir</strong>
                <small>Conferência RFID</small>
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
