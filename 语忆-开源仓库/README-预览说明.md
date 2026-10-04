# 语忆 · 前端预览说明（第一版）

> 📌 **这是一份开发期的历史记录（第一版 + 第二轮真机反馈），不是当前说明书。**
> 其中「转写仍是演示数据 / TTS 走 `speechSynthesis`」等结论**已被后续版本取代**：
> 现在手机端走 **Vosk WASM 离线识别**，APK 里走**原生 `TextToSpeech`**。
> 最新说明请看 [README.md](README.md)、[docs/USAGE.md](docs/USAGE.md) 与 [docs/VERIFICATION.md](docs/VERIFICATION.md)；
> 本文保留价值在于：需求对照表、无障碍实现细节、真 bug 修复记录、以及当时的「未验证」清单。

预览文件：`index.html`（单文件，双击用浏览器打开即可，无需服务器、无外部依赖）
建议预览：Chrome / Edge，按 `F12` → 切换设备模拟（iPhone 尺寸 430×932），真机直接扫码或拷贝打开。

> ⚠️ **要在安卓真机上试振动/通知，别用双击打开的文件**：`file://` 下 Service Worker 注册会被浏览器拒绝
> （origin 为 `"null"`），而 Chrome for Android 弹系统通知必须走 `registration.showNotification`，
> 结果就是**通知弹不出来**。请用下面的手机预览服务器（https）。见 §0.1。

## 0.1 在安卓手机上预览（推荐，振动/通知才完整）

双击 **`手机预览.bat`**：它会起一个本地服务器并打印手机该打开的地址（同时把地址写进 `手机地址.txt`）。

| 端口 | 用途 |
|---|---|
| **https 8444** | **手机用这个**（自签名证书，SAN 里带上本机局域网 IP） |
| http 8790 | 电脑上快速看。注意分两种：`http://127.0.0.1:8790/` 能力是**全的**（Chrome 把 127.0.0.1 当可信来源，实测 `isSecureContext=true`、SW 可注册）；换成局域网 IP 走 http（`http://<电脑IP>:8790/`）就只剩界面，没有振动/通知/麦克风 |

手机上按顺序做 4 步：

1. 连同一个 WiFi / 热点，浏览器打开打印出来的 `https://<电脑IP>:8444/`
2. 首次提示「连接不安全」→ 点「高级」→「继续前往」（自签名证书，数据只在你的电脑和手机之间走）
3. **先点一下页面任意位置** ← 见下方「为什么必须先点一下」
4. 待办面板里开「浏览器通知」并在弹窗点「允许」；再从浏览器菜单「添加到主屏幕」

**为什么必须先点一下**：`navigator.vibrate()` 需要**粘性用户激活（sticky user activation）**
（[MDN](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/vibrate) 明确写了 "Sticky user activation is required"）。
页面打开后一次都没交互过时，调用会被浏览器**静默忽略**——不报错、也不振。所以待办面板顶部加了
`#armCard` 提示条（`vibrationArmed()` 探测 `navigator.userActivation.hasBeenActive`），点过一下之后自动消失。
正常录入待办要点「确认保存」，本来就已经完成激活；这条提示主要是给「打开页面等演示待办自己响」的场景兜底。

**为什么必须走 https**：系统通知与 Screen Wake Lock 都要求安全上下文（
[Notifications](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API/Using_the_Notifications_API)、
[Wake Lock](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API) 均标注 Secure context），
麦克风同理。用 `_tools/serve-mobile.py` 起的 https 地址打开即可满足。

**自检**（服务在跑的时候执行）：

```powershell
# 真实页面里探测安全上下文与各能力，并真的注册一次 Service Worker
node _tools/check-https-capabilities.mjs --url https://127.0.0.1:8444/
# 对照：直接双击文件，会看到 Service Worker 注册失败（通知弹不出来）
node _tools/check-https-capabilities.mjs --url "file:///C:/Users/HP/Desktop/yuyi-preview/index.html"
```

实测结论（本机 2026-10-04）：

| | https 预览服务器 | 直接双击（`file://`） |
|---|---|---|
| 安全上下文 | ✅ `isSecureContext: true` | ✅（桌面 Chrome 也认 file://） |
| `navigator.vibrate` | ✅ | ✅ |
| Notification API | ✅ | ✅ |
| **Service Worker 注册** | ✅ scope `https://…:8444/` | ❌ `The URL protocol of the current origin ('null') is not supported` |
| **`showNotification`（手机弹通知的必要条件）** | ✅ | ❌ |
| Wake Lock / 麦克风 / 语音播报 | ✅ / ✅ / ✅ | ✅ / ✅ / ✅ |

## 0. 两种查看方式（推荐先看 M3E 画布）

| 方式 | 入口 | 用途 |
|---|---|---|
| **M3E Canvas 画布**（可视化改设计） | 编辑器：<http://127.0.0.1:3033/> · Galaxy 组件库：<http://127.0.0.1:3033/galaxy/> | 16 屏结构化画布，可拖拽、改文案、**Tidy** 对齐、换主题，再 **Copy prompt** 让编码工具实现 |
| 真实 HTML 预览 | `index.html`（双击打开，或走 §0.1 的 https） | 真机效果 + 交互流程（录音状态、确认弹窗、面板、助手浮层） |

画布数据：`design/m3e-design.json`（68 KB / 69,723 字节，**16 屏 102 组 157 个组件**）
一键载入链接：`design/draft-url.txt`（10 KB 的 `#docz=` 链接；编辑器内也可用「打开项目」直接选 `m3e-design.json`）

> 校验口径：早期 10 屏版本做过 M3E 官方校验；本轮 16 屏版本我只跑了 `python _tools/check-mobile.py`（`[OK]`，见下文「画布排版」），**未重跑 M3E 官方校验**。

重新生成链接 / 重开服务：

```powershell
node "$env:USERPROFILE\.dsh\skills\m3e-canvas\scripts\canvas.mjs" start --output "C:\Users\HP\Desktop\yuyi-preview\design\m3e-exports"
node "$env:USERPROFILE\.dsh\skills\m3e-canvas\scripts\canvas.mjs" draft "C:\Users\HP\Desktop\yuyi-preview\design\m3e-design.json" --output "C:\Users\HP\Desktop\yuyi-preview\design\m3e-exports"
```

画布上的 16 屏（含本轮新增第 16 帧 `remind`「提醒触发」）：首页·待机 / 录音中 / 录音暂停 / 小语助手浮层 / 我的 / 确认弹窗·录音转写 / 原音频面板 / AI 总结笔记 / 待办面板（安卓振动提醒）/ 导出记录 / 帮助与语音指令 / 目录面板（入口页）/ 导出盲文确认 / 录音已保存 / 色板·层级·语音指令 / **提醒触发（`remind`）**。完整清单见下方「内容结构」。
屏幕之间已按流程连好跳转：录音按钮 → 录音中 → 暂停 → 继续；呼叫 → 助手浮层；**目录页的「原音频」「AI 总结笔记」两个按钮 → 对应面板**；侧边栏 → 各面板；导出 → 确认弹窗。每屏的 `note` 里写了点击行为、播报话术和禁令，会一起进入 Copy prompt 的提示词。

### 内容结构（2026-10-04 补齐）

16 屏：`首页·待机 / 录音中 / 录音暂停 / 小语助手浮层 / 我的 / 确认弹窗·录音转写 / 原音频面板 / AI 总结笔记 / 待办面板 / 导出记录 / 帮助与语音指令 / 目录面板（内容入口）/ 导出盲文确认 / 录音已保存 / 色板·层级·语音指令 / 提醒触发（remind）`

本次补的 4 屏：

| 屏幕 | 内容 | 入口 |
|---|---|---|
| **我的** | 使用情况（录音 26 段 / AI 总结 22 条）、朗读与通知（浏览器通知开关 / 正文字号「特大」/ 高对比度 / 朗读语速滑块）、更多（导出记录 / 帮助与语音指令） | 底部 Tab【我的】 |
| **导出记录** | 3 条历史 BRF 导出（条目 / 时间 / 文件名 / 盲文级别 / 体积）、重新下载、全部导出、清空记录（需确认）、BRF 说明卡 | 我的 → 导出记录 |
| **帮助与语音指令** | 唤醒词说明、7 条可用指令、通用控制、「不能用的说法」3 条（暂停/继续、语速、自由闲聊） | 我的 → 帮助与语音指令；也是「小语，帮助」的完整版 |
| **录音已保存** | 保存确认卡（时长/体积/时间）+ 三个去向：交给 AI 转文字 / 回放原音频 / 先放着 | 说完「小语，结束」或点停录音后立刻出现 |

底部 Tab 按要求统一为 **首页 / 笔记 / AI / 我的**（之前第 2 项误写成「AI 总结」），四个 Tab 都连了跳转。

> **2026-10-04 待办振动提醒改动同步了画布（帧数 15 → 16）**：`todos` 帧顶部的免责 banner 换成「安卓振动提醒」能力卡（supporting 写三段式节奏）、`me` 帧通知项改成通知权限说明、`brand` 帧补上「知道了 / 延后十分钟」语音指令，并新增第 16 帧 `remind`「提醒触发」——标题「待办提醒」+ 待办全文 + `知道了` / `延后 10 分钟` 两个按钮，对应真实弹窗 `#remindDlg`。

- **目录页 = 内容入口**：顶部两个主按钮 —— 「原音频」（tonal）和「AI 总结笔记」（filled）；下面是原有按目录组浏览的记录条目 + 上一组 / 下一组 + 标签筛选。
- **原音频面板**（新增 `audio` 帧）：存放每次录音的原始音频文件。每条显示时长、体积、录制时间、是否已总结，操作有 `播放 / AI 总结 / 重命名 / 导出 / 删除`；底部「再录一段」回到录音。原声永远保留，删除需二次确认。
- **AI 总结笔记面板**（原 `notes` 帧改名）：里面全是 AI 从原音频里总结提炼的内容（要点 / 摘要 / 标签 / 所属目录），每条都带「AI 总结」标记和对应原音频时长；操作有 `朗读 / 原音频 / 标签 / 导出 / 删除`；底部「重新总结这条音频」。
- 两个面板互相可达：原音频里点「AI 总结」跳到对应总结；AI 总结里点「原音频」跳回原音频。
- 侧边栏第一个按钮（笔记）**先弹两个选项**：原音频 / AI 总结笔记（第二轮按真机反馈改的——之前是直接跳进 AI 总结笔记）。导出时**先选格式**（中文 Word / 中文盲文 Word / 盲文 BRF），如果是 AI 总结还会多给一个「改用原音频导出」选项。
- **我的 → 导出记录**：历史 BRF 列表，每条可「下载」；清空记录走通用确认弹窗（会写明"音频和 AI 总结都不会动"），取消后条数不变（实测 3/3）。
- **我的 → 帮助与语音指令**：唤醒词卡 + 7 条可用指令 + 3 条禁用说法，与助手浮层的「小语，帮助」互补（浮层给当前状态可用项，这里给完整清单）。
- **录音已保存**：录完立刻出现，三个去向按钮（交给 AI 转文字 / 回放原音频 / 先放着），选"回放"直接打开原音频面板。

> 在画布里改完后，用编辑器右上角 **Save project** 导出 JSON（会落到 `design/m3e-exports/`），告诉我文件名，我把它合并回 `m3e-design.json` 和 `index.html`。

### 画布排版（2026-10-04 按真机比例重排）

画布不再手摆坐标，而是用排版引擎 `_tools/relayout-mobile.py` 从声明式描述生成：

- **手机帧 430 × 932（≈ 9:19.5，接近 iPhone 15 / Pixel 的竖屏比例）**，16 屏全部同尺寸
- 内容边距 16，内容宽 398；纵向节奏 **同区 12 / 跨区 20 / 大区块 40**
- 底部 Tab 高 104，固定在帧底（帧高 − 104），内容在它之上滚动
- 卡片内的按钮/文字用固定节奏：区标题 +8 → 圆形按钮 +44（92 dp 圆）→ 按钮文字 +106 → 说明 +172 → 分隔线 +220 → 脚注 +252
- 底部面板底板贴帧底（如原音频面板 300→932）
- 画布按 5 列网格摆放（16 帧排成 5×3 + 1，第 4 行只有 `remind` 一帧），列距 80、行距 100（`relayout-mobile.py` 里 `i % 5` 与 `W+80 / H+100`）

排版一致性由 `_tools/check-mobile.py` 强制校验（下面是 2026-10-04 我实跑的输出，含新增的 `remind` 帧）：

```
frames:16 groups:102 items:157  size:430x932

[OK] no overlap / no overflow / spacing ok / all targets valid
  home       430x932  groups=13  content_bottom=932
  recording  430x932  groups=9   content_bottom=932
  paused     430x932  groups=8   content_bottom=932
  assistant  430x932  groups=10  content_bottom=632
  me         430x932  groups=8   content_bottom=932
  confirm    430x932  groups=6   content_bottom=932
  audio      430x932  groups=5   content_bottom=632
  notes      430x932  groups=5   content_bottom=632
  todos      430x932  groups=6   content_bottom=712
  exports    430x932  groups=5   content_bottom=552
  help       430x932  groups=5   content_bottom=782
  catalog    430x932  groups=7   content_bottom=692
  export     430x932  groups=5   content_bottom=932
  saved      430x932  groups=3   content_bottom=932
  brand      430x932  groups=2   content_bottom=135
  remind     430x932  groups=5   content_bottom=485
```

它检查 6 件事：**重叠**、**越界**（水平 >430 / 纵向 >932）、**间距**（<8px 报警）、**底板裁剪**、**帧宽高是否统一**、**跳转目标**是否存在 + **id 全局唯一**（组 id 和组件 id 不能重名）。

改了画布后跑这两条就能保证排版不退化：

```powershell
python "C:\Users\HP\Desktop\yuyi-preview\_tools\relayout-mobile.py"   # 重排全部 16 屏（430x932）
python "C:\Users\HP\Desktop\yuyi-preview\_tools\post-layout.py"       # 修同名 id + 校验排版
```

> 注意：M3E 编辑器服务在跑的时候会重写 `D:\m3e-canvas\out\`，所以重排前先 `canvas.mjs stop`。
> 排版参数集中在 `_tools/relayout-mobile.py` 顶部：`W,H,PAD,CW = 430,932,16,398`、`GAP_S,GAP_M,GAP_L = 12,20,40`、`NAV_H = 104`，改这几个数就能整体调密度。

---

## 1. 需求 → 组件对照表

| 提示词条目 | 实现位置（DOM id / class） | 状态 |
|---|---|---|
| 1. 顶部 Header：Logo + 「语忆」+ slogan | `.header` / `.brand-logo` / `.brand-name` / `.brand-slogan` | ✅ |
| 1. 右上角 `…` 更多操作 | `#moreBtn` | ✅ 弹通用确认弹窗 + 说明入口 |
| 1. 日期「今日 · 10月3日 星期六」 | `#todayLine` | ✅ 按真实日期自动生成 |
| 1. 大标题 + 提示文字 | `.header-title` / `.header-sub` | ✅ |
| 2. 卡片顶部小字「课堂原声记录」 | `#recordCardTitle` | ✅ |
| 2. 深墨绿圆形录音主按钮（麦克风 + 文字） | `#recordBtn`（`data-state="idle\|recording\|paused"`） | ✅ 点击 → 录音 → 暂停 → 继续 |
| 2. 点击后本地播报预设话术 | Toast + `#srStatus` | ✅ 文案：「好的，开始录音。录音结束时请说‘小语，结束’。」 |
| 2. 按钮下方提示 + 卡片底部小字 | `#recordHint` / `.card-foot` | ✅ |
| 2. 「小语，结束」**仅录音状态**生效 | `ROUTES.end` | ✅ 非录音时提示不生效（不会退出助手） |
| 2. 结束保存音频 → 确认弹窗 | `#confirmDialog` | ✅ 「录音已经保存。是否交给 AI 转换为文字？」 |
| 2. 录音内容与助手指令隔离 | 视觉/文案说明 + 逻辑分支 | ⏳ 需接入真实 VAD 后做门控 |
| 3. 呼叫组件：菱形图标 + 输入框 + 呼叫按钮 | `.call-card` / `#callInput` / `#callBtn` | ✅ |
| 3. 输入框下小字提示 | `#callSub` | ✅ |
| 3. 呼叫 → 助手浮层 + 固定话术 | `#assistant` / `#asstCase` | ✅ 播报完整欢迎话术 |
| 4. 右侧悬浮侧边栏 4 按钮（笔记/待办/目录/导出） | `#sideTools` / `#sideNote` `#sideTodo` `#sideDir` `#sideExport` | ✅ 常驻、不随滚动消失、不挤压布局 |
| 4. 笔记面板（查看/朗读/管理） | `#notesPanel` ⚠️ 已改版为 **AI 总结笔记面板** | ✅ 列表 + 搜索 + 朗读/原音频/标签/导出/删除 |
| 4b. 原音频面板（新增） | `#audioPanel` | ✅ 波形 + 播放/暂停 + 重命名 + 删除 + 定位到 AI 总结 |
| 4. 目录面板（集合 + 条目 + 上一组/下一组） | `#dirPanel` ⚠️ 顶部改为「原音频 / AI 总结笔记」两个入口按钮 | ✅ 3 组示例目录，可切换、可跳条目 |
| 4. 待办面板（新增/查看/完成/删除/振动提醒/通知） | `#todoPanel` / `#vibPanelCard` `#vibSwitch` `#vibTestBtn` `#notifySwitch` `#notifyState` `#permCard` `#permBtn` `#todoList` `#todoStep` | ✅ 安卓振动提醒（三段式节奏）+ 通知权限开关 + 每条待办显示提醒时间与方式徽标（旧「不调用系统闹钟」免责 banner 已删除，改成能力卡） |
| 4. 导出（**先选格式**：中文 Word / 中文盲文 Word / 盲文 BRF） | `#sideExport` → `openExportFlow()` → `exportAs()` | ✅ 选格式 → 复述确认 → 生成 → 完成提示；`exportLog` 会新增一条（文件名 / 格式 / 体积），并同步到「我的 → 导出记录」 |
| 4. 所有修改操作先复述再确认 | `openConfirm()`（唯一通用弹窗） | ✅ 归类/标签/删除/待办/导出全部走它 |
| 4. 原文永不被改写，AI 只作附注 | 文案 + 弹窗 `note` 字段 | ✅ UI 层已表达 |
| 5. 底部 Tab（首页/笔记/AI/我的，默认首页） | `.tabbar` / `#tabHome` `#tabNote` `#tabAI` `#tabMe` | ✅ |
| 6.1 助手浮层：状态文本 / 播报文本 | `#asstState` / `#asstCase` / `#asstHint` | ✅ |
| 6.1 退出 / 返回 / 重复 / 帮助 / 取消 / 结束 | `ROUTES` + `.chip[data-cmd]` | ✅ 点击 chip = 模拟说出该口令 |
| 6.2 通用确认弹窗（复用） | `#confirmDialog` + `openConfirm()` | ✅ 支持：确认 / 其他选项 / 取消，可动态改写文案 |
| 6.2 示例 1 原话已保存 | 录音结束 → 保存 → 转写确认 | ✅ 改为「录音已保存 → 交给 AI 转文字 → AI 附注建议」链路 |
| 6.2 示例 2 归类 + 标签建议（可「换一个目录」） | `assignSuggestion()` | ✅ 「换一个目录」会循环切换并再次确认 |
| 6.2 示例 3 待办新建确认 | `addTodo()`（兼容旧调用，内部转入 5 步流程） | ✅ 先复述再确认，走 `openConfirm()` |
| 6.2 示例 4/5 导出确认 + 完成提示 | `openExportFlow()` | ✅ 文案与提示词一致 |
| **待办振动 §3.2 三段式节拍（安卓）** | `doVibrate()` / `vibStart()` / `vibStop()`；常量 `VIB_GROUP` `VIB_GROUPS` `VIB_GAP` | ✅ 实测 3 组、单组 1250 ms、组间 2000 ms（振动窗口 7.75 s，**不是 18 s**）；探针 A1–A6 PASS |
| **待办振动 §3.3 常驻系统通知** | `pushTodoNotification()` / `closeTodoNotification()` | ✅ 实测 `requireInteraction:true`、`tag=yuyi-todo-<id>`、标题「待办提醒」、正文=待办全文；探针 C2–C5 PASS |
| **待办振动 §3.4 慢速语音播报 2 遍** | `ttsSpeak()` / `ttsStop()`（`speechSynthesis`） | ✅ 实测 `rate=0.85`、第一组振动结束后 +1250 ms 起播、重复 2 遍；探针 A6 / C6 PASS |
| **待办振动 §3.5 知道了 / 延后十分钟** | `ackReminder()` / `snoozeReminder(10)`；`#remindDlg` `#remindAckBtn` `#remindSnoozeBtn`；chip `todoAck` `todoSnooze` | ✅ 实测（细节见 §2）；探针 D1–D5 PASS |
| **待办振动 §4 后台保活四层** | `calibrateAll()` / `startHiddenWatch()` / `stopHiddenWatch()` / `requestWakeLock()` / `releaseWakeLock()` | ✅ 四层均已实现；探针 E1–E5 全 PASS（60s/90s/30s 阈值 + 定时器装上/卸下 + wakeLock 请求与释放）；**wakeLock 只断言到「调用了 API」，没断言真机拿到锁** |
| 7.1 禁用：暂停/继续/语速的语音控制 | 无对应 chip；按钮是唯一入口 | ✅ 助手面板底部有明确说明 |
| 7.2 不做自由闲聊，低置信请重说 | `#asstHint` 文案 + 无文本自由对话 | ✅ |
| 7.3 待办提醒的真实边界（旧表述「不承诺系统闹钟 / 锁屏震动」**已作废**） | `#vibPanelCard`（能力卡）+ `#vibState` + 提醒弹窗 `.dlg-note` | ⚠️ 安卓 Chrome/Edge 下是**真振动**（`navigator.vibrate` 三段式）+ 常驻通知；iOS 没有网页振动 API；振动强度受手机马达影响；浏览器被彻底查杀、微信内置浏览器后台保活弱时不会触发 —— 详见 §2、§5 |
| 8. 颜色规范 | CSS 变量 `--green/--orange/--card-bg/--ink/--muted` | ✅ |

层级（z-index）：页面 0 → Tab 20 → 侧边栏 30 → 面板 40 → 助手浮层 50 → Toast 60。

---

## 2. 我做的可验收交互（已用无头浏览器逐条跑通）

- 录音按钮：开始 → `暂停录音|recording`，再点 → `继续录音|paused`，再点 → `暂停录音|recording`
- 「小语，结束」：返回 idle + 弹窗「录音已保存」+ 按钮 `交给 AI 转文字 / 暂不处理 / 取消`
- 二次确认：`转写完成` → `AI 附注建议…要确认执行吗？`（确认 / 取消）；确认后标签变为「高等数学 / 待复习」
- 助手：呼叫按钮与 Tab【AI】都能唤起；「小语，退出」关闭；非录音时点「小语，结束」→ 提示不生效且不退出
- 帮助弹窗：按当前状态列出可用指令，录音状态才出现「小语，结束」
- 导出：确认弹窗 → 完成后弹出「盲文文档导出完成。原文和笔记内容没有变化。」+ 卡片出现已导出标记
- 侧边栏底部 595px < Tab 顶部 867px，无重叠；无 console 报错

### 改版后的新流程（同样逐条跑通）

- **目录页**：顶部两个入口按钮文案为 `原音频` / `AI 总结笔记`；点「原音频」→ 原音频面板打开、目录页关闭
- **原音频面板**：3 段音频，统计「共 3 段原音频 · 共 26:17」；单条显示 `原声 12:40 · 24.6 MB · 10月3日 10:24 · 已有 AI 总结`；操作 `播放 / AI 总结 / 重命名 / 导出 / 删除`
- 播放 → 波形变 `wave playing` + Toast「正在播放原声」，再点变暂停
- 点「AI 总结」→ 自动切到 AI 总结笔记面板并定位该条（副标题「全部由 AI 从原音频里总结提炼 · 只是附注建议，不改写原话」，标签 `AI 总结|高等数学|待复习|原音频 12:40`）
- AI 总结里点「原音频」→ 切回原音频面板（双向可达）
- 重命名：弹「重命名这段原音频？」→ 按钮 `确认重命名 / 取消` → 确认后标题加「（已重命名）」
- 删除原音频：弹「删除这段原音频？」+ 说明「对应的 AI 总结也会一起移除」；**取消后仍是 3/3 条**；确认后音频 3→2、AI 总结同步 3→2
- 「重新总结这条音频？」→ 确认后总结正文变为「要点（已更新）：① …」（修掉了早期的「① ①」重复前缀）
- 助手业务指令 chips：`原音频 / AI 总结 / 重新总结 / 提醒我…… / 打开目录 / 导出盲文 / 搜索 / 加标签 / 归类`；点「原音频」打开面板并播报状态文案
- 从原音频导出：弹窗显示「导出对象：《…》（来自原始音频）」，按钮 `确认导出 / 换一段音频 / 改用原音频导出 / 取消`
- 待办面板的旧免责 banner「不调用系统闹钟 / 锁屏震动」**已删除**，换成 `#vibPanelCard` 安卓振动提醒能力卡（旧探针依赖的 `.banner` 类故意保留在这张卡上）

### 待办振动提醒（安卓）· 2026-10-04 落地

来源规范：《安卓手机端专属·待办振动提醒功能规范（公益落地版）》；接口契约：`_tools/todo-vibration-contract.md`（冻结 v1.1）。
落地方式：全部用浏览器标准 API（`navigator.vibrate` / `Notification` / `visibilitychange` / `navigator.wakeLock` / `speechSynthesis`），零外部依赖，仍是 `index.html` 单文件。

> **证据口径（重要）**：标「**实测**」的依据是 chrome-headless-shell 注入桩跑出的结果（`__seq` 调用序列、`vibrateCalls`、DOM 读回；页面基准日 2026-10-04 星期日，Asia/Shanghai）；标「源码核对」的是我读 `index.html` 确认的实现事实；标「**待验证**」的**没有**端到端证据，不许当结论用。
> **独立验收闸门（已交付，我亲自跑过两个方向）**：`_tools/verify-todo-vibration.ps1` 是带退出码的探针——**61 项断言 / 3 个场景**（场景 1 正常路径 A/B/C/D/E/G/H；场景 2 不支持振动 + 通知被拒 F1/F2；场景 3 过期待办汇总 + 后台延迟 + 多条串行 F3/F4/F5）。跑法：`powershell -ExecutionPolicy Bypass -File _tools\verify-todo-vibration.ps1`（`-Page <其它 index.html>` 可换目标；页面里的 `window.__yuyi` 是它唯一的只读出口）。
> **鉴别力实测（我实跑）**：改造前 `index.html`（从 `语忆前端预览.zip` 解出，118,180 B，sha256 `6A34B4DFC1CA687F…`）→ **PASS 0 / FAIL 61，exit 1**；当前 `index.html`（168,199 B，sha256 `F1656870F6094FDD…`）→ **PASS 61 / FAIL 0，exit 0**（这两组用的探针版本是 `4088EA7A27EE1E7E`）。**局部回归**另有 5 组窄变异实测，见下表。
> **核对基线**：`index.html` 168,199 字节、sha256 前 16 位 `F1656870F6094FDD`（Lead 已冻结）；此后若再改行为，本节需要一次 delta 复核。

**窄变异实测（每次只改 1 处；改 `%TEMP%` 副本、真文件不动；`-Page` 指向副本跑闸门）** —— M3/M4 由 Lead 跑；**M1/M2/M5 我复跑，转红集合逐条一致**（探针 `AEF2275D91C6DA18`，exit 1）。

| 变异（只改 1 处） | 实际转红 | 汇总 |
|---|---|---|
| M1 振动节拍末项 `200`→`300`（单组 1250→1350 ms） | `A1` `A3` `A4` `A5` `A6` `C1` | 55 / 6 |
| M2 通知 `requireInteraction: true`→`false` | 只有 `C3` | 60 / 1 |
| M3 `TTS_REPEAT = 2`→`1` | 只有 `C6` | 60 / 1 |
| M4 `WAKELEAD_MS = 30000`→`20000` | 只有 `E1` | 60 / 1 |
| M5 删掉 `#remindAckBtn` 的 `aria-label` | 只有 `G2` | 60 / 1 |

- **M1 为什么红 6 条（不是误报）**：`A3` 断言单组时长、`A5` 断言**由它派生**的组间重排 delay `3250`、`A6` 断言**由它派生**的 TTS 启动延迟 `1250`、`C1` 断言准确的节拍串 `vibrate:200/100/600/150/200`——这几条本来就是**同一事实的不同投影**，一起转红是正确行为，不代表探针脆弱。M2–M5 都**恰好 1 条**转红，说明断言之间没有互相遮蔽。
- M1 / M2 / M5 三组我**亲自复跑**，转红集合与上表逐条一致（用的是当前版探针 `AEF2275D91C6DA18`）；M1 复跑时 **F4d 没有转红**，说明「把场景 3 的 TTS 快照从 `1300ms` 推到 `1800ms`」这处余量修复有效（见 §8 复现要点）。

#### 1) 语音录入 5 步（`todoStart()` → `todoStepNext()`）

| 步 | 入口 | 播报 / 界面 | 校验与失败处理 |
|---|---|---|---|
| 1 内容 | 说「小语，待办事项提醒」，或点「新建」，或 chip `data-cmd="todo"` | `请口述录入待办事项内容，说完后说完成录入。`；`#todoStep` 显示「第 1 / 4 步 · …」 | 内容为空 → 「没有听清待办内容，请再说一遍，说完说『完成录入』。」，不前进 |
| 2 复述确认 | 点「完成录入」或回车 | `openConfirm()`：`已识别待办事项：XXX，请问内容是否正确？` | 选「重新录」回到第 1 步 |
| 3 时间 | 确认内容后 | `请问设置提醒时间？` | `parseWhen()` 返回 `null` → 「抱歉，我没有听清时间，请说清楚几点几分」；连续 2 次失败追加「您可以说几月几日几点几分。」 |
| 4 方式 | 时间确认后 | `提醒方式选择闹钟响铃，还是震动？` | 没听清 → 「请说『震动』或『闹钟响铃』」；说「震动」但浏览器不支持 API → 当场降级 `ring` 并播报「当前浏览器不支持震动，已切换为声音提醒」 |
| 5 最终确认 | 方式确认后 | `待办事项：XXX；提醒时间：XXX；提醒方式：震动提醒，请问确认保存吗？` | 确认才写入 `state.todos`；取消退回第 4 步 |

- 保存成功播报：「待办事项保存成功，到点将震动提醒。」（选铃声则「…到点将铃声提醒。」）；保存时立即 `scheduleAll()` 排调度。
- 保存振动待办时：`needPermGuide()` 为真 → 弹通知权限引导（`#permCard` / `#permBtn`）；`firstVibGuide()` 首次提示「添加到浏览器主页 + 允许浏览器后台运行 + 关闭省电优化」。
- **话术一致性**：5 步文案与契约 §5 逐字一致（**源码核对，非实测**）；「5 步逐步走完的整条链路」**没有**端到端实测——探针断言的是 chip / `ROUTES` 存在性与解析、应答行为，**没有**走完整 5 步。

#### 2) 触发顺序（实测 `__seq`）

```
wakelock-request:screen → vibrate:0 → tts-cancel → vibrate:200/100/600/150/200 → notify:待办提醒
```

- `vibrate:0` / `tts-cancel` 是 `stopReminder()` 的**清理动作**（触发新一条前先停掉上一条），**不是节拍的一部分**。
- 真实节拍调用是 `vibrate: 200/100/600/150/200`：短震 200 → 停 100 → 长震 600 → 停 150 → 短震 200，单组 **1250 ms**。
- 通知与振动**同刻**（`notify:待办提醒` 紧跟在节拍之后）；TTS 在 **+1250 ms**（第一组振动结束后）才出现。
- 振动总计 **3 组**（实测 `vibrateCalls` 长度 3：`[0]`、`[200,100,600,150,200]`、`0`）；3 组 + 2 次组间隔 2000 ms = **7.75 s 振动窗口**。
- 通知 options（实测）：`requireInteraction === true`、`tag = yuyi-todo-<id>`、标题 `待办提醒`、正文 = 待办全文（后台挂起延迟时附「（原定提醒时间HH:MM）」）。
- TTS（实测）：**慢速重复 2 遍**、`rate === 0.85`，文本 `待办提醒：过期丙，原定提醒时间03:38`。

> **规范 §3.2 自身数字不自洽，Lead 的裁定（如实记录）**：规范写「共循环 3 组，每组间隔 2 秒，总时长约 18 秒」，但按它自己的节拍算出来是 `1250×3 + 2000×2 = 7750 ms ≈ 7.75 s`，**算不出 18 s**。
> 裁定：**节拍数字优先**（它们是精确值）；「约 18 秒」解释为**整条提醒的生命周期窗口**（振动窗口 7.75 s + TTS 慢速播报 2 遍 ≈ 18 s），对应常量 `REMIND_WINDOW_MS = 18000`（用于到点后释放唤醒锁）。
> 所以**不要**读成「18 秒的振动」：振动是 3 组、共 7.75 s；18 s 是提醒窗口。

#### 3) 知道了 / 延后十分钟（实测）

| 操作 | 入口 | 实测结果 |
|---|---|---|
| 知道了 | 说「知道了 / 明白了 / 停」、chip `data-cmd="todoAck"`、`#remindAckBtn` | `vibrateCalls` 末项 = `0`；`activeTodo === null`；该待办 `reminded === true`；弹窗隐藏；`notif.live` 清空；`nextPending()` 指向下一条 |
| 延后十分钟 | 说「延后十分钟 / 等会儿再提醒」、chip `data-cmd="todoSnooze"`、`#remindSnoozeBtn` | `snooze` 自增 1；`reminded === false`；`at - now === 600 s`（实测 600）；重新进入待调度 |

- 触发后（实测）：`#remindDlg` 打开、`#remindBody` = 待办全文、焦点自动进入 `#remindAckBtn`。
- 多条同时到点（实测）：**逐条串行**，同一时刻只有一个 `activeTodo`，处理完一条才触发下一条（振动与语音不叠加）。
- 在待办列表里点「完成」并确认，等同「知道了」（`ackReminder(true)`）；删除正在提醒的待办会先 `stopReminder()` 再移除 —— 源码核对。

#### 4) 后台保活四层

| 层 | 触发点 | 行为 | 证据 |
|---|---|---|---|
| 1 时间校准 | `visibilitychange`（回到前台）、`focus`（屏幕点亮/切回）、`pageshow`、`online` / `offline` | `calibrateAll(reason)`：全量重算所有 `at` 的剩余毫秒并重排定时器（`scheduleAll()`） | 源码核对 + 阈值实测（探针 E1：60s / 90s / 30s 三个常量） |
| 2 锁屏校验 | 页面隐藏时 `startHiddenWatch()` 起的 60 s 定时器（`HIDDEN_CHECK_MS`） | 与预期时刻比较，漂移 > 30 s（`DRIFT_LIMIT_MS`）→ `calibrateAll("drift:…")`；隐藏态到点直接 `fireReminder()`，不漏触发 | **实测**（探针 E2：隐藏时确实装上、可见时卸下 `hiddenTimer` + `heartbeatTimer`；E3：实际 `setInterval` delay 里出现 `60000` / `90000`） |
| 3 心跳 | 隐藏态 90 s 定时器（`HEARTBEAT_MS`） | 只更新时间戳 `sched.heartbeatAt`（极小计算、不耗流量），空闲时重排调度 | **实测**（探针 E3，同上；「不耗流量」是源码事实） |
| 4 唤醒锁 | 触发前 30 s（`WAKELEAD_MS`） | `navigator.wakeLock.request('screen')`；提醒结束 / 窗口结束立即 `release()`；不支持则静默跳过 | **实测**（探针 E4 请求 + E5 释放，均 PASS）；但**只到「调用了 API」这一层——没有断言真机是否真的拿到锁** |

#### 5) 异常 7 条（逐条对照实测）

| 场景 | 实测结果 | 证据 |
|---|---|---|
| 不支持振动 API | `vibSupported() === false`；`#vibTestBtn` 隐藏、`#vibSwitch` 禁用；`#vibState` =「当前浏览器不支持振动 API，已自动降级为铃声提醒」；触发时该待办 `mode` 由 `vibrate` 改为 `ring`；`#srStatus` =「当前浏览器不支持震动，已切换为声音提醒」 | 实测 + 探针 **F1a–F1e** |
| 通知权限被拒 | 待办**保留**在列表；`notif.live` 为空、无通知调用；弹窗与前台振动路径仍正常；`#srAlert` =「未获得通知权限，后台可能无法收到提醒，建议在设置中开启」 | 实测 + 探针 **F2a–F2d** |
| 页面被系统清理 | 下次打开 `announceOverdue()` 汇总过期待办并逐条播报（文案见下） | 实测 + 探针 **F3a–F3c**（按 `at` 升序 + alert/assertive 通道） |
| 后台挂起延迟 | `remind.overdue === true`；弹窗元信息含「后台挂起导致延迟，原定提醒时间 03:37」；通知 body 含原定时间；TTS 文本含「原定提醒时间」 | 实测 + 探针 **F4a–F4d** |
| 多条同时 | 串行、不叠加（见上表「知道了 / 延后十分钟」） | 实测 + 探针 **F5a / F5b** |
| 静音 / 勿扰 | 只发送标准振动请求，**不读取也不伪造系统静音状态**（设计自证：`window.__yuyi.muteSystemHint === false`）；无额外提示 | 实测 + 探针 **F5c**。⚠️ **规范 §3.2 原文「安卓静音模式、勿扰模式下振动正常触发，不被系统屏蔽」与平台事实不符**：[MDN](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/vibrate) 明确写 "Some devices may not vibrate if they are in Silent mode or Do Not Disturb (DND) mode"。UI 文案已改为「静音/勿扰下是否振动取决于手机系统设置」，不再做这个承诺（探针 **N3** 守住这句） |
| 麦克风权限不足 | 实现为 `checkMicPermission()`：`navigator.permissions.query({name:'microphone'})` 为 `denied` 时播报「麦克风权限不足，无法语音录入待办，提醒功能正常可用」 | **待验证**：探针 **F7** 只断言 `checkMicPermission` 存在且是 `function`，**没有**把 `denied` 分支的播报端到端跑一遍 |

> 上面每一行都是**单独场景**的实测。补充一条：如果同一轮里「不支持振动」和「通知权限被拒」**同时**发生，`alertSay()` 会把两句**合并成一句**播报（「当前浏览器不支持震动，已切换为声音提醒。未获得通知权限，后台可能无法收到提醒，建议在设置中开启」），避免后一条把前一条顶掉、纯听觉用户漏听（`fireReminder()` 里的 `degradedMsg` + `permMsg`）。**这条已由独立探针 F1e 实测通过**——修之前 `toast()` 内部会调 `say()` 写 `#srStatus`，约 30 ms 内就把降级提示顶掉了（纯听觉用户漏听），属于真缺陷。

过期待办汇总实测文案（`#srAlert`，`role=alert` / `aria-live=assertive`，按 `at` 升序）：

```
您有2条已过期的待办提醒，分别是：过期丁（原定提醒时间03:35）；过期戊（原定提醒时间03:39）。
```

#### 6) 时间解析黄金用例（实测，页面基准日 2026-10-04 星期日）

| 输入 | 解析结果 | 输入 | 解析结果 |
|---|---|---|---|
| 下周一早上八点半 | Oct 5 08:30 | 今天 20:00 | Oct 4 20:00 |
| 下周三 | Oct 7 09:00 | 18:30 | Oct 4 18:30 |
| 周一 | Oct 5 09:00 | 下午三点十五分 | Oct 4 15:15 |
| 周日 | Oct 11 09:00 | 十点半 | Oct 4 10:30 |
| 明天下午三点 | Oct 5 15:00 | 晚上八点 | Oct 4 20:00 |
| 后天早上七点 | Oct 6 07:00 | 周五下午2点 | Oct 9 14:00 |
| 12月25日 18:30 | Dec 25 18:30 | 随便说点什么 | `null`（解析失败） |
| 10月8日 09:00 | Oct 8 09:00 | 2小时后 / 半小时后 / 10分钟后 | 相对时间（now + N） |

解析口径（实测 + Lead 裁定）：

- 明确指定了**已经过去**的日期 → 返回 `null`（视为解析失败，请用户重说）。规范原文**没有**规定这种情况，这是 Lead 的裁定（见 §5）。
- 只说了几点、且今天该时刻已过 → **顺延到明天**；只说了日期、没说时刻 → 当天 **09:00**。
- 同一句里既有日期又有时刻、但结果已过去 → `null`（有明确日期时**不**顺延）。

#### 7) 回归（既有探针 + 画布，均在最新 `index.html` 上复跑）

- **振动提醒本体的闸门**：`_tools/verify-todo-vibration.ps1`（见上面「证据口径」），当前版本 **PASS 61 / FAIL 0 / exit 0**。
- `_tools/verify-ui.ps1`、`verify-newflows.ps1`、`verify-newscreens.ps1` 三个既有探针在**最新** `index.html` 上复跑：**全部无 JS 异常**（`throwAt=(none)`）、`probe-ok`。
- `verify-newflows.ps1` 依赖的 `#todoPanel .banner` 选择器**故意保留**（`#vibPanelCard` 同时带 `vib-card` 和 `banner` 两个类，见 `index.html` 里那条注释）。
- 画布：`python _tools/check-mobile.py` → `frames:16 groups:102 items:157 size:430x932` + `[OK] no overlap / no overflow / spacing ok / all targets valid`（我实跑）。
- 注意：三个既有探针是**旧功能回归**，不覆盖振动提醒本身。

#### 8) 探针复现要点（踩过的坑，后人别重踩）

| 坑 | 现象 | 正确做法 |
|---|---|---|
| stub 注入位置 | 注入在页面脚本之后 → 观测不到真实调用顺序 | stub 必须插在 `<head>` 之后、页面 `<script>` **之前** |
| 快照取早了 | 在 `ack` **之前**取 `__seq` → 看不到 `wakelock-release`（释放发生在 ack 时） | 断言「释放唤醒锁」必须在 **ack 之后**再取序列（探针 E5） |
| 焦点归还误判 | 同一场景里 ack 后立刻排了第二条待办，第二个弹窗**合法地**再次抢走焦点 → 误判「焦点没归还」 | 焦点归还的断言要单独场景、单独诊断（探针 G5） |
| 焦点归还的时序 | 弹窗隐藏后**同一 tick 内** `activeElement` 仍是 `#remindAckBtn`，浏览器对 `display:none` 的焦点修正是**异步**的 | **延后 250 ms** 再观测（实测 +250 ms 变成 `BODY`） |
| 高度量错 | headless 虚拟时间下 `.dialog` 的 `animation:pop` 冻在 `scale(0.94)`，`getBoundingClientRect()` 读出 **48.88** | 用 **`offsetHeight`**（真实 52 px；探针 G6 就是这么断言的） |
| TTS 快照余量不足 | 场景 3 的 TTS 快照只比 TTS 启动晚 200 ms，而 TTS 启动时刻 = `VIB_GROUP_MS`；于是「改节拍」会**连累 F4d**（原定提醒时间那条）误红 | 快照时刻从 `1300ms` 推到 **`1800ms`**（余量 >400 ms）；复测 M1 时 **F4d 不再误红** |
| 探针文件编码 | 无 BOM 的 UTF-8 在 Windows PowerShell 5.1 下按 ANSI 解码，中文 here-string 的 `'@` 终止符会**解析失败**（表现为 `Missing closing ')'`） | 存成 **UTF-8 with BOM**（当前已是）；`powershell -ExecutionPolicy Bypass -File` 与 pwsh 两种跑法都验证过 |

---

## 3. 故意留空 / 待你后续给功能时接入的点

| 位置 | 当前行为 | 接入方式 |
|---|---|---|
| **待办·振动** | ✅ **已接真实 `navigator.vibrate`**（不再是「只驱动 UI」） | `doVibrate()` / `vibStart()` / `vibStop()` 是唯一出口；节拍常量 `VIB_GROUP` `VIB_GROUPS` `VIB_GAP`；能力探测 `vibSupported()`，不支持时 `mode` 降级 `ring` |
| **待办·系统通知** | ✅ **已接 `Notification`**（常驻、不自动消失） | `pushTodoNotification()` / `closeTodoNotification()`；权限走 `requestNotifyPermission()` / `afterPermission()`，状态读 `Notification.permission` |
| **待办·后台保活** | ✅ **已接 `visibilitychange` / `focus` / `pageshow` / `online` / `navigator.wakeLock`** | `calibrateAll(reason)` 全量校准；`startHiddenWatch()` 起 60 s 校验 + 90 s 心跳；`requestWakeLock()` / `releaseWakeLock()` 于触发前 30 s / 结束即释放 |
| **待办·语音播报** | ✅ **已接 `speechSynthesis`** | `ttsSpeak(text, 2, 0.85)` / `ttsStop()`；浏览器不支持时回落到 `say()` |
| **待办·调度与应答** | ✅ 已接（内存调度） | `scheduleAll()` / `nextPending()` / `fireReminder(id)` / `ackReminder()` / `snoozeReminder(10)` / `stopReminder()` / `announceOverdue()`（页面被清理后汇总过期） |
| **待办·语音录入（ASR）** | ⏳ 5 步流程仍靠 chip / 输入框喂文本 | 语音引擎（§10b）已就绪：把识别文本写进 `#todoInput` 再调 `todoStepNext()` 即可接上；`todoStart()` / `todoStepNext()` 仍是 5 步流程唯一入口 |
| **待办·麦克风权限** | ✅ 已接 `navigator.permissions.query({name:'microphone'})` | `checkMicPermission()`；`denied` 分支文案已实现，但**端到端播报待验证** |
| 录音 | 只驱动 UI 状态与计时 | `startRecording()` / `pauseRecording()` / `stopRecording()` 三个函数是唯一入口，替换成 `MediaRecorder` 即可 |
| ~~唤醒词「小语」~~ **已接入（第二轮）** | 状态药丸 = 语音开关 | `§10b` 用 Web Speech API（`webkitSpeechRecognition`）持续识别；命中唤醒词（小语/小雨/小宇/小羽/小玉/小v…）→ `openAssistant()`。药丸按**真实状态**显示：未开启=灰「点这里开启语音唤醒」／识别中=绿「小语正在待机监听 · 听到「…」」／浏览器不支持=橙「本浏览器不支持语音唤醒」。**不再假装一直在监听** |
| ~~指令识别~~ **已接入（第二轮）** | 语音 与 chip 点击走同一张路由表 | `VOICE_CMDS` 顺序匹配 → `ROUTES[key]()`；唤醒词可省略（「结束录音」「打开原音频」直接生效）。喊了「小语」但没命中时**明确说不知道并给出可用指令**，不猜 |
| TTS 播报 | 待办提醒 + **AI 总结「朗读」** 都是真实 `speechSynthesis` | `ttsSpeak(text, times, rate, onEnd)` / `ttsStop()`；「我的 → 朗读语速」真的驱动朗读语速（`state.ttsRate`）。朗读按钮会变成「停止」，读完自动复位；其余界面播报仍是 `say()` / `alertSay()` / `toast()` |
| 语音识别的代价（**新增·必读**） | **不是纯本地识别** | Chrome/Edge 会把音频送到语音服务换文字，**需要联网**。连不上时药丸显示「识别服务连不上 · 点这里重试」并提示改用按钮；麦克风被拒时提示去地址栏锁形图标里开启。不想联网就用按钮/输入框/chip 完成同样的事 |
| 数据 | `state.notes`（AI 总结）/ `state.audios`（原音频）/ `state.todos`（已扩展 `at` `mode` `reminded` `snooze` `firedAt`）/ `DIRS` 内存数组；另有两条 localStorage 标记 `yuyi.todo.permAsked`（权限引导只弹一次）、`yuyi.todo.backGuide`（后台稳定性提示只弹一次） | 改为接口拉取，渲染函数 `renderNotes()` / `renderAudios()` / `renderTodos()` / `renderDir()` 保持不变 |
| 原音频播放 | 波形变为播放态 + Toast | `state.playingId` 已就位，接 `<audio>` 或播放器后由它驱动 |
| BRF 导出 | 弹窗 + 完成提示 | `openExportFlow()` 的确认回调里换成真实下载/接口 |
| 转写（把录音变成逐字稿） | 仍是演示数据 | 第二轮把「录音结束」改成了 **① 归到哪个大类 → ② 是否生成 AI 总结笔记 → ③ 是否导出（中文 Word / 中文盲文 Word / 盲文 BRF）** 的三步引导；真正把音频转成文字仍需接后端（本地 Vosk 离线模型 / 云端转写）。（**后续版本已接入**：手机端 Vosk WASM 离线识别，见 README） |

---

## 4. 无障碍实现（面向盲人/低视力用户）

- 全站语义化标签、按钮一律 `<button>`；图标 `aria-hidden`
- 状态变更双通道播报：`#srStatus`（polite）+ `#srAlert`（assertive），录音/弹窗/面板切换都会播报
- 弹窗 `role="dialog"` / `role="alertdialog"` + `aria-modal`，打开时焦点移入、Tab 焦点圈定、关闭后焦点归还触发元素
- `Esc` = 返回上一步（等同「小语，返回」）
- 键盘操作才显示焦点环（鼠标/触屏不显示橙色描边，避免视觉噪音）
- 触控目标：主按钮 44–50px；已把「待机监听」药丸加高到 ≥34px
- 支持 `prefers-reduced-motion`（关闭脉冲动画）与 `prefers-color-scheme: dark`（可选深色外观，不影响规范色）

**待办振动提醒新增的无障碍实现**

- **新增控件 `aria-label`（探针 G2 实测 + 源码核对）**：`#vibSwitch`「开启或关闭待办振动提醒」（不支持振动时改为「当前浏览器不支持振动，已降级为铃声提醒」）；`#vibTestBtn`「试一次三段式振动节奏」；`#notifySwitch`「开启或关闭浏览器通知」；`#permBtn`「允许浏览器通知权限」；`#remindAckBtn`「知道了，停止振动并标记这条待办为已提醒」；`#remindSnoozeBtn`「延后十分钟后按相同规则重新提醒这条待办」；`#todoDoneBtn` 首屏就有静态 `aria-label="新建待办，进入语音录入流程"`，进入流程后由 `setFootBtn()` 按步骤改写（「完成待办内容录入 / 完成提醒时间设置 / 完成提醒方式选择」）。⚠️ **补静态 `aria-label` 是探针 G2 抓出来的真缺陷**：之前只有 `setFootBtn()` 运行后才补，首屏是无标签按钮（违反规范 §5.1）。
- **待办条目整体朗读串（实测）**：`todoAria()` = `震动提醒模式，待办内容<文本>`（实测值：`震动提醒模式，待办内容周三前把课题初稿发到群里`）。提醒方式徽标 `.todo-mode` 带 `aria-hidden="true"`，不会被重复朗读。
- **提醒弹窗焦点圈定与归还（探针 G1/G4/G5 实测）**：`#remindDlg > section` 是 `role="alertdialog"` + `aria-modal="true"` + `aria-labelledby/aria-describedby`；打开时 `trapFocus()` 圈定 Tab 焦点、60 ms 后焦点自动进入 `#remindAckBtn`（探针 G4）；关闭时用 `remind.restore.focus()` 归还给触发元素（探针 G5，**必须延后 250 ms 观测**，原因见 §2「探针复现要点」）。播报文本由 `alertSay()`（assertive）主动朗读，不依赖焦点朗读。
- **触控目标 ≥48 dp（探针 G6 实测）**：`#remindAckBtn` / `#remindSnoozeBtn` 的 `offsetHeight` = **52 px**。⚠️ 别用 `getBoundingClientRect()` 量：headless 虚拟时间下弹窗动画 `animation:pop` 冻在 `scale(0.94)`，会读出 48.88 这个假值。
- **纯听觉闭环**：录入 5 步 → 到点提醒 →「知道了 / 延后十分钟」全程可只用语音；每步都有 `setAssistantCase()` 播报 + `#srStatus`/`#srAlert` 双通道；语音指令与两个按钮共用同一对入口（`ackReminder()` / `snoozeReminder(10)`），语音指令优先于触摸、不等播报读完（弹窗 `.dlg-note` 里写明）。无障碍侧由探针 **G1–G6** 覆盖。注意「整条纯语音链路端到端走通」**没有**实测。

---

## 5. 已知取舍（等你确认是否调整）

1. 预览版把「待机监听」状态药丸放在了 Header 下方——提示词没写这个元素，是我为了表达"待机可唤醒"加的，不需要可以删。
2. 录音卡片在录音时会多出一个计时胶囊（`00:12` + 录音中/已暂停），暂停态按钮变浅灰。纯 UI 需要，无语音入口。
3. AI 整理出的是「转写完成 → 归类建议」两步确认；如果你要求只弹一次，把 `stopRecording()` 里的第二个 `openConfirm` 去掉即可。
4. 桌面浏览器打开时会渲染成 430×932 的手机框；真机/DevTools 移动模拟下自动满屏。
5. 画布中「录音主按钮」「品牌 Logo」用圆形/圆角 `box` + 主题色表示，M3E 没有圆形大按钮这个原生组件；尺寸与颜色是照规范给的（140dp 圆、`#2A4A40`），可以在编辑器里调 `corners`。

### 待办振动提醒的边界与取舍（2026-10-04）

6. **不伪造系统能力**：只发标准振动请求，**不读取也不伪造系统静音状态**——静音/勿扰下是否真振、振多强，取决于安卓系统与浏览器，不是我们声明的能力（MDN：设备在静音/勿扰模式下可能不振动）。设计自证：`window.__yuyi.muteSystemHint === false`。同理，通知权限、麦克风权限都只读真实状态（`Notification.permission` / `navigator.permissions.query`），不做假的「已开启」。

7. **振动需要「先点一下页面」**：MDN 明确 `vibrate()` 需要 sticky user activation。页面打开后从未交互过时，定时器触发的提醒**不会振动**（静默忽略）。已加 `#armCard` 提示条 + `vibrationArmed()` 探测；实际录入待办要点「确认保存」，本来就会完成激活。

8. **手机端系统通知必须走 Service Worker**：Chrome for Android 上 `new Notification()` 会抛
   `TypeError: Illegal constructor. Use ServiceWorkerRegistration.showNotification() instead.`，
   所以通知路径是「有 SW 注册 → `registration.showNotification()`；否则先试构造器（桌面/`file://`），
   只有构造器抛错且注册还在路上时才等注册完成」。回归探针 **M1–M5** 专门盯这条（含"不得退回构造器"）。
   ⚠️ 这条是实现陷阱：早期版本把"等 SW"排在构造器之前，导致 `file://` 下通知被推迟后丢失——已修。
7. **只有安卓能振**：iOS / Safari 没有网页振动 API（`navigator.vibrate` 缺失）→ 自动降级成铃声提醒 + 通知，别指望 iPhone 上振动。桌面浏览器同理。
8. **微信内置浏览器后台保活弱**：切到后台/锁屏后可能不触发提醒；建议用系统浏览器打开，或把页面「添加到桌面」。
9. **需要用户自己加白名单**：触发前 30 s 申请 `wakeLock` 能提高唤醒率，但**页面被系统彻底查杀（任务管理器清理 / 省电优化）后，没有任何网页手段能把它唤回**，到点不会振也不会响；只能下次打开页面时由 `announceOverdue()` 汇总播报过期待办。首次保存振动待办时 `firstVibGuide()` 会提示一次「添加到浏览器主页 + 允许浏览器后台运行 + 关闭省电优化」（每个浏览器只提示一次，标记存在 localStorage `yuyi.todo.backGuide`）。
10. **振动强度受手机马达影响**：节拍里的 200 / 600 ms 是**请求时长**，不是实测的物理振幅或实际振动时长；不同机型体感差别很大。
11. **提醒窗口 vs 振动时长（规范不自洽的裁定）**：规范 §3.2 的「约 18 秒」算不出实际节拍（`1250×3 + 2000×2 = 7.75 s`）。裁定为**节拍数字优先**，「18 s」只作整条提醒的**生命周期窗口**（`REMIND_WINDOW_MS = 18000`，到点释放唤醒锁）。README 与实现都**不写**「18 秒的振动」。
12. **「已过去的日期」怎么算，是我定的**：规范只给了「明天下午三点」「下周一早上八点半」这类例子，没规定已过去日期。裁定为**返回解析失败并请用户重说**（不猜、不静默改到明天）；只说了几点且今天已过才顺延到次日。
13. **时间解析是规则式、不是完整 NLU**：只覆盖规范示例的句式（中文数字 / 阿拉伯数字 / `HH:MM` 冒号写法 / 相对时间）。解析不到就返回 `null` 并请用户重说。上线接真实 ASR 前，建议把失败句式收集起来再补规则。
14. **旧免责表述已作废**：原来 `#todoPanel` 顶部那句「不调用系统闹钟 / 锁屏震动」已经不准确（安卓下确实会真振动），**已删除**，替换为 `#vibPanelCard` 的真实能力卡。锁屏/后台送达靠的是「页面在浏览器里还活着 + 常驻通知 + 振动」，**仍然不是系统闹钟**，所以「不承诺系统闹钟级可靠性」这条边界保留。

### 修复记录（开发中修掉的真 bug，2026-10-04）

| # | 现象 | 根因 | 修法 | 证据 |
|---|---|---|---|---|
| 1 | 用**同步 `close` 桩**复测通知关闭路径，700 ms 内 `vibrateCalls` 涨到 **1357** 次（正确值 3） | `closeTodoNotification()` 先 `n.close()` 再从 `notif.live` 摘出；`close` 事件回调会重入 `stopReminder()`，与 `stopReminder()` 内部的 `scheduleAll()` 相互重入 | 改成**先把实例摘出 `notif.live`、再 `close()`**，并给 `stopReminder()` 加 `remindStopping` 可重入保护 | **实测**：复测 `vibrateCalls` 稳定为 3 |
| 2 | 周日说「下周一」被算成 8 天后 | 「下周」按西历「周日是一周第一天」的口径算 | 改按中文习惯**以周一为一周起点**（`parseWhen()` 里用 `monday` 作基准） | **实测**：页面基准日 2026-10-04（周日）说「下周一」→ Oct 5 08:30 |
| 3 | 「12月25日 18:30」静默落到默认 09:00 | 时刻解析只认「X点Y分」，不认 `HH:MM` 冒号写法；`H` 为 null 就走进「只说了日期 → 09:00」分支 | 补 `HH:MM` / `HH：MM` 匹配分支 | **实测**：12月25日 18:30 → Dec 25 18:30 |
| 4 | `#todoDoneBtn` **首屏是没有 `aria-label` 的按钮**（读屏只会念「按钮」），违反规范 §5.1 | 静态 HTML 上没写 `aria-label`，只在 `setFootBtn()` 运行时才补 | HTML 上加静态 `aria-label="新建待办，进入语音录入流程"`，`setFootBtn()` 再按步骤动态改写 | **探针 G2 实测**：修前「缺失列表非空」→ FAIL；修后 PASS |

外加一条**设计改进**（Lead 归类为「改进」而非第 5 个缺陷，但它的前置现象确实是缺陷）：**「不支持振动 + 通知权限被拒」同时发生时把两条播报合并成一句 assertive 播报**（`degradedMsg` + `permMsg`）。修之前 `toast()` 内部会调 `say()` 写 `#srStatus`，约 30 ms 内就把「当前浏览器不支持震动，已切换为声音提醒」顶掉——纯听觉用户会漏听降级提示。它有独立断言（探针 **F1e**），修后 PASS。

另外三处是**同一类「顺序」约定**（源码里写了注释说明理由），属于防回归、不是复现过的 bug，如实标注：

- `ackReminder()`：**先**置 `reminded = true` 再 `stopReminder()`；`snoozeReminder()`：**先**改 `at` 再 `stopReminder()`；`stopReminder()` 内部先把 `remind.activeTodo` 摘空再关通知。理由：`stopReminder()` 里会调 `scheduleAll()`，顺序反了就会把刚处理完的待办重新排上（表现为提醒反复/不前进）。这三处我**只做了源码核对，没有单独复现旧行为**。
- 删除路径同理：先 `stopReminder("deleted")`，再置 `done/reminded`，最后从 `state.todos` 移除并重新 `scheduleAll()`。
---

## 6. 第二轮：真机反馈修复（2026-10-04，安卓实机使用后）

用户在手机上实际使用后提了 8 条问题，逐条处理如下。

| # | 反馈 | 处理 |
|---|---|---|
| 1 | 「我的」里没有 AI 总结笔记入口 | 原来「AI 总结 22 条」那一行 `data-goto="audio"` **错指向原音频面板**，已改为指向 AI 总结笔记，并把标题写成「AI 总结笔记 22 条 · 点这里打开」 |
| 2 | 喊「小语」没反应 | **此前页面里根本没有语音识别代码**，状态药丸只是装饰。第二轮接入 Web Speech API（见 §3 表最后四行）：药丸变成语音开关，命中唤醒词唤起助手，命中固定指令走 `ROUTES` |
| 3 | 「笔记」打开应该是两个选项（原音频 / AI 总结笔记），而不是直接进 AI 总结 | `#sideNote` 改为先弹「笔记 · 看哪一边？」共两个选项 + 取消 |
| 4 | AI 总结的「朗读」失效 | 原来只播报一句「正在朗读」并提示「TTS 待接入」，**没有任何声音**。现在真的念「标题 + 要点」，按钮变「停止」，读完自动复位；「我的 → 朗读语速」也真正驱动朗读语速 |
| 5 | 导出没有「中文 / 盲文」选择 | 原来只有盲文 BRF。现在先选格式：**中文 Word 文档** / **中文盲文 Word 文档** / **盲文 BRF 文件**，导出后写进导出记录 |
| 6 | 录音时喊「小语，结束」没反应 | 同 #2（无语音识别）。另把「录音结束」改成用户要的三步引导：**① 这条原音频归到哪个大类 → ② 是否生成 AI 总结笔记 → ③ 是否导出（中文 Word / 中文盲文 Word / 盲文 BRF / 先不导出）**；归类写进原音频记录、生成后自动入笔记列表 |
| 7 | 小语对固定声音的响应要优化 | 唤醒词做了谐音覆盖（小语/小雨/小宇/小羽/小玉/小v/晓雨/晓宇/小予），指令表**先长后短**（避免「重新总结」被「总结」抢走），并支持省略唤醒词直说（「结束录音」直接生效） |
| 8 | 界面要适配手机端，底栏固定在底部、中间可以滑 | **根因**：`.app-frame` 用的是 `min-height:100dvh`，内容一长整页就比视口高，`position:absolute;bottom:0` 的底栏被顶到可视区外。已改为 `height:100dvh` + `html,body{height:100%;overflow:hidden}`，只让 `.main` / `.sheet-body` / `.screen-body` 内部滚动（并补了 `min-height:0` 与 `overscroll-behavior:contain`） |

顺带修掉两个小问题：语音药丸从 **35px 加高到 44px**（原来 `verify-ui` 把它列为可点区域过小的告警项，现在 `smallTaps` 为空）；`.wake-pill` 按状态区分颜色（灰=未开启 / 绿=识别中 / 橙=浏览器不支持）。

### 6.1 本轮验收

| 项目 | 结果 |
|---|---|
| 振动验收闸门（原 74 项 + 新增场景 6 的 **O1–O10**） | **PASS 84 / FAIL 0，exit 0**（连跑两次一致） |
| 场景 6 覆盖 | 语音指令命中与拒识、药丸状态与尺寸、**外框高=视口 / 底栏贴底 / 页面不滚**、朗读按钮 + TTS 可用、笔记两选项、导出三格式、录音结束三步 |
| 既有三探针 | `verify-ui` / `verify-newflows` / `verify-newscreens` 全部 `throwAt=(none)`、`probe-ok` |

### 6.2 既有探针同步（重要）

`verify-ui.ps1` 与 `verify-newscreens.ps1` **在本轮一开始是失败的**，原因不是功能回归，而是它们写死了本轮刚被要求改掉的旧流程：

- `verify-ui.ps1`：结束录音后 **70 ms** 就去点弹窗，而新的「① 归到哪个大类」弹窗有 **320 ms** 延迟 → `#dlgActions` 为空 → 空指针，探针不再输出。已把该段等待放宽（`600 ms` / `2500 ms`）并补记 `dlg1/dlg2/dlg3`。
- `verify-newscreens.ps1`：还在点 `[data-goto="audio"]`，而那一行正是按反馈 #1 改成 `notes` 的 → 空指针。已改为 `[data-goto="notes"]` 并把读数键改成 `meToNotes`。

两个脚本都已重跑通过。**这是「测试跟着需求改」，不是放宽断言**——它们记录的是新流程的预期值。

### 6.3 本轮仍未验证的

- **手机端未复测**：改动做完时手机已从 USB 断开（`adb devices` 为空），所以上面这些结论全部来自 headless Chrome，**没有一条是真机复测**。请重新插线后双击 `手机USB直连.bat`（或用 WiFi 的 `https://<电脑IP>:8444/`）刷新页面确认。
- **语音识别是否真的能用**：headless Chrome 里 `webkitSpeechRecognition` 存在（`voiceSupported() === true`），指令解析也用「直接喂文本」验过；但**麦克风采集 + 真实识别这一环没有端到端验证过**，尤其它依赖联网（Chrome 的语音服务）。请真机点药丸开启后试说「小语」。
- 「小语，结束」这条路径是用 `handleVoiceText('小语结束')` 直接喂文本验的，语音识别本身是否准确没有验证。
