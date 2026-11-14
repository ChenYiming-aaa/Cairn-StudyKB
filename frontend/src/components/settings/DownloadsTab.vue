<script setup>
/**
 * 「下载」tab（M8 T8.4）：可选组件的安装 / 取消 / 重试 / 卸载。
 * 条目不写死：后端 `components.IDS` 加一个，这里就多一张卡（T9.4 加「本地识别」时没改结构）。
 *
 * 三条设计决定：
 *
 * 1. **一个轮询拿全部卡**，不给每个组件各开一个 `progress` 轮询。
 *    `GET /api/components` 一次就带全部状态（含 `install` 明细），只在"有组件在装"
 *    时才 1 秒一次，装完立刻停 —— 设置窗口开着不动不该有后台流量。
 * 2. **状态以服务端为准**，本地只记"刚刚点了什么"用来禁用按钮。下载进度是后端的
 *    内存态，前端自己插值算出来的进度条会和真实进度对不上（还会在失败后继续爬到 100）。
 * 3. **失败一定说人话 + 给重试**。`COMPONENT_HASH_MISMATCH` 这种码用户看不懂，
 *    走 `friendlyMessage` 翻成"校验不通过，已删除，请重试"。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import { useToast } from '../../composables/useToast'
import { fileSize } from '../../utils/format'

const toast = useToast()

const items = ref([])
const loading = ref(true)
const loadError = ref('')
/** 每张卡自己的忙碌态（安装/卸载按钮的防连点），不参与状态判断 */
const busy = ref({})
const mirror = ref('')
/** 静态演示版（VITE_DEMO）没有后端，装了也写不进磁盘：只展示，不许假装能装 */
const isDemo = ref(false)
const mirrorSaved = ref('')
const savingMirror = ref(false)

let timer = null
let stopped = false

const anyRunning = computed(() => items.value.some((i) => i.state === 'downloading'))

/** 状态徽标：文案要说清"现在到底能不能用"，不是复述枚举 */
function badge(item) {
  if (item.state === 'downloading') {
    const pct = item.install?.pct ?? 0
    return { tone: 'run', text: `安装中 ${pct}%` }
  }
  if (item.state === 'installed') return { tone: 'ok', text: '已安装' }
  if (item.state === 'broken') return { tone: 'bad', text: '装好了但起不来' }
  if (item.install?.status === 'failed') return { tone: 'bad', text: '上次没装成' }
  if (item.install?.status === 'cancelled') return { tone: '', text: '已取消' }
  // mode=local：源码运行、本机装了库，所以功能其实是可用的 —— 不能写"未安装"骗人
  return { tone: '', text: item.mode === 'local' ? '用本机已安装的版本' : '未安装' }
}

function canInstall(item) {
  return item.state !== 'downloading' && !busy.value[item.id]
}

async function load() {
  try {
    const data = await api.components()
    items.value = data.items || []
    isDemo.value = Boolean(data.demo)
    mirror.value = data.mirror || ''
    mirrorSaved.value = mirror.value
    loadError.value = ''
  } catch (err) {
    loadError.value = friendlyMessage(err)
  } finally {
    loading.value = false
    schedule()
  }
}

/** 只有"有东西在装"时才继续轮询；否则停（窗口开着不动不该有流量） */
function schedule() {
  if (stopped || timer) return
  if (!anyRunning.value) return
  timer = setTimeout(async () => {
    timer = null
    await load()
  }, 1000)
}

async function install(item) {
  busy.value = { ...busy.value, [item.id]: true }
  try {
    await api.installComponent(item.id)
    toast.info(`开始下载${item.name}，${fileSize(item.size, 0)}。可以关掉设置窗口，装完会通知`)
    await load()
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    busy.value = { ...busy.value, [item.id]: false }
  }
}

async function cancel(item) {
  busy.value = { ...busy.value, [item.id]: true }
  try {
    await api.cancelComponent(item.id)
    toast.info('已取消，下载了一半的文件已删除')
    await load()
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    busy.value = { ...busy.value, [item.id]: false }
    schedule()
  }
}

async function uninstall(item) {
  busy.value = { ...busy.value, [item.id]: true }
  try {
    const res = await api.uninstallComponent(item.id)
    toast.ok(`已卸载${item.name}，释放 ${fileSize(res?.freed || item.bytes, 0)}`)
    await load()
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    busy.value = { ...busy.value, [item.id]: false }
  }
}

async function saveMirror() {
  savingMirror.value = true
  try {
    await api.patchSettings({ components: { mirror: mirror.value.trim() } })
    mirrorSaved.value = mirror.value.trim()
    toast.ok(mirrorSaved.value ? '镜像已保存，下次安装走它' : '已改回直连 GitHub')
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    savingMirror.value = false
  }
}

onMounted(load)

onBeforeUnmount(() => {
  stopped = true
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="dl">
    <p class="intro">
      这些组件用到才装：装了对应功能才完整，不装不影响别的地方。读 PDF 和图片要先装「本地识别」。
    </p>

    <p v-if="isDemo" class="demo-note">
      演示版不能安装组件。装桌面版后可以安装和卸载。
    </p>

    <p v-if="loading" class="state">正在读组件状态…</p>
    <p v-else-if="loadError" class="state bad">{{ loadError }}</p>

    <ul v-else class="cards">
      <li v-for="item in items" :key="item.id" class="card" :class="item.state">
        <div class="card-head">
          <h4 class="name">
            {{ item.name }}
            <span class="badge" :class="badge(item).tone">{{ badge(item).text }}</span>
          </h4>
          <span class="size">{{ item.state === 'installed' ? fileSize(item.bytes, 0) : fileSize(item.size, 0) }}</span>
        </div>

        <p class="why">{{ item.why }}</p>

        <!-- 下载中：进度 + 取消。百分比与字节都来自后端，前端不自己插值 -->
        <div v-if="item.state === 'downloading'" class="progress">
          <div class="bar"><i :style="{ width: (item.install?.pct || 0) + '%' }" /></div>
          <div class="progress-meta">
            <span class="phase">{{ item.install?.phase === 'verify' ? '校验文件…' : item.install?.phase === 'extract' ? '解压中…' : `${fileSize(item.install?.got, 0)} / ${fileSize(item.install?.total, 0)}` }}</span>
            <button
              class="btn btn-sm btn-ghost"
              type="button"
              :disabled="busy[item.id]"
              @click="cancel(item)"
            >
              取消
            </button>
          </div>
        </div>

        <!-- 失败：原因 + 重试。原因来自后端错误码，不拼英文内部细节 -->
        <p v-else-if="item.install?.status === 'failed'" class="err">
          {{ item.install.error_msg || '上次没装成' }}
        </p>

        <div class="actions">
          <template v-if="item.state === 'installed'">
            <span class="hint">
              {{ item.mode === 'component' ? '运行中' : item.mode === 'local' ? '用本机已安装的版本' : '已安装' }}
              <template v-if="item.version"> · v{{ item.version }}</template>
            </span>
            <button
              class="btn btn-sm btn-ghost"
              type="button"
              :disabled="busy[item.id]"
              @click="uninstall(item)"
            >
              卸载
            </button>
          </template>

          <template v-else-if="item.state === 'downloading'">
            <span class="hint">关掉窗口也会继续下载</span>
          </template>

          <template v-else>
            <span class="hint">{{ isDemo ? '演示版不能装' : item.state === 'broken' ? '重装一次通常能修' : `下载 ${fileSize(item.size, 0)}` }}</span>
            <button
              class="btn btn-sm btn-primary"
              type="button"
              :disabled="isDemo || !canInstall(item)"
              @click="install(item)"
            >
              {{ busy[item.id] ? '启动中…' : item.install?.status === 'failed' ? '重试' : item.install?.status === 'cancelled' ? '继续' : '安装' }}
            </button>
          </template>
        </div>
      </li>
    </ul>

    <!-- 下载源：默认直连 GitHub；镜像要用户自己填（不偷偷改流量）。
         标题做成行内标签而不是上方的 h5 —— 设置窗口固定 620px 高，多一行就会被
         底栏压掉半句（2026-11-10 实测截图确认过）。 -->
    <section class="mirror">
      <div class="mirror-row">
        <label class="mirror-label" for="mirror-input">下载源</label>
        <input
          id="mirror-input"
          v-model="mirror"
          class="mirror-input"
          type="text"
          inputmode="url"
          placeholder="留空 = 直连 GitHub"
        />
        <button
          class="btn btn-sm"
          type="button"
          :disabled="savingMirror || mirror.trim() === mirrorSaved"
          @click="saveMirror"
        >
          {{ savingMirror ? '保存中…' : '保存' }}
        </button>
      </div>
      <p class="mirror-note">
        留空 = 直连 GitHub；填第三方镜像（如 <code>ghfast.top</code>）能加速，但它能看到你的下载请求。
      </p>
    </section>
  </div>
</template>

<style scoped>
.dl {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.intro {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: var(--lh-body);
}

.demo-note {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-warning-border);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
}

.state {
  margin: 0;
  padding: var(--space-4);
  border: 1px dashed var(--c-border);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.state.bad {
  color: var(--c-warning-ink);
  border-color: var(--c-warning-border);
  background: var(--c-warning-soft);
}

.cards {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
}

.card {
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
}

.card.installed {
  border-color: var(--c-primary-border);
}

.card-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}

.badge {
  padding: 1px var(--space-2);
  border-radius: 999px;
  background: var(--c-bg-2);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
  font-weight: 400;
}

.badge.ok {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.badge.run {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.badge.bad {
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
}

.size {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.why {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: var(--lh-body);
}

.progress {
  margin-top: var(--space-2);
}

.bar {
  height: 4px;
  border-radius: 2px;
  background: var(--c-bg-2);
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--c-primary);
  transition: width 0.3s ease;
}

.progress-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.phase {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.progress-meta .btn {
  margin-left: auto;
}

.err {
  margin: var(--space-2) 0 0;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.actions .btn {
  margin-left: auto;
}

.mirror {
  margin-top: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--c-border);
}

.mirror-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.mirror-label {
  flex: none;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-2);
}

.mirror-input {
  flex: 1;
  min-width: 0;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
  color: var(--c-text-1);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.mirror-input:focus {
  border-color: var(--c-primary-border);
  outline: none;
}

.mirror-note {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: var(--lh-body);
}

.mirror-note code {
  padding: 0 3px;
  border-radius: 3px;
  background: var(--c-bg-2);
  font-family: var(--font-mono);
  word-break: break-all;
}
</style>
