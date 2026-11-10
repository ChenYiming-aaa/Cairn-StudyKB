// preload（T8.5）：渲染进程与主进程之间**唯一的**通道。
//
// 契约 §4 曾定「不注入 preload」—— 当时是为了不做 baseUrl 注入（页面与 /api 同源，
// 不需要任何桥）。更新器是第一个真正需要特权的能力：下载文件、起安装器、退进程，
// 这些都不能给渲染进程。所以只开**四个方法 + 三个只读字段**，一律走 IPC，
// **绝不暴露 `ipcRenderer` 本身**（暴露了等于把所有通道都开给页面）。
//
// 版本号与是否打包由 main 通过 `additionalArguments` 传进来（同步、无需 IPC 往返）；
// 页面拿它决定「要不要显示更新按钮」，作弊也没用 —— 主进程侧还会再判一次 isPackaged。
'use strict'

const { contextBridge, ipcRenderer } = require('electron')

function arg(name) {
  const hit = process.argv.find((a) => a.startsWith(`--cairn-${name}=`))
  return hit ? hit.slice(hit.indexOf('=') + 1) : ''
}

const appInfo = {
  version: arg('version'),
  isPackaged: arg('packaged') === '1',
  platform: process.platform,
}

if (process.isMainFrame) {
  contextBridge.exposeInMainWorld('cairn', {
    app: Object.freeze({ ...appInfo }),
    update: {
      check: () => ipcRenderer.invoke('update:check'),
      download: () => ipcRenderer.invoke('update:download'),
      cancel: () => ipcRenderer.invoke('update:cancel'),
      install: () => ipcRenderer.invoke('update:install'),
      // 进度是主进程推的（下载在 main 里跑，不经渲染进程的网络栈）
      onProgress: (callback) => {
        const handler = (_event, payload) => callback(payload)
        ipcRenderer.on('update:progress', handler)
        return () => ipcRenderer.removeListener('update:progress', handler)
      },
    },
  })
}
