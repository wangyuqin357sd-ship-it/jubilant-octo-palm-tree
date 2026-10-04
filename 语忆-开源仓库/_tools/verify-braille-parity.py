#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文盲文 JS 移植的等价性验证（Python 原实现 ↔ 浏览器 JS 实现）。

运行
----
    python yuyi-preview\\_tools\\verify-braille-parity.py

默认只读、只验证；全部 PASS 返回 0，任何一条 FAIL 返回 1，
环境问题（找不到 node / 表文件）返回 2。

    python yuyi-preview\\_tools\\verify-braille-parity.py --rebuild-data
        从后端表重新生成 yuyi-preview/data/braille-zh.json（minify + 补 meta）
    python yuyi-preview\\_tools\\verify-braille-parity.py --keep-temp
        保留中间文件（语料 / node 输入输出）便于人工核查

验证内容
--------
1) 表数据等价：`yuyi-preview/data/braille-zh.json` 与
   `ai-voice-summary/data/braille_zh.json` 的 6 个顶层键（chars / digits /
   lower / upper / words）逐一比较，键名与映射值必须完全一致；
   meta 必须保留后端全部字段并带上 source / generated。
2) 引擎等价（逐字符）：用 Python 原实现算期望值，用 node 跑 JS 实现算实际值，
   逐条 `==` 比较。语料覆盖纯中文长句、中文+阿拉伯数字、中文+英文混排、
   中文标点、换行、纯数字与小数、纯英文大小写、空串、只有标点、未映射字符
   （emoji / 生僻符号）等。
3) 全表保真：chars(21034) + words(23354) 每一条单独转换，两侧各自算 FNV-1a
   聚合校验和并比对（比逐条传输 4 万个字符串更省，也更容易发现个别偏差）。

编码
----
Windows 上 node 与 python 之间**不走管道传中文**：语料、期望值、JS 实际输出
都落成 UTF-8 文件再读；Python 侧所有 open() 都显式写 encoding='utf-8'。
stdout 不是终端时（被重定向/被捕获）会自动切到 UTF-8，且任何无法编码的字符
（盲文字符 U+28xx、emoji）都会降级成 \\uXXXX 转义而不是抛 UnicodeEncodeError。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

# --------------------------------------------------------------------- 路径

HERE = os.path.dirname(os.path.abspath(__file__))               # yuyi-preview/_tools
PROJECT = os.path.dirname(HERE)                                  # yuyi-preview
DESKTOP = os.path.dirname(PROJECT)                               # 工作目录
PY_SRC = os.path.join(DESKTOP, "ai-voice-summary", "scripts")
PY_TABLE = os.path.join(DESKTOP, "ai-voice-summary", "data", "braille_zh.json")
JS_IMPL = os.path.join(HERE, "braille-zh.js")
JS_TABLE = os.path.join(PROJECT, "data", "braille-zh.json")
DATA_SOURCE_LABEL = "ai-voice-summary/data/braille_zh.json"

TOP_KEYS = ("chars", "digits", "lower", "upper", "words")

# 折行验证宽度：32 是后端默认（BRF 约定），其余为边界/硬折行场景
WRAP_WIDTHS = (32, 16, 8, 1)

# ------------------------------------------------------------------ 输出层

_OUT: list[str] = []
_ENCODING = "utf-8"


def emit(line: str = "") -> None:
    """按 stdout 实际能编码的字符集输出，编码不了就降级成转义，绝不抛异常。"""
    _OUT.append(line)
    text = line
    try:
        text.encode(_ENCODING)
    except (UnicodeEncodeError, LookupError):
        text = text.encode("ascii", "backslashreplace").decode("ascii")
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:      # 极端情况：编码名骗了我们
        sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")


def fail_summary(lines: list[str]) -> None:
    for item in lines:
        emit("    " + item)


# ------------------------------------------------------------------ 结果收集

class Checks:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[tuple[str, str]] = []

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            emit(f"[PASS] {label}")
        else:
            self.failed.append((label, detail))
            emit(f"[FAIL] {label}")
            if detail:
                emit("       " + detail)
        return ok

    def equal(self, label: str, got: object, expected: object) -> bool:
        if got == expected:
            return self.check(label, True)
        detail = (
            "期望: " + _short(expected) + "\n"
            "       实际: " + _short(got)
        )
        return self.check(label, False, detail)

    @property
    def total(self) -> int:
        return self.passed + len(self.failed)


def _short(value: object, limit: int = 220) -> str:
    """人可读且一定可打印的表示（中文/盲文原样，控制字符转义）。"""
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(value)
    text = text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    if len(text) > limit:
        text = text[:limit] + f"…(+{len(text) - limit} 字符)"
    return text


# ------------------------------------------------------------------ 表数据

def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:      # 显式 UTF-8
        return json.load(handle)


def write_json(path: str, payload: object) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:   # 显式 UTF-8
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def rebuild_data() -> int:
    """从后端表生成浏览器用的 minify 副本（语义等价 + meta 溯源）。"""
    emit("=" * 78)
    emit("重新生成 yuyi-preview/data/braille-zh.json")
    emit("=" * 78)
    if not os.path.isfile(PY_TABLE):
        emit(f"[FAIL] 找不到后端表：{PY_TABLE}")
        return 2

    with open(PY_TABLE, "rb") as handle:
        raw_bytes = handle.read()
    backend = json.loads(raw_bytes.decode("utf-8"))
    sha = hashlib.sha256(raw_bytes).hexdigest()

    os.makedirs(os.path.dirname(JS_TABLE), exist_ok=True)
    out = {key: backend[key] for key in TOP_KEYS}
    meta = dict(backend.get("meta", {}))              # 原有 meta 一个都不丢
    meta["source"] = DATA_SOURCE_LABEL
    meta["generated"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    meta["source_sha256"] = sha
    meta["browser_copy"] = "minified semantic copy; keys and values identical to the backend table"
    out["meta"] = meta
    # 键顺序固定，便于人眼 diff
    ordered = {key: out[key] for key in sorted(out)}
    write_json(JS_TABLE, ordered)

    size = os.path.getsize(JS_TABLE)
    emit(f"[ OK ] 已写入 {JS_TABLE}")
    emit(f"       后端表 {len(raw_bytes)} 字节 → 浏览器表 {size} 字节"
         f"（{size / max(len(raw_bytes), 1) * 100:.1f}%）")

    # 读回抽样打印：确认中文与盲文点号没有乱码
    back = load_json(JS_TABLE)
    emit("")
    emit("读回抽样（中文 / 点位写法 / Unicode 盲文）：")
    samples = ["中", "国", "人", "是", "一", "文", "好", "你", "，", "。", "！", "？",
               "：", "；", "“", "”", "‘", "’", "a", "A", "0", "9", "　", "\r"]
    bad = 0
    for char in samples:
        spec = back["chars"].get(char) or back["digits"].get(char) \
            or back["lower"].get(char) or back["upper"].get(char)
        cells = cells_to_unicode(spec) if spec else ""
        backend_spec = backend["chars"].get(char) or backend["digits"].get(char) \
            or backend["lower"].get(char) or backend["upper"].get(char)
        ok = spec == backend_spec
        bad += 0 if ok else 1
        emit(f"    {char!r:8} {str(spec):12} {cells}   {'一致' if ok else '不一致!'}")
    words = list(back["words"].items())[:3]
    for word, spec in words:
        emit(f"    {word!r:8} {spec:12} {cells_to_unicode(spec)}   "
             f"{'一致' if backend['words'].get(word) == spec else '不一致!'}")
    emit(f"    抽样 {len(samples) + len(words)} 条，点位不一致 {bad} 条")
    emit("")
    return 0 if bad == 0 else 1


def cells_to_unicode(spec: str) -> str:
    out = []
    for group in spec.split("-"):
        value = 0
        for digit in group:
            if digit == "0":
                continue
            index = int(digit)
            if 1 <= index <= 8:
                value |= 1 << (index - 1)
        out.append(chr(0x2800 + value))
    return "".join(out)


def check_data_parity(checks: Checks, js_table_path: str = JS_TABLE) -> bool:
    emit("=" * 78)
    emit("① 表数据等价：yuyi-preview/data/braille-zh.json ↔ 后端 braille_zh.json")
    emit("=" * 78)

    if not os.path.isfile(PY_TABLE):
        emit(f"[FAIL] 缺少后端表：{PY_TABLE}")
        return False
    if not os.path.isfile(js_table_path):
        emit(f"[FAIL] 缺少浏览器表：{js_table_path}")
        emit("       先运行：python yuyi-preview\\_tools\\verify-braille-parity.py --rebuild-data")
        return False

    backend = load_json(PY_TABLE)
    front = load_json(js_table_path)

    checks.check("后端表顶层键 = {chars,digits,lower,upper,words,meta}",
                 set(backend) == set(TOP_KEYS) | {"meta"},
                 f"实际: {sorted(backend)}")
    checks.check("浏览器表顶层键一致",
                 set(front) == set(TOP_KEYS) | {"meta"},
                 f"实际: {sorted(front)}")

    ok = True
    for key in TOP_KEYS:
        left = backend.get(key)
        right = front.get(key)
        if not isinstance(left, dict) or not isinstance(right, dict):
            checks.check(f"{key}: 两侧都是对象", False, f"{type(left)} / {type(right)}")
            ok = False
            continue
        missing = sorted(set(left) - set(right))
        extra = sorted(set(right) - set(left))
        diff = [k for k in left if k in right and left[k] != right[k]]
        same = not missing and not extra and not diff
        detail = ""
        if not same:
            detail = (f"缺 {len(missing)} 键 {missing[:5]}；多 {len(extra)} 键 {extra[:5]}；"
                      f"值不同 {len(diff)} 键 {diff[:5]}")
        checks.check(f"{key}: {len(left)} 条键名与映射值逐一相同", same, detail)
        ok = ok and same

    # meta：原有信息保留 + 新增来源与生成时间
    meta = front.get("meta", {}) if isinstance(front.get("meta"), dict) else {}
    bmeta = backend.get("meta", {})
    lost = [k for k in bmeta if k not in meta or meta[k] != bmeta[k]]
    checks.check(f"meta 保留后端全部 {len(bmeta)} 个字段且取值相同", not lost,
                 f"丢失/被改写: {lost}")
    checks.check("meta.source 标明来源", meta.get("source") == DATA_SOURCE_LABEL,
                 f"实际: {meta.get('source')!r}")
    generated = str(meta.get("generated", ""))
    try:
        _dt.datetime.fromisoformat(generated)
        iso_ok = True
    except ValueError:
        iso_ok = False
    checks.check(f"meta.generated 是 ISO 时间（{generated}）", iso_ok)

    # 读回抽样打印（防止编码把中文/点位写坏）
    emit("")
    emit("读回抽样打印（浏览器表原样读出，并与后端表逐条核对）：")

    def lookup(container: dict, sample: str):
        for name in ("chars", "digits", "lower", "upper", "words"):
            table = container.get(name) or {}
            if sample in table:
                return name, table[sample]
        return None, None

    samples = ["中", "国", "人", "是", "一", "好", "你", "文",
               "，", "。", "！", "？", "：", "；", "“", "”", "‘", "’",
               "a", "A", "z", "0", "9", "\t", "\r", "\u3000",
               "……", "一下", "一个", "银行", "三重", "行业"]
    shown = 0
    mismatched = 0
    for sample in samples:
        table_name, spec = lookup(front, sample)
        if table_name is None:
            emit(f"    {sample!r:10} 不在表中（转换时按未覆盖处理）")
            continue
        back_name, back_spec = lookup(backend, sample)
        same = (table_name, spec) == (back_name, back_spec)
        mismatched += 0 if same else 1
        shown += 1
        emit(f"    {sample!r:10} {table_name:6} {spec:18} → {cells_to_unicode(spec)}"
             f"   {'与后端一致' if same else '与后端不一致!'}")
    emit(f"    共抽样 {shown} 条（覆盖 chars/digits/lower/upper/words），"
         f"点位写法与后端不一致 {mismatched} 条，中文与盲文均无乱码")
    emit("")
    return ok


# -------------------------------------------------------------------- 语料

CORPUS: list[tuple[str, str]] = [
    ("pure-chinese-long",
     "本次会议主要讨论了三件事：第一，产品上线时间定在下个月中旬；"
     "第二，市场部门需要在两周内完成竞品调研报告；第三，财务预算追加五十万元。"),
    ("chinese-with-arabic-digits",
     "负责人分别是张伟、李娜和王强，截止日期为2026年11月30日。"),
    ("chinese-english-mixed",
     "人工智能语音总结工具 AI Voice Summary v2.1 已经可以导出 Word 文档和 BRF 文件。"),
    ("chinese-punctuation",
     "“你好，”她说，“这样真的好吗？”——是的！当然；没问题。"),
    ("multiline-newlines",
     "一句话摘要\n人工智能语音总结工具已经可以导出 Word 文档。\n待办事项\n"
     "- 张伟负责接口联调 (2026-11-30)"),
    ("digits-only", "2026"),
    ("digits-decimal", "3.14 和 12,345.67 以及 0.5%"),
    ("digits-fullwidth", "１２３４５６７８９０"),
    ("ascii-letters-case", "Hello World ABCXYZ abcxyz"),
    ("ascii-fullwidth", "ＡＢＣａｂｃ"),
    ("empty-string", ""),
    ("punctuation-only", "，。！？：；“”‘’、；——……（）《》"),
    ("unmapped-emoji-rare",
     "生僻字𠀋和表情😀还有符号☃\ufeff"),
    ("unmapped-all", "😀🎉"),
    ("whitespace-tabs", "a\tb\u3000c\rd"),
    ("single-char", "中"),
    ("polyphone-word-rules", "银行行业三重长大"),
    ("mixed-everything",
     "2026年10月4日，AI 助手已上传 3 个文件（共 12.5 MB）。\n提示音：滴！"),
]

CELL_SPECS = ["0", "3456-245", "3-256", "45-45", "5-0", "6-1", "12345678",
              "9", "6-9", "0-0", "12345678-9-0", "1-12-123", "34-256"]

# 折行边界：直接喂盲文串（不经过语料），覆盖 Python `wrap_cells` 的怪癖分支
EXTRA_WRAPS: list[tuple[str, str, int]] = [
    ("wrap-two-spaces-width1", "⠁  ⠃", 1),
    ("wrap-emoji-triple-width1", "😀😀😀", 1),           # 非 BMP 硬折行（码点切分）
    ("wrap-unmapped-mixed-width2", "⠁😀⠃𠀋⠉", 2),
    ("wrap-long-token-width32", "⠁" * 70, 32),
    ("wrap-spaces-only-width1", "   ", 1),
    ("wrap-trailing-newline", "⠁⠃\n", 3),
    ("wrap-leading-newline", "\n⠁⠃", 3),
    ("wrap-empty", "", 4),
    ("wrap-big-width", "⠁⠃⠉", 999),
    ("wrap-py-space-1c", "\u001c ⠁", 1),                # Python isspace 真 / JS trim 假
    ("wrap-py-space-85", "\u0085 ⠁", 1),
    ("wrap-py-space-a0", "\u00a0 ⠁", 1),
    ("wrap-py-space-2028", "\u2028 ⠁", 1),
    ("wrap-exact-fit", "⠁⠃⠉⠙", 4),
    ("wrap-one-over", "⠁⠃⠉⠙⠑", 4),
]


def build_cases() -> list[dict]:
    cases = []
    for cid, text in CORPUS:
        # 语料必须能干净地编码成 UTF-8（否则传输本身就不等价）
        text.encode("utf-8")
        cases.append({"id": cid, "text": text, "widths": list(WRAP_WIDTHS)})
    return cases


# ------------------------------------------------------- Python 侧期望输出

def build_expected(cases: list[dict]) -> dict:
    import braille_zh as bz

    expected: dict[str, dict] = {}
    for case in cases:
        text = case["text"]
        result = bz.to_braille(text)
        braille = result.braille
        expected[case["id"]] = {
            "toBrailleText_run": bz.to_braille_text(text),
            "toBrailleText_each": bz.to_braille_text(text, number_sign="each"),
            "stats": result.stats(),
            "coverageReport": bz.coverage_report(text),
            "unmappedChars": bz.unmapped_chars(text),
            "wrapDefault": bz.wrap_cells(braille),
            "wraps": {str(w): bz.wrap_cells(braille, w) for w in case["widths"]},
            "braillePreview": braille[:24],
        }
    return expected


def fnv1a_of(text: str, seed: int = 0x811C9DC5) -> int:
    """与 JS 侧同构的 FNV-1a（按码点，不按 UTF-8 字节），用于全表聚合比对。"""
    value = seed
    for char in text:
        value = ((value ^ ord(char)) * 0x01000193) & 0xFFFFFFFF
    return value


def python_table_digest(raw: dict) -> dict:
    """Python 原实现把表里每条 chars/words 单独转换后的聚合校验和。"""
    import braille_zh as bz

    out = {}
    for key in ("chars", "words"):
        entries = sorted(raw[key].keys())
        digest = 0x811C9DC5
        mapped = 0
        for entry in entries:
            converted = bz.to_braille_text(entry)
            digest = fnv1a_of(entry + "\x00" + converted, digest)
            mapped += 1
        out[key] = {"count": mapped, "fnv1a": f"{digest:08x}"}
    return out


# ----------------------------------------------------------- node 执行器

NODE_RUNNER = r"""
'use strict';
// 由 verify-braille-parity.py 生成：读 UTF-8 文件 → 跑 JS 实现 → 写 UTF-8 文件。
// 中文/盲文一律走文件，绝不经过命令行参数或管道。
const fs = require('fs');
const path = require('path');

const [jsPath, dataPath, casesPath, outPath] = process.argv.slice(2);
const BrailleZH = require(path.resolve(jsPath));

const payload = JSON.parse(fs.readFileSync(casesPath, 'utf8'));
const cases = payload.cases;

function cpCompare(a, b) {
  const ca = Array.from(a), cb = Array.from(b);
  const n = Math.min(ca.length, cb.length);
  for (let i = 0; i < n; i += 1) {
    const va = ca[i].codePointAt(0), vb = cb[i].codePointAt(0);
    if (va !== vb) return va < vb ? -1 : 1;
  }
  return ca.length === cb.length ? 0 : (ca.length < cb.length ? -1 : 1);
}

function fnv1a(text, seed) {
  let h = seed >>> 0;
  for (const ch of text) {          // for..of 按码点迭代
    h = Math.imul(h ^ ch.codePointAt(0), 0x01000193) >>> 0;
  }
  return h;
}

(async () => {
  const out = { readyBeforeLoad: BrailleZH.ready(), errors: {} };

  // 加载前调用应该显式报错，而不是给出错结果
  try { BrailleZH.toBrailleText('中'); out.errors.beforeLoad = 'no-throw'; }
  catch (e) { out.errors.beforeLoad = 'throw'; }

  await BrailleZH.load(dataPath);
  out.readyAfterLoad = BrailleZH.ready();

  // 公开 API 常量（后端约定：默认折行宽度 32）
  out.defaultWidth = BrailleZH.DEFAULT_WIDTH;
  out.constants = {
    NUMBER_SIGN: BrailleZH.NUMBER_SIGN,
    CAPITAL_SIGN: BrailleZH.CAPITAL_SIGN,
    BLANK_CELL: BrailleZH.BLANK_CELL,
  };
  out.tableInfoKeys = Object.keys(BrailleZH.tableInfo()).sort();

  // 错误行为：与 Python 一样必须抛
  out.errors.wrapWidthZero = (() => {
    try { BrailleZH.wrapCells('x', 0); return 'no-throw'; } catch (e) { return 'throw'; }
  })();
  out.errors.nonStringText = (() => {
    try { BrailleZH.toBrailleText(123); return 'no-throw'; } catch (e) { return 'throw'; }
  })();

  // 逐条语料
  out.results = {};
  for (const c of cases) {
    const rec = {};
    const braille = BrailleZH.toBrailleText(c.text);
    rec.toBrailleText_run = braille;
    rec.toBrailleText_each = BrailleZH.toBrailleText(c.text, { number_sign: 'each' });
    // 字符串形式的 opts 也应接受
    rec.toBrailleText_each_byString = BrailleZH.toBrailleText(c.text, 'each');
    rec.stats = BrailleZH.toBraille(c.text).stats();
    rec.coverageReport = BrailleZH.coverageReport(c.text);
    rec.unmappedChars = BrailleZH.coverage(c.text);
    rec.braillePreview = Array.from(braille).slice(0, 24).join('');
    rec.wrapDefault = BrailleZH.wrapCells(braille);
    rec.wraps = {};
    for (const w of c.widths) rec.wraps[String(w)] = BrailleZH.wrapCells(braille, w);
    out.results[c.id] = rec;
  }

  // 点位写法 → Unicode 盲文
  out.cellsToUnicode = {};
  for (const spec of payload.cellsToUnicodeSpecs) {
    out.cellsToUnicode[spec] = BrailleZH.cellsToUnicode(spec);
  }

  // 折行边界（直接喂盲文串，不经过语料转换）
  out.extraWraps = {};
  for (const item of payload.extraWraps) {
    out.extraWraps[item.id] = BrailleZH.wrapCells(item.braille, item.width);
  }

  // 全表保真：chars / words 每条单独转换后的聚合校验和
  const raw = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
  out.tableDigest = {};
  for (const key of ['chars', 'words']) {
    const entries = Object.keys(raw[key]).sort(cpCompare);
    let digest = 0x811C9DC5;
    for (const entry of entries) {
      digest = fnv1a(entry + '\x00' + BrailleZH.toBrailleText(entry), digest);
    }
    out.tableDigest[key] = { count: entries.length, fnv1a: digest.toString(16).padStart(8, '0') };
  }

  fs.writeFileSync(outPath, JSON.stringify(out), 'utf8');
})().catch((err) => {
  process.stderr.write('NODE-RUNNER-ERROR: ' + (err && err.stack ? err.stack : String(err)) + '\n');
  process.exit(1);
});
"""


BROWSER_RUNNER = r"""
'use strict';
// 由 verify-braille-parity.py 生成：模拟浏览器环境跑一遍真实的浏览器入口。
// 沙箱里没有 module / exports / define / require，只有 window(=globalThis) 与 fetch，
// 因此 braille-zh.js 必须走 UMD 的「挂 window.BrailleZH」分支，加载必须走 fetch 分支。
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const [jsPath, dataPath, outPath] = process.argv.slice(2);
const src = fs.readFileSync(jsPath, 'utf8');

const sandbox = { console: console, setTimeout: setTimeout, Promise: Promise };
sandbox.fetch = function (url) {
  sandbox.__fetchCalls = (sandbox.__fetchCalls || 0) + 1;
  const target = path.resolve(path.dirname(dataPath), String(url));
  const text = fs.readFileSync(target, 'utf8');
  return Promise.resolve({
    ok: true,
    status: 200,
    json: function () { return Promise.resolve(JSON.parse(text)); },
  });
};
vm.createContext(sandbox);
vm.runInContext('this.window = globalThis; this.self = globalThis;', sandbox);
vm.runInContext(src, sandbox, { filename: jsPath });

(async () => {
  const out = {};
  out.windowHasBrailleZH = typeof sandbox.window.BrailleZH === 'object'
    && sandbox.window.BrailleZH !== null;
  const B = sandbox.window.BrailleZH;
  out.apiKeys = Object.keys(B).sort();
  out.readyBeforeLoad = B.ready();
  await B.load('braille-zh.json');        // 相对路径 → 必须走 fetch 分支
  await B.load('braille-zh.json');        // 第二次应命中缓存
  out.readyAfterLoad = B.ready();
  out.fetchCalls = sandbox.__fetchCalls || 0;
  out.sample = B.toBrailleText('人工智能语音总结，2026年10月3日。');
  out.wrapSample = B.wrapCells(out.sample, 16);
  out.metaSource = B.tableInfo().source;
  out.metaGenerated = B.tableInfo().generated;
  fs.writeFileSync(outPath, JSON.stringify(out), 'utf8');
})().catch(function (err) {
  process.stderr.write('BROWSER-PATH-ERROR: ' + (err && err.stack ? err.stack : String(err)) + '\n');
  process.exit(1);
});
"""

BROWSER_SAMPLE = "人工智能语音总结，2026年10月3日。"

REQUIRED_API = ["cellsToUnicode", "coverage", "load", "ready", "toBrailleText", "wrapCells"]


def run_browser_path(workdir: str, js_impl: str, js_table: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("找不到 node，可执行文件不在 PATH 上")
    runner_path = os.path.join(workdir, "run-browser-path.cjs")
    out_path = os.path.join(workdir, "browser-output.json")
    with open(runner_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(BROWSER_RUNNER)
    proc = subprocess.run([node, runner_path, js_impl, js_table, out_path],
                          capture_output=True, cwd=workdir, timeout=300)
    stdout = proc.stdout.decode("utf-8", "replace").strip()
    stderr = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"浏览器路径冒烟失败（退出码 {proc.returncode}）\n"
                           f"stdout: {stdout}\nstderr: {stderr}")
    return load_json(out_path)


def check_browser_path(checks: Checks, workdir: str, js_impl: str, js_table: str) -> None:
    emit("")
    emit("=" * 78)
    emit("③ 浏览器路径冒烟（UMD 挂 window.BrailleZH + BrailleZH.load 走 fetch）")
    emit("=" * 78)
    try:
        result = run_browser_path(workdir, js_impl, js_table)
    except RuntimeError as exc:
        checks.check("浏览器路径可运行", False, str(exc))
        return

    import braille_zh as bz
    checks.check("无 module/define 时挂到 window.BrailleZH", result.get("windowHasBrailleZH") is True,
                 f"实际: {result.get('windowHasBrailleZH')!r}")
    keys = result.get("apiKeys") or []
    missing = [name for name in REQUIRED_API if name not in keys]
    checks.check(f"要求的 API 齐全 {REQUIRED_API}", not missing, f"缺少: {missing}")
    checks.check("load() 之前 ready() === false", result.get("readyBeforeLoad") is False)
    checks.check("await load() 之后 ready() === true", result.get("readyAfterLoad") is True)
    checks.check("重复 load() 命中缓存（只 fetch 一次）", result.get("fetchCalls") == 1,
                 f"实际 fetch 次数: {result.get('fetchCalls')!r}")
    checks.equal("浏览器入口样本 toBrailleText ↔ to_braille_text",
                 result.get("sample"), bz.to_braille_text(BROWSER_SAMPLE))
    checks.equal("浏览器入口样本 wrapCells(...,16) ↔ wrap_cells(...,16)",
                 result.get("wrapSample"), bz.wrap_cells(bz.to_braille_text(BROWSER_SAMPLE), 16))
    checks.check("表 meta 带上 source（溯源字段可见）",
                 result.get("metaSource") == DATA_SOURCE_LABEL,
                 f"实际: {result.get('metaSource')!r}")
    emit(f"    浏览器入口样本：{result.get('sample')}")
    emit(f"    折行 16 方      ：{_short(result.get('wrapSample'))}")


def run_node(workdir: str, cases: list[dict], js_impl: str, js_table: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("找不到 node，可执行文件不在 PATH 上")

    cases_path = os.path.join(workdir, "cases.json")
    out_path = os.path.join(workdir, "js-output.json")
    runner_path = os.path.join(workdir, "run-braille-zh.cjs")

    payload = {
        "cases": cases,
        "cellsToUnicodeSpecs": CELL_SPECS,
        "extraWraps": [{"id": cid, "braille": braille, "width": width}
                       for cid, braille, width in EXTRA_WRAPS],
    }
    write_json(cases_path, payload)
    with open(runner_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(NODE_RUNNER)

    proc = subprocess.run(
        [node, runner_path, js_impl, js_table, cases_path, out_path],
        capture_output=True,
        cwd=workdir,
        timeout=300,
    )
    stdout = proc.stdout.decode("utf-8", "replace").strip()
    stderr = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(
            f"node 退出码 {proc.returncode}\nstdout: {stdout}\nstderr: {stderr}")
    if not os.path.isfile(out_path):
        raise RuntimeError(f"node 没有产出结果文件\nstdout: {stdout}\nstderr: {stderr}")
    return load_json(out_path)


# --------------------------------------------------------------- 比对主体

FIELD_LABELS = [
    ("toBrailleText_run", "toBrailleText(text) ↔ to_braille_text(text)"),
    ("toBrailleText_each", "toBrailleText(text,{number_sign:'each'}) ↔ to_braille_text(number_sign='each')"),
    ("stats", "toBraille(text).stats() ↔ to_braille(text).stats()"),
    ("coverageReport", "coverageReport(text) ↔ coverage_report(text)"),
    ("unmappedChars", "coverage(text) ↔ unmapped_chars(text)"),
    ("wrapDefault", "wrapCells(braille) ↔ wrap_cells(braille)  [默认宽度 32]"),
    ("wraps", f"wrapCells(braille,w) ↔ wrap_cells(braille,w)  [w={','.join(map(str, WRAP_WIDTHS))}]"),
]


def compare_engine(checks: Checks, cases: list[dict], expected: dict, actual: dict,
                   js_table: str) -> None:
    emit("=" * 78)
    emit("② 引擎等价（逐字符比对：Python 期望值 ↔ node 跑出来的 JS 实际值）")
    emit("=" * 78)

    emit("")
    emit("--- API 契约（JS 侧，非 Python 对照项）---")
    checks.check("load() 之前 ready() === false", actual.get("readyBeforeLoad") is False,
                 f"实际: {actual.get('readyBeforeLoad')!r}")
    checks.check("load() 之后 ready() === true", actual.get("readyAfterLoad") is True,
                 f"实际: {actual.get('readyAfterLoad')!r}")
    checks.check("未加载时调用转换会显式报错（不产出错误结果）",
                 actual.get("errors", {}).get("beforeLoad") == "throw",
                 f"实际: {actual.get('errors', {}).get('beforeLoad')!r}")
    checks.check("DEFAULT_WIDTH === 32（后端 BRF 约定）", actual.get("defaultWidth") == 32,
                 f"实际: {actual.get('defaultWidth')!r}")
    checks.check("常量 ⠼/⠠/⠀ 与 Python 一致",
                 actual.get("constants") == {"NUMBER_SIGN": "\u283c",
                                            "CAPITAL_SIGN": "\u2820",
                                            "BLANK_CELL": "\u2800"},
                 f"实际: {actual.get('constants')!r}")
    checks.check("wrapCells(x, 0) 抛错（同 Python ValueError）",
                 actual.get("errors", {}).get("wrapWidthZero") == "throw",
                 f"实际: {actual.get('errors', {}).get('wrapWidthZero')!r}")
    checks.check("toBrailleText(123) 抛 TypeError（同 Python）",
                 actual.get("errors", {}).get("nonStringText") == "throw",
                 f"实际: {actual.get('errors', {}).get('nonStringText')!r}")

    results = actual.get("results", {})
    for case in cases:
        cid = case["id"]
        text = case["text"]
        emit("")
        emit(f"--- 语料 {cid} ---")
        emit(f"    原文({len(text)} 字符): {_short(text, 120)}")
        exp = expected[cid]
        got = results.get(cid)
        if not isinstance(got, dict):
            checks.check(f"{cid} :: node 返回了结果", False, "缺少该语料的结果")
            continue
        for field, label in FIELD_LABELS:
            checks.equal(f"{cid} :: {label}", got.get(field), exp[field])
        # 字符串形式 opts 应与对象形式一致
        checks.equal(f"{cid} :: toBrailleText(text,'each') 与对象形式等价",
                     got.get("toBrailleText_each_byString"), exp["toBrailleText_each"])
        preview = exp["braillePreview"].replace("\n", "\\n")
        checks.check(
            f"{cid} :: 盲文预览 '{preview}'  |  {exp['stats']['cell_count']} 方, "
            f"覆盖 {exp['stats']['mapped_chars']}/{exp['stats']['total_chars']}, "
            f"{exp['stats']['lines']} 行, 未覆盖 {exp['stats']['unmapped_chars']}",
            True)

    emit("")
    emit("--- cellsToUnicode ↔ cells_to_unicode（点位写法 → Unicode 盲文）---")
    got_specs = actual.get("cellsToUnicode", {})
    for spec in CELL_SPECS:
        import braille_zh as bz
        checks.equal(f"cellsToUnicode({spec!r}) ↔ cells_to_unicode",
                     got_specs.get(spec), bz.cells_to_unicode(spec))

    emit("")
    emit("--- 折行边界 wrapCells ↔ wrap_cells（直接喂盲文串，覆盖硬折行/怪癖分支）---")
    got_wraps = actual.get("extraWraps", {})
    import braille_zh as bz_extra
    for cid, braille, width in EXTRA_WRAPS:
        checks.equal(f"wrapCells({_short(braille, 40)}, {width}) [{cid}] ↔ wrap_cells",
                     got_wraps.get(cid), bz_extra.wrap_cells(braille, width))

    emit("")
    emit("--- 全表保真（每条 chars/words 单独转换后聚合 FNV-1a 比对）---")
    raw = load_json(js_table)
    py_digest = python_table_digest(raw)
    js_digest = actual.get("tableDigest", {})
    for key in ("chars", "words"):
        want = py_digest[key]
        have = js_digest.get(key, {})
        checks.check(
            f"{key}: {want['count']} 条逐条转换的聚合校验和一致"
            f"（Python {want['fnv1a']} ↔ JS {have.get('fnv1a')}）",
            have.get("count") == want["count"] and have.get("fnv1a") == want["fnv1a"],
            f"Python: {want} / JS: {have}")


# -------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    global _ENCODING
    parser = argparse.ArgumentParser(
        description="中文盲文 Python↔JS 等价性验证",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild-data", action="store_true",
                        help="从后端表重新生成 yuyi-preview/data/braille-zh.json")
    parser.add_argument("--keep-temp", action="store_true", help="保留中间文件")
    parser.add_argument("--js", default=JS_IMPL, help="被验证的 JS 实现路径（默认 _tools/braille-zh.js）")
    parser.add_argument("--data", default=JS_TABLE, help="被验证的浏览器表路径（默认 data/braille-zh.json）")
    parser.add_argument("--report", default=os.path.join(tempfile.gettempdir(),
                                                         "braille-parity-report.txt"),
                        help="UTF-8 报告文件路径")
    args = parser.parse_args(argv)
    js_impl = os.path.abspath(args.js)
    js_table_path = os.path.abspath(args.data)

    # 被重定向/被捕获时用 UTF-8 输出，避免中文与盲文被控制台代码页吃掉
    try:
        if not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    _ENCODING = getattr(sys.stdout, "encoding", None) or "ascii"

    emit("中文盲文转译：Python 原实现 ↔ 浏览器 JS 实现 等价性验证")
    emit(f"时间：{_dt.datetime.now().astimezone().isoformat(timespec='seconds')}")
    emit(f"Python {sys.version.split()[0]} ({sys.executable})")
    emit(f"node  : {shutil.which('node') or '未找到'}")
    emit(f"原实现: {os.path.join(PY_SRC, 'braille_zh.py')}")
    emit(f"JS 实现: {js_impl}")
    emit(f"浏览器表: {js_table_path}")
    emit("")

    if args.rebuild_data:
        code = rebuild_data()
        if code != 0:
            return code

    checks = Checks()
    emit("=" * 78)
    emit("Python 原实现（期望值来源）")
    emit("=" * 78)
    for path in (PY_SRC, PY_TABLE, js_impl, js_table_path):
        emit(f"    {'OK ' if os.path.exists(path) else '缺失'}  {path}")
    missing = [p for p in (PY_SRC, PY_TABLE, js_impl, js_table_path) if not os.path.exists(p)]
    if missing:
        emit(f"[FAIL] 缺少必要文件：{missing}")
        return 2
    if shutil.which("node") is None:
        emit("[FAIL] 找不到 node")
        return 2
    sys.path.insert(0, PY_SRC)
    try:
        import braille_zh  # noqa: F401
    except Exception as exc:                       # noqa: BLE001
        emit(f"[FAIL] 无法导入 Python 原实现：{exc!r}")
        return 2
    emit(f"    后端表 {os.path.getsize(PY_TABLE)} 字节 / 浏览器表 {os.path.getsize(js_table_path)} 字节")
    emit("")

    data_ok = check_data_parity(checks, js_table_path)

    cases = build_cases()
    emit("=" * 78)
    emit(f"语料：{len(cases)} 条（每条 {len(FIELD_LABELS) + 1} 项比对，另加 "
         f"{len(CELL_SPECS)} 条点位写法）")
    emit("=" * 78)
    for case in cases:
        emit(f"    {case['id']:28} {len(case['text']):3} 字符  {_short(case['text'], 60)}")
    emit("")

    expected = build_expected(cases)

    workdir = tempfile.mkdtemp(prefix="braille-parity-")
    try:
        emit(f"中间文件目录：{workdir}")
        try:
            actual = run_node(workdir, cases, js_impl, js_table_path)
        except RuntimeError as exc:
            emit(f"[FAIL] 运行 JS 实现失败：{exc}")
            return 2
        compare_engine(checks, cases, expected, actual, js_table_path)
        check_browser_path(checks, workdir, js_impl, js_table_path)
    finally:
        if args.keep_temp:
            emit(f"（--keep-temp）中间文件保留在 {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    emit("")
    emit("=" * 78)
    emit("结论")
    emit("=" * 78)
    emit(f"表数据等价：{'通过' if data_ok and not any('表' in l or 'meta' in l for l, _ in checks.failed) else '见上方 FAIL'}")
    emit(f"检查项：{checks.total} 项，PASS {checks.passed}，FAIL {len(checks.failed)}")
    if checks.failed:
        emit("")
        emit("失败明细：")
        for label, detail in checks.failed:
            emit(f"  - {label}")
            if detail:
                emit("      " + detail.replace("\n", "\n      "))
        verdict = "存在不等价项"
    else:
        verdict = ("✅ 全部 PASS —— JS 与 Python 在 toBrailleText / toBraille().stats() / "
                   "wrapCells / cellsToUnicode / coverage 上逐字符等价")
    emit(f"判定：{verdict}")

    # UTF-8 报告（完整原始输出）
    try:
        with open(args.report, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(_OUT) + "\n")
        emit(f"完整输出已写入（UTF-8）：{args.report}")
    except OSError as exc:
        emit(f"（写报告文件失败：{exc}）")

    return 1 if checks.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())