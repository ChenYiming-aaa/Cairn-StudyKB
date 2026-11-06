<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage } from './api/client'
import IngestPanel from './components/IngestPanel.vue'
import { useToast } from './composables/useToast'
import { useUi } from './composables/useUi'

const router = useRouter()
const { toasts, error: toastError, ok: toastOk, info: toastInfo, dismiss } = useToast()
const { pasteOpen, openPaste, closePaste, requestRefresh, openItem } = useUi()

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

/** 链接已在库里：不派任务，刷新后把用户带到已有条目 */
function onExisting(itemId) {
  closePaste()
  requestRefresh()
  toastInfo(`该链接已在知识库中（条目 #${itemId}）`)
}

/** 网页抓取 / 视频转录落库完成：刷新列表，但**不关面板**——让用户看到「已入库」再自己关 */
function onIngested() {
  requestRefresh()
  toastOk('采集完成，已加入知识库')
}

/** 「去看看」：关面板 → 切到知识库 → 选中刚入库的条目 */
function onOpen(itemId) {
  closePaste()
  requestRefresh()
  if (!itemId) return
  router.push('/')
  openItem(itemId)
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        Cairn
        <small>个人知识库</small>
      </div>
      <nav class="nav">
        <router-link to="/" class="nav-item" exact-active-class="on">知识库</router-link>
        <router-link to="/tasks" class="nav-item" active-class="on">任务</router-link>
      </nav>
      <span class="conn" :class="backend" :title="backend === 'ok' ? '后端已连接' : '后端未连接'">
        <i class="dot" />
        {{ backend === 'ok' ? '已连接' : backend === 'down' ? '未连接' : '连接中' }}
      </span>
      <div class="topbar-spacer" />
      <button class="btn btn-primary" type="button" @click="openPaste()">＋ 采集内容</button>
    </header>

    <router-view />

    <IngestPanel
      :open="pasteOpen"
      @close="closePaste()"
      @created="onCreated"
      @existing="onExisting"
      @ingested="onIngested"
      @open="onOpen"
    />

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
.nav {
  display: flex;
  gap: var(--space-1);
  margin-left: var(--space-4);
}

.nav-item {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  text-decoration: none;
}

.nav-item:hover {
  background: var(--c-bg-2);
}

.nav-item.on {
  background: var(--c-primary-soft);
  color: var(--c-primary);
}

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
