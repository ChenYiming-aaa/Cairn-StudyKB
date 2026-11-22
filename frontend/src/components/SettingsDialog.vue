<script setup>
/**
 * 设置窗口（M6 T6.5）：模态，宽 880 / 高 620，左侧 4 个 tab。
 *
 * 这个文件只负责「壳」：开合、tab 记忆。tab 的内容在 `components/settings/*`；
 * 「下载」是 M8 T8.4 补上的（组件按需安装）。
 *
 * 模态的三条无障碍底线**不再自己实现**，全部交给原生 `<dialog>` + showModal()：
 * 焦点圈定、Esc/返回手势、背景 inert、关闭时焦点还给打开它的按钮，浏览器都包了。
 * 自己要做的只剩两件：给窗口一个可访问名（aria-labelledby），以及关闭时把防抖中的改动推一次。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { useSettings } from '../composables/useSettings'
import { useUi } from '../composables/useUi'
import AboutTab from './settings/AboutTab.vue'
import AppearanceTab from './settings/AppearanceTab.vue'
import DownloadsTab from './settings/DownloadsTab.vue'
import ModelTab from './settings/ModelTab.vue'

// 2026-11-22：四个 tab 原来各带一行 11px 副标题（「服务、Key、每个任务用谁」之类）。
// 页签名本身已经说清去哪儿，副标题只是把同一件事再讲一遍 —— 删掉，竖排导航只剩四个词。
const TABS = [
  { id: 'model', label: '模型' },
  { id: 'appearance', label: '外观' },
  { id: 'downloads', label: '下载' },
  // 「检查更新」只在这个页签里，叫「关于」没人会想到更新在这（M12 审计 §2 第 26 条）
  { id: 'about', label: '关于与更新' },
]

const { settingsOpen, settingsTab, closeSettings, setSettingsTab } = useUi()
const { flushNow } = useSettings()

const dlg = ref(null)

const current = computed(() => TABS.find((t) => t.id === settingsTab.value) || TABS[0])

/** 三种关法（Esc、点遮罩、点「关闭」）最后都走到这里：先落盘再同步状态 */
function onClose() {
  flushNow()
  if (settingsOpen.value) closeSettings()
}

watch(settingsOpen, (open) => {
  const node = dlg.value
  if (!node) return
  if (open && !node.open) node.showModal()
  // 已经关掉时 close() 是空转，不会重入 onClose
  else if (!open && node.open) node.close()
})

onBeforeUnmount(() => {
  if (dlg.value?.open) dlg.value.close()
})
</script>

<template>
  <Teleport to="body">
    <!-- closedby="any"：点遮罩也能关（Esc 与返回手势本来就是模态的默认行为） -->
    <dialog
      ref="dlg"
      class="settings"
      closedby="any"
      aria-labelledby="settings-title"
      @close="onClose"
    >
      <aside class="side">
        <h2 id="settings-title" class="title">设置</h2>
        <nav class="tabs" role="tablist" aria-label="设置分类">
          <button
            v-for="tab in TABS"
            :key="tab.id"
            type="button"
            class="tab-btn"
            role="tab"
            :class="{ on: tab.id === current.id }"
            :aria-selected="tab.id === current.id"
            @click="setSettingsTab(tab.id)"
          >
            <span class="tab-label">{{ tab.label }}</span>
          </button>
        </nav>
        <p class="side-foot">改动即时保存</p>
      </aside>

      <section class="body">
        <header class="body-head">
          <h3 class="body-title">{{ current.label }}</h3>
          <!-- autofocus：打开时光标落在这里，读屏先念标题再让人自己往内容区走 -->
          <button class="btn btn-sm btn-ghost" type="button" autofocus @click="dlg.close()">
            关闭
          </button>
        </header>

        <div class="body-scroll" role="tabpanel" :aria-label="current.label">
          <ModelTab v-if="current.id === 'model'" />
          <AppearanceTab v-else-if="current.id === 'appearance'" />
          <DownloadsTab v-else-if="current.id === 'downloads'" />
          <AboutTab v-else-if="current.id === 'about'" />
        </div>

        <footer class="body-foot">
          <span>内容只存在本机；只会发给你配置的模型接口。</span>
        </footer>
      </section>
    </dialog>
  </Teleport>
</template>

<style scoped>
/* display 只在打开时给：无条件写会把 dialog 的「关着」状态（display: none）盖掉 */
.settings[open] {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
}

.settings {
  width: min(880px, 100vw - 2 * var(--space-6));
  height: min(620px, 100vh - 2 * var(--space-6));
  margin: auto;
  overflow: hidden;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-0);
  box-shadow: var(--shadow-md);
}

.side {
  display: flex;
  flex-direction: column;
  padding: var(--space-4) var(--space-3);
  border-right: 1px solid var(--c-border);
  background: var(--c-bg-1);
}

.title {
  margin: 0 var(--space-2) var(--space-3);
  font-size: var(--fs-lg);
  font-weight: 600;
}

.tabs {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tab-btn {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
}

.tab-btn:hover {
  background: var(--c-bg-2);
}

.tab-btn.on {
  background: var(--c-primary-soft);
}

.tab-label {
  font-size: var(--fs-sm);
  color: var(--c-text-1);
}

.tab-btn.on .tab-label {
  color: var(--c-primary-ink);
  font-weight: 600;
}

.side-foot {
  margin: auto 0 0;
  padding: 0 var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.body-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--c-border);
}

.body-title {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}

.body-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
}

.body-foot {
  padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--c-border);
  background: var(--c-bg-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
