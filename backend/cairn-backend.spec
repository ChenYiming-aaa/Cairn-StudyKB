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

# 这些包带非 .py 资源（词表 / dll / html 模板 / 浏览器驱动），静态分析抓不到
for pkg in ('sqlite_vec', 'zhconv', 'trafilatura', 'faster_whisper', 'playwright', 'onnxruntime'):
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

# 明确不要的：装在本机但从没被 import 的重型/无关模块，能省几百 MB
excludes = [
    'tkinter', 'matplotlib', 'IPython', 'jupyter', 'pytest', 'notebook',
    'PyQt5', 'PySide2', 'PySide6', 'torch.distributed', 'torch.testing',
]

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
