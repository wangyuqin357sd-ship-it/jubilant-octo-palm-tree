# 语忆 · 交接摘要（压缩版）

> 用途：本文件是整段工作的压缩状态。新会话只需读这一个文件即可继续，不必回看完整对话。
> 最后更新：2026-10-04 06:1x（Asia/Shanghai）

---

## 1. 产品与目标

- **产品**：语忆 —— 安卓端**为盲人做的**语音笔记网页（单页应用）。语音助手叫「小语」。
- **主文件**：`yuyi-preview/index.html`（单文件、零依赖、离线优先）。
- **核心链路**：录音 → 存本地音频 → 小语主动问是否做 AI 笔记总结（转写+总结）→ 问笔记归哪个类目 → 问是否导出（盲文/中文 Word）→ 真下载文件。
- **用户最高优先级**：**纯语音+触觉闭环**，全程不用看屏幕。语音不可用 = 产品废掉。

## 2. 已交付物

| 文件 | 体积 | 作用 |
|---|---|---|
| `yuyi-preview/index.html` | ~236 KB | 主应用（唯一实现载体） |
| `yuyi-preview/sw.js` | 1.6 KB | Service Worker（手机端弹系统通知必须用它，`new Notification()` 在安卓 Chrome 抛 TypeError） |
| `yuyi-preview/手机预览.bat` | 781 B | 一键起 https 服务（CRLF 已校验） |
| `yuyi-preview/手机USB直连.bat` | 2.6 KB | USB 映射守护（插上自动建 reverse + 打开页面） |
| `yuyi-preview/_tools/serve-mobile.py` | ~12 KB | http 8790 / https 8444，自签证书（SAN 带局域网 IP），白名单只放行 8 个路径 |
| `yuyi-preview/_tools/mic-diagnose.html` | ~9 KB | **麦克风/识别诊断页**（`/diag`）：拾音强度条、getUserMedia、识别引擎状态、事件日志 |
| `yuyi-preview/_tools/docx-mini.js` | 21.5 KB | 零依赖真 `.docx` 生成器（ZIP stored/deflate + CRC32） |
| `yuyi-preview/_tools/braille-zh.js` | 23.3 KB | 中文盲文 JS（与后端 Python 逐字符等价） |
| `yuyi-preview/data/braille-zh.json` | 950 KB | 中文盲文表（44,388 条映射） |
| `yuyi-preview/data/asr/model.tar.gz` | **43.9 MB** | **离线识别：中文 Vosk 模型（手机端 WASM 用）** |
| `yuyi-preview/data/asr/vosk.js` | 5.8 MB | **离线识别：WASM 引擎** |
| `yuyi-preview/data/asr/yuyi-asr.js` | 22.6 KB | **离线识别：页面包装层 `window.YuyiASR`** |
| `yuyi-preview/_tools/match-cmd.js` | 25.8 KB | 容错指令匹配（口语填充/语气词/谐音/score） |
| `yuyi-preview/data/asr-phrases.json` | 11.3 KB | 规范短语表（供 Vosk 语法约束用） |
| `yuyi-preview/_tools/verify-todo-vibration.ps1` | ~40 KB | **主验收闸门（85 项断言，带 exit code）** |
| `yuyi-preview/_tools/todo-vibration-contract.md` | 10 KB | 冻结接口契约 v1.1 |
| `yuyi-preview/_tools/check-https-capabilities.mjs` | 8.9 KB | CDP 能力自检（真实页面探 isSecureContext/SW/通知/vibrate/wakeLock） |
| `yuyi-preview/README-预览说明.md` | ~59 KB | 说明文档（含第二轮 8 条反馈的修复记录与"未验证"清单） |

## 3. 验收状态（截至本文件）

```
主闸门 verify-todo-vibration.ps1        PASS 85 / FAIL 0   exit 0（连跑两次一致、无临时残留）
既有三探针 verify-ui/newflows/newscreens  throwAt=(none)、probe-ok
画布 check-mobile.py                     frames:16 groups:102 items:157 [OK]
docx-mini 独立复核                        137/137 PASS（ZIP 结构 + OPC 完整性 + python-docx 逐条回读）
中文盲文独立复核                          217/217 PASS（含全表 44,388 条聚合校验和与 Python 一致）
盲文反证                                  故意改坏 5 份副本 → 全部 exit 1
静态路由                                  / /sw.js /lib/docx-mini.js /lib/braille-zh.js /data/braille-zh.json /diag 全 200
```

## 4. 真机实测（vivo V2270A / iQOO Z7，adb 已连通）

| 项 | 结果 |
|---|---|
| 手机端布局（底栏固定、中间滚动） | ✅ 已修（根因：`.app-frame` 用 `min-height:100dvh`，内容一长底栏被顶出视口） |
| 语音自动开麦 | ✅ 药丸变绿「正在监听」，toast「语音唤醒已开启」 |
| 「我的」AI 接口配置入口 | ✅ 可见、可打开（18 个服务商预设，保存进 localStorage） |
| **麦克风硬件/权限/采集** | ✅ **正常**：getUserMedia 成功取流；**拾音峰值 0.242**（安静时 0.002） |
| **云端语音识别** | ❌ **固定返回 `aborted`**（两次复现）→ **云端通道在该机型不通，这是"说了没反应"的根因** |
| 浏览器 Permissions API | ❌ vivo 浏览器未实现 `permissions.query({name:'microphone'})` → `checkMicPermission()` 静默跳过 |

## 5. 已修的真缺陷（有据可查）

1. 周日说「下周一」算成 8 天后 → 改为以周一为一周起点
2. 「12月25日 18:30」冒号写法静默落 09:00 → 支持 `HH:MM`
3. 通知 `close` 同步回调与 `stopReminder` 相互重入（vibrateCalls 涨到 1357）→ 先摘出 + 可重入保护
4. `#todoDoneBtn` 首屏无 aria-label → 补静态 + 动态
5. 「不支持振动 + 通知被拒」两条播报互相顶掉 → 合并成一句 assertive
6. `file://` 下通知被推迟后丢失 → 构造器优先、SW 兜底
7. `#armCard` 抢走既有探针依赖的 `.banner` 选择器 → 改独立类名
8. 闸门用 `-EA Stop` 被 Chrome GPU 警告中断 → 改 Continue + 原生调用局部放宽
9. **识别器重复创建**（`voice.on` 异步置位，三处调用点可并发建两个 → 互相 abort）→ 已加 1.5s 去抖

## 6. 下一步：把离线识别接进页面（3 步，接口已确认对得上）

`yuyi-asr.js` 暴露 `window.YuyiASR`，用法与页面现有结构**天然吻合**：
```js
YuyiASR.create({ onResult: t => handleVoiceText(t), onStatus: paintWake })
```
1. **`serve-mobile.py`**：白名单放行 `/data/asr/**`（含 `model.tar.gz`、`vosk.js`、`yuyi-asr.js`、`manifest.json`），重启用 `手机预览.bat`
2. **`index.html`**：
   - 动态加载 `data/asr/yuyi-asr.js`
   - `voiceStart()` 里把 `new SR()` 换成 `YuyiASR.create(...)` + `startMic()`
   - **Web Speech 整段降级为兜底**（仅当离线引擎加载失败才用），且保留已加的"连续失败 2 次就停止空转并播报"
   - `voiceStop()` 调 `YuyiASR.stop()/destroy()`
3. **`handleVoiceText`**：把手写正则换成 `MatchCmd.match()`（子代理正在交 `verify-match-cmd.py`：≥20 条口语变体的 free vs 短语表命中率对比 + 30 条用例 + 混淆矩阵）

预期结果：诊断页的「识别引擎状态」从 `aborted` 变成「听到了：…」。

## 7. 未验证 / 不能声称的

- **真机录音是否真存下音频**：未验成（adb 点击在用户手机上多次点偏录音按钮；需用户手点 5 秒 + 说「小语，结束」）
- 真实语音说「小语，结束」的端到端链路（一直用喂文本等价验证）
- 录音时 MediaRecorder 与识别引擎**抢麦克风**能否共存
- 导出在手机上真正落盘
- Word/盲文的**真实渲染**校验（本机无 LibreOffice；WPS 无可用无头命令行）
- 手机端 WASM 离线识别的真机性能（模型 43.9MB 首次加载、内存、低端机表现）
- WX 内置浏览器、iOS 全部未测

## 8. 环境事实（照抄可用）

- 预览：`http://127.0.0.1:8790/`（本机能力全）· 手机 WiFi：`https://<电脑局域网IP>:8444/`（启动时脚本会打印实际地址）· 手机 USB：`http://127.0.0.1:8790/`（需 `adb reverse`）
- 诊断页：`http://127.0.0.1:8790/diag`
- adb：用 `where adb` 或本机 Android SDK 的 platform-tools；设备序列号用 `adb devices` 现场查（**不写进仓库**）
- Chrome shell：`D:\DevCache\ms-playwright\chromium_headless_shell-*\...\chrome-headless-shell.exe`
- 跑闸门：`powershell -ExecutionPolicy Bypass -File yuyi-preview\_tools\verify-todo-vibration.ps1`（**文件必须 UTF-8 with BOM**，否则 PS 5.1 按 ANSI 解码会解析失败）
- 闸门临时文件前缀 `vtv-`，`%TEMP%` 会自动清理
- 注意：`match-cmd.js`/`braille-zh.js`/`docx-mini.js` 目前**只在 _tools 与 data 下，index.html 尚未接线**（除 braille/docx 已通过 `/lib/` 路由接了一半）