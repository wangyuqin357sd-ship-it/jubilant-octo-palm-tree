# 语忆 · 验收证据与未验证清单

> 本文分两部分：**① 验过的（带脚本、带数字）** 和 **② 没验过的（诚实列出）**。
> 原则：**宁可显得弱，也不写没验过的话。** 任何数字都能在仓库里找到对应脚本或记录。

---

## 目录

- [1. 验收数字（脚本口径）](#1-验收数字脚本口径)
- [2. 被排除的文件与体积](#2-被排除的文件与体积)
- [3. 脱敏扫描结果（三类，可复跑）](#3-脱敏扫描结果三类可复跑)
- [4. 脱敏与出处（私有项目名引用说明）](#4-脱敏与出处私有项目名引用说明)
- [5. 真机实测](#5-真机实测)
- [6. 未验证清单](#6-未验证清单)
- [7. 仓库体积](#7-仓库体积)

---

## 1. 验收数字（脚本口径）

全部来自 `_tools/` 下的脚本，**每条都给了可复跑的命令**。

| # | 项目 | 结果 | 脚本 | 命令 |
|---|---|---|---|---|
| 1 | **主闸门**（待办振动契约） | **PASS 85 / FAIL 0**，exit 0 | `_tools/verify-todo-vibration.ps1` | `powershell -ExecutionPolicy Bypass -File _tools\verify-todo-vibration.ps1` |
| 2 | docx 生成器独立复核 | **137/137 PASS** | `_tools/verify-docx-mini.py` | `python _tools\verify-docx-mini.py` |
| 3 | 中文盲文独立复核 | **217/217 PASS**（含全表 **44,388** 条聚合校验和与 Python 一致） | `_tools/verify-braille-parity.py` | `python _tools\verify-braille-parity.py` |
| 4 | 盲文**反证** | 故意改坏 5 份副本 → **全部 exit 1** | 同上（负例） | 同上 |
| 5 | 离线识别 | **28/28**（含**阻断全部外部域名**后仍识别成功） | `_tools/verify-asr-offline.py` / `_tools/verify-asr-wasm.mjs` | `python _tools\verify-asr-offline.py` / `node _tools\verify-asr-wasm.mjs` |
| 6 | 导航硬规则 | **49 条路径 / 0 失败** | 由 P0 代理执行的路径遍历（记录在 `_tools/PENDING-FIXES.md:102`） | 见该文件 |
| 7 | 既有三探针 | `throwAt=(none)`、`probe-ok` | `_tools/verify-ui.ps1` / `verify-newflows.ps1` / `verify-newscreens.ps1` | 逐个跑 |
| 8 | 画布排版自检 | `frames:16 groups:102 items:157 [OK]` | `_tools/check-mobile.py` | `python _tools\check-mobile.py` |
| 9 | 静态路由 | `/ /sw.js /lib/docx-mini.js /lib/braille-zh.js /data/braille-zh.json /diag` 全 **200** | 预览服务器 | 起服务后逐个访问 |
| 10 | 安全上下文与能力 | CDP 真实页面探 `isSecureContext`/SW/通知/vibrate/wakeLock | `_tools/check-https-capabilities.mjs` | `node _tools\check-https-capabilities.mjs --url http://127.0.0.1:8790/` |

**几个数字的准确含义**（避免误读）：

- **85 项**：主闸门里的断言条数，**带 exit code**；连跑两次结果一致、无临时文件残留。
- **137/137**：ZIP 结构 + OPC 完整性 + 用 `python-docx` **逐条回读**。
  即「文件是合法 docx 且内容能读回来」，**不等于**「在 Word 里排版好看」（见 [第 6 节](#6-未验证清单)）。
- **217/217 + 44,388**：中文盲文与后端 Python **逐字符等价**（同表、同查表顺序、同数字号/大写符/全角归一化规则）。
  44,388 = 表内 `chars` 21,034 + `words` 23,354（与 `data/braille-zh.json` 的 `meta.counts` 一致）。
- **49 条路径**：快速连点/连续跳转后最终状态正确性（如「笔记→我的→笔记→首页」）。
  注意 `PENDING-FIXES.md` 同时提示：**加了动画之后要重验**。

---

## 2. 被排除的文件与体积

`.gitignore` 逐条写了「为什么」。这是**实测体积**（不是估算）：

| 路径 | 文件数 | 体积 | 排除理由 |
|---|---:|---:|---|
| `android/.toolchain/` | 1,493 | **781.20 MB** | JDK17 + build-tools r34 + platform-34；官方地址可自取（[BUILD.md](BUILD.md)） |
| `android/.build/` | 47 | **133.90 MB** | 构建中间产物，可重建 |
| `android/dist/` | 2 | **44.94 MB** | APK 产物，可重建 |
| `data/asr/model.tar.gz` | 1 | **41.86 MB** | 第三方模型（Apache-2.0），`fetch-asr-wasm.py` 重取 |
| `data/asr/vosk.js` | 1 | **5.54 MB** | 第三方引擎（Apache-2.0），同上 |
| `android/assets/data/asr/model.tar.gz` | 1 | **41.86 MB** | 上面那份的构建期副本 |
| `android/assets/data/asr/vosk.js` | 1 | **5.54 MB** | 同上 |
| `_shots/` | 68 | **15.72 MB** | 原始截图；精选的几张已复制到 `docs/images/` |
| `android/_shots-apk-verify/` | 10 | **2.84 MB** | 原始截图（同上） |
| `android/yuyi-debug.keystore` | 1 | 2.7 KB | ⚠️ **签名私钥**，绝不公开；构建时自动重新生成 |
| `_tools/.cert/key.pem` + `cert.pem` + `sans.txt` | 3 | 2.9 KB | ⚠️ **TLS 私钥**（自签）；`serve-mobile.py` 运行时会自动重签 |
| `design/draft-url.txt` | 1 | 11.4 KB | 11 KB 不透明 base64，本机画布工具的书签 |
| `启动说明.txt` | 1 | 4.2 KB | 内容已过期（引用不存在的 `screenshots\`、`tools\`） |
| `android/_tools/deploy-probe.ps1` | 1 | 3.4 KB | 写死真机序列号 |
| `android/_tools/eval-b64.ps1` | 1 | 1.4 KB | 写死真机序列号 |
| `手机地址.txt` | 1 | 0.4 KB | 写死本机局域网 IP |
| `android/_exported-selftest.docx` | 1 | 3.0 KB | 导出功能的手工验证产物 |
| `design/m3e-exports/` | 0 | 0 | 空目录（画布导出目标） |
| **合计** | **1,634** | **≈ 1,073.41 MB** | |

> `android/probe.txt` 与 `*.log` 也在 `.gitignore` 里，但**当前磁盘上并不存在** —— 属于预防性规则。

复核方式（任何一条都能自己验）：

```powershell
git check-ignore -v android/.toolchain/dl/jdk17.zip
# → .gitignore:10:android/.toolchain/	android/.toolchain/dl/jdk17.zip
```

---

## 3. 脱敏扫描结果（三类，可复跑）

扫描对象 = **`git ls-files` 里真正会提交的文件**（未提交的不算，所以先 `git add` 再扫）。

### 3.1 私有网段前缀 → **0 处**

> 本文档为了能自证「0 处」，**不写出这个前缀的字面量**，而用拼接的方式表达模式：

```powershell
$pat = '192' + '\.168\.'      # 拆开写，避免本文档自己命中自己要检验的模式
Select-String -Path $paths -Pattern $pat -Encoding UTF8
```

```
MATCHES: 0
```

顺带扫**真实私有 IPv4**（三段私有网段：192.168 段、10 段、172.16–31 段，模式同样拆开写）：**0 处**。

> **本次为达到 0 处做了 6 处脱敏**（全部是文本改动，行为不变；**原值不再在本文档复述**）：
> | 文件 | 原来是什么 | 改成 |
> |---|---|---|
> | `_tools/HANDOVER.md` | 一行里写了**本机局域网 https 预览地址**（含真实 IP） | `https://<电脑局域网IP>:8444/`（启动时脚本会打印实际地址） |
> | `_tools/HANDOVER.md` | **真机序列号** | 「用 `adb devices` 现场查（不写进仓库）」 |
> | `_tools/serve-mobile.py` | `ip.startswith(…)` 里写死的私有网段前缀 | 按八位组判断（`_o[0]=='192' and _o[1]=='168'`），**行为等价** |
> | `_tools/asr-offline.py` | 同上前缀 + 注释里的示例 IP | 同上改八位组；注释改为 `<局域网IP>` |
> | `_tools/check-https-capabilities.mjs` | 用法示例里的**真实 IP** | `https://<电脑局域网IP>:8444/` |
> | `android/src/com/yuyi/app/MainActivity.java` | 注释里形如 `http://<私有网段>…` 的示例 | 注释改为「局域网 http:// 地址」（**只改注释，不改代码**） |
>
> 另有 2 个**整文件排除**（不是改写）：`手机地址.txt`（写死本机多个局域网 IP）、
> `android/_tools/deploy-probe.ps1` 与 `eval-b64.ps1`（写死真机序列号）。

### 3.2 真实 API Key → **0 处**

原始模式 `sk-` 会**大量误命中 `vosk-`**（`vosk-browser` / `vosk-model-small-cn-0.22`），所以分两步扫：

```powershell
# (a) 真正的密钥形态：sk- 后跟 16 位以上密钥字符，且排除 vosk-
Select-String -Path $paths -Pattern '(?<!vo)sk-[A-Za-z0-9_\-]{16,}' -Encoding UTF8
# → MATCHES: 0

# (b) 常见真实 Key 前缀（这些是**公开的前缀名**，不是密钥）
foreach($p in @('sk-proj-','sk-ant-','sk-or-v1-','sk_live_','ghp_','gho_','AIza','xoxb-','AKIA')){
  Select-String -Path $paths -Pattern $p -Encoding UTF8
}
# → 除本文档自己列出的这些前缀名以外，全部 0
```

> 诚实说明：`docs/VERIFICATION.md`（就是本文）**自己**会命中 (b) 里的每个前缀名各 1 处，
> 因为这里把它们列出来当模式名了；也会命中 (a) 的说明文字。
> 所以 (a)(b) 的正确读法是：**排除本文档后 0 处**；或者直接看结果里有没有非本文件的命中。
> 这些前缀是公开知识（就像说「AWS 的 Key ID 以某个四字母开头」），不构成泄露。

`sk-` 的**全部 82 处**出现，归类如下：

| 类别 | 处数 | 例子 |
|---|---:|---|
| 含 `vosk-`（引擎/模型名） | 75 | `vosk-browser@0.0.8`、`vosk-model-small-cn-0.22` |
| 形如 `sk-…` 的**占位符**（输入框 placeholder / 文档示例） | 5 | `placeholder="sk-…"`、`sk-xxxx` |
| 掩码示例（**讨论如何不泄露 Key** 的文档） | 2 | `sk-pr…789`、`读到以 sk- 开头的…出声播报掩码` |
| **真实 Key** | **0** | — |

也就是说：**仓库里没有任何真实 API Key**，连示例都用的是假值 / 掩码。

### 3.3 设备序列号 → **0 处**

> 序列号的字面值同样**不在本文档复述**（复述就等于重新泄露一次）。用变量表达：

```powershell
$pat = '<真机序列号>'      # 运行时替换为实际要核验的序列号
Select-String -Path $paths -Pattern $pat -Encoding UTF8
# MATCHES: 0
```

原本有 3 处：`_tools/HANDOVER.md`（**已脱敏**，改为「用 `adb devices` 现场查」）、
`android/_tools/deploy-probe.ps1` 与 `android/_tools/eval-b64.ps1`
（两个**已整文件排除**——它们是写死序列号的本机 adb 调试脚本，且依赖同样被排除的 `probe.txt`）。

### 3.4 一条完整的复跑脚本

把下面整段贴进 PowerShell（在仓库根目录）即可复现上面全部结论。
注意模式串**都是拼接出来的**，这样本文档自己不会命中自己要检验的模式：

```powershell
$root = (Get-Location).Path
$tracked = git ls-files
$paths = @($tracked | ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path $_ })
"tracked: $($paths.Count) files"

"`n[1] 私有网段前缀"
$pat = '192' + '\.168\.'
$r = Select-String -Path $paths -Pattern $pat -Encoding UTF8
if ($r) { $r } else { "  MATCHES: 0" }

"`n[2] 真实私有 IPv4"
$pat = '\b(' + '192' + '\.168' + '\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b'
$r = Select-String -Path $paths -Pattern $pat -Encoding UTF8
if ($r) { $r } else { "  MATCHES: 0" }

"`n[3] 设备序列号（把 <SERIAL> 换成实际值）"
$pat = $env:YUYI_SERIAL   # 例如先 $env:YUYI_SERIAL = '...'
if ($pat) {
  $r = Select-String -Path $paths -Pattern $pat -Encoding UTF8
  if ($r) { $r } else { "  MATCHES: 0" }
} else { "  跳过（未设置 `$env:YUYI_SERIAL）" }

"`n[4] API Key 形态（排除 vosk- 误命中）"
$r = Select-String -Path $paths -Pattern '(?<!vo)sk-[A-Za-z0-9_\-]{16,}' -Encoding UTF8
if ($r) { $r } else { "  MATCHES: 0" }
```

> ⚠️ **一个容易踩的坑**（我第一次就踩了）：不要写 `$paths | Select-String -Pattern ...`。
> 把**字符串数组**管道给 `Select-String` 时，它绑定的是 `-InputObject`，
> 于是它去搜「路径字符串本身」，**永远返回 0 处** —— 假阴性。
> 必须写成 `Select-String -Path $paths -Pattern ...`。

---

## 4. 脱敏与出处（私有项目名引用说明）

扫到两个**私有兄弟项目**的名字被引用：

| 名字 | 处数 | 文件数 |
|---|---:|---:|
| `ai-voice-summary` | 38 | 13 |
| `xiaoyu-assistant` | 2 | 2 |

**结论：没有私有代码被拷进来。** 逐类核对如下（这是本节的重点）：

| 出现位置 | 性质 | 判断 |
|---|---|---|
| `_tools/braille-zh.js`、`android/assets/**/braille-zh.js` 顶部注释 | **出处说明**：「这是 `…/braille_zh.py` 的浏览器端移植，目标是逐字符等价」 | 是**移植**（Python → JS 重写），不是拷贝；引擎代码本身是本项目的 |
| `data/braille-zh.json`、`android/assets/data/braille-zh.json` 的 `meta.source` | **数据出处字段**：该表也存在于私有库中 | 表的**最终上游是 Liblouis `zh-chn.ctb`（LGPL-2.1-or-later）**，可合法再分发；见 [THIRD-PARTY.md](../THIRD-PARTY.md) |
| `_tools/asr-offline.py`、`asr-phrases.py`、`verify-asr-offline.py`、`verify-asr-wasm.mjs`、`fetch-asr-wasm.py`、`verify-braille-parity.py`、`data/asr/README.md` 等 | **本机默认路径 / 出处注释**：指向私有库里那份 Vosk 模型的本地目录 | 是**路径引用与出处**，不是代码拷贝；这些脚本都是为本项目写的验收/打包工具 |
| `xiaoyu-assistant` 的 2 处 | 文档里的**链路形态参考**（「手机采 16k 单声道 PCM 逐段回传的链路形态，参考…」） | 纯说明文字 |

**为什么保留这些引用（而不是全部抹掉）**：

1. 它们是**出处与署名**。把出处删掉会让仓库**更不诚实**，也会切断 Liblouis(LGPL) → 这份表的许可链条，
   而那正是法律上唯一必须讲清楚的东西。
2. 其中若干处是**功能性路径**（`DEFAULT_MODEL = SKILL_ROOT / "local-asr" / "models" / …`），
   机械替换会**改坏可运行的脚本**；而 `/models/vosk-model-small-cn-0.22` 这个名字本身是
   **上游 Apache-2.0 模型的公开名字**，不是秘密。
3. 逐条核对后**没有发现任何从私有库拷贝的代码**（`index.html`、`MainActivity.java`、
   `docx-mini.js`、`match-cmd.js`、各 `verify-*` 都是本项目原创）。

> **给维护者的建议**：如果你希望公开库里完全不出现这两个名字，
> 可以只改**注释/文档**（不动功能路径与 `meta`），或把对应文件移到不提交的位置；
> 但请保留 [THIRD-PARTY.md](../THIRD-PARTY.md) 里的 Liblouis 许可说明。

---

## 5. 真机实测

设备：**vivo V2270A / iQOO Z7**（Android 15）。以下都是**在真机上跑出来的**，不是模拟器。

| 项 | 结果 | 证据 |
|---|---|---|
| **APK 装机可用** | ✅ `adb install -r` 成功，能启动、能操作 | `_shots/apk-0*.png`、`apk-05-home-final.png` |
| **离线识别在真机出字** | ✅ 手机端 Vosk WASM 出文字（不依赖云端通道） | `_tools/verify-asr-offline.py`（28/28）+ 真机运行 |
| **内置自检 15 项** | ✅ **全部通过（15 项）** | 截图 [docs/images/apk-selftest.png](images/apk-selftest.png) |
| **安全上下文** | ✅ `isSecureContext = true`，origin `https://appassets.local` | 同上截图 |
| **WebView 无 `speechSynthesis`** | ✅ 实测「不存在（WebView 的正常表现）」→ 所以必须走原生 TTS | 同上截图 |
| **原生 TTS 桥可用** | ✅ `YuyiNative.speak` / `saveFile` / `stop` / `available` 全为「有」 | 同上截图 |
| **TTS 引擎初始化 + 播报完成** | ✅ 引擎 **`com.vivo.aiservice`** 初始化成功，`speak` 到 **`onDone`** 回调走完 | 真机 logcat（`TAG_TTS`） |
| **导出真 .docx 落到 `/sdcard/Download`** | ✅ 经 `MediaStore.Downloads` 真实落盘 | 真机文件系统 + 「导出记录」面板 |
| **麦克风与拾音** | ✅ `getUserMedia` 取流成功；**拾音峰值 0.242**（安静时 0.002） | `_tools/mic-diagnose.html`（`/diag`） |
| **云端语音识别（对照）** | ❌ **固定返回 `aborted`**（两次复现）→ 这才是「说了没反应」的根因 | `/diag` 识别引擎状态 |
| **浏览器 Permissions API（对照）** | ❌ vivo 浏览器未实现 `permissions.query({name:'microphone'})` → `checkMicPermission()` 静默跳过 | 真机 |

**「云端识别不通」这件事的意义**：它不是 bug，而是**产品决策的依据** ——
正因为该机型云端通道不可用，才转向 **Vosk 离线识别**（见 [README §6.1](../README.md#61-云端识别在这台机型上不可用所以改成了离线)）。

---

## 6. 未验证清单

**这一节比上面那节更重要。** 以下是**没有验过**的东西，任何对外材料都不应声称它们成立。

### 6.1 需要人耳/人手确认的

- ⚠️ **扬声器是否真的出声**：TTS 的**回调链**走通了（`speak` → `onDone`），
  但「人耳确实听到了声音」**需要人工确认**。回调成功 ≠ 扬声器有声（可能媒体音量为 0）。
- ⚠️ **振动体感**：三段式振动的节奏是否真的「能分辨」需要人耳/手感确认。
- ⚠️ **真机录音是否真存下音频**：未验成 —— adb 点击在用户手机上多次点偏录音按钮，
  需要用户手点 5 秒 + 说「小语，结束」才能确认（`HANDOVER.md §7`）。
- ⚠️ **真实语音说「小语，结束」的端到端链路**：一直用**喂文本**的等价方式验证，
  真人口述的端到端**没有**实测。
- ⚠️ **「整条纯语音链路端到端走通」**：各环节都验过，但**没有让真实盲人用户**
  从开机走到导出完整跑一遍。

### 6.2 渲染与设备

- ⚠️ **Word / 盲文没有真实渲染校验**：本机**无 LibreOffice**，WPS **无可用的无头命令行**。
  所以「打开后视觉上长什么样」没验过（**格式合法、内容可回读**已验，137/137 与 217/217）。
- ⚠️ **盲文点显器 / 盲文打印机实际输出**：没验过（.brf 是标准格式，但没有硬件实测）。
- ⚠️ **iOS 全部未测。**
- ⚠️ **微信内置浏览器未测。**
- ⚠️ **低端机 WASM 离线识别性能未测**：内存、发热、首次加载时长（模型 41.9 MB）。
- ⚠️ **录音时 MediaRecorder 与识别引擎抢麦克风能否共存**：未验。

### 6.3 覆盖不全的路径

- ⚠️ **部分真机路径未覆盖**：探针主要覆盖 Web 侧与待办/振动契约；
  安卓壳的若干分支（权限被永久拒绝、后台被杀、蓝牙耳机切换等）**没有**逐条真机验证。
- ⚠️ **49 条导航路径**是加动画**之前**验的；`PENDING-FIXES.md` 明确提示**加动画后要重验**。
- ⚠️ **`-SkipAssets` 相关的构建分支**（第 4 节的表格）是**按代码语义整理**的，
  没有穷举「每种文件改动 × 是否加参数」的组合去实测。

### 6.4 明确**不能**声称的

- ❌ 不能说「已在 Word/WPS 里验证排版正确」。
- ❌ 不能说「iOS / 微信里可用」。
- ❌ 不能说「端到端已被视障用户验证」。
- ❌ 不能说「小语在所有安卓机型上都会说话」（**取决于是否有中文 TTS 引擎**，见 [README §6.3](../README.md#63-部分机型需要安装-tts-引擎)）。
- ❌ 不能说「离线转写很快」（**RTF ≈ 1.4–2.0，慢于实时**）。

---

## 7. 仓库体积

首版提交（root commit，只有一个提交，无历史包袱）的实测体积：

| 指标 | 值 |
|---|---|
| 提交文件数 | **82** 个（`39351 insertions(+)`，root commit，无历史包袱） |
| 工作区被跟踪内容 | **5.53 MB** |
| `.git` 目录（对象库） | **2.58 MB**（101 个对象，`git count-objects -vH`：`size: 2.54 MiB`） |
| 其中 `docs/images/` 精选截图 | **1.80 MB**（7 张） |

对照：**磁盘上整个目录 ≈ 1,078.91 MB / 1,714 个文件**，
其中 **≈ 1,073.41 MB / 1,634 个文件**按 [第 2 节](#2-被排除的文件与体积)排除，
真正进仓库的只有**源码、数据表、脚本、文档与精选截图**（≈ 5.5 MB）。

复跑方式：

```powershell
git count-objects -vH
git ls-files | Measure-Object                                    # 82
git ls-files | ForEach-Object { (Get-Item $_).Length } | Measure-Object -Sum
```

体积控制的关键取舍：

| 决定 | 换来什么 |
|---|---|
| 不提交 `.toolchain/`（781 MB） | 仓库小 781 MB，代价是新人要按 BUILD.md 下三个压缩包 |
| 不提交 `vosk.js` + `model.tar.gz`（47 MB） | 仓库小 47 MB，代价是首次要跑一次 `fetch-asr-wasm.py` |
| 不提交 `.build/` + `dist/`（179 MB） | 仓库小 179 MB，代价是首次构建慢一点（可完整重建） |
| 只提交 7 张精选截图（1.80 MB）而不是 `_shots/`（16 MB） | 仓库小 14 MB，且**避免把含本机状态的原始截图**发出去 |