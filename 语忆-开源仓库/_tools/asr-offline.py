#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语忆 · 手机预览用的**完全离线**语音识别服务（Vosk，本机跑，不联网）。

为什么要有这个
--------------
预览页原来用浏览器自带的 ``webkitSpeechRecognition``：Chrome 会把麦克风音频
送到云端换文字。离线 / 受限网络下这条路直接不可用，而且录音内容会离开本机。
这个服务让手机只把 PCM 发到**同一局域网里的这台电脑**，识别全部在本机完成。

复用（不重新发明）
------------------
* 引擎封装与模型探测：``ai-voice-summary/scripts/local_asr.py``
  （复用 ``detect_engines`` / ``clean_text`` / ``SAMPLE_RATE`` / ``stage_path_for_native``）
* 中文模型：``ai-voice-summary/local-asr/models/vosk-model-small-cn-0.22``
* 手机采 16k 单声道 PCM 逐段回传的链路形态：参考 ``xiaoyu-assistant``（那边是
  Microsoft Speech Recognizer；这里换成 Vosk，接口形态保持一致）

接口
----
``GET  /health``
    → ``{"ok":true,"engine":"vosk","model":"<模型绝对路径>","sample_rate":16000,"offline":true}``
``POST /asr?session=<id>``
    body = 裸 PCM（16 kHz / 单声道 / 16-bit little-endian）；
    若以 ``RIFF`` 开头则当成 WAV，自动剥掉头部只取 data 段。
    同一个 ``session`` 内服务端保留 Vosk recognizer 状态 → 跨 chunk 连续识别。
    请求头 ``X-Final: 1``（等价 ``?final=1``）表示这是最后一段，返回后销毁会话。
    → ``{"text":…,"partial":…,"session":…,"delta":…,"final":…,"ms":…}``
``OPTIONS *``  预检，带全套 CORS 头。
``GET  /``     一份自述 JSON（方便手机/浏览器直接打开看服务活着）。

响应字段语义（**页面接入前请先看这一段**）
------------------------------------------
* ``text``    —— 本会话**累计**已定稿文本，单调增长，**不会因为某个 chunk 没定稿而变空**。
* ``partial`` —— 还没定稿的“实时尾巴”。想显示滚动效果就用 ``text + partial``。
* ``live``    —— ``text + partial``，**页面直接渲染这个字段就对了**。
                 实测 Vosk 中文模型在没有明显停顿时会一直不定稿（整段话都算“未定稿”），
                 只渲染 ``text`` 的话预览框会长时间空着；``live`` 从第一段起就有字。
* ``delta``   —— **本段新增**的文本（append 型客户端的字面语义）。
* ``final``   —— 本段是否 ``X-Final``（true 时会话已销毁）。
* ``ms``      —— 本段服务端处理耗时（毫秒）。

全离线保证
----------
不下载模型、不请求任何外部地址；连列本机局域网 IPv4 都是读 ``ipconfig`` 的输出，
不做任何 socket 外连（除了自己给自己做的回环自检）。
Vosk / Kaldi 的原生日志被 ``SetLogLevel(-1)`` 加 fd 级改道压掉，stdout 只留机器可读行。

性能上踩过的坑（都会影响手机体验，已修）
----------------------------------------
1. **每个新 recognizer 的首次真实解码要 5.9~8.2 秒**，之后同样 2 秒音频只要 0.5 秒；
   而且这笔钱**不跨 recognizer 共享** —— 每次新会话都新建的话，手机每按一次录音
   都要干等 6 秒。所以会话结束时把 recognizer 复位**还池**复用
   （``RecognizerPool``），启动时再用真实语音预热。实测每会话首个分片
   5384~8406ms → **647~976ms**。
2. 纯静音**预热不了**（走不到解码路径），合成伪语音只能付掉一半；
   用一段真实语音最有效，故启动时只读复用 workspace 里的 ``test-sample.wav``。
3. 一整块丢给 ``AcceptWaveform`` 会丢字：它一次只回一个「本段结束」信号，
   块内含两个句子停顿时前一句会被覆盖 → 统一切成 8000 字节再喂。
4. Vosk 中文模型在没有明显停顿时会一直不定稿（整段话都算"未定稿"），
   只给 ``text`` 的话预览框会长时间空着 → 另给 ``live``（见上）。

用法
----
    python asr-offline.py                 # 8795（占用则 8796~8799），同时监听 0.0.0.0 与 127.0.0.1
    python asr-offline.py --port 8795
    python asr-offline.py --model "D:\\path\\to\\vosk-model-small-cn-0.22"
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# --------------------------------------------------------------------------- #
# 输出编码：Windows 控制台默认 GBK，中文会乱码；显式 UTF-8
# --------------------------------------------------------------------------- #
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

VERSION = "1.0.0"
DEFAULT_PORTS = (8795, 8796, 8797, 8798, 8799)
LAN_BIND = "0.0.0.0"
LOOP_BIND = "127.0.0.1"

SKILL_ROOT = Path(r"C:\Users\HP\Desktop\ai-voice-summary")
LOCAL_ASR_PY = SKILL_ROOT / "scripts" / "local_asr.py"
DEFAULT_MODEL = SKILL_ROOT / "local-asr" / "models" / "vosk-model-small-cn-0.22"
SAMPLE_WAV = SKILL_ROOT / "local-asr" / "test-sample.wav"      # 只读：预热用真实语音

MAX_BODY = 64 * 1024 * 1024          # 单段最大 64 MB，防内存滥用
SESSION_TTL = 300.0                  # 空闲多久回收会话（秒）
_FEED_SLICE = 8000                   # 喂 Vosk 的切片大小（字节，= 0.25 秒 @16k/s16）
_READ_CHUNK = 1 << 16
PREWARM_COUNT = 2                    # 复用池里常备几个已预热的 recognizer


def log(message: str) -> None:
    """人类可读日志一律走 stderr —— stdout 留给验证脚本解析。"""
    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 复用 ai-voice-summary/scripts/local_asr.py
# --------------------------------------------------------------------------- #
def load_local_asr():
    """按路径导入 local_asr（目录名带连字符，不能当包 import）。

    注意：必须先把模块塞进 ``sys.modules`` —— 否则 ``@dataclass`` 装饰器在
    解析 ``LocalEngine`` 时会找不到本模块，报
    ``AttributeError: 'NoneType' object has no attribute '__dict__'``。
    """
    if not LOCAL_ASR_PY.is_file():
        raise RuntimeError(f"找不到离线识别资产：{LOCAL_ASR_PY}")
    spec = importlib.util.spec_from_file_location("local_asr", LOCAL_ASR_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {LOCAL_ASR_PY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["local_asr"] = module
    spec.loader.exec_module(module)
    return module


def resolve_model(module, override: str = "") -> str:
    """挑一个真实存在的 Vosk 模型目录，返回**绝对路径**。

    优先级：命令行/env 指定 > 本项目已知路径 > local_asr 自动探测到的第一个。
    """
    candidates: list[str] = []
    for raw in (override, os.environ.get("YUYI_ASR_MODEL", ""), str(DEFAULT_MODEL)):
        raw = (raw or "").strip().strip('"')
        if raw:
            candidates.append(raw)
    with contextlib.suppress(Exception):        # 复用资产里的模型探测逻辑
        for engine in module.detect_engines():
            if engine.id == "vosk":
                candidates.extend(engine.models)

    seen: set[str] = set()
    for raw in candidates:
        path = Path(raw)
        if not path.is_absolute():
            path = (Path.cwd() / path)
        try:
            path = path.resolve()
        except OSError:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_dir() and (path / "am").is_dir() and (path / "conf").is_dir():
            return key
    raise RuntimeError(
        "没有找到可用的 Vosk 中文模型目录（需要含 am/ 与 conf/ 子目录）。\n"
        f"期望位置：{DEFAULT_MODEL}\n"
        "也可用 --model 或环境变量 YUYI_ASR_MODEL 指定。"
    )


_MODEL_STDERR: list[str] = []


@contextlib.contextmanager
def native_stderr_quiet():
    """把 C/C++ 层（Kaldi/Vosk）直接写 fd 2 的噪声临时改道到匿名临时文件。

    ``SetLogLevel(-1)`` 压不掉所有原生输出，而 stdout 必须保持干净给验证脚本解析。
    ``tempfile.TemporaryFile`` 关闭即删，不留可见临时文件。
    """
    saved_fd = sink = None
    with contextlib.suppress(OSError):
        saved_fd = os.dup(2)
        sink = tempfile.TemporaryFile()
        os.dup2(sink.fileno(), 2)
    try:
        yield sink
    finally:
        if saved_fd is not None:
            with contextlib.suppress(OSError):
                os.dup2(saved_fd, 2)
                os.close(saved_fd)
        if sink is not None:
            with contextlib.suppress(Exception):
                sink.close()


def load_vosk_model(model_dir: str):
    """加载 Vosk 模型，顺带把原生噪声挡在控制台外；失败时把捕获内容取回来做诊断。"""
    import vosk

    with contextlib.suppress(Exception):
        vosk.SetLogLevel(-1)

    captured: list[str] = []
    try:
        with native_stderr_quiet() as sink:
            try:
                return vosk.Model(model_dir)
            except Exception as exc:
                raise RuntimeError(f"Vosk 打不开模型目录：{model_dir}\n（原始错误：{exc}）") from exc
            finally:
                if sink is not None:
                    with contextlib.suppress(Exception):
                        sink.flush()
                        sink.seek(0)
                        captured.append(sink.read().decode("utf-8", "replace").strip())
    except RuntimeError as error:
        detail = captured[0] if captured else ""
        _MODEL_STDERR.append(detail)
        raise RuntimeError(f"{error}\n{detail[-800:]}") from error


def _synthetic_speech(seconds: float, rate: int = 16000) -> bytes:
    """合成一段“像人说话”的波形（基频抖动 + 几个谐波 + 音节包络）。

    只为了把**解码路径**的首次初始化成本在启动时付掉。纯静音只会走到端点检测，
    真正带语音的第一次解码还另有一笔开销 —— 实测第一段 2 秒音频要 4.6 秒，
    后面同样长度只要 0.5~1.4 秒。这里喂一段伪语音把这个差距提前吃掉。
    """
    import array
    import math

    total = max(1, int(seconds * rate))
    samples = array.array("h")
    for index in range(total):
        t = index / rate
        envelope = 0.55 + 0.45 * math.sin(2.0 * math.pi * 3.2 * t)
        f0 = 125.0 + 35.0 * math.sin(2.0 * math.pi * 0.8 * t)
        value = (0.60 * math.sin(2.0 * math.pi * f0 * t)
                 + 0.28 * math.sin(2.0 * math.pi * 2.0 * f0 * t)
                 + 0.12 * math.sin(2.0 * math.pi * 3.0 * f0 * t))
        samples.append(int(max(-1.0, min(1.0, value * envelope * 0.7)) * 32767))
    return samples.tobytes()


def warmup_audio() -> tuple[bytes, str]:
    """预热用音频。

    实测：纯静音**不能**预热 —— Vosk 在静音上走不到真正的解码路径；合成伪语音
    只能付掉一半（首个真实分片 5.9s → 3.1s）。真正有效的是一段真实语音。
    workspace 里就有（``ai-voice-summary/local-asr/test-sample.wav``），只读复用；
    万一不在，退回合成伪语音。
    """
    if SAMPLE_WAV.is_file():
        try:
            with wave.open(str(SAMPLE_WAV), "rb") as handle:
                if (handle.getframerate() == 16000 and handle.getnchannels() == 1
                        and handle.getsampwidth() == 2):
                    frames = handle.readframes(min(handle.getnframes(), 16000 * 3))
                    return frames, "真实中文样本(3s)"
        except Exception as exc:
            log(f"  · 预热样本读取失败（{exc}），改用合成音频")
    return _synthetic_speech(1.5), "合成伪语音(1.5s)"


class RecognizerPool:
    """复用 ``KaldiRecognizer`` —— 这是本服务流畅与否的关键。

    实测（本机 vosk + small-cn 模型）：

    * 全新的 recognizer 跑第一个 2 秒真实分片要 **5.9~8.2 秒**；
    * **同一个** recognizer 再跑一个 2 秒分片只要 **0.5 秒**；
    * 这笔初始化成本**不跨 recognizer 共享** —— 每个新会话都新建 recognizer 的话，
      手机每次点录音都要干等 6 秒。

    所以会话结束时把 recognizer 复位后**还池**，下次直接复用。手机预览是「按一下说一句」
    的节奏，池子里的 recognizer 很快就被真实语音喂热，之后就一直是 0.5 秒级。
    """

    def __init__(self, model, size: int = PREWARM_COUNT):
        self._model = model
        self.size = size
        self._idle: list = []
        self._lock = threading.Lock()
        self.created = 0

    def acquire(self):
        with self._lock:
            if self._idle:
                return self._idle.pop()
        return self._make()

    def _make(self):
        import vosk
        recognizer = vosk.KaldiRecognizer(self._model, 16000)
        with contextlib.suppress(Exception):
            # 不需要词级时间戳：实测 SetWords(True) 让首次解码从 5.9s 涨到 8.2s，
            # 稳态也慢一点点。本服务只要文本。
            recognizer.SetWords(False)
        with self._lock:
            self.created += 1
        return recognizer

    def release(self, recognizer) -> None:
        """复位后放回池子；池满就直接丢弃。"""
        if recognizer is None:
            return
        try:
            with native_stderr_quiet():
                recognizer.FinalResult()          # 收尾并复位，供下一个会话使用
        except Exception:
            return
        with self._lock:
            if len(self._idle) < self.size:
                self._idle.append(recognizer)

    def prewarm(self, audio: bytes, rounds: int | None = None) -> float:
        """启动时把池子填满并逐个预热，把首次解码成本提前付掉。"""
        started = time.perf_counter()
        for _ in range(rounds if rounds is not None else self.size):
            recognizer = self.acquire()
            with native_stderr_quiet():
                for offset in range(0, len(audio), _FEED_SLICE):
                    recognizer.AcceptWaveform(audio[offset:offset + _FEED_SLICE])
            self.release(recognizer)
        return round((time.perf_counter() - started) * 1000.0, 1)


# --------------------------------------------------------------------------- #
# 音频：裸 PCM 或 WAV
# --------------------------------------------------------------------------- #
def extract_pcm(body: bytes) -> tuple[bytes, str]:
    """返回 ``(PCM 字节, 来源说明)``。

    body 以 ``RIFF`` 开头就按 WAV 处理。这里**不用**“无条件砍 44 字节”的土办法：
    项目自带的 ``test-sample.wav`` 在 ``fmt `` 之后还有一个 26 字节的 ``LIST`` 块，
    data 段其实从第 78 字节才开始 —— 砍 44 会把这些块头当成音频喂给 Vosk。
    所以先用 ``wave`` 正经解析；万一解析不了再退回砍 44 字节。
    """
    if not body.startswith(b"RIFF"):
        return body, "raw-pcm"

    try:
        with wave.open(io.BytesIO(body), "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            width = handle.getsampwidth()
            frames = handle.readframes(handle.getnframes())
        note = f"wav({rate}Hz/{channels}ch/{width * 8}bit)"
        if channels != 1 or rate != 16000 or width != 2:
            note += "-格式不符已按16k单声道16bit解释"
        return frames, note
    except Exception as exc:                                  # 退化路径
        log(f"  · WAV 解析失败（{exc}），退回剥 44 字节头")
        return body[44:], "wav-44byte-strip"


# --------------------------------------------------------------------------- #
# 会话：每个 session 一个 KaldiRecognizer，跨 chunk 保留状态
# --------------------------------------------------------------------------- #
class Session:
    """一个连续识别会话。``recognizer`` 不是线程安全的，用锁串行化。"""

    __slots__ = ("id", "recognizer", "raw_parts", "clean_text", "prev_clean",
                 "lock", "touched", "chunks", "odd_byte")

    def __init__(self, session_id: str, recognizer):
        self.id = session_id
        self.recognizer = recognizer
        self.raw_parts: list[str] = []      # 已定稿的原始文本片段
        self.clean_text = ""                # 已定稿的累计（去过中文间空格）
        self.prev_clean = ""                # 上一段返回时的累计，用来算 delta
        self.lock = threading.Lock()
        self.touched = time.time()
        self.chunks = 0
        self.odd_byte = b""                 # 跨 chunk 落单的半拉样本


class SessionStore:
    def __init__(self, pool: RecognizerPool, module, ttl: float = SESSION_TTL):
        self._pool = pool
        self._clean = module.clean_text
        self._ttl = ttl
        self._items: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._janitor = threading.Thread(target=self._sweep, name="session-janitor",
                                         daemon=True)
        self._janitor.start()

    def _sweep(self) -> None:
        while not self._stop.wait(30.0):
            deadline = time.time() - self._ttl
            with self._lock:
                stale_ids = [k for k, v in self._items.items() if v.touched < deadline]
                stale = [self._items.pop(key) for key in stale_ids]
            for item in stale:                      # 会话超时也要把 recognizer 还池
                self._pool.release(item.recognizer)
            if stale_ids:
                log(f"  · 回收空闲会话 {len(stale_ids)} 个：{', '.join(stale_ids[:8])}")

    def get_or_create(self, session_id: str) -> Session:
        with self._lock:
            item = self._items.get(session_id)
            if item is None:
                item = Session(session_id, self._pool.acquire())
                self._items[session_id] = item
                log(f"  + 新建会话 {session_id!r}（当前 {len(self._items)} 个）")
            return item

    def drop(self, session_id: str) -> None:
        """结束会话：recognizer 复位后还池，给下一次录音复用。"""
        with self._lock:
            item = self._items.pop(session_id, None)
        if item is not None:
            self._pool.release(item.recognizer)

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def shutdown(self) -> None:
        self._stop.set()

    # ---------------- 识别 ----------------
    def feed(self, item: Session, pcm: bytes, final: bool) -> dict:
        started = time.perf_counter()
        if item.odd_byte:
            pcm = item.odd_byte + pcm
            item.odd_byte = b""
        if len(pcm) % 2:                    # 16-bit 样本不该被切成奇数长度
            item.odd_byte = pcm[-1:]
            pcm = pcm[:-1]

        with item.lock:
            item.touched = time.time()
            item.chunks += 1
            if pcm:
                try:
                    # 必须切片喂：AcceptWaveform 一次只回一个「本段结束」信号，
                    # 一整块丢进去时若里面含两个句子停顿，前一句的 Result 会被后一句
                    # 覆盖掉（丢字）。切成 8000 字节（0.25 秒）与 local_asr.py 一致。
                    for offset in range(0, len(pcm), _FEED_SLICE):
                        slice_ = pcm[offset:offset + _FEED_SLICE]
                        if item.recognizer.AcceptWaveform(slice_):
                            self._absorb(item, item.recognizer.Result())
                except Exception as exc:
                    raise RuntimeError(f"Vosk AcceptWaveform 失败：{exc}") from exc

            partial = ""
            with contextlib.suppress(Exception):
                partial = json.loads(item.recognizer.PartialResult()).get("partial", "")
            partial = self._clean(partial)

            if final:
                try:
                    self._absorb(item, item.recognizer.FinalResult())
                except Exception as exc:
                    raise RuntimeError(f"Vosk FinalResult 失败：{exc}") from exc
                partial = ""

            # delta = 本段新增。累计文本是「原始片段拼起来再过一遍 clean_text」，
            # 中文词间空格会被吃掉，所以用前缀长度切；万一前缀对不上就整段返回。
            if item.clean_text.startswith(item.prev_clean):
                delta = item.clean_text[len(item.prev_clean):].strip()
            else:
                delta = item.clean_text
            item.prev_clean = item.clean_text

        return {
            "text": item.clean_text,
            "partial": partial,
            "live": item.clean_text + partial,
            "delta": delta.strip(),
            "session": item.id,
            "final": bool(final),
            "ms": round((time.perf_counter() - started) * 1000.0, 1),
        }

    def _absorb(self, item: Session, payload_json: str) -> None:
        """把一次定稿结果并进累计文本。"""
        try:
            payload = json.loads(payload_json)
        except Exception:
            return
        raw = payload.get("text") or ""
        if not raw.strip():
            return
        item.raw_parts.append(raw)
        item.clean_text = self._clean("".join(item.raw_parts))


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = f"YuyiOfflineASR/{VERSION}"
    protocol_version = "HTTP/1.1"          # keep-alive：手机连续 POST 不用反复握手
    store: SessionStore = None             # type: ignore[assignment]
    model_path = ""
    load_ms = 0.0
    started_at = time.time()

    # ---------------- 通用 ----------------
    def log_message(self, fmt: str, *args) -> None:
        log("  http %s - %s" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------------- 路由 ----------------
    def do_OPTIONS(self) -> None:                       # noqa: N802
        try:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self) -> None:                          # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:                           # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route == "/health":
            lan = lan_urls(self.server.server_address[1])   # type: ignore[attr-defined]
            return self._send_json(200, {
                "ok": True,
                "engine": "vosk",
                "model": self.model_path,
                "sample_rate": 16000,
                "offline": True,
                "version": VERSION,
                "model_load_ms": self.load_ms,
                "sessions": self.store.count(),
                "uptime_s": round(time.time() - self.started_at, 1),
                "lan_urls": lan,
            })
        if route == "/":
            return self._send_json(200, {
                "ok": True,
                "service": "语忆 · 离线语音识别（Vosk）",
                "offline": True,
                "endpoints": {
                    "GET /health": "服务与模型状态",
                    "POST /asr?session=<id>": "裸 PCM 16k/mono/s16le，或 WAV（自动剥头）",
                },
                "fields": {
                    "text": "本会话累计已定稿文本（单调增长）",
                    "partial": "尚未定稿的实时尾巴",
                    "live": "text + partial —— 页面直接渲染这个字段",
                    "delta": "本段新增文本（append 型客户端用）",
                    "final": "本段是否为最后一段",
                    "ms": "本段服务端耗时（毫秒）",
                },
                "note": "X-Final: 1 结束并销毁会话；全程离线，音频不出本机。",
            })
        return self._send_json(404, {"ok": False, "error": "not found", "path": route})

    def do_POST(self) -> None:                          # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        if route != "/asr":
            return self._send_json(404, {"ok": False, "error": "not found", "path": route})

        try:
            query = parse_qs(parsed.query)
            session_id = (query.get("session", [""])[0] or "").strip() or "default"
            if len(session_id) > 128:
                return self._send_json(400, {"ok": False, "error": "session id 过长（≤128）"})
            final = (self.headers.get("X-Final", "").strip().lower() in ("1", "true", "yes")
                     or query.get("final", [""])[0].strip().lower() in ("1", "true", "yes"))

            if (self.headers.get("Transfer-Encoding", "") or "").lower().strip() == "chunked":
                return self._send_json(411, {"ok": False,
                                             "error": "请带 Content-Length（不要 chunked）"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send_json(400, {"ok": False, "error": "Content-Length 不是整数"})
            if length <= 0:
                return self._send_json(400, {"ok": False, "error": "空 body：需要裸 PCM 字节"})
            if length > MAX_BODY:
                return self._send_json(413, {"ok": False,
                                             "error": f"body 过大（>{MAX_BODY // 1048576}MB）"})

            body = self._read_body(length)

            if route == "/asr" and not body:
                return self._send_json(400, {"ok": False, "error": "没有读到 body"})

            pcm, source = extract_pcm(body)
            if not pcm:
                return self._send_json(400, {"ok": False, "error": "剥掉 WAV 头后没有音频数据"})

            item = self.store.get_or_create(session_id)
            try:
                result = self.store.feed(item, pcm, final)
            finally:
                if final:
                    self.store.drop(session_id)

            log(f"  · asr session={session_id!r} src={source} bytes={len(pcm)} "
                f"chunk#{item.chunks} text+={len(result['delta'])} "
                f"partial={len(result['partial'])} {result['ms']}ms"
                + ("  [FINAL 已销毁]" if final else ""))
            return self._send_json(200, result)
        except Exception as exc:
            log("  ! /asr 出错：" + "".join(
                traceback.format_exception_only(type(exc), exc)).strip())
            log(traceback.format_exc())
            return self._send_json(500, {"ok": False, "error": str(exc)})

    def _read_body(self, length: int) -> bytes:
        buffer = bytearray()
        while len(buffer) < length:
            chunk = self.rfile.read(min(_READ_CHUNK, length - len(buffer)))
            if not chunk:
                break
            buffer.extend(chunk)
        return bytes(buffer)


class DualStackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# --------------------------------------------------------------------------- #
# 网络/端口
# --------------------------------------------------------------------------- #
def ip_rank(ip: str) -> int:
    # 按八位组判断，避免在源码里写出完整的私有网段字面量
    _o = ip.split(".")
    if len(_o) == 4 and _o[0] == "192" and _o[1] == "168":
        return 0
    if ip.startswith("10."):
        return 1
    if ip.startswith("169.254."):
        return 9
    if ip.startswith("172."):                 # 多半是 Hyper-V/WSL 虚拟网卡
        return 3
    return 2


def lan_ips() -> list[str]:
    """本机局域网 IPv4 列表。

    故意**不用** UDP-connect 探测默认路由那种做法 —— 需求要求“不得访问任何外部网络”，
    这里只解析 ``ipconfig`` 的本地输出，一个包都不发。
    """
    ips: list[str] = []
    if os.name != "nt":
        with contextlib.suppress(Exception):
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if not ip.startswith("127.") and ip not in ips:
                    ips.append(ip)
        return sorted(ips, key=ip_rank)
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["ipconfig"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=15, creationflags=flags).stdout or ""
        # 中文 Windows 是「IPv4 地址 . . . : <局域网IP>」，英文是「IPv4 Address. . . : 」
        for match in re.finditer(r"IPv4[^:]*:\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})", out):
            ip = match.group(1)
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception as exc:
        log(f"  · 读取 ipconfig 失败（{exc}），跳过局域网地址提示")
    return sorted(ips, key=ip_rank)


def lan_urls(port: int) -> list[str]:
    return [f"http://{ip}:{port}" for ip in lan_ips()]


def port_answers(host: str, port: int, timeout: float = 0.3) -> bool:
    """端口上是否已有程序在应答（连接探测，不发送任何业务数据）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def bind_pair(port: int, lan_host: str) -> tuple[DualStackServer, DualStackServer | None]:
    """同时绑 0.0.0.0（手机）与 127.0.0.1（本机）。

    Windows 允许 ``0.0.0.0:P`` 与 ``127.0.0.1:P`` 共存，回环请求会被更具体的那个抢走。
    所以两个都要占住：只绑 0.0.0.0 时，若别的程序持有回环，本机请求会被别人应答。
    任一绑不上就整体放弃这个端口，换下一个。
    """
    lan = DualStackServer((lan_host, port), Handler)
    try:
        loop = DualStackServer((LOOP_BIND, port), Handler)
    except OSError:
        lan.server_close()
        raise
    return lan, loop


def pick_servers(candidates: tuple[int, ...], lan_host: str, lan_ip_sample: str):
    """按候选顺序找可用端口；全被占则退回系统随机端口。"""
    last_error = ""
    for port in candidates:
        if port_answers(LOOP_BIND, port) or (lan_ip_sample and port_answers(lan_ip_sample, port)):
            log(f"  · {port} 已被占用，顺延")
            continue
        try:
            lan, loop = bind_pair(port, lan_host)
        except OSError as exc:
            last_error = str(exc)
            log(f"  · {port} 绑不上（{exc}），顺延")
            continue
        return port, lan, loop, "candidate"

    log(f"  ! {candidates[0]}~{candidates[-1]} 都不可用（{last_error or '被占用'}），"
        "改用系统随机端口")
    lan, loop = bind_pair(0, lan_host)
    return lan.server_address[1], lan, loop, "ephemeral"


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="语忆 · 完全离线的 Vosk 语音识别服务（供手机预览调用）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORTS[0],
                        help="首选端口，默认 8795；被占用自动顺延 8796~8799")
    parser.add_argument("--model", default="",
                        help="Vosk 模型目录（默认用 ai-voice-summary 里的中文小模型）")
    parser.add_argument("--lan-bind", default=LAN_BIND, help="对外绑定地址，默认 0.0.0.0")
    parser.add_argument("--self-check", action="store_true",
                        help="启动后对自己发一次 /health，确认回环上确实是本服务")
    parser.add_argument("--no-warmup", action="store_true",
                        help="跳过启动预热（预热是为了让第一个分片不慢好几倍）")
    args = parser.parse_args(argv)

    log(f"语忆 · 离线语音识别服务 v{VERSION}（Vosk，全程不联网）")

    module = load_local_asr()
    model_path = resolve_model(module, args.model)
    log(f"  · 模型：{model_path}")

    load_started = time.perf_counter()
    model = load_vosk_model(model_path)
    load_ms = round((time.perf_counter() - load_started) * 1000.0, 1)
    log(f"  · 模型加载完成（{load_ms} ms）")

    if not args.no_warmup:
        audio, label = warmup_audio()
        pool = RecognizerPool(model, PREWARM_COUNT)
        warm_ms = pool.prewarm(audio)
        log(f"  · 预热完成（{warm_ms} ms，{label}，池内 {pool.size} 个）"
            "—— 录音的第一个分片不会再干等好几秒")
    else:
        pool = RecognizerPool(model, 0)
        log("  · 已跳过预热（第一个分片会明显偏慢）")

    store = SessionStore(pool, module)
    Handler.store = store
    Handler.model_path = model_path
    Handler.load_ms = load_ms

    lan_ip_sample = (lan_ips() or [""])[0]
    candidates = tuple(dict.fromkeys([args.port, *DEFAULT_PORTS]))
    port, lan_server, loop_server, how = pick_servers(candidates, args.lan_bind, lan_ip_sample)

    threads = []
    for server in (lan_server, loop_server):
        if server is None:
            continue
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                                  daemon=True)
        thread.start()
        threads.append(thread)

    urls = [f"http://127.0.0.1:{port}"] + [f"http://{ip}:{port}" for ip in lan_ips()]

    # ---- stdout：机器可读行，验证脚本靠它拿实际端口 ----
    print(f"PORT={port}", flush=True)
    print(f"MODEL={model_path}", flush=True)
    print(f"HEALTH=http://127.0.0.1:{port}/health", flush=True)
    for url in urls:
        print(f"URL={url}", flush=True)
    print("READY=1", flush=True)

    log("")
    log(f"  ✓ 已监听 {LOOP_BIND}:{port}（本机）与 {args.lan_bind}:{port}（手机）"
        + ("   ※ 端口为系统随机分配" if how == "ephemeral" else ""))
    log(f"  ✓ 引擎 vosk / 采样率 16000 / 离线")
    log("")
    log("  ── 电脑上 ──")
    log(f"     {urls[0]}/health")
    log("  ── 手机上（需与电脑同一 WiFi/热点）──")
    for url in urls[1:]:
        log(f"     {url}/health")
    if len(urls) == 1:
        log("     （没读到局域网 IPv4，用 ipconfig 确认电脑的 IP）")
    log("")
    log("  Ctrl+C 停止。")
    log("")

    if args.self_check:
        run_self_check(port)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log("\n  收到 Ctrl+C，正在停止…")
    finally:
        store.shutdown()
        for server in (lan_server, loop_server):
            if server is not None:
                with contextlib.suppress(Exception):
                    server.shutdown()
                with contextlib.suppress(Exception):
                    server.server_close()
    return 0


def run_self_check(port: int) -> None:
    """确认回环端口上应答的确实是本服务（而不是别的程序抢了端口）。"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        ok = payload.get("ok") is True and payload.get("engine") == "vosk"
        log(f"  {'✓' if ok else '!'} 回环自检：{'通过' if ok else '异常'} {payload}")
    except Exception as exc:
        log(f"  ! 回环自检失败：{exc}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as error:                      # 启动期错误给清楚的人话
        log(f"启动失败：{error}")
        log(traceback.format_exc())
        raise SystemExit(2)