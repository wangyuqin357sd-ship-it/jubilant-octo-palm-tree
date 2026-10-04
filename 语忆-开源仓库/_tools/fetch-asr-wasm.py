#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语忆 · 手机端**离线**语音识别：一次性获取 / 打包脚本
================================================================================
为什么需要它
------------
`yuyi-preview/index.html` 原来用浏览器自带的 `webkitSpeechRecognition`。
那个接口**必须联网**（Chrome 会把麦克风音频送到云端换文字），
不满足「完全离线、不联网、不上云」的要求。

本脚本负责把「页面内 WASM 推理」所需的东西一次性准备好，全部落进
`yuyi-preview/data/asr/`，之后页面只从**本机静态服务器**加载，不再需要任何外网：

    data/asr/vosk.js         vosk-browser 0.0.8 的 UMD 单文件包（约 5.8 MB）
                             —— WASM 以 base64 data-URI 内嵌，Web Worker 也以
                                base64 内嵌，**不需要任何额外的 .wasm / worker 文件**
    data/asr/model.tar.gz    中文模型 vosk-model-small-cn-0.22 的 tar.gz 包
    data/asr/manifest.json   体积 / SHA-256 / 版本，供页面与校验脚本核对

为什么模型必须是 **tar.gz**（而不是直接把模型目录丢进去）
----------------------------------------------------------
`vosk-browser` 加载模型的真实约定（读它的源码 dist/vosk.js 得出，不是猜的）：

    worker: load(modelUrl)
      storagePath = "/vosk"
      modelPath   = "/vosk/" + modelUrl.replace(/[\\W]/g, "_")
      FS.mkdir(storagePath); FS.mount(IDBFS, {}, storagePath); FS.syncfs(true)
      Vosk.downloadAndExtract(fullModelUrl, modelPath)
      FS.syncfs(false)                     # 落进 IndexedDB，下次不再下载

    downloadAndExtract(url, localPath):
      archivePath = localPath + "/downloaded.tar.gz"
      fetch(url) -> 存成 downloaded.tar.gz
      extract(archivePath, localPath, /* stripFirstComponent */ true)
      # extract() 调用 wasm 里的 Module.ArchiveHelper.Extract()，用 libarchive 解包
      touchFile(localPath + "/extracted.ok")

关键三点：
  1. 模型是**一个 HTTP 文件**，由 worker `fetch()` 下来，再在 wasm 里解包。
  2. `stripFirstComponent = true` —— 压缩包**必须有一个顶层目录**，
     解包时把这一层剥掉。所以本脚本打包成 `vosk-model-small-cn-0.22/am/...`，
     解出来正好是 `am/ ... conf/ ... graph/ ...`。
     （若打成没有顶层目录的裸 tar，第一层 `am` 会被剥掉，模型直接不可用。）
  3. 解包一次后会写 `extracted.ok` 并同步进 IndexedDB。同一个浏览器第二次打开
     就**跳过下载与解包**，直接命中缓存 —— 首次下载量大，之后很快。

gzip 由 wasm 里的 libarchive 解，**不依赖** HTTP 的 `Content-Encoding`，
所以静态服务器按普通二进制文件发即可，也不需要自己压。

只读承诺
--------
`ai-voice-summary/local-asr/models/vosk-model-small-cn-0.22` 是**只读复用**：
本脚本只 `walk` + `read`，绝不写入、绝不改动该目录及 `ai-voice-summary/**` 下任何文件。

用法
----
    python yuyi-preview/_tools/fetch-asr-wasm.py                 # 缺什么补什么
    python yuyi-preview/_tools/fetch-asr-wasm.py --force         # 全部重做
    python yuyi-preview/_tools/fetch-asr-wasm.py --verify-only   # 只校验不下载
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# 中文输出在 cp936/gbk 控制台下会乱码；统一 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent            # yuyi-preview/_tools
BASE = HERE.parent                                # yuyi-preview/
OUT_DIR = BASE / "data" / "asr"                   # 允许新建的唯一目录

# 只读的模型来源（相对 yuyi-preview）
MODEL_SRC = (BASE.parent / "ai-voice-summary" / "local-asr" / "models"
             / "vosk-model-small-cn-0.22")

VOSK_BROWSER_VERSION = "0.0.8"
ENGINE_NAME = "vosk.js"
MODEL_NAME = "model.tar.gz"
MANIFEST_NAME = "manifest.json"

# 下载源（按顺序尝试）。第一条是 npm registry 的正式 tarball 地址。
TARBALL_URLS = [
    f"https://registry.npmjs.org/vosk-browser/-/vosk-browser-{VOSK_BROWSER_VERSION}.tgz",
    f"https://cdn.jsdelivr.net/npm/vosk-browser@{VOSK_BROWSER_VERSION}/vosk-browser-{VOSK_BROWSER_VERSION}.tgz",
]
# 直接取单文件的兜底 CDN（拿不到 tarball 时用）
RAW_JS_URLS = [
    f"https://cdn.jsdelivr.net/npm/vosk-browser@{VOSK_BROWSER_VERSION}/dist/vosk.js",
    f"https://unpkg.com/vosk-browser@{VOSK_BROWSER_VERSION}/dist/vosk.js",
]

UA = "yuyi-preview-fetch-asr-wasm/1.0"


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def dir_size(path: Path) -> tuple[int, int]:
    """返回 (总字节数, 文件数)。只读遍历。"""
    total = 0
    count = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
            count += 1
    return total, count


def fetch_bytes(url: str, *, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def step(ok: bool, label: str, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" —— {detail}" if detail else ""))


# --------------------------------------------------------------------------- #
# 1) 引擎 vosk.js
# --------------------------------------------------------------------------- #
def looks_like_vosk_bundle(path: Path) -> bool:
    """粗校验：确认拿到的是 UMD 版的 vosk-browser（内嵌 wasm + worker）。"""
    if not path.is_file() or path.stat().st_size < 1_000_000:
        return False
    with open(path, "rb") as handle:
        head = handle.read(4096)
    if b"global.Vosk" not in head:
        return False
    # 尾部应当导出 Model / createModel
    with open(path, "rb") as handle:
        handle.seek(max(0, path.stat().st_size - 4096))
        tail = handle.read()
    return b"createModel" in tail


def obtain_engine(out: Path, *, force: bool) -> dict:
    if out.is_file() and not force and looks_like_vosk_bundle(out):
        print(f"  · {ENGINE_NAME} 已存在（{human(out.stat().st_size)}），跳过下载")
        return {"skipped": True, "source": "existing"}

    workdir = Path(tempfile.mkdtemp(prefix="yuyi-asr-"))
    errors: list[str] = []
    try:
        # --- 路线 A：npm registry tarball（首选） ---
        for url in TARBALL_URLS:
            print(f"  · 尝试下载 tarball：{url}")
            try:
                blob = fetch_bytes(url)
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"{url} -> {exc}")
                print(f"     失败：{exc}")
                continue
            tgz = workdir / "vosk-browser.tgz"
            tgz.write_bytes(blob)
            try:
                with tarfile.open(tgz, "r:gz") as archive:
                    member = next((m for m in archive.getmembers()
                                   if m.isfile() and m.name.endswith("dist/vosk.js")), None)
                    if member is None:
                        raise RuntimeError("压缩包里没有 dist/vosk.js")
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise RuntimeError("压缩包里 dist/vosk.js 读不出来")
                    extracted = workdir / "vosk.js"
                    extracted.write_bytes(handle.read())
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"{url} (解包) -> {exc}")
                print(f"     解包失败：{exc}")
                continue
            if looks_like_vosk_bundle(extracted):
                shutil.copyfile(extracted, out)
                print(f"  · 已从 npm tarball 取出 {ENGINE_NAME}（{human(out.stat().st_size)}）")
                return {"skipped": False, "source": url}
            errors.append(f"{url} -> 内容不像 vosk-browser 包")
            print("     内容不像 vosk-browser 包，换下一个源")

        # --- 路线 B：直接取单文件 CDN ---
        for url in RAW_JS_URLS:
            print(f"  · 尝试直接下载 {ENGINE_NAME}：{url}")
            try:
                blob = fetch_bytes(url)
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"{url} -> {exc}")
                print(f"     失败：{exc}")
                continue
            candidate = workdir / "vosk.js"
            candidate.write_bytes(blob)
            if looks_like_vosk_bundle(candidate):
                shutil.copyfile(candidate, out)
                print(f"  · 已从 CDN 取出 {ENGINE_NAME}（{human(out.stat().st_size)}）")
                return {"skipped": False, "source": url}
            errors.append(f"{url} -> 内容不像 vosk-browser 包")
            print("     内容不像 vosk-browser 包，换下一个源")

        # --- 路线 C：本机 npm（前面都拿不到时才用） ---
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if npm:
            print(f"  · 尝试本机 npm pack：{npm}")
            try:
                completed = subprocess.run(
                    [npm, "pack", f"vosk-browser@{VOSK_BROWSER_VERSION}",
                     "--pack-destination", str(workdir)],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=300, check=False, shell=False)
                tgz = next(iter(workdir.glob("vosk-browser-*.tgz")), None)
                if completed.returncode == 0 and tgz is not None:
                    with tarfile.open(tgz, "r:gz") as archive:
                        member = next((m for m in archive.getmembers()
                                       if m.isfile() and m.name.endswith("dist/vosk.js")), None)
                        if member is not None:
                            handle = archive.extractfile(member)
                            assert handle is not None
                            candidate = workdir / "vosk-npm.js"
                            candidate.write_bytes(handle.read())
                            if looks_like_vosk_bundle(candidate):
                                shutil.copyfile(candidate, out)
                                print(f"  · 已从 npm pack 取出 {ENGINE_NAME}")
                                return {"skipped": False, "source": "npm pack"}
                errors.append(f"npm pack -> rc={completed.returncode} "
                              f"{(completed.stderr or '').strip()[:200]}")
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"npm pack -> {exc}")
        else:
            errors.append("npm pack -> 本机没有 npm")

        raise SystemExit(
            "  ! 拿不到 vosk-browser，所有下载路线都失败：\n"
            + "\n".join(f"      - {e}" for e in errors)
            + "\n    网络不通时请手动下载 vosk-browser 的 dist/vosk.js 放到 "
              f"{out}\n"
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 2) 模型 model.tar.gz
# --------------------------------------------------------------------------- #
def obtain_model(out: Path, *, force: bool) -> dict:
    if not MODEL_SRC.is_dir():
        raise SystemExit(
            f"  ! 找不到本机中文模型目录：{MODEL_SRC}\n"
            "    这个目录是只读复用的来源，必须先存在。"
        )
    raw_bytes, raw_files = dir_size(MODEL_SRC)
    print(f"  · 源模型：{MODEL_SRC}")
    print(f"    只读遍历：{raw_files} 个文件，{human(raw_bytes)}")

    if out.is_file() and not force:
        print(f"  · {MODEL_NAME} 已存在（{human(out.stat().st_size)}），跳过打包"
              "（要重打加 --force）")
        return {"skipped": True, "raw_bytes": raw_bytes, "raw_files": raw_files}

    # 顶层目录名 = 源目录名。stripFirstComponent=true 会把它剥掉。
    top = MODEL_SRC.name
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")

    started = time.time()
    written = 0
    # 固定 mtime=0 → 同样的输入产出同样的包，便于比对
    with open(tmp, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6,
                           mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
                for item in sorted(MODEL_SRC.rglob("*")):
                    relative = item.relative_to(MODEL_SRC)
                    arcname = f"{top}/{relative.as_posix()}"
                    info = tar.gettarinfo(str(item), arcname=arcname)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    if item.is_file():
                        with open(item, "rb") as handle:
                            tar.addfile(info, handle)
                        written += item.stat().st_size
                    else:
                        tar.addfile(info)
    os.replace(tmp, out)
    elapsed = time.time() - started

    print(f"  · 已打包 {MODEL_NAME}：{human(out.stat().st_size)}"
          f"（原始 {human(raw_bytes)}，压缩率 "
          f"{out.stat().st_size / max(1, raw_bytes) * 100:.1f}%，耗时 {elapsed:.1f}s）")
    print(f"    顶层目录：{top}/  （vosk-browser 会用 stripFirstComponent=true 剥掉）")
    return {"skipped": False, "raw_bytes": raw_bytes, "raw_files": raw_files,
            "pack_seconds": round(elapsed, 2)}


def check_tar_layout(path: Path) -> tuple[bool, str]:
    """解包前先自己核一遍：必须只有一个顶层目录，且里面有 am/final.mdl。"""
    try:
        with tarfile.open(path, "r:gz") as archive:
            names = archive.getnames()
    except Exception as exc:                              # noqa: BLE001
        return False, f"打不开：{exc}"
    if not names:
        return False, "空包"
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) != 1:
        return False, f"顶层目录不唯一：{sorted(tops)[:5]}"
    top = tops.pop()
    needed = [f"{top}/am/final.mdl", f"{top}/conf/model.conf"]
    missing = [n for n in needed if n not in names]
    if missing:
        return False, f"缺少 {missing}"
    return True, f"顶层 {top}/，{len(names)} 个条目"


# --------------------------------------------------------------------------- #
# 3) manifest
# --------------------------------------------------------------------------- #
def write_manifest(engine: Path, model: Path, extra: dict) -> dict:
    manifest = {
        "schema": "yuyi-asr-wasm/1",
        "engine": {
            "name": "vosk-browser",
            "version": VOSK_BROWSER_VERSION,
            "license": "Apache-2.0",
            "file": engine.name,
            "bytes": engine.stat().st_size,
            "sha256": sha256_file(engine),
            "note": ("UMD 单文件：libvosk 的 WASM 以 base64 data-URI 内嵌，"
                     "Web Worker 也以 base64 内嵌；不需要额外 .wasm / worker 文件。"),
        },
        "model": {
            "name": MODEL_SRC.name,
            "file": model.name,
            "bytes": model.stat().st_size,
            "sha256": sha256_file(model),
            "raw_bytes": extra.get("raw_bytes"),
            "raw_files": extra.get("raw_files"),
            "layout": "tar.gz，单个顶层目录，vosk-browser 以 stripFirstComponent=true 解包",
        },
        "total_bytes": engine.stat().st_size + model.stat().st_size,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (OUT_DIR / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(
        description="获取 vosk-browser 引擎并把本机中文模型打包成 tar.gz（可重复运行）")
    parser.add_argument("--force", action="store_true", help="已存在也重新下载/打包")
    parser.add_argument("--verify-only", action="store_true", help="只校验现有产物，不下载")
    args = parser.parse_args()

    print()
    print("  语忆 · 离线语音识别（页面内 WASM）准备脚本")
    print("  " + "=" * 70)
    print(f"  输出目录：{OUT_DIR}")
    print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = OUT_DIR / ENGINE_NAME
    model = OUT_DIR / MODEL_NAME

    if args.verify_only:
        problems = []
        if not looks_like_vosk_bundle(engine):
            problems.append(f"{ENGINE_NAME} 缺失或不像 vosk-browser 包")
        if not model.is_file():
            problems.append(f"{MODEL_NAME} 缺失")
        else:
            ok, detail = check_tar_layout(model)
            if not ok:
                problems.append(f"{MODEL_NAME} 结构不对：{detail}")
        for item in problems:
            step(False, item)
        if problems:
            print("\n  校验未通过。跑一次不带参数的脚本即可补齐。\n")
            return 1
        print(f"  [PASS] 产物齐全：{human(engine.stat().st_size)} + "
              f"{human(model.stat().st_size)}")
        print()
        return 0

    print("  ① 引擎 vosk-browser")
    engine_info = obtain_engine(engine, force=args.force)
    step(looks_like_vosk_bundle(engine), "引擎包自检",
         f"{human(engine.stat().st_size)}")
    print()

    print("  ② 中文模型打包")
    model_info = obtain_model(model, force=args.force)
    ok, detail = check_tar_layout(model)
    step(ok, "模型包结构自检", detail)
    print()

    print("  ③ manifest")
    manifest = write_manifest(engine, model, model_info)
    step(True, MANIFEST_NAME,
         f"总体积 {human(manifest['total_bytes'])}")

    print()
    print("  完成。手机首次打开需要下载的总字节数：")
    print(f"      {ENGINE_NAME:<16} {manifest['engine']['bytes']:>10,} B")
    print(f"      {MODEL_NAME:<16} {manifest['model']['bytes']:>10,} B")
    print(f"      {'合计':<14} {manifest['total_bytes']:>10,} B"
          f"  （{human(manifest['total_bytes'])}）")
    print()
    print("  下一步：")
    print("      1) 页面里 data/asr/ 需要能被静态服务器访问到 ——")
    print("         注意 _tools/serve-mobile.py 有一份硬编码白名单 ALLOW，")
    print("         不加条目的话 /data/asr/** 会 404（这是 Lead 的文件，本脚本不改）。")
    print("      2) 跑离线自测：node _tools/verify-asr-wasm.mjs")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())