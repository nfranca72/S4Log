import { useState, useRef, useCallback } from 'react'
import { packingApi, clientsApi, ordersApi } from '../services/api'
import { useToast } from '../context/ToastContext'
import {
  Steps, Card, CardTitle, StatsBar, Stat,
  InfoGrid, InfoField, Badge, Btn, ResultBanner, Spinner
} from '../components/ui'
import styles from './Module1.module.css'

// ── Tab: Encomenda ────────────────────────────────────────────────────────────
function TabEncomenda() {
  const toast = useToast()
  const [step, setStep]                   = useState(1)
  const [loading, setLoading]             = useState(false)
  const [preview, setPreview]             = useState(null)
  const [articlesCreated, setArticlesCreated] = useState(false)
  const [client, setClient]               = useState(null)
  const [clientQuery, setClientQuery]     = useState('')
  const [clientOptions, setClientOptions] = useState([])
  const [clientOpen, setClientOpen]       = useState(false)
  const [filter, setFilter]               = useState('all')
  const [search, setSearch]               = useState('')
  const [mode, setMode]                   = useState(null)        // 'new' | 'merge'
  const [escpOrders, setEscpOrders]       = useState([])
  const [selectedEscp, setSelectedEscp]   = useState(null)
  const [mergeDiff, setMergeDiff]         = useState(null)
  const [result, setResult]               = useState(null)
  const [mergeFile, setMergeFile]         = useState(null)
  const debounceRef = useRef(null)

  const STEPS = ['Upload Excel', 'Artigos', 'Encomenda', 'Resultado']

  const handleFile = async (file) => {
    if (!file?.name?.toUpperCase().match(/\.(XLSX|XLS)$/)) {
      toast('O ficheiro deve ser Excel (.xlsx)', 'error'); return
    }
    setLoading(true)
    try {
      const data = await ordersApi.preview(file)
      setPreview(data)
      setStep(2)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const onClientInput = (val) => {
    setClientQuery(val); setClient(null)
    clearTimeout(debounceRef.current)
    if (val.length < 1) { setClientOpen(false); return }
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await clientsApi.search(val)
        setClientOptions(data); setClientOpen(true)
      } catch { toast('Erro ao carregar clientes', 'error') }
    }, 300)
  }

  const selectClient = (c) => {
    setClient(c)
    setClientQuery(`${c.client_id} — ${c.client_name}`)
    setClientOpen(false)
  }

  const filteredRows = (preview?.rows ?? []).filter(r => {
    if (filter === 'new'    &&  r.exists_in_db) return false
    if (filter === 'exists' && !r.exists_in_db) return false
    if (search) {
      const q = search.toLowerCase()
      return r.item_id.toLowerCase().includes(q) ||
             r.descricao.toLowerCase().includes(q) ||
             r.style_color.toLowerCase().includes(q)
    }
    return true
  })

  const newItems = (() => {
    if (!preview) return []
    const seen = new Set()
    return preview.rows.filter(r => {
      if (r.exists_in_db || seen.has(r.item_id)) return false
      seen.add(r.item_id); return true
    })
  })()

  const doCreateArticles = async () => {
    setLoading(true)
    try {
      await ordersApi.createItems(preview.rows.filter(r => !r.exists_in_db))
      setArticlesCreated(true)
      toast(`Artigos criados com sucesso`)
      // Load ESCP orders for step 3
      const orders = await ordersApi.listEscp()
      setEscpOrders(orders)
      setStep(3)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const goToOrder = async () => {
    setLoading(true)
    try {
      const orders = await ordersApi.listEscp()
      setEscpOrders(orders)
      setStep(3)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const doMergePreview = async () => {
    if (!mergeFile) { toast('Seleciona o ficheiro para merge', 'error'); return }
    setLoading(true)
    try {
      const diff = await ordersApi.mergePreview(selectedEscp.order_id, mergeFile)
      setMergeDiff(diff)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const doCreateNew = async () => {
    if (!client) { toast('Seleciona um cliente', 'error'); return }
    setLoading(true)
    try {
      const obs = preview.rows[0]?.nota_giaf || ''
      const res = await ordersApi.createEscp(client.client_id, preview.rows, obs)
      setResult({ type: 'new', ...res })
      setStep(4)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const doApplyMerge = async () => {
    setLoading(true)
    try {
      await ordersApi.mergeApply(
        selectedEscp.order_id,
        mergeDiff.added.map(r => ({ ...r })),
        mergeDiff.changed.map(c => ({ so_number: c.row.so_number, new_qty: c.new_qty }))
      )
      setResult({ type: 'merge', order_id: selectedEscp.order_id, added: mergeDiff.added.length, changed: mergeDiff.changed.length })
      setStep(4)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const reset = () => {
    setStep(1); setPreview(null); setClient(null); setClientQuery('')
    setMode(null); setSelectedEscp(null); setMergeDiff(null)
    setResult(null); setArticlesCreated(false); setFilter('all'); setSearch('')
  }

  return (
    <div>
      <Steps steps={STEPS} current={step} />

      {/* Step 1 — Upload */}
      {step === 1 && (
        <Card>
          <CardTitle>Ficheiro Excel de encomenda</CardTitle>
          <div className={styles.dropZone} onClick={() => document.getElementById('orderInput').click()}>
            <input id="orderInput" type="file" accept=".xlsx,.xls" style={{display:'none'}}
              onChange={e => handleFile(e.target.files[0])} />
            {loading ? <><Spinner size={32}/><p style={{marginTop:16,color:'var(--text2)'}}>A processar...</p></>
              : <>
                  <div className={styles.dropIcon}>📊</div>
                  <h3 className={styles.dropTitle}>Arraste o ficheiro Excel ou clique para selecionar</h3>
                  <p className={styles.dropDesc}>Formato: SO Number · NEG/DOT · PO Number · Style/Color · Código GIAF · Descrição · Tamanho · Quantidade</p>
                </>}
          </div>
        </Card>
      )}

      {/* Step 2 — Articles */}
      {step === 2 && preview && (
        <>
          <StatsBar>
            <Stat label="Linhas"          value={preview.total_lines} />
            <Stat label="Total peças"     value={preview.total_qty}   color="var(--accent)" />
            <Stat label="Artigos únicos"  value={preview.unique_items} />
            <Stat label="Já existem"      value={preview.existing_items} color="var(--green)" />
            <Stat label="A criar"         value={preview.new_items}   color="var(--yellow)" />
          </StatsBar>

          <div className={styles.actions} style={{marginBottom:4}}>
            <Btn variant="outline" onClick={reset}>← Voltar</Btn>
            {newItems.length > 0 && !articlesCreated
              ? <Btn variant="primary" loading={loading} onClick={doCreateArticles}>Criar {newItems.length} artigo(s) →</Btn>
              : <Btn variant="primary" loading={loading} onClick={goToOrder}>Continuar →</Btn>
            }
          </div>

          <Card>
            <CardTitle>Artigos da encomenda</CardTitle>
            <div className={styles.tableFilters}>
              {['all','new','exists'].map(f => (
                <button key={f} className={`${styles.filterBtn} ${filter===f?styles.filterActive:''}`} onClick={()=>setFilter(f)}>
                  {f==='all'?'Todos':f==='new'?'Novos':'Existentes'}
                </button>
              ))}
              <input className={styles.searchInput} placeholder="Pesquisar..." value={search} onChange={e=>setSearch(e.target.value)} />
            </div>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr>
                  <th>Código</th><th>Descrição</th><th>GIAF</th>
                  <th>Style/Color</th><th>Tam.</th><th>NEG/DOT</th>
                  <th style={{textAlign:'right'}}>Qtd.</th><th>Estado</th>
                </tr></thead>
                <tbody>
                  {filteredRows.map((r,i) => (
                    <tr key={i}>
                      <td className={styles.mono} style={{fontSize:12}}>{r.item_id}</td>
                      <td className={styles.desc}>{r.descricao}</td>
                      <td className={`${styles.mono} ${styles.muted}`} style={{fontSize:11}}>{r.codigo_giaf}</td>
                      <td className={styles.mono}>{r.style_color}</td>
                      <td><span className={styles.sizePill}>{r.tamanho}</span></td>
                      <td><span className={styles.sizePill}>{r.neg_dot}</span></td>
                      <td className={styles.mono} style={{textAlign:'right'}}>{r.quantidade}</td>
                      <td><Badge type={r.exists_in_db?'exists':'new'}>{r.exists_in_db?'Existe':'Novo'}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Articles creation */}
          {newItems.length > 0 && !articlesCreated && (
            <Card>
              <CardTitle>Artigos a criar ({newItems.length})</CardTitle>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead><tr><th>Código</th><th>Descrição</th><th>GIAF</th><th>Modelo</th></tr></thead>
                  <tbody>
                    {newItems.map((r,i) => (
                      <tr key={i}>
                        <td className={styles.mono} style={{fontSize:12}}>{r.item_id}</td>
                        <td className={styles.muted}>{r.descricao}</td>
                        <td className={`${styles.mono} ${styles.muted}`}>{r.codigo_giaf}</td>
                        <td className={styles.mono}>{r.style_color}-{r.tamanho}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
          {articlesCreated && newItems.length > 0 && (
            <div className={styles.emptyMsg} style={{color:'var(--green)'}}>✓ {newItems.length} artigo(s) criado(s)</div>
          )}

        </>
      )}

      {/* Step 3 — Order */}
      {step === 3 && (
        <>
          {!mode && (
            <Card>
              <CardTitle>Encomenda ESCP</CardTitle>
              <p style={{color:'var(--text2)',fontSize:14,marginBottom:20}}>
                Pretende criar uma nova encomenda ou adicionar à uma encomenda já existente?
              </p>
              <div className={styles.actions}>
                <Btn variant="primary" onClick={() => setMode('new')}>Criar nova encomenda</Btn>
                <Btn variant="outline" onClick={() => setMode('merge')}>Adicionar a encomenda existente</Btn>
              </div>
            </Card>
          )}

          {mode === 'new' && (
            <Card>
              <CardTitle>Nova encomenda ESCP</CardTitle>
              <div style={{marginBottom:20}}>
                <label className={styles.clientLabel}>Cliente *</label>
                <div className={styles.clientWrap}>
                  <input className={styles.clientInput} type="text" placeholder="Pesquisar cliente..."
                    value={clientQuery} onChange={e => onClientInput(e.target.value)}
                    onFocus={() => clientQuery && setClientOpen(true)}
                    onBlur={() => setTimeout(() => setClientOpen(false), 200)} />
                  {clientOpen && clientOptions.length > 0 && (
                    <div className={styles.dropdown}>
                      {clientOptions.map(c => (
                        <div key={c.client_id} className={styles.dropdownItem} onMouseDown={() => selectClient(c)}>
                          <span className={styles.dropdownId}>{c.client_id}</span>
                          <span className={styles.dropdownName}>{c.client_name}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {client && <div className={styles.clientConfirm}>✓ {client.client_id} — {client.client_name}</div>}
              </div>
              <div className={styles.actions}>
                <Btn variant="outline" onClick={() => setMode(null)}>← Voltar</Btn>
                <Btn variant="success" loading={loading} disabled={!client} onClick={doCreateNew}>
                  Criar encomenda com {preview?.rows.length} linhas →
                </Btn>
              </div>
            </Card>
          )}

          {mode === 'merge' && !mergeDiff && (
            <Card>
              <CardTitle>Adicionar a encomenda existente</CardTitle>
              <div className={styles.tableWrap} style={{marginBottom:16}}>
                <table className={styles.table}>
                  <thead><tr><th>Nº</th><th>Cliente</th><th>Data</th><th>Linhas</th><th>Total peças</th><th></th></tr></thead>
                  <tbody>
                    {escpOrders.map(o => (
                      <tr key={o.order_id} className={selectedEscp?.order_id===o.order_id?styles.rowActive:''}
                        onClick={() => setSelectedEscp(o)} style={{cursor:'pointer'}}>
                        <td className={styles.mono}>#{o.order_id}</td>
                        <td>{o.client_id}</td>
                        <td className={styles.muted}>{o.order_date}</td>
                        <td className={styles.mono}>{o.total_lines}</td>
                        <td className={styles.mono}>{o.total_qty}</td>
                        <td>{selectedEscp?.order_id===o.order_id && <span className={styles.activePill}>Selecionada</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedEscp && (
                <div style={{marginTop:12}}>
                  <label className={styles.clientLabel}>Ficheiro para merge</label>
                  <input type="file" accept=".xlsx,.xls" onChange={e => setMergeFile(e.target.files[0])}
                    className={styles.clientInput} style={{cursor:'pointer'}} />
                </div>
              )}
              <div className={styles.actions} style={{marginTop:16}}>
                <Btn variant="outline" onClick={() => setMode(null)}>← Voltar</Btn>
                <Btn variant="primary" loading={loading} disabled={!selectedEscp || !mergeFile} onClick={doMergePreview}>
                  Ver diferenças →
                </Btn>
              </div>
            </Card>
          )}

          {mode === 'merge' && mergeDiff && (
            <Card>
              <CardTitle>Diferenças encontradas — Encomenda #{mergeDiff.order_id}</CardTitle>
              <StatsBar>
                <Stat label="Linhas novas"    value={mergeDiff.added.length}   color="var(--yellow)" />
                <Stat label="Qtd. alteradas"  value={mergeDiff.changed.length} color="var(--accent)" />
                <Stat label="Sem alterações"  value={mergeDiff.unchanged} />
              </StatsBar>

              {mergeDiff.changed.length > 0 && (
                <>
                  <div className={styles.cardTitle} style={{marginTop:16}}>Quantidades alteradas</div>
                  <table className={styles.table}>
                    <thead><tr><th>Artigo</th><th>SO Number</th><th style={{textAlign:'right'}}>Qtd. atual</th><th style={{textAlign:'right'}}>Qtd. nova</th></tr></thead>
                    <tbody>
                      {mergeDiff.changed.map((c,i) => (
                        <tr key={i}>
                          <td className={styles.mono} style={{fontSize:12}}>{c.row.item_id}</td>
                          <td className={styles.muted}>{c.row.so_number}</td>
                          <td className={styles.mono} style={{textAlign:'right',color:'var(--text3)'}}>{c.old_qty}</td>
                          <td className={styles.mono} style={{textAlign:'right',color:'var(--accent)'}}>{c.new_qty}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}

              {mergeDiff.added.length > 0 && (
                <>
                  <div className={styles.cardTitle} style={{marginTop:16}}>Linhas novas</div>
                  <table className={styles.table}>
                    <thead><tr><th>Artigo</th><th>PO Number</th><th style={{textAlign:'right'}}>Qtd.</th></tr></thead>
                    <tbody>
                      {mergeDiff.added.map((r,i) => (
                        <tr key={i}>
                          <td className={styles.mono} style={{fontSize:12}}>{r.item_id}</td>
                          <td className={styles.muted}>{r.po_number}</td>
                          <td className={styles.mono} style={{textAlign:'right'}}>{r.quantidade}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}

              <div className={styles.actions} style={{marginTop:16}}>
                <Btn variant="outline" onClick={() => setMergeDiff(null)}>← Voltar</Btn>
                <Btn variant="success" loading={loading} onClick={doApplyMerge}>
                  Aplicar alterações →
                </Btn>
              </div>
            </Card>
          )}
        </>
      )}

      {/* Step 4 — Result */}
      {step === 4 && result && (
        <>
          <ResultBanner ok={true}
            title={result.type==='new' ? 'Encomenda criada com sucesso' : 'Merge aplicado com sucesso'}
            detail={result.type==='new'
              ? `Encomenda #${result.order_id} criada com ${result.total_lines} linhas e ${result.total_qty} peças.`
              : `Encomenda #${result.order_id}: ${result.added} linhas adicionadas, ${result.changed} quantidades atualizadas.`
            }
          />
          <div className={styles.actions}>
            <Btn variant="success" onClick={reset}>Nova importação</Btn>
          </div>
        </>
      )}
    </div>
  )
}

// ── Tab: Packing List ─────────────────────────────────────────────────────────
const PACKING_STEPS = ['Upload CSV', 'Preview & Cliente', 'Artigos', 'Resultado']

function TabPacking() {
  const toast = useToast()
  const [step, setStep]                   = useState(1)
  const [loading, setLoading]             = useState(false)
  const [preview, setPreview]             = useState(null)
  const [client, setClient]               = useState(null)
  const [clientQuery, setClientQuery]     = useState('')
  const [clientOptions, setClientOptions] = useState([])
  const [clientOpen, setClientOpen]       = useState(false)
  const [filter, setFilter]               = useState('all')
  const [search, setSearch]               = useState('')
  const [result, setResult]               = useState(null)
  const [articlesCreated, setArticlesCreated] = useState(false)
  const [escpOrders, setEscpOrders]       = useState([])
  const [selectedEscp, setSelectedEscp]   = useState(null)
  const [escpLoaded, setEscpLoaded]       = useState(false)
  const debounceRef = useRef(null)
  const fileRef     = useRef(null)

  const handleFile = async (file) => {
    if (!file?.name?.toUpperCase().endsWith('.CSV')) { toast('Ficheiro deve ser .CSV', 'error'); return }
    setLoading(true)
    try {
      const url = selectedEscp
        ? `/api/packing/preview?escp_order_id=${selectedEscp.order_id}`
        : '/api/packing/preview'

      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(url, { method: 'POST', body: fd })
      if (!res.ok) {
        const err = await res.json()
        if (err.detail?.errors) throw new Error(err.detail.errors.join('\n'))
        throw new Error(err.detail || 'Erro no servidor')
      }
      const data = await res.json()
      setPreview(data)
      setStep(2)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const loadEscpOrders = async () => {
    if (escpLoaded) return
    try {
      const orders = await ordersApi.listEscp()
      setEscpOrders(orders)
      setEscpLoaded(true)
    } catch { toast('Erro ao carregar encomendas', 'error') }
  }

  const onClientInput = (val) => {
    setClientQuery(val); setClient(null)
    clearTimeout(debounceRef.current)
    if (val.length < 1) { setClientOpen(false); return }
    debounceRef.current = setTimeout(async () => {
      try { const d = await clientsApi.search(val); setClientOptions(d); setClientOpen(true) }
      catch { toast('Erro ao carregar clientes', 'error') }
    }, 300)
  }

  const selectClient = (c) => {
    setClient(c); setClientQuery(`${c.client_id} — ${c.client_name}`); setClientOpen(false)
  }

  const filteredRows = (preview?.rows ?? []).filter(r => {
    if (filter === 'new'    &&  r.exists_in_db) return false
    if (filter === 'exists' && !r.exists_in_db) return false
    if (search) {
      const q = search.toLowerCase()
      return r.item_id.toLowerCase().includes(q) || r.season_desc.toLowerCase().includes(q) || r.ean.includes(q)
    }
    return true
  })

  const newItems = (() => {
    if (!preview) return []
    const seen = new Set()
    return preview.rows.filter(r => { if (r.exists_in_db || seen.has(r.item_id)) return false; seen.add(r.item_id); return true })
  })()

  const doCreateArticles = async () => {
    setLoading(true)
    try {
      await packingApi.createItems(newItems)
      setArticlesCreated(true)
      toast(`${newItems.length} artigo(s) criado(s) com sucesso`)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const doImport = async () => {
    setLoading(true)
    try {
      const data = await fetch('/api/packing/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id:     '',  // backend obtém da encomenda ESCP
          csv_rows:      preview.rows,
          header:        preview.header,
          escp_order_id: selectedEscp?.order_id || null,
        }),
      }).then(r => r.json())
      setResult(data); setStep(4)
    } catch (e) { toast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const reset = () => {
    setStep(1); setPreview(null); setClient(null); setClientQuery('')
    setResult(null); setFilter('all'); setSearch(''); setArticlesCreated(false)
    setSelectedEscp(null)
  }

  const h = preview?.header

  return (
    <div>
      <Steps steps={PACKING_STEPS} current={step} />

      {step === 1 && (
        <Card>
          <CardTitle>Encomenda inicial (opcional mas recomendado)</CardTitle>
          <p style={{color:'var(--text2)',fontSize:13,marginBottom:14}}>
            Associar a uma encomenda ESCP permite resolver automaticamente os códigos de artigo corretos.
          </p>
          <div className={styles.escpRow}>
            <select className={styles.select} value={selectedEscp?.order_id||''}
              onChange={e => setSelectedEscp(escpOrders.find(o => o.order_id === parseInt(e.target.value)) || null)}
              onFocus={loadEscpOrders}>
              <option value="">Seleciona uma encomenda ESCP</option>
              {escpOrders.map(o => <option key={o.order_id} value={o.order_id}>#{o.order_id} — {o.client_id} ({o.total_lines} linhas)</option>)}
            </select>
            {selectedEscp && <span className={styles.activePill}>✓ Encomenda #{selectedEscp.order_id}</span>}
          </div>

          <div style={{marginTop:20}}>
            <CardTitle>Ficheiro CSV {!selectedEscp && <span style={{color:'var(--red)',fontSize:11,fontWeight:400}}>— seleciona primeiro uma encomenda</span>}</CardTitle>
            <div
              className={styles.dropZone}
              onClick={() => selectedEscp && document.getElementById('csvInput').click()}
              style={{opacity: selectedEscp ? 1 : 0.4, cursor: selectedEscp ? 'pointer' : 'not-allowed'}}
            >
              <input id="csvInput" type="file" accept=".csv,.CSV" style={{display:'none'}} ref={fileRef}
                onChange={e => handleFile(e.target.files[0])} disabled={!selectedEscp} />
              {loading ? <><Spinner size={32}/><p style={{marginTop:16,color:'var(--text2)'}}>A processar...</p></>
                : <>
                    <div className={styles.dropIcon}>📄</div>
                    <h3 className={styles.dropTitle}>
                      {selectedEscp ? 'Arraste o CSV ou clique para selecionar' : 'Seleciona primeiro uma encomenda ESCP'}
                    </h3>
                    <p className={styles.dropDesc}>Formato Nike — HEADER1 / HEADER2 / HEADER3 + linhas de detalhe</p>
                  </>}
            </div>
          </div>
        </Card>
      )}

      {step === 2 && preview && (
        <>
          <StatsBar>
            <Stat label="Caixas"          value={preview.total_boxes}       color="var(--accent)" />
            <Stat label="Total peças"     value={preview.total_qty}         color="var(--accent)" />
            <Stat label="Artigos únicos"  value={preview.total_articles} />
            <Stat label="Já existem"      value={preview.existing_articles} color="var(--green)" />
            <Stat label="A criar"         value={preview.new_articles}      color="var(--yellow)" />
          </StatsBar>

          <Card>
            <CardTitle>Informação do documento</CardTitle>
            <InfoGrid>
              <InfoField label="Nº Documento"    value={h.doc_num}         mono />
              <InfoField label="Data entrega"    value={h.delivery_date}   mono />
              <InfoField label="Nº caixas"       value={h.num_boxes}       mono />
              <InfoField label="Total peças"     value={h.total_qty}       mono />
              {selectedEscp && <InfoField label="Encomenda" value={`#${selectedEscp.order_id}`} mono />}
            </InfoGrid>
            <div style={{marginTop:'12px'}}>
              <div style={{fontSize:'11px',fontWeight:500,color:'var(--text2)',textTransform:'uppercase',letterSpacing:'.05em',marginBottom:'4px'}}>Ref. Fornecedor</div>
              <div style={{fontSize:'12px',fontFamily:'var(--font-mono)',background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'6px',padding:'8px 10px',wordBreak:'break-all',lineHeight:'1.8',maxHeight:'80px',overflowY:'auto'}}>
                {h.ref_supplier || '—'}
              </div>
            </div>

            <div className={styles.clientSection}>
              <div className={styles.clientConfirm} style={{marginTop:0}}>
                ✓ Cliente será assumido da encomenda #{selectedEscp?.order_id}
              </div>
            </div>
          </Card>

          <div className={styles.actions} style={{marginBottom:4}}>
            <Btn variant="outline" onClick={reset}>← Novo ficheiro</Btn>
            <Btn variant="primary" onClick={() => { setArticlesCreated(false); setStep(3) }}>Verificar artigos →</Btn>
          </div>

          <Card>
            <CardTitle>Linhas do packing list</CardTitle>
            <div className={styles.tableFilters}>
              {['all','new','exists'].map(f => (
                <button key={f} className={`${styles.filterBtn} ${filter===f?styles.filterActive:''}`} onClick={()=>setFilter(f)}>
                  {f==='all'?'Todos':f==='new'?'Novos':'Existentes'}
                </button>
              ))}
              <input className={styles.searchInput} placeholder="Pesquisar artigo..." value={search} onChange={e=>setSearch(e.target.value)} />
            </div>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr>
                  <th>Artigo</th><th>Descrição</th><th>EAN</th><th>Cor</th>
                  <th>Tam.</th><th>País</th><th style={{textAlign:'right'}}>Qtd. Cx</th>
                  <th style={{textAlign:'right'}}>Qtd. Total</th><th>Estado</th>
                </tr></thead>
                <tbody>
                  {filteredRows.map((r,i) => (
                    <tr key={i}>
                      <td className={styles.mono} style={{fontSize:12}}>{r.item_id}</td>
                      <td className={styles.desc}>{r.season_desc}</td>
                      <td className={styles.mono} style={{fontSize:12}}>{r.ean}</td>
                      <td className={styles.mono}>{r.color_code}</td>
                      <td><span className={styles.sizePill}>{r.size}</span></td>
                      <td className={styles.mono}>{r.country}</td>
                      <td className={styles.mono} style={{textAlign:'right'}}>{r.qty_box}</td>
                      <td className={styles.mono} style={{textAlign:'right'}}>{r.qty_total}</td>
                      <td><Badge type={r.exists_in_db?'exists':'new'}>{r.exists_in_db?'Existe':'Novo'}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

        </>
      )}

      {step === 3 && (
        <>
          <Card>
            <CardTitle>Artigos a criar no sistema</CardTitle>
            {newItems.length === 0
              ? <div className={styles.emptyMsg}>✓ Todos os artigos já existem na base de dados</div>
              : articlesCreated
                ? <div className={styles.emptyMsg} style={{color:'var(--green)'}}>✓ {newItems.length} artigo(s) criado(s)</div>
                : <>
                    <p className={styles.articlesNote}>Os seguintes <strong>{newItems.length}</strong> artigo(s) serão criados:</p>
                    <div className={styles.tableWrap} style={{marginTop:14}}>
                      <table className={styles.table}>
                        <thead><tr><th>Código</th><th>Descrição</th><th>EAN</th><th>País</th><th>Marca</th></tr></thead>
                        <tbody>
                          {newItems.map((r,i) => (
                            <tr key={i}>
                              <td className={styles.mono} style={{fontSize:12}}>{r.item_id}</td>
                              <td className={styles.muted}>{r.season_desc}</td>
                              <td className={styles.mono} style={{fontSize:12}}>{r.ean}</td>
                              <td className={styles.mono}>{r.country}</td>
                              <td style={{color:'var(--accent)'}}>NIKE</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
            }
          </Card>
          <div className={styles.actions}>
            <Btn variant="outline" onClick={() => setStep(2)}>← Voltar</Btn>
            {newItems.length > 0 && !articlesCreated
              ? <Btn variant="primary" loading={loading} onClick={doCreateArticles}>Criar {newItems.length} artigo(s) →</Btn>
              : <Btn variant="success" loading={loading} onClick={doImport}>Importar packing list →</Btn>
            }
          </div>
        </>
      )}

      {step === 4 && result && (
        <>
          <ResultBanner ok={result.packing?.qty_match}
            title={result.packing?.qty_match ? 'Importação concluída com sucesso' : 'Importação concluída com avisos'}
            detail={`Packing list #${result.packing?.order_id} criado.${result.warnings?.length ? ' ' + result.warnings.join(' ') : ''}`}
          />
          <Card>
            <CardTitle>Resumo</CardTitle>
            <InfoGrid>
              <InfoField label="Nº Packing"        value={result.packing?.order_id}    mono />
              <InfoField label="Cliente"            value={selectedEscp?.client_id || result.packing?.client_id} mono />
              <InfoField label="Total peças"        value={result.packing?.total_qty}   mono />
              <InfoField label="Total caixas"       value={result.packing?.total_boxes} mono />
              <InfoField label="Artigos criados"    value={result.items_created}        mono />
              <InfoField label="Quantidades ok"     value={result.packing?.qty_match ? '✓ Sim' : '⚠ Divergência'} mono />
            </InfoGrid>
          </Card>
          <div className={styles.actions}>
            <Btn variant="success" onClick={reset}>Nova importação</Btn>
          </div>
        </>
      )}
    </div>
  )
}

// ── Main Module1 ──────────────────────────────────────────────────────────────
export default function Module1() {
  const [activeTab, setActiveTab] = useState('encomenda')

  return (
    <div>
      <div style={{marginBottom:28}}>
        <h1 style={{fontSize:22,fontWeight:600,marginBottom:6}}>Importação</h1>
        <p style={{fontSize:13,color:'var(--text2)'}}>Encomendas e packing lists Nike</p>
      </div>

      <div style={{display:'flex',gap:2,marginBottom:24,background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'var(--radius)',overflow:'hidden'}}>
        {[
          { key: 'encomenda', label: '📋 Encomenda (Excel)' },
          { key: 'packing',   label: '📦 Packing List (CSV)' },
        ].map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
            flex:1, padding:'12px 20px', border:'none', cursor:'pointer',
            background: activeTab===t.key ? 'rgba(79,142,247,.15)' : 'transparent',
            color: activeTab===t.key ? 'var(--accent)' : 'var(--text2)',
            fontFamily:'var(--font-sans)', fontSize:14, fontWeight: activeTab===t.key ? 600 : 400,
            borderBottom: activeTab===t.key ? '2px solid var(--accent)' : '2px solid transparent',
            transition:'all .15s',
          }}>{t.label}</button>
        ))}
      </div>

      {activeTab === 'encomenda' && <TabEncomenda />}
      {activeTab === 'packing'   && <TabPacking />}
    </div>
  )
}
