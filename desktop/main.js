// Cairn 桌面壳（T5.5）。
//
// 只做五件事，一件都不多：
//   1. 随机端口：`net.createServer().listen(0)` 让系统给，绝不硬编码（M5 §1 约束 6）
//   2. spawn 后端：dev 用 `uv run python -m app`，打包后用 `resources/backend/cairn-backend.exe`
//   3. 每 300ms 轮询 `GET /api/health`，**握手成功之后才建窗口**（ADR-016）
//      —— 握手用 HTTP 轮询而不是读子进程 stdout，因为 windowed exe 的 stdout 是 None
//   4. 窗口加载 `http://127.0.0.1:{port}/`：页面与 /api 同源，不用 `file://`
//      （`file://` 的 origin 是 null，会撞上后端只放行 5173 的 CORS 白名单）
//   5. 关窗/退出时按**进程树**杀掉后端，不留孤儿进程
//
// 明确不做（留给 T5.6/T5.7）：NSIS 安装包配置、图标、签名、托盘、自动更新、首次引导。
// 也不注入 preload：契约 §4 已定「页面走相对路径，底座同源」，注入 baseUrl 只会多一层
// 永远用不上的配置（docs/contracts/接口契约.md §4）。
'use strict'

const { app, BrowserWindow, dialog, session } = require('electron')
const { spawn, spawnSync } = require('node:child_process')
const http = require('node:http')
const net = require('node:net')
const fs = require('node:fs')
const path = require('node:path')

const isDev = !app.isPackaged
// 数据目录必须是 %APPDATA%/Cairn（M5 §1 约束 4）。
// app.getPath('userData') 取的是 package.json 的 `name`（cairn-desktop），**不是**
// productName，所以必须显式改名，否则数据会落在 %APPDATA%/cairn-desktop。
app.setName('Cairn')

const BACKEND_DIR = path.resolve(__dirname, '..', 'backend')
const HEALTH_INTERVAL_MS = 300
const HEALTH_TIMEOUT_MS = 30000

// 内容安全策略在 main 里注入 header，而不是往 index.html 塞 <meta>：
// 那里加会把 vite dev 的内联 HMR 脚本一起拦掉（dev 页面是 5173 直接吐的）。
// style-src 必须留 'unsafe-inline'：模板里有 `style="width: 80%"` 这类静态属性。
// frame-src 只放 'self'：学习页预览是 `GET /api/html/{id}`，同源 iframe。
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "media-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "frame-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ')

let backend = null
let win = null
let backendPort = 0
let quitting = false
let consoleErrors = 0
// 进程启动时刻：DoD 要求"双击 5 秒内出界面"，只能拿它当 0 点
const T0 = Date.now()

// ── 日志 ────────────────────────────────────────────────
// Electron 主进程在 Windows 下 stdout 不总能落到控制台；windowed exe 更是没有 stdout。
// 所以一律双写文件。dev 写到 desktop/_smoke/（gitignored，方便看现场），
// 打包后写到 %APPDATA%/Cairn/logs/（安装目录只读）。
const LOG_DIR = isDev ? path.join(__dirname, '_smoke') : path.join(app.getPath('userData'), 'logs')
const LOG_FILE = path.join(LOG_DIR, 'shell.log')
const verbose = isDev || process.env.CAIRN_SHELL_VERBOSE === '1'

// 立刻建目录：日志必须从"主进程第一行"就开始记。
// 这一行曾经救过一次——打包后主进程根本没跑到 boot()，全靠这个标记才定位到是
// `app.getPath('userData')` 取成了 `%APPDATA%/cairn-desktop`（productName 不参与命名）。
try {
  fs.mkdirSync(LOG_DIR, { recursive: true })
} catch { /* 建不出来也不能不启动 */ }

// main.js 一旦被 Electron 执行就会有这一行；如果日志里连它都没有，
// 说明问题不在启动逻辑，而在"主进程根本没加载"（asar / main 字段 / 入口路径）。
log(`主进程已加载 pid=${process.pid}`)

function log(msg) {
  // 带时间戳：排障时"握手用了多久""首屏多久出来"只能靠这个对时间轴
  const t = new Date().toTimeString().slice(0, 8)
  const line = `[${t}] ${msg}`
  if (verbose) console.log(line)
  try {
    fs.appendFileSync(LOG_FILE, line + '\n')
  } catch { /* 日志写不进去也不能拖垮启动 */ }
}

function appendBackend(chunk) {
  const text = chunk.toString().replace(/\s+$/, '')
  if (!text) return
  const t = new Date().toTimeString().slice(0, 8)
  try {
    for (const line of text.split(/\r?\n/)) fs.appendFileSync(LOG_FILE, `[${t}] [backend] ${line}\n`)
  } catch { /* 同上 */ }
}

// ── 端口与握手 ──────────────────────────────────────────
function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.unref()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })
}

function healthOnce(port) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: '127.0.0.1', port, path: '/api/health', timeout: 1000 },
      (res) => {
        let body = ''
        res.setEncoding('utf8')
        res.on('data', (c) => { body += c })
        res.on('end', () => resolve(res.statusCode === 200 ? body : null))
      },
    )
    req.on('timeout', () => req.destroy())
    req.on('error', () => resolve(null))
  })
}

async function waitHealth(port) {
  const t0 = Date.now()
  let attempts = 0
  while (Date.now() - t0 < HEALTH_TIMEOUT_MS) {
    attempts += 1
    const body = await healthOnce(port)
    if (body) return { body, attempts, elapsed: Date.now() - t0 }
    await new Promise((r) => setTimeout(r, HEALTH_INTERVAL_MS))
  }
  return { body: null, attempts, elapsed: Date.now() - t0 }
}

// ── 后端进程 ────────────────────────────────────────────
function startBackend(port) {
  // dev：uv run 会再拉一层 python 子进程，所以下面必须按**树**杀（taskkill /T）
  // prod：cairn-backend.exe 自己就是后端，没有中间层，但 /T 照样适用
  const exe = path.join(process.resourcesPath, 'backend', 'cairn-backend.exe')
  const cmd = isDev ? 'uv' : exe
  const args = isDev
    ? ['run', 'python', '-m', 'app', '--port', String(port)]
    : ['--port', String(port), '--data-dir', app.getPath('userData')]

  const env = { ...process.env }
  // 后端的 print/日志会被我们接到管道里写进 shell.log；Windows 下 Python 对管道默认用
  // cp936，混着 utf-8 读就是乱码。显式要求 utf-8，日志才看得懂。
  env.PYTHONIOENCODING = 'utf-8'
  env.PYTHONUTF8 = '1'
  if (!isDev) {
    // 页面在 resources/web（electron-builder 的 extraResources），后端已有这个开关，
    // 不用改后端代码。dev 不设，后端自己回落到 frontend/dist。
    env.CAIRN_WEB_DIR = path.join(process.resourcesPath, 'web')
    // 打包后不该再往「项目目录」里写：清掉可能从系统环境继承来的覆盖项
    delete env.DATA_DIR
  }

  log(`spawn ${cmd} ${args.join(' ')}`)
  const child = spawn(cmd, args, {
    cwd: isDev ? BACKEND_DIR : undefined,
    windowsHide: true,
    env,
  })
  child.stdout?.on('data', appendBackend)
  child.stderr?.on('data', appendBackend)
  child.on('error', (e) => log(`后端 spawn 失败: ${e.message}`))
  child.on('exit', (code, sig) => {
    log(`后端进程退出 code=${code} signal=${sig}`)
    // 握手成功之后后端又死了（OOM / 崩在某个请求里）：给用户一个能看懂的页面，
    // 而不是留一个点不动的白窗。boot 阶段的退出由 waitHealth 失败兜住，不重复弹。
    if (backendPort && !quitting) showError({ reason: 'backend-exited', detail: `code=${code}` })
  })
  return child
}

// taskkill 的中文提示是 GBK，按 utf8 读是乱码
function killBackend() {
  if (!backend || !backend.pid) return
  const pid = backend.pid
  const r = spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { encoding: 'buffer' })
  const raw = Buffer.concat([r.stdout || Buffer.alloc(0), r.stderr || Buffer.alloc(0)])
  let out
  try { out = new TextDecoder('gbk').decode(raw) } catch { out = raw.toString('utf8') }
  log(`taskkill /PID ${pid} /T /F → ${out.trim().replace(/\r?\n/g, ' | ')}`)
  backend = null
}

// ── 窗口 ────────────────────────────────────────────────
function injectCsp(base) {
  session.defaultSession.webRequest.onHeadersReceived({ urls: [`${base}/*`] }, (details, cb) => {
    const headers = details.responseHeaders || {}
    delete headers['Content-Security-Policy']
    delete headers['content-security-policy']
    headers['Content-Security-Policy'] = [CSP]
    cb({ responseHeaders: headers })
  })
}

function openWindow(base) {
  win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    title: 'Cairn',
    backgroundColor: '#faf8f4',
    show: false,                 // 等 ready-to-show，避免启动时先白一帧
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  })

  win.once('ready-to-show', () => {
    log(`窗口可显示：距进程启动 ${Date.now() - T0}ms`)
    win.show()
  })

  // 首屏完成单独记一行（不只在 verbose 下）：这是"5 秒内出界面"的唯一硬证据
  win.webContents.once('did-finish-load', () => {
    log(`首屏加载完成：距进程启动 ${Date.now() - T0}ms`)
  })

  if (verbose) {
    win.webContents.on('console-message', (...a) => {
      const e = a[0]
      const level = e && typeof e === 'object' && e.level !== undefined ? e.level : a[1]
      const msg = e && typeof e === 'object' && e.message !== undefined ? e.message : a[2]
      if (level === 'error' || level === 3) consoleErrors += 1
      log(`console[${level}] ${String(msg).slice(0, 300)}`)
    })
  }

  win.loadURL(`${base}/`)
  win.on('closed', () => { win = null })

  // 冒烟用：只为自动化验"关窗无残留"，不是产品功能
  const ms = Number(process.env.SMOKE_AUTOCLOSE_MS || 0)
  if (ms > 0) {
    win.webContents.once('did-finish-load', () => {
      setTimeout(async () => {
        try {
          const img = await win.webContents.capturePage()
          fs.writeFileSync(path.join(LOG_DIR, 'window.png'), img.toPNG())
          log(`截图已存 ${path.join(LOG_DIR, 'window.png')}`)
        } catch (e) { log(`截图失败（不影响验证）: ${e.message}`) }
        log(`关窗前 console 错误数 = ${consoleErrors}`)
        win.close()
      }, ms)
    })
  }
}

// 后端起不来的兜底页。绝不 `app.exit` 了事——那样用户只看到窗口闪一下就没了，
// 或者留一个白窗（遗留 8）。页面上要给出「日志在哪」，这是用户唯一能自救的信息。
function showError({ reason, detail }) {
  const params = new URLSearchParams({
    reason: reason || 'unknown',
    detail: detail || '',
    log: LOG_FILE,
    mode: isDev ? 'dev' : 'packaged',
  })
  if (!win) {
    win = new BrowserWindow({
      width: 720,
      height: 520,
      title: 'Cairn · 启动失败',
      backgroundColor: '#faf8f4',
      autoHideMenuBar: true,
      webPreferences: { contextIsolation: true, nodeIntegration: false },
    })
    win.on('closed', () => { win = null })
  }
  win.loadFile(path.join(__dirname, 'error.html'), { query: Object.fromEntries(params) })
}

// ── 启动 ────────────────────────────────────────────────
async function boot() {
  log(`Cairn 启动 mode=${isDev ? 'dev' : 'packaged'} electron=${process.versions.electron}`)
  log(`userData=${app.getPath('userData')}`)

  backendPort = await freePort()
  log(`空闲端口 ${backendPort}`)
  backend = startBackend(backendPort)

  const h = await waitHealth(backendPort)
  if (!h.body) {
    log(`握手失败：${HEALTH_TIMEOUT_MS}ms 内 /api/health 未就绪（尝试 ${h.attempts} 次）`)
    killBackend()
    showError({ reason: 'health-timeout', detail: `${HEALTH_TIMEOUT_MS}ms / ${h.attempts} 次` })
    return
  }
  log(`握手成功：${h.attempts} 次 / ${h.elapsed}ms / ${h.body}`)

  const base = `http://127.0.0.1:${backendPort}`
  injectCsp(base)
  openWindow(base)
}

// 单实例：第二次双击只是把已有窗口叫到前面，而不是再起一个后端占一个端口
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  app.whenReady().then(boot).catch((e) => {
    log(`启动异常: ${e && e.stack ? e.stack : e}`)
    killBackend()
    showError({ reason: 'boot-exception', detail: String((e && e.message) || e) })
  })
}

app.on('window-all-closed', () => {
  log('窗口已关闭，清理后端')
  killBackend()
  app.quit()
})

// 兜底：崩溃或强制退出路径上再杀一次（killBackend 幂等）
app.on('before-quit', () => {
  quitting = true
  killBackend()
})
process.on('exit', () => { try { killBackend() } catch { /* 退出路径上不再抛 */ } })
