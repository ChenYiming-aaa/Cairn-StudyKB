<script setup>
import { computed, onBeforeUnmount, reactive } from 'vue'

import { api, friendlyMessage } from '../../api/client'

/**
 * 站点登录（从 `IngestPanel` 原样搬出，T9.8 拆分时不动行为）。
 *
 * 只有「需要登录才给内容」的站点用得上：B 站字幕、知乎受限页。
 * 点登录由后端弹一个独立浏览器窗口（不是用户日常那个），登录态存在后端自己的
 * profile 里，导出成 cookies.txt 给 yt-dlp 和网页抓取共用。
 *
 * `hint` 由父组件按任务错误码给（`FETCH_LOGIN_REQUIRED` / `FETCH_BLOCKED`）——
 * 把「为什么要登录」说在登录框里，省得用户去别处找原因。
 */
const props = defineProps({
  hint: { type: String, default: '' },
})

const auth = reactive({
  open: false,
  sites: {},
  busy: false,
  message: '',
  browserAvailable: true,
  login: { status: 'idle', site: '' },
})

const loggedInLabels = computed(() =>
  Object.values(auth.sites).filter((s) => s.logged_in).map((s) => s.label)
)

const summary = computed(() =>
  loggedInLabels.value.length ? `已登录 ${loggedInLabels.value.join('、')}` : '均未登录'
)

let timer = null

/** 拉一次状态，返回 login.status 供轮询判断是否继续。 */
async function refresh() {
  try {
    const data = await api.authStatus()
    auth.sites = data.sites || {}
    auth.browserAvailable = data.browser_available !== false
    const login = data.login || { status: 'idle', site: '' }
    auth.login = login
    if (login.message) auth.message = login.message
    return login.status
  } catch {
    return 'idle'          // 状态拿不到不该打断采集，静默即可
  }
}

function poll() {
  if (timer) clearTimeout(timer)
  const tick = async () => {
    const status = await refresh()
    auth.busy = status === 'running'
    if (status === 'running') timer = setTimeout(tick, 1200)
  }
  timer = setTimeout(tick, 600)
}

/** 展开时才查：登录态会过期，一分钟前查的不代表现在 */
function toggle() {
  auth.open = !auth.open
  if (auth.open) refresh()
}

async function startLogin(site) {
  auth.message = ''
  try {
    const res = await api.authLogin(site)
    auth.login = res
    auth.busy = res.status === 'running'
    if (res.message) auth.message = res.message
    if (auth.busy) poll()
  } catch (err) {
    auth.message = friendlyMessage(err)
  }
}

function loginLabel(key, site) {
  if (auth.busy && auth.login?.site === key) return '等待登录…'
  return site.logged_in ? '重新登录' : '登录'
}

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <section class="auth">
    <button class="auth-head" type="button" :aria-label="auth.open ? '收起站点登录' : '展开站点登录'" @click="toggle">
      <span class="auth-dot" :class="{ on: loggedInLabels.length > 0 }" />
      <span class="auth-title">站点登录</span>
      <span class="auth-sum">{{ summary }}</span>
      <span class="auth-more">{{ auth.open ? '收起' : '展开' }}</span>
    </button>

    <div v-if="auth.open" class="auth-body">
      <p class="auth-tip">
        B 站字幕、知乎受限页这类要登录的站点，在这里登一次就行。点「登录」会开一个独立窗口，登完自动保存，不影响你日常用的浏览器。
      </p>
      <p v-if="!auth.browserAvailable" class="auth-warn">
        站点登录暂时用不了：还没装浏览器组件。去「设置 → 下载」装上「网页渲染」就能用。
      </p>
      <div v-else class="auth-list">
        <div v-for="(site, key) in auth.sites" :key="key" class="auth-item">
          <span class="auth-name">{{ site.label }}</span>
          <span class="auth-state" :class="{ on: site.logged_in }">
            {{ site.logged_in ? '已登录' : '未登录' }}
          </span>
          <button class="btn btn-sm" type="button" :disabled="auth.busy" @click="startLogin(key)">
            {{ loginLabel(key, site) }}
          </button>
        </div>
      </div>
      <p v-if="props.hint" class="auth-warn">{{ props.hint }}</p>
      <p v-if="auth.message" class="auth-msg">{{ auth.message }}</p>
    </div>
  </section>
</template>

<style scoped>
.auth {
  margin: var(--space-4) 0 0;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.auth-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 0;
  background: var(--c-bg-0);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  cursor: pointer;
  text-align: left;
}

.auth-head:hover {
  background: var(--c-bg-2);
}

.auth-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-border);
}

.auth-dot.on {
  background: var(--c-success);
}

.auth-title {
  color: var(--c-text-1);
}

.auth-sum {
  color: var(--c-text-3);
}

.auth-more {
  margin-left: auto;
  color: var(--c-text-3);
}

.auth-body {
  padding: var(--space-3);
  border-top: 1px solid var(--c-border);
}

.auth-tip {
  margin: 0 0 var(--space-3);
  font-size: var(--fs-xs);
  line-height: 1.65;
  color: var(--c-text-3);
}

.auth-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.auth-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-sm);
}

.auth-name {
  min-width: 48px;
  color: var(--c-text-1);
}

.auth-state {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.auth-state.on {
  color: var(--c-success-ink);
}

.auth-item .btn {
  margin-left: auto;
}

.auth-msg,
.auth-warn {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  line-height: 1.6;
}

.auth-msg {
  color: var(--c-text-2);
}

.auth-warn {
  color: var(--c-warning-ink);
}
</style>
