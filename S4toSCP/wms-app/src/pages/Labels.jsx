import { useEffect, useMemo, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { Card, CardTitle, Btn, StatsBar, Stat } from '../components/ui'
import styles from './Labels.module.css'

const API = import.meta.env.VITE_API_URL ?? '/api'

async function request(path, options) {
  const res = await fetch(`${API}${path}`, options)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Erro no servidor' }))
    throw new Error(err.detail || 'Erro no servidor')
  }
  return res.json()
}

export default function Labels() {
  const toast = useToast()
  const [mode, setMode] = useState('item')
  const [printConfigs, setPrintConfigs] = useState([])
  const [selectedPrint, setSelectedPrint] = useState('')
  const [printing, setPrinting] = useState(false)

  const [itemSearch, setItemSearch] = useState('')
  const [items, setItems] = useState([])
  const [selectedItem, setSelectedItem] = useState(null)
  const [itemRows, setItemRows] = useState([])

  const [docTypes, setDocTypes] = useState([])
  const [docType, setDocType] = useState('')
  const [docSearch, setDocSearch] = useState('')
  const [documents, setDocuments] = useState([])
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [docRows, setDocRows] = useState([])

  const rows = mode === 'item' ? itemRows : docRows
  const totalLabels = useMemo(
    () => rows.reduce((sum, row) => sum + (parseInt(row.print_qty, 10) || 0), 0),
    [rows],
  )

  useEffect(() => {
    request('/labels/print-configs').then(setPrintConfigs).catch(() => {})
    request('/labels/document-types').then(setDocTypes).catch(() => {})
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      request(`/labels/items?search=${encodeURIComponent(itemSearch)}`)
        .then(setItems)
        .catch(e => toast(e.message, 'error'))
    }, 250)
    return () => clearTimeout(timer)
  }, [itemSearch])

  useEffect(() => {
    if (!docType) {
      setDocuments([])
      setSelectedDoc(null)
      setDocRows([])
      return
    }
    const timer = setTimeout(() => {
      request(`/labels/documents?doc_type=${encodeURIComponent(docType)}&search=${encodeURIComponent(docSearch)}`)
        .then(setDocuments)
        .catch(e => toast(e.message, 'error'))
    }, 250)
    return () => clearTimeout(timer)
  }, [docType, docSearch])

  const selectItem = async (item) => {
    setSelectedItem(item)
    try {
      if (item.dimensions) {
        const vars = await request(`/labels/items/${encodeURIComponent(item.item_id)}/variations`)
        setItemRows(vars.map(row => ({ ...row, item_desc: item.item_desc, print_qty: 0 })))
      } else {
        setItemRows([{
          item_id: item.item_id,
          item_desc: item.item_desc,
          color_id: '',
          grid_id: '',
          size_id: '',
          order_num: 0,
          print_qty: 0,
        }])
      }
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const selectDocument = async (doc) => {
    setSelectedDoc(doc)
    try {
      const lines = await request(`/labels/documents/${encodeURIComponent(doc.doc_type)}/${doc.order_id}/lines`)
      setDocRows(lines.map(row => ({ ...row, print_qty: 0 })))
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const setQty = (source, index, value) => {
    const qty = Math.max(0, parseInt(value, 10) || 0)
    const setter = source === 'item' ? setItemRows : setDocRows
    setter(prev => prev.map((row, i) => i === index ? { ...row, print_qty: qty } : row))
  }

  const preparePrint = async () => {
    if (printing) return

    if (!selectedPrint) {
      toast('Seleciona a etiqueta a imprimir', 'error')
      return
    }
    if (totalLabels <= 0) {
      toast('Indica pelo menos uma quantidade de etiquetas', 'error')
      return
    }

    try {
      setPrinting(true)
      const result = await request('/labels/print', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          config_file: selectedPrint,
          lines: rows
            .filter(row => (parseInt(row.print_qty, 10) || 0) > 0)
            .map(row => ({
              item_id: row.item_id,
              item_desc: row.item_desc || '',
              color_id: row.color_id || '',
              grid_id: row.grid_id || '',
              size_id: row.size_id || '',
              order_num: row.order_num || 0,
              order_row: row.order_row || null,
              print_qty: parseInt(row.print_qty, 10) || 0,
            })),
        }),
      })
      toast(`${result.labels_printed} etiqueta(s) enviadas para ${result.printer}`, 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setPrinting(false)
    }
  }

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Etiquetas RFID</h1>
        <p className={styles.pageDesc}>Preparação de etiquetas para impressora Zebra ZT411</p>
      </div>

      <div className={styles.modeRow}>
        <button className={`${styles.modeBtn} ${mode === 'item' ? styles.modeActive : ''}`} onClick={() => setMode('item')}>
          Por artigo
        </button>
        <button className={`${styles.modeBtn} ${mode === 'document' ? styles.modeActive : ''}`} onClick={() => setMode('document')}>
          Por documento
        </button>
      </div>

      <StatsBar>
        <Stat label="Linhas selecionadas" value={rows.filter(r => (parseInt(r.print_qty, 10) || 0) > 0).length} />
        <Stat label="Etiquetas a imprimir" value={totalLabels} color="var(--accent)" />
      </StatsBar>

      {mode === 'item' && (
        <Card>
          <CardTitle>Selecionar artigo</CardTitle>
          <div className={styles.grid}>
            <div className={styles.field}>
              <label>Artigo ou descricao</label>
              <input className={styles.input} value={itemSearch} onChange={e => setItemSearch(e.target.value)} placeholder="Pesquisar..." />
            </div>
          </div>
          <div className={styles.resultList} style={{marginTop:14}}>
            {items.map(item => (
              <div
                key={item.item_id}
                className={`${styles.resultItem} ${selectedItem?.item_id === item.item_id ? styles.resultActive : ''}`}
                onClick={() => selectItem(item)}
              >
                <div className={styles.mainText}>{item.item_id}</div>
                <div className={styles.subText}>{item.item_desc || '-'}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {mode === 'document' && (
        <Card>
          <CardTitle>Selecionar documento</CardTitle>
          <div className={styles.grid}>
            <div className={styles.field}>
              <label>Tipo de documento</label>
              <select className={styles.select} value={docType} onChange={e => setDocType(e.target.value)}>
                <option value="">Selecionar...</option>
                {docTypes.map(type => (
                  <option key={type.doc_type} value={type.doc_type}>{type.doc_type} - {type.doc_descr}</option>
                ))}
              </select>
            </div>
            <div className={styles.field}>
              <label>Documento, cliente ou nome</label>
              <input className={styles.input} value={docSearch} onChange={e => setDocSearch(e.target.value)} placeholder="Pesquisar..." disabled={!docType} />
            </div>
          </div>
          <div className={styles.resultList} style={{marginTop:14}}>
            {documents.map(doc => (
              <div
                key={`${doc.doc_type}-${doc.order_id}`}
                className={`${styles.resultItem} ${selectedDoc?.order_id === doc.order_id ? styles.resultActive : ''}`}
                onClick={() => selectDocument(doc)}
              >
                <div className={styles.mainText}>{doc.doc_type} #{doc.order_id}</div>
                <div className={styles.subText}>{doc.client_id} {doc.client_name ? `- ${doc.client_name}` : ''}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {rows.length > 0 && (
        <Card>
          <CardTitle>Quantidades de etiquetas</CardTitle>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Artigo</th>
                  <th>Descricao</th>
                  <th>Cor</th>
                  <th>Grelha</th>
                  <th>Tamanho</th>
                  {mode === 'document' && <th style={{textAlign:'right'}}>Qtd. doc.</th>}
                  <th style={{textAlign:'right'}}>Etiquetas</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.item_id}-${row.order_row || index}-${row.color_id}-${row.size_id}`}>
                    <td className={styles.mono}>{row.item_id}</td>
                    <td>{row.item_desc}</td>
                    <td className={styles.mono}>{row.color_id || '-'}</td>
                    <td className={styles.mono}>{row.grid_id || '-'}</td>
                    <td className={styles.mono}>{row.size_id || '-'}</td>
                    {mode === 'document' && <td className={styles.mono} style={{textAlign:'right'}}>{row.qty_ord}</td>}
                    <td style={{textAlign:'right'}}>
                      <input
                        className={`${styles.input} ${styles.qtyInput}`}
                        type="number"
                        min="0"
                        value={row.print_qty}
                        onChange={e => setQty(mode === 'item' ? 'item' : 'document', index, e.target.value)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className={styles.grid} style={{marginTop:16}}>
            <div className={styles.field}>
              <label>Etiqueta</label>
              <select className={styles.select} value={selectedPrint} onChange={e => setSelectedPrint(e.target.value)}>
                <option value="">Selecionar...</option>
                {printConfigs.map(config => (
                  <option key={config.file_name} value={config.file_name}>{config.description} - {config.file_name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className={styles.summary}>
            Total preparado: {totalLabels} etiqueta(s)
          </div>
          <div className={styles.actions}>
            <Btn variant="success" onClick={preparePrint}>{printing ? 'A imprimir...' : 'Imprimir'}</Btn>
          </div>
        </Card>
      )}
    </div>
  )
}
