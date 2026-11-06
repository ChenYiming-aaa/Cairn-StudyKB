"""视频转录 adapter（T2.6）：yt-dlp 取元数据 → 下音频 → faster-whisper 识别。

约束（M2 §1.1 的同一条理由）：路由与 service 都不许直接 import yt_dlp / faster_whisper，
一律走 `BaseTranscriber`，换平台或换识别引擎只改实现类。

四个阶段与进度区间照 M2 §6.3：
`metadata` 0–5 → `downloading` 5–30 → `transcribing` 30–95（由调用方 saving 95–100）。

为什么没有 torch：faster-whisper 走 ctranslate2，本机没装 torch 也能用；
因此 `_cuda_ok()` 判的是 ctranslate2，**不是** `torch.cuda.is_available()`（M2 §6.3 的坑）。
"""
from __future__ import annotations

import logging
import shutil
import threading
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import ctranslate2
import numpy as np
from faster_whisper import WhisperModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from app.config import get_settings
from app.services import subtitles
from app.services.fetch_errors import FetchError

log = logging.getLogger(__name__)

# 阶段名与进度区间（T2.7 契约：stage 四阶段之一）
STAGE_METADATA = "metadata"
STAGE_DOWNLOAD = "downloading"
STAGE_TRANSCRIBE = "transcribing"

P_META_DONE = 5
P_DOWNLOAD_DONE = 30
P_TRANSCRIBE_DONE = 95
MODEL_CHOICES = ("tiny", "base", "small", "medium", "large-v3")
DEFAULT_MODEL = "small"
DEFAULT_LANGUAGE = "zh"
SAMPLE_RATE = 16000            # whisper 只吃 16k 单声道 float32

# on_progress(progress, stage)
ProgressFn = Callable[[int, str], None]


@dataclass(frozen=True)
class Transcript:
    """一次成功转录的结果。`text` 已是带 `[mm:ss]` 时间戳的纯文本。"""

    url: str
    title: str
    text: str
    duration: float          # 秒；未知时为 0
    language: str            # 实际识别语言（auto 时为检测结果）
    segment_count: int
    source: str = "asr"      # asr = 语音识别；subtitle = 现成字幕


class BaseTranscriber(ABC):
    @abstractmethod
    def transcribe(self, url: str, on_progress: ProgressFn | None = None) -> Transcript:
        """下载并识别；失败一律抛 FetchError（code 为 TRANSCRIBE_*）。"""


# ── 工具函数 ────────────────────────────────────────────────


def models_dir() -> Path:
    """模型放 data/models/whisper（M2 §6.3：不要放用户缓存目录，卸载重装会丢）。"""
    return get_settings().data_dir / "models" / "whisper"


def tmp_root() -> Path:
    return get_settings().data_dir / "tmp"


def clear_tmp() -> int:
    """启动时清空 data/tmp（M2 §7：大文件把磁盘塞满的兜底）。返回删掉的目录数。"""
    root = tmp_root()
    if not root.exists():
        return 0
    removed = 0
    for child in root.iterdir():
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
            removed += 1
        except OSError as exc:               # 占用中的文件跳过，不阻塞启动
            log.warning("清理临时文件失败 %s（%s）", child.name, type(exc).__name__)
    return removed


def format_ts(seconds: float) -> str:
    """秒 → `mm:ss`；超过 1 小时用 `h:mm:ss`。"""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def read_wav(path: Path) -> np.ndarray:
    """把 16k 单声道 16bit 的 wav 读成 float32 数组，交给 faster-whisper。

    为什么不 `model.transcribe(str(path))` 让它自己解码：faster-whisper 1.2.1 的
    `decode_audio` 会调 `av.open(metadata_errors=...)`，而 PyAV 19 已删掉该参数
    → 直接 TypeError（本机实测）。我们本来就是 ffmpeg 转出来的固定格式，
    用标准库 wave 解码既没有版本耦合，也少一次 PyAV 的重采样。
    格式不符时报错而不是硬读：错采样率会让识别结果是乱的，静默降级更难查。
    """
    with wave.open(str(path), "rb") as fp:
        channels, width = fp.getnchannels(), fp.getsampwidth()
        rate, frames = fp.getframerate(), fp.getnframes()
        raw = fp.readframes(frames)

    if channels != 1 or rate != SAMPLE_RATE or width != 2:
        raise FetchError(
            "TRANSCRIBE_MODEL_FAIL",
            detail=f"wav 格式不符：ch={channels} rate={rate} width={width}",
        )
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _cuda_ok() -> bool:
    """ctranslate2 能不能用 CUDA float16。

    只是**便宜的预判**：真跑起来仍可能在加载时报 cuDNN 版本不匹配（M2 §7 第 3 行），
    所以 `_load_model` 还包了一层 try/except 回落 CPU。不要只信这个函数。
    """
    try:
        if ctranslate2.get_cuda_device_count() < 1:
            return False
        return "float16" in ctranslate2.get_supported_compute_types("cuda")
    except Exception as exc:                  # noqa: BLE001 - 探测失败即视为不可用
        log.warning("CUDA 探测失败（%s），回落 CPU", type(exc).__name__)
        return False


_model_cache: dict[str, WhisperModel] = {}
_model_lock = threading.Lock()                # 同一模型不可被两个任务并发使用
_load_lock = threading.Lock()


def _load_model(size: str) -> WhisperModel:
    """按 size 缓存模型；CUDA 建不起来就回落 CPU int8（M2 §7 排障表）。"""
    with _load_lock:
        cached = _model_cache.get(size)
        if cached is not None:
            return cached

        root = models_dir()
        root.mkdir(parents=True, exist_ok=True)
        attempts = [("cuda", "float16")] if _cuda_ok() else []
        attempts.append(("cpu", "int8"))

        last_exc: Exception | None = None
        for device, compute in attempts:
            try:
                model = WhisperModel(
                    size, device=device, compute_type=compute, download_root=str(root)
                )
            except Exception as exc:          # noqa: BLE001 - cudnn 缺失等情况统一回落
                last_exc = exc
                log.warning(
                    "whisper 模型 %s 在 %s/%s 上加载失败（%s），继续尝试下一档",
                    size, device, compute, type(exc).__name__,
                )
                continue
            # 首次使用会下载模型（约 500MB），日志里留痕便于排障
            log.info("whisper 模型 %s 就绪：%s/%s，目录 %s", size, device, compute, root)
            _model_cache[size] = model
            return model

        raise FetchError(
            "TRANSCRIBE_MODEL_FAIL",
            detail=f"{type(last_exc).__name__}: {str(last_exc)[:200]}" if last_exc else "",
        ) from last_exc


def _classify_ytdlp_error(exc: DownloadError) -> FetchError:
    """yt-dlp 的异常只有字符串，只能按关键字分类（M2 §7 第 2/6 行）。

    顺序有讲究：先判"要不要登录"，再判"页面没了"，最后才判无音轨 ——
    403 的错误串里也可能出现 format 相关字样，顺序反了会误报成 NO_AUDIO。
    """
    text = str(exc).lower()
    if "unsupported url" in text:
        return FetchError("TRANSCRIBE_UNSUPPORTED", detail="unsupported url")
    if any(k in text for k in ("sign in", "login", "private video", "http error 403",
                               "http error 401", "members-only", "需要登录")):
        return FetchError("TRANSCRIBE_BLOCKED", detail=str(exc)[:200])
    if any(k in text for k in ("http error 404", "http error 410", "not found")):
        return FetchError("TRANSCRIBE_NOT_FOUND", detail=str(exc)[:200])
    if any(k in text for k in ("no audio", "unable to obtain file audio codec",
                               "requested format is not available")):
        return FetchError("TRANSCRIBE_NO_AUDIO", detail=str(exc)[:200])
    return FetchError("TRANSCRIBE_YTDLP_FAIL", detail=str(exc)[:200])


class _YdlLogger:
    """把 yt-dlp 的输出收进本项目的 logger。

    不接管的话它会直接往 stderr 打 `ERROR:` 与 `[download]` 行，
    既污染控制台，也绕过了按天滚动的日志文件（红线 8 要求失败可追）。
    """

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            log.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        log.info("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.error("yt-dlp: %s", msg)


def _has_audio(info: dict) -> bool:
    """元数据阶段就能判掉「无音轨视频」，省掉一次下载（DoD 要求独立错误码）。

    只认明确的 `acodec == "none"`：直链站点（generic extractor）返回的 acodec 是 `None`
    即"未知"，不能当"没有"——那样所有直链视频都会被误判成无音轨。
    真有音轨缺失的情况，下载阶段拿不到 wav 时还会再兜一次。
    """
    formats = info.get("formats") or []
    codecs = [(f.get("acodec") or "").lower() for f in formats]
    known = [c for c in codecs if c]
    if not known:
        return True
    return not all(c == "none" for c in known)


class YtDlpWhisperTranscriber(BaseTranscriber):
    """默认实现：yt-dlp 下 wav + faster-whisper 识别。同步阻塞，跑在线程池里。"""

    def __init__(self, model: str = DEFAULT_MODEL, language: str = DEFAULT_LANGUAGE):
        self.model_size = model if model in MODEL_CHOICES else DEFAULT_MODEL
        self.language = language or DEFAULT_LANGUAGE

    # ── 对外入口 ────────────────────────────────────────────
    def transcribe(self, url: str, on_progress: ProgressFn | None = None) -> Transcript:
        report = on_progress or (lambda *_: None)
        work = tmp_root()
        work.mkdir(parents=True, exist_ok=True)
        # 每个任务一个独立子目录，finally 里整个删掉（M2 §7 最后一行）
        tmp = Path(self._mkdtemp(work))
        try:
            report(0, STAGE_METADATA)
            title, duration, info = self._metadata(url, report)

            # ① 先看有没有现成字幕。「有就用、没有就转」，字幕链任何异常都只是降级
            hit = self._try_subtitles(info)
            if hit is not None:
                text, lang, count = hit
                report(P_TRANSCRIBE_DONE, STAGE_TRANSCRIBE)
                return Transcript(url=url, title=title, text=text, duration=duration,
                                  language=lang, segment_count=count, source="subtitle")

            # ② 没字幕才需要音轨（放这里而不是 _metadata：无音轨+有字幕的视频也该能入库）
            if not _has_audio(info):
                raise FetchError("TRANSCRIBE_NO_AUDIO", detail="元数据里所有 format 的 acodec=none")

            report(P_META_DONE, STAGE_DOWNLOAD)
            wav = self._download(url, tmp, report)
            report(P_DOWNLOAD_DONE, STAGE_TRANSCRIBE)
            text, detected, segments, real_duration = self._transcribe(wav, duration, report)
            if not text.strip():
                raise FetchError("TRANSCRIBE_EMPTY", detail="0 段语音")
            return Transcript(url=url, title=title, text=text,
                              duration=real_duration or duration,
                              language=detected, segment_count=segments)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _try_subtitles(info: dict) -> tuple[str, str, int] | None:
        """取现成字幕；没有/拿不到/解析为空一律返回 None，让调用方回去跑 ASR。

        这里**不抛异常**：字幕是优化项，它的失败不该影响采集结果。
        """
        track = subtitles.pick(info)
        if track is None:
            return None
        try:
            cues = subtitles.fetch(track)
        except Exception as exc:          # noqa: BLE001 - 网络/格式/鉴权都可能
            log.info("字幕不可用，回退语音识别（%s）", type(exc).__name__)
            return None
        if not cues:
            return None
        lines = [f"[{format_ts(start)}] {text}" for start, text in cues]
        return "\n".join(lines), track.lang, len(cues)

    # ── 阶段一：元数据 ──────────────────────────────────────
    def _metadata(self, url: str, report: ProgressFn) -> tuple[str, float, dict]:
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                "logger": _YdlLogger(),
                "socket_timeout": 30, "retries": 2, **_cookies_opts(), **_ffmpeg_opts()}
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except DownloadError as exc:
            raise _classify_ytdlp_error(exc) from exc
        except Exception as exc:              # noqa: BLE001 - 统一成 T2.7 契约里的码
            raise FetchError("TRANSCRIBE_YTDLP_FAIL", detail=type(exc).__name__) from exc

        if not isinstance(info, dict):
            raise FetchError("TRANSCRIBE_YTDLP_FAIL", detail="extract_info 未返回字典")
        if info.get("_type") == "playlist":
            # noplaylist 已尽力，仍拿到播放列表说明该链接本身是合集：不做，明确拒绝
            raise FetchError("TRANSCRIBE_UNSUPPORTED", detail="播放列表链接")

        raw_title = (info.get("title") or "").strip() or "未命名视频"
        title = raw_title[:100]
        duration = float(info.get("duration") or 0)
        report(P_META_DONE // 2, STAGE_METADATA)
        return title, duration, info

    # ── 阶段二：下载音频 ────────────────────────────────────
    def _download(self, url: str, tmp: Path, report: ProgressFn) -> Path:
        last = [-1]

        def hook(d: dict) -> None:
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            if not total:
                return
            pct = min(100.0, got / total * 100)
            # 5–30 区间；每变 1% 才回调，最后的 30 由调用方补
            value = P_META_DONE + int(pct * (P_DOWNLOAD_DONE - P_META_DONE) / 100)
            if value != last[0]:
                last[0] = value
                report(value, STAGE_DOWNLOAD)

        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(tmp / "%(id)s.%(ext)s"),
            "quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
            "logger": _YdlLogger(),
            "socket_timeout": 30, "retries": 2,
            "progress_hooks": [hook],
            "postprocessors": [{"key": "FFmpegExtractAudio",
                                "preferredcodec": "wav", "preferredquality": "16"}],
            # 固定输出 16k 单声道 16bit：read_wav 只认这个格式（见其 docstring）
            "postprocessor_args": {"extractaudio": ["-ar", str(SAMPLE_RATE), "-ac", "1",
                                                    "-c:a", "pcm_s16le"]},
            **_ffmpeg_opts(),
        }
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
        except DownloadError as exc:
            raise _classify_ytdlp_error(exc) from exc
        except Exception as exc:              # noqa: BLE001
            raise FetchError("TRANSCRIBE_YTDLP_FAIL", detail=type(exc).__name__) from exc

        wavs = sorted(tmp.glob("*.wav"))
        if not wavs:
            # 下到了文件但没能抽出音轨：多半是源本身没有音频流
            raise FetchError("TRANSCRIBE_NO_AUDIO", detail="postprocess 后无 wav 产出")
        return wavs[0]

    # ── 阶段三：识别 ────────────────────────────────────────
    def _transcribe(
        self, wav: Path, hint_duration: float, report: ProgressFn
    ) -> tuple[str, str, int, float]:
        model = _load_model(self.model_size)
        span = P_TRANSCRIBE_DONE - P_DOWNLOAD_DONE
        audio = read_wav(wav)

        with _model_lock:                     # 同一模型不并发
            try:
                segments, info = model.transcribe(
                    audio, language=self.language or None,
                    vad_filter=True, beam_size=5,
                )
                duration = float(getattr(info, "duration", 0) or hint_duration or 0)
                detected = getattr(info, "language", "") or (self.language or "")

                lines: list[str] = []
                count = 0
                for seg in segments:          # 生成器：边转边回报
                    count += 1
                    if duration > 0:
                        value = P_DOWNLOAD_DONE + int(min(1.0, seg.end / duration) * span)
                        report(value, STAGE_TRANSCRIBE)
                    lines.append(f"[{format_ts(seg.start)}] {seg.text.strip()}")
            except FetchError:
                raise
            except Exception as exc:          # noqa: BLE001 - 模型/音频层面的失败
                raise FetchError(
                    "TRANSCRIBE_MODEL_FAIL", detail=f"{type(exc).__name__}: {str(exc)[:200]}"
                ) from exc

        report(P_TRANSCRIBE_DONE, STAGE_TRANSCRIBE)
        return "\n".join(lines), detected, count, duration

    @staticmethod
    def _mkdtemp(root: Path) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="whisper-", dir=str(root))


def _ffmpeg_opts() -> dict:
    """把 Settings.ffmpeg_exe 的绝对路径交给 yt-dlp（M2 §7 第一行：PATH 里可能没有）。"""
    cfg = get_settings()
    exe = cfg.ffmpeg_exe
    return {"ffmpeg_location": str(exe)} if exe else {}


def _cookies_opts() -> dict:
    """可选的 cookies.txt：B 站字幕与会员视频要靠它，没配就按未登录处理。

    用文件而不是 `cookiesfrombrowser`：后者在浏览器运行时读不到库
    （Windows 下 Edge 的 cookie 库被锁、Chrome 的 DPAPI 解不开，2026-11-06 实测）。
    """
    path = get_settings().ytdlp_cookies.strip()
    return {"cookiefile": path} if path and Path(path).exists() else {}


_default_transcriber: BaseTranscriber | None = None


def get_transcriber() -> BaseTranscriber:
    global _default_transcriber
    if _default_transcriber is None:
        _default_transcriber = YtDlpWhisperTranscriber()
    return _default_transcriber


def set_transcriber(transcriber: BaseTranscriber | None) -> None:
    """给 verify 脚本注入假实现（T2.10：不打真实视频站点）。"""
    global _default_transcriber
    _default_transcriber = transcriber
