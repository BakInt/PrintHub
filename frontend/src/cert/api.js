// cert 模块接口封装：复用主程序请求器（token 注入 / CSRF / FormData 处理都在 client.js）。
import { request } from '@/api/client'

export function fetchCertTemplates() {
  return request('/api/cert/templates')
}

// files: { 槽位 key: File }；quads: { 槽位 key: [[x,y]×4] 归一化 }；cutGuides: null 用模板默认。
export function generateCertDoc({ templateCode, files, quads, cutGuides }) {
  const form = new FormData()
  form.append('template_code', templateCode)
  if (cutGuides !== null && cutGuides !== undefined) form.append('cut_guides', String(!!cutGuides))
  Object.entries(files || {}).forEach(([key, file]) => {
    if (file) form.append(`slot_${key}`, file, file.name || `${key}.jpg`)
  })
  Object.entries(quads || {}).forEach(([key, quad]) => {
    if (quad) form.append(`quad_${key}`, JSON.stringify(quad))
  })
  return request('/api/cert/generate', { method: 'POST', body: form })
}

export function fetchCertDocs(limit = 10, offset = 0) {
  return request(`/api/cert/docs?limit=${limit}&offset=${offset}`)
}

export function deleteCertDoc(docId) {
  return request(`/api/cert/docs/${docId}`, { method: 'DELETE' })
}

// 下单闭环复用主程序现有接口（模块内不出现任何支付代码）。
export function fetchPrice(payload) {
  return request('/api/price', { method: 'POST', body: payload })
}

export function createPayment(payload) {
  return request('/api/payment/create', { method: 'POST', body: payload })
}

export function fetchPrintOptions() {
  return request('/api/print-options')
}

// —— 管理侧（后台 AdminView「证件照管理」tab，CertAdminPanel 使用） ——

export function fetchAdminCertTemplates() {
  return request('/api/admin/cert-templates')
}

export function updateAdminCertTemplate(code, payload) {
  return request(`/api/admin/cert-templates/${code}`, { method: 'PATCH', body: payload })
}

export function fetchAdminCertSettings() {
  return request('/api/admin/cert-settings')
}

export function updateAdminCertSettings(payload) {
  return request('/api/admin/cert-settings', { method: 'PUT', body: payload })
}
