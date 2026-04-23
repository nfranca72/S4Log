// Em desenvolvimento usa o proxy do vite (/api → localhost:8000)
// Em produção usa o URL directo do backend
const BASE = import.meta.env.VITE_API_URL ?? '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Erro no servidor' }))
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
