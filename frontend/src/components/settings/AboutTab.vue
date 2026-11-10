<script setup>
/**
 * 「关于」tab（M6 T6.8 + T8.5 接线）。
 *
 * 版本号取 `GET /api/version`（不是前端 package.json）：关于页要回答的是
 * 「**这个二进制**是哪一版」，前端版本只说明「界面代码是哪一版」，两者打包后可能不一致。
 * 拿不到就显示 `—`，绝不写死一个数字充数。
 *
 * 「检查更新」的实现在主进程（`desktop/updater.js`），这里只管状态机与文案；
 * 状态挂在 `useUpdater` 的模块级单例上 —— 切 tab / 关窗口不会把 170 MB 的下载弄丢。
 * 浏览器里跑（vite dev、静态演示页）没有 `window.cairn`，按钮禁用并写明原因。
 */
import { computed, onMounted, ref } from 'vue'

import { api } from '../../api/client'
import { useSettings } from '../../composables/useSettings'
import { useUpdater } from '../../composables/useUpdater'

const info = ref(null)
const loading = ref(true)
const { settings, load: loadSettings } = useSettings()

const {
  state, result, progress, error, verify, current, latest, notes,
  fmtBytes, check, download, cancel, install, openManual,
} = useUpdater()

// 四个链接：仓库 / 演示 / 更新日志 / 反馈
const LINKS = [
  { label: 'GitHub 仓库', href: 'https://github.com/ChenYiming-aaa/Cairn-StudyKB' },
  { label: '在线演示', href: 'https://chenyiming-aaa.github.io/Cairn-StudyKB/' },
  { label: '更新日志', href: 'https://github.com/ChenYiming-aaa/Cairn-StudyKB/blob/main/CHANGELOG.md' },
  { label: '反馈问题', href: 'https://github.com/ChenYiming-aaa/Cairn-StudyKB/issues/new' },
]

const version = computed(() => info.value?.version || '—')
// 演示站没有打包元数据，写「源码运行」会让人以为这是本地跑起来的实例
const isDemo = import.meta.env.VITE_DEMO === '1'
const commit = computed(() => {
  const value = (info.value?.commit || '').trim()
  return value ? value.slice(0, 7) : ''
})
// 构建时间只在打包时注入；源码直跑没有，就不要编一个出来
const builtAt = computed(() => {
  const raw = (info.value?.built_at || '').trim()
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
})

onMounted(async () => {
  // 配置来源要能看见（S-3）：光有开关没人检查，等于没修
  loadSettings()
  try {
    info.value = await api.version()
  } catch {
    // 后端没起来时关于页也要能看：版本显示 —，链接照常
    info.value = null
  } finally {
    loading.value = false
  }
})

/** 配置来源审计：`ok=false` 只表示"配置被两处拼起来过"，开发机才会出现 */
const cfg = computed(() => settings.value?.config || null)
const cfgState = computed(() => {
  const c = cfg.value
  if (!c) return { tone: '', text: '读取中…' }
  if (!c.ok) return { tone: 'bad', text: `从 ${c.legacy_file} 补过值` }
  return { tone: 'ok', text: c.strict ? '只读数据目录（严格模式）' : '只读数据目录' }
})

function checkUpdate() {
  // 没打包（源码跑 electron .）时主进程会直接回 DEV，这里不必自己判断一次
  check()
}

/** 主按钮随状态走：同一时刻只有一个"下一步"，不摆一排按钮让人猜 */
const primary = computed(() => {
  switch (state.value) {
    case 'checking':
      return { label: '正在检查…', action: checkUpdate, disabled: true }
    case 'available':
      return { label: `下载 ${fmtBytes(result.value?.size)}`, action: download, disabled: false }
    case 'downloading':
      return { label: '取消下载', action: cancel, disabled: false }
    case 'ready':
      return { label: '打开安装程序', action: install, disabled: false }
    case 'latest':
      return { label: '重新检查', action: checkUpdate, disabled: false }
    case 'error':
      // 已经拿到版本信息了（下载阶段出错）→ 重试下载；否则重试检查
      return { label: '重试', action: result.value ? download : checkUpdate, disabled: false }
    case 'unavailable':
      return { label: '检查更新', action: () => {}, disabled: true }
    default:
      return { label: '检查更新', action: checkUpdate, disabled: false }
  }
})

const hint = computed(() => {
  switch (state.value) {
    case 'checking':
      return '正在连 GitHub…'
    case 'latest':
      return '已是最新版本'
    case 'available':
      return `${latest.value} 可用（当前 ${current.value}）`
    case 'downloading':
      return `${progress.value.pct || 0}%（${fmtBytes(progress.value.got)} / ${fmtBytes(progress.value.total)}）`
    case 'ready':
      return '已下载完成，可以安装了'
    case 'error':
      return ''
    case 'unavailable':
      return '桌面版才能检查更新；浏览器里（含在线演示）没有更新器'
    default:
      return '看看 GitHub 上有没有新版本'
  }
})
</script>

<template>
  <div class="about">
    <header class="hdr">
      <img class="mark" src="/logo.svg" alt="" width="44" height="44" />
      <div class="hdr-text">
        <h4 class="name">
          Cairn
          <span class="ver">v{{ loading ? '…' : version }}</span>
        </h4>
        <p class="tagline">
          把看过的网页、视频、文章收进本地知识库，让模型整理成可检索、可复习的知识资产。
        </p>
      </div>
    </header>

    <section class="block">
      <h5 class="block-title">构建信息</h5>
      <dl class="facts">
        <div class="fact">
          <dt>提交</dt>
          <dd>{{ commit || (isDemo ? '在线演示，不含构建信息' : '源码运行，没有提交号') }}</dd>
        </div>
        <div class="fact">
          <dt>构建时间</dt>
          <dd>{{ builtAt || (isDemo ? '在线演示，不含构建信息' : '源码运行，没有构建时间') }}</dd>
        </div>
      </dl>
      <div class="update">
        <div class="update-row">
          <button
            class="btn btn-sm"
            type="button"
            :disabled="primary.disabled"
            @click="primary.action"
          >
            {{ primary.label }}
          </button>
          <span class="update-note" :class="{ ok: state === 'latest', warn: state === 'error' }">
            {{ hint }}
          </span>
        </div>

        <div
          v-if="state === 'downloading'"
          class="bar"
          role="progressbar"
          :aria-valuenow="progress.pct || 0"
          aria-valuemin="0"
          aria-valuemax="100"
        >
          <span class="bar-fill" :style="{ width: (progress.pct || 0) + '%' }"></span>
        </div>

        <!-- 更新说明只给前 20 行，多的自己滚动：设置窗口只有 620px 高 -->
        <p v-if="state === 'available' && notes" class="notes">{{ notes }}</p>

        <p v-if="state === 'error'" class="err">
          <span>{{ error?.message }}</span>
          <a class="manual" href="#" @click.prevent="openManual">手动下载安装包</a>
        </p>

        <p v-if="state === 'ready'" class="update-note">
          已下载 {{ fmtBytes(progress.got) }}，
          {{ verify === 'sha256' ? '校验值一致' : '这个版本没附 .sha256，只比对了大小' }}。
        </p>
        <p v-if="state === 'ready'" class="update-note warn">
          应用没有代码签名，安装时 Windows 可能提示「已保护你的电脑」，选「更多信息 → 仍要运行」。
          安装前会先关掉当前窗口，不会动 `%APPDATA%\Cairn` 里的内容。
        </p>
      </div>
    </section>

    <section class="block">
      <h5 class="block-title">配置来源</h5>
      <dl class="facts">
        <div class="fact">
          <dt>配置文件</dt>
          <dd>{{ cfg?.env_file || '—' }}</dd>
        </div>
        <div class="fact">
          <dt>有没有从老地方拿过配置</dt>
          <dd>
            <span class="src" :class="cfgState.tone">{{ cfgState.text }}</span>
          </dd>
        </div>
      </dl>
      <p v-if="cfg?.hint" class="update-note">{{ cfg.hint }}</p>
    </section>

    <section class="block">
      <h5 class="block-title">链接</h5>
      <div class="links">
        <a
          v-for="link in LINKS"
          :key="link.href"
          class="link"
          :href="link.href"
          target="_blank"
          rel="noreferrer"
        >
          {{ link.label }}
          <span class="arrow" aria-hidden="true">↗</span>
        </a>
      </div>
    </section>

    <p class="privacy">
      数据目录 <code>%APPDATA%\Cairn</code>：备份就是复制这个文件夹，卸载不会删内容。
    </p>
  </div>
</template>

<style scoped>
.about {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.hdr {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
}

.mark {
  flex: none;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-sm);
}

.hdr-text {
  min-width: 0;
}

.name {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
}

.ver {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.tagline {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: var(--lh-body);
}

.block-title {
  margin: 0 0 var(--space-2);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-2);
}

.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
  margin: 0;
}

.fact {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
}

.fact dt {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.fact dd {
  margin: 2px 0 0;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--c-text-1);
  word-break: break-all;
}

.update {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.update-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.bar {
  height: 4px;
  border-radius: 999px;
  background: var(--c-bg-2);
  overflow: hidden;
}

.bar-fill {
  display: block;
  height: 100%;
  background: var(--c-primary);
  transition: width 0.2s linear;
}

/* 更新说明可能很长：限高 + 自己滚，别把窗口撑出滚动条 */
.notes {
  max-height: 76px;
  margin: 0;
  overflow-y: auto;
  padding: var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
  line-height: 1.5;
  white-space: pre-wrap;
}

.err {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px var(--space-2);
  margin: 0;
  color: var(--c-danger-ink);
  font-size: var(--fs-xs);
  line-height: 1.5;
}

.manual {
  color: var(--c-primary-ink);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.src {
  font-family: var(--font-body, inherit);
  font-size: var(--fs-xs);
  color: var(--c-text-1);
}

.src.ok {
  color: var(--c-success-ink);
}

.src.bad {
  color: var(--c-warning-ink);
}

.update-note {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: 1.45;
}

.update-note.ok {
  color: var(--c-success-ink);
}

.update-note.warn {
  color: var(--c-warning-ink);
}

.links {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
}

.link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  color: var(--c-text-1);
  font-size: var(--fs-sm);
  text-decoration: none;
  transition: border-color 0.15s, background 0.15s;
}

.link:hover {
  border-color: var(--c-primary-border);
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.arrow {
  color: var(--c-text-3);
}

.privacy {
  margin: 0;
  padding-top: var(--space-2);
  border-top: 1px dashed var(--c-border);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: var(--lh-body);
}

.privacy code {
  padding: 0 3px;
  border-radius: 3px;
  background: var(--c-bg-2);
  font-family: var(--font-mono);
}
</style>
