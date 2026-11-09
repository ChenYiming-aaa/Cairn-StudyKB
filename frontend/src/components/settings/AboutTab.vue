<script setup>
/**
 * 「关于」tab（M6 T6.8）。
 *
 * 版本号取 `GET /api/version`（不是前端 package.json）：关于页要回答的是
 * 「**这个二进制**是哪一版」，前端版本只说明「界面代码是哪一版」，两者打包后可能不一致。
 * 拿不到就显示 `—`，绝不写死一个数字充数。
 *
 * 「检查更新」在这一版是占位：真逻辑要桌面壳的 IPC（T8.5），M6 只把入口和形状定下来。
 */
import { computed, onMounted, ref } from 'vue'

import { api } from '../../api/client'
import { useSettings } from '../../composables/useSettings'
import { useToast } from '../../composables/useToast'

const toast = useToast()
const info = ref(null)
const loading = ref(true)
const { settings, load: loadSettings } = useSettings()

// 四个链接：仓库 / 演示 / 更新日志 / 反馈
const LINKS = [
  { label: 'GitHub 仓库', href: 'https://github.com/ChenYiming-aaa/Cairn-StudyKB' },
  { label: '在线演示', href: 'https://chenyiming-aaa.github.io/Cairn-StudyKB/' },
  { label: '更新日志', href: 'https://github.com/ChenYiming-aaa/Cairn-StudyKB/blob/main/CHANGELOG.md' },
  { label: '反馈问题', href: 'https://github.com/ChenYiming-aaa/Cairn-StudyKB/issues/new' },
]

const version = computed(() => info.value?.version || '—')
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
  // TODO(T8.5)：接桌面壳的更新器 —— 检查 → 下载（带进度）→ 打开安装程序 → 退出
  toast.info('这一版还没有更新器：M8 接入后，这里能直接检查并下载新版本')
}
</script>

<template>
  <div class="about">
    <header class="hdr">
      <img class="mark" src="/logo.svg" alt="" width="44" height="44" />
      <div class="hdr-text">
        <h4 class="name">
          Cairn
          <span class="ver">v{{ loading ? '…' : version }}</span>
          <span class="tag">v0.2 开发预览</span>
        </h4>
        <p class="tagline">
          把看过的网页、视频、文章收进本地知识库，让 AI 整理成可检索、可复习的知识资产。
        </p>
      </div>
    </header>

    <section class="block">
      <h5 class="block-title">构建信息</h5>
      <dl class="facts">
        <div class="fact">
          <dt>提交</dt>
          <dd>{{ commit || '源码运行（未注入 commit）' }}</dd>
        </div>
        <div class="fact">
          <dt>构建时间</dt>
          <dd>{{ builtAt || '源码运行（未注入构建时间）' }}</dd>
        </div>
      </dl>
      <div class="update-row">
        <button class="btn btn-sm" type="button" @click="checkUpdate">检查更新</button>
        <span class="update-note">当前版本已是最新的说法要等 M8 接上更新器；现在点了不会下载任何东西。</span>
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

.tag {
  padding: 1px var(--space-2);
  border: 1px solid var(--c-warning-border);
  border-radius: 999px;
  background: var(--c-warning-soft);
  color: var(--c-warning);
  font-size: var(--fs-xs);
  font-weight: 400;
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

.update-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.src {
  font-family: var(--font-body, inherit);
  font-size: var(--fs-xs);
  color: var(--c-text-1);
}

.src.ok {
  color: var(--c-success);
}

.src.bad {
  color: var(--c-warning);
}

.update-note {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: 1.45;
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
