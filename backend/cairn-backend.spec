# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（T5.5 / T5.6）。

入口用 `entry.py` 而不是 `app/__main__.py`：PyInstaller 会把**入口脚本所在目录**塞进
`sys.path`，入口在 `backend/` 下时 `import app` 才成立（详见 `entry.py` 的说明）。

为什么 onedir 不用 onefile（M5 §1 约束 7 / ADR-014）：
onefile 每次启动要自解压几百 MB 到临时目录，首屏必然超过 5 秒；而且自解压 + 未签名
更容易被 Defender 拦。onedir 只解压一次（其实是根本没打包成压缩），启动只受 import 影响。

三条防坑（M5 §6.4 列的前三条，都是"运行时 FileNotFoundError"）：
1. `app/templates`、`app/prompts` 必须显式 add-data，铺到 `_MEIPASS/app/` 下，
   与源码树同形，`app/paths.py:app_path()` 两边一条路；
2. `sqlite_vec` 的 `.dll`、`zhconv` 的词表、`trafilatura` 的数据文件都不是 `.py`，
   PyInstaller 的静态分析看不见，必须 collect；
3. `console=False`（windowed）后 `sys.stdout is None`，所以日志只写文件
   （`config.setup_logging` 已在冻结时跳过 console handler）。

M8（T8.1）起这份 spec 只管**基础功能**：三个重栈（向量 / 语音 / 浏览器）被
`MONOLITH_HEAVY` 剔出去，各自打在 `backend/components/<id>/` 的独立 exe 里，
由 `tools/build_components.py` 生产。改这份文件时别把它们的 collect 加回来。
"""
import pathlib

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── 运行期要读的**非 .py** 文件 ─────────────────────────────────
# 只 add-data 了 templates/prompts 是不够的：`app/db/migrate.py` 会
# `SCHEMA_FILE.read_text()` 读 `app/db/schema.sql`，PyInstaller 的静态分析只跟 import，
# 跟不到这种字符串拼出来的路径。漏了它，**全新安装第一次启动**就会
# `FileNotFoundError: _internal/app/db/schema.sql`（已装过库的机器反而看不出问题，
# 因为"数据库已是 v2，跳过建表"）。
# 所以这里按后缀收全：以后再加 .sql / .html / .md 不用回来改 spec。
DATA_SUFFIXES = {'.sql', '.html', '.md', '.txt', '.json'}
datas = [
    (str(p), str(p.parent))
    for p in pathlib.Path('app').rglob('*')
    if p.is_file() and p.suffix.lower() in DATA_SUFFIXES
]

# 这些包带非 .py 资源（词表 / dll / html 模板），静态分析抓不到。
# M8 起**只留基础包**：faster_whisper / playwright / onnxruntime 的数据文件
# 随各自组件走（`tools/build_components.py` 里逐份 collect），主包里收进来就是白占 200 MB。
for pkg in ('sqlite_vec', 'zhconv', 'trafilatura'):
    try:
        datas += collect_data_files(pkg)
    except Exception:  # noqa: BLE001 - 某个包没装时不该让整次打包失败
        pass

hiddenimports = []
for pkg in ('uvicorn', 'fastapi', 'sqlite_vec', 'zhconv'):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:  # noqa: BLE001
        pass

# ── 重栈全部挪进组件（M8 §2.4 / T8.1）─────────────────────────────────
# 下面这些包在 v0.1.0 里占了约 560 MB 解包体积（torch 一家 367 MB），而它们只在
# 特定场景用得上。M8 把它们从主包剔掉，改成 `components/<id>/` 下的独立 exe，
# 主程序通过管道对话（`app/services/components.py`）。缺了不会崩：三处降级点
# 本来就存在（`embedder.get_model` / `transcriber._load_model` / `browser` 的 try import），
# 验收见 `scripts/verify_m8.py` §1.4。
#
# **不要**顺手把 `numpy` 加进来：`transcriber.read_wav` 与 `retriever` 的精排都用它。
# `sqlite_vec` / `zhconv` / `trafilatura` / `yt_dlp` 同理，它们是基础功能。
#
# ⚠️ **torch.distributed 的历史坑跟着搬走了**：v0.1.0 曾经为了 12 MB 排除
# `torch.distributed` / `torch.testing`，结果 sentence_transformers → torch.utils.data
# 在半初始化状态下炸掉，同进程再 import torch 一律抛。现在 torch 整个不在主包里，
# 那条约束写进了 `tools/build_components.py` 的 embed 段（组件 spec 必须
# `collect_submodules('torch.distributed')`），改那边别漏。
MONOLITH_HEAVY = [
    'torch', 'transformers', 'sentence_transformers', 'scipy', 'sklearn',
    'faster_whisper', 'ctranslate2', 'av', 'onnxruntime', 'playwright', 'hf_xet',
]

# 明确不要的：装在本机但从没被 import 的重型/无关模块，能省几百 MB
excludes = [
    'tkinter', 'matplotlib', 'IPython', 'jupyter', 'pytest', 'notebook',
    'PyQt5', 'PySide2', 'PySide6',
] + MONOLITH_HEAVY

a = Analysis(
    ['entry.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# ── babel 的 locale-data 只留中英（T8.1 量体积时发现，31 MB）────────────
# 它不是我们直接用的：`trafilatura` → `courlan.filters` → `from babel import Locale`，
# 而 babel 的 hook 会把**全世界**的 locale .dat 收进来。实测 31 MB（占瘦身后解包体积的 1/4）。
# courlan 只在一个地方用 `Locale.parse()`，且外面包了 `except (TypeError, UnknownLocaleError)`，
# 缺表就是"该过滤器不生效"，不会抛。留这几个是因为 locale 解析会做别名归一
# （`zh` → `zh_Hans`，`en` → `en_US`），留少了等于把中文路径过滤功能关掉。
KEEP_LOCALE_DATA = {'root', 'en', 'en_US', 'zh', 'zh_Hans', 'zh_Hant'}
a.datas = [
    d for d in a.datas
    if not (d[0].replace('\\', '/').startswith('babel/locale-data/')
            and pathlib.Path(d[0]).stem not in KEEP_LOCALE_DATA)
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cairn-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # upx 压缩过的 exe 更容易被 Defender 误杀
    console=False,           # windowed：用户看不到黑框；出错只能看 data/logs/app.log
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='cairn-backend',
)
