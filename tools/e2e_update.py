#!/usr/bin/env python3
"""更新器端到端实测（T8.5）。

**这是"装真机"的验收，不是单元测试**：真装一个 Cairn、真拉 170 MB、真起 NSIS、真退进程。
所以它不在 `verify_m8.py` 里跑（那个脚本要求"不联网、不装东西、随时能跑"），
而是 T8.5 收口时手工跑一次的记录工具。

三个断言（任务书 §5 T8.5 明写"不能省"的那三个）：
  1. **断网给人话** —— 连不上时界面要有一句能看懂的话 + 手动下载入口，不能只留红叉
  2. **取消下载文件删净** —— `%TEMP%\\cairn-update\\` 里不能留半截 exe
  3. **装完无孤儿 `cairn-backend.exe`** —— 点「打开安装程序」后壳退出，旧后端必须跟着死

为什么"发现 0.2.0"走本地假 API：GitHub 上 0.2.0 的 Release 要到 T8.7 才建（今天只有 v0.1.0），
真 API 必然回答"已是最新"。本地服务的响应形状与 GitHub 一致，**下载、校验、起安装器、
退进程全是真的**，只有"最新版是谁"这条来自本地。生产代码不读这个开关，默认就是 api.github.com。

用法（在**装好 0.1.9 之后**跑）：

    python tools/e2e_update.py \\
        --exe "C:/Users/<你>/AppData/Local/Programs/Cairn/Cairn.exe" \\
        --asset "desktop/release-m8e/Cairn-0.2.0-setup.exe" \\
        --version 0.2.0 \\
        --only all

    # 单独跑某一幕（调试用）
    python tools/e2e_update.py ... --only offline
    python tools/e2e_update.py ... --only cancel
    python tools/e2e_update.py ... --only install
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = 'ChenYiming-aaa/Cairn-StudyKB'
RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((bool(ok), name, detail))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail else ''), flush=True)


def step(title: str) -> None:
    print(f'\n── {title} ' + '─' * max(0, 44 - len(title)), flush=True)


# ── 本地"GitHub" ────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    asset: Path | None = None
    sha: str = ''
    version: str = '0.2.0'
    throttle_bps = 6 * 1024 * 1024
    request_log: list[str] = []

    def log_message(self, *args):        # 别把每个请求都打到控制台
        pass

    def do_GET(self):                     # noqa: N802
        _Handler.request_log.append(self.path)
        if self.path.endswith('/releases/latest'):
            body = json.dumps({
                'tag_name': f'v{self.version}',
                'name': f'Cairn v{self.version}',
                'html_url': f'https://github.com/{REPO}/releases/tag/v{self.version}',
                'body': '### 本次更新\n\n- 更新器端到端实测用的假 Release\n- 第二行说明\n',
                'assets': [
                    # 文件名跟着"假版本"走（内容还是本地这个真安装包）：装 0.2.0 之后
                    # 想再验一次更新，就把假版本设成 0.2.1，不必真去造一个 0.2.1
                    {'name': f'Cairn-{self.version}-setup.exe', 'size': self.asset.stat().st_size,
                     'browser_download_url': f'http://127.0.0.1:{self.server.server_port}/dl/setup.exe'},
                    {'name': f'Cairn-{self.version}-setup.exe.sha256', 'size': 80,
                     'browser_download_url': f'http://127.0.0.1:{self.server.server_port}/dl/setup.exe.sha256'},
                ],
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == '/dl/setup.exe.sha256':
            body = f'{self.sha}  {Path(self.asset).name}\n'.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == '/dl/setup.exe':
            size = self.asset.stat().st_size
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(size))
            self.end_headers()
            sent = 0
            chunk = 256 * 1024
            try:
                with open(self.asset, 'rb') as fp:
                    while sent < size:
                        buf = fp.read(chunk)
                        if not buf:
                            break
                        self.wfile.write(buf)
                        sent += len(buf)
                        # 限速：取消测试要能在 5%–10% 处插进去
                        time.sleep(len(buf) / self.throttle_bps)
            except (BrokenPipeError, ConnectionAbortedError):
                pass
            return
        self.send_error(404)


def start_fake_github(asset: Path, version: str) -> tuple[ThreadingHTTPServer, str]:
    _Handler.asset = asset
    _Handler.version = version
    _Handler.sha = hashlib.sha256(asset.read_bytes()).hexdigest()
    _Handler.request_log.clear()
    srv = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_port}'


# ── 进程与 CDP ──────────────────────────────────────────────
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return int(s.getsockname()[1])


def _tasklist(name: str) -> int:
    out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}', '/NH'],
                         capture_output=True, text=True, encoding='gbk', errors='replace').stdout
    return out.count(name)


def launch(exe: Path, env_extra: dict[str, str], cdp_port: int) -> subprocess.Popen:
    env = {**os.environ, **env_extra}
    # 这个环境变量在 WorkBuddy 的 shell 里是开着的，会让打包后的 exe 退化成纯 Node
    # （报 `Cannot read properties of undefined (reading 'isPackaged')`，且不写日志）
    env.pop('ELECTRON_RUN_AS_NODE', None)
    proc = subprocess.Popen([str(exe), f'--remote-debugging-port={cdp_port}'], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def wait_cdp(port: int, timeout: float = 40) -> None:
    """等 CDP 起来，**并且等到窗口页面出现**。

    只等 `/json/version` 是不够的：那个端点在浏览器进程起来时就响应了，此时窗口还没建，
    Playwright `connect_over_cdp` 拿到的 contexts 里 0 个 page，之后再也不会刷新。
    """
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=1) as resp:
                targets = json.load(resp)
            if any(t.get('type') == 'page' and str(t.get('url', '')).startswith('http://127.0.0.1')
                   for t in targets):
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError(f'CDP {port} 端口 {timeout}s 内没等到应用页面')


def attach(cdp_port: int):
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{cdp_port}')
    page = None
    for ctx in browser.contexts:
        for p in ctx.pages:
            if '127.0.0.1' in (p.url or '') and p.url.startswith('http'):
                page = p
                break
    if page is None:
        raise RuntimeError('没找到应用窗口的页面')
    page.wait_for_load_state('domcontentloaded')
    return pw, browser, page


def open_about(page) -> None:
    page.wait_for_selector('button[aria-label="设置"]', timeout=30000)
    page.click('button[aria-label="设置"]')
    page.wait_for_selector('[role="dialog"]', timeout=10000)
    page.click('[role="tab"]:has-text("关于")')
    page.wait_for_selector('.update', timeout=10000)


def update_text(page) -> str:
    return (page.locator('.update .update-row .update-note').inner_text() or '').strip()


def update_button(page):
    return page.locator('.update .update-row button').first


def wait_text(page, needle: str, timeout: float = 60) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if needle in update_text(page):
            return True
        time.sleep(0.3)
    return False


def clear_temp() -> None:
    """清空 %TEMP%/cairn-update 再开跑。

    不清的话，"取消后没有残留"会被上一次成功安装留下的包误判成失败
    （那个包按设计要留到下次启动、10 分钟后才清）。
    """
    shutil.rmtree(temp_dir(), ignore_errors=True)


def shot(name: str) -> Path:
    d = ROOT / 'data' / 'e2e_update'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{name}.png'


def wait_err(page, needle: str, timeout: float = 30) -> str:
    """等错误段落出现并包含 needle，返回实际文本（失败时也返回，便于打印）"""
    end = time.time() + timeout
    text = ''
    while time.time() < end:
        loc = page.locator('.update .err')
        if loc.count():
            text = loc.inner_text().strip()
            if needle in text:
                return text
        time.sleep(0.3)
    return text


def temp_dir() -> Path:
    return Path(tempfile.gettempdir()) / 'cairn-update'


def temp_files() -> list[str]:
    d = temp_dir()
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def kill_installer_windows(name: str) -> None:
    """把 NSIS 向导关掉（我们只用它验证"壳退出"，安装本身交给下面的静默安装）。

    进程名是**本地那个安装包的文件名**，不是假 Release 的版本号 —— 两者可能不同（见 --fake-version）。
    """
    subprocess.run(['taskkill', '/IM', name, '/F'],
                   capture_output=True, text=True, encoding='gbk', errors='replace')


# ── 三幕 ────────────────────────────────────────────────────
def scenario_offline(exe: Path) -> None:
    step('① 断网：必须给人话')
    cdp = _free_port()
    # `.invalid` 是保留域名，DNS 一定解析失败 —— 与真断网走同一条错误路径
    proc = launch(exe, {'CAIRN_UPDATE_API_BASE': 'http://cairn-offline.invalid'}, cdp)
    try:
        wait_cdp(cdp)
        pw, browser, page = attach(cdp)
        open_about(page)
        check('关于页有「检查更新」按钮', update_button(page).is_visible())
        update_button(page).click()
        text = wait_err(page, '连不上', timeout=30)
        check('断网时显示人话（不是红叉/英文错误码）',
              '连不上' in text and '检查网络' in text, text[:90])
        check('同时给出手动下载入口', page.locator('.update .manual').count() == 1)
        check('没有把异常码当正文丢给用户', 'ERR_' not in text and 'Error' not in text, text[:60])
        page.screenshot(path=str(shot('offline')))
        pw.stop()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(1)


def scenario_cancel(exe: Path, api: str, version: str) -> None:
    step('② 取消下载：临时文件必须删净')
    clear_temp()
    cdp = _free_port()
    proc = launch(exe, {'CAIRN_UPDATE_API_BASE': api}, cdp)
    try:
        wait_cdp(cdp)
        pw, browser, page = attach(cdp)
        open_about(page)
        update_button(page).click()
        check(f'发现新版本 {version}', wait_text(page, f'{version} 可用', timeout=40), update_text(page))
        check('按钮变成下载', '下载' in update_button(page).inner_text(), update_button(page).inner_text())

        update_button(page).click()          # 开始下载
        # 等到 3% 以上再取消：太早取消可能还没建文件，验不出"删净"
        pct = 0
        end = time.time() + 60
        while time.time() < end and pct < 3:
            try:
                pct = int(page.locator('.update .bar-fill').evaluate('(el) => parseInt(el.style.width) || 0'))
            except Exception:
                pct = 0
            time.sleep(0.2)
        check('下载真的开始了（进度 > 3%）', pct >= 3, f'{pct}%')
        during = temp_files()
        check('下载中有半截文件（说明在真写盘）', any(n.endswith('.exe') for n in during), str(during))

        update_button(page).click()          # 取消
        check('取消后回到可下载状态', wait_text(page, f'{version} 可用', timeout=30), update_text(page))
        time.sleep(1.0)
        after = temp_files()
        check('取消后临时目录没有 exe 残留', not any(n.endswith('.exe') for n in after), str(after))
        page.screenshot(path=str(shot('cancel')))
        pw.stop()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(1)


def scenario_install(exe: Path, api: str, asset: Path, version: str) -> None:
    step('③ 下载完 → 打开安装程序 → 壳退出 → 无孤儿后端')
    clear_temp()
    cdp = _free_port()
    proc = launch(exe, {'CAIRN_UPDATE_API_BASE': api}, cdp)
    try:
        wait_cdp(cdp)
        pw, browser, page = attach(cdp)
        open_about(page)
        update_button(page).click()
        check('发现新版本', wait_text(page, f'{version} 可用', timeout=40), update_text(page))
        update_button(page).click()          # 下载
        ok = wait_text(page, '已下载完成', timeout=600)
        check('下载完成并校验通过', ok, update_text(page))
        ready_text = page.locator('.update .update-note').all_inner_texts()
        check('明确写了校验方式', any('校验值一致' in t for t in ready_text), ' / '.join(ready_text)[:80])
        check('按钮变成「打开安装程序」', '安装程序' in update_button(page).inner_text(),
              update_button(page).inner_text())
        check('下载的文件在临时目录', any(n.endswith('.exe') for n in temp_files()), str(temp_files()))

        check('点之前有后端进程', _tasklist('cairn-backend.exe') >= 1, str(_tasklist('cairn-backend.exe')))
        update_button(page).click()           # 打开安装程序

        # 壳应自己退出
        end = time.time() + 30
        while time.time() < end and proc.poll() is None:
            time.sleep(0.3)
        check('壳已退出（app.exit(0)）', proc.poll() is not None, f'exit={proc.poll()}')
        time.sleep(1.5)
        check('没有孤儿 cairn-backend.exe', _tasklist('cairn-backend.exe') == 0,
              f'count={_tasklist("cairn-backend.exe")}')
        check('没有残留 Cairn.exe', _tasklist('Cairn.exe') == 0, f'count={_tasklist("Cairn.exe")}')
        check('安装器确实起来了', _tasklist(asset.name) >= 1, f'count={_tasklist(asset.name)}')
        pw.stop()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()

    step('③b 把向导关掉，用同一个安装包静默装完（验"装完"之后的版本与孤儿）')
    kill_installer_windows(asset.name)
    time.sleep(1.0)
    r = subprocess.run([str(asset), '/S'], capture_output=True)
    check('静默安装退出码 0', r.returncode == 0, f'code={r.returncode}')
    time.sleep(3)
    check('装完仍然没有孤儿后端', _tasklist('cairn-backend.exe') == 0,
          f'count={_tasklist("cairn-backend.exe")}')


def scenario_real(exe: Path, version: str) -> None:
    """不设任何 override，走真 api.github.com —— 验 User-Agent / 重定向 / JSON 解析这条真路。

    今天 GitHub 上只有 v0.1.0，所以 0.2.0 的包必须判「已是最新」；
    等 T8.7 传了 v0.2.0 的 Release，同一幕会变成「0.2.0 可用」。
    """
    step('④ 真 GitHub：版本与构建信息 + 判定')
    cdp = _free_port()
    proc = launch(exe, {}, cdp)
    try:
        wait_cdp(cdp)
        pw, browser, page = attach(cdp)
        open_about(page)
        facts = [t.strip() for t in page.locator('.facts .fact dd').all_inner_texts()]
        ver_text = page.locator('.about .ver').inner_text().strip()
        check('关于页版本取自后端（T8.6）', version in ver_text, ver_text)
        check('装机版有提交号（不再显示"源码运行"）',
              facts and '源码运行' not in facts[0], facts[0] if facts else '')
        check('装机版有构建时间', len(facts) > 1 and '源码运行' not in facts[1], facts[1] if len(facts) > 1 else '')
        update_button(page).click()
        ok = wait_text(page, '已是最新版本', timeout=45)
        check('真 API 判定为「已是最新」', ok, update_text(page))
        page.screenshot(path=str(shot('latest')))
        pw.stop()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', required=True, help='已安装的 Cairn.exe（0.1.9）')
    ap.add_argument('--asset', required=True, help='0.2.0 的 setup.exe（本地 HTTP 服务用）')
    ap.add_argument('--version', default='0.2.0', help='本机已装版本的期望值（用于关于页断言）')
    ap.add_argument('--fake-version', default=None,
                    help='假 Release 的版本号；默认等于 --version。装的是 0.2.0 却想再验更新时设 0.2.1')
    ap.add_argument('--only', default='all',
                    choices=['all', 'offline', 'cancel', 'install', 'real'])
    args = ap.parse_args()

    exe = Path(args.exe).resolve()
    asset = Path(args.asset).resolve()
    if not exe.exists():
        print(f'✗ 找不到 {exe}')
        return 2
    if not asset.exists():
        print(f'✗ 找不到 {asset}')
        return 2
    if _tasklist('Cairn.exe'):
        print('✗ 已经有一个 Cairn 在跑，先退掉')
        return 2

    if not args.fake_version:
        args.fake_version = args.version
    srv, api = start_fake_github(asset, args.fake_version)
    print(f'本地假 GitHub：{api}   载荷 {asset.name}（{asset.stat().st_size:,} B）')
    try:
        if args.only in ('all', 'offline'):
            scenario_offline(exe)
        if args.only in ('all', 'cancel'):
            scenario_cancel(exe, api, args.fake_version)
        if args.only in ('all', 'install'):
            scenario_install(exe, api, asset, args.fake_version)
        if args.only in ('all', 'real'):
            scenario_real(exe, args.version)
    finally:
        srv.shutdown()

    bad = [r for r in RESULTS if not r[0]]
    print(f'\n{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
