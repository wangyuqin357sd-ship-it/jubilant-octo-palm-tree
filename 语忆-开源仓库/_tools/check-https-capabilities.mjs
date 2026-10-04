/*
  语忆 · 手机预览「安全上下文与能力」自检
  ============================================================================
  作用：确认**通过 https 预览服务器打开时**，浏览器真的给了这个源
        振动 / 系统通知 / Service Worker / 唤醒锁 / 麦克风 等能力。
        直接双击 index.html（file://）时这些能力会缺失，用本工具一眼就能看出差别。

  做法：起一个 headless Chrome，指到目标 URL，用 CDP（DevTools 协议）在**真实页面**里
        执行一段能力探测，把结果打成 JSON。零依赖（只用 Node 内置 fetch / WebSocket）。

  用法：
    node _tools/check-https-capabilities.mjs
    node _tools/check-https-capabilities.mjs --url https://<电脑局域网IP>:8444/
    node _tools/check-https-capabilities.mjs --url file:///<本仓库绝对路径>/index.html

  退出码：全部关键能力就绪 → 0；否则 → 1
*/

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/* ---------------------------------------------------------------- 参数 */
function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}
const URL_TARGET = arg('url', 'https://127.0.0.1:8444/');
const PORT = Number(arg('port', '9444'));

/* ---------------------------------------------------------------- 找 shell */
function findChrome() {
  const roots = [
    'D:\\DevCache\\ms-playwright',
    join(process.env.LOCALAPPDATA || '', 'ms-playwright'),
  ];
  for (const root of roots) {
    if (!root || !existsSync(root)) continue;
    const hits = [];
    for (const dir of readdirSync(root)) {
      if (!dir.startsWith('chromium_headless_shell-')) continue;
      const sub = join(root, dir, 'chrome-headless-shell-win64', 'chrome-headless-shell.exe');
      if (existsSync(sub)) hits.push(sub);
    }
    if (hits.length) return hits.sort().pop();
  }
  return null;
}

const exe = findChrome();
if (!exe) {
  console.error('找不到 chrome-headless-shell.exe');
  process.exit(2);
}

/* ---------------------------------------------------------------- 探测表达式 */
const PROBE = `(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 80 && !window.__yuyi; i++) await sleep(100);
  const Y = window.__yuyi;
  const out = {};
  out.url = location.href;
  out.protocol = location.protocol;
  out.isSecureContext = window.isSecureContext;
  out.hasNotification = 'Notification' in window;
  out.notificationPermission = (() => { try { return Notification.permission; } catch (e) { return 'ERR'; } })();
  out.vibrate = typeof navigator.vibrate;
  out.hasWakeLock = 'wakeLock' in navigator;
  out.hasServiceWorker = 'serviceWorker' in navigator;
  out.hasMediaDevices = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  out.hasSpeech = 'speechSynthesis' in window;
  out.hasUserActivation = !!(navigator.userActivation && typeof navigator.userActivation.hasBeenActive === 'boolean');
  out.hasBeenActive = navigator.userActivation ? navigator.userActivation.hasBeenActive : null;
  out.hasYuyi = !!Y;
  out.todoItems = document.querySelectorAll('#todoList .todo').length;
  out.vibState = (document.getElementById('vibState') || {}).textContent || '';
  out.notifyState = (document.getElementById('notifyState') || {}).textContent || '';
  out.armCardPresent = !!document.getElementById('armCard');
  out.armCardHidden = document.getElementById('armCard') ? document.getElementById('armCard').hidden : null;
  let reg = null;
  try {
    if (navigator.serviceWorker) reg = await navigator.serviceWorker.register('sw.js', { scope: './' });
  } catch (e) { out.swRegisterError = String((e && e.message) || e); }
  out.swRegistered = !!reg;
  out.swScope = reg ? reg.scope : null;
  out.swShowNotification = !!(reg && typeof reg.showNotification === 'function');
  out.swController = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
  try {
    Object.defineProperty(navigator, 'userActivation', { configurable: true,
      get: () => ({ hasBeenActive: true, isActive: true }) });
    out.syncArmUIWhenArmed = Y ? Y.syncArmUI() : null;
    out.armCardHiddenWhenArmed = document.getElementById('armCard').hidden;
  } catch (e) { out.armStubError = String(e.message); }
  return JSON.stringify(out, null, 1);
})()`;

/* ---------------------------------------------------------------- 跑起来 */
const profile = mkdtempSync(join(tmpdir(), 'yuyi-cap-'));
const chrome = spawn(exe, [
  '--headless', '--no-sandbox', '--disable-gpu',
  '--ignore-certificate-errors',            // 模拟手机上点「高级 → 继续前往」之后的状态
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`,
  '--window-size=430,932',
  URL_TARGET,
], { stdio: 'ignore' });

let done = false;
function cleanup(code) {
  if (done) return;
  done = true;
  try { chrome.kill(); } catch (e) {}
  try { rmSync(profile, { recursive: true, force: true }); } catch (e) {}
  process.exit(code);
}
setTimeout(() => { console.error('超时：拿不到调试目标'); cleanup(2); }, 40000);

async function targetWs() {
  for (let i = 0; i < 100; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const page = list.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
      if (page) return page.webSocketDebuggerUrl;
    } catch (e) { /* 还没起来 */ }
    await new Promise(r => setTimeout(r, 150));
  }
  return null;
}

const ws = await targetWs();
if (!ws) { console.error('没拿到页面调试目标'); cleanup(2); }

const socket = new WebSocket(ws);
let id = 0;
const pending = new Map();
function send(method, params) {
  const msgId = ++id;
  socket.send(JSON.stringify({ id: msgId, method, params }));
  return new Promise((res, rej) => pending.set(msgId, { res, rej }));
}
socket.addEventListener('message', ev => {
  let msg;
  try { msg = JSON.parse(ev.data); } catch (e) { return; }
  if (msg.id && pending.has(msg.id)) {
    const { res, rej } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) rej(new Error(JSON.stringify(msg.error)));
    else res(msg.result);
  }
});

socket.addEventListener('open', async () => {
  try {
    await send('Runtime.enable', {});
    const r = await send('Runtime.evaluate', {
      expression: PROBE, awaitPromise: true, returnByValue: true,
    });
    if (r.exceptionDetails) {
      console.error('页面内探测抛错：', JSON.stringify(r.exceptionDetails).slice(0, 600));
      cleanup(1);
    }
    const data = JSON.parse(r.result.value);
    console.log('目标：' + URL_TARGET);
    console.log(JSON.stringify(data, null, 1));
    console.log('');

    const secure = data.protocol === 'https:' || data.isSecureContext === true;
    const checks = [
      ['安全上下文（振动/通知/麦克风的前提）', data.isSecureContext === true || secure],
      ['navigator.vibrate 存在', data.vibrate === 'function'],
      ['Notification API 存在', data.hasNotification === true],
      ['Service Worker 可用且注册成功', data.hasServiceWorker === true && data.swRegistered === true],
      ['registration.showNotification 可调用（手机弹通知的必要条件）', data.swShowNotification === true],
      ['Wake Lock 可用（提醒前 30s 防熄屏）', data.hasWakeLock === true],
      ['麦克风 API 可用', data.hasMediaDevices === true],
      ['语音播报可用', data.hasSpeech === true],
      ['待办页面已渲染（3 条演示数据）', data.todoItems === 3],
      ['能探测「页面是否已交互」（振动激活引导）', data.hasUserActivation === true],
    ];
    let bad = 0;
    for (const [name, ok] of checks) {
      console.log((ok ? '  PASS  ' : '  FAIL  ') + name);
      if (!ok) bad++;
    }
    console.log('');
    if (data.protocol === 'file:') {
      console.log('  提示：这是 file:// 打开的结果。桌面 Chrome 下 file:// 算安全上下文，');
      console.log('        振动/麦克风 API 都在，但 **Service Worker 注册被拒**（origin 为 "null"）——');
      console.log('        而 Chrome for Android 弹系统通知必须走 registration.showNotification，');
      console.log('        所以手机端的常驻通知在 file:// 下弹不出来。');
      console.log('        要完整体验请用 https 预览服务器：双击「手机预览.bat」。');
    }
    console.log('  结论：' + (bad ? `有 ${bad} 项未就绪` : '全部就绪'));
    cleanup(bad ? 1 : 0);
  } catch (e) {
    console.error('探测失败：' + e.message);
    cleanup(1);
  }
});
socket.addEventListener('error', () => { console.error('WebSocket 连接失败'); cleanup(2); });