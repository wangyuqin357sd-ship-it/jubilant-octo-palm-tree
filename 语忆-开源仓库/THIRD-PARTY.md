# 第三方组件与许可

语忆本体（前端、安卓壳、工具脚本）是 **MIT**，见 [LICENSE](LICENSE)。

但仓库里有**三处不是我们写的东西**，下面逐条写清来源、许可、以及「仓库里有没有它」。
凡是**不在仓库里**的，都给了可重复执行的获取方式。

---

## 1. 中文盲文查表数据 —— 派生自 Liblouis（⚠️ LGPL-2.1-or-later）

| 项 | 值 |
|---|---|
| 仓库内文件 | `data/braille-zh.json`（927.9 KB，44,388 条映射，表数据）<br>查表引擎（MIT，本项目写的）：`_tools/braille-zh.js`、`android/assets/lib/braille-zh.js` |
| 上游 | **Liblouis** —— `tables/zh-chn.ctb` |
| 上游许可 | **LGPL-2.1-or-later** |
| 表内自述 | `meta.upstream = "liblouis tables/zh-chn.ctb"`、`meta.upstream_license = "LGPL-2.1-or-later"`、`meta.upstream_origin = "data\vendor\zh-chn.ctb"` |
| 表名 | `Chinese Mainland Braille (现行盲文 / 汉语盲文) lookup table` |
| 点位记法 | 点号区间，如 `"3-456"`；`"0"` 表示空方 |
| 条数构成 | `chars` 21,034 + `words` 23,354 = **44,388**（另有 `digits` 10、`upper` 26、`lower` 26） |
| 生成器 | `meta.generator = "tools/build_braille_table.py"`，生成于 2026-10-03 |

**这一条要特别注意**：Liblouis 的盲文表是 **LGPL-2.1-or-later**。
LGPL 是有传染性的许可，所以：

- `data/braille-zh.json` **不受本仓库的 MIT 覆盖**，它随 LGPL-2.1-or-later 走。
- 再分发本仓库时，请保留本文件与 `LICENSE` 末尾的许可范围说明。
- 我们做的是「把上游表数据转成 JSON 查表结构」+ 一个查表引擎（`braille-zh.js`，
  由本项目编写，是 MIT）；**没有修改 Liblouis 的表规则本身**。
- 如果你打算商用，建议自行复核 LGPL 的合规姿势，或改用其它许可的盲文表。

> 说明：`_tools/braille-zh.js` / `android/assets/**/braille-zh.js` 是查表**引擎**（MIT），
> 它们运行时加载上面的表数据；引擎本身不含任何盲文点位。

---

## 2. 离线语音识别引擎 —— vosk-browser（Apache-2.0，**不在仓库里**）

| 项 | 值 |
|---|---|
| 文件 | `data/asr/vosk.js`（5,804,767 B ≈ 5.8 MB） |
| 版本 | `vosk-browser@0.0.8` 的 UMD 单文件包 |
| 许可 | **Apache-2.0** |
| 为什么不在仓库里 | 5.8 MB 第三方产物，属「可重新下载」的东西，不进版本库 |
| 怎么拿回来 | `python _tools/fetch-asr-wasm.py` |

`vosk.js` 的特殊之处（`_tools/fetch-asr-wasm.py` 里也写了）：它把 libvosk 的 WASM
以 **base64 data-URI 内嵌**，Web Worker 也内嵌，所以**不需要**额外的 `.wasm` 或 worker 文件。

---

## 3. 中文识别模型 —— vosk-model-small-cn-0.22（Apache-2.0，**不在仓库里**）

| 项 | 值 |
|---|---|
| 文件 | `data/asr/model.tar.gz`（43,890,403 B ≈ 41.9 MB） |
| 模型 | `vosk-model-small-cn-0.22`（Vosk 官方中文小模型） |
| 许可 | **Apache-2.0** |
| 体积说明 | 原始模型目录 68,292,271 B，gzip 后为 64.3% |
| 为什么不在仓库里 | 41.9 MB 二进制，且是第三方模型，不进版本库 |
| 怎么拿回来 | `python _tools/fetch-asr-wasm.py` |

打包约定（不是猜的，是读 `vosk-browser` 源码 `dist/vosk.js` 得出的）：
tar.gz 里保留**单个顶层目录** `vosk-model-small-cn-0.22/`，
`vosk-browser` 用 `stripFirstComponent=true` 解包，解出来正好是 `am/ conf/ graph/ …`。
详见 `data/asr/README.md`。

---

## 4. 其余工具链（运行期下载，均不进仓库）

| 组件 | 许可 | 用途 | 获取方式 |
|---|---|---|---|
| OpenJDK 17（Adoptium/TUNA） | GPL-2.0-with-classpath-exception | 编译 Java / keytool / d8 | 见 [docs/BUILD.md](docs/BUILD.md) |
| Android build-tools r34 | Apache-2.0 | aapt2 / zipalign / apksigner | 同上 |
| Android platform-34 (`android.jar`) | Apache-2.0 | 编译期 bootclasspath | 同上 |
| Python `cryptography` | Apache-2.0 / BSD | 自签局域网 HTTPS 证书 | `pip install cryptography` |
| Chromium headless shell（可选） | BSD-3-Clause | 跑 `_tools/verify-*.ps1` 回归 | 随 Playwright 安装 |

以上都只在**开发机**上出现，不随本仓库分发。

---

## 5. 字体与图形

界面**不含任何第三方字体或图标文件**：图标是内联 SVG / Unicode 字符，
字体走系统默认（`system-ui` / 思源黑体等），因此没有字体许可问题。

---

## 6. 我们没用的东西（也给个交代）

- **没有**任何分析/埋点 SDK、没有广告 SDK、没有崩溃上报。
- **没有**从任何闭源项目拷贝的代码。`data/`、`_tools/`、`android/src/` 里的实现都是本项目写的
  （盲文**表数据**除外，见第 1 条 —— 那是 Liblouis 的 LGPL 数据）。
- 少数脚本注释里提到过作者本机的兄弟项目目录名，那只是**出处说明**，不是被拷贝的代码；
  详见 [docs/VERIFICATION.md](docs/VERIFICATION.md) 的「脱敏与出处」一节。