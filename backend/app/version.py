"""版本元数据（T8.6）：关于页与更新器唯一的比较基准。

**为什么版本号放在这个 .py 里，不读 `pyproject.toml`**：冻结包里没有 `pyproject.toml`
（它不参与打包），运行期去读只会得到 FileNotFoundError。所以这里是一份**源码里的常量**，
由 `tools/bump_version.py` 与 `pyproject.toml` / 两个 `package.json` 一起改（`--check` 会核对四处一致）。

**为什么 `commit` / `built_at` 不用环境变量**：M6 阶段 `health.py` 读的是
`CAIRN_COMMIT` / `CAIRN_BUILT_AT`，但环境变量只活在**构建机执行那条命令的进程里**——
用户双击 `Cairn.exe` 时它根本不存在，装机版的关于页会永远显示"源码运行"。
现在改成构建时写进 `app/_build_info.py`（`cairn-backend.spec` 在 Analysis 之前生成，
gitignored），随包带走；源码直跑没有这个文件，如实返回 `None`，不编造。
"""
from __future__ import annotations

import sys

# 唯一真源。改版本号请用 `python tools/bump_version.py --to X.Y.Z`，别只手改这里。
VERSION = "0.2.0"


def _build_info() -> tuple[str, str]:
    """构建时戳：没有就返回空串（源码直跑的正常状态）。

    `sys.frozen` 这一层判断不是防呆：`_build_info.py` 是**打包产物**，打完包会留在
    源码树里（gitignored）。不看 frozen 的话，之后每次 `uv run python` 都会拿着
    上一次打包的提交号与时间说"这是这个进程的构建信息"—— 源码运行反而变成最不诚实的那种。
    """
    if not getattr(sys, 'frozen', False):
        return "", ""
    try:
        from app import _build_info as bi  # noqa: PLC0415 - 构建产物可能不存在
    except Exception:  # noqa: BLE001 - 任何 import 失败都等价于"没有"
        return "", ""
    return str(getattr(bi, "COMMIT", "") or ""), str(getattr(bi, "BUILT_AT", "") or "")


def info() -> dict:
    """`GET /api/version` 的响应体。

    空串统一转 `None`：接口契约写的是"取不到就返回 null"，前端据此显示"源码运行"，
    而不是把一个空串当版本号渲染出来。
    """
    commit, built_at = _build_info()
    return {
        "version": VERSION,
        "commit": commit.strip() or None,
        "built_at": built_at.strip() or None,
    }
