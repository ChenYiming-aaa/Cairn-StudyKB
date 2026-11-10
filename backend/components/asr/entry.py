"""转录组件 worker（T8.2：真 faster-whisper 推理）。

分工（数据契约 §10 的延伸）：
- **主程序负责拿到 16k 单声道 wav**（yt-dlp postprocess 或 ffmpeg 抽轨），只管传路径；
- **组件负责加载模型与识别**，回 `segments`（`start` / `end` / `text`）。

这样拆的两个理由：
1. ffmpeg 已经在主包里（视频是核心功能，M8 不拆它），组件不必再带一份；
2. 模型缓存放 `<数据目录>/models/whisper`，与主程序共用 —— 装上组件时已有的模型
   立刻能用，卸载组件也不删模型（用户白等的 500 MB 不该被卸载动作干掉）。

**繁简归一不放这里**：`zhconv` 是主包依赖，主程序拿到 `segments` 后自己转（见
`app/services/transcriber.py` 的 `_transcribe_remote`）。组件包里少一个依赖就少一份体积。

**进度**：faster-whisper 的 `transcribe` 返回生成器，边转边吐 segment，用 `seg.end/duration`
折算 10–95 的百分比。协议约定"长任务每 30 秒必须有 progress"，主程序按空闲超时实现，
见 `component_proc.py` 的 `idle` 参数。
"""
from __future__ import annotations

import os
import sys
import threading
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _protocol import OpError, main  # noqa: E402

VERSION = "0.2.0"
DEFAULT_MODEL = "small"
DEFAULT_LANGUAGE = "zh"
SAMPLE_RATE = 16000
P_START = 10          # 载模型之前的进度
P_DONE = 95           # 剩下的 95–100 留给主程序"写入库"
MODEL_CHOICES = ("tiny", "base", "small", "medium", "large-v3")

_model_cache: dict[tuple[str, str], object] = {}
_load_lock = threading.Lock()      # 同一模型不并发加载
_use_lock = threading.Lock()       # 同一模型实例不并发推理


def _default_model_dir() -> Path:
    configured = os.environ.get("CAIRN_MODELS_DIR", "").strip()
    if configured:
        base = Path(configured)
    else:
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata) / "Cairn" / "models"
    return base / "whisper"


def read_wav(path: Path):
    """16k 单声道 16bit wav → float32 数组。

    与主程序 `transcriber.read_wav` 同一份规则（也同一个理由：faster-whisper 1.2.1 的
    内置解码会调 `av.open(metadata_errors=...)`，PyAV 19 已删掉该参数 → TypeError）。
    格式不符就报错，别硬读 —— 错采样率的输出是乱的，静默降级更难查。
    """
    import numpy as np

    try:
        with wave.open(str(path), "rb") as fp:
            channels, width = fp.getnchannels(), fp.getsampwidth()
            rate, frames = fp.getframerate(), fp.getnframes()
            raw = fp.readframes(frames)
    except Exception as exc:  # noqa: BLE001 - 不是 wav / 文件坏
        raise OpError("ASR_BAD_INPUT", f"读不了这个 wav（{type(exc).__name__}）") from exc

    if channels != 1 or rate != SAMPLE_RATE or width != 2:
        raise OpError("ASR_BAD_INPUT",
                      f"wav 格式不符：ch={channels} rate={rate} width={width}")
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _cuda_ok() -> bool:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return False
        return "float16" in ctranslate2.get_supported_compute_types("cuda")
    except Exception:  # noqa: BLE001 - 探测失败即视为不可用
        return False


def _load(size: str, root: Path):
    key = (size, str(root))
    with _load_lock:
        cached = _model_cache.get(key)
        if cached is not None:
            return cached
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001 - 组件包里缺 ctranslate2 / DLL 加载失败
            raise OpError("ASR_MODEL_FAIL",
                          f"临时加载 faster-whisper 失败（{type(exc).__name__}）") from exc

        root.mkdir(parents=True, exist_ok=True)
        attempts = [("cuda", "float16")] if _cuda_ok() else []
        attempts.append(("cpu", "int8"))
        last: Exception | None = None
        for device, compute in attempts:
            try:
                model = WhisperModel(size, device=device, compute_type=compute,
                                     download_root=str(root))
            except Exception as exc:  # noqa: BLE001 - cuDNN 缺失等，回落下一档
                last = exc
                continue
            _model_cache[key] = model
            return model
        raise OpError("ASR_MODEL_FAIL",
                      f"whisper 模型 {size} 加载失败（{type(last).__name__}: {str(last)[:160]}）")


def transcribe(req: dict, progress) -> dict:
    raw_path = str(req.get("path") or "")
    if not raw_path:
        raise OpError("ASR_BAD_INPUT", "没给音频路径")
    path = Path(raw_path)
    if not path.exists():
        raise OpError("ASR_BAD_INPUT", f"音频不存在：{raw_path}")

    size = str(req.get("model") or DEFAULT_MODEL)
    if size not in MODEL_CHOICES:
        size = DEFAULT_MODEL
    language = str(req.get("language") or DEFAULT_LANGUAGE)
    root = Path(req.get("model_dir") or _default_model_dir())
    hint = float(req.get("hint_duration") or 0)

    progress(2)
    audio = read_wav(path)
    progress(P_START)

    model = _load(size, root)
    progress(P_START + 2)

    out: list[dict] = []
    try:
        with _use_lock:
            segments, info = model.transcribe(
                audio, language=language or None, vad_filter=True, beam_size=5,
            )
            duration = float(getattr(info, "duration", 0) or hint or 0)
            detected = str(getattr(info, "language", "") or language)
            for seg in segments:
                out.append({"start": round(float(seg.start), 2),
                            "end": round(float(seg.end), 2),
                            "text": (seg.text or "").strip()})
                if duration > 0:
                    pct = P_START + int(min(1.0, seg.end / duration) * (P_DONE - P_START))
                    progress(pct)
    except OpError:
        raise
    except Exception as exc:  # noqa: BLE001 - 模型/音频层面的失败
        raise OpError("ASR_FAILED", f"识别失败（{type(exc).__name__}: {str(exc)[:160]}）") from exc

    if not duration:
        duration = out[-1]["end"] if out else 0.0
    progress(P_DONE)
    return {"segments": out, "language": detected, "model": size, "duration": duration}


# ── 自检 ────────────────────────────────────────────────
def _blank_wav(path: Path, seconds: float = 1.0) -> None:
    """写一段静音 wav 当自检输入。

    刻意**不用**真语音：自检要验的是"exe 起得来、ctranslate2 载得进、wav 解得出、
    生成器消费得完"，不是识别准确率。静音过 VAD 后 0 段是**预期结果**，
    所以 `_expect` 允许空 segments —— 拿一段必须靠网络下载的语音当自检素材
    反而会让"打包坏了"和"网断了"混在一起。
    """
    import numpy as np

    frames = int(SAMPLE_RATE * seconds)
    with wave.open(str(path), "wb") as fp:
        fp.setnchannels(1)
        fp.setsampwidth(2)
        fp.setframerate(SAMPLE_RATE)
        fp.writeframes(np.zeros(frames, dtype=np.int16).tobytes())


def _expect(reply: dict, elapsed: float = 0.0) -> tuple[bool, str]:
    if not reply.get("ok"):
        return False, f"回包形状不对：{str(reply)[:160]}"
    if not isinstance(reply.get("segments"), list):
        return False, f"segments 不是列表：{str(reply)[:160]}"
    if not reply.get("model"):
        return False, f"没回 model 字段：{str(reply)[:160]}"
    return True, (f"transcribe ok：{len(reply['segments'])} 段（静音输入，0 段是预期），"
                  f"language={reply.get('language')}，{elapsed:.1f}s")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import tempfile
        import time

        from _protocol import selftest

        with tempfile.TemporaryDirectory(prefix="cairn-asr-") as tmp:
            wav = Path(tmp) / "silence.wav"
            _blank_wav(wav)
            started = time.time()
            code = selftest("asr", VERSION,
                            {"op": "transcribe", "path": str(wav), "model": "tiny"},
                            lambda reply: _expect(reply, time.time() - started))
        sys.exit(code)
    sys.exit(main("asr", VERSION, {"transcribe": transcribe},
                  sample={"op": "transcribe", "path": ""}, expect=_expect))
