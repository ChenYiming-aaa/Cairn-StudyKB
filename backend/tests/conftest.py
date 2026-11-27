"""pytest 的公共夹具：把应用按「干净机」启动，任何用例都不许碰真实数据目录。

为什么必须在 import app 之前设环境变量：`config.get_settings()` 首次调用即缓存，
之后改 `os.environ` 不再生效（M1 的老问题，11 个验收脚本都在文件头做同一件事）。

`CAIRN_ENV_STRICT=1` 让配置只读环境变量：单测里绝不允许因为本机根目录有 `.env`
就真的去调模型 —— 那样「绿」取决于有没有 Key 和网速，而且会花钱。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="cairn-pytest-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["VECTOR_ENABLED"] = "0"
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ["CAIRN_NO_AUTO_ORGANIZE"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")

# 让 `import app.xxx` 走得通：pytest 的 rootdir 是 backend/，但从别处调用时（IDE）
# 不保证在当前目录
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return _TMP


@pytest.fixture()
def db(data_dir: Path):
    """一份空库（含全部迁移）。

    用例之间共用同一个 DATA_DIR，所以每个用例开始前把库删掉重建 ——
    「上一条用例留下的题」混进来，会让「只导入了 1 题」这种断言变得莫名其妙。
    """
    from app.db.conn import get_conn
    from app.db.migrate import init_db

    path = data_dir / "data.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    init_db(path)
    conn = get_conn(path)
    try:
        yield conn
    finally:
        conn.close()
