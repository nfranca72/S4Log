// Em desenvolvimento usa o proxy do vite (/api → localhost:8000)
// Em produção usa o URL directo do backend
const BASE = import.meta.env.VITE_API_URL ?? '/api'
const STATION_STORAGE_KEY = 's4log_station_identifier'

function stationIdentifierHeader() {
  const value = typeof window !== 'undefined'
    ? (window.localStorage.getItem(STATION_STORAGE_KEY) || '').trim()
    : ''
  return value ? { 'X-Station-Identifier': value } : {}
}

function withStationHeaders(options = {}) {
  return {
    ...options,
    headers: {
      ...stationIdentifierHeader(),
      ...(options.headers || {}),
    },
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, withStationHeaders(options))
  if (!res.ok) {
    const text = await res.text()
    let err
    try {
      err = JSON.parse(text)
    } catch {
      err = { detail: text || `Erro HTTP ${res.status}` }
    }
    const detail = err?.detail
    if (Array.isArray(detail)) {
      const msg = detail
        .map(item => {
          const pathLabel = Array.isArray(item?.loc) ? item.loc.join('.') : ''
          const textLabel = String(item?.msg || item || '').trim()
          return pathLabel ? `${pathLabel}: ${textLabel}` : textLabel
        })
        .filter(Boolean)
        .join(' | ')
      throw new Error(msg || `Erro HTTP ${res.status}`)
    }
    if (detail && typeof detail === 'object') {
      throw new Error(
        detail.message
        || detail.error
        || JSON.stringify(detail)
      )
    }
    throw new Error(detail || 'Erro no servidor')
  }
  return res.json()
}

export { STATION_STORAGE_KEY }

/* ── Clientes ── */
export const clientsApi = {
  search: (q = '') => request(`/clients/?search=${encodeURIComponent(q)}`),
}

/* ── Packing ── */
export const packingApi = {
  preview: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/packing/preview', { method: 'POST', body: fd })
  },

  createItems: (rows) =>
    request('/items/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rows),
    }),

  import: (clientId, csvRows, header) =>
    request('/packing/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, csv_rows: csvRows, header }),
    }),

  list: () => request('/packing/'),

  get: (orderId) => request(`/packing/${orderId}`),

  getBoxes: (orderId) => request(`/packing/${orderId}/boxes`),

  getBox: (orderId, volNum) => request(`/packing/${orderId}/boxes/${volNum}`),

  confirmBox: (orderId, volNum, qtyRead) =>
    request(`/packing/${orderId}/boxes/${volNum}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qty_read: qtyRead }),
    }),
}

/* ── Import Artigos Benfica ── */
export const benficaItemsApi = {
  preview: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/benfica-items/preview', { method: 'POST', body: fd })
  },

  import: (rows) =>
    request('/benfica-items/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rows),
    }),
}

/* ── Encomendas ESCP ── */
export const ordersApi = {
  preview: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/orders/preview', { method: 'POST', body: fd })
  },

  createItems: (rows) =>
    request('/orders/items/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rows),
    }),

  listEscp: () => request('/orders/escp'),

  createEscp: (clientId, rows, obs) =>
    request('/orders/escp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, rows, obs }),
    }),

  mergePreview: (orderId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request(`/orders/escp/${orderId}/merge-preview`, { method: 'POST', body: fd })
  },

  mergeApply: (orderId, rowsToAdd, rowsToUpdate) =>
    request(`/orders/escp/${orderId}/merge-apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order_id: orderId, rows_to_add: rowsToAdd, rows_to_update: rowsToUpdate }),
    }),
}

/* ── Movimentos Simplificados ── */
export const simplMovApi = {
  types:        ()                       => request('/simplified-movements/types'),
  partners:     (partnerType, search='') => request(`/simplified-movements/partners?partner_type=${partnerType}&search=${encodeURIComponent(search)}`),
  documents:    (docType, partnerId='')  => request(`/simplified-movements/documents?doc_type=${docType}&partner_id=${encodeURIComponent(partnerId)}`),
  docLines:     (orderId, docType, withComponents=false) =>
    request(`/simplified-movements/documents/${orderId}/lines?doc_type=${docType}&with_components=${withComponents ? 1 : 0}`),
  itemDetails:  (itemId)                 => request(`/simplified-movements/items/${itemId}`),
  itemDimStock: (itemId, whId)           => request(`/simplified-movements/items/${itemId}/dim-stock${whId ? `?wh_id=${whId}` : ''}`),
  itemLots:     (itemId, whId)           => request(`/simplified-movements/items/${itemId}/lots${whId ? `?wh_id=${whId}` : ''}`),
  itemVolumes:  (itemId, whId)           => request(`/simplified-movements/items/${itemId}/volumes${whId ? `?wh_id=${whId}` : ''}`),
  searchItems:  (search)                 => request(`/simplified-movements/items?search=${encodeURIComponent(search)}`),
  warehouses:   (docType='')             => request(`/simplified-movements/warehouses?doc_type=${docType}`),
  locations:    (whId)                   => request(`/simplified-movements/warehouses/${whId}/locations`),
  execute:      (payload)                => request('/simplified-movements/execute', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  }),
}

/* ── Abastecimento ── */
export const supplyApi = {
  partners: (docType, search = '') =>
    request(`/abastecimento/partners?doc_type=${encodeURIComponent(docType)}&search=${encodeURIComponent(search)}`),
  warehouses: () => request('/abastecimento/warehouses'),
  locations: (whId) => request(`/abastecimento/warehouses/${whId}/locations`),
  documentTypes: () => request('/abastecimento/document-types'),
  documents: (docType, partnerId = '', search = '') =>
    request(
      `/abastecimento/documents?doc_type=${encodeURIComponent(docType)}&partner_id=${encodeURIComponent(partnerId)}&search=${encodeURIComponent(search)}`
    ),
  requirements: (payload) =>
    request('/abastecimento/requirements', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  volumePrintConfigs: (docType = 'CX') =>
    request(`/abastecimento/volume-print-configs?doc_type=${encodeURIComponent(docType)}`),
}

/* ── Documento de Separacao ── */
export const separationApi = {
  config: () => request('/separation-documents/config'),
  warehouses: () => request('/separation-documents/warehouses'),
  documentTypes: () => request('/separation-documents/document-types'),
  executionDocumentTypes: () => request('/separation-documents/execution/document-types'),
  executionOrders: (docTypes = []) => {
    const query = new URLSearchParams()
    docTypes.forEach(docType => {
      if (docType) query.append('doc_type', docType)
    })
    return request(`/separation-documents/execution/orders${query.toString() ? `?${query.toString()}` : ''}`)
  },
  executionParameters: () => request('/separation-documents/execution/parameters'),
  executionDetail: (orderPickingId) =>
    request(`/separation-documents/execution/${encodeURIComponent(orderPickingId)}/detail`),
  executionCreateVolume: (orderPickingId, volTypeId) =>
    request(`/separation-documents/execution/${encodeURIComponent(orderPickingId)}/volumes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vol_type_id: volTypeId }),
    }),
  executionCheckBox: (orderPickingId, rowNumber, volNum) =>
    request(`/separation-documents/execution/${encodeURIComponent(orderPickingId)}/lines/${encodeURIComponent(rowNumber)}/check-box`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vol_num: volNum }),
    }),
  executionPickLine: (orderPickingId, rowNumber, payload) =>
    request(`/separation-documents/execution/${encodeURIComponent(orderPickingId)}/lines/${encodeURIComponent(rowNumber)}/pick`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  executionUnpickLine: (orderPickingId, rowNumber) =>
    request(`/separation-documents/execution/${encodeURIComponent(orderPickingId)}/lines/${encodeURIComponent(rowNumber)}/unpick`, {
      method: 'POST',
    }),
  partners: (docType, search = '') =>
    request(`/separation-documents/partners?doc_type=${encodeURIComponent(docType)}&search=${encodeURIComponent(search)}`),
  documents: (docType, partnerId = '', search = '') =>
    request(
      `/separation-documents/documents?doc_type=${encodeURIComponent(docType)}&partner_id=${encodeURIComponent(partnerId)}&search=${encodeURIComponent(search)}`
    ),
  lines: (payload) =>
    request('/separation-documents/lines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  searchItems: (whId, search) =>
    request(`/separation-documents/items?wh_id=${encodeURIComponent(whId)}&search=${encodeURIComponent(search)}`),
  itemBoxes: (itemId, whIds, sizeId = '') => {
    const ids = Array.isArray(whIds) ? whIds : [whIds]
    const query = new URLSearchParams()
    ids.filter(id => id !== '' && id != null).forEach(id => query.append('wh_id', id))
    query.append('size_id', sizeId)
    return request(`/separation-documents/items/${encodeURIComponent(itemId)}/boxes?${query.toString()}`)
  },
  create: (payload) =>
    request('/separation-documents/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  consultation: (params = {}) => {
    const query = new URLSearchParams()
    if (params.fromDate) query.set('from_date', params.fromDate)
    if (params.toDate) query.set('to_date', params.toDate)
    if (params.onlyOpen) query.set('only_open', 'true')
    return request(`/separation-documents/orders-picking${query.toString() ? `?${query.toString()}` : ''}`)
  },
  consultationMetadata: () => request('/separation-documents/orders-picking/metadata'),
  consultationDetail: (orderPickingId) => request(`/separation-documents/orders-picking/${encodeURIComponent(orderPickingId)}`),
  consultationUpdate: (orderPickingId, payload) =>
    request(`/separation-documents/orders-picking/${encodeURIComponent(orderPickingId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  consultationDelete: (orderPickingId, payload) =>
    request(`/separation-documents/orders-picking/${encodeURIComponent(orderPickingId)}/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    }),
}

/* ── Contagem RFID ── */
export const countingApi = {
  start: (tunnelId) =>
    request(`/counting/tunnels/${tunnelId}/start`, {
      method: 'POST',
    }),
  reset: (tunnelId) =>
    request(`/counting/tunnels/${tunnelId}/reset`, {
      method: 'POST',
    }),
  stop: (tunnelId) =>
    request(`/counting/tunnels/${tunnelId}/stop`, {
      method: 'POST',
    }),
  snapshot: (tunnelId) => request(`/counting/tunnels/${tunnelId}/snapshot`),
}

/* ── SAP B1 Integrator ── */
export const sapB1Api = {
  status: () => request('/sap-b1/status'),
  config: () => request('/sap-b1/config'),
  updateConfig: (payload) =>
    request('/sap-b1/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  toggle: (integration, enabled) =>
    request(`/sap-b1/toggle/${integration}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  runNow: (integration) =>
    request(`/sap-b1/run-now/${integration}`, {
      method: 'POST',
    }),
  health: () => request('/sap-b1/health'),
  errors: (integration = '') =>
    request(`/sap-b1/errors${integration ? `?integration=${encodeURIComponent(integration)}` : ''}`),
  resolveError: (id, payload) =>
    request(`/sap-b1/errors/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  retryError: (id) =>
    request(`/sap-b1/errors/${id}/retry`, {
      method: 'POST',
    }),
  logs: (integration = '') =>
    request(`/sap-b1/logs?limit=50${integration ? `&integration=${encodeURIComponent(integration)}` : ''}`),
}
