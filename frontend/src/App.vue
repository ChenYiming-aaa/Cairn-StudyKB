<script setup>
import { onMounted, ref } from 'vue'

import { api, friendlyMessage } from './api/client'
import PasteDialog from './components/PasteDialog.vue'
import { useToast } from './composables/useToast'
import { useUi } from './composables/useUi'

const { toasts, error: toastError, ok: toastOk, dismiss } = useToast()
const { pasteOpen, openPaste, closePaste, requestRefresh } = useUi()

const backend = ref('checking')

onMounted(async () => {
  try {
    await api.health()
    backend.value = 'ok'
  } catch (err) {
    backend.value = 'down'
    toastError(friendlyMessage(err))
  }
})

function onCreated(result) {
  closePaste()
  requestRefresh()
  toastOk(result.duplicated ? `内容已存在，已定位到「${result.title}」` : `已加入「${result.title}」`)
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        Cairn
        <small>个人知识库</small>
      </div>
      <span class="conn" :class="backend" :title="backend === 'ok' ? '后端已连接' : '后端未连接'">
        <i class="dot" />
        {{ backend === 'ok' ? '已连接' : backend === 'down' ? '未连接' : '连接中' }}
      </span>
      <div class="topbar-spacer" />
      <button class="btn btn-primary" type="button" @click="openPaste()">＋ 粘贴文本</button>
    </header>

    <router-view />

    <PasteDialog :open="pasteOpen" @close="closePaste()" @created="onCreated" />

    <div class="toast-stack">
      <div
        v-for="item in toasts"
        :key="item.id"
        class="toast"
        :class="item.kind"
        @click="dismiss(item.id)"
      >
        {{ item.message }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.conn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.conn.ok {
  color: var(--c-success);
}

.conn.down {
  color: var(--c-danger);
}

.toast-stack {
  position: fixed;
  right: var(--space-6);
  bottom: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  z-index: 60;
}

.toast {
  max-width: 380px;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  border: 1px solid var(--c-border);
  border-left-width: 3px;
  box-shadow: var(--shadow-md);
  font-size: var(--fs-sm);
  cursor: pointer;
  animation: slide-in 0.18s ease;
}

.toast.ok {
  border-left-color: var(--c-success);
}

.toast.error {
  border-left-color: var(--c-danger);
}

.toast.info {
  border-left-color: var(--c-primary);
}

@keyframes slide-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
