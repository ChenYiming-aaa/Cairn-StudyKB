// Electron 更新器（T8.5）。
//
// 为什么不用 electron-updater（M8 §4.1）：它要发布时生成 latest.yml，对 `oneClick: false`
// 的辅助式安装器支持有限；而本项目**没有代码签名**，静默覆盖安装出问题无法排查。
// 自己写只需要「GitHub API + 下载 + 起安装器」，行为完全可控，也没有额外依赖。
//
// 三层职责分得很清：
//   updater.js  只做网络与文件（检查 / 下载 / 校验 / 清理 / 起安装器），不碰窗口与 IPC
//   main.js     IPC + 来源校验 + 退出流程（先杀后端再 exit，否则会留孤儿进程）
//   preload.js  只暴露四个方法，不暴露 ipcRenderer 本身
//
// `CAIRN_UPDATE_API_BASE` 只给验收用（与 `CAIRN_COMPONENT_BASE_URL` 同一类）：
// 端到端测「0.1.9 发现 0.2.0」时，0.2.0 的 Release 还没建（要到 T8.7），
// 只能让主进程去问一个形状一致的本地服务。**生产不读它**，默认就是 api.github.com。
'use strict'

const { app, net } = require('electron')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

const { compareVersions, parseVersion } = require('./semver')

const REPO = 'ChenYiming-aaa/Cairn-StudyKB'
const API_BASE = (process.env.CAIRN_UPDATE_API_BASE || 'https://api.github.com').replace(/\/+$/, '')
const RELEASES_PAGE = `https://github.com/${REPO}/releases/latest`
const TIMEOUT_MS = 8000
// GitHub 要求带 User-Agent，否则 403。带上自己的版本号，对方日志里也认得出是谁。
const USER_AGENT = `Cairn/${app.getVersion()} (+https://github.com/${REPO})`

// 下载中的单实例状态：同一时刻只允许一个下载，取消就是 abort 这一个请求。
let current = null          // { req, file, cancelled }
let lastCheck = null        // 最近一次 check() 的响应，下载只认它，不接受渲染进程传 URL

function humanError(code, detail) {
  const map = {
    NETWORK: '连不上 GitHub，请检查网络或代理设置。',
    TIMEOUT: '连 GitHub 超时了，网络慢或被拦时常见。过一会儿再试，或直接下载安装包。',
    HTTP_403: 'GitHub 接口限流了（同一个网络出口共用 IP 时常见），过几分钟再试。',
    CHECKSUM: '下载的文件校验不通过，已删除。可能是网络中间件改过内容，重试或手动下载。',
    DISK: '写临时文件失败，可能是磁盘满了。清一点空间再试。',
    DEV: '开发模式（未打包）不检查更新。打包后的版本才有更新器。',
  }
  return {
    ok: false,
    code,
    message: map[code] || `更新检查失败（${code}）${detail ? '：' + detail : ''}`,
    detail: detail || '',
    manualUrl: RELEASES_PAGE,
  }
}

// ── HTTP（主进程，绕开渲染进程的 CSP 与代理差异）──────────────
function request(url, { timeout = TIMEOUT_MS } = {}) {
  return new Promise((resolve, reject) => {
    let settled = false
    const done = (fn, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      fn(value)
    }
    const req = net.request({ url, method: 'GET', redirect: 'follow' })
    req.setHeader('User-Agent', USER_AGENT)
    req.setHeader('Accept', 'application/vnd.github+json')
    const timer = setTimeout(() => {
      req.abort()
      done(reject, Object.assign(new Error('timeout'), { code: 'TIMEOUT' }))
    }, timeout)
    req.on('response', (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => done(resolve, {
        status: res.statusCode,
        headers: res.headers,
        body: Buffer.concat(chunks).toString('utf8'),
      }))
      res.on('error', (e) => done(reject, e))
    })
    req.on('error', (e) => done(reject, e))
    req.end()
  })
}

/** 把 Electron 的网络错误翻成可判断的码：断网 / DNS / 连接被拒都归 NETWORK */
function classify(err) {
  const code = String((err && err.code) || '')
  if (code === 'TIMEOUT') return 'TIMEOUT'
  if (code === 'ERR_ABORTED' || code === 'ABORT_ERR') return 'CANCELLED'
  return 'NETWORK'
}

// ── 检查 ────────────────────────────────────────────────
async function check() {
  if (!app.isPackaged) return humanError('DEV')
  const url = `${API_BASE}/repos/${REPO}/releases/latest`
  let res
  try {
    res = await request(url)
  } catch (e) {
    return humanError(classify(e), String((e && e.message) || e))
  }
  if (res.status === 404) {
    return { ok: false, code: 'NO_RELEASE', message: 'GitHub 上还没有发布版本。', manualUrl: RELEASES_PAGE }
  }
  if (res.status === 403 || res.status === 429) return humanError('HTTP_403')
  if (res.status !== 200) {
    return humanError('HTTP_' + res.status, `GitHub 返回 ${res.status}`)
  }
  let rel
  try {
    rel = JSON.parse(res.body)
  } catch {
    return humanError('BAD_JSON', 'GitHub 返回的不是 JSON')
  }

  const latest = String(rel.tag_name || rel.name || '').replace(/^v/i, '')
  const currentVersion = app.getVersion()
  if (!parseVersion(latest)) return humanError('BAD_VERSION', String(rel.tag_name || ''))

  const assets = Array.isArray(rel.assets) ? rel.assets : []
  const installer = assets.find((a) => /-setup\.exe$/i.test(String(a.name || '')))
    || assets.find((a) => /\.exe$/i.test(String(a.name || '')))
  const sha = assets.find((a) => /\.sha256$/i.test(String(a.name || '')))

  lastCheck = {
    latest,
    current: currentVersion,
    htmlUrl: rel.html_url || RELEASES_PAGE,
    notes: String(rel.body || '').split(/\r?\n/).slice(0, 20).join('\n').trim(),
    asset: installer
      ? { name: installer.name, size: Number(installer.size) || 0, url: installer.browser_download_url }
      : null,
    sha256Asset: sha ? { name: sha.name, url: sha.browser_download_url } : null,
  }
  lastCheck.hasUpdate = compareVersions(latest, currentVersion) > 0
  return {
    ok: true,
    current: currentVersion,
    latest,
    hasUpdate: lastCheck.hasUpdate,
    notes: lastCheck.notes,
    htmlUrl: lastCheck.htmlUrl,
    size: lastCheck.asset ? lastCheck.asset.size : 0,
    hasInstaller: Boolean(lastCheck.asset),
    hasChecksum: Boolean(sha),
  }
}

// ── 下载 ────────────────────────────────────────────────
function updateDir() {
  return path.join(app.getPath('temp'), 'cairn-update')
}

/** 清掉上次留下的安装包。
 *
 * 启动时调，但**只删 10 分钟之前的**：升级成功那一瞬，新版本可能紧接着被启动，
 * 而 NSIS 还在收尾、占着我们拉起来的那个 setup.exe，立刻删会失败（说不清是谁的问题）。
 * 10 分钟足够让安装器收工，又不至于让 172 MB 在临时目录里躺一整天。
 * 取消 / 失败路径是当场删的，不靠这里兜底。
 */
function cleanup() {
  const dir = updateDir()
  const cutoff = Date.now() - 10 * 60 * 1000
  try {
    for (const name of fs.readdirSync(dir)) {
      const file = path.join(dir, name)
      try {
        if (fs.statSync(file).mtimeMs < cutoff) fs.rmSync(file, { recursive: true, force: true })
      } catch { /* 单个文件失败不影响其它 */ }
    }
    fs.rmdirSync(dir)          // 空了就顺手收掉；非空会抛，忽略
    return true
  } catch {
    return false
  }
}

function cancel() {
  if (!current) return false
  current.cancelled = true
  // 两刀都要下：`abort()` 只掐请求，已经开始回包的响应流还会继续把数据推过来
  // （实测取消后进度仍在涨、文件删不掉，就是只掐了第一刀）
  try { current.req.abort() } catch { /* 已经结束 */ }
  try { current.res && current.res.destroy() } catch { /* 同上 */ }
  return true
}

/**
 * 下载安装包。进度经 `onProgress({got,total,pct})` 回调，平均 200ms 一次（不刷爆 IPC）。
 * 取消 / 出错 **一律删除半截文件**：留着它只会让下次误判"已下载"。
 */
function download(onProgress) {
  const info = lastCheck
  if (!info || !info.asset) {
    return Promise.resolve({ ok: false, code: 'NO_ASSET', message: '这个版本没有可下载的安装包。' })
  }
  if (current) return Promise.resolve({ ok: false, code: 'BUSY', message: '已经有一个下载在进行。' })

  const dir = updateDir()
  const file = path.join(dir, path.basename(info.asset.name))
  const expectedSize = info.asset.size || 0

  // 失败一律删除半截文件；但必须在文件流 close 之后删，Windows 上流还开着时 rm 会 EBUSY
  const fail = (code, detail) => ({
    ok: false,
    code,
    message: humanError(code, detail).message,
    detail: detail || '',
  })

  try {
    fs.mkdirSync(dir, { recursive: true })
    fs.rmSync(file, { force: true })
  } catch (e) {
    return Promise.resolve(fail('DISK', String(e.message || e)))
  }

  return new Promise((resolve) => {
    const out = fs.createWriteStream(file)
    let got = 0
    let lastTick = 0
    let settled = false
    const req = net.request({ url: info.asset.url, method: 'GET', redirect: 'follow' })
    current = { req, file, cancelled: false }
    req.setHeader('User-Agent', USER_AGENT)

    const finish = (result) => {
      if (settled) return
      settled = true
      if (current && current.req === req) current = null
      out.close(() => {
        if (!result.ok) {
          try { fs.rmSync(file, { force: true }) } catch { /* 删不掉也不能把错误码盖掉 */ }
        }
        resolve(result)
      })
    }

    req.on('response', (res) => {
      if (res.statusCode !== 200) {
        res.resume()
        finish(fail('HTTP_' + res.statusCode, `下载返回 ${res.statusCode}`))
        return
      }
      if (current && current.req === req) current.res = res
      const total = Number(res.headers['content-length']) || expectedSize
      res.on('data', (chunk) => {
        got += chunk.length
        out.write(chunk)
        const now = Date.now()
        if (now - lastTick > 200) {
          lastTick = now
          if (onProgress) {
            onProgress({ got, total, pct: total ? Math.min(99, Math.round((got / total) * 100)) : 0 })
          }
        }
      })
      res.on('end', async () => {
        out.end()
        if (current && current.req === req && current.cancelled) {
          finish({ ok: false, code: 'CANCELLED', message: '已取消下载。', cancelled: true })
          return
        }
        if (expectedSize && got !== expectedSize) {
          finish(fail('SIZE', `大小不符：期望 ${expectedSize}，实得 ${got}`))
          return
        }
        // 校验：有 .sha256 就比哈希，没有就只报大小并明说（M8 §4.2）
        let verify = 'size'
        if (info.sha256Asset) {
          try {
            const shaRes = await request(info.sha256Asset.url)
            const hex = (String(shaRes.body).match(/[a-f0-9]{64}/i) || [''])[0].toLowerCase()
            const actual = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
            if (!hex || hex !== actual) {
              finish(fail('CHECKSUM', hex ? '哈希不一致' : '.sha256 里没有哈希'))
              return
            }
            verify = 'sha256'
          } catch (e) {
            finish(fail(classify(e), String((e && e.message) || e)))
            return
          }
        }
        if (onProgress) onProgress({ got, total: got, pct: 100 })
        finish({ ok: true, path: file, bytes: got, verify })
      })
      res.on('error', (e) => finish(fail(classify(e), String((e && e.message) || e))))
      // destroy() 之后可能只来 close 不来 error，取消的判断放这里兜一次
      res.on('close', () => {
        if (current && current.cancelled) {
          finish({ ok: false, code: 'CANCELLED', message: '已取消下载。', cancelled: true })
        }
      })
    })

    req.on('error', (e) => {
      // abort() 会走到这里：当作用户取消，不当故障（否则界面会红一次再变灰）
      if (current && current.cancelled) {
        finish({ ok: false, code: 'CANCELLED', message: '已取消下载。', cancelled: true })
        return
      }
      finish(fail(classify(e), String((e && e.message) || e)))
    })
    req.end()
  })
}

/** 已下好的文件还在不在（安装前再确认一次，防止用户手工删了临时目录） */
function downloadedFile() {
  const info = lastCheck
  if (!info || !info.asset) return null
  const file = path.join(updateDir(), path.basename(info.asset.name))
  try {
    const st = fs.statSync(file)
    return st.isFile() && st.size > 0 ? file : null
  } catch {
    return null
  }
}

module.exports = {
  REPO,
  RELEASES_PAGE,
  check,
  download,
  cancel,
  cleanup,
  downloadedFile,
  compareVersions,
  parseVersion,
}
