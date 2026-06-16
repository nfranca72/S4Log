// Em desenvolvimento usa o proxy do vite (/api → localhost:8000)
// Em produção usa o URL directo do backend
const BASE = import.meta.env.VITE_API_URL ?? '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    const text = await res.text()
    let err
    try {
      err = JSON.parse(text)
    } catch {
      err = { detail: text || `Erro HTTP ${res.status}` }
    }
    throw new Error(err.detail || 'Erro no servidor')
  }
  return res.json()
}

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
