import { useEffect, useMemo, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { Btn, Card, CardTitle, ResultBanner, Stat, StatsBar } from '../components/ui'
import { supplyApi } from '../services/api'
import styles from './Abastecimento.module.css'

const DRAFTS_KEY = 's4log:abastecimento:drafts'

function stamp() {
  return new Date().toLocaleString('pt-PT')
}

function nextNumber(values) {
  return values.length ? Math.max(...values) + 1 : 1
}

function loadDrafts() {
  try {
    const raw = window.localStorage.getItem(DRAFTS_KEY)
    const parsed = JSON.parse(raw || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveDrafts(value) {
  window.localStorage.setItem(DRAFTS_KEY, JSON.stringify(value))
}

function flattenBoxes(pallets, looseBoxes) {
  const palletBoxes = pallets.flatMap(pallet =>
    pallet.boxes.map(box => ({
      ...box,
      label: `PLT ${pallet.number} / CX ${box.number}`,
      parent_label: `PLT ${pallet.number}`,
    }))
  )

  const freeBoxes = looseBoxes.map(box => ({
    ...box,
    label: `CX ${box.number}`,
    parent_label: 'Caixa solta',
  }))

  return [...palletBoxes, ...freeBoxes]
}

function totalAssignedForItem(pallets, looseBoxes, itemId) {
  return flattenBoxes(pallets, looseBoxes).reduce((sum, box) => {
    const boxTotal = box.allocations
      .filter(allocation => allocation.item_id === itemId)
      .reduce((acc, allocation) => acc + Number(allocation.qty || 0), 0)
    return sum + boxTotal
  }, 0)
}

function totalAllocatedVolumes(pallets, looseBoxes) {
  return flattenBoxes(pallets, looseBoxes).reduce(
    (sum, box) => sum + box.allocations.length,
    0
  )
}

function applyToBoxes(pallets, looseBoxes, boxId, updater) {
  const nextPallets = pallets.map(pallet => ({
    ...pallet,
    boxes: pallet.boxes.map(box => (box.id === boxId ? updater(box) : box)),
  }))
  const nextLooseBoxes = looseBoxes.map(box => (box.id === boxId ? updater(box) : box))
  return { nextPallets, nextLooseBoxes }
}

export default function Abastecimento() {
  const toast = useToast()

  const [partners, setPartners] = useState([])
  const [partnerSearch, setPartnerSearch] = useState('')
  const [selectedPartner, setSelectedPartner] = useState(null)

  const [warehouses, setWarehouses] = useState([])
  const [docTypes, setDocTypes] = useState([])
  const [documents, setDocuments] = useState([])
  const [requirements, setRequirements] = useState([])
  const [requirementsSummary, setRequirementsSummary] = useState(null)

  const [docType, setDocType] = useState('')
  const [documentSearch, setDocumentSearch] = useState('')
  const [selectedOrderIds, setSelectedOrderIds] = useState([])
  const [documentsModalOpen, setDocumentsModalOpen] = useState(false)
  const [pendingOrderIds, setPendingOrderIds] = useState([])

  const [whOrig, setWhOrig] = useState('')
  const [whDest, setWhDest] = useState('')
  const [locOrig, setLocOrig] = useState('')
  const [locDest, setLocDest] = useState('')
  const [origLocations, setOrigLocations] = useState([])
  const [destLocations, setDestLocations] = useState([])

  const [shipQtyByItem, setShipQtyByItem] = useState({})
  const [allocEditor, setAllocEditor] = useState({})

  const [pallets, setPallets] = useState([])
  const [looseBoxes, setLooseBoxes] = useState([])
  const [draftName, setDraftName] = useState('')
  const [drafts, setDrafts] = useState([])
  const [validation, setValidation] = useState(null)

  const [loadingBase, setLoadingBase] = useState(true)
  const [loadingDocuments, setLoadingDocuments] = useState(false)
  const [loadingRequirements, setLoadingRequirements] = useState(false)

  const allBoxes = useMemo(() => flattenBoxes(pallets, looseBoxes), [pallets, looseBoxes])

  useEffect(() => {
    let cancelled = false
    async function loadBase() {
      setLoadingBase(true)
      try {
        const [docTypeRows, warehouseRows] = await Promise.all([
          supplyApi.documentTypes(),
          supplyApi.warehouses(),
        ])
        if (cancelled) return
        setDocTypes(docTypeRows)
        setWarehouses(warehouseRows)
        setDocType(docTypeRows[0]?.doc_type || '')
        setWhOrig(warehouseRows[0]?.wh_id ? String(warehouseRows[0].wh_id) : '')
        setWhDest(warehouseRows[1]?.wh_id ? String(warehouseRows[1].wh_id) : '')
        setDrafts(loadDrafts())
      } catch (error) {
        toast(error.message || 'Erro ao carregar dados base', 'error')
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
    const timer = setTimeout(async () => {
      try {
        const rows = await supplyApi.partners(docType, partnerSearch)
        if (!cancelled) setPartners(rows)
      } catch {
        if (!cancelled) setPartners([])
      }
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [docType, partnerSearch])

  useEffect(() => {
    setSelectedPartner(null)
  }, [docType])

  useEffect(() => {
    if (!whOrig) {
      setOrigLocations([])
      setLocOrig('')
      return
    }
    supplyApi.locations(whOrig)
      .then(rows => {
        setOrigLocations(rows)
        setLocOrig(rows[0]?.location_id || '')
      })
      .catch(() => {
        setOrigLocations([])
        setLocOrig('')
      })
  }, [whOrig])

  useEffect(() => {
    if (!whDest) {
      setDestLocations([])
      setLocDest('')
      return
    }
    supplyApi.locations(whDest)
      .then(rows => {
        setDestLocations(rows)
        setLocDest(rows[0]?.location_id || '')
      })
      .catch(() => {
        setDestLocations([])
        setLocDest('')
      })
  }, [whDest])

  async function fetchDocuments() {
    if (!docType) {
      toast('Seleciona o tipo de ordem de fabrico', 'error')
      return
    }
    if (!selectedPartner?.partner_id) {
      toast('Seleciona primeiro o fornecedor/subcontratado', 'error')
      return
    }
    setLoadingDocuments(true)
    try {
      const rows = await supplyApi.documents(docType, selectedPartner?.partner_id || '', documentSearch)
      setDocuments(rows)
      setPendingOrderIds(selectedOrderIds.filter(orderId => rows.some(row => row.order_id === orderId)))
      setDocumentsModalOpen(true)
      if (rows.length === 0) {
        toast('Nao foram encontradas ordens para os filtros selecionados', 'error')
      } else {
        toast(`${rows.length} ordens carregadas com sucesso`)
      }
    } catch (error) {
      toast(error.message || 'Erro ao carregar ordens', 'error')
      setDocuments([])
    } finally {
      setLoadingDocuments(false)
    }
  }

  function togglePendingOrder(orderId) {
    setPendingOrderIds(current =>
      current.includes(orderId)
        ? current.filter(value => value !== orderId)
        : [...current, orderId]
    )
  }

  function applySelectedOrders() {
    setSelectedOrderIds(pendingOrderIds)
    setDocumentsModalOpen(false)
    toast(`${pendingOrderIds.length} ordens selecionadas`)
  }

  async function fetchRequirements() {
    if (!selectedOrderIds.length) {
      toast('Seleciona pelo menos uma ordem', 'error')
      return
    }
    if (!whOrig) {
      toast('Seleciona o armazem de origem', 'error')
      return
    }
    setLoadingRequirements(true)
    try {
      const result = await supplyApi.requirements({
        doc_type: docType,
        order_ids: selectedOrderIds,
        wh_id_orig: Number(whOrig),
      })
      const lines = result.groups.flatMap(group => group.lines)
      setRequirements(result.groups)
      setRequirementsSummary(result.summary)
      setShipQtyByItem(Object.fromEntries(
        lines.map(line => [line.item_id, String(line.qty_to_ship_max || 0)])
      ))
      setValidation(null)
      toast('Necessidades calculadas com sucesso')
    } catch (error) {
      toast(error.message || 'Erro ao calcular necessidades', 'error')
      setRequirements([])
      setRequirementsSummary(null)
    } finally {
      setLoadingRequirements(false)
    }
  }

  function toggleOrder(orderId) {
    setSelectedOrderIds(current =>
      current.includes(orderId)
        ? current.filter(value => value !== orderId)
        : [...current, orderId]
    )
  }

  function addPallet() {
    const next = nextNumber(pallets.map(pallet => pallet.number))
    setPallets(current => [...current, { id: `plt-${Date.now()}-${next}`, number: next, boxes: [] }])
  }

  function addLooseBox() {
    const next = nextNumber(allBoxes.map(box => box.number))
    setLooseBoxes(current => [...current, { id: `box-${Date.now()}-${next}`, number: next, allocations: [] }])
  }

  function addBoxToPallet(palletId) {
    const next = nextNumber(allBoxes.map(box => box.number))
    setPallets(current => current.map(pallet => (
      pallet.id !== palletId
        ? pallet
        : {
            ...pallet,
            boxes: [...pallet.boxes, { id: `box-${Date.now()}-${next}`, number: next, allocations: [] }],
          }
    )))
  }

  function removePallet(palletId) {
    const pallet = pallets.find(row => row.id === palletId)
    if (!pallet) return
    if (pallet.boxes.length > 0) {
      toast('A palete so pode ser removida quando nao tiver caixas', 'error')
      return
    }
    setPallets(current => current.filter(row => row.id !== palletId))
  }

  function removeBox(boxId) {
    const box = allBoxes.find(row => row.id === boxId)
    if (!box) return
    if (box.allocations.length > 0) {
      toast('A caixa so pode ser removida quando estiver vazia', 'error')
      return
    }
    setPallets(current => current.map(pallet => ({
      ...pallet,
      boxes: pallet.boxes.filter(row => row.id !== boxId),
    })))
    setLooseBoxes(current => current.filter(row => row.id !== boxId))
  }

  function addAllocation(line) {
    const editor = allocEditor[line.item_id] || {}
    const boxId = editor.boxId
    const qty = Number(editor.qty || 0)
    const shipQty = Number(shipQtyByItem[line.item_id] || 0)
    const assigned = totalAssignedForItem(pallets, looseBoxes, line.item_id)
    const remaining = shipQty - assigned

    if (!boxId) {
      toast('Seleciona a caixa de destino', 'error')
      return
    }
    if (qty <= 0) {
      toast('Indica uma quantidade valida para a caixa', 'error')
      return
    }
    if (qty > remaining) {
      toast('A quantidade excede o restante por alocar', 'error')
      return
    }

    const allocation = {
      id: `alloc-${Date.now()}`,
      item_id: line.item_id,
      item_desc: line.item_desc,
      group_desc: line.group_desc,
      qty,
    }
    const { nextPallets, nextLooseBoxes } = applyToBoxes(
      pallets,
      looseBoxes,
      boxId,
      box => ({ ...box, allocations: [...box.allocations, allocation] })
    )
    setPallets(nextPallets)
    setLooseBoxes(nextLooseBoxes)
    setAllocEditor(current => ({
      ...current,
      [line.item_id]: { ...current[line.item_id], qty: '' },
    }))
  }

  function removeAllocation(boxId, allocationId) {
    const { nextPallets, nextLooseBoxes } = applyToBoxes(
      pallets,
      looseBoxes,
      boxId,
      box => ({ ...box, allocations: box.allocations.filter(row => row.id !== allocationId) })
    )
    setPallets(nextPallets)
    setLooseBoxes(nextLooseBoxes)
  }

  function buildSnapshot() {
    return {
      selectedPartner,
      partnerSearch,
      docType,
      documents,
      documentSearch,
      selectedOrderIds,
      whOrig,
      whDest,
      locOrig,
      locDest,
      origLocations,
      destLocations,
      requirements,
      requirementsSummary,
      shipQtyByItem,
      pallets,
      looseBoxes,
      draftName,
      savedAt: stamp(),
    }
  }

  function saveDraft() {
    const name = draftName.trim()
    if (!name) {
      toast('Indica uma descricao para o standby', 'error')
      return
    }
    const nextDrafts = [
      {
        id: `draft-${Date.now()}`,
        name,
        updated_at: stamp(),
        snapshot: buildSnapshot(),
      },
      ...drafts,
    ]
    setDrafts(nextDrafts)
    saveDrafts(nextDrafts)
    toast('Separacao colocada em standby')
  }

  function restoreDraft(draft) {
    const snapshot = draft.snapshot || {}
    setSelectedPartner(snapshot.selectedPartner || null)
    setPartnerSearch(snapshot.partnerSearch || '')
    setDocType(snapshot.docType || '')
    setDocuments(snapshot.documents || [])
    setDocumentSearch(snapshot.documentSearch || '')
    setSelectedOrderIds(snapshot.selectedOrderIds || [])
    setWhOrig(snapshot.whOrig || '')
    setWhDest(snapshot.whDest || '')
    setLocOrig(snapshot.locOrig || '')
    setLocDest(snapshot.locDest || '')
    setOrigLocations(snapshot.origLocations || [])
    setDestLocations(snapshot.destLocations || [])
    setRequirements(snapshot.requirements || [])
    setRequirementsSummary(snapshot.requirementsSummary || null)
    setShipQtyByItem(snapshot.shipQtyByItem || {})
    setPallets(snapshot.pallets || [])
    setLooseBoxes(snapshot.looseBoxes || [])
    setDraftName(snapshot.draftName || draft.name || '')
    setValidation(null)
    toast(`Standby retomado: ${draft.name}`)
  }

  function deleteDraft(draftId) {
    const nextDrafts = drafts.filter(draft => draft.id !== draftId)
    setDrafts(nextDrafts)
    saveDrafts(nextDrafts)
  }

  function validatePlan() {
    const issues = []
    const lines = requirements.flatMap(group => group.lines)

    if (!selectedPartner) issues.push('Falta selecionar o fornecedor/subcontratado.')
    if (!whOrig || !whDest) issues.push('Faltam armazens de origem e destino.')
    if (!selectedOrderIds.length) issues.push('Nao existem ordens selecionadas.')
    if (!allBoxes.length) issues.push('Nao existem paletes/caixas criadas para a separacao.')

    for (const line of lines) {
      const shipQty = Number(shipQtyByItem[line.item_id] || 0)
      const assigned = totalAssignedForItem(pallets, looseBoxes, line.item_id)

      if (shipQty > Number(line.qty_to_ship_max || 0)) {
        issues.push(`O artigo ${line.item_id} excede a quantidade maxima a enviar.`)
      }
      if (shipQty !== assigned) {
        issues.push(`O artigo ${line.item_id} tem ${shipQty} para enviar e ${assigned} alocado em volumes.`)
      }
    }

    if (issues.length) {
      setValidation({ ok: false, title: 'Plano com inconsistencias', detail: issues.join(' ') })
      return
    }

    setValidation({
      ok: true,
      title: 'Plano validado',
      detail: `Separacao pronta para pre-guia. ${selectedOrderIds.length} ordens, ${allBoxes.length} caixas, ${totalAllocatedVolumes(pallets, looseBoxes)} atribuicoes.`,
    })
  }

  const lines = requirements.flatMap(group => group.lines)
  const totalShipQty = lines.reduce((sum, line) => sum + Number(shipQtyByItem[line.item_id] || 0), 0)
  const filteredDocuments = documents.filter(document => {
    const term = documentSearch.trim().toLowerCase()
    if (!term) return true
    return [
      String(document.doc_type || ''),
      String(document.order_id || ''),
      String(document.partner_id || ''),
      String(document.partner_name || ''),
      String(document.order_date || ''),
      String(document.due_date || ''),
      String(document.obs || ''),
    ].some(value => value.toLowerCase().includes(term))
  })

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Abastecimento</h1>
        <p className={styles.pageDesc}>
          Saida de materia-prima para fabricas com selecao de ordens de producao,
          calculo de necessidades e distribuicao por paletes/caixas.
        </p>
      </div>

      <StatsBar>
        <Stat label="Ordens" value={selectedOrderIds.length} color="var(--accent)" />
        <Stat label="Componentes" value={lines.length} color="var(--green)" />
        <Stat label="Qtd. a enviar" value={totalShipQty} color="var(--yellow)" />
        <Stat label="Volumes" value={allBoxes.length} color="var(--red)" />
      </StatsBar>

      {validation && (
        <ResultBanner ok={validation.ok} title={validation.title} detail={validation.detail} />
      )}

      <Card>
        <CardTitle>Standby</CardTitle>
        <div className={styles.toolbar}>
          <input
            className={styles.input}
            value={draftName}
            onChange={e => setDraftName(e.target.value)}
            placeholder="Descricao da separacao pendente"
          />
          <Btn onClick={saveDraft}>Guardar standby</Btn>
          <Btn variant="outline" onClick={validatePlan}>Validar plano</Btn>
        </div>
        <div className={styles.draftList}>
          {drafts.length === 0 && <div className={styles.empty}>Sem separacoes pendentes em standby.</div>}
          {drafts.map(draft => (
            <div key={draft.id} className={styles.draftItem}>
              <div>
                <div className={styles.draftTitle}>{draft.name}</div>
                <div className={styles.draftMeta}>Atualizado em {draft.updated_at}</div>
              </div>
              <div className={styles.actions}>
                <Btn variant="outline" onClick={() => restoreDraft(draft)}>Retomar</Btn>
                <Btn variant="danger" onClick={() => deleteDraft(draft.id)}>Eliminar</Btn>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <CardTitle>Contexto</CardTitle>
        {loadingBase ? (
          <div className={styles.empty}>A carregar configuracao base...</div>
        ) : (
          <div className={styles.grid}>
            <div className={styles.field}>
              <label>Tipo ordem fabrico</label>
              <select className={styles.select} value={docType} onChange={e => setDocType(e.target.value)}>
                {docTypes.map(type => (
                  <option key={type.doc_type} value={type.doc_type}>
                    {type.doc_type} - {type.title}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.field}>
              <label>Fornecedor / Subcontratado</label>
              <input
                className={styles.input}
                value={partnerSearch}
                onChange={e => setPartnerSearch(e.target.value)}
                disabled={!docType}
                placeholder="Pesquisar por codigo ou nome"
              />
              <div className={styles.pickList}>
                {partners.map(partner => (
                  <button
                    key={partner.partner_id}
                    type="button"
                    className={`${styles.pickItem} ${selectedPartner?.partner_id === partner.partner_id ? styles.pickItemActive : ''}`}
                    onClick={() => setSelectedPartner(partner)}
                  >
                    <strong>{partner.partner_id}</strong> {partner.partner_name}
                  </button>
                ))}
              </div>
            </div>

            <div className={styles.field}>
              <label>Armazem origem</label>
              <select className={styles.select} value={whOrig} onChange={e => setWhOrig(e.target.value)}>
                {warehouses.map(warehouse => (
                  <option key={warehouse.wh_id} value={warehouse.wh_id}>
                    {warehouse.wh_id} - {warehouse.wh_desc}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.field}>
              <label>Localizacao origem</label>
              <select className={styles.select} value={locOrig} onChange={e => setLocOrig(e.target.value)}>
                {origLocations.map(location => (
                  <option key={location.location_id} value={location.location_id}>
                    {location.location_id} - {location.location_desc}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.field}>
              <label>Armazem destino</label>
              <select className={styles.select} value={whDest} onChange={e => setWhDest(e.target.value)}>
                {warehouses.map(warehouse => (
                  <option key={warehouse.wh_id} value={warehouse.wh_id}>
                    {warehouse.wh_id} - {warehouse.wh_desc}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.field}>
              <label>Localizacao destino</label>
              <select className={styles.select} value={locDest} onChange={e => setLocDest(e.target.value)}>
                {destLocations.map(location => (
                  <option key={location.location_id} value={location.location_id}>
                    {location.location_id} - {location.location_desc}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
      </Card>

      <Card>
        <CardTitle>Ordens de producao</CardTitle>
        <div className={styles.toolbar}>
          <Btn onClick={fetchDocuments} loading={loadingDocuments}>Carregar ordens</Btn>
          <Btn variant="outline" onClick={fetchRequirements} loading={loadingRequirements}>
            Calcular necessidades
          </Btn>
        </div>
        <div className={styles.summaryBar}>
          <span>Tipo: {docType || '-'}</span>
          <span>Fornecedor: {selectedPartner?.partner_name || selectedPartner?.partner_id || '-'}</span>
          <span>Selecionadas: {selectedOrderIds.length}</span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Ordem</th>
                <th>Modelo</th>
                <th>Artigo</th>
                <th>Fornecedor</th>
                <th>Data</th>
                <th>Linhas</th>
                <th>Obs.</th>
              </tr>
            </thead>
            <tbody>
              {selectedOrderIds.length === 0 && (
                <tr>
                  <td colSpan="7" className={styles.emptyCell}>Sem ordens selecionadas.</td>
                </tr>
              )}
              {documents.filter(document => selectedOrderIds.includes(document.order_id)).map(document => (
                <tr key={document.order_id}>
                  <td>{document.order_id}</td>
                  <td>{document.doc_type}</td>
                  <td>{document.item_id || '-'}</td>
                  <td>{document.partner_name || document.partner_id}</td>
                  <td>{document.order_date || '-'}</td>
                  <td>{document.total_lines}</td>
                  <td>{document.obs || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <CardTitle>Paletes e caixas</CardTitle>
        <div className={styles.toolbar}>
          <Btn onClick={addPallet}>Nova palete</Btn>
          <Btn variant="outline" onClick={addLooseBox}>Nova caixa solta</Btn>
        </div>
        <div className={styles.volumeGrid}>
          {pallets.map(pallet => (
            <div key={pallet.id} className={styles.volumeCard}>
              <div className={styles.volumeHeader}>
                <div>
                  <div className={styles.volumeTitle}>PLT {pallet.number}</div>
                  <div className={styles.volumeMeta}>{pallet.boxes.length} caixas associadas</div>
                </div>
                <div className={styles.actions}>
                  <Btn variant="outline" onClick={() => addBoxToPallet(pallet.id)}>Nova caixa</Btn>
                  <Btn variant="danger" onClick={() => removePallet(pallet.id)}>Eliminar</Btn>
                </div>
              </div>
              <div className={styles.subVolumes}>
                {pallet.boxes.length === 0 && <div className={styles.empty}>Sem caixas nesta palete.</div>}
                {pallet.boxes.map(box => (
                  <div key={box.id} className={styles.subVolume}>
                    <div className={styles.subVolumeTop}>
                      <strong>CX {box.number}</strong>
                      <button type="button" className={styles.linkDanger} onClick={() => removeBox(box.id)}>
                        remover
                      </button>
                    </div>
                    {box.allocations.map(allocation => (
                      <div key={allocation.id} className={styles.allocItem}>
                        <span>{allocation.item_id} - {allocation.qty}</span>
                        <button
                          type="button"
                          className={styles.linkDanger}
                          onClick={() => removeAllocation(box.id, allocation.id)}
                        >
                          retirar
                        </button>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          ))}

          {looseBoxes.map(box => (
            <div key={box.id} className={styles.volumeCard}>
              <div className={styles.volumeHeader}>
                <div>
                  <div className={styles.volumeTitle}>CX {box.number}</div>
                  <div className={styles.volumeMeta}>Caixa sem palete</div>
                </div>
                <Btn variant="danger" onClick={() => removeBox(box.id)}>Eliminar</Btn>
              </div>
              {box.allocations.length === 0 && <div className={styles.empty}>Sem atribuicoes.</div>}
              {box.allocations.map(allocation => (
                <div key={allocation.id} className={styles.allocItem}>
                  <span>{allocation.item_id} - {allocation.qty}</span>
                  <button
                    type="button"
                    className={styles.linkDanger}
                    onClick={() => removeAllocation(box.id, allocation.id)}
                  >
                    retirar
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <CardTitle>Necessidades por grupo de artigo</CardTitle>
        {requirementsSummary && (
          <div className={styles.summaryBar}>
            <span>Ordens: {requirementsSummary.orders_count}</span>
            <span>Componentes: {requirementsSummary.items_count}</span>
            <span>Necessario: {requirementsSummary.qty_needed}</span>
            <span>Em falta: {requirementsSummary.qty_missing}</span>
            <span>Max. envio: {requirementsSummary.qty_to_ship_max}</span>
          </div>
        )}

        {requirements.length === 0 && <div className={styles.empty}>Sem necessidades calculadas.</div>}
        {requirements.map(group => (
          <div key={`${group.group_code}-${group.group_desc}`} className={styles.groupBlock}>
            <div className={styles.groupHeader}>
              <div>
                <h3>{group.group_desc}</h3>
                <p>{group.lines.length} componentes</p>
              </div>
              <div className={styles.groupTotals}>
                <span>Falta {group.qty_missing}</span>
                <span>Stock {group.qty_stock}</span>
              </div>
            </div>

            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Componente</th>
                    <th>Ordens</th>
                    <th>Necess.</th>
                    <th>Abastecido</th>
                    <th>Falta</th>
                    <th>Stock</th>
                    <th>A enviar</th>
                    <th>Caixa</th>
                    <th>Qtd.</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {group.lines.map(line => {
                    const assigned = totalAssignedForItem(pallets, looseBoxes, line.item_id)
                    const editor = allocEditor[line.item_id] || {}
                    return (
                      <tr key={line.item_id}>
                        <td>
                          <div className={styles.cellTitle}>{line.item_id}</div>
                          <div className={styles.cellSub}>{line.item_desc}</div>
                        </td>
                        <td>{line.orders.join(', ')}</td>
                        <td>{line.qty_needed}</td>
                        <td>{line.qty_supplied}</td>
                        <td>{line.qty_missing}</td>
                        <td>{line.qty_stock}</td>
                        <td>
                          <input
                            className={styles.inlineInput}
                            type="number"
                            min="0"
                            max={line.qty_to_ship_max}
                            value={shipQtyByItem[line.item_id] || ''}
                            onChange={e => setShipQtyByItem(current => ({
                              ...current,
                              [line.item_id]: e.target.value,
                            }))}
                          />
                          <div className={styles.cellSub}>Alocado: {assigned}</div>
                        </td>
                        <td>
                          <select
                            className={styles.inlineSelect}
                            value={editor.boxId || ''}
                            onChange={e => setAllocEditor(current => ({
                              ...current,
                              [line.item_id]: { ...current[line.item_id], boxId: e.target.value },
                            }))}
                          >
                            <option value="">Selecionar</option>
                            {allBoxes.map(box => (
                              <option key={box.id} value={box.id}>{box.label}</option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <input
                            className={styles.inlineInput}
                            type="number"
                            min="0"
                            value={editor.qty || ''}
                            onChange={e => setAllocEditor(current => ({
                              ...current,
                              [line.item_id]: { ...current[line.item_id], qty: e.target.value },
                            }))}
                          />
                        </td>
                        <td>
                          <Btn variant="outline" onClick={() => addAllocation(line)}>Atribuir</Btn>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </Card>

      {documentsModalOpen && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <div className={styles.modalHeader}>
              <div>
                <h2 className={styles.modalTitle}>Lista de documentos em aberto</h2>
                <p className={styles.modalDesc}>
                  Seleciona as ordens do tipo {docType} para o parceiro {selectedPartner?.partner_name || selectedPartner?.partner_id}
                  e filtra por modelo, numero, fornecedor ou outra informacao.
                </p>
              </div>
              <button type="button" className={styles.modalClose} onClick={() => setDocumentsModalOpen(false)}>×</button>
            </div>

            <div className={styles.toolbar}>
              <input
                className={styles.input}
                value={documentSearch}
                onChange={e => setDocumentSearch(e.target.value)}
                placeholder="Filtrar por modelo, numero, fornecedor, data ou observacoes"
              />
              <Btn variant="outline" onClick={() => setPendingOrderIds(filteredDocuments.map(document => document.order_id))}>
                Selecionar visiveis
              </Btn>
              <Btn variant="outline" onClick={() => setPendingOrderIds([])}>
                Limpar
              </Btn>
            </div>

            <div className={styles.modalTableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th />
                    <th>Modelo</th>
                    <th>Numero</th>
                    <th>Artigo</th>
                    <th>Fornecedor</th>
                    <th>Data</th>
                    <th>Prevista</th>
                    <th>Linhas</th>
                    <th>Obs.</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDocuments.length === 0 && (
                    <tr>
                      <td colSpan="9" className={styles.emptyCell}>Sem documentos para os filtros aplicados.</td>
                    </tr>
                  )}
                  {filteredDocuments.map(document => (
                    <tr key={document.order_id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={pendingOrderIds.includes(document.order_id)}
                          onChange={() => togglePendingOrder(document.order_id)}
                        />
                      </td>
                      <td>{document.doc_type}</td>
                      <td>{document.order_id}</td>
                      <td>{document.item_id || '-'}</td>
                      <td>{document.partner_name || document.partner_id}</td>
                      <td>{document.order_date || '-'}</td>
                      <td>{document.due_date || '-'}</td>
                      <td>{document.total_lines}</td>
                      <td>{document.obs || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className={styles.modalFooter}>
              <span className={styles.modalMeta}>{pendingOrderIds.length} ordens selecionadas</span>
              <div className={styles.actions}>
                <Btn variant="outline" onClick={() => setDocumentsModalOpen(false)}>Fechar</Btn>
                <Btn onClick={applySelectedOrders}>Aplicar selecao</Btn>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
