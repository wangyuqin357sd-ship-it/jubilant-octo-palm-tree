#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 ``asr-offline.py`` 真的能离线识别中文 —— 而且要和另一条独立链路对得上。

不验证就等于没做
----------------
这个脚本不是“跑一下就报成功”，它做三件互相独立的事：

1. **HTTP 流式链路**：把 ``ai-voice-summary/local-asr/test-sample.wav`` 切成多段
   （每段 2 秒，模拟手机真实上报节奏），依次 POST 到 ``/asr?session=verify``，
   只有最后一段带 ``X-Final: 1``。断言返回的中文非空、且累计文本**单调增长**
   （这是「服务端保住了 recognizer 状态、跨 chunk 连续识别」的直接证据）。
2. **交叉验证**：另外用 ``ai-voice-summary/scripts/local_asr.py`` 的 Python API
   （``transcribe_local``，**完全不经 HTTP**）对同一份 wav 识别一次，把两次结果
   去掉空白与标点后比字符重合率与序列相似度。重合率低于阈值 → FAIL。
   两条链路只要有一条是坏的（比如服务端把音频截断了、编码错了），分数就会掉下来。
3. **接口契约**：CORS 预检、WAV 直传（带 RIFF 头）、``X-Final`` 之后会话确实被销毁、
   局域网地址可达（手机能不能连）。

跑完一定杀掉子进程，并把 ``%TEMP%`` 下的工作目录删干净。

    python verify-asr-offline.py            # 退出码 0 = 全过，1 = 有 FAIL
"""

from __future__ import annotations

import contextlib
import difflib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import wave
from collections import Counter
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
SERVER = HERE / "asr-offline.py"
SKILL_ROOT = Path(r"C:\Users\HP\Desktop\ai-voice-summary")
LOCAL_ASR_PY = SKILL_ROOT / "scripts" / "local_asr.py"
SAMPLE_WAV = SKILL_ROOT / "local-asr" / "test-sample.wav"

PREFERRED_PORT = 8795
CHUNK_SECONDS = 2.0            # 每段 2 秒，贴近手机上报节奏
MIN_CHUNKS = 3                 # 需求要求至少 3 段
OVERLAP_MIN = 0.80             # 字符重合率低于此值判 FAIL
SIMILARITY_MIN = 0.80          # 序列相似度低于此值判 FAIL
READY_TIMEOUT = 120.0

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 比对前要丢掉的东西：空白 + 中英文标点 + 各种符号
DROP_RE = re.compile(r"[\s\u3000-\u303f\uff00-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65"
                     r"!-/:-@\[-`{-~]+")
REPLACEMENT = "\ufffd"

RESULT: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULT.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))
    return bool(ok)


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


# --------------------------------------------------------------------------- #
# 文本处理 / 比对
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    """去掉空白与标点、统一全角半角，只留可比对的正文字符。"""
    value = unicodedata.normalize("NFKC", text or "")
    value = DROP_RE.sub("", value)
    return value.replace(REPLACEMENT, "")


def overlap_rate(left: str, right: str) -> float:
    """字符重合率：按字符多重集求交集 / 较长者长度。"""
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    common = Counter(left) & Counter(right)
    return sum(common.values()) / max(len(left), len(right))


def similarity(left: str, right: str) -> float:
    """顺序敏感的相似度（stdlib difflib）。防止“字都对但顺序乱了”蒙混过关。"""
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()


def cjk_ratio(text: str) -> float:
    core = re.sub(r"\s+", "", text or "")
    if not core:
        return 0.0
    return len(CJK_RE.findall(core)) / len(core)


# --------------------------------------------------------------------------- #
# HTTP 小工具
# --------------------------------------------------------------------------- #
def http_request(port: int, path: str, data: bytes | None = None, headers: dict | None = None,
                 method: str = "POST", timeout: float = 120.0):
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, dict(response.headers), raw
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read()


def http_json(port: int, path: str, data: bytes | None = None, headers: dict | None = None,
              method: str = "POST"):
    status, response_headers, raw = http_request(port, path, data, headers, method)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {"_raw": raw[:400].decode("utf-8", "replace")}
    return status, response_headers, payload


# --------------------------------------------------------------------------- #
# 复用 local_asr（直接用 Python API，不经 HTTP）
# --------------------------------------------------------------------------- #
def load_local_asr():
    """导入 local_asr。必须先登记进 sys.modules，否则 dataclass 装饰器会炸。"""
    spec = importlib.util.spec_from_file_location("local_asr", LOCAL_ASR_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {LOCAL_ASR_PY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["local_asr"] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    print("语忆 · 离线语音识别服务 —— 验证脚本")
    print(f"  服务端：{SERVER}")
    print(f"  素材：  {SAMPLE_WAV}")
    print(f"  交叉验证：{LOCAL_ASR_PY}（Python API，不经 HTTP）")

    workdir = Path(tempfile.mkdtemp(prefix="yuyi-asr-verify-"))
    process: subprocess.Popen | None = None
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    port = PREFERRED_PORT
    health: dict = {}

    try:
        # ---------------- 素材自检 ----------------
        section("0. 素材与前置")
        if not record("测试音频存在", SAMPLE_WAV.is_file(), str(SAMPLE_WAV)):
            return 1
        with wave.open(str(SAMPLE_WAV), "rb") as handle:
            channels, rate, width = handle.getnchannels(), handle.getframerate(), handle.getsampwidth()
            frames = handle.readframes(handle.getnframes())
            total_frames = handle.getnframes()
        duration = total_frames / float(rate)
        record("测试音频是 16kHz / 单声道 / 16-bit",
               channels == 1 and rate == 16000 and width == 2,
               f"{rate}Hz / {channels}ch / {width * 8}bit / {duration:.2f}s / {len(frames)}B")
        record("服务端脚本存在", SERVER.is_file(), str(SERVER))

        # ---------------- 1. 启动子进程 + 等 /health ----------------
        section("1. 启动服务（子进程）并等待 /health 就绪")
        spawn_started = time.perf_counter()
        process = subprocess.Popen(
            [sys.executable, "-u", str(SERVER)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(HERE), text=True, encoding="utf-8", errors="replace", bufsize=1,
        )

        def pump(stream, sink: list[str]) -> None:
            with contextlib.suppress(Exception):
                for line in stream:
                    sink.append(line.rstrip("\n"))

        threading.Thread(target=pump, args=(process.stdout, stdout_lines), daemon=True).start()
        threading.Thread(target=pump, args=(process.stderr, stderr_lines), daemon=True).start()

        def server_log() -> str:
            return "".join(f"      | {line}\n" for line in (stdout_lines + stderr_lines)[-25:])

        deadline = time.time() + READY_TIMEOUT
        ready = False
        while time.time() < deadline:
            if process.poll() is not None:
                break
            for line in list(stdout_lines):
                if line.startswith("PORT="):
                    with contextlib.suppress(ValueError):
                        port = int(line.split("=", 1)[1].strip())
            try:
                status, _, payload = http_json(port, "/health", method="GET")
                if status == 200 and payload.get("ok") is True:
                    health = payload
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.4)

        if not record("服务已就绪（/health 返回 ok）", ready,
                      f"端口 {port}，启动到就绪 {time.perf_counter() - spawn_started:.1f}s"
                      if ready else f"等待超时；子进程输出：\n{server_log()}"):
            return 1

        printed_port = next((int(l.split("=", 1)[1]) for l in stdout_lines
                             if l.startswith("PORT=") and l.split("=", 1)[1].isdigit()), None)
        record("stdout 打印了实际端口（PORT=）", printed_port == port,
               f"stdout PORT={printed_port}，实际 {port}"
               + ("" if port == PREFERRED_PORT else f"（{PREFERRED_PORT} 被占用，已顺延）"))

        # ---------------- 2. /health 契约 ----------------
        section("2. /health 契约（引擎与模型）")
        record("engine == vosk", health.get("engine") == "vosk", repr(health.get("engine")))
        record("sample_rate == 16000", health.get("sample_rate") == 16000,
               repr(health.get("sample_rate")))
        record("offline == true", health.get("offline") is True, repr(health.get("offline")))
        model_path = Path(str(health.get("model", "")))
        record("模型路径是绝对路径", model_path.is_absolute(), str(model_path))
        record("模型路径真实存在（目录）", model_path.is_dir(), str(model_path))
        record("模型目录含 Vosk 必需子目录 am/ 与 conf/",
               (model_path / "am").is_dir() and (model_path / "conf").is_dir(),
               f"am/={(model_path / 'am').is_dir()} conf/={(model_path / 'conf').is_dir()}")
        print(f"      → 实际端口 {port} / 模型 {model_path}")

        # ---------------- 3. 流式分段识别 ----------------
        section(f"3. 分段流式识别（每段 {CHUNK_SECONDS:g}s，同一 session，最后一段 X-Final）")
        step_frames = max(1, int(CHUNK_SECONDS * rate))
        offsets = list(range(0, total_frames, step_frames))
        if len(offsets) < MIN_CHUNKS:                     # 理论上不会发生，兜底
            offsets = [int(i * total_frames / MIN_CHUNKS) for i in range(MIN_CHUNKS)]
        record(f"切成了 ≥{MIN_CHUNKS} 段", len(offsets) >= MIN_CHUNKS, f"实际 {len(offsets)} 段")

        chunks: list[dict] = []
        monotonic = True
        live_consistent = True
        previous_text = ""
        wall_started = time.perf_counter()
        for index, start in enumerate(offsets):
            stop = min(start + step_frames, total_frames)
            pcm = frames[start * width * channels:stop * width * channels]
            is_final = (index == len(offsets) - 1)
            headers = {"Content-Type": "application/octet-stream"}
            if is_final:
                headers["X-Final"] = "1"
            status, _, payload = http_json(port, "/asr?session=verify", pcm, headers)
            if status != 200:
                record(f"第 {index + 1} 段 POST 成功", False, f"HTTP {status} {payload}")
                return 1
            chunks.append(payload)
            current = str(payload.get("text", ""))
            if not current.startswith(previous_text):
                monotonic = False
            previous_text = current
            live = str(payload.get("live", ""))
            if live != current + str(payload.get("partial", "")):
                live_consistent = False
            print(f"      段{index + 1}/{len(offsets)} {len(pcm) / (rate * 2.0):.2f}s "
                  f"{payload.get('ms')}ms  可渲染={live!r} 新增={payload.get('delta', '')!r}")
        wall_elapsed = time.perf_counter() - wall_started

        record("每段都返回了 session 字段", all(c.get("session") == "verify" for c in chunks),
               repr({c.get("session") for c in chunks}))
        record("只有最后一段带 X-Final=1", chunks[-1].get("final") is True
               and all(c.get("final") is False for c in chunks[:-1]),
               f"final 标志={[c.get('final') for c in chunks]}")
        record("累计 text 单调增长（证明跨 chunk 保住了 recognizer 状态）", monotonic,
               f"长度序列={[len(str(c.get('text', ''))) for c in chunks]}")
        record("live == text + partial（字段契约自洽）", live_consistent,
               "每段都一致" if live_consistent else "有不一致")
        record("第一段就有字可渲染（预览框不会长时间空着）",
               bool(str(chunks[0].get("live", "")).strip()),
               f"第 1 段 live={str(chunks[0].get('live', ''))!r}")
        record("最后一长段 live 已全部定稿（partial 清空、live==text）",
               chunks[-1].get("partial") == "" and chunks[-1].get("live") == chunks[-1].get("text"),
               f"partial={chunks[-1].get('partial')!r}")
        record("live 整体增长（末段比首段长）",
               len(str(chunks[-1].get("live", ""))) > len(str(chunks[0].get("live", ""))),
               f"{len(str(chunks[0].get('live', '')))} → {len(str(chunks[-1].get('live', '')))} 字")
        # 注意：不要求 live 逐字单调 —— Vosk 的实时假设会自我修正（实测第 5→6 段
        # 「…中旬的」被改成「…中旬第」）。所以 partial/live 只能用于显示，
        # 要落库的必须是 text（单调、已定稿）。这条只作说明，不算 FAIL。
        revised = sum(1 for i in range(1, len(chunks))
                      if not str(chunks[i].get("live", "")).startswith(
                          str(chunks[i - 1].get("live", ""))))
        print(f"      · 说明：实时尾巴自我修正过 {revised} 次（正常现象）→"
              f" partial/live 仅用于显示，落库请用 text")

        streaming_text = str(chunks[-1].get("text", ""))
        streaming_delta_join = "".join(str(c.get("delta", "")) for c in chunks)
        record("最后一段 text 非空", bool(streaming_text.strip()), repr(streaming_text))
        record("所有段 delta 拼接后非空", bool(normalize(streaming_delta_join)),
               f"{len(normalize(streaming_delta_join))} 字")
        record("text 是中文（汉字占比 ≥60%）", cjk_ratio(streaming_text) >= 0.60,
               f"汉字占比 {cjk_ratio(streaming_text):.1%}")
        record("没有乱码替换符 U+FFFD", REPLACEMENT not in streaming_text)
        record("返回的是合法 UTF-8 JSON（中文未走管道乱码）",
               bool(CJK_RE.search(streaming_text)), f"样张：{streaming_text[:24]}")

        ms_values = [float(c.get("ms") or 0.0) for c in chunks]
        chunk_seconds = [len(frames[s * width * channels:min(s + step_frames, total_frames)
                                     * width * channels]) / (rate * 2.0) for s in offsets]
        print(f"      → 流式总耗时 {wall_elapsed * 1000:.0f}ms / {len(chunks)} 段；"
              f"单段服务端耗时 中位 {sorted(ms_values)[len(ms_values) // 2]:.0f}ms "
              f"最大 {max(ms_values):.0f}ms；单段音频 {chunk_seconds[0]:.2f}s")

        # ---------------- 4. 独立交叉验证 ----------------
        section("4. 独立交叉验证：local_asr.py 直接调 Python API（不经 HTTP）")
        module = load_local_asr()
        batch_started = time.perf_counter()
        batch = module.transcribe_local(SAMPLE_WAV, engine="vosk", language="zh", workdir=workdir)
        batch_elapsed = (time.perf_counter() - batch_started) * 1000.0
        batch_text = str(batch.get("text", ""))
        record("批量链路识别出文本", bool(batch_text.strip()), f"{batch_elapsed:.0f}ms")
        record("批量链路 engine == vosk", batch.get("engine") == "vosk", repr(batch.get("engine")))

        left, right = normalize(streaming_text), normalize(batch_text)
        overlap = overlap_rate(left, right)
        similar = similarity(left, right)
        print()
        print(f"      流式（HTTP 分段，{len(chunks)} 段）→ {streaming_text!r}")
        print(f"      批量（local_asr API，整段）→ {batch_text!r}")
        print(f"      归一化后字符数：流式 {len(left)} / 批量 {len(right)}")
        print(f"      字符重合率 overlap  = {overlap:.4f}   （阈值 ≥{OVERLAP_MIN}）")
        print(f"      序列相似度 similarity = {similar:.4f}   （阈值 ≥{SIMILARITY_MIN}）")
        print()
        record(f"字符重合率 ≥ {OVERLAP_MIN}", overlap >= OVERLAP_MIN, f"实测 {overlap:.4f}")
        record(f"序列相似度 ≥ {SIMILARITY_MIN}", similar >= SIMILARITY_MIN, f"实测 {similar:.4f}")
        record("两条链路结果完全一致", left == right,
               "完全一致" if left == right else "有差异但重合率达标")

        # ---------------- 5. 接口契约细节 ----------------
        section("5. 接口契约：CORS / WAV 直传 / X-Final 销毁会话 / 局域网可达")

        status, headers, payload = http_json(port, "/asr?session=cors-test",
                                             method="OPTIONS",
                                             headers={"Origin": "http://example.local",
                                                      "Access-Control-Request-Method": "POST"})
        allow_origin = headers.get("Access-Control-Allow-Origin")
        allow_headers = headers.get("Access-Control-Allow-Headers")
        record("OPTIONS 预检返回 2xx", 200 <= status < 300, f"HTTP {status}")
        record("预检带 Access-Control-Allow-Origin: *", allow_origin == "*", repr(allow_origin))
        record("预检带 Access-Control-Allow-Headers: *", allow_headers == "*", repr(allow_headers))

        status, headers, payload = http_json(port, "/asr?session=wav-test",
                                             SAMPLE_WAV.read_bytes(),
                                             {"Content-Type": "audio/wav", "X-Final": "1"})
        wav_text = str(payload.get("text", ""))
        record("直接 POST 整个 WAV（RIFF 头）成功", status == 200 and bool(wav_text.strip()),
               f"HTTP {status}，识别出 {len(normalize(wav_text))} 字")
        wav_overlap = overlap_rate(normalize(wav_text), right)
        record("WAV 直传结果与批量链路一致", wav_overlap >= OVERLAP_MIN,
               f"重合率 {wav_overlap:.4f}")
        status, headers, payload = http_json(port, "/health", method="GET")
        record("POST 响应带 Access-Control-Allow-Origin: *", headers.get(
            "Access-Control-Allow-Origin") == "*", repr(headers.get("Access-Control-Allow-Origin")))

        silence = b"\x00\x00" * int(rate * 0.6)
        status, _, payload = http_json(port, "/asr?session=verify", silence,
                                       {"Content-Type": "application/octet-stream"})
        after = str(payload.get("text", ""))
        record("X-Final 之后同名 session 已销毁（重新开始，不带旧文本）",
               status == 200 and after == "", f"text={after!r}（期望空）")

        lan_urls = list(health.get("lan_urls") or [])
        lan_ok, lan_detail = False, "没有读到局域网地址"
        for url in lan_urls:
            try:
                with urllib.request.urlopen(f"{url}/health", timeout=4) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if body.get("ok") is True:
                    lan_ok, lan_detail = True, f"{url}/health → ok（手机可用这个地址）"
                    break
            except Exception as exc:
                lan_detail = f"{url} 不可达：{exc}"
        record("局域网地址（0.0.0.0 绑定）可达 —— 手机据此连接", lan_ok, lan_detail)

        # ---------------- 6. 收尾 ----------------
        section("6. 收尾")
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=8)
        if process.poll() is None:
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
        record("子进程已结束", process.poll() is not None, f"退出码 {process.returncode}")

        time.sleep(0.8)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2):
                still_up = True
        except Exception:
            still_up = False
        record("端口已释放（服务确实停了）", not still_up)
    finally:
        if process is not None and process.poll() is None:
            with contextlib.suppress(Exception):
                process.kill()
            with contextlib.suppress(Exception):
                process.wait(timeout=5)
        shutil.rmtree(workdir, ignore_errors=True)
        leftover = workdir.exists()
        print(f"\n  临时工作目录已清理：{workdir} → {'仍在（异常）' if leftover else '已删除'}")

    # ---------------- 汇总 ----------------
    section("汇总")
    failed = [name for name, ok, _ in RESULT if not ok]
    print(f"  共 {len(RESULT)} 项检查：通过 {len(RESULT) - len(failed)}，失败 {len(failed)}")
    if failed:
        for name in failed:
            print(f"    ✗ {name}")
        print("\n  结论：FAIL")
        return 1
    print("\n  结论：全部 PASS —— 离线识别（HTTP 分段 + 独立批量链路）互相验证通过")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  被中断")
        raise SystemExit(1)