"""网页渲染组件 worker（T8.0 **空实现**：只证明协议）。

T8.2 接 playwright：组件自己起浏览器（复用本机 Edge/Chrome，失败再退回自带 Chromium），
`render` 返回 `(html, 最终地址, 状态码)`。**登录助手**（可见窗口 + 5 分钟等待）也归组件，
主程序只负责把状态转发给界面 —— 窗口必须活在组件进程里，不能跨管道开。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _protocol import OpError, main  # noqa: E402

VERSION = "0.2.0"


def render(req: dict, progress) -> dict:
    url = str(req.get("url") or "")
    if not url.lower().startswith(("http://", "https://")):
        raise OpError("BROWSER_BAD_INPUT", "只接受 http(s) 地址")
    progress(60)
    return {
        "html": "<html><body><p>（空实现：还没接真浏览器）</p></body></html>",
        "final_url": url,
        "status": 200,
    }


def _expect(reply: dict) -> tuple[bool, str]:
    if not reply.get("ok") or not reply.get("html"):
        return False, f"回包形状不对：{str(reply)[:120]}"
    if not {"html", "final_url", "status"} <= set(reply):
        return False, f"缺字段：{sorted(reply)}"
    return True, f"render ok：{len(reply['html'])} 字节，status={reply['status']}"


if __name__ == "__main__":
    sys.exit(main(
        "browser", VERSION, {"render": render},
        sample={"op": "render", "url": "https://example.com/"},
        expect=_expect,
    ))
