// 两页合一（doc2up）模块接口：上传复用主程序 /api/upload（含转换/安全检测），
// 合成走本模块 /api/doc2up/create；下单复用 CertOrderPanel 的 /api/price + /api/payment/create。
import { request } from '@/api/client'

export function uploadDocument(file) {
  const form = new FormData()
  form.append('file', file, file.name)
  return request('/api/upload', { method: 'POST', body: form })
}

export function createDoc2Up(fileId) {
  return request('/api/doc2up/create', { method: 'POST', body: { file_id: fileId } })
}
