import { useState, useEffect, useCallback, useMemo } from 'react'
import { Btn } from '../components/ui'
import styles from './Module3.module.css'

const BASE = import.meta.env.VITE_API_URL ?? '/api'
const api = {
  get: async (path) => {
    const response = await fetch(`${BASE}${path}`)
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`)
    return payload
  },
}

const STATUS_LABELS = {
  INICIAL:       { label: 'Inicial',        color: '#6b7280' },
  EMCONFERENCIA: { label: 'Em conferência', color: '#d97706' },
  FECHADO:       { label: 'Fechado',         color: '#16a34a' },
}

const STOCK_COLUMNS = [
  { key: 'wh_id', label: 'Armazém', mono: true },
  { key: 'item_id', label: 'Artigo', mono: true },
  { key: 'item_desc', label: 'Descrição' },
  { key: 'client_ref', label: 'Ref. cliente' },
  { key: 'model', label: 'Modelo' },
  { key: 'location_id', label: 'Localização', mono: true },
  { key: 'lot', label: 'Lote' },
  { key: 'color_id', label: 'Cor' },
  { key: 'color_desc', label: 'Descrição cor' },
  { key: 'size_id', label: 'Tamanho' },
  { key: 'size_desc', label: 'Descrição tamanho' },
  { key: 'country', label: 'País' },
  { key: 'vol_num', label: 'Volume' },
  { key: 'qty', label: 'Quantidade', numeric: true },
]

const EMPTY_STOCK_COLUMN_FILTERS = Object.fromEntries(
  STOCK_COLUMNS.map(column => [column.key, ''])
)

function matchesColumnFilter(value, filter, numeric = false) {
  const criterion = String(filter || '').trim()
  if (!criterion) return true

  if (numeric) {
    const match = criterion.replace(',', '.').match(/^(<=|>=|<>|!=|=|<|>)?\s*(-?\d+(?:\.\d+)?)$/)
    if (!match) return String(value ?? '').toLowerCase().includes(criterion.toLowerCase())
    const actual = Number(value)
    const expected = Number(match[2])
    if (!Number.isFinite(actual)) return false
    switch (match[1] || '=') {
      case '<': return actual < expected
      case '<=': return actual <= expected
      case '>': return actual > expected
      case '>=': return actual >= expected
      case '<>':
      case '!=': return actual !== expected
      default: return actual === expected
    }
  }

  return String(value ?? '').toLocaleLowerCase('pt-PT').includes(
    criterion.toLocaleLowerCase('pt-PT')
  )
}

function localDateValue(value = new Date()) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function SelectionList({ label, allLabel, options, selected, onChange, getKey, getLabel, disabled }) {
  const toggle = (key) => {
    onChange(selected.includes(key) ? selected.filter(value => value !== key) : [...selected, key])
  }

  return (
    <fieldset className={styles.selectionField} disabled={disabled}>
      <legend>{label}</legend>
      <label className={styles.checkOption}>
        <input type="checkbox" checked={!selected.length} onChange={() => onChange([])} />
        <span>{allLabel}</span>
      </label>
      <div className={styles.selectionOptions}>
        {options.map(option => {
          const key = String(getKey(option))
          return (
            <label className={styles.checkOption} key={key}>
              <input
                type="checkbox"
                checked={selected.includes(key)}
                onChange={() => toggle(key)}
              />
              <span title={getLabel(option)}>{getLabel(option)}</span>
            </label>
          )
        })}
        {!options.length && <span className={styles.optionEmpty}>Sem opções</span>}
      </div>
    </fieldset>
  )
}

function StockListing() {
  const [options, setOptions] = useState({ warehouses: [], locations: [] })
  const [selectedWh, setSelectedWh] = useState([])
  const [selectedLocations, setSelectedLocations] = useState([])
  const [itemFilters, setItemFilters] = useState('')
  const [historical, setHistorical] = useState(false)
  const [stockDate, setStockDate] = useState(localDateValue)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [truncated, setTruncated] = useState(false)
  const [searched, setSearched] = useState(false)
  const [columnFilters, setColumnFilters] = useState(EMPTY_STOCK_COLUMN_FILTERS)

  useEffect(() => {
    api.get('/consulting/stock/options')
      .then(data => setOptions({
        warehouses: Array.isArray(data.warehouses) ? data.warehouses : [],
        locations: Array.isArray(data.locations) ? data.locations : [],
      }))
      .catch(err => setError(err.message))
  }, [])

  const visibleLocations = selectedWh.length
    ? options.locations.filter(location => selectedWh.includes(String(location.wh_id)))
    : options.locations

  useEffect(() => {
    const allowed = new Set(visibleLocations.map(location => `${location.wh_id}|${location.location_id}`))
    setSelectedLocations(current => current.filter(location => allowed.has(location)))
  }, [selectedWh, options.locations])

  const parsedItemFilters = () => itemFilters
    .split(/[;,\n]+/)
    .map(value => value.trim())
    .filter(Boolean)

  const search = async () => {
    if (historical && !stockDate) {
      setError('Indique a data para calcular o stock histórico.')
      return
    }

    const params = new URLSearchParams()
    selectedWh.forEach(value => params.append('wh_ids', value))
    selectedLocations.forEach(value => params.append('location_keys', value))
    parsedItemFilters().forEach(value => params.append('item_filters', value))
    if (historical) params.set('as_of_date', stockDate)

    setLoading(true)
    setError('')
    setSearched(true)
    try {
      const data = await api.get(`/consulting/stock?${params.toString()}`)
      setRows(Array.isArray(data.rows) ? data.rows : [])
      setTruncated(Boolean(data.truncated))
    } catch (err) {
      setRows([])
      setTruncated(false)
      setError(err.message || 'Não foi possível consultar o stock.')
    } finally {
      setLoading(false)
    }
  }

  const filteredRows = useMemo(
    () => rows.filter(row => STOCK_COLUMNS.every(column =>
      matchesColumnFilter(row[column.key], columnFilters[column.key], column.numeric)
    )),
    [rows, columnFilters]
  )

  const hasColumnFilters = Object.values(columnFilters).some(value => value.trim())

  const updateColumnFilter = (key, value) => {
    setColumnFilters(current => ({ ...current, [key]: value }))
  }

  const exportCsv = () => {
    if (!filteredRows.length) return
    const headers = STOCK_COLUMNS.map(column => column.label)
    const values = filteredRows.map(row => STOCK_COLUMNS.map(column => row[column.key]))
    const quote = value => `"${String(value ?? '').replaceAll('"', '""')}"`
    const csv = [headers, ...values].map(line => line.map(quote).join(';')).join('\r\n')
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = historical ? `stock-${stockDate}.csv` : 'stock-atual.csv'
    link.click()
    URL.revokeObjectURL(link.href)
  }

  const totalQty = filteredRows.reduce((total, row) => total + Number(row.qty || 0), 0)

  return (
    <div className={styles.stockLayout}>
      <div className={styles.stockFilters}>
        <SelectionList
          label="Armazéns"
          allLabel="Todos os armazéns"
          options={options.warehouses}
          selected={selectedWh}
          onChange={setSelectedWh}
          getKey={option => option.wh_id}
          getLabel={option => `${option.wh_id} — ${option.wh_desc || 'Sem descrição'}`}
        />
        <SelectionList
          label="Localizações"
          allLabel="Todas as localizações"
          options={visibleLocations}
          selected={selectedLocations}
          onChange={setSelectedLocations}
          getKey={option => `${option.wh_id}|${option.location_id}`}
          getLabel={option => `${option.wh_id} / ${option.location_id}${option.location_desc ? ` — ${option.location_desc}` : ''}`}
        />
        <div className={styles.itemFilterBlock}>
          <label htmlFor="stock-item-filters">Artigos</label>
          <textarea
            id="stock-item-filters"
            value={itemFilters}
            onChange={event => setItemFilters(event.target.value)}
            placeholder={'Todos, ou um/vários filtros separados por vírgula\nEx.: ME%, ART001, MOD_*'}
            rows={5}
          />
          <span>Aceita os metacarateres <strong>%</strong>, <strong>_</strong> ou <strong>*</strong>.</span>
        </div>
        <div className={styles.dateFilterBlock}>
          <label className={styles.historicalToggle}>
            <input
              type="checkbox"
              checked={historical}
              onChange={event => setHistorical(event.target.checked)}
            />
            <span>Ver existências numa data</span>
          </label>
          <input
            type="date"
            value={stockDate}
            max={localDateValue()}
            disabled={!historical}
            onChange={event => setStockDate(event.target.value)}
          />
          <small>O resultado corresponde ao final do dia indicado.</small>
        </div>
        <div className={styles.stockActions}>
          <Btn variant="primary" onClick={search} loading={loading}>Consultar stock</Btn>
          <Btn variant="outline" onClick={exportCsv} disabled={!filteredRows.length}>Exportar CSV</Btn>
        </div>
      </div>

      {error && <div className={styles.errorMessage}>{error}</div>}
      {truncated && (
        <div className={styles.warningMessage}>
          A listagem excede 5.000 linhas. Refine os filtros para obter todos os resultados.
        </div>
      )}

      <div className={styles.panel}>
        <div className={styles.panelHeader}>
          <span>
            {historical ? `Stock em ${stockDate}` : 'Stock atual'} ({filteredRows.length}
            {hasColumnFilters ? ` de ${rows.length}` : ''} linhas)
          </span>
          <div className={styles.stockHeaderActions}>
            {hasColumnFilters && (
              <button
                type="button"
                className={styles.clearColumnFilters}
                onClick={() => setColumnFilters(EMPTY_STOCK_COLUMN_FILTERS)}
              >
                Limpar filtros de colunas
              </button>
            )}
            <span className={styles.stockTotal}>Quantidade total: {totalQty.toLocaleString('pt-PT')}</span>
          </div>
        </div>
        <div className={`${styles.tableWrap} ${styles.stockTableWrap}`}>
          <table className={styles.table}>
            <thead>
              <tr>
                {STOCK_COLUMNS.map(column => <th key={column.key}>{column.label}</th>)}
              </tr>
              <tr className={styles.columnFilterRow}>
                {STOCK_COLUMNS.map(column => (
                  <th key={column.key}>
                    <input
                      type="text"
                      value={columnFilters[column.key]}
                      onChange={event => updateColumnFilter(column.key, event.target.value)}
                      placeholder={column.numeric ? 'Ex.: > 10' : 'Filtrar...'}
                      aria-label={`Filtrar ${column.label}`}
                    />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row, index) => (
                <tr key={`${row.wh_id}|${row.location_id}|${row.item_id}|${row.lot}|${row.vol_num}|${row.color_id}|${row.size_id}|${row.country}|${index}`}>
                  {STOCK_COLUMNS.map(column => (
                    <td
                      key={column.key}
                      className={`${column.mono ? styles.mono : ''} ${column.numeric ? styles.right : ''}`}
                    >
                      {column.numeric
                        ? Number(row[column.key]).toLocaleString('pt-PT')
                        : row[column.key]}
                    </td>
                  ))}
                </tr>
              ))}
              {!loading && searched && !filteredRows.length && (
                <tr>
                  <td colSpan={STOCK_COLUMNS.length} className={styles.empty}>
                    {rows.length ? 'Nenhuma linha corresponde aos filtros das colunas' : 'Sem stock para os filtros indicados'}
                  </td>
                </tr>
              )}
              {!searched && (
                <tr><td colSpan={STOCK_COLUMNS.length} className={styles.empty}>Defina os filtros e consulte o stock</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function MovTable({ movs }) {
  if (!movs.length) return <p className={styles.empty}>Sem movimentos</p>
  return (
    <table className={styles.table}>
      <thead><tr>
        <th>Data</th><th>Artigo</th><th>Descrição</th>
        <th>Movimento</th><th>Origem</th><th>Destino</th><th>Qtd</th>
      </tr></thead>
      <tbody>
        {movs.map((m, i) => (
          <tr key={i} className={styles.row}>
            <td className={styles.mono}>{m.mov_date}</td>
            <td className={styles.mono}>{m.item_id}</td>
            <td>{m.item_desc}</td>
            <td>{m.mov_type}</td>
            <td>{m.wh_orig} / {m.loc_orig}</td>
            <td>{m.wh_dest} / {m.loc_dest}</td>
            <td className={styles.right}>{m.qty.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ViewByArticle({ selected }) {
  const [lines,     setLines]     = useState([])
  const [selLine,   setSelLine]   = useState(null)
  const [stock,     setStock]     = useState([])
  const [selBox,    setSelBox]    = useState('')
  const [boxes,     setBoxes]     = useState([])
  const [movements, setMovements] = useState([])

  useEffect(() => {
    if (!selected) return
    setLines([]); setSelLine(null); setStock([]); setBoxes([]); setMovements([]); setSelBox('')
    api.get(`/consulting/packings/${selected.order_id}/lines?doc_type=${selected.doc_type}`).then(d => setLines(d || []))
    api.get(`/consulting/packings/${selected.order_id}/boxes?doc_type=${selected.doc_type}`).then(d => setBoxes(d || []))
  }, [selected])

  const selectLine = async (line) => {
    setSelLine(line); setMovements([])
    const d = await api.get(`/consulting/items/${encodeURIComponent(line.item_id)}/stock`)
    setStock(d || [])
  }

  const loadMovements = async (vol) => {
    setSelBox(vol)
    if (vol) {
      const d = await api.get(`/consulting/packings/${selected.order_id}/boxes/${vol}/movements`)
      setMovements(d || [])
    }
  }

  return (
    <>
      <div className={styles.panel}>
        <div className={styles.panelHeader}>
          <span>Linhas — {selected.order_id}</span>
          {selected.obs && <span className={styles.obs}>{selected.obs}</span>}
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr>
              <th>Artigo</th><th>Ref. Cliente</th><th>Descrição</th>
              <th>Qtd Ini</th><th>Qtd Conf</th><th>Em Stock</th>
            </tr></thead>
            <tbody>
              {lines.map(l => (
                <tr key={l.order_row}
                  className={selLine?.order_row === l.order_row ? styles.rowSelected : styles.row}
                  onClick={() => selectLine(l)}>
                  <td className={styles.mono}>{l.item_id}</td>
                  <td>{l.client_ref}</td><td>{l.item_desc}</td>
                  <td className={styles.right}>{l.qty_initial.toLocaleString()}</td>
                  <td className={styles.right}>{l.qty_confirmed.toLocaleString()}</td>
                  <td className={styles.right}>{l.qty_stock.toLocaleString()}</td>
                </tr>
              ))}
              {!lines.length && <tr><td colSpan={6} className={styles.empty}>Sem linhas</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {selLine && (
        <div className={styles.panel}>
          <div className={styles.panelHeader}><span>Stock — {selLine.item_id}</span></div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>Armazém</th><th>Localização</th><th>Quantidade</th></tr></thead>
              <tbody>
                {stock.map((s, i) => (
                  <tr key={i} className={styles.row}>
                    <td>{s.wh_id} — {s.wh_desc}</td>
                    <td>{s.loc_id} — {s.loc_desc}</td>
                    <td className={styles.right}>{s.qty.toLocaleString()}</td>
                  </tr>
                ))}
                {!stock.length && <tr><td colSpan={3} className={styles.empty}>Sem stock</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className={styles.panel}>
        <div className={styles.panelHeader}>
          <span>Movimentos — por caixa</span>
          <select className={styles.boxSelect} value={selBox}
            onChange={e => loadMovements(e.target.value)}>
            <option value="">Selecciona caixa...</option>
            {boxes.map(box => (
              <option key={box.vol_num} value={box.vol_num}>
                Caixa {box.vol_num}{box.barcode ? ` - ${box.barcode}` : ''}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.tableWrap}><MovTable movs={movements} /></div>
      </div>
    </>
  )
}

function ViewByBox({ selected }) {
  const [boxes,     setBoxes]     = useState([])
  const [selBox,    setSelBox]    = useState(null)
  const [selItem,   setSelItem]   = useState(null)
  const [movements, setMovements] = useState([])

  useEffect(() => {
    if (!selected) return
    setBoxes([]); setSelBox(null); setSelItem(null); setMovements([])
    api.get(`/consulting/packings/${selected.order_id}/boxes?doc_type=${selected.doc_type}`).then(d => setBoxes(d || []))
  }, [selected])

  const selectItem = async (box, item) => {
    setSelBox(box); setSelItem(item)
    const d = await api.get(
      `/consulting/packings/${selected.order_id}/boxes/${box.vol_num}/items/${encodeURIComponent(item.item_id)}/movements`
    )
    setMovements(d || [])
  }

  return (
    <>
      {boxes.map(box => (
        <div key={box.vol_num} className={styles.panel}>
          <div className={styles.panelHeader}>
            <span>
              Caixa {box.vol_num}
              {box.barcode && <span className={styles.barcode}> · {box.barcode}</span>}
            </span>
            {(() => {
              const hasDiff = box.items.some(i => i.qty_confirmed !== i.qty_initial && i.qty_confirmed > 0)
              return (
                <span className={styles.badge}
                  style={{ background: box.verified ? (hasDiff ? '#d97706' : '#16a34a') : '#6b7280' }}>
                  {box.verified ? (hasDiff ? '⚠ Diferenças' : '✓ Conferida') : 'Por conferir'}
                </span>
              )
            })()}
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr>
                <th>Artigo</th><th>Ref. Cliente</th><th>Descrição</th>
                <th>Qtd Ini</th><th>Qtd Conf</th><th>Em Stock</th>
              </tr></thead>
              <tbody>
                {box.items.map(item => (
                  <tr key={item.item_id}
                    className={[
                      selBox?.vol_num === box.vol_num && selItem?.item_id === item.item_id
                        ? styles.rowSelected : styles.row,
                      item.qty_confirmed > 0 && item.qty_confirmed !== item.qty_initial
                        ? styles.rowDiff : ''
                    ].join(' ')}
                    onClick={() => selectItem(box, item)}>
                    <td className={styles.mono}>
                      {item.qty_confirmed > 0 && item.qty_confirmed !== item.qty_initial && (
                        <span title="Diferença entre previsto e conferido" style={{marginRight:'4px',color:'#d97706'}}>⚠</span>
                      )}
                      {item.item_id}
                    </td>
                    <td>{item.client_ref}</td><td>{item.item_desc}</td>
                    <td className={styles.right}>{item.qty_initial.toLocaleString()}</td>
                    <td className={styles.right}>{item.qty_confirmed.toLocaleString()}</td>
                    <td className={styles.right}>{item.qty_stock.toLocaleString()}</td>
                  </tr>
                ))}
                {!box.items.length && (
                  <tr><td colSpan={6} className={styles.empty}>Sem artigos</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {selItem && (
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <span>Movimentos — {selItem.item_id} / Caixa {selBox?.vol_num}</span>
          </div>
          <div className={styles.tableWrap}><MovTable movs={movements} /></div>
        </div>
      )}
    </>
  )
}

function PackingConsultation() {
  const [docType,  setDocType]  = useState('PSCP')
  const [status,   setStatus]   = useState('TODOS')
  const [viewMode, setViewMode] = useState('artigo')
  const [packings, setPackings] = useState([])
  const [loading,  setLoading]  = useState(false)
  const [selected, setSelected] = useState(null)
  const [searchText, setSearchText] = useState('')

  const search = useCallback(async () => {
    setLoading(true); setSelected(null)
    try {
      const data = await api.get(`/consulting/packings?doc_type=${docType}&status=${status}`)
      let result = Array.isArray(data) ? data : []
      if (searchText.trim()) {
        const q = searchText.trim().toLowerCase()
        result = result.filter(p =>
          String(p.order_id).includes(q) ||
          (p.requester_id || '').toLowerCase().includes(q)
        )
      }
      setPackings(result)
    } catch { setPackings([]) }
    finally { setLoading(false) }
  }, [docType, status])

  useEffect(() => { search() }, [])

  const exportCSV = () => {
    if (!selected) return
    window.open(`${BASE}/consulting/packings/${selected.order_id}/export?doc_type=${selected.doc_type}`, '_blank')
  }

  const exportTotals = () => {
    if (!selected) return
    window.open(`${BASE}/consulting/packings/${selected.order_id}/export-totals?doc_type=${selected.doc_type}`, '_blank')
  }

  return (
    <div className={styles.consultationSection}>
      <div className={styles.filterBar}>
        <div className={styles.filterGroup}>
          <label>Tipo</label>
          <select value={docType} onChange={e => setDocType(e.target.value)}>
            <option value="PSCP">Packing List (PSCP)</option>
            <option value="ESCP">Encomenda (ESCP)</option>
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label>Estado</label>
          <select value={status} onChange={e => setStatus(e.target.value)}>
            <option value="TODOS">Todos</option>
            <option value="INICIAL">Inicial</option>
            <option value="EMCONFERENCIA">Em conferência</option>
            <option value="FECHADO">Fechado</option>
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label>Vista</label>
          <div className={styles.toggle}>
            <button className={viewMode === 'artigo' ? styles.toggleActive : styles.toggleBtn}
              onClick={() => setViewMode('artigo')}>Por artigo</button>
            <button className={viewMode === 'caixa' ? styles.toggleActive : styles.toggleBtn}
              onClick={() => setViewMode('caixa')}>Por caixa</button>
          </div>
        </div>
        <div className={styles.filterGroup}>
          <label>Pesquisa</label>
          <input
            type="text" placeholder="Nº interno ou ref. cliente..."
            value={searchText} onChange={e => setSearchText(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && search()}
            className={styles.searchInput}
          />
        </div>
        <Btn variant="primary" onClick={search} loading={loading}>Pesquisar</Btn>
        {selected && (
          <Btn variant="outline" onClick={exportCSV}>↓ CSV Caixas</Btn>
        )}
        {selected && (
          <Btn variant="outline" onClick={exportTotals}>↓ CSV Totais</Btn>
        )}
      </div>

      <div className={styles.layout}>
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <span>Packing Lists ({packings.length})</span>

          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr>
                <th>Nº</th><th>Ref. Cliente</th><th>Cliente</th><th>Data</th><th>Estado</th>
                <th>Caixas</th><th>Qtd Ini</th><th>Qtd Conf</th><th>Em Stock</th>
              </tr></thead>
              <tbody>
                {packings.map(p => {
                  const st = STATUS_LABELS[p.status] || { label: p.status, color: '#888' }
                  return (
                    <tr key={p.order_id}
                      className={selected?.order_id === p.order_id ? styles.rowSelected : styles.row}
                      onClick={() => setSelected(p)}>
                      <td className={styles.mono}>{p.order_id}</td>
                      <td className={styles.mono}>{p.requester_id || '—'}</td>
                      <td>{p.client_id}</td>
                      <td>{p.order_date}</td>
                      <td><span className={styles.badge} style={{ background: st.color }}>{st.label}</span></td>
                      <td className={styles.center}>{p.confirmed_boxes}/{p.total_boxes}</td>
                      <td className={styles.right}>{p.qty_initial.toLocaleString()}</td>
                      <td className={styles.right}>{p.qty_confirmed.toLocaleString()}</td>
                      <td className={styles.right}>{p.qty_stock.toLocaleString()}</td>
                    </tr>
                  )
                })}
                {!loading && !packings.length && (
                  <tr><td colSpan={8} className={styles.empty}>Nenhum resultado</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {selected && viewMode === 'artigo' && <ViewByArticle selected={selected} />}
        {selected && viewMode === 'caixa'  && <ViewByBox     selected={selected} />}
      </div>
    </div>
  )
}

export default function Module3() {
  const [consultationType, setConsultationType] = useState('packings')

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>Consulta</h1>
          <p className={styles.pageDesc}>
            {consultationType === 'stocks'
              ? 'Existências atuais ou numa data anterior'
              : 'Packing lists e encomendas'}
          </p>
        </div>
        <div className={styles.sectionTabs} role="tablist" aria-label="Tipo de consulta">
          <button
            type="button"
            role="tab"
            aria-selected={consultationType === 'packings'}
            className={consultationType === 'packings' ? styles.sectionTabActive : styles.sectionTab}
            onClick={() => setConsultationType('packings')}
          >
            Packings
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={consultationType === 'stocks'}
            className={consultationType === 'stocks' ? styles.sectionTabActive : styles.sectionTab}
            onClick={() => setConsultationType('stocks')}
          >
            Stocks
          </button>
        </div>
      </div>

      {consultationType === 'stocks' ? <StockListing /> : <PackingConsultation />}
    </div>
  )
}
