// cert 模块公共常量：门户卡片 icon/theme 映射（后端只存名字符串，视觉由前端实现）、
// 模块路由映射与公共文案。不写死色值，theme 键映射到 CSS 变量组合（亮暗自动适配）。
import { BookOpen, Columns2, CreditCard, FileText, IdCard, Printer } from 'lucide-vue-next'

export const CERT_ICON_MAP = {
  'credit-card': CreditCard,
  'book-open': BookOpen,
  'id-card': IdCard,
  printer: Printer,
  'columns-2': Columns2,
}

export function certIcon(name) {
  return CERT_ICON_MAP[name] || FileText
}

// 语义配色组合（UI_ADAPTATION.md 第 3 节），禁止出现 hex/rgba。
export const CERT_THEME_CLASS = {
  blue: 'bg-primary/10 text-primary border-primary/25',
  teal: 'bg-accent text-accent-foreground border-primary/25',
  green: 'bg-success/10 text-success border-success/30',
  amber: 'bg-warning/15 text-warning border-warning/30',
}

export function certThemeClass(theme) {
  return CERT_THEME_CLASS[theme] || CERT_THEME_CLASS.blue
}

// 模板 code → 模块页路由（门户卡片跳转）。新增模块：这里加一行 + routes.js 注册。
// doc2up（两页合一打印）也走模板驱动：卡片显隐由后台「证件照管理」启停控制。
export const CERT_MODULE_ROUTES = {
  id_card: '/cert/id-card',
  hukou: '/cert/hukou',
  doc2up: '/cert/doc-2up',
}

export function certModuleRoute(code) {
  return CERT_MODULE_ROUTES[code] || null
}

export const CERT_CONSENT_TEXT = '本人确认打印自有证件，仅用于合法用途'

export const CERT_PRIVACY_NOTE = '证件照片仅用于生成打印件，不会被保存；生成件到期后自动删除，也可随时手动删除。'
