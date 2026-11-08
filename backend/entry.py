"""PyInstaller 入口（T5.5 用，现在不打包）。

为什么不能直接用 `app/__main__.py` 当打包入口：
PyInstaller 会把**入口脚本所在目录**放进 `sys.path`。入口若是 `backend/app/__main__.py`，
`sys.path[0]` 就是 `backend/app/`，而 `app/__main__.py` 内部的 `from app.config import ...`
要找的是 `backend/app/` 这个包，`import app` 必然失败。放在 `backend/entry.py` 时
`sys.path[0]` 是 `backend/`，`app` 才是可导入的包。

（开发期 `uv run python -m app` 不受影响：`-m` 把 cwd 放进 `sys.path`，而且
`app/__main__.py` 传的是 app 对象给 uvicorn，不走 `"app.main:app"` 字符串导入。
两条路的入口形状统一在 `main()` 上，这里只做转接。）

入口脚本的 `__package__` 是 `None`，所以必须用绝对导入。
"""
from app.__main__ import main

if __name__ == "__main__":
    main()
