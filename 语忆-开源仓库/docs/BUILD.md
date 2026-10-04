# 语忆 · APK 构建说明

> 目标：从零把 `android/` 编成一个能装、能用的 APK。
> **不需要 Gradle、不需要 Android Studio、不需要 androidx、不需要联网构建。**

---

## 目录

- [0. 为什么不走 Gradle](#0-为什么不走-gradle)
- [1. 准备工具链（3 个压缩包）](#1-准备工具链3-个压缩包)
- [2. 准备离线识别资产](#2-准备离线识别资产)
- [3. 构建](#3-构建)
- [4. 参数：`-SkipAssets` 与 `-Clean`（⚠️ 最容易踩）](#4-参数-skipassets-与--clean-最容易踩)
- [5. 构建链 9 步详解](#5-构建链-9-步详解)
- [6. 签名密钥（⚠️ 不在仓库里）](#6-签名密钥-不在仓库里)
- [7. 一个必须知道的坑：改脚本会丢 BOM](#7-一个必须知道的坑改脚本会丢-bom)
- [8. 怎么打开内置自检页](#8-怎么打开内置自检页)
- [9. 产物与验收](#9-产物与验收)
- [10. 常见构建失败](#10-常见构建失败)

---

## 0. 为什么不走 Gradle

原开发机上没有 java/javac/gradle/Android SDK。Gradle 路线还要再拉一堆 Maven 依赖，
**任何一个下载失败整条链就断**。所以这里只依赖三个可以直接下载的压缩包，
构建链全部写在 `android/build-apk.ps1` 里，**可复现、可审计**：

```
aapt2 compile → aapt2 link → javac → d8 → 手动重打包 → zipalign → keytool → apksigner → verify
```

代价是必须自己处理 Windows 上 aapt2 的两个坑（见 [第 6 步「手动重打包」](#第-6-步手动重打包-这是必须的)）。

---

## 1. 准备工具链（3 个压缩包）

下载后**解压到 `android\.toolchain\`**，目录名要能被脚本的匹配规则找到：

```
android\.toolchain\
├─ jdk17\            <- JDK 17 解压后，里面**只有一层**子目录（例：jdk-17.0.20.1+1\bin\java.exe）
├─ build-tools_r34\  <- build-tools 解压后，里面**只有一层**子目录（例：android-14\aapt2.exe）
└─ platform-34\      <- platform 解压后，里面**只有一层**子目录（例：android-34\android.jar）
```

脚本的定位规则（`Find-One`）是这些通配：

| 找什么 | 相对 `.toolchain` 的匹配模式 |
|---|---|
| `java.exe` / `javac.exe` / `keytool.exe` / `jar.exe` | `jdk17\*\bin\*.exe` |
| `aapt2.exe` / `zipalign.exe` | `build-tools_r34\*\aapt2.exe` |
| `d8.jar` / `apksigner.jar` | `build-tools_r34\*\lib\*.jar` |
| `android.jar` | `platform-34\*\android.jar` |

> `*` 只匹配**一层**目录名。所以别把内容解压成 `jdk17\jdk-17\jdk-17\bin\` 这种两层结构。

**下载地址**（脚本头部注释里也写了）：

| 组件 | 地址 |
|---|---|
| JDK 17（Adoptium / 清华 TUNA 镜像） | `https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jdk/x64/windows/OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip` |
| build-tools r34 | `https://dl.google.com/android/repository/build-tools_r34-windows.zip` |
| platform-34 | `https://dl.google.com/android/repository/platform-34-ext7_r03.zip` |

脚本**自己不联网**：解压好了就能离线构建。

> 整包解压后约 **781 MB**（所以 `.toolchain/` 在 `.gitignore` 里，绝不进仓库）。

---

## 2. 准备离线识别资产

```powershell
python _tools\fetch-asr-wasm.py
```

它会拉两个**不在仓库里**的文件（第三方二进制，见 [THIRD-PARTY.md](../THIRD-PARTY.md)）：

| 产物 | 体积 | 说明 |
|---|---|---|
| `data\asr\vosk.js` | 5.8 MB | `vosk-browser@0.0.8` 的 UMD 单文件（WASM 与 Worker 都 base64 内嵌） |
| `data\asr\model.tar.gz` | 41.9 MB | `vosk-model-small-cn-0.22` 打包（顶层单目录，`stripFirstComponent=true`） |

下载路线有多条（npm registry / jsdelivr / unpkg / `npm pack`），全部失败时会告诉你怎么手动放文件。
脚本可重复运行（幂等）。

> **不想用离线识别也想编 APK？** 可以先不跑这一步，但**第 3 步构建会少这两个 assets**，
> 页面里的离线识别会加载失败（并如实播报失败）。想要完整体验就跑一下。

---

## 3. 构建

```powershell
# 仓库根目录下
powershell -ExecutionPolicy Bypass -File android\build-apk.ps1
```

> **为什么必须带 `-ExecutionPolicy Bypass`**：开发机执行策略是 `RemoteSigned`，
> 直接用 `& .\build-apk.ps1` 会被拒绝。

产物：

```
android\dist\yuyi-offline-v1.0.0.apk      （约 44.6 MB）
```

脚本最后会打印 `apksigner verify` 的结果和密钥信息；`verify` 不过会 `exit 1`。

---

## 4. 参数：`-SkipAssets` 与 `-Clean`（⚠️ 最容易踩）

```powershell
# 只改了 Java（MainActivity.java）—— 省掉 50 MB 的 assets 拷贝
powershell -ExecutionPolicy Bypass -File android\build-apk.ps1 -SkipAssets

# 清掉 android\.build\ 里的中间产物
powershell -ExecutionPolicy Bypass -File android\build-apk.ps1 -Clean
```

### ⚠️ 改了 `index.html`（或任何网页资源）**必须全量构建，不要加 `-SkipAssets`**

`-SkipAssets` 的语义是**「跳过第 1 步：把整站资源拷进 `android\assets\`」**。
它检查 `android\assets\index.html` 是否存在，存在就直接复用**上一次拷贝的旧副本**。

也就是说：

| 你改了什么 | 能用 `-SkipAssets` 吗 |
|---|---|
| `android\src\**.java` | ✅ 能 |
| `android\AndroidManifest.xml` | ✅ 能 |
| `android\res\**` | ✅ 能 |
| **`index.html`** | ❌ **不能** —— 必须全量 |
| **`sw.js`** | ❌ 不能 |
| **`data\braille-zh.json`** / **`data\asr-phrases.json`** | ❌ 不能 |
| **`_tools\docx-mini.js`** / **`_tools\braille-zh.js`**（会被拷成 `assets\lib\*` 与 `assets\_tools\*`） | ❌ 不能 |
| **`android\selftest.html`** | ❌ 不能 |
| **`data\asr\**`**（引擎/模型换了） | ❌ 不能 |

**症状**：加了 `-SkipAssets` 却发现「改的页面没生效」—— 这是最常见的自伤。
拿不准就**不加任何参数**跑一次。

另外脚本会在全量构建时**打印并记录本次打包的 `index.html` 指纹**
（字节数 / SHA256 前 16 位 / mtime），存在 `android\.build\index-fingerprint.txt`。
「APK 里的页面是不是我以为的那份」—— 拿它对。

---

## 5. 构建链 9 步详解

| 步 | 做什么 | 关键点 |
|---|---|---|
| **0/9** | 定位工具链 | 设置 `JAVA_HOME` 与 `PATH`；`java -version` 只写 stderr，必须走 `Invoke-Native` |
| **1/9** | 把整站资源拷进 `android\assets\` | 见 [第 4 节](#4-参数-skipassets-与--clean-最容易踩)。**不打包** `_shots\`、`_tools\*.ps1`、`_tools\*.py`、`design\`、README |
| **2/9** | `aapt2 compile --dir res -o res.zip` | 编译资源 |
| **3/9** | `aapt2 link` | 生成 `base.apk`，`-A assets` 收资源，`--java gen` 生成 `R.java` |
| **4/9** | `javac -source 8 -target 8 -bootclasspath android.jar` | 编译 `gen/` + `src/`。失败会退回 `-classpath android.jar` |
| **5/9** | `d8 --min-api 21` | 生成 `classes.dex` |
| **6/9** | **手动重打包**（自己写的 `RepackApk.java`） | ⭐ 见下 |
| **7/9** | `zipalign -f -p 4` | 4 字节对齐 |
| **8/9** | `keytool` + `apksigner sign` | v1+v2+v3 全开 |
| **9/9** | `apksigner verify --verbose --print-certs` | 不过就 `exit 1` |

### 第 6 步「手动重打包」—— 这是必须的

两个 **Windows 上的真实坑**，跳过这步 APK 会装不上或白屏：

1. **aapt2 在 Windows 上把 assets 条目名写成反斜杠**
   （`assets\data\asr\model.tar.gz`）。设备上 `AssetManager` 按 `/` 精确查表，
   于是 `getAssets().open("data/asr/model.tar.gz")` **必然找不到** → 页面白屏。
   → 第 6 步把条目名规范化成正斜杠。

2. **`.NET` 的 `CompressionLevel.NoCompression` 不产出 zip `STORED`（method 0）**
   它只是让 deflate 输出 stored block，条目仍是 method 8（体积反而变大：实测
   `resources.arsc` raw=1348 → stored=1353）。而 **targetSdk ≥ 30 时 Android 硬性要求
   `resources.arsc` 未压缩**，否则直接装不上。
   → 所以必须用纯 JDK 的 `ZipOutputStream` **显式写 method 0 + size + CRC32**。

脚本在第 6 步后会**复核**：无反斜杠条目、`resources.arsc` 与 `model.tar.gz` 是否真 STORED、
`classes.dex` 是否恰好 1 个。任一不符就 `Die`。

> `aapt2 link` 时还会用 `--no-compress-regex '\.gz$'`（让 41.9 MB 的模型原样 STORED，
> 否则每次读都要 inflate 一遍）；这个姿势失败会退回无参 `--no-compress` 重试。

---

## 6. 签名密钥（⚠️ 不在仓库里）

- 密钥文件：`android\yuyi-debug.keystore`（PKCS12，alias `yuyi`）—— **`.gitignore` 排除了，绝不进仓库**。
- **脚本会自动生成**：`if (-not (Test-Path $KsPath)) { keytool -genkeypair ... }`，
  有效期 10950 天（30 年），RSA 2048。
- 生成命令里的口令是**写死的固定值**（`build-apk.ps1` 里的 `$KsPass` / `$KsAlias`）。

> ⚠️ **这是个「自签调试密钥」，不是发布密钥。**
> 口令写在脚本里、密钥不进仓库，是为了让任何人都能一键构建出**可安装的本地包**。
> **不要用它发布到应用商店**；要正式发布请自己 `keytool` 生成私钥并妥善保管，
> 同时把 `-v1/-v2/-v3` 签名选项与 `--ks/--ks-pass` 换成你自己的。
> 复用了旧的 `yuyi-debug.keystore` 时脚本会打印「复用已有密钥」。

---

## 7. 一个必须知道的坑：改脚本会丢 BOM

**`build-apk.ps1` 与 `_tools\verify-*.ps1` 这类 PowerShell 脚本必须保存为 `UTF-8 with BOM`。**

原因：它们里面写的是中文。**Windows PowerShell 5.1 在没有 BOM 时会按 ANSI（中文系统上是 GBK）解码**，
中文字符串会变成乱码，脚本直接**解析失败**。

> ⚠️ **很多编辑器/工具在「保存」时会静默丢掉 BOM**（包括一些自动化改写工具）。
> 如果你用工具批量改了这些 `.ps1`，改完请确认它们**仍然带 BOM**，否则脚本会突然跑不起来。
> 换用 PowerShell 7（`pwsh`）可以避免这个问题（它默认按 UTF-8 解码），但 5.1 仍然常见。

自查是否带 BOM：

```powershell
# 前 3 个字节应该是 EF BB BF
Format-Hex android\build-apk.ps1 -Count 3
```

---

## 8. 怎么打开内置自检页

APK 自带一个**诊断页**（不是产品页面），用 intent extra 把首屏换成它：

```powershell
adb shell am start -n com.yuyi.app/com.yuyi.app.MainActivity --es yuyi_page selftest.html
```

它会显示 **15 项**检查（图见 [README](../README.md#apk-内置自检--15-项全部通过)）：

- **运行环境**（10 行）：`URL`、`origin`、**安全上下文**、`indexedDB`、
  `speechSynthesis`、`YuyiNative.speak` / `saveFile` / `stop` / `available`、`UA`
- **内置资源 HTTP 状态 / 字节数**（8 项，含一个**故意 404 的负例** `lib/__no_such_file__.js`），
  用来证明「脚本是真的执行了」，而不只是「文件存在」

真机上它是这样的：

```
语忆 · APK 内置自检
[ 全部通过（15 项） ]
URL                 https://appassets.local/selftest.html
origin              https://appassets.local
安全上下文           true
indexedDB           object
speechSynthesis     不存在（WebView 的正常表现）   ← 所以必须走原生 TTS 桥
YuyiNative.speak    有
YuyiNative.saveFile 有
YuyiNative.stop     有
YuyiNative.available 有
```

### 为什么 APK 里访问的是 `https://appassets.local`

外壳用 `WebViewClient.shouldInterceptRequest` 把 `https://appassets.local/<path>`
映射到 APK 内的 `assets/<path>`（`/` → `assets/index.html`）。
好处是页面拿到的是一个**真正的 https origin**，于是
`isSecureContext === true`、Service Worker 能注册、IndexedDB 可用。

### 导出是怎么真落盘的

页面里 `downloadBlob()` 造一个 `blob:` URL 再点 `<a download>` —— 这在 WebView 里
**文件不落地**（实测确认 `/sdcard/Download` 没有文件）。
所以外壳自己接住 `DownloadListener`，把 blob 用 fetch 读成 base64、分片喂回 Java，
再经 **MediaStore**（`MediaStore.Downloads`）落到系统**「下载」**目录。
**只动外壳，不碰产品代码。**

---

## 9. 产物与验收

| 项 | 值 |
|---|---|
| 产物 | `android\dist\yuyi-offline-v1.0.0.apk` |
| 体积 | 约 44.6 MB（其中离线模型占大头） |
| 包名 / 版本 | `com.yuyi.app` / versionCode 1 / versionName 1.0.0 |
| minSdk / targetSdk | **21 / 34** |
| 权限 | `INTERNET`、`RECORD_AUDIO`、`MODIFY_AUDIO_SETTINGS`、`VIBRATE`、`POST_NOTIFICATIONS`、`WAKE_LOCK`、`WRITE_EXTERNAL_STORAGE`（`maxSdkVersion=28`） |
| 包可见性 | **`<queries><intent><action android:name="android.intent.action.TTS_SERVICE"/>`**（不加这条 TTS 引擎根本看不到，`onInit` 直接 ERROR） |
| 中间产物 | `android\.build\`（`res.zip` / `base.apk` / `classes.dex` / `unsigned.apk` / `aligned.apk` / `index-fingerprint.txt`） |

> **中间产物为什么不放 `%TEMP%`**：实测本机 aapt2 往 `C:\Users\<用户>\...\Temp` 写输出会直接报
> `数据无效。(13)`（普通 PowerShell 写同一目录却没问题）。换到工程目录下即正常，
> 所以 `.build\` 放在 `android\` 里。

装到手机：

```powershell
adb install -r android\dist\yuyi-offline-v1.0.0.apk
```

装完的验收（真机实测结论见 [VERIFICATION.md](VERIFICATION.md)）：
离线识别能出字、TTS 能播报、导出真 .docx 落到 `/sdcard/Download`、内置自检 15 项通过。

---

## 10. 常见构建失败

| 报错 | 原因 | 怎么办 |
|---|---|---|
| `找不到 java.exe (JDK) （在 …\.toolchain 下按模式 jdk17\*\bin\java.exe 找）` | 目录层级不对 | 按[第 1 节](#1-准备工具链3-个压缩包)的结构放，`*` 只匹配一层 |
| `aapt2 compile 退出码 非0` + `数据无效。(13)` | aapt2 往 `%TEMP%` 写失败 | 已规避（中间产物在 `android\.build\`）；确认你没有手动把 `$Work` 改回 `%TEMP%` |
| `resources.arsc 被压缩了（raw=… stored=…）` | 第 6 步重打包没生效 | 别跳过第 6 步；确认 `android\_tools\RepackApk.java` 在（构建链依赖它） |
| `还有 N 个条目名带反斜杠` | 同上 | 同上 |
| `APK 里没有 assets/data/asr/model.tar.gz` | 没跑 `fetch-asr-wasm.py` | 跑[第 2 节](#2-准备离线识别资产) |
| `javac 编译失败` | `gen/R.java` 没生成 / 工具链不匹配 | 看 `aapt2 link` 那步是否 `--java` 成功 |
| `apksigner verify 没过` | 签名参数或 keystore 损坏 | 删掉 `android\yuyi-debug.keystore` 让它重新生成 |
| 装上了但**白屏** | assets 条目名问题（历史 bug） | 走完整构建链，别手工打 zip |
| **改了页面但 APK 里没变** | 用了 `-SkipAssets` | **全量重建**，见[第 4 节](#4-参数-skipassets-与--clean-最容易踩) |
| 脚本一跑就报**语法/解析错误** | `.ps1` 的 BOM 丢了（被工具改过） | 见[第 7 节](#7-一个必须知道的坑改脚本会丢-bom) |
| 小语**不讲话** | 手机没有中文 TTS 引擎 | 打开内置自检看 `YuyiNative.*`；装一个 TTS 引擎（见 README §6.3） |