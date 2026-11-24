"""起子进程的公共规则。

后端在安装包里是**无控制台的 windowed exe**。Windows 下这种进程 spawn 控制台
程序（ffmpeg 等）时，系统会为子进程新建一个控制台窗口 —— 用户看到的就是采集
面板一开、 Transcription 一跑就闪一个 cmd 框。所有非交互子进程都要带
`creationflags=CREATE_NO_WINDOW`；交互式的（浏览器登录窗口）不在此列。
"""
from __future__ import annotations

import os

# 0x08000000 = Windows CREATE_NO_WINDOW；非 Windows 传 0 由 subprocess 忽略。
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
