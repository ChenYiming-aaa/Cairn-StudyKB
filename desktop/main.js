// Cairn 桌面壳 —— 空壳验证（M1 遗留项），只验四件事：
//   1. spawn 后端（uv run python -m app，不上 PyInstaller）
//   2. 随机端口 + 每 300ms 轮询 GET /api/health，确认可用后才建窗口（ADR-013 / ADR-016）
//   3. 窗口用 file:// 加载 index.html
//   4. 关窗口后杀掉后端整棵进程树，不留 python 残留
// 明确不做：NSIS 安装包 / 图标 / 签名 / 接 Vite 产物 / 托盘 / 自动更新。
'use strict'

const { app, BrowserWindow } = require('electron')
const { spawn, spawnSync } = require('node:child_process')
const http = require('node:http')
const net = require('node:net')
const fs = require('node:fs')
const path = require('node:path')

const BACKEND_DIR = path.resolve(__dirname, '..', 'backend')
const SMOKE_DIR = path.join(__dirname, '_smoke')
const LOG_FILE = path.join(SMOKE_DIR, 'run.log')
const HEALTH_INTERVAL_MS = 300
const HEALTH_TIMEOUT_MS = 30000

let backend = null
let win = null

// Electron 主进程在 Windows 下的 stdout 不总能落到控制台，所以同时写一份日志文件，
// 四项验证的实测输出都从这份文件取。
function log(msg) {
  const line = `[shell] ${msg}`
  console.log(line)
  fs.appendFileSync(LOG_FILE, line + '\n')
}

function appendBackend(chunk) {
  const text = chunk.toString().trimEnd()
  if (!text) return
  for (const line of text.split(/\r?\n/)) {
    fs.appendFileSync(LOG_FILE, `[backend] ${line}\n`)
  }
}

// 让系统分配一个空闲端口：listen(0) 后立刻关掉，拿到的端口再交给后端
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

// 单次 GET /api/health；连不上 / 超时 / 非 200 一律当"还没起来"
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

// uv run 会再拉一个 python 子进程，只 kill uv 会留下孤儿；按 pid 杀整棵树
function killBackend() {
  if (!backend || !backend.pid) return
  const pid = backend.pid
  // taskkill 的中文提示是 GBK 编码，按 utf8 读会变乱码，这里显式解码
  const r = spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { encoding: 'buffer' })
  const raw = Buffer.concat([r.stdout || Buffer.alloc(0), r.stderr || Buffer.alloc(0)])
  let out
  try { out = new TextDecoder('gbk').decode(raw) } catch { out = raw.toString('utf8') }
  log(`4/4 taskkill /PID ${pid} /T /F → ${out.trim().replace(/\r?\n/g, ' | ')}`)
  backend = null
}

function createWindow(port, version) {
  win = new BrowserWindow({
    width: 900,
    height: 640,
    title: 'Cairn',
    backgroundColor: '#faf8f4',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  })

  win.loadFile(path.join(__dirname, 'index.html'), {
    query: { port: String(port), version: version || '' },
  })

  win.webContents.on('did-finish-load', async () => {
    log(`3/4 页面加载完成 url=${win.webContents.getURL()}`)
    log(`3/4 窗口标题 = ${win.getTitle()}`)
    try {
      const img = await win.webContents.capturePage()
      const png = path.join(SMOKE_DIR, 'window.png')
      fs.writeFileSync(png, img.toPNG())
      log(`3/4 截图已存 ${png}`)
    } catch (e) {
      log(`3/4 截图失败（不影响验证）: ${e.message}`)
    }
    const ms = Number(process.env.SMOKE_AUTOCLOSE_MS || 0)
    if (ms > 0) {
      log(`3/4 ${ms}ms 后自动关窗（SMOKE_AUTOCLOSE_MS，仅验证用）`)
      setTimeout(() => win.close(), ms)
    }
  })

  win.on('closed', () => { win = null })
}

async function boot() {
  fs.mkdirSync(SMOKE_DIR, { recursive: true })
  fs.writeFileSync(LOG_FILE, '')

  const port = await freePort()
  log(`1/4 探测到空闲端口 ${port}`)

  const args = ['run', 'python', '-m', 'app', '--port', String(port)]
  log(`1/4 spawn: uv ${args.join(' ')}   cwd=${BACKEND_DIR}`)
  backend = spawn('uv', args, { cwd: BACKEND_DIR, windowsHide: true, env: process.env })
  log(`1/4 后端进程 pid=${backend.pid}`)
  backend.stdout.on('data', appendBackend)
  backend.stderr.on('data', appendBackend)
  backend.on('exit', (code, sig) => log(`4/4 后端进程退出 code=${code} signal=${sig}`))

  const h = await waitHealth(port)
  if (!h.body) {
    log(`2/4 失败：${HEALTH_TIMEOUT_MS}ms 内 /api/health 未就绪（尝试 ${h.attempts} 次）`)
    killBackend()
    app.exit(1)
    return
  }
  log(`2/4 GET http://127.0.0.1:${port}/api/health → ${h.body}`)
  log(`2/4 握手成功：尝试 ${h.attempts} 次，耗时 ${h.elapsed}ms`)

  let version = ''
  try { version = JSON.parse(h.body).version } catch { /* 只用于展示 */ }
  createWindow(port, version)
}

app.whenReady().then(boot).catch((e) => {
  log(`启动失败: ${e && e.stack ? e.stack : e}`)
  killBackend()
  app.exit(1)
})

app.on('window-all-closed', () => {
  log('4/4 窗口已关闭，开始清理后端')
  killBackend()
  app.quit()
})

// 兜底：崩溃或强制退出路径上再杀一次（killBackend 幂等）
app.on('before-quit', killBackend)
