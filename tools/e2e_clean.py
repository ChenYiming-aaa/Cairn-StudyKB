#!/usr/bin/env python3
"""T8.8 干净机走查（可自动化那一半）。

T8.8 要求「一台没有 Python / Node 的干净机器：装 → 首启 → 只装 embed → 问一个语义问题
（应命中）→ 卸载 embed → 再问（应降级且不崩）→ 检查更新」。手头没有第二台机器，只能
**在本机模拟干净环境**：已装目录整份复制到临时目录，用户数据目录指到全新目录
（`--user-data-dir`，壳会把它当 `--data-dir` 传下去），PATH 削到只剩 `System32` ——
被测进程既看不到源码树，也找不到任何 Python / Node。

测的是真东西：组件包从 GitHub 真下（262 MB）、模型真下（~92 MB）、问答真调模型，
所以不在 `verify_m8.py` 里跑，跟 `e2e_update.py` 同一类"发布前手工跑一次"的工具。

    python tools/e2e_clean.py --src "D:/知识库/Cairn" --work "D:/cairn-t88" [--keep-install]

前置：`%APPDATA%/Cairn/.env` 里有可用的模型 Key（脚本只复制，不读取、不打印内容）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RESULTS: list[tuple[bool, str, str]] = []
CLEAN_PATH = r'C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem'
EXPECTED = '0.2.1'          # 走查针对的版本；发新版时改这一处


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((bool(ok), name, detail))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail else ''), flush=True)


def step(title: str) -> None:
    print(f'\n── {title} ' + '─' * max(0, 46 - len(title)), flush=True)


# ── HTTP（直接打后端，不绕界面；端口从窗口 URL 拿）────────────
def api(base: str, method: str, path: str, body: dict | None = None,
        timeout: float = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, text = resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:          # 4xx/5xx 也要能读到错误码
        status, text = exc.code, exc.read().decode('utf-8', 'replace')
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {'_raw': text}
    payload['_status'] = status
    return payload


def api_sse(base: str, path: str, body: dict, timeout: float = 180) -> list[dict]:
    """读完整条 SSE（`/api/ask` 是流式的，读到底才算完）。"""
    events: list[dict] = []
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode('utf-8', 'replace').strip()
            if not line.startswith('data: '):
                continue
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return events


# ── 进程与 CDP ─────────────────────────────────────────────
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return int(s.getsockname()[1])


def _tasklist(name: str) -> int:
    out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}', '/NH'],
                         capture_output=True, text=True, encoding='gbk', errors='replace').stdout
    return out.count(name)


def launch(exe: Path, userdata: Path, cdp_port: int) -> subprocess.Popen:
    env = {**os.environ}
    env.pop('ELECTRON_RUN_AS_NODE', None)   # 会让打包 exe 退化成纯 Node，且不写日志
    env['PATH'] = CLEAN_PATH                # 模拟"这台机器没装 Python / Node"
    env.pop('DATA_DIR', None)
    proc = subprocess.Popen(
        [str(exe), f'--remote-debugging-port={cdp_port}', f'--user-data-dir={userdata}'],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def wait_page(port: int, timeout: float = 90) -> str:
    """等窗口页面出现，返回它的 URL（后端端口就在里面）。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=1) as r:
                targets = json.load(r)
            for t in targets:
                url = str(t.get('url', ''))
                if t.get('type') == 'page' and url.startswith('http://127.0.0.1'):
                    return url
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError(f'{timeout}s 内没等到应用窗口页面')


def quit_app(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(2)


# ── 走查 ───────────────────────────────────────────────────
SEED = ('间隔重复是一种把复习安排在遗忘发生之前的记忆方法。艾宾浩斯遗忘曲线表明，新学的内容在'
        '最初两天里掉得最快，之后逐渐变缓。因此合理的做法是在快要忘的时候再看一遍，而不是等彻底'
        '忘光了重新学。每一轮间隔可以按 1 天、2 天、4 天、7 天递推，答错的条目回到更短的间隔。')
PARAPHRASE = '怎样安排温习的节奏才不容易忘干净'


def poll_install(base: str, cid: str, timeout: float = 1800) -> dict:
    end, last = time.time() + timeout, ''
    while time.time() < end:
        st = api(base, 'GET', f'/api/components/{cid}/progress')
        line = f"{st.get('status')} {st.get('pct')}%"
        if line != last:
            print(f'    {cid}: {line}', flush=True)
            last = line
        if st.get('status') in ('installed', 'done', 'failed', 'cancelled'):
            return st
        time.sleep(3)
    return {'status': 'timeout'}


def wait_vectors(base: str, timeout: float = 300) -> float:
    """等后台的「全库补向量」跑完（首次还要下 92 MB 模型），返回等了多少秒。

    装完那一刻向量还没有：补向量是异步任务，模型也要现下。真人在这段时间里
    看到的是「向量不可用，已降级为全文检索」——不算错，但必须**自己恢复**。
    """
    started = time.time()
    while time.time() - started < timeout:
        got = api(base, 'GET', '/api/search?q=' + urllib.parse.quote(PARAPHRASE))
        if any(i.get('match_type') == 'vector' for i in got.get('items', [])):
            break
        time.sleep(5)
    return time.time() - started


def run_checks(base: str, keep_install: bool) -> None:
    step('① 首启：窗口、版本、组件清单')
    health = api(base, 'GET', '/api/health')
    check('后端握手成功（窗口能起来就不是白屏）', health.get('_status') == 200,
          f"HTTP {health.get('_status')}")
    ver = api(base, 'GET', '/api/version')
    check(f'版本是 {EXPECTED}', ver.get('version') == EXPECTED, str(ver.get('version')))
    check('装机版有提交号（不是"源码运行"）',
          bool(ver.get('commit')) and ver.get('commit') != 'unknown', str(ver.get('commit')))

    comps = api(base, 'GET', '/api/components')
    items = {c.get('id'): c for c in comps.get('items', [])}
    check('三个组件都在清单里', len(items) == 3, ','.join(sorted(items)))
    check('干净机器上 embed 是「没装」而不是误判成 local',
          items.get('embed', {}).get('mode') != 'local', f"mode={items.get('embed', {}).get('mode')}")
    check('三个组件初始都没有装',
          all(c.get('state') == 'missing' for c in items.values()),
          str({k: v.get('state') for k, v in items.items()}))

    step('② 无组件：采集 + 检索 + 问答（必须降级、不能崩）')
    created = api(base, 'POST', '/api/knowledge', {'raw_content': SEED, 'source_type': 'text'})
    check('新建条目成功', created.get('_status') == 201, f"HTTP {created.get('_status')}")
    check('已切块', int(created.get('chunk_count') or 0) > 0, f"chunks={created.get('chunk_count')}")

    search = api(base, 'GET', '/api/search?q=' + urllib.parse.quote(PARAPHRASE))
    check('没有向量组件时检索仍返回 200（不是 500）', search.get('_status') == 200,
          f"HTTP {search.get('_status')}")
    check('降级原因如实说是「组件没装」',
          search.get('fallback') == 'vector_component_missing', str(search.get('fallback')))

    events = api_sse(base, '/api/ask', {'question': PARAPHRASE})
    kinds = [e.get('type') for e in events]
    check('没有向量组件时问答不崩（有 sources 或明确的 no_result）',
          ('sources' in kinds) or ('no_result' in kinds), ','.join(kinds[:6]))
    check('没有向量组件时报错是「要装组件」而不是别的东西',
          'error' not in kinds or any(e.get('code') == 'COMPONENT_MISSING' for e in events),
          ','.join(k for k in kinds if k == 'error') or 'no error')

    step('③ 只装 embed（真从 GitHub 下 262 MB）')
    if keep_install:
        print('    --keep-install：跳过下载，直接用已装好的', flush=True)
    else:
        started = api(base, 'POST', '/api/components/embed/install')
        check('安装接口立即返回 202', started.get('_status') == 202, f"HTTP {started.get('_status')}")
        done = poll_install(base, 'embed')
        check('embed 装完了', done.get('status') in ('installed', 'done'),
              f"{done.get('status')} {done.get('error_code') or ''}")
        if done.get('status') not in ('installed', 'done'):
            return

    comps = api(base, 'GET', '/api/components')
    embed = next((c for c in comps.get('items', []) if c.get('id') == 'embed'), {})
    check('装完状态是 installed', embed.get('state') == 'installed', str(embed.get('state')))
    check('装完 resolve 到组件进程（不是 local）', embed.get('mode') == 'component',
          str(embed.get('mode')))

    step('④ 装完 embed：语义检索 / 问答应命中')
    waited = wait_vectors(base)
    search = api(base, 'GET', '/api/search?q=' + urllib.parse.quote(PARAPHRASE))
    vec_hits = [i for i in search.get('items', []) if i.get('match_type') == 'vector']
    check('历史条目补上了向量（改写问法能靠向量命中）', bool(vec_hits),
          f'hits={len(vec_hits)}，等了 {waited:.0f}s')
    check('有向量时不再报降级', search.get('fallback') in (None, '', 'none'),
          str(search.get('fallback')))

    events = api_sse(base, '/api/ask', {'question': PARAPHRASE})
    sources = next((e.get('sources') for e in events if e.get('type') == 'sources'), None)
    answer = ''.join(e.get('text', '') for e in events if e.get('type') == 'delta')
    check('装完 embed 后问答给出引用来源', bool(sources), f'sources={len(sources or [])}')
    check('答案不是空的', len(answer.strip()) > 10, answer.strip()[:40])

    step('⑤ 卸载 embed：退回全文检索，且不崩')
    t0 = time.time()
    freed = api(base, 'DELETE', '/api/components/embed', timeout=180)
    print(f'    卸载耗时 {time.time() - t0:.1f}s', flush=True)
    check('卸载返回释放空间', int(freed.get('freed') or 0) > 0, str(freed.get('freed')))
    after = {c.get('id'): c.get('state')
             for c in api(base, 'GET', '/api/components').get('items', [])}
    check('卸载后状态回到 missing', after.get('embed') == 'missing', str(after.get('embed')))

    search = api(base, 'GET', '/api/search?q=' + urllib.parse.quote(PARAPHRASE))
    check('卸载后检索仍 200', search.get('_status') == 200, f"HTTP {search.get('_status')}")
    check('卸载后如实说明已退回全文', search.get('fallback') == 'vector_component_missing',
          str(search.get('fallback')))

    events = api_sse(base, '/api/ask', {'question': PARAPHRASE})
    kinds = [e.get('type') for e in events]
    check('卸载后问答不崩', ('sources' in kinds) or ('no_result' in kinds), ','.join(kinds[:6]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='已安装的 Cairn 目录（含 Cairn.exe）')
    ap.add_argument('--work', required=True, help='临时工作目录（会被清空重建）')
    ap.add_argument('--keep-install', action='store_true', help='跳过 262 MB 下载（复用已装的）')
    args = ap.parse_args()

    src = Path(args.src).resolve()
    work = Path(args.work).resolve()
    app_dir = work / 'app'
    userdata = work / 'userdata'
    if not (src / 'Cairn.exe').exists():
        print(f'✗ {src} 里没有 Cairn.exe')
        return 2
    if _tasklist('Cairn.exe'):
        print('✗ 已经有一个 Cairn 在跑，先退掉（干净机走查要独占）')
        return 2

    step('⓪ 准备一台"干净机"')
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    print(f'    复制 {src} → {app_dir}', flush=True)
    shutil.copytree(src, app_dir)
    (userdata / 'logs').mkdir(parents=True, exist_ok=True)
    key_src = Path(os.environ.get('APPDATA', '')) / 'Cairn' / '.env'
    if key_src.exists():
        shutil.copy2(key_src, userdata / '.env')          # 只复制，不读内容
        print('    已复制本机 .env', flush=True)
    else:
        print('    ⚠ 没找到 %APPDATA%/Cairn/.env，问答会报 LLM_NO_KEY', flush=True)
    check('干净 PATH 里既没有 python 也没有 node',
          shutil.which('python', path=CLEAN_PATH) is None
          and shutil.which('node', path=CLEAN_PATH) is None, CLEAN_PATH)

    cdp = _free_port()
    proc = launch(app_dir / 'Cairn.exe', userdata, cdp)
    try:
        url = wait_page(cdp)
        base = url.split('/', 3)[0] + '//' + url.split('/', 3)[2]
        print(f'    窗口已开：{base}（数据目录 {userdata}）', flush=True)
        check('数据目录真的落在临时目录（没碰 %APPDATA%/Cairn）',
              (userdata / 'data.db').exists(), str(userdata / 'data.db'))
        run_checks(base, args.keep_install)
    finally:
        quit_app(proc)

    step('⑥ 退出')
    time.sleep(2)
    check('退出后没有孤儿 cairn-backend.exe', _tasklist('cairn-backend.exe') == 0,
          f'count={_tasklist("cairn-backend.exe")}')

    bad = [r for r in RESULTS if not r[0]]
    print(f'\n{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS')
    for _, name, detail in bad:
        print(f'  失败：{name}  [{detail}]')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
