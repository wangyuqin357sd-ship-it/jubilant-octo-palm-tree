/* ============================================================================
   语忆 · 页面内离线语音识别（WASM，不联网 / 不上云）
   ============================================================================
   全局导出：window.YuyiASR

   它解决什么问题
   --------------
   index.html 原来用浏览器自带的 webkitSpeechRecognition —— Chrome 会把麦克风
   音频**送到云端**换文字，必须联网。本文件把识别换成**页面内 WASM 推理**：
   引擎（vosk.js，内嵌 libvosk 的 wasm）与中文模型（model.tar.gz）都从
   **本机静态服务器**的 data/asr/ 加载，识别全程在手机本机完成。

   对页面而言，接口和以前**完全对等**：给它 16 kHz 单声道 PCM 流，它回文字
   （含中间结果），最后能停。页面里现成的 handleVoiceText(text) 不用改，
   把它接到 onResult / onPartial 上即可。

   最小可用示例
   ------------
     const asr = YuyiASR.create({
       baseUrl: 'data/asr/',                 // 引擎与模型所在目录（会自动解析成绝对 URL）
       onStatus: s => paintWake(s),          // 'loading-engine' | 'loading-model' | 'ready' | 'listening' | 'stopped' | 'error'
       onPartial: t => { voice.heard = t; }, // 中间结果（随时在变）
       onResult:  t => handleVoiceText(t),   // 一句话说完 —— 交给页面原有的处理函数
       onError:   e => console.warn(e.message)
     });

     await asr.init();      // 加载引擎 + 模型（第一次慢：要下约 55 MB 并解包；之后走 IndexedDB 缓存）
     await asr.start();     // 开麦，开始识别
     ...
     await asr.stop();      // 停止，返回最后一段文字
     asr.destroy();         // 释放 worker 与声卡

   不想开麦、只想喂自己拿到的 PCM：
     await asr.init();
     await asr.start({ mic: false });
     await asr.feed(float32_16k_mono);       // 或 Int16Array，内部会换算
     await asr.stop();

   加载失败要优雅降级：init()/start() 会抛异常，同时也会走 onError；
   用 YuyiASR.available() 先判断环境，失败时页面照旧用按钮/输入框即可 —— 不要卡死。

   ---------------------------------------------------------------------------
   关于底下那层 vosk-browser（读它的源码确认过，不是猜的）
     · vosk.js 是 UMD 单文件：libvosk 的 WASM 以 base64 data-URI 内嵌，
       Web Worker 也以 base64 内嵌 —— 不需要任何额外的 .wasm / worker 文件。
     · 模型必须是 **tar.gz**，且**含一个顶层目录**；worker 用
       ArchiveHelper.Extract(..., stripFirstComponent=true) 剥掉那一层。
     · worker 内部把模型解到 IDBFS（/vosk/<name>），成功后写 extracted.ok 并
       syncfs 到 IndexedDB —— 同一个浏览器第二次打开就跳过下载与解包。
     · acceptWaveformFloat(buf, rate) 内部做 value * 0x8000，所以传进去的
       浮点必须归一化到 [-1, 1]（Int16 要 /32768）。
     · 每个 chunk 的 sampleRate 必须与构造 recognizer 时一致，否则 worker 会
       **静默重建 recognizer**、丢掉已识别内容 —— 所以这里一律固定 16000。
     · Vosk.createModel() 只在收到 'load' 时 settle，worker 报错时它**永不 resolve**。
       所以这里不用 createModel，自己 new Vosk.Model() 并监听 load / error / 超时。
   ============================================================================ */

(function (global) {
  'use strict';

  var SAMPLE_RATE = 16000;          // Kaldi 与中文模型都按 16 kHz 训练/配置
  var MIC_CHUNK = 4096;             // 约 256 ms @16k

  var DEFAULTS = {
    baseUrl: 'data/asr/',
    engineFile: 'vosk.js',
    modelFile: 'model.tar.gz',
    manifestFile: 'manifest.json',
    sampleRate: SAMPLE_RATE,
    logLevel: -1,                   // -1 只报 warning，别把控制台刷满
    loadTimeoutMs: 300000,          // 首次：下载约 47 MB + wasm 解包，给 5 分钟
    feedTimeoutMs: 60000,           // 单块 PCM 等的上限，防 worker 无响应时挂死
    drainTimeoutMs: 120000,         // stop() 里等队列排空的上限
    maxInflight: 1,                 // 在途块数。实测调大不提速、只增延迟，唤醒词场景保持 1
    maxQueuedSeconds: 5             // 本地待喂缓冲的上限（秒），超了丢最老的块
  };

  /* ------------------------------------------------------------------ 环境 */
  function available() {
    var ok = true, why = [];
    if (typeof WebAssembly !== 'object') { ok = false; why.push('没有 WebAssembly'); }
    if (typeof Worker !== 'function') { ok = false; why.push('没有 Web Worker'); }
    if (typeof indexedDB !== 'object') { ok = false; why.push('没有 IndexedDB（模型缓存要用）'); }
    return { ok: ok, why: why.join('、') };
  }

  function absUrl(base, file) {
    return new URL(file, new URL(base, global.location.href)).href;
  }

  /* --------------------------------------------------- 引擎脚本只加载一次 */
  var enginePromise = null;
  function loadEngineScript(url) {
    if (global.Vosk && typeof global.Vosk.Model === 'function') return Promise.resolve();
    if (enginePromise) return enginePromise;
    enginePromise = new Promise(function (resolve, reject) {
      var el = global.document.createElement('script');
      el.src = url;
      el.async = true;
      el.onload = function () {
        if (global.Vosk && typeof global.Vosk.Model === 'function') resolve();
        else { enginePromise = null; reject(new Error('vosk.js 加载了，但没有导出 Vosk.Model')); }
      };
      el.onerror = function () {
        enginePromise = null;
        reject(new Error('加载识别引擎失败：' + url +
          '（确认静态服务器把 data/asr/ 放行了；serve-mobile.py 有一份硬编码白名单）'));
      };
      global.document.head.appendChild(el);
    });
    return enginePromise;
  }

  /* --------------------------------------------------- 音频解码 / 重采样 */
  function toFloat32(pcm) {
    if (pcm instanceof Float32Array) return pcm;
    if (pcm instanceof Int16Array) {
      var out = new Float32Array(pcm.length);
      for (var i = 0; i < pcm.length; i++) out[i] = pcm[i] / 32768;
      return out;
    }
    if (pcm instanceof ArrayBuffer) return toFloat32(new Int16Array(pcm));
    if (pcm && pcm.buffer instanceof ArrayBuffer) return toFloat32(new Int16Array(pcm.buffer));
    throw new Error('不认识这种 PCM：要 Float32Array 或 Int16Array');
  }

  /** 线性插值重采样。够用且无依赖；麦克风路径上优先让 AudioContext 直接给 16k。 */
  function resample(input, fromRate, toRate) {
    if (fromRate === toRate) return input;
    var ratio = fromRate / toRate;
    var length = Math.round(input.length / ratio);
    var out = new Float32Array(length);
    for (var i = 0; i < length; i++) {
      var pos = i * ratio;
      var i0 = Math.floor(pos);
      var i1 = Math.min(i0 + 1, input.length - 1);
      var frac = pos - i0;
      out[i] = input[i0] * (1 - frac) + input[i1] * frac;
    }
    return out;
  }

  /** 把任意浏览器能解码的音频（wav / webm / mp3 / m4a…）转成 16k 单声道 Float32。 */
  function decodeToPcm16k(arrayBuffer) {
    var Ctx = global.AudioContext || global.webkitAudioContext;
    if (!Ctx) return Promise.reject(new Error('没有 AudioContext，无法解码音频'));
    var tmp = new Ctx();
    return new Promise(function (resolve, reject) {
      // 老 Safari 只有回调版；Chrome / 现代浏览器是 Promise 版
      var p;
      try { p = tmp.decodeAudioData(arrayBuffer, resolve, reject); }
      catch (e) { reject(e); return; }
      if (p && typeof p.then === 'function') p.then(resolve, reject);
    }).then(function (buffer) {
      var raw = buffer.getChannelData(0);
      var mono;
      if (buffer.numberOfChannels > 1) {           // 多声道下混成单声道
        mono = new Float32Array(raw.length);
        for (var c = 0; c < buffer.numberOfChannels; c++) {
          var ch = buffer.getChannelData(c);
          for (var i = 0; i < ch.length; i++) mono[i] += ch[i] / buffer.numberOfChannels;
        }
      } else {
        mono = raw;
      }
      var out = resample(mono, buffer.sampleRate, SAMPLE_RATE);
      var copy = new Float32Array(out.length);
      copy.set(out);
      try { tmp.close(); } catch (e) {}
      return copy;
    });
  }

  /* ------------------------------------------------------- AudioWorklet 源 */
  var WORKLET_SRC = [
    'class YuyiAsrCapture extends AudioWorkletProcessor {',
    '  constructor(){ super(); this.size = ' + MIC_CHUNK + '; this.buf = new Float32Array(this.size); this.n = 0; }',
    '  process(inputs){',
    '    const input = inputs[0];',
    '    if (!input || !input.length) return true;',
    '    const ch = input[0];',
    '    if (!ch) return true;',
    '    for (let i = 0; i < ch.length; i++){',
    '      this.buf[this.n++] = ch[i];',
    '      if (this.n === this.size){',
    '        const copy = new Float32Array(this.buf);',   // 必须拷贝：transfer 会掏空原数组
    '        this.port.postMessage(copy, [copy.buffer]);',
    '        this.n = 0;',
    '      }',
    '    }',
    '    return true;',
    '  }',
    '}',
    'registerProcessor("yuyi-asr-capture", YuyiAsrCapture);'
  ].join('\n');

  /* =========================================================== 实例 ======= */
  function create(options) {
    var cfg = {};
    for (var k in DEFAULTS) cfg[k] = DEFAULTS[k];
    for (var k2 in (options || {})) cfg[k2] = options[k2];

    var handlers = {
      onStatus: cfg.onStatus || function () {},
      onPartial: cfg.onPartial || function () {},
      onResult: cfg.onResult || function () {},
      onError: cfg.onError || function () {},
      onLevel: cfg.onLevel || null
    };

    var state = {
      status: 'idle',        // idle | loading-engine | loading-model | ready | listening | stopped | error
      model: null,
      recognizer: null,
      mic: null,
      audioCtx: null,
      source: null,
      node: null,
      sink: null,
      stream: null,
      queue: [],             // 还没喂进 worker 的 PCM（本地缓冲，有上限）
      current: null,         // 正在 worker 里算的那一块（在途）
      queuedSamples: 0,
      inflight: 0,
      dropped: 0,
      lastError: null,
      destroyed: false
    };

    var engineUrl = absUrl(cfg.baseUrl, cfg.engineFile);
    var modelUrl = absUrl(cfg.baseUrl, cfg.modelFile);

    function setStatus(s) {
      state.status = s;
      try { handlers.onStatus(s); } catch (e) {}
    }
    function fail(err) {
      var e = (err instanceof Error) ? err : new Error(String(err));
      state.lastError = e;
      setStatus('error');
      try { handlers.onError(e); } catch (x) {}
      return e;
    }

    /* ---------------------------------------------- 有界队列 + 回执驱动
       为什么仍然要做背压（实测结论，别删）：
       vosk-browser 把每一块 PCM postMessage 给 worker，worker 一块一块算、
       每块回一条 result/partialresult。规则很简单，但有两个坑：
         · 如果不等回执、无限往队列里灌，内存和「音频→文字」的滞后都会无界增长，
           等到跟不上时就是整段垮掉，而不是优雅退化；
         · 实测（headless Chrome，15.87 s 音频）：块大小 100 ms / 200 ms / 整段
           对总耗时几乎没有影响（RTF 2.26 / 2.26 / 2.29）—— 瓶颈是纯算力，
           不是每块的开销。所以在途块数**调大并不能提速**，只会增加延迟。
       因此默认 maxInflight = 1（严格「喂一块等一块」），
       额外音频先进本地队列；本地队列也满了才丢最老的块，并记在 state().dropped。
       要低延迟的唤醒词场景就用默认值：滞后最小。 */
    function pump() {
      while (state.recognizer && state.inflight < cfg.maxInflight && state.queue.length) {
        var item = state.queue.shift();
        state.queuedSamples -= item.pcm.length;
        state.inflight++;
        state.current = item;
        try {
          // 传进去的是 Float32Array；vosk 内部 .map() 会新建一份再 transfer，
          // 所以调用方自己那个数组不会被掏空，可放心复用。
          state.recognizer.acceptWaveformFloat(toFloat32(item.pcm), cfg.sampleRate);
        } catch (e) {
          state.inflight--; state.current = null;
          clearTimeout(item.timer);
          if (item.reject) item.reject(fail(e));
        }
      }
    }

    /** worker 回了一条 result / partialresult：这一块算完了。 */
    function onAck() {
      if (state.inflight > 0) state.inflight--;
      var item = state.current;
      state.current = null;
      if (item) {
        clearTimeout(item.timer);
        if (item.reject) item.reject = null;
        if (item.resolve) item.resolve();
        item.resolve = null;
      }
      pump();
    }

    /** 出错时把在途和排队的都收掉，别让调用方挂着。 */
    function drain(err) {
      var items = state.queue.slice();
      state.queue.length = 0;
      state.queuedSamples = 0;
      if (state.current) { items.push(state.current); state.current = null; }
      state.inflight = 0;
      items.forEach(function (item) {
        clearTimeout(item.timer);
        if (item.reject) item.reject(err); else if (item.resolve) item.resolve();
      });
    }

    /** 入队。resolve 可有可无：push() 不带，feed() 带。 */
    function enqueue(pcm, resolve, reject) {
      var floats = toFloat32(pcm);
      if (!floats.length) { if (resolve) resolve(); return true; }
      // 本地队列上限：按秒数折算，超了就丢**最老的**（丢新块会让语音断在中间更难听）
      var maxSamples = cfg.maxQueuedSeconds * cfg.sampleRate;
      while (state.queuedSamples + floats.length > maxSamples && state.queue.length) {
        var old = state.queue.shift();
        state.queuedSamples -= old.pcm.length;
        state.dropped++;
        clearTimeout(old.timer);
        if (old.resolve) old.resolve();          // 让 await 方不至于挂死
      }
      var item = { pcm: floats, resolve: resolve || null, reject: reject || null, timer: null };
      if (reject) {
        item.timer = setTimeout(function () {
          var i = state.queue.indexOf(item);
          if (i >= 0) state.queue.splice(i, 1), state.queuedSamples -= item.pcm.length;
          if (state.current === item) state.current = null, state.inflight = Math.max(0, state.inflight - 1);
          reject(fail(new Error('识别超时：这一段没有回执（' +
            (state.lastError ? state.lastError.message : 'worker 无响应') + '）')));
        }, cfg.feedTimeoutMs);
      }
      state.queue.push(item);
      state.queuedSamples += item.pcm.length;
      pump();
      return true;
    }

    /* ------------------------------------------------------------ 读体积 */
    /** 首次要下载多少字节 —— 页面可以据此给用户一句提示。 */
    function describeAssets() {
      return fetch(absUrl(cfg.baseUrl, cfg.manifestFile), { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (m) {
          if (!m) return null;
          return {
            totalBytes: m.total_bytes,
            engineBytes: m.engine && m.engine.bytes,
            modelBytes: m.model && m.model.bytes,
            engineVersion: m.engine && m.engine.version,
            modelName: m.model && m.model.name
          };
        })
        .catch(function () { return null; });
    }

    /* ------------------------------------------------------- 加载模型 */
    function loadModel() {
      return new Promise(function (resolve, reject) {
        var settled = false;
        var timer = setTimeout(function () {
          if (settled) return;
          settled = true;
          reject(fail(new Error('模型加载超时（' + Math.round(cfg.loadTimeoutMs / 1000) +
            ' 秒）。第一次打开要下载并解包约 47 MB，慢的话再等等，或检查手机与电脑是否在同一 WiFi。')));
        }, cfg.loadTimeoutMs);

        function done(err, model) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          if (err) reject(fail(err)); else resolve(model);
        }

        var model;
        try {
          model = new global.Vosk.Model(modelUrl, cfg.logLevel);
        } catch (e) { done(e); return; }

        model.addEventListener('load', function (ev) {
          var detail = ev && ev.detail;
          if (detail && detail.result) done(null, model);
          else done(new Error('worker 报告模型加载失败（模型包结构不对？必须是含单个顶层目录的 tar.gz）'));
        });
        model.addEventListener('error', function (ev) {
          var detail = ev && ev.detail;
          done(new Error('模型加载出错：' + ((detail && detail.error) || '未知')));
        });
      });
    }

    /* ---------------------------------------------------------- init */
    function init() {
      if (state.destroyed) return Promise.reject(fail(new Error('这个实例已经 destroy 了')));
      if (state.model) return Promise.resolve(state);

      var env = available();
      if (!env.ok) {
        return Promise.reject(fail(new Error('这个浏览器跑不了页面内离线识别：' + env.why +
          '。可以先用页面上的按钮和输入框完成同样的事。')));
      }

      setStatus('loading-engine');
      return loadEngineScript(engineUrl)
        .then(function () {
          setStatus('loading-model');
          return loadModel();
        })
        .then(function (model) {
          state.model = model;
          // worker 里的错误（例如 malloc 失败、模型目录不对）只会派发到 Model 上，
          // 不会派发到 recognizer 上。不接住的话 feed() 会一直等一个永远不来的回执。
          model.addEventListener('error', function (ev) {
            var detail = ev && ev.detail;
            var message = 'worker 出错：' + ((detail && detail.error) || '未知');
            if (state.recognizer) drain(fail(new Error(message)));
            else fail(new Error(message));
          });
          setStatus('ready');
          return state;
        })
        .catch(function (e) { throw fail(e); });
    }

    /* ------------------------------------------------- 一段 PCM 喂进去 */
    /**
     * feed(pcm) —— 喂一段 16 kHz 单声道 PCM，返回一个 promise：
     * 等 worker 对这一段的处理结束（吐出了 result 或 partialresult）才 resolve。
     * 这样调用方可以放心地「喂一段、等一段」，不会把 worker 的队列灌爆。
     */
    function feed(pcm) {
      if (!state.recognizer) return Promise.reject(fail(new Error('还没 start()，没有识别器')));
      var floats = toFloat32(pcm);
      if (!floats.length) return Promise.resolve();
      return new Promise(function (resolve, reject) { enqueue(floats, resolve, reject); });
    }

    /**
     * push(pcm) —— 实时麦克风路径：入队后立刻返回，不产生 promise。
     * 仍然受「在途 ≤ maxInflight + 本地队列 ≤ maxQueuedSeconds」约束，
     * 真的跟不上时会丢最老的块并记在 state().dropped 上（不会静默堆爆内存）。
     */
    function push(pcm) {
      if (!state.recognizer) return false;
      try { return enqueue(pcm, null, null); }
      catch (e) { fail(e); return false; }
    }

    /* ------------------------------------------------------- start */
    function start(opts) {
      opts = opts || {};
      var wantMic = opts.mic !== false;

      return init().then(function () {
        if (state.recognizer) return null;              // 已经在跑
        if (!state.model || !state.model.ready) {
          throw fail(new Error('模型已经不可用（可能被 terminate 了）'));
        }
        state.recognizer = new state.model.KaldiRecognizer(cfg.sampleRate);
        state.recognizer.setWords(false);
        state.recognizer.on('result', function (msg) {
          var text = (msg && msg.result && msg.result.text) || '';
          onAck();
          if (text) { try { handlers.onResult(text); } catch (e) {} }
        });
        state.recognizer.on('partialresult', function (msg) {
          var partial = (msg && msg.result && msg.result.partial) || '';
          onAck();
          if (partial) { try { handlers.onPartial(partial); } catch (e) {} }
        });
        if (!wantMic) { setStatus('listening'); return null; }
        return startMic(opts.stream);
      });
    }

    /* ------------------------------------------------------ 麦克风 */
    function startMic(existingStream) {
      if (!global.navigator || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw fail(new Error('拿不到麦克风接口。手机必须走 https（或 127.0.0.1）才有安全上下文。'));
      }
      var Ctx = global.AudioContext || global.webkitAudioContext;
      if (!Ctx) throw fail(new Error('没有 AudioContext，收不了麦克风'));

      return (existingStream ? Promise.resolve(existingStream)
        : navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            video: false
          }))
        .catch(function (e) {
          throw fail(new Error('麦克风没拿到：' + ((e && e.name) || e) +
            '。请在地址栏图标里允许麦克风后重试；也可以先用按钮操作。'));
        })
        .then(function (stream) {
          state.stream = stream;
          // 直接向浏览器要 16 kHz —— Chrome for Android 一般会给。
          // 万一没给成，下面按真实 rate 做一次线性重采样，绝不把错的 rate 喂给 worker
          // （rate 对不上 worker 会静默重建 recognizer，前面识别的东西全丢）。
          var ctx;
          try { ctx = new Ctx({ sampleRate: cfg.sampleRate }); }
          catch (e) { ctx = new Ctx(); }
          state.audioCtx = ctx;
          var src = ctx.createMediaStreamSource(stream);
          state.source = src;
          var effectiveRate = ctx.sampleRate;

          function emit(floats) {
            var pcm = effectiveRate === cfg.sampleRate
              ? floats : resample(floats, effectiveRate, cfg.sampleRate);
            push(pcm);
          }

          var workletReady = (typeof ctx.audioWorklet !== 'undefined' &&
                              typeof global.AudioWorkletNode === 'function' &&
                              typeof URL !== 'undefined' && typeof Blob !== 'undefined');

          if (workletReady) {
            var blob = new Blob([WORKLET_SRC], { type: 'application/javascript' });
            var url = URL.createObjectURL(blob);
            return ctx.audioWorklet.addModule(url)
              .then(function () {
                URL.revokeObjectURL(url);
                var node = new global.AudioWorkletNode(ctx, 'yuyi-asr-capture');
                node.port.onmessage = function (ev) { emit(ev.data); };
                src.connect(node);
                state.node = node;
                setStatus('listening');
              })
              .catch(function () {                       // 退回 ScriptProcessor
                try { URL.revokeObjectURL(url); } catch (e) {}
                return startScriptProcessor(ctx, src, emit);
              });
          }
          return startScriptProcessor(ctx, src, emit);
        });
    }

    function startScriptProcessor(ctx, src, emit) {
      var node = ctx.createScriptProcessor(MIC_CHUNK, 1, 1);
      node.onaudioprocess = function (ev) {
        var ch = ev.inputBuffer.getChannelData(0);
        var copy = new Float32Array(ch.length);
        copy.set(ch);
        emit(copy);
      };
      // ScriptProcessor 必须连到 destination 才会持续触发；串一个 0 增益节点，别把麦克风回放出来。
      var sink = ctx.createGain();
      sink.gain.value = 0;
      src.connect(node);
      node.connect(sink);
      sink.connect(ctx.destination);
      state.node = node;
      state.sink = sink;
      setStatus('listening');
      return null;
    }

    function stopMic() {
      try { if (state.node) { state.node.port && (state.node.port.onmessage = null); state.node.onaudioprocess = null; state.node.disconnect(); } } catch (e) {}
      try { if (state.source) state.source.disconnect(); } catch (e) {}
      try { if (state.sink) state.sink.disconnect(); } catch (e) {}
      try { if (state.stream) state.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
      try { if (state.audioCtx && state.audioCtx.state !== 'closed') state.audioCtx.close(); } catch (e) {}
      state.node = null; state.source = null; state.sink = null;
      state.stream = null; state.audioCtx = null;
    }

    /* -------------------------------------------------------- stop */
    /** 停止并取回最后一段文字（排队里还没算的尾巴不会丢）。 */
    function stop() {
      stopMic();
      if (!state.recognizer) { setStatus('stopped'); return Promise.resolve(''); }
      var rec = state.recognizer;
      // 先把本地队列排空、等最后一块算完，再取 FinalResult；
      // 否则还在队列里的那几块音频会被丢掉，尾巴就少了字。
      var drained = new Promise(function (resolve) {
        var timer = setTimeout(resolve, cfg.drainTimeoutMs);
        (function check() {
          if (state.queue.length === 0 && state.inflight === 0) { clearTimeout(timer); resolve(); return; }
          setTimeout(check, 30);
        })();
      });
      return drained.then(function () {
        if (state.recognizer !== rec) { setStatus('stopped'); return ''; }
        state.recognizer = null;
        return new Promise(function (resolve) {
          var settled = false;
          var timer = setTimeout(function () { if (!settled) { settled = true; resolve(''); } }, 15000);
          rec.on('result', function (msg) {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            resolve((msg && msg.result && msg.result.text) || '');
          });
          try { rec.retrieveFinalResult(); }
          catch (e) { clearTimeout(timer); settled = true; resolve(''); }
        }).then(function (tail) {
          try { rec.remove(); } catch (e) {}
          setStatus('stopped');
          if (tail) { try { handlers.onResult(tail); } catch (e) {} }
          return tail;
        });
      });
    }

    /* ----------------------------------------------------- destroy */
    function destroy() {
      if (state.destroyed) return;
      state.destroyed = true;
      stopMic();
      drain(new Error('实例已销毁'));
      try { if (state.recognizer) state.recognizer.remove(); } catch (e) {}
      state.recognizer = null;
      try { if (state.model) state.model.terminate(); } catch (e) {}
      state.model = null;
      setStatus('stopped');
    }

    return {
      init: init,
      start: start,
      feed: feed,
      push: push,
      stop: stop,
      destroy: destroy,
      describeAssets: describeAssets,
      state: function () {
        return {
          status: state.status,
          ready: !!(state.model && state.model.ready),
          listening: !!state.recognizer,
          queuedChunks: state.queue.length,
          queuedSeconds: +(state.queuedSamples / cfg.sampleRate).toFixed(3),
          inflight: state.inflight,
          dropped: state.dropped,          // 跟不上时丢掉的块数（>0 说明这台设备算不过来）
          error: state.lastError ? state.lastError.message : ''
        };
      }
    };
  }

  global.YuyiASR = {
    create: create,
    available: available,
    decodeToPcm16k: decodeToPcm16k,
    resample: resample,
    SAMPLE_RATE: SAMPLE_RATE,
    version: '1.0.0',
    engine: 'vosk-browser (libvosk WASM, Kaldi)'
  };
})(typeof window !== 'undefined' ? window : this);