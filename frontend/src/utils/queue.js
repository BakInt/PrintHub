// 排队信息的中文文案助手，供支付/状态页、首页下单提示复用。

export function formatQueueMessage(queue, status) {
  if (!queue || !queue.in_queue) return ''
  const ahead = Number(queue.ahead || 0)
  const total = Number(queue.total || 0)
  if (ahead > 0) {
    return `您的打印正在排队，前面还有 ${ahead} 单，当前共有 ${total} 单正在打印或排队中。`
  }
  if (status === 'printing') {
    return `轮到您了，您的打印任务正在进行中${total > 1 ? `，后面还有 ${total - 1} 单在排队` : ''}。`
  }
  return `前面暂无排队，您的打印任务即将开始${total > 1 ? `，当前共有 ${total} 单在队列中` : ''}。`
}

// 下单成功后的即时提示：结合排队情况给出一句话说明。
export function formatOrderCreatedQueueMessage(queue) {
  if (!queue) return ''
  const ahead = Number(queue.ahead || 0)
  if (!queue.in_queue) return ''
  if (ahead > 0) {
    return `下单成功，前面还有 ${ahead} 单在打印，请耐心等待。`
  }
  return '下单成功，前面暂无排队，您的打印任务将很快开始。'
}
