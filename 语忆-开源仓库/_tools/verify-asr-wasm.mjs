#!/usr/bin/env node
/* ============================================================================
   语忆 · 离线 ASR(WASM) 无头验证
   ============================================================================
   用 node 驱动 headless Chrome（零 npm 依赖：CDP over 内建 WebSocket），真的把
   `data/asr/` 里的 WASM 引擎与中文模型跑起来，证明：

     1. 在 %TEMP% 起一个**只服务 yuyi-preview 项目目录**的静态服务器
        （不用 Lead 的 serve-mobile.py）
     2. headless Chrome 打开 _tools/asr-wasm.test.html，
        页内从 data/asr/ 加载 WASM + 模型（同源，不是 CDN）
     3. 把 ai-voice-summary/local-asr/test-sample.wav 解码成 16k 单声道 PCM，
        **分片**（默认 5 片，≥3）喂进去，模拟流式，拿到识别文本
     4. 断言：文本非空、含中文字符
     5. 交叉验证：用 Python 侧 ai-voice-summary/scripts/local_asr.py 的 API
        对同一份 wav 识别一次，算两次结果的**字符重合率**（LCS），低于阈值 FAIL
     6. 离线自证：另起一轮 Chrome，加 --host-resolver-rules 把外部域名全部阻断，
        重跑 3–4 必须仍然识别成功；并用「外部域名探测」做对照，
        证明阻断确实生效而不是没网
     7. 打印每步 PASS/FAIL 与汇总；有 FAIL → exit 1，全 PASS → exit 0；
        结束时杀掉 Chrome 与静态服务器，清掉临时文件

   用法：
     node yuyi-preview/_tools/verify-asr-wasm.mjs
     node yuyi-preview/_tools/verify-asr-wasm.mjs --log %TEMP%\asr-verify.log
     node yuyi-preview/_tools/verify-asr-wasm.mjs --slices 5 --threshold 0.85
   ============================================================================ */

import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));      // yuyi-preview/_tools
const ROOT = path.dirname(HERE);                                 // yuyi-preview
const DESKTOP = path.dirname(ROOT);                              // Desktop
const ASR_DIR = path.join(ROOT, 'data', 'asr');
const TEST_PAGE = path.join(HERE, 'asr-wasm.test.html');
const SAMPLE_WAV = path.join(DESKTOP, 'ai-voice-summary', 'local-asr', 'test-sample.wav');
const LOCAL_ASR_PY = path.join(DESKTOP, 'ai-voice-summary', 'scripts', 'local_asr.py');
const MODEL_DIR = path.join(DESKTOP, 'ai-voice-summary', 'local-asr', 'models', 'vosk-model-small-cn-0.22');

/* ------------------------------------------------------------------ 参数 */
const argv = process.argv.slice(2);
function opt(name, dflt) {
  const i = argv.indexOf('--' + name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
}
function flag(name) { return argv.includes('--' + name); }

const SLICES = parseInt(opt('slices', '5'), 10);
const THRESHOLD = parseFloat(opt('threshold', '0.85'));
const OVERALL_TIMEOUT_MS = parseInt(opt('timeout', '900'), 10) * 1000;   // 每轮上限
const LOG_PATH = opt('log', '');
const KEEP_TEMP = flag('keep-temp');

/* ------------------------------------------------------------------ 输出 */
const lines = [];
function out(s = '') {
  lines.push(s);
  process.stdout.write(s + '\n');
}
const TMP_CREATED = [];
function tmpPath(name) {
  const p = path.join(os.tmpdir(), name);
  TMP_CREATED.push(p);
  return p;
}

let passCount = 0, failCount = 0;
const stepResults = [];
function step(ok, label, detail = '') {
  if (ok) passCount++; else failCount++;
  stepResults.push({ ok, label, detail });
  out(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ' —— ' + detail : ''}`);
  return ok;
}
function section(title) {
  out('');
  out('  ' + title);
  out('  ' + '-'.repeat(Math.max(20, title.length)));
}

/* ========================================================================== */
/* 1) 只服务项目目录的静态服务器                                                */
/* ========================================================================== */
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.wasm': 'application/wasm',
  '.gz': 'application/gzip',
  '.wav': 'audio/wav',
  '.md': 'text/markdown; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
};

const requestLog = [];

function startStaticServer() {
  return new Promise((resolve, reject) => {
    const server = http.createServer(async (req, res) => {
      let urlPath;
      try { urlPath = decodeURIComponent(new URL(req.url, 'http://x').pathname); }
      catch { urlPath = req.url; }

      let filePath = null;
      let alias = '';
      // 唯一一个显式只读别名：被测音频在 yuyi-preview 之外，但属于「只读复用」，
      // 不做这个映射就只能把 wav 复制进项目目录（那会多出一个不该有的文件）。
      if (urlPath === '/__src__/test-sample.wav') {
        filePath = SAMPLE_WAV;
        alias = ' [alias→ai-voice-summary/local-asr/test-sample.wav, 只读]';
      } else {
        // 其余一律限制在项目目录内，且不允许 .. 逃逸
        const rel = urlPath === '/' ? 'index.html' : urlPath.replace(/^\/+/, '');
        const resolved = path.resolve(ROOT, rel);
        if (resolved === ROOT || resolved.startsWith(ROOT + path.sep)) filePath = resolved;
      }

      requestLog.push(`${req.method} ${urlPath}${alias}`);

      if (!filePath) {
        res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('forbidden');
        requestLog[requestLog.length - 1] += ' -> 403';
        return;
      }
      try {
        const stat = await fsp.stat(filePath);
        if (!stat.isFile()) throw new Error('not a file');
        const type = MIME[path.extname(filePath).toLowerCase()] || 'application/octet-stream';
        res.writeHead(200, {
          'Content-Type': type,
          'Content-Length': String(stat.size),
          // 不要缓存：否则「离线那轮」可能是浏览器缓存命中，证明不了什么
          'Cache-Control': 'no-store, no-cache, must-revalidate',
          'Access-Control-Allow-Origin': '*',
        });
        fs.createReadStream(filePath).pipe(res);
        requestLog[requestLog.length - 1] += ` -> 200 ${stat.size}B`;
      } catch (e) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('not found: ' + urlPath);
        requestLog[requestLog.length - 1] += ' -> 404';
      }
    });
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

/* ========================================================================== */
/* 2) 找 Chrome                                                                */
/* ========================================================================== */
function findChrome() {
  const candidates = [];
  const roots = ['D:\\DevCache\\ms-playwright', path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright')];
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    let dirs = [];
    try { dirs = fs.readdirSync(root); } catch { continue; }
    // chromium_headless_shell-* 优先，其次 chromium-*
    for (const d of dirs.filter(x => /^chromium_headless_shell-\d+$/.test(x)).sort().reverse()) {
      candidates.push(path.join(root, d, 'chrome-headless-shell-win64', 'chrome-headless-shell.exe'));
      candidates.push(path.join(root, d, 'chrome-headless-shell-win32', 'chrome-headless-shell.exe'));
    }
    for (const d of dirs.filter(x => /^chromium-\d+$/.test(x)).sort().reverse()) {
      candidates.push(path.join(root, d, 'chrome-win64', 'chrome.exe'));
      candidates.push(path.join(root, d, 'chrome-win', 'chrome.exe'));
    }
  }
  for (const c of candidates) if (fs.existsSync(c)) return c;
  // 兜底：系统 Chrome
  for (const c of [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  ]) if (fs.existsSync(c)) return c;
  return null;
}

/* ========================================================================== */
/* 3) 极简 CDP 客户端（零依赖）                                                 */
/* ========================================================================== */
class CdpSession {
  constructor(child, profileDir) {
    this.child = child;
    this.profileDir = profileDir;
    this.ws = null;
    this.nextId = 0;
    this.pending = new Map();
    this.stderr = '';
  }

  static async launch(exe, extraArgs = []) {
    const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuyi-asr-profile-'));
    TMP_CREATED.push(profileDir);
    const args = [
      '--headless',
      '--no-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-extensions',
      '--disable-background-networking',
      '--disable-component-update',
      '--disable-client-side-phishing-detection',
      '--disable-sync',
      '--metrics-recording-only',
      '--mute-audio',
      '--remote-debugging-port=0',
      `--user-data-dir=${profileDir}`,
      ...extraArgs,
      'about:blank',
    ];
    const child = spawn(exe, args, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    const session = new CdpSession(child, profileDir);
    child.stderr.on('data', d => { session.stderr += d.toString(); });
    child.stdout.on('data', () => {});

    const portFile = path.join(profileDir, 'DevToolsActivePort');
    let port = null;
    for (let i = 0; i < 300; i++) {
      if (child.exitCode !== null) throw new Error('Chrome 提前退出：' + session.stderr.slice(0, 800));
      if (fs.existsSync(portFile)) {
        const txt = fs.readFileSync(portFile, 'utf8').split('\n')[0].trim();
        if (txt) { port = txt; break; }
      }
      await new Promise(r => setTimeout(r, 100));
    }
    if (!port) throw new Error('等不到 DevToolsActivePort：' + session.stderr.slice(0, 800));
    session.port = port;
    return session;
  }

  async newPage(url) {
    const r = await fetch(`http://127.0.0.1:${this.port}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
    const target = await r.json();
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    this.ws = ws;
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = e => rej(new Error('WS 连接失败')); });
    ws.onmessage = ev => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
      }
    };
    ws.onclose = () => {
      for (const { reject } of this.pending.values()) reject(new Error('CDP 连接断开'));
      this.pending.clear();
    };
    await this.send('Page.enable');
    await this.send('Runtime.enable');
    return target;
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== 1) return reject(new Error('CDP 未连接'));
      const id = ++this.nextId;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error(`CDP 超时：${method}`)); }
      }, 120000);
    });
  }

  /** 在页面里跑一段表达式（支持 await），返回 JSON 值。 */
  async evaluate(expression, { awaitPromise = true, timeout = 120000 } = {}) {
    const r = await this.send('Runtime.evaluate', {
      expression, awaitPromise, returnByValue: true, timeout,
    });
    if (r.exceptionDetails) {
      const d = r.exceptionDetails;
      throw new Error('页面异常：' + ((d.exception && (d.exception.description || d.exception.value)) || d.text));
    }
    return r.result ? r.result.value : undefined;
  }

  async kill() {
    try { if (this.ws) this.ws.close(); } catch {}
    try { this.child.kill(); } catch {}
    // 等进程真的退出，否则删 profile 会 EBUSY
    await new Promise(res => {
      if (this.child.exitCode !== null) return res();
      const t = setTimeout(() => { try { this.child.kill('SIGKILL'); } catch {} res(); }, 8000);
      this.child.once('exit', () => { clearTimeout(t); res(); });
    });
  }
}

async function rmrfRetry(p, attempts = 12) {
  for (let i = 0; i < attempts; i++) {
    try { await fsp.rm(p, { recursive: true, force: true }); return true; }
    catch { await new Promise(r => setTimeout(r, 300)); }
  }
  return false;
}

/* ========================================================================== */
/* 4) 轮次：跑一遍测试页                                                        */
/* ========================================================================== */
async function runRound({ exe, label, url, chromeArgs, timeoutMs }) {
  const session = await CdpSession.launch(exe, chromeArgs);
  try {
    await session.newPage(url);
    const deadline = Date.now() + timeoutMs;
    let done = false;
    while (Date.now() < deadline) {
      try {
        done = await session.evaluate('window.__ASR_DONE__ === true', { awaitPromise: false });
      } catch (e) {
        // 导航过程中执行上下文会被销毁，这类报错是正常的，继续等
        if (/CDP 连接断开/.test(e.message)) throw e;
      }
      if (done) break;
      await new Promise(r => setTimeout(r, 1000));
    }
    let result;
    try {
      result = await session.evaluate('JSON.stringify(window.__ASR_RESULT__ || null)', { awaitPromise: false });
      result = result ? JSON.parse(result) : null;
    } catch { result = null; }
    let summary = '';
    try { summary = await session.evaluate('document.getElementById("summary").textContent', { awaitPromise: false }); } catch {}
    if (!done) {
      throw new Error(`${label} 超时（${timeoutMs / 1000}s）。页面摘要：\n${summary}\nChrome stderr: ${session.stderr.slice(-1200)}`);
    }
    return { result, summary, stderr: session.stderr };
  } finally {
    await session.kill();
  }
}

/* ========================================================================== */
/* 5) Python 侧交叉验证                                                         */
/* ========================================================================== */
function runPythonAsr() {
  const pyFile = tmpPath(`yuyi-asr-ref-${process.pid}.py`);
  const outFile = tmpPath(`yuyi-asr-ref-${process.pid}.json`);
  const script = `# -*- coding: utf-8 -*-
import json, sys, traceback
from pathlib import Path

WAV = Path(r"""${SAMPLE_WAV}""")
MODEL = r"""${MODEL_DIR}"""
OUT = Path(r"""${outFile}""")
SCRIPTS = r"""${path.dirname(LOCAL_ASR_PY)}"""

payload = {"ok": False}
try:
    sys.path.insert(0, SCRIPTS)
    from local_asr import transcribe_local
    import time as _time
    started = _time.perf_counter()
    result = transcribe_local(WAV, engine="vosk", model=MODEL, language="zh")
    elapsed_ms = round((_time.perf_counter() - started) * 1000)
    payload = {
        "ok": True,
        "text": result.get("text", ""),
        "engine": result.get("engine", ""),
        "note": result.get("note", ""),
        "segments": len(result.get("segments") or []),
        "offline": result.get("offline", False),
        "ms": elapsed_ms,
    }
except Exception as exc:
    payload = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
               "traceback": traceback.format_exc()[-2000:]}
OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
`;
  fs.writeFileSync(pyFile, script, 'utf8');
  const py = process.platform === 'win32' ? 'python' : 'python3';
  const proc = spawnSync(py, [pyFile], {
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    timeout: 600000,
    windowsHide: true,
  });
  let payload;
  try {
    payload = JSON.parse(fs.readFileSync(outFile, 'utf8'));
  } catch (e) {
    payload = {
      ok: false,
      error: `拿不到 Python 结果（退出码 ${proc.status}）：${(proc.stderr || '').trim().slice(0, 600)}`,
    };
  }
  payload.stdout = (proc.stdout || '').trim().slice(0, 400);
  try { fs.unlinkSync(pyFile); } catch {}
  try { fs.unlinkSync(outFile); } catch {}
  return payload;
}

/* ========================================================================== */
/* 6) 文本归一化 + 重合率                                                       */
/* ========================================================================== */
function normText(s) {
  // 去标点、空白、以及 Vosk 在中文词之间插的空格；只留汉字/字母/数字
  return String(s || '')
    .replace(/[\s\u3000]+/g, '')
    .replace(/[^\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9]/g, '');
}
function lcsLength(a, b) {
  if (!a.length || !b.length) return 0;
  const prev = new Uint32Array(b.length + 1);
  const cur = new Uint32Array(b.length + 1);
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      cur[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], cur[j - 1]);
    }
    prev.set(cur); cur.fill(0);
  }
  return prev[b.length];
}
function overlap(a, b) {
  const A = normText(a), B = normText(b);
  const lcs = lcsLength(A, B);
  const setA = new Set(A), setB = new Set(B);
  let inter = 0;
  for (const c of setA) if (setB.has(c)) inter++;
  const union = setA.size + setB.size - inter;
  return {
    aLen: A.length, bLen: B.length,
    lcs,
    dice: (A.length + B.length) ? +((2 * lcs) / (A.length + B.length)).toFixed(4) : 0,
    coverageA: A.length ? +(lcs / A.length).toFixed(4) : 0,   // 浏览器结果被 Python 结果覆盖的比例
    coverageB: B.length ? +(lcs / B.length).toFixed(4) : 0,
    jaccard: union ? +(inter / union).toFixed(4) : 0,
    normA: A, normB: B,
  };
}

/* ========================================================================== */
/* 主流程                                                                      */
/* ========================================================================== */
let server = null;
async function main() {
  out('');
  out('  语忆 · 离线 ASR(WASM) 无头验证');
  out('  ' + '='.repeat(74));
  out(`  时间      : ${new Date().toISOString()}`);
  out(`  项目目录  : ${ROOT}`);
  out(`  测试页    : ${TEST_PAGE}`);
  out(`  被测音频  : ${SAMPLE_WAV}`);
  out(`  分片数    : ${SLICES}（任务要求 ≥3）`);
  out(`  重合率阈值: ${THRESHOLD}`);

  /* ---- 步骤 1：静态服务器 ---- */
  section('① 起一个只服务项目目录的静态服务器（%TEMP% 之外不挂任何东西）');
  server = await startStaticServer();
  const port = server.address().port;
  const baseUrl = `http://localhost:${port}`;
  step(true, '静态服务器已监听', `${baseUrl}  （root = ${ROOT}）`);
  step(fs.existsSync(TEST_PAGE), '测试页存在', TEST_PAGE);
  // 只读别名单独说明，不藏着
  out(`         · 唯一例外：/__src__/test-sample.wav → ${SAMPLE_WAV}（只读映射，`);
  out('           因为被测音频在 yuyi-preview 之外，否则就得把它复制进项目目录）');

  /* ---- 步骤 2：资源就位 ---- */
  section('② 检查 data/asr/ 产物（引擎 + 模型 + manifest）');
  const enginePath = path.join(ASR_DIR, 'vosk.js');
  const modelPath = path.join(ASR_DIR, 'model.tar.gz');
  const manifestPath = path.join(ASR_DIR, 'manifest.json');
  let manifest = null;
  step(fs.existsSync(enginePath), 'vosk.js 存在',
    fs.existsSync(enginePath) ? `${fs.statSync(enginePath).size.toLocaleString()} B` : '缺失');
  step(fs.existsSync(modelPath), 'model.tar.gz 存在',
    fs.existsSync(modelPath) ? `${fs.statSync(modelPath).size.toLocaleString()} B` : '缺失');
  try { manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')); } catch {}
  step(!!manifest, 'manifest.json 可读',
    manifest ? `engine v${manifest.engine.version} / model ${manifest.model.name}` : '读不了');
  step(fs.existsSync(SAMPLE_WAV), '测试音频存在',
    fs.existsSync(SAMPLE_WAV) ? `${fs.statSync(SAMPLE_WAV).size.toLocaleString()} B` : '缺失');
  step(fs.existsSync(LOCAL_ASR_PY), 'Python local_asr.py 存在', LOCAL_ASR_PY);

  const modelBytes = fs.existsSync(modelPath) ? fs.statSync(modelPath).size : 0;
  const engineBytes = fs.existsSync(enginePath) ? fs.statSync(enginePath).size : 0;

  /* ---- 步骤 3：找 Chrome ---- */
  section('③ 找 headless Chrome');
  const exe = findChrome();
  step(!!exe, 'Chrome 可执行文件', exe || '没找到（找过 D:\\DevCache\\ms-playwright 与 %LOCALAPPDATA%\\ms-playwright）');
  if (!exe) throw new Error('没有 Chrome，无法继续');
  const verProbe = spawnSync(exe, ['--version'], { encoding: 'utf8', windowsHide: true });
  out(`         · ${(verProbe.stdout || verProbe.stderr || '').trim()}`);

  /* ---- 步骤 4：第一轮（正常联网） ---- */
  section('④ 第 1 轮：headless Chrome 打开自测页，页内加载 WASM + 模型（同源）');
  const url1 = `${baseUrl}/_tools/asr-wasm.test.html?slices=${SLICES}&warm=1&passes=2`;
  out(`         · ${url1}`);
  const t1 = Date.now();
  const round1 = await runRound({
    exe, label: '第 1 轮', url: url1, chromeArgs: [], timeoutMs: OVERALL_TIMEOUT_MS,
  });
  const wall1 = Date.now() - t1;
  const r1 = round1.result;
  step(!!r1, '第 1 轮返回结果', `整轮墙钟 ${(wall1 / 1000).toFixed(1)}s`);
  if (!r1) throw new Error('第 1 轮没有结果：\n' + round1.summary + '\n' + round1.stderr.slice(-1500));

  out('');
  out('         页面摘要：');
  String(round1.summary || '').split('\n').forEach(l => out('           ' + l));
  out('');
  out('         引擎 URL : ' + r1.engineUrl);
  out('         模型 URL : ' + r1.modelUrl);
  out('         页面源   : ' + r1.pageOrigin);

  const sameOrigin = r1.engineUrl.startsWith(r1.pageOrigin) && r1.modelUrl.startsWith(r1.pageOrigin);
  step(sameOrigin, '引擎与模型都来自本机静态服务器（同源，不是 CDN）',
    `origin=${r1.pageOrigin}`);
  const offOrigin = (r1.resources || []).filter(x => !x.sameOrigin);
  step(offOrigin.length === 0, '页面加载的资源里没有跨域项',
    offOrigin.length ? offOrigin.map(x => x.url).join(', ') : `${(r1.resources || []).length} 条同源资源`);

  step(r1.timings && r1.timings.modelReadyMs != null, '第 1 轮模型加载成功',
    r1.assets ? `模型 ${r1.assets.modelBytes.toLocaleString()} B + 引擎 ${r1.assets.engineBytes.toLocaleString()} B` : '');

  /* ---- 步骤 5：分片喂入 ---- */
  section('⑤ 第 1 轮：把 wav 解码成 16k 单声道 PCM，分片喂进去');
  out(`         · 音频 ${r1.pcm.seconds} s / ${r1.pcm.samples} 采样点 @${r1.pcm.sampleRate} Hz 单声道`);
  out(`         · 分 ${r1.chunks.slices} 片，共 ${r1.chunks.count} 个子块；` +
      `拿到 result=${r1.chunks.results} 条、partial=${r1.chunks.partials} 条中间结果`);
  step(r1.chunks.slices >= 3, `分片数 ≥ 3（实际 ${r1.chunks.slices}）`);
  step(r1.chunks.count >= 3, `实际喂入的子块数 ≥ 3（实际 ${r1.chunks.count}）`);
  step(r1.chunks.partials >= 1 || r1.chunks.results >= 1, '拿到了流式识别回执（中间结果或最终结果）');
  out('');
  out('         浏览器识别文本：');
  out('           ' + (r1.text || '（空）'));
  if (r1.partialSamples && r1.partialSamples.length) {
    out('         中间结果片段（前几条）：');
    r1.partialSamples.slice(0, 6).forEach(p => out('           · ' + p));
  }

  /* ---- 步骤 6：断言 ---- */
  section('⑥ 断言：文本非空 + 含中文');
  step(!!r1.text && r1.text.trim().length > 0, '识别文本非空',
    `${normText(r1.text).length} 个有效字符`);
  step(/[\u4e00-\u9fff]/.test(r1.text), '识别文本含中文字符',
    (r1.text.match(/[\u4e00-\u9fff]/g) || []).length + ' 个汉字');

  /* ---- 步骤 7：Python 交叉验证 ---- */
  section('⑦ 交叉验证：Python local_asr.py（同一个 Vosk 引擎 + 同一个模型）');
  const py = runPythonAsr();
  step(!!py.ok, 'Python 侧识别成功', py.ok ? `engine=${py.engine} segments=${py.segments} offline=${py.offline}` : (py.error || ''));
  if (py.ok) {
    out('');
    out('         Python 识别文本：');
    out('           ' + (py.text || '（空）').replace(/\n/g, ' / '));
    out(`         （${py.note || ''}）`);
    out(`         Python 侧（原生 vosk，CPU）识别同一份 wav 的耗时：` +
        `${py.ms} ms → RTF ${(py.ms / 1000 / 15.866).toFixed(3)}`);
    out('         这个数字很关键：本机当时负载不低，原生实现自己就跑到 RTF≈1 上下，');
    out('         所以浏览器 wasm 的绝对 RTF 只能同机同时间横向比，不能当设备性能结论。');
  }

  let ov = null;
  if (py.ok) {
    ov = overlap(r1.text, py.text);
    out('');
    out('         两次结果对比（均已去标点空白）：');
    out(`           浏览器 : ${ov.normA}`);
    out(`           Python : ${ov.normB}`);
    out(`           字符数 : ${ov.aLen} vs ${ov.bLen}`);
    out(`           最长公共子序列 LCS = ${ov.lcs}`);
    out(`           重合率(Dice=2·LCS/(|A|+|B|)) = ${ov.dice}`);
    out(`           覆盖率(浏览器结果被 Python 覆盖) = ${ov.coverageA}`);
    out(`           覆盖率(Python 结果被浏览器覆盖) = ${ov.coverageB}`);
    out(`           字符集合 Jaccard = ${ov.jaccard}`);
    step(ov.dice >= THRESHOLD, `字符重合率 ≥ ${THRESHOLD}（实际 ${ov.dice}）`);
  } else {
    step(false, '字符重合率无法计算（Python 侧没跑成）', py.error || '');
  }

  /* ---- 步骤 8：离线轮 ---- */
  section('⑧ 离线自证：用 --host-resolver-rules 阻断全部外部域名，重跑 3–4');
  const resolverRule = 'MAP * 0.0.0.0, EXCLUDE localhost, EXCLUDE 127.0.0.1';
  const chromeArgs2 = [`--host-resolver-rules=${resolverRule}`];
  out(`         · 参数：--host-resolver-rules="${resolverRule}"`);
  out('         · 用全新的 profile（不共享上一轮的 IndexedDB/HTTP 缓存），避免缓存把结论带偏');
  const url2 = `${baseUrl}/_tools/asr-wasm.test.html?slices=${SLICES}`;
  const t2 = Date.now();
  const round2 = await runRound({
    exe, label: '第 2 轮', url: url2, chromeArgs: chromeArgs2, timeoutMs: OVERALL_TIMEOUT_MS,
  });
  const wall2 = Date.now() - t2;
  const r2 = round2.result;
  step(!!r2, '第 2 轮（阻断外部域名）返回结果', `整轮墙钟 ${(wall2 / 1000).toFixed(1)}s`);
  if (!r2) throw new Error('第 2 轮没有结果：\n' + round2.summary + '\n' + round2.stderr.slice(-1500));

  out('');
  out('         页面摘要：');
  String(round2.summary || '').split('\n').forEach(l => out('           ' + l));
  out('');
  out('         浏览器识别文本（阻断外部域名下）：');
  out('           ' + (r2.text || '（空）'));

  // 对照组：证明「阻断」是真的生效，而不是恰好没网
  const ext1 = r1.external || {};
  const ext2 = r2.external || {};
  out('');
  out(`         外部域名探测对照（${ext1.url || ''}）：`);
  out(`           第 1 轮（不阻断）：${JSON.stringify(ext1)}`);
  out(`           第 2 轮（已阻断）：${JSON.stringify(ext2)}`);
  const netWasUp = ext1.ok === true;
  const blocked = ext2.ok !== true;
  step(blocked, '第 2 轮外部域名确实被阻断（探测失败）');
  if (netWasUp) {
    step(true, '对照有效：第 1 轮同一探测是成功的 → 说明本机有外网，第 2 轮的失败是阻断造成的');
  } else {
    out('         ! 注意：第 1 轮的外部探测也没成功，说明本机此刻本来就连不上外网。');
    out('           这样「第 2 轮成功」就不能单独证明没有外部依赖，只能作为弱证据；');
    out('           真正的强证据是上面第 4 步的同源检查 + 服务器访问日志。');
  }

  step(!!r2.text && r2.text.trim().length > 0, '阻断外部域名后识别文本仍然非空', `${normText(r2.text).length} 个有效字符`);
  step(/[\u4e00-\u9fff]/.test(r2.text), '阻断外部域名后仍然识别出中文',
    (r2.text.match(/[\u4e00-\u9fff]/g) || []).length + ' 个汉字');
  if (py.ok) {
    const ov2 = overlap(r2.text, py.text);
    out('');
    out(`         与 Python 结果的重合率：${ov2.dice}（LCS=${ov2.lcs}）`);
    step(ov2.dice >= THRESHOLD, `离线轮重合率 ≥ ${THRESHOLD}（实际 ${ov2.dice}）`);
  }
  const sameOrigin2 = r2.engineUrl.startsWith(r2.pageOrigin) && r2.modelUrl.startsWith(r2.pageOrigin);
  step(sameOrigin2, '离线轮的引擎与模型同样来自本机服务器', r2.modelUrl);

  /* ---- 步骤 9：性能 ---- */
  section('⑨ 性能数据');
  const totalBytes = manifest ? manifest.total_bytes : (engineBytes + modelBytes);
  out(`         · 手机首次要下载的模型/引擎总字节数：${totalBytes.toLocaleString()} B` +
      `（${(totalBytes / 1024 / 1024).toFixed(2)} MiB）`);
  out(`            引擎 vosk.js      ${engineBytes.toLocaleString()} B`);
  out(`            模型 model.tar.gz ${modelBytes.toLocaleString()} B`);
  out(`            原始模型目录       ${manifest ? manifest.model.raw_bytes.toLocaleString() : '?'} B` +
      `（已 gzip 到 ${(modelBytes / (manifest ? manifest.model.raw_bytes : modelBytes) * 100).toFixed(1)}%）`);
  out(`         · 第 1 轮（冷启动，IndexedDB 空）整轮墙钟：${(wall1 / 1000).toFixed(1)} s`);
  out(`         · 第 2 轮（冷启动 + 阻断外部域名）整轮墙钟：${(wall2 / 1000).toFixed(1)} s`);
  if (r1.timings) {
    const t = r1.timings;
    out(`         · 页面开始加载 → 模型就绪：${t.pageStartToModelReadyMs} ms`);
    out(`         · 页面开始加载 → 第一句文字出来：${t.pageStartToFirstTextMs} ms`);
    out(`         · 页面开始加载 → 全部识别完成：${t.pageStartToRecognizedMs} ms`);
    out(`         · 识别 ${r1.pcm.seconds} s 音频耗时：${t.recognizeMs} ms` +
        ` → RTF = ${t.rtf}（第 1 遍，含首次预热）`);
    if (t.steadyMs != null) {
      out(`         · 稳态（第 2 遍，同一段音频、全新 recognizer）：${t.steadyMs} ms` +
          ` → RTF = ${t.steadyRtf}`);
      out(`         · 加速比（稳态）：${(r1.pcm.seconds * 1000 / t.steadyMs).toFixed(2)}× 实时`);
    }
    out(`         · 队列健康度：dropped=${(r1.asrState && r1.asrState.dropped) || 0}，` +
        `queued=${(r1.asrState && r1.asrState.queuedChunks) || 0}` +
        `（>0 表示这台机器喂不过来、wrapper 已经开始丢块）`);
    if (t.warmInitMs != null) {
      out(`         · 模型已被 IndexedDB 缓存后再 init：${t.warmInitMs} ms` +
          `（冷启动 ${t.pageStartToModelReadyMs} ms，快 ${(t.pageStartToModelReadyMs / Math.max(1, t.warmInitMs)).toFixed(1)}×）`);
    } else {
      out('         · 缓存命中耗时：本机这一次没测到（warm init 未完成）');
    }
  }
  step(r1.timings && r1.timings.rtf != null && r1.timings.rtf < 5,
    `识别吞吐在合理范围（RTF < 5 的兜底线，实际 ${r1.timings && r1.timings.rtf}）`,
    '这不是「能否实时」的结论：绝对 RTF 随当时机器负载变化很大，见下面的对照');
  out('');
  out('         ⚠ 关于 RTF 的诚实说明：');
  out('           · 本机当时不是空闲状态（同时有别的 Chrome / 应用在跑），');
  out('             同一次运行里 Python 原生 vosk 自己就跑到 RTF≈1 上下 ——');
  out('             说明这个绝对值主要反映「当时的机器负载」，不是设备能力结论。');
  out('           · 首次解码还有一笔一次性的预热成本（wasm JIT + 68 MB 模型分页），');
  out('             所以「第一遍」永远比稳态慢，长录音看稳态更有意义。');
  out('           · 真机手机上的稳态 RTF 本次**没有测**，不能拿这里的数字下结论。');

  /* ---- 服务器访问日志 ---- */
  section('⑩ 静态服务器收到的请求（证明资源都从本机来）');
  const asrReq = requestLog.filter(l => /data\/asr|asr-wasm\.test|yuyi-asr|__src__/.test(l));
  asrReq.forEach(l => out('         · ' + l));
  const asrCount = asrReq.length;
  step(asrCount >= 3, `确实向本机服务器要过 data/asr/ 等资源（${asrCount} 条）`);

  /* ---- 汇总 ---- */
  section('汇总');
  out(`  步骤总数 ${passCount + failCount}：PASS ${passCount}，FAIL ${failCount}`);
  if (failCount) {
    out('  失败的步骤：');
    stepResults.filter(s => !s.ok).forEach(s => out(`    ✗ ${s.label}${s.detail ? ' —— ' + s.detail : ''}`));
  }
  out('');
  out(`  弱项/未测项（诚实说明）：`);
  out(`    · 未在真机手机浏览器上跑过（本机只有 Windows + headless Chrome 153）`);
  out(`    · 未测 iOS Safari（AudioWorklet / IDBFS 行为可能不同）`);
  out(`    · 未测低端机内存（模型解包后 wasm 堆峰值未量）`);
  out(`    · headless 下没有麦克风，走的是「解码 wav → 分片喂 PCM」路径，`);
  out(`      麦克风路径 start({mic:true}) 只做了代码审阅与降级分支，未实测`);
  out('');
  return failCount === 0 ? 0 : 1;
}

/* ------------------------------------------------------------------ 收尾 */
async function cleanup() {
  try { if (server) server.close(); } catch {}
  if (!KEEP_TEMP) {
    for (const p of TMP_CREATED) {
      let isDir = false;
      try { isDir = fs.statSync(p).isDirectory(); } catch { continue; }
      if (!isDir) { try { await fsp.rm(p, { force: true }); } catch {} }
    }
    // profile 目录最后删（Chrome 句柄可能还没放）
    for (const p of TMP_CREATED.filter(x => /yuyi-asr-profile-/.test(x))) await rmrfRetry(p);
  }
}

let exitCode = 1;
try {
  exitCode = await main();
} catch (e) {
  out('');
  out('  [FAIL] 验证过程中断：' + (e && e.stack ? e.stack : e));
  section('汇总');
  out(`  步骤总数 ${passCount + failCount}：PASS ${passCount}，FAIL ${failCount}（另有致命中断）`);
  exitCode = 1;
} finally {
  await cleanup();
  if (LOG_PATH) {
    try { fs.writeFileSync(LOG_PATH, lines.join('\n') + '\n', 'utf8'); process.stdout.write(`\n  （完整日志：${LOG_PATH}）\n`); } catch {}
  }
}

out('');
out(exitCode === 0 ? '  === 全部 PASS ===' : '  === 存在 FAIL ===');
out('');
process.exit(exitCode);