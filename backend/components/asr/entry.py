"""转录组件 worker（T8.0 **空实现**：只证明协议与进度事件）。

T8.2 接 `faster_whisper`：主程序用 ffmpeg 抽好 16k 单声道 wav，把**文件路径**交给组件，
组件负责加载模型、识别、回 segments。这样组件不用碰 ffmpeg，模型缓存仍落在
`<数据目录>/models/`（数据契约 §10：模型不算组件的一部分）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _protocol import OpError, main  # noqa: E402

VERSION = "0.2.0"


def transcribe(req: dict, progress) -> dict:
    path = str(req.get("path") or "")
    if not path:
        raise OpError("ASR_BAD_INPUT", "没给音频路径")
    if not Path(path).exists():
        raise OpError("ASR_BAD_INPUT", f"音频不存在：{path}")
    progress(30)
    progress(70)
    return {
        "segments": [{"start": 0.0, "end": 1.0, "text": "（空实现：还没接真模型）"}],
        "language": "zh",
        "model": "stub",
    }


def _expect(reply: dict) -> tuple[bool, str]:
    segments = reply.get("segments") or []
    if not reply.get("ok") or not segments:
        return False, f"回包形状不对：{str(reply)[:120]}"
    seg = segments[0]
    if not {"start", "end", "text"} <= set(seg):
        return False, f"segment 缺字段：{seg}"
    return True, f"transcribe ok：{len(segments)} 段，language={reply.get('language')}"


if __name__ == "__main__":
    sample_path = Path(__file__).resolve()
    sys.exit(main(
        "asr", VERSION, {"transcribe": transcribe},
        sample={"op": "transcribe", "path": str(sample_path)},
        expect=_expect,
    ))
