import { useState, useEffect, useCallback } from 'react'
import { Btn } from '../components/ui'
import styles from './Module3.module.css'

const BASE = import.meta.env.VITE_API_URL ?? '/api'
const api = { get: (path) => fetch(`${BASE}${path}`).then(r => r.json()) }

const STATUS_LABELS = {
  INICIAL:       { label: 'Inicial',        color: '#6b7280' },
  EMCONFERENCIA: { label: 'Em conferência', color: '#d97706' },
  FECHADO:       { label: 'Fechado',         color: '#16a34a' },
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

export default function Module3() {
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
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Consulta</h1>
        <p className={styles.pageDesc}>Packing lists e encomendas</p>
      </div>
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
