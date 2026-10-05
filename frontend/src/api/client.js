const API_BASE = import.meta.env.VITE_API_BASE || ''
const CSRF_COOKIE = 'cloud_print_csrf'
const CSRF_SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE'])

export function buildApiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path
  if (!API_BASE) return path
  return `${API_BASE.replace(/\/$/, '')}${path.startsWith('/') ? path : `/${path}`}`
}

function formatErrorMessage(data) {
  const detail = data?.detail ?? data?.error ?? data
  
  let diagnostics = []
  if (data && typeof data === 'object') {
    diagnostics = data.diagnostics || data.detail?.diagnostics || []
  }
  
  let errorText = ''
  
  if (typeof detail === 'string') {
    errorText = normalizeErrorMessage(detail)
  } else if (Array.isArray(detail)) {
    errorText = detail.map((item) => {
      if (typeof item === 'string') return normalizeErrorMessage(item)
      const fieldLabel = translateFieldLocation(item.loc)
      if (typeof item.msg === 'string') return normalizeErrorMessage(`${fieldLabel ? `${fieldLabel}：` : ''}${translateValidationMessage(item.msg)}`)
      return normalizeErrorMessage(JSON.stringify(item))
    }).join('；')
  } else if (detail && typeof detail === 'object') {
    if (typeof detail.error === 'string') errorText = normalizeErrorMessage(detail.error)
    else if (typeof detail.message === 'string') errorText = normalizeErrorMessage(detail.message)
    else if (typeof detail.msg === 'string') errorText = normalizeErrorMessage(detail.msg)
    else errorText = normalizeErrorMessage(JSON.stringify(detail))
  } else {
    errorText = '请求失败'
  }
  
  if (diagnostics.length > 0) {
    const diagnosticHints = diagnostics
      .filter((d) => d.hint && !d.ok)
      .map((d) => d.hint)
      .filter((h, i, self) => self.indexOf(h) === i)
    
    if (diagnosticHints.length > 0) {
      errorText += '\n\n提示：' + diagnosticHints.join('；')
    }
  }
  
  return errorText
}

const FIELD_LABELS = {
  username: '用户名',
  password: '密码',
  new_password: '新密码',
  captcha: '验证码',
  email: '邮箱',
  phone: '手机号',
  real_name: '真实姓名',
  name: '名称',
  amount: '金额',
  balance: '余额',
  payment_method: '支付方式',
  contact_name: '联系人姓名',
  contact_phone: '联系人手机号',
  copies: '份数',
  page_count: '页数',
  file_ids: '文件',
  new_name: '新名称',
  template_id: '模板',
  uri: '打印机地址',
  driver: '驱动',
  code: '兑换码'
}

function translateFieldLocation(loc) {
  if (!Array.isArray(loc)) return ''
  // 去掉 body/query/path 等来源前缀，取最后一个有意义的字段名
  const parts = loc.filter((item) => !['body', 'query', 'path', 'header', 'cookie'].includes(item))
  const field = parts.length ? parts[parts.length - 1] : ''
  if (!field) return ''
  return FIELD_LABELS[field] || field
}

function translateValidationMessage(message) {
  const text = String(message || '')
  const rules = [
    [/String should have at least (\d+) characters?/i, (m) => `至少需要 ${m[1]} 个字符`],
    [/String should have at most (\d+) characters?/i, (m) => `最多允许 ${m[1]} 个字符`],
    [/String should match pattern .*/i, () => '格式不正确'],
    [/Input should be a valid string/i, () => '请输入有效的文本'],
    [/Input should be a valid integer.*/i, () => '请输入有效的整数'],
    [/Input should be a valid number.*/i, () => '请输入有效的数字'],
    [/Input should be a valid boolean.*/i, () => '请输入有效的布尔值'],
    [/Input should be greater than or equal to ([\d.]+)/i, (m) => `不能小于 ${m[1]}`],
    [/Input should be greater than ([\d.]+)/i, (m) => `必须大于 ${m[1]}`],
    [/Input should be less than or equal to ([\d.]+)/i, (m) => `不能大于 ${m[1]}`],
    [/Input should be less than ([\d.]+)/i, (m) => `必须小于 ${m[1]}`],
    [/(Field required|Input should be provided)/i, () => '此项为必填'],
    [/value is not a valid email address.*/i, () => '邮箱格式不正确'],
    [/ensure this value has at least (\d+) items?/i, (m) => `至少需要 ${m[1]} 项`],
    [/List should have at least (\d+) items?.*/i, (m) => `至少需要 ${m[1]} 项`],
    // 自定义校验器（如兑换码「请输入兑换码」、兑换面额「必须大于 0」）的文案会带
    // Pydantic 的 "Value error, " 前缀，这里剥掉前缀、只展示中文提示。
    [/^Value error,\s*(.+)$/is, (m) => m[1]]
  ]
  for (const [pattern, build] of rules) {
    const match = text.match(pattern)
    if (match) return build(match)
  }
  return text
}

function normalizeErrorMessage(message) {
  const text = String(message || '')
  
  if (/(\b4096\b|unauthorized|not-authorized|forbidden|CUPS 拒绝|没有足够的 CUPS|没有足够的打印机管理权限)/i.test(text)) {
    return 'CUPS 拒绝当前操作：后端没有足够的打印机管理权限。请优先使用系统中已有的打印队列，或在宿主机 CUPS/系统打印机设置中授权后端创建和管理队列。'
  }
  
  if (/1280|server-error-internal-error/i.test(text)) {
    const parts = []
    parts.push('CUPS 服务器内部错误')
    if (text.includes('driver') || text.includes('PPD')) {
      parts.push('请检查驱动名称是否正确，或尝试使用 "everywhere" 驱动')
    }
    if (text.includes('uri') || text.includes('URI')) {
      parts.push('请检查打印机 URI 格式是否正确')
    }
    parts.push('建议在软路由 CUPS 管理界面（http://192.168.1.1:631/）中手动测试添加打印机')
    return parts.join('；')
  }
  
  // 后端未捕获异常时 FastAPI 只返回纯文本 "Internal Server Error"，翻译成可读中文的服务器故障提示。
  if (/^(internal server error|服务器内部错误)/i.test(text.trim())) {
    return '服务器内部错误，请稍后重试'
  }
  
  return text
}

export function getToken() {
  return localStorage.getItem('cloud-print-token')
}

export function setToken(token) {
  if (token) localStorage.setItem('cloud-print-token', token)
  else localStorage.removeItem('cloud-print-token')
}

function readCookie(name) {
  return document.cookie
    .split(';')
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))
    ?.slice(name.length + 1) || ''
}

async function ensureCsrfToken() {
  let token = readCookie(CSRF_COOKIE)
  if (token) return decodeURIComponent(token)
  await fetch(buildApiUrl('/api/auth/csrf'), { credentials: 'include' })
  token = readCookie(CSRF_COOKIE)
  return token ? decodeURIComponent(token) : ''
}

export async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  const method = (options.method || 'GET').toUpperCase()
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (!CSRF_SAFE_METHODS.has(method) && !headers['X-CSRF-Token']) {
    const csrfToken = await ensureCsrfToken()
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken
  }
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch(buildApiUrl(path), {
    ...options,
    credentials: 'include',
    headers,
    body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body
  })
  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const error = new Error(formatErrorMessage(data))
    error.data = data
    throw error
  }
  return data
}
