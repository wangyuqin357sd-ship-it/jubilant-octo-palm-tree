#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 ``yuyi-preview/_tools/match-cmd.js`` —— 逐条断言 + 混淆矩阵。

这个脚本不是「跑一遍看看」，而是**每条用例都写死期望 key 并断言**：

* 标准说法 / 口语变体 / 语气词 / 语序变化 / 谐音唤醒词 / 干扰输入；
* 容易串台的成对指令单独再断言一次（打开待办 vs 待办事项提醒、
  总结 vs 重新总结、导出盲文 vs 先不导出、打开笔记 vs AI 总结笔记 …）；
* 录音中只放行 ``end`` / ``todoAck`` 的约束、弹窗应答词的开关、
  ``score`` 的取值范围；
* **内嵌表和 data/asr-phrases.json 必须逐字段一致**（表漂移直接 FAIL）；
* 末尾打印**混淆矩阵**（期望 key × 实际 key），串台一眼可见。

任一条 FAIL → 退出码 1；全 PASS → 0。

跑法：
    python _tools/verify-match-cmd.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
MATCH_JS = ROOT / "_tools" / "match-cmd.js"
PHRASES_JSON = ROOT / "data" / "asr-phrases.json"
NULL = "(null)"

# 与 match-cmd.js 内嵌表同步时要逐字段比对的字段（顺序无关）
TABLE_FIELDS = ("version", "wake", "rules", "fillers", "commands", "dialog")


# --------------------------------------------------------------------------- #
# 用例：(分类, 识别原文, opts, 期望 key, 期望 role)
# --------------------------------------------------------------------------- #
CASES: list[tuple[str, str, dict, str | None, str | None]] = [
    # ---- 标准说法：就是页面 chip / 提示语里那句 ----
    ("标准说法", "打开原音频", {}, "navAudio", None),
    ("标准说法", "打开待办", {}, "navTodo", None),
    ("标准说法", "打开笔记", {}, "navNote", None),
    ("标准说法", "打开目录", {}, "navCatalog", None),
    ("标准说法", "打开导出记录", {}, "navExports", None),
    ("标准说法", "打开接口配置", {}, "navAiCfg", None),
    ("标准说法", "打开帮助", {}, "navHelp", None),
    ("标准说法", "打开我的", {}, "navMe", None),
    ("标准说法", "回到首页", {}, "navHome", None),
    ("标准说法", "开始录音", {}, "start", None),
    ("标准说法", "结束录音", {}, "end", None),
    ("标准说法", "重新总结", {}, "summarize", None),
    ("标准说法", "AI 总结笔记", {}, "note", None),
    ("标准说法", "待办事项提醒", {}, "todoStart", None),
    ("标准说法", "知道了", {}, "todoAck", None),
    ("标准说法", "延后十分钟", {}, "todoSnooze", None),
    ("标准说法", "导出盲文", {}, "export", None),
    ("标准说法", "取消", {}, "cancel", None),
    ("标准说法", "搜索", {}, "search", None),
    ("标准说法", "重复", {}, "repeat", None),
    ("标准说法", "返回", {}, "back", None),
    ("标准说法", "退出", {}, "exit", None),
    ("标准说法", "帮助", {}, "help", None),
    # ---- 口语变体：用户实测说过的那些 ----
    ("口语变体", "小语，结束吧", {}, "end", None),
    ("口语变体", "我结束了", {}, "end", None),
    ("口语变体", "好了结束", {}, "end", None),
    ("口语变体", "小语结束录音", {}, "end", None),
    ("口语变体", "小语帮我打开原音频", {}, "navAudio", None),
    ("口语变体", "打开一下待办", {}, "navTodo", None),
    ("口语变体", "待办在哪儿", {}, "navTodo", None),
    ("口语变体", "看看我的待办", {}, "navTodo", None),
    ("口语变体", "帮我导出盲文文档", {}, "export", None),
    ("口语变体", "导成中文 Word", {}, "export", None),
    ("口语变体", "先不导出", {}, "cancel", None),
    ("口语变体", "这个不需要", {}, "cancel", None),
    ("口语变体", "不用了", {}, "cancel", None),
    ("口语变体", "小语，知道了", {}, "todoAck", None),
    ("口语变体", "行了停", {}, "todoAck", None),
    ("口语变体", "等会儿再提醒我", {}, "todoSnooze", None),
    ("口语变体", "小语，打开目录", {}, "navCatalog", None),
    ("口语变体", "打开设置", {}, "navMe", None),
    ("口语变体", "小语，开始录音", {}, "start", None),
    # ---- 语气词 / 填充词：前缀、后缀、句中都要处理 ----
    ("语气词", "嗯……那个，帮我打开一下待办吧", {}, "navTodo", None),
    ("语气词", "麻烦你啦，帮我导出一下盲文", {}, "export", None),
    ("语气词", "我想返回上一步", {}, "back", None),
    ("语气词", "请重复一下", {}, "repeat", None),
    ("语气词", "算了，取消吧", {}, "cancel", None),
    ("语气词", "小语啊，退出吧", {}, "exit", None),
    ("语气词", "好了，明白了", {}, "todoAck", None),
    ("语气词", "能不能帮我打开原声", {}, "navAudio", None),
    # ---- 语序变化：关键词在后面也能认 ----
    ("语序变化", "待办帮我打开", {}, "navTodo", None),
    ("语序变化", "原音频打开一下", {}, "navAudio", None),
    ("语序变化", "盲文导出", {}, "export", None),
    ("语序变化", "目录打开", {}, "navCatalog", None),
    # ---- 谐音唤醒词（沿用 index.html 的 WAKE_WORDS） ----
    ("谐音唤醒", "小语", {}, "wake", None),
    ("谐音唤醒", "你好小语", {}, "wake", None),
    ("谐音唤醒", "小雨，打开待办", {}, "navTodo", None),
    ("谐音唤醒", "晓宇，结束吧", {}, "end", None),
    ("谐音唤醒", "小v，打开目录", {}, "navCatalog", None),
    ("谐音唤醒", "小羽打开我的", {}, "navMe", None),
    # ---- 容易混淆的成对指令（同时验证不串台） ----
    ("易混淆成对", "打开待办", {}, "navTodo", None),
    ("易混淆成对", "待办事项提醒", {}, "todoStart", None),
    ("易混淆成对", "提醒我", {}, "todoStart", None),
    ("易混淆成对", "总结", {}, "note", None),
    ("易混淆成对", "重新总结", {}, "summarize", None),
    ("易混淆成对", "重新总结一下", {}, "summarize", None),
    ("易混淆成对", "导出盲文", {}, "export", None),
    ("易混淆成对", "导出中文 Word 文档", {}, "export", None),
    ("易混淆成对", "导出盲文 BRF", {}, "export", None),
    ("易混淆成对", "先不导出", {}, "cancel", None),
    ("易混淆成对", "打开笔记", {}, "navNote", None),
    ("易混淆成对", "AI 总结笔记", {}, "note", None),
    ("易混淆成对", "打开帮助", {}, "navHelp", None),
    ("易混淆成对", "帮助", {}, "help", None),
    ("易混淆成对", "我的", {}, "navMe", None),
    # ---- 干扰输入：必须老老实实返回 null ----
    ("应当 null", "今天天气不错", {}, None, None),
    ("应当 null", "我们下课吧", {}, None, None),
    ("应当 null", "这个函数怎么写", {}, None, None),
    ("应当 null", "我们总结一下今天的内容", {}, None, None),
    ("应当 null", "打开课本第三页", {}, None, None),
    ("应当 null", "老师刚才讲的目录结构很重要", {}, None, None),
    ("应当 null", "这段代码为什么要用递归", {}, None, None),
    ("应当 null", "", {}, None, None),
    ("应当 null", "，。！？……", {}, None, None),
    # ---- 约束：录音中只放行 end / todoAck ----
    ("录音约束", "小语，结束", {"recording": True}, "end", None),
    ("录音约束", "知道了", {"recording": True}, "todoAck", None),
    ("录音约束", "打开目录", {"recording": True}, None, None),
    ("录音约束", "小语，开始录音", {"recording": True}, None, None),
    ("录音约束", "重新总结", {"recording": True}, None, None),
    # ---- 约束：弹窗应答词只在弹窗打开时生效 ----
    ("弹窗应答", "需要", {}, None, None),
    ("弹窗应答", "需要", {"dialog": True}, "summarize", "affirm"),
    ("弹窗应答", "不用", {"dialog": True}, "cancel", "deny"),
    ("弹窗应答", "先不导出", {"dialog": True}, "cancel", "deny"),
    ("弹窗应答", "知道了", {"dialog": True}, "todoAck", None),
]

# 成对指令：必须各归各位，互不串台
PAIRS = [
    (("打开待办", {}), "navTodo", ("待办事项提醒", {}), "todoStart"),
    (("待办在哪儿", {}), "navTodo", ("提醒我", {}), "todoStart"),
    (("总结", {}), "note", ("重新总结", {}), "summarize"),
    (("导出盲文", {}), "export", ("先不导出", {}), "cancel"),
    (("导出中文 Word 文档", {}), "export", ("别导出", {}), "cancel"),
    (("打开笔记", {}), "navNote", ("AI 总结笔记", {}), "note"),
    (("打开帮助", {}), "navHelp", ("帮助", {}), "help"),
    (("打开我的", {}), "navMe", ("我的", {}), "navMe"),
]

RUNNER_JS = r"""
const fs = require("fs");
const M = require(process.argv[2]);
const payload = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const results = payload.cases.map(function (c) {
  let result = null, error = null;
  try { result = M.match(c.text, c.opts || {}); }
  catch (e) { error = String((e && e.message) || e); }
  let detail = null;
  try { detail = M.explain(c.text, c.opts || {}); } catch (e) { detail = null; }
  return { text: c.text, opts: c.opts || {}, result: result, error: error, explain: detail };
});
fs.writeFileSync(process.argv[4], JSON.stringify({
  ok: true, version: M.VERSION, table: M.TABLE, results: results
}, null, 1), "utf8");
"""


def run_node(cases: list[dict]) -> dict:
    work = Path(tempfile.mkdtemp(prefix="yuyi-verify-"))
    runner = work / "runner.js"
    inp = work / "in.json"
    outp = work / "out.json"
    runner.write_text(RUNNER_JS, encoding="utf-8")
    inp.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(runner), str(MATCH_JS), str(inp), str(outp)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if proc.returncode != 0 or not outp.is_file():
        raise SystemExit("node 跑 match-cmd.js 失败：\n" + (proc.stderr or proc.stdout or "")[:2000])
    return json.loads(outp.read_text(encoding="utf-8"))


def strip_private(value):
    """去掉 JSON 里以下划线开头的说明字段，剩下的就是要和内嵌表逐字段比对的内容。"""
    if isinstance(value, dict):
        return {k: strip_private(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [strip_private(v) for v in value]
    return value


def main() -> int:
    print("语忆 · match-cmd.js 验证")
    print("=" * 78)
    failures: list[str] = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not ok:
            failures.append(label + (f"  {detail}" if detail else ""))

    # ---- 0) 前置：文件都在 ----
    check(MATCH_JS.is_file(), f"文件存在：{MATCH_JS.name}")
    check(PHRASES_JSON.is_file(), f"文件存在：{PHRASES_JSON.name}")
    if failures:
        return 1

    # ---- 1) 跑用例 ----
    payload = [{"text": t, "opts": o} for _, t, o, _, _ in CASES]
    data = run_node(payload)
    results = data["results"]

    # ---- 2) 内嵌表与 data/asr-phrases.json 必须逐字段一致 ----
    doc = json.loads(PHRASES_JSON.read_text(encoding="utf-8"))
    expected_table = strip_private({k: doc[k] for k in TABLE_FIELDS})
    embedded = strip_private(data["table"])
    if embedded == expected_table:
        check(True, "内嵌表与 data/asr-phrases.json 逐字段一致",
              f"({len(embedded['commands'])} 命令 + {len(embedded['dialog'])} 弹窗应答)")
    else:
        diff = []
        for field in TABLE_FIELDS:
            if embedded.get(field) != expected_table.get(field):
                diff.append(field)
        check(False, "内嵌表与 data/asr-phrases.json 不一致", f"不同字段：{diff}（改表后要重新生成）")

    # ---- 3) 逐条断言 ----
    print("\n  ── 逐条断言（期望 key 写死在用例里）──")
    current = ""
    for (category, text, opts, want, want_role), got in zip(CASES, results):
        if category != current:
            current = category
            print(f"\n  【{category}】")
        if got["error"]:
            check(False, f"{text!r}", f"抛异常：{got['error']}")
            continue
        res = got["result"]
        actual = res["key"] if res else NULL
        label = f"{text!r}" + (f" opts={opts}" if opts else "")
        ok = (actual == want) if want is not None else (res is None)
        detail = f"期望 {want or NULL}，实际 {actual}"
        if ok and res is not None:
            detail += f" score={res['score']} matched={res.get('matched', '')}"
            if want_role is not None and res.get("role") != want_role:
                ok = False
                detail += f"（role 期望 {want_role}，实际 {res.get('role')}）"
        elif not ok and res is None:
            detail += f"（explain.wake={got['explain']['wake']}）"
        check(ok, label, detail)

    # ---- 4) score 取值范围 ----
    print("\n  ── 分数契约（0 ≤ score ≤ 1；完全一致 = 1.0）──")
    bad_score = []
    exact_not_one = []
    for (category, text, opts, want, _), got in zip(CASES, results):
        res = got["result"]
        if not res:
            continue
        if not (0.0 <= res["score"] <= 1.0):
            bad_score.append(f"{text}→{res['score']}")
        if got["explain"]["best"] and got["explain"]["best"]["exact"] and res["score"] != 1.0:
            exact_not_one.append(f"{text}→{res['score']}")
    check(not bad_score, "所有分数都在 0~1", "、".join(bad_score))
    check(not exact_not_one, "精确命中的分数都是 1.0", "、".join(exact_not_one))

    # ---- 5) 成对指令不串台（单独再断言一次） ----
    print("\n  ── 成对指令不串台 ──")
    pair_payload = []
    for (a, ka, b, kb) in PAIRS:
        pair_payload.append({"text": a[0], "opts": a[1]})
        pair_payload.append({"text": b[0], "opts": b[1]})
    pair_data = run_node(pair_payload)["results"]
    for i, (a, ka, b, kb) in enumerate(PAIRS):
        ra = pair_data[2 * i]["result"]
        rb = pair_data[2 * i + 1]["result"]
        ga = ra["key"] if ra else NULL
        gb = rb["key"] if rb else NULL
        ok = ga == ka and gb == kb
        check(ok, f"{a[0]!r}→{ka} 且 {b[0]!r}→{kb}", f"实际 {ga} / {gb}")

    # ---- 6) 混淆矩阵 ----
    print("\n  ── 混淆矩阵（期望 key × 实际 key）──")
    expected_keys: list[str] = []
    actual_keys: list[str] = []
    for (_, _, _, want, _), got in zip(CASES, results):
        e = want or NULL
        a = got["result"]["key"] if got["result"] else NULL
        if e not in expected_keys:
            expected_keys.append(e)
        if a not in actual_keys:
            actual_keys.append(a)
    expected_keys.sort(key=lambda k: (k == NULL, k))
    actual_keys.sort(key=lambda k: (k == NULL, k))
    matrix = {e: {a: 0 for a in actual_keys} for e in expected_keys}
    for (_, _, _, want, _), got in zip(CASES, results):
        e = want or NULL
        a = got["result"]["key"] if got["result"] else NULL
        matrix[e][a] += 1
    col_w = max(6, *(len(k) for k in actual_keys))
    header = " " * 16 + "".join(k.rjust(col_w + 1) for k in actual_keys)
    print("  " + header)
    for e in expected_keys:
        cells = ""
        for a in actual_keys:
            n = matrix[e][a]
            mark = str(n) if n else "·"
            if n and e != a:
                mark = f"{n}!"                      # 非对角线 = 串台，标个 !
            cells += mark.rjust(col_w + 1)
        print("  " + e.ljust(15) + cells)
    off = sum(matrix[e][a] for e in expected_keys for a in actual_keys if e != a and matrix[e][a])
    check(off == 0, "混淆矩阵对角线以外没有任何一条", f"串台 {off} 条")

    # ---- 7) 汇总 ----
    total = len(CASES) + len(PAIRS)
    print("\n" + "=" * 78)
    print(f"  用例 {len(CASES)} 条 + 成对断言 {len(PAIRS)} 对 = {total} 条断言")
    if failures:
        print(f"  结果：FAIL（{len(failures)} 条）")
        for item in failures:
            print("    ✗ " + item)
        return 1
    print("  结果：全部 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())