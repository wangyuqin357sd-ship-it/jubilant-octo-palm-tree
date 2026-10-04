# 语忆 · 页面内离线语音识别（WASM）

这个目录是给 `yuyi-preview/index.html` 用的**完全离线**语音识别资源。
识别在手机浏览器本机完成：不联网、不上云、不依赖电脑实时传输。

> 本目录由 `_tools/fetch-asr-wasm.py` 生成与校验，可重复运行。
> 源模型目录 `ai-voice-summary/local-asr/models/vosk-model-small-cn-0.22`
> 是**只读复用**，打包过程只读不写。

## 里面有什么

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| `vosk.js` | 5,804,767 B | `vosk-browser@0.0.8` 的 UMD 单文件包（Apache-2.0）。libvosk 的 WASM 以 base64 data-URI **内嵌**，Web Worker 也以 base64 **内嵌** —— 不需要任何额外的 `.wasm` / worker 文件。 |
| `model.tar.gz` | 43,890,403 B | 中文模型 `vosk-model-small-cn-0.22`（原始目录 68,292,271 B，gzip 后 64.3%）。 |
| `yuyi-asr.js` | 22.6 KB | 给页面用的封装：`window.YuyiASR`。 |
| `manifest.json` | 842 B | 上面几个文件的体积与 SHA-256，页面可据此提示「首次要下多少」。 |
| `README.md` | — | 本文件。 |

**手机首次打开需要下载的总字节数：49,695,170 B ≈ 47.39 MiB。**

## 为什么模型必须是 tar.gz（不是把目录直接丢进来）

这是 `vosk-browser` 的真实约定（读它的 `dist/vosk.js` 源码确认，不是猜的）：

```
worker.load(modelUrl):
  storagePath = "/vosk"
  modelPath   = "/vosk/" + modelUrl.replace(/[\W]/g, "_")
  FS.mkdir(storagePath); FS.mount(IDBFS, {}, storagePath); FS.syncfs(true)
  Vosk.downloadAndExtract(modelUrl, modelPath)
  FS.syncfs(false)                          # 落进 IndexedDB

downloadAndExtract(url, localPath):
  downloaded.tar.gz = fetch(url)
  ArchiveHelper.Extract(archive, localPath, stripFirstComponent = true)   # wasm 里的 libarchive
  touch extracted.ok
```

三个要点：

1. 模型是**一个 HTTP 文件**，由 worker `fetch()` 下来，再在 wasm 里用 libarchive 解包。
   **gzip 由 wasm 解，不依赖 HTTP 的 `Content-Encoding`** —— 静态服务器按普通二进制发即可。
2. `stripFirstComponent = true`：压缩包**必须有一个顶层目录**，解包时剥掉这一层。
   所以本包打成 `vosk-model-small-cn-0.22/am/...`，解出来正好是 `am/ conf/ graph/ ...`。
   若打成没有顶层目录的裸 tar，第一层 `am` 会被剥掉，模型直接不可用。
3. 解包成功后写 `extracted.ok` 并同步进 **IndexedDB**。同一个浏览器第二次打开会
   **跳过下载与解包**（本机实测：冷启动模型就绪 8.7 s → 缓存命中 2.9 s）。

重新打包（例如换了模型）只需要跑：

```
python yuyi-preview/_tools/fetch-asr-wasm.py --force
```

## 页面怎么调用

`yuyi-asr.js` 暴露一个全局 `YuyiASR`，接口刻意和原来的 `webkitSpeechRecognition`
**完全对等**：给 16 kHz 单声道 PCM 流 → 回文字（含中间结果）→ 能停。
页面里现成的 `handleVoiceText(text)` 一行都不用改，接到 `onResult` 上即可。

```html
<script src="data/asr/yuyi-asr.js"></script>
<script>
const asr = YuyiASR.create({
  baseUrl: 'data/asr/',
  onStatus:  s => paintWake(s),           // loading-engine|loading-model|ready|listening|stopped|error
  onPartial: t => { voice.heard = t; },   // 中间结果，随时在变
  onResult:  t => handleVoiceText(t),     // 一句话结束 —— 交给页面原有逻辑
  onError:   e => toast('离线识别不可用', e.message)
});

await asr.init();   // 首次慢（下 47 MB + 解包），之后走 IndexedDB
await asr.start();  // 开麦
// …
await asr.stop();   // 停止；返回最后一段文字（尾巴不会丢）
asr.destroy();      // 释放 worker 与声卡
</script>
```

也可以不开麦，自己喂 PCM：

```js
await asr.init();
await asr.start({ mic: false });
await asr.feed(float32_16k_mono);   // 或 Int16Array，内部会 /32768 归一化
await asr.stop();
```

把录音 Blob 转成 PCM 再识别（页面已有的 MediaRecorder 流程可以接这里）：

```js
const pcm = await YuyiASR.decodeToPcm16k(await blob.arrayBuffer());
```

`await asr.feed(chunk)` 会等 worker 处理完这一块才 resolve（天然背压，不会灌爆队列）；
实时麦克风路径内部用的是不等回执的 `asr.push(chunk)`。

### 失败要优雅降级

```js
const env = YuyiASR.available();     // {ok, why}
if (!env.ok) { /* 页面照旧用按钮 / 输入框 */ }
```

`init()` / `start()` 失败会**抛异常**，同时也会走 `onError`。别让页面卡死：
识别不可用时，按钮、输入框、助手指令 chip 都能完成同样的事。
麦克风拿不到时（http 非安全上下文）也会明确报错，不会假装在听。

## 实测性能（本机 headless Chrome 153，**机器当时负载不低**）

| 指标 | 实测（3 次完整运行的区间） |
| --- | --- |
| 首次要下载 | 49,695,170 B ≈ 47.39 MiB（引擎 5.53 MiB + 模型 41.86 MiB） |
| 页面开始加载 → 模型就绪（冷，IndexedDB 空） | 8.7 – 13.5 s（含下载 47 MB + wasm 解包 68 MB） |
| 模型已被 IndexedDB 缓存后再 init | 2.9 – 4.0 s（比冷启动快 3.4 倍） |
| 页面开始加载 → 第一句文字出来 | 13.7 – 19.0 s（冷启动那一轮） |
| 识别 15.87 s 音频 | 第 1 遍 28 – 37 s；稳态 33 s |
| 实时率 RTF | 1.69 – 3.04（同一台机器上**原生 Python vosk 自己就是 1.80 – 2.10**） |
| 队列健康度 | `dropped = 0`（这台机器喂得过来，没有丢块） |

**别把上面的 RTF 当设备结论。** 同一次运行里用 Python 的原生 vosk 跑同一份 wav，
RTF 也是 1.06 – 2.03 —— 说明这个绝对值主要反映「当时这台机器的负载」。
可以确定的只有两点：

1. **wasm 大约是原生的 1.2–2 倍开销**（同机同时间对比），不是数量级倒退；
2. **本次没有在真机手机上量过稳态 RTF。** 手机能不能实时跟上是**未验证**的。

块大小（100 ms / 200 ms / 整段）对总耗时几乎没有影响（RTF 2.26 / 2.26 / 2.29），
在途块数调大也不提速、只增加「音频→文字」的滞后 —— 瓶颈是纯算力。
所以 `YuyiASR` 默认 `maxInflight = 1`（严格喂一块等一块），
额外音频进本地队列（上限 5 s），真的跟不上才丢最老的块并记在 `asr.state().dropped`。

## 已知的坑（都已在 `yuyi-asr.js` 里处理）

| 坑 | 处理方式 |
| --- | --- |
| `Vosk.createModel()` 只在收到 `load` 时 settle，worker 报错时**永不 resolve** | 不用它；自己 `new Vosk.Model()` 并监听 `load` / `error` / 超时 |
| worker 内部错误只派发到 `Model` 上，**不会**派发到 recognizer 上 → `feed()` 会永远等一个不来的回执 | 在 Model 上接 `error`，把在途与排队的 promise 全部收掉 |
| 每个 chunk 的 `sampleRate` 必须与构造 recognizer 时一致，否则 worker **静默重建** recognizer、丢掉已识别内容 | 一律固定 16000；麦克风侧若拿不到 16 k 音频，先线性重采样再喂 |
| `acceptWaveformFloat` 内部做 `value * 0x8000` | 传进去的浮点必须归一化到 `[-1, 1]`；Int16 会先 `/32768` |
| worker 是 base64 **blob worker**，`location.href` 是 `blob:…`，相对路径会丢掉子目录 | 主线程先把 URL 解析成绝对地址再交给它 |
| 模型 URL 里的非字母数字字符会被替换成 `_` 作为 IDBFS 目录名 | 无影响，只是缓存目录名 |

> 顺便记一笔排查过程：中途我曾用「页面上收到几条 result/partialresult」来数回执，
> 结论一度是「一次灌 80 块会卡死 120 s」。后来发现 **partial 文本为空时 wrapper
> 不会回调**，于是那些块根本没被计到 —— 是量法错了，不是引擎的问题。
> 现在 wrapper 的回执记账（`onAck`）是**无条件**的，这个坑已经堵上。

## 静态服务器的白名单问题（**重要，需要 Lead 改一处**）

`_tools/serve-mobile.py` 里有一份**硬编码白名单** `ALLOW`，只放行
`/`、`/index.html`、`/sw.js`、`/lib/docx-mini.js`、`/lib/braille-zh.js`、
`/data/braille-zh.json`、`/README-预览说明.md`。
**`/data/asr/**` 不在里面 —— 手机打开会 404。** 那是 Lead 的文件，本目录不擅自改。
需要加的是（示意）：

```python
ALLOW = {
    ...
    '/data/asr/yuyi-asr.js':  os.path.join('data','asr','yuyi-asr.js'),
    '/data/asr/vosk.js':      os.path.join('data','asr','vosk.js'),
    '/data/asr/model.tar.gz': os.path.join('data','asr','model.tar.gz'),
    '/data/asr/manifest.json':os.path.join('data','asr','manifest.json'),
}
```

注意 `serve-mobile.py` 的 `_send()` 会给所有响应加 `Cache-Control: no-store`。
对 43 MB 的模型来说，这意味着**每次刷新都要重新下载** ——
不过 `vosk-browser` 自己把解包结果存进了 IndexedDB，第二次打开会跳过下载，
所以只有第一次和「清了站点数据之后」才真的要下 47 MB。

另外 `content-type` 的分支只认 `.html/.js/.json/markdown`，`.gz` 会落到
`text/markdown`。**这不影响功能**（worker 用 `fetch()` 拿 ArrayBuffer，
不看 Content-Type），但要是想干净些，加一个 `.tar.gz → application/gzip` 的分支即可。

## 验证

```
node yuyi-preview/_tools/verify-asr-wasm.mjs
```

无头 Chrome 跑两轮：一轮正常，一轮用 `--host-resolver-rules` 阻断全部外部域名，
并把结果与 Python 侧 `local_asr.py`（同一个 Vosk 引擎 + 同一个模型）交叉比对。

---

## 附：把 index.html 的「10b) 语音识别」整节换掉（给 Lead 的粘贴版）

下面这段是**最小改动**的接法：`handleVoiceText` 一个字都不用动，
`paintWake()` / `toast()` / `say()` 也照旧用。原来的
`SR` / `voiceSupported` / `voiceStart` / `voiceStop` 四块替换成：

```js
/* ---- 前提：<script src="data/asr/yuyi-asr.js"></script> 放在本节之前 ---- */
/* 在现有的 voice 对象里加一个 inst 字段：
   const voice = { rec:null, inst:null, on:false, restart:false, err:"", heard:"", autoStarted:false }; */

function voiceSupported(){ return YuyiASR.available().ok; }

function voiceStart(){
  if (!voiceSupported()){
    openConfirm({
      icon: "check", title: "这台设备跑不了离线语音识别",
      body: "浏览器没有 " + YuyiASR.available().why + "。",
      restate: { label: "可以怎么做", text: "页面上的按钮、输入框和助手指令 chip 能做同样的事。" },
      note: "语音不可用，其余功能不受影响。", confirmText: "知道了"
    });
    return false;
  }
  if (voice.on) return true;
  if (!voice.inst){
    voice.inst = YuyiASR.create({
      baseUrl: "data/asr/",
      onStatus: s => {
        if (s === "loading-engine") toast("正在加载离线识别引擎…");
        if (s === "loading-model")  toast("首次要下载中文模型（约 47 MB）", "之后会走浏览器缓存，不用再下");
        if (s === "listening"){
          voice.on = true; voice.err = ""; paintWake();
          toast("语音唤醒已开启", "离线识别，不联网"); say("语音唤醒已开启。");
        }
      },
      onPartial: t => { voice.heard = normVoice(t); paintWake(); },
      onResult:  t => { handleVoiceText(t); },     /* ← 现有函数，原样复用 */
      onError:   e => { voice.err = e.message; voice.on = false; paintWake();
                        toast("离线识别不可用", e.message); }
    });
  }
  voice.restart = true;
  /* start() 内部会先 init()（加载引擎 + 模型）再开麦；失败会抛，也会走 onError */
  voice.inst.start().catch(e => {
    voice.err = String((e && e.message) || e); voice.on = false; paintWake();
    toast("离线语音没能启动", voice.err);
  });
  return true;
}

function voiceStop(){
  voice.restart = false; voice.on = false; voice.autoArmed = true;
  if (voice.inst) voice.inst.stop().catch(() => {});
  paintWake(); toast("语音唤醒已关闭。"); say("语音唤醒已关闭。");
}
```

`paintWake()` 里判断不支持的那两处文案可以直接沿用 —— 现在「不支持」的含义
从「没有 webkitSpeechRecognition」变成「没有 WebAssembly / Worker / IndexedDB」。

**降级路径**：`YuyiASR.available()` 为 false、或 `init()` 抛异常时，
页面行为要和以前「不支持语音」时完全一样 —— 按钮、输入框、指令 chip 照常可用，
不弹红、不卡死。这一点建议 Lead 实测一遍（把 `baseUrl` 故意改成不存在的路径就能模拟）。

**想复用已有的录音 Blob**（MediaRecorder 录下来的 webm/m4a）直接把 PCM 喂进去：

```js
const pcm = await YuyiASR.decodeToPcm16k(await blob.arrayBuffer());
await voice.inst.start({ mic: false });     // 不开麦，只识别
for (let i = 0; i < pcm.length; i += 3200) await voice.inst.feed(pcm.subarray(i, i + 3200));
const tail = await voice.inst.stop();
```