#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语忆 · 固定指令短语表 + 离线命中率测试台。

为什么要有这个
--------------
用户实测反馈：「很多次我说话小语都听不见、没有任何反应」。原因是页面用
``^...$`` 整句锚定匹配固定指令，真人说「结束了」「小语结束吧」「帮我打开原音频」
一律匹配不上。另一个项目的结论是：**把指令词加进固定语法，固定语法识别率远高于
自由听写**（``xiaoyu-assistant/README.md``）。这个文件把那条结论在本项目上**量化**。

两件事
------
1. **短语表**：读 ``yuyi-preview/data/asr-phrases.json``（页面与这里共用同一份），
   校验每个 ``id`` 确实是 ``index.html`` 里 ``ROUTES`` 的 key（现场读文件核对，
   不靠手抄的常量），并把标准说法+口语变体摊平成 Vosk 固定语法可用的短语列表。
2. **命中率测试台**：用 Windows 自带 TTS（``System.Speech.Synthesis``）把一组
   真人会说的口语变体合成成 16 kHz WAV，分别用 Vosk
   ① free 模式 ``KaldiRecognizer(model, 16000)``
   ② 短语表模式 ``KaldiRecognizer(model, 16000, json.dumps(phrases))``
   识别，按**预先写死**的规则判定命中，最后给出 ``free X/N`` vs ``phrases Y/N``。

判定规则（**先写死再看结果**，实测后没有回头调整过）
----------------------------------------------------
* 规范化：删掉所有空白与标点、全角转半角、英文小写（与 ``local_asr.clean_text``
  的口径一致：Vosk 会在中文词之间塞空格，必须先吃掉）。
* **命中** = 识别文本规范化后，**包含**该条目标指令在 ``asr-phrases.json``
  里声明的任一 ``keys`` 关键片段（子串包含）。
* 关键片段不来自识别结果，来自短语表；测试用例只声明「目标指令 id」，
  片段由表解析 —— 表和判定口径是同一份文件，先定表再跑分。
* 命中到**别的**指令的关键片段不算命中，只记进「错认成」列供排查。
* 干扰句的判定是反过来的：识别文本命中**全表任何一条**的关键片段 = 误触发。

Vosk 词表的坑（实测发现，必须记下来）
------------------------------------
``vosk-model-small-cn-0.22`` 的词表里**没有**「小语」「原音频」「我的」这些词
（``graph/`` 下也没有 words.txt 可供直接读取）。固定语法里出现词表外的词，
Vosk 只会打一行 ``Ignoring word missing in vocabulary`` 然后**悄悄丢掉**它，
语法就残废了。所以这里用 ``model.vosk_model_find_word`` 探词表，把每条短语
贪心切成**词表内的词序列**（「打开原音频」→ ``打开 原 音频``）。

诚实边界（别把这份报告读过头）
------------------------------
* 语料是 **TTS 合成**，不是真人录音；本机只有 ``Microsoft Huihui Desktop``
  一个中文音色，所以**没有覆盖不同说话人、口音、性别、麦克风与噪声**。
* 只在电脑上用 16 kHz 干净 WAV 跑过，**没有在真机手机浏览器上验证**。
* 短语表模式的分数天然偏高：语法就是这张表，表里写了就大概率能认回来；
  真正说明问题的是 free 模式那一列。

用法
----
    python asr-phrases.py --check          # 只校验短语表（不加载模型，秒回）
    python asr-phrases.py                  # 跑完整命中率测试台
    python asr-phrases.py --out report.md  # 同时把报告写到文件（默认写 %TEMP%）
    python asr-phrases.py --voice "Microsoft Huihui Desktop" --model "D:\\...\\vosk-model-small-cn-0.22"
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import wave
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------- #
# 输出编码：Windows 控制台默认 GBK，中文会乱码；显式 UTF-8
# --------------------------------------------------------------------------- #
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

VERSION = "1.0.0"

ROOT = Path(__file__).resolve().parent.parent                    # yuyi-preview/
PHRASES_JSON = ROOT / "data" / "asr-phrases.json"
INDEX_HTML = ROOT / "index.html"
SKILL_ROOT = Path(r"C:\Users\HP\Desktop\ai-voice-summary")
DEFAULT_MODEL = SKILL_ROOT / "local-asr" / "models" / "vosk-model-small-cn-0.22"
LOCAL_ASR_PY = SKILL_ROOT / "scripts" / "local_asr.py"
SAMPLE_RATE = 16000
DEFAULT_VOICE = "Microsoft Huihui Desktop"

# 干扰句：应当在容错匹配里返回 null、在 ASR 里也不该被认成指令
DISTRACTORS = [
    ("今天天气不错", 0),
    ("我们下课吧", 0),
    ("这个函数怎么写", 0),
    ("我们总结一下今天的内容", 0),
    ("打开课本第三页", 0),
    ("老师再见", 1),
]

# 口语变体测试集：(目标指令 id, 目标来自哪张表, 真人会说的句子, TTS 语速 -10..10)
# 语速故意有快有慢（-1 / 0 / 1 / 2），模拟不同说话节奏。
CASES: list[tuple[str, str, str, int]] = [
    ("end", "commands", "小语，结束吧", 0),
    ("end", "commands", "我结束了", 1),
    ("end", "commands", "好了结束", 0),
    ("end", "commands", "小语结束录音", 0),
    ("end", "commands", "结束", -1),
    ("navAudio", "commands", "小语帮我打开原音频", 0),
    ("navTodo", "commands", "打开一下待办", 1),
    ("navTodo", "commands", "待办在哪儿", 0),
    ("navTodo", "commands", "看看我的待办", 0),
    ("export", "commands", "小语，导出盲文", 0),
    ("export", "commands", "帮我导出盲文文档", 1),
    ("export", "commands", "导成中文 Word", 0),
    ("cancel", "commands", "先不导出", -1),
    ("summarize", "commands", "小语，做 AI 笔记总结", 0),
    ("summarize", "dialog", "需要", 0),
    ("cancel", "commands", "不用了", 0),
    ("cancel", "commands", "这个不需要", 1),
    ("todoAck", "commands", "小语，知道了", 0),
    ("todoAck", "commands", "行了停", 0),
    ("todoSnooze", "commands", "延后十分钟", 0),
    ("todoSnooze", "commands", "等会儿再提醒我", 0),
    ("navCatalog", "commands", "小语，打开目录", 0),
    ("navHome", "commands", "回到首页", 0),
    ("navMe", "commands", "打开设置", 0),
    ("navHelp", "commands", "打开帮助", 1),
    ("note", "commands", "AI 总结笔记", 0),
    ("start", "commands", "小语，开始录音", 0),
    ("help", "commands", "你能做什么", 0),
]


# --------------------------------------------------------------------------- #
# 1) 复用 ai-voice-summary/scripts/local_asr.py 的 clean_text（只读，不改它）
# --------------------------------------------------------------------------- #
def load_local_asr():
    """按路径导入 local_asr；失败就退回本文件里的等价实现。

    导入前关掉字节码写出：``ai-voice-summary/**`` 是只读复用资产，
    不往人家目录里落 .pyc（缓存本来有效时也不会写，这里只是把风险去掉）。
    """
    if not LOCAL_ASR_PY.is_file():
        return None
    sys.dont_write_bytecode = True
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("local_asr", LOCAL_ASR_PY)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["local_asr"] = module          # @dataclass 解析时需要
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


_LOCAL_ASR = load_local_asr()
_CJK = r"\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef"
_CJK_SPACE = re.compile(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])")


def clean_text(text: str) -> str:
    """吃掉 Vosk 塞进中文词之间的空格；与 local_asr.clean_text 同口径。"""
    if _LOCAL_ASR is not None:
        return _LOCAL_ASR.clean_text(text)
    value = re.sub(r"\s+", " ", (text or "").strip())
    previous = None
    while previous != value:
        previous = value
        value = _CJK_SPACE.sub("", value)
    return value.strip()


_PUNCT = re.compile(
    r"[\s\u3000，。、；：！？…·—～\"'“”‘’（）《》【】〈〉「」『』〔〕()\[\]{}<>.,!?;:~`@#$%^&*+=|\\/_-]"
)


def norm(text: str) -> str:
    """判定用的规范化：删标点空格、全角转半角、英文小写。"""
    value = unicodedata.normalize("NFKC", text or "")
    value = _PUNCT.sub("", value)
    return value.lower()


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


# --------------------------------------------------------------------------- #
# 2) 短语表：加载 + 校验
# --------------------------------------------------------------------------- #
def load_phrases(path: Path = PHRASES_JSON) -> dict:
    if not path.is_file():
        raise SystemExit(f"找不到短语表：{path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    for field in ("version", "wake", "rules", "fillers", "commands", "dialog"):
        if field not in doc:
            raise SystemExit(f"短语表缺少字段：{field}")
    return doc


def routes_keys_from_index(path: Path = INDEX_HTML) -> list[str]:
    """从 index.html 现场读出 ``const ROUTES = {`` 里的顶层 key。

    只读文件，不改。页面是唯一事实源：短语表里的 id 必须在这里能找到，
    否则匹配函数返回的 key 在页面上根本没有对应函数，等于又「没反应」。
    """
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.find("const ROUTES = {")
    if start < 0:
        return []
    keys: list[str] = []
    for line in text[start:].splitlines()[1:]:
        if line.strip() == "};":
            break
        match = re.match(r"^ {4}([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", line)
        if match:
            keys.append(match.group(1))
    return keys


def entry_index(doc: dict) -> dict[tuple[str, str], dict]:
    """(表名, id) → 条目。dialog 与 commands 的 id 可以重复（例如 cancel/deny）。"""
    out: dict[tuple[str, str], dict] = {}
    for group in ("commands", "dialog"):
        for item in doc[group]:
            key = (group, item["id"])
            if key in out:
                raise SystemExit(f"短语表里有重复条目：{group}/{item['id']}")
            out[key] = item
    return out


def validate(doc: dict) -> list[str]:
    """结构校验，返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    ids = [c["id"] for c in doc["commands"]]
    for dup, count in Counter(ids).items():
        if count > 1:
            problems.append(f"commands 里 id 重复：{dup} × {count}")
    live = routes_keys_from_index()
    if not live:
        problems.append("读不出 index.html 的 ROUTES key（文件缺失或格式变了）")
    else:
        for item in doc["commands"]:
            if item["id"] not in live:
                problems.append(f"id「{item['id']}」不在 index.html 的 ROUTES 里")
        for item in doc["dialog"]:
            if item["id"] not in live:
                problems.append(f"dialog id「{item['id']}」不在 index.html 的 ROUTES 里")
    for group in ("commands", "dialog"):
        for item in doc[group]:
            for field in ("id", "text", "alts", "keys"):
                if field not in item:
                    problems.append(f"{group}/{item.get('id', '?')} 缺少字段 {field}")
            if not item.get("keys"):
                problems.append(f"{group}/{item.get('id', '?')} 的 keys 是空的，永远匹配不上")
            for key in item.get("keys", []):
                if norm(key) != key:
                    problems.append(f"{group}/{item.get('id')} 的 key「{key}」没规范化"
                                    f"（应为「{norm(key)}」）")
            for alt in item.get("alts", []):
                if norm(alt) != alt:
                    problems.append(f"{group}/{item.get('id')} 的 alt「{alt}」没规范化"
                                    f"（应为「{norm(alt)}」）")
    for word in doc["wake"]["words"]:
        if norm(word) != word:
            problems.append(f"唤醒词「{word}」没规范化（应为「{norm(word)}」）")
    return problems


def grammar_phrases(doc: dict) -> list[str]:
    """摊平成 Vosk 固定语法用的短语列表（标准说法 + 口语变体 + 唤醒词）。"""
    out: list[str] = []
    seen: set[str] = set()

    def push(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            out.append(value)

    for group in ("commands", "dialog"):
        for item in doc[group]:
            push(item["text"])
            for alt in item["alts"]:
                push(alt)
    push(doc["wake"]["canonical"])
    for greet in doc["wake"]["greetings"]:
        push(greet + doc["wake"]["canonical"])
    return out


# --------------------------------------------------------------------------- #
# 3) Vosk 词表分词：固定语法里不能出现词表外的词
# --------------------------------------------------------------------------- #
_MAX_TOKEN = 6


def make_segmenter(model):
    cache: dict[str, bool] = {}

    def in_vocab(word: str) -> bool:
        if not word:
            return False
        hit = cache.get(word)
        if hit is None:
            try:
                hit = model.vosk_model_find_word(word) >= 0
            except Exception:
                hit = False
            cache[word] = hit
        return hit

    def segment(text: str) -> tuple[list[str], list[str]]:
        """贪心最长匹配切成词表内的词序列；返回 (词序列, 被丢掉的词表外字符)。

        词表外的字符**直接丢掉**，不放进语法 —— Vosk 拿到词表外的词只会打一行
        ``Ignoring word missing in vocabulary`` 然后自己丢掉它，我们提前做掉，
        语法里剩下什么就一目了然（也顺便消掉几千行原生日志）。
        """
        tokens: list[str] = []
        oov: list[str] = []
        i = 0
        while i < len(text):
            for size in range(min(_MAX_TOKEN, len(text) - i), 0, -1):
                piece = text[i:i + size]
                if in_vocab(piece):
                    tokens.append(piece)
                    i += size
                    break
            else:
                oov.append(text[i])
                i += 1
        return tokens, oov

    return segment


def build_grammar(doc: dict, segment) -> tuple[list[str], list[str], int]:
    """短语 → 词表内词序列。返回 (语法列表, 被丢掉的词表外字符, 原始短语数)。"""
    raw = grammar_phrases(doc)
    grammar: list[str] = []
    seen: set[str] = set()
    oov: list[str] = []
    for phrase in raw:
        body = norm(phrase)
        if not body:
            continue
        tokens, missing = segment(body)
        oov.extend(missing)
        joined = " ".join(tokens)
        if joined and joined not in seen:
            seen.add(joined)
            grammar.append(joined)
    return grammar, oov, len(raw)


@contextlib.contextmanager
def mute_native_stderr():
    """把 C++ 层直接写 fd 2 的 Kaldi 日志挡在控制台外。

    ``vosk.SetLogLevel(-1)`` 压不住 ``UpdateGrammarFst`` 的 WARNING，而每个
    recognizer 建一次就刷一遍（几十条 × 几十个文件 = 几千行）。这里在 fd 级别
    临时改道到匿名临时文件；顺便把它读回来，报告里说明白了多少行。
    python 自己的 stderr 先 flush，免得被一起吞掉。
    """
    captured = ""
    saved = sink = None
    with contextlib.suppress(Exception):
        sys.stderr.flush()
        saved = os.dup(2)
        sink = tempfile.TemporaryFile()
        os.dup2(sink.fileno(), 2)
    try:
        yield
    finally:
        if saved is not None:
            with contextlib.suppress(OSError):
                os.dup2(saved, 2)
                os.close(saved)
        if sink is not None:
            with contextlib.suppress(Exception):
                sink.flush()
                sink.seek(0)
                captured = sink.read().decode("utf-8", "replace")
                sink.close()
        globals()["_NATIVE_STDERR"] = captured


# --------------------------------------------------------------------------- #
# 4) TTS 合成（Windows 自带 System.Speech，不联网）
# --------------------------------------------------------------------------- #
PS_SCRIPT = r'''
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$jobs = [System.IO.File]::ReadAllText($env:YUYI_TTS_JOBS, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:YUYI_TTS_VOICE) { $synth.SelectVoice($env:YUYI_TTS_VOICE) }
Write-Output ("VOICE=" + $synth.Voice.Name + "|" + $synth.Voice.Culture)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($j in $jobs) {
  $synth.Rate = [int]$j.rate
  $synth.SetOutputToWaveFile($j.wav, $fmt)
  $synth.Speak($j.text)
  $synth.SetOutputToNull()
  Write-Output ("WAV=" + $j.wav)
}
$synth.Dispose()
'''


def synth_all(items: list[tuple[str, str, int]], workdir: Path, voice: str) -> str:
    """一次性合成所有句子（items = [(名字, 文本, 语速)]），返回实际音色名。"""
    jobs = []
    for name, text, rate in items:
        jobs.append({"wav": str(workdir / f"{name}.wav"), "text": text, "rate": rate})
    job_file = workdir / "tts-jobs.json"
    job_file.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")

    env = dict(os.environ)
    env["YUYI_TTS_JOBS"] = str(job_file)
    env["YUYI_TTS_VOICE"] = voice
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=600,
    )
    if completed.returncode != 0:
        raise SystemExit("TTS 合成失败：\n" + (completed.stderr or completed.stdout or "")[:1500])
    actual = ""
    for line in (completed.stdout or "").splitlines():
        if line.startswith("VOICE="):
            actual = line[len("VOICE="):].strip()
    return actual


def wav_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1 \
                or handle.getsampwidth() != 2:
            raise SystemExit(f"TTS 产出的 WAV 不是 16k/单声道/16bit：{path}")
        return handle.readframes(handle.getnframes())


# --------------------------------------------------------------------------- #
# 5) 识别：free 模式 vs 短语表模式
# --------------------------------------------------------------------------- #
_FEED_SLICE = 8000            # 0.25 秒；与 local_asr.py 一致，避免丢句


def recognize(model, pcm: bytes, grammar: list[str] | None = None) -> str:
    import vosk

    if grammar:
        rec = vosk.KaldiRecognizer(model, SAMPLE_RATE, json.dumps(grammar, ensure_ascii=False))
    else:
        rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
    pieces: list[str] = []
    for offset in range(0, len(pcm), _FEED_SLICE):
        if rec.AcceptWaveform(pcm[offset:offset + _FEED_SLICE]):
            payload = json.loads(rec.Result())
            if payload.get("text"):
                pieces.append(payload["text"])
    tail = json.loads(rec.FinalResult())
    if tail.get("text"):
        pieces.append(tail["text"])
    return clean_text(" ".join(pieces))


# --------------------------------------------------------------------------- #
# 6) 判定（规则见文件头，先写死再看结果）
# --------------------------------------------------------------------------- #
def hit_target(recognized: str, keys: list[str]) -> bool:
    text = norm(recognized)
    return any(norm(key) in text for key in keys if key)


def who_else(recognized: str, doc: dict, exclude: tuple[str, str]) -> str:
    """识别文本命中了别的哪条指令（诊断用，不参与命中判定）。"""
    text = norm(recognized)
    for group in ("commands", "dialog"):
        for item in doc[group]:
            if (group, item["id"]) == exclude:
                continue
            for key in item["keys"]:
                if key and norm(key) in text:
                    return f"{item['id']}({key})"
    return ""


def false_triggered(recognized: str, doc: dict, include_dialog: bool = True) -> str:
    """干扰句是否误触发了指令。

    ``include_dialog=False`` 只算**常驻**指令（commands）。页面把「需要/不用」这类
    弹窗应答词锁在 ``opts.dialog`` 后面，弹窗没开时它们根本进不了候选池，
    所以两个口径都要报，免得把「设计上不会发生的误触发」算到用户头上。
    """
    text = norm(recognized)
    groups = ("commands", "dialog") if include_dialog else ("commands",)
    for group in groups:
        for item in doc[group]:
            for key in item["keys"]:
                if key and norm(key) in text:
                    return f"{item['id']}({key})"
    return ""


# --------------------------------------------------------------------------- #
# 7) 报告
# --------------------------------------------------------------------------- #
def print_table(rows: list[dict], headers: list[str], widths: list[int]) -> None:
    print("  " + "  ".join(pad(h, w) for h, w in zip(headers, widths)))
    print("  " + "-" * (sum(widths) + 2 * (len(widths) - 1)))
    for row in rows:
        print("  " + "  ".join(pad(str(row.get(h, "")), w) for h, w in zip(headers, widths)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="语忆 · 固定指令短语表 + Vosk free/短语表 命中率测试台")
    parser.add_argument("--check", action="store_true", help="只校验短语表，不加载模型")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="Vosk 中文模型目录")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="TTS 音色名")
    parser.add_argument("--out", default="", help="把报告写到这个文件（默认写到 %%TEMP%%）")
    parser.add_argument("--keep-wav", action="store_true", help="保留合成的 wav（默认删）")
    args = parser.parse_args(argv)

    doc = load_phrases()
    problems = validate(doc)
    live = routes_keys_from_index()

    print(f"语忆 · 固定指令短语表 v{VERSION}")
    print(f"  表：{PHRASES_JSON}")
    print(f"  命令 {len(doc['commands'])} 条 + 弹窗应答 {len(doc['dialog'])} 条；"
          f"index.html ROUTES 现场读到 {len(live)} 个 key")
    if problems:
        print("\n  短语表校验：FAIL")
        for item in problems:
            print("    ✗ " + item)
        return 1
    print("  短语表校验：PASS（id 全部对得上 ROUTES；keys 都规范化过）")
    if args.check:
        total_keys = sum(len(c["keys"]) for c in doc["commands"] + doc["dialog"])
        total_alts = sum(len(c["alts"]) for c in doc["commands"] + doc["dialog"])
        print(f"  标准说法 {len(doc['commands']) + len(doc['dialog'])} 条，"
              f"口语变体 {total_alts} 条，关键片段 {total_keys} 条")
        return 0

    model_dir = Path(args.model)
    if not (model_dir / "am").is_dir():
        raise SystemExit(f"找不到 Vosk 模型目录（需要含 am/ 与 conf/）：{model_dir}")

    import vosk
    vosk.SetLogLevel(-1)
    started = time.perf_counter()
    model = vosk.Model(str(model_dir))
    load_ms = (time.perf_counter() - started) * 1000
    print(f"  模型：{model_dir.name}（加载 {load_ms:.0f} ms）")

    segment = make_segmenter(model)
    grammar, oov, raw_count = build_grammar(doc, segment)
    print(f"  固定语法：{raw_count} 条说法 → {len(grammar)} 条词表内短语")
    if oov:
        print(f"  注意：{len(oov)} 个字不在词表里（{''.join(sorted(set(oov)))}）")
    print("  例：「打开原音频」→ " + " ".join(segment(norm("打开原音频"))[0]))
    print("  例：「小语结束吧」→ " + " ".join(segment(norm("小语结束吧"))[0]))

    index = entry_index(doc)
    workdir = Path(tempfile.mkdtemp(prefix="yuyi-asr-phrases-"))
    items: list[tuple[str, str, int]] = []
    for i, (_, _, sentence, rate) in enumerate(CASES):
        items.append((f"case{i:02d}", sentence, rate))
    for i, (sentence, rate) in enumerate(DISTRACTORS):
        items.append((f"noise{i:02d}", sentence, rate))

    print(f"\n  TTS 合成 {len(items)} 条（{args.voice}，16 kHz 单声道）…")
    actual_voice = synth_all(items, workdir, args.voice)
    print(f"  实际音色：{actual_voice or '未知'}")

    lines: list[str] = []
    lines.append(f"# 语忆 · 固定指令命中率实测报告（{time.strftime('%Y-%m-%d %H:%M')}）")
    lines.append("")
    lines.append(f"- 短语表：`data/asr-phrases.json` v{doc['version']}"
                 f"（{len(doc['commands'])} 命令 + {len(doc['dialog'])} 弹窗应答）")
    lines.append(f"- 固定语法：{raw_count} 条说法 → {len(grammar)} 条词表内短语"
                 f"（Vosk 词表外的词会被静默丢弃，所以先按词表切分）")
    lines.append(f"- 模型：`{model_dir.name}`；采样率 {SAMPLE_RATE}")
    lines.append(f"- TTS：`{actual_voice}`（Windows System.Speech，16 kHz 单声道 WAV）")
    lines.append("- 语料是 TTS 合成，**不是真人录音**；本机只有这一个中文音色。")
    lines.append("")

    # ---------------- 口语变体：free vs 短语表 ----------------
    print(f"\n  ── 口语变体 {len(CASES)} 条：free 模式 vs 短语表模式 ──\n")
    rows: list[dict] = []
    free_hits = phrase_hits = 0
    text_level_miss: list[str] = []
    with mute_native_stderr():
        for i, (target, group, sentence, rate) in enumerate(CASES):
            entry = index[(group, target)]
            keys = entry["keys"]
            pcm = wav_pcm(workdir / f"case{i:02d}.wav")
            free_text = recognize(model, pcm)
            phrase_text = recognize(model, pcm, grammar)
            free_ok = hit_target(free_text, keys)
            phrase_ok = hit_target(phrase_text, keys)
            free_hits += free_ok
            phrase_hits += phrase_ok
            covered = any(norm(k) in norm(sentence) for k in keys)
            if not covered:
                text_level_miss.append(sentence)
            rows.append({
                "句子": sentence,
                "目标": target,
                "free 识别": free_text or "(空)",
                "free 判定": "命中" if free_ok else ("错认成 " + who_else(free_text, doc, (group, target))
                                                  if who_else(free_text, doc, (group, target)) else "未命中"),
                "短语识别": phrase_text or "(空)",
                "短语判定": "命中" if phrase_ok else ("错认成 " + who_else(phrase_text, doc, (group, target))
                                                  if who_else(phrase_text, doc, (group, target)) else "未命中"),
                "语速": rate,
                "表内覆盖": "是" if covered else "否",
            })
    widths = [26, 12, 20, 16, 20, 16, 5, 8]
    headers = ["句子", "目标", "free 识别", "free 判定", "短语识别", "短语判定", "语速", "表内覆盖"]
    print_table(rows, headers, widths)

    total = len(CASES)
    print(f"\n  free 命中 {free_hits}/{total}   vs   短语表命中 {phrase_hits}/{total}")
    print(f"  （其中 {total - len(text_level_miss)}/{total} 条的说法在短语表里覆盖得到；"
          f"没覆盖的是：{'、'.join(text_level_miss) if text_level_miss else '无'}）")

    lines.append("## 一、口语变体命中率（TTS 合成）")
    lines.append("")
    lines.append(f"**free 命中 {free_hits}/{total} vs phrases 命中 {phrase_hits}/{total}**")
    lines.append("")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "---|" * len(headers))
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    lines.append("")

    # ---------------- 干扰句：误触发 ----------------
    print(f"\n  ── 干扰句 {len(DISTRACTORS)} 条：会不会被误认成指令 ──\n")
    noise_rows: list[dict] = []
    free_false = phrase_false = 0
    free_false_cmd = phrase_false_cmd = 0
    with mute_native_stderr():
        for i, (sentence, rate) in enumerate(DISTRACTORS):
            pcm = wav_pcm(workdir / f"noise{i:02d}.wav")
            free_text = recognize(model, pcm)
            phrase_text = recognize(model, pcm, grammar)
            free_hit = false_triggered(free_text, doc)
            phrase_hit = false_triggered(phrase_text, doc)
            free_cmd = false_triggered(free_text, doc, include_dialog=False)
            phrase_cmd = false_triggered(phrase_text, doc, include_dialog=False)
            free_false += bool(free_hit)
            phrase_false += bool(phrase_hit)
            free_false_cmd += bool(free_cmd)
            phrase_false_cmd += bool(phrase_cmd)
            noise_rows.append({
                "句子": sentence,
                "free 识别": free_text or "(空)",
                "free 误触发": free_hit or "无",
                "短语识别": phrase_text or "(空)",
                "短语误触发": phrase_hit or "无",
                "语速": rate,
                "只算常驻 free/短语": f"{free_cmd or '无'} / {phrase_cmd or '无'}",
            })
    nwidths = [20, 20, 16, 22, 16, 5, 26]
    nheaders = ["句子", "free 识别", "free 误触发", "短语识别", "短语误触发", "语速", "只算常驻 free/短语"]
    print_table(noise_rows, nheaders, nwidths)
    print(f"\n  free 误触发 {free_false}/{len(DISTRACTORS)}   vs   "
          f"短语表误触发 {phrase_false}/{len(DISTRACTORS)}")
    print(f"  只算常驻指令（弹窗应答词不算，页面本来就把它们锁在 opts.dialog 后面）："
          f"free {free_false_cmd}/{len(DISTRACTORS)} vs 短语表 {phrase_false_cmd}/{len(DISTRACTORS)}")
    print("  说明：短语表模式是**受限语法**，语法之外的话没有出口，"
          "所以它必然更容易把无关语音硬套成某条指令 —— 这是它的代价，不是意外。")
    native_lines = len([line for line in globals().get("_NATIVE_STDERR", "").splitlines() if line.strip()])
    if native_lines:
        print(f"  （Vosk/Kaldi 的原生日志挡掉了 {native_lines} 行 —— 都是词表外的词，"
              "已在建语法时剔除，不进报告。）")

    lines.append("## 二、干扰句误触发（同一次实测）")
    lines.append("")
    lines.append(f"- free 误触发 {free_false}/{len(DISTRACTORS)} vs 短语表误触发 "
                 f"{phrase_false}/{len(DISTRACTORS)}（含弹窗应答词）")
    lines.append(f"- 只算常驻指令：free {free_false_cmd}/{len(DISTRACTORS)} vs "
                 f"短语表 {phrase_false_cmd}/{len(DISTRACTORS)}")
    lines.append("")
    lines.append("| " + " | ".join(nheaders) + " |")
    lines.append("|" + "---|" * len(nheaders))
    for row in noise_rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in nheaders) + " |")
    lines.append("")
    lines.append("## 三、诚实边界")
    lines.append("")
    lines.append("- 语料是 **TTS 合成**，不是真人录音；本机只有 "
                 f"`{actual_voice}` 一个中文音色，**没有覆盖不同说话人/口音/性别/麦克风/噪声**。")
    lines.append("- 只在电脑上用 16 kHz 干净 WAV 跑，**没有在真机手机浏览器上验证**。")
    lines.append("- 短语表模式的分数天然偏高：语法就是这张表本身；真正说明问题的是 free 那一列。")
    lines.append("- 判定规则在跑之前就写死（见 `_tools/asr-phrases.py` 文件头），实测后没有回头调。")
    lines.append("")

    out_path = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "yuyi-asr-phrases-report.md"
    out_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"\n  报告已写入：{out_path}")

    if not args.keep_wav:
        for item in list(workdir.glob("*.wav")) + [workdir / "tts-jobs.json"]:
            with contextlib.suppress(OSError):
                item.unlink()
        with contextlib.suppress(OSError):
            workdir.rmdir()
    else:
        print(f"  WAV 保留在：{workdir}")

    if phrase_hits < free_hits:
        print("\n  ！短语表模式命中率反而更低 —— 如实报告，没有回头改判定规则。")
        return 2          # 只表示「不符合预期」，不是脚本错误
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)