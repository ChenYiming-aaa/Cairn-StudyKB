/** 全局 Toast：模块级单例，任何组件调 useToast() 都指向同一份列表。 */
import { ref } from 'vue'

const toasts = ref([])
let seq = 0

function dismiss(id) {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

function push(message, kind = 'info', ttl = 4000) {
  const id = ++seq
  toasts.value = [...toasts.value, { id, message, kind }]
  setTimeout(() => dismiss(id), ttl)
}

export function useToast() {
  return {
    toasts,
    dismiss,
    info: (message) => push(message, 'info'),
    ok: (message) => push(message, 'ok', 3000),
    error: (message) => push(message, 'error', 7000),
  }
}
