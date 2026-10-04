<#
  语忆 · 待办振动提醒 —— 独立验收探针
  ==========================================================================
  规范：《安卓手机端专属·待办振动提醒功能规范（公益落地版）》
  基准：`_tools/todo-vibration-contract.md`（冻结 v1.1）
  目标：yuyi-preview/index.html（单文件、纯前端、零依赖）

  做法：沿用本仓库既有模式（verify-ui.ps1 / verify-newscreens.ps1 / verify-newflows.ps1）
        —— 在 <head> 之后注入 stub（记录调用序列、可用性伪造、定时器 delay），
           在 </body> 之前注入探针，用 chrome-headless-shell --dump-dom 取回 JSON，
           再在 PowerShell 侧逐条断言并打印 PASS/FAIL。

  stub 之所以注入 <head> 之后：必须早于页面自身的 <script>，否则观测不到
  「振动 → 通知 → TTS」的真实调用顺序。

  用法：
    powershell -ExecutionPolicy Bypass -File _tools\verify-todo-vibration.ps1
    powershell -ExecutionPolicy Bypass -File _tools\verify-todo-vibration.ps1 -Page <其它 index.html>
  退出码：全部 PASS → 0；有 FAIL → 1。
#>
param(
  [string]$Page = 'C:\Users\HP\Desktop\yuyi-preview\index.html'
)

# 与同目录 verify-ui / verify-newflows / verify-newscreens 保持一致：不要用 Stop。
# Chrome 偶发往 stderr 打 GPU 警告，Stop 会把整轮验收直接中断（实测踩过）。
$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------- 环境
$exe = (Get-ChildItem 'D:\DevCache\ms-playwright\chromium_headless_shell-*' -Recurse `
          -Filter 'chrome-headless-shell.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1).FullName
if (-not $exe) {
  $exe = (Get-ChildItem (Join-Path $env:LOCALAPPDATA 'ms-playwright') -Recurse `
            -Filter 'chrome-headless-shell.exe' -ErrorAction SilentlyContinue |
          Sort-Object FullName -Descending | Select-Object -First 1).FullName
}
if (-not $exe) { Write-Host 'NO chrome-headless-shell FOUND'; exit 2 }
if (-not (Test-Path -LiteralPath $Page)) { Write-Host "PAGE NOT FOUND: $Page"; exit 2 }

Write-Host "页面 : $Page"
Write-Host "外壳 : $exe"
Write-Host ''

# ---------------------------------------------------------------- 断言记账
$script:pass = 0; $script:fail = 0; $script:lines = @()
function Check([string]$id, [string]$desc, [bool]$ok, [string]$got = '') {
  if ($ok) { $script:pass++; $script:lines += ('PASS  {0,-6} {1}' -f $id, $desc) }
  else     { $script:fail++; $script:lines += ('FAIL  {0,-6} {1}     实测={2}' -f $id, $desc, $got) }
}

# ---------------------------------------------------------------- 场景执行器
function Invoke-Scenario([string]$Stub, [string]$Probe, [int]$Budget) {
  $tmp  = Join-Path $env:TEMP ('vtv-' + [guid]::NewGuid().ToString('N') + '.html')
  $prof = Join-Path $env:TEMP ('vtv-prof-' + [guid]::NewGuid().ToString('N'))
  try {
    $html = Get-Content -LiteralPath $Page -Raw -Encoding UTF8
    if ($Stub) { $html = $html -replace '(?s)(<head>)', ("`$1`r`n<script>" + $Stub + '</script>') }
    $html = $html -replace '</body>', ($Probe + "`r`n</body>")
    [System.IO.File]::WriteAllText($tmp, $html, (New-Object System.Text.UTF8Encoding($false)))
    # 原生调用的 stderr 噪音（Chrome 偶发 GPU 警告）不能中断验收：临时放宽 EA
    $prevEA = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
      $raw = & $exe --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --user-data-dir=$prof `
             --window-size=430,1240 --virtual-time-budget=$Budget `
             --dump-dom ("file:///" + ($tmp -replace '\\', '/')) 2>&1 | Out-String
    } finally {
      $ErrorActionPreference = $prevEA
    }
  } finally {
    Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $tmp  -Force -ErrorAction SilentlyContinue
  }
  $m = [regex]::Match($raw, '(?s)<pre id="probe-json">(.*?)</pre>')
  if (-not $m.Success) {
    Write-Host '  [warn] 未取回探针 JSON，尾部输出：'
    Write-Host ('  ' + $raw.Substring([Math]::Max(0, $raw.Length - 400)))
    return $null
  }
  $j = $m.Groups[1].Value -replace '&quot;', '"' -replace '&amp;', '&' -replace '&lt;', '<' -replace '&gt;', '>'
  try { return ($j | ConvertFrom-Json) } catch { Write-Host ('  [warn] JSON 解析失败：' + $_.Exception.Message); return $null }
}

# ================================================================ 通用 stub
# 记录：vibrate 调用序列、Notification 构造参数、TTS 文本/语速、wakeLock 请求与释放、定时器 delay
$stubCommon = @'
(function(){
  window.__seq=[]; window.__delays=[];
  Object.defineProperty(Navigator.prototype,'vibrate',{configurable:true,writable:true,
    value:function(p){ window.__seq.push(['vibrate', Array.isArray(p)?p.join('/'):String(p)]); return true; }});
  function FakeNotif(title,opts){ this.title=title; this.opts=opts||{}; this.__todoId=null; this._l={};
    window.__seq.push(['notify', title, JSON.stringify(opts||{})]); }
  FakeNotif.prototype.addEventListener=function(k,f){ (this._l[k]=this._l[k]||[]).push(f); };
  FakeNotif.prototype.close=function(){                       // 刻意用同步回调：回归「close 重入」缺陷
    window.__seq.push(['notify-close', this.title]);
    var self=this; (this._l.close||[]).forEach(function(f){ f.call(self); }); };
  FakeNotif.permission='granted';
  FakeNotif.requestPermission=function(){ return Promise.resolve('granted'); };
  window.Notification=FakeNotif;
  if(!window.speechSynthesis){ window.speechSynthesis={}; }
  window.speechSynthesis.speak =function(u){ window.__seq.push(['tts', u&&u.text, u&&u.rate]); };
  window.speechSynthesis.cancel=function(){ window.__seq.push(['tts-cancel','']); };
  Object.defineProperty(navigator,'wakeLock',{configurable:true, value:{ request:function(n){
    window.__seq.push(['wakelock-request',n]);
    return Promise.resolve({ released:false, addEventListener:function(){},
      release:function(){ this.released=true; window.__seq.push(['wakelock-release','']); return Promise.resolve(); } });
  }}});
  var _st=window.setTimeout,_si=window.setInterval;
  window.setTimeout =function(fn,d){ window.__delays.push('T'+(d||0)); return _st.apply(window,arguments); };
  window.setInterval=function(fn,d){ window.__delays.push('I'+(d||0)); return _si.apply(window,arguments); };
  window.addEventListener('error',function(e){ window.__seq.push(['error', String(e.message)+'@'+e.lineno]); });
})();
'@

# ================================================================ 场景 1：正常路径（A/B/C/D/E/G/H）
$probe1 = @'
<script>
window.__p={};
window.addEventListener('DOMContentLoaded',function(){
  var Y=window.__yuyi, p=window.__p, g=function(s){return document.getElementById(s)},
      seq=function(k){return window.__seq.filter(function(x){return x[0]===k})};
  try{
    p.hasYuyi=!!Y;
    if(!Y){ var pre=document.createElement('pre');pre.id='probe-json';pre.textContent=JSON.stringify(p);document.body.appendChild(pre); return; }

    /* --- 常量与纯函数 --- */
    p.consts={ group:Y.VIB_GROUP, groups:Y.VIB_GROUPS, gap:Y.VIB_GAP,
               groupMs:Y.VIB_GROUP_MS, window:Y.REMIND_WINDOW_MS,
               hidden:Y.HIDDEN_CHECK_MS, heartbeat:Y.HEARTBEAT_MS, wakelead:Y.WAKELEAD_MS,
               ttsRate:Y.TTS_RATE, ttsRepeat:Y.TTS_REPEAT, tagPrefix:Y.NOTIFY_TAG_PREFIX,
               muteSystemHint:Y.muteSystemHint };
    p.mode=[Y.parseMode('用震动'), Y.parseMode('振动一下'), Y.parseMode('闹钟响铃'),
            Y.parseMode('用声音'), Y.parseMode('随便说点什么')];
    /* ⚠️ 必须容错：空态（用户已删除演示数据）下 todos[0]/todos[2] 是 undefined。
       原来这里直接抛错被 catch 吞掉 → p.reg / p.a11y / startHiddenWatch / 待办排程
       全都不执行 → 一次抛错连锁打红 25 条断言，把真正的根因埋掉。
       空态下给可断言的占位值，让探针继续跑完。 */
    /* 空态（演示数据已删）下不注入 state —— 用合成输入直接测 todoAria 这个真函数。
       注意不能改 Y.state.todos，否则 H1 的"列表条数==state.todos.length"会因 DOM 未重渲染而假红。 */
    /* G3 测的是 todoAria 的两个分支：有时间 → 震动提醒模式；无时间 → 无提醒。
       所以合成输入必须一对、覆盖两支（原来两条都带时间，第二条必红）。 */
    var _syn1={text:"测试待办一",at:Date.now()+3600000,mode:"vibrate"};
    var _syn2={text:"测试待办二",at:null,mode:"vibrate"};
    p.aria=[Y.todoAria(Y.state.todos[0]||_syn1), Y.todoAria(Y.state.todos[2]||Y.state.todos[1]||_syn2)];
    p.todoCount=Y.state.todos.length;

    /* --- 回归：既有功能未被动到 --- */
    p.reg={ todoItems:document.querySelectorAll('#todoList .todo').length,
            confirmDlg:!!g('confirmDialog'), assistant:!!g('assistant'),
            audioPanel:!!g('audioPanel'), notesPanel:!!g('notesPanel'),
            dirPanel:!!g('dirPanel'), exportsPanel:!!g('exportsPanel'),
            banner:(document.querySelector('#todoPanel .banner')||{}).textContent||'',
            chips:document.querySelectorAll('.cmd-group .chip[data-cmd]').length,
            chipAck:!!document.querySelector('#assistant [data-cmd="todoAck"]'),
            chipSnooze:!!document.querySelector('#assistant [data-cmd="todoSnooze"]'),
            ids:['vibPanelCard','vibSwitch','vibTestBtn','vibState','permCard','permBtn',
                 'notifySwitch','notifyState','remindDlg','remindTitle','remindBody',
                 'remindAckBtn','remindSnoozeBtn','todoDoneBtn','todoVoiceBtn','todoAddBtn','todoInput']
                .filter(function(id){return !g(id)}) };
    p.a11y={ role:(document.querySelector('#remindDlg section')||{}).getAttribute
                     ? document.querySelector('#remindDlg section').getAttribute('role') : null,
             ariaModal:document.querySelector('#remindDlg section').getAttribute('aria-modal'),
             labels:(function(){ var bad=[];
               ['vibSwitch','vibTestBtn','notifySwitch','permBtn','remindAckBtn','remindSnoozeBtn','todoDoneBtn']
                 .forEach(function(id){ var e=g(id); if(!e||!(e.getAttribute('aria-label')||'').trim()) bad.push(id); });
               return bad; })() };

    /* --- 保活：隐藏态看护确实装上了两个定时器 --- */
    Y.startHiddenWatch();
    p.watch={ hidden:!!Y.sched.hiddenTimer, heartbeat:!!Y.sched.heartbeatTimer };
    Y.stopHiddenWatch();
    p.watchCleared={ hidden:!Y.sched.hiddenTimer, heartbeat:!Y.sched.heartbeatTimer };

    /* --- 触发一条正常（未延迟）振动待办 --- */
    Y.state.todos.length=0;
    Y.state.todos.push({id:'v1',text:'验收：交作业',done:false,from:'探针',
      at:Date.now()+40,mode:'vibrate',reminded:false,snooze:0,firedAt:null});
    Y.scheduleAll();
  }catch(e){ p.setupErr=String(e.message); }

  setTimeout(function(){                       /* 400ms：振动与通知已发出，TTS 尚未启动 */
    try{
      var o=g('remindAckBtn'), s=g('remindSnoozeBtn');
      p.s1={
        vibrateCalls:Y.vibrateCalls.map(function(c){return Array.isArray(c)?c.join(','):String(c)}),
        active:Y.remind.activeTodo?Y.remind.activeTodo.id:null,
        overdue:Y.remind.overdue,
        dlgOpen:!g('remindDlg').hidden,
        title:g('remindTitle').textContent,
        body:g('remindBody').textContent,
        focusId:document.activeElement?document.activeElement.id:null,
        ackOffsetH:o.offsetHeight, snzOffsetH:s.offsetHeight,
        notifLive:Y.notif.live.length,
        notifOpts:window.__seq.filter(function(x){return x[0]==='notify'}).map(function(x){return x[2]?JSON.parse(x[2]):null}),
        delays:window.__delays.slice(0,20)
      };
    }catch(e){ p.err1=String(e.message); }
  },400);

  setTimeout(function(){                       /* 1600ms：TTS 已在 +1250ms 启动，取完整序列后再应答 */
    try{
      p.s1b={
        seq:window.__seq.map(function(x){return x[0]+(x[1]!==undefined&&x[1]!==''?(':'+String(x[1]).slice(0,60)):'')}),
        tts:window.__seq.filter(function(x){return x[0]==='tts'}).map(function(x){return [x[1],x[2]];})
      };
      Y.ackReminder();
      p.s2={
        vibrateLast:(function(){var v=Y.vibrateCalls;return v.length?(Array.isArray(v[v.length-1])?v[v.length-1].join(','):String(v[v.length-1])):'none';})(),
        vibrateTotal:Y.vibrateCalls.length,
        active:Y.remind.activeTodo?Y.remind.activeTodo.id:null,
        reminded:Y.state.todos[0]?Y.state.todos[0].reminded:null,
        dlgOpen:!g('remindDlg').hidden,
        notifLive:Y.notif.live.length,
        next:Y.nextPending()?Y.nextPending().id:null,
        focusInsideDialog:!!(document.activeElement && g('remindDlg').contains(document.activeElement))
      };
      }catch(e){ p.err1b=String(e.message); }

    /* 焦点归还与唤醒锁释放都发生在 ack 之后；此时刻意不安排新提醒，避免第二个弹窗再次抢焦点 */
    setTimeout(function(){
      try{
        var a=document.activeElement;
        p.s2b={ focusId:a?(a.id||''):'', focusTag:a?a.tagName:'(none)',
                insideDialog:!!(a && g('remindDlg').contains(a)), dlgOpen:!g('remindDlg').hidden,
                restoreWasBody:Y.remind.restore===document.body,
                seqAfterAck:window.__seq.map(function(x){return x[0]+(x[1]!==undefined&&x[1]!==''?(':'+String(x[1]).slice(0,60)):'')}) };
        /* 焦点与唤醒锁断言取完，再排第二条待办用于「延后十分钟」断言 */
        Y.state.todos.push({id:'v2',text:'验收：延后台',done:false,from:'探针',
          at:Date.now()+40,mode:'vibrate',reminded:false,snooze:0,firedAt:null});
        Y.scheduleAll();
      }catch(e){ p.err1c=String(e.message); }
    },250);
  },1600);

  setTimeout(function(){                       /* 2400ms：v2 已触发，测「延后十分钟」 */
    try{
      p.s3={ active:Y.remind.activeTodo?Y.remind.activeTodo.id:null, vibrateTotal:Y.vibrateCalls.length };
      var before=Date.now();
      Y.snoozeReminder(10);
      var t2=Y.state.todos.filter(function(x){return x.id==='v2'})[0];
      p.s4={ active:Y.remind.activeTodo?Y.remind.activeTodo.id:null,
             snooze:t2?t2.snooze:null, reminded:t2?t2.reminded:null,
             atDeltaSec:t2?Math.round((t2.at-before)/1000):null,
             next:Y.nextPending()?Y.nextPending().id:null,
             dlgOpen:!g('remindDlg').hidden };
      p.errs=window.__seq.filter(function(x){return x[0]==='error'}).length;
    }catch(e){ p.err2=String(e.message); }
    var pre=document.createElement('pre');pre.id='probe-json';pre.textContent=JSON.stringify(p,null,1);
    document.body.appendChild(pre);
  },2400);
});
</script>
'@

# ================================================================ 场景 2：不支持振动 + 通知被拒（F1/F2）
$stub2 = @'
(function(){
  window.__seq=[];
  Object.defineProperty(Navigator.prototype,'vibrate',{configurable:true,writable:true,value:undefined});
  function F(t,o){this.title=t;this.opts=o||{};this._l={};window.__seq.push(['notify',t]);}
  F.prototype.addEventListener=function(k,f){(this._l[k]=this._l[k]||[]).push(f);};
  F.prototype.close=function(){var s=this;(this._l.close||[]).forEach(function(f){f.call(s)});};
  F.permission='denied'; F.requestPermission=function(){return Promise.resolve('denied')};
  window.Notification=F;
  window.addEventListener('error',function(e){window.__seq.push(['error',String(e.message)+'@'+e.lineno])});
})();
'@
$probe2 = @'
<script>
window.__p={};
window.addEventListener('DOMContentLoaded',function(){
  var Y=window.__yuyi,p=window.__p,g=function(s){return document.getElementById(s)};
  p.hasYuyi=!!Y;
  try{
    p.vibSupported=Y.vibSupported();
    p.vibTestHidden=g('vibTestBtn').hidden;
    p.vibSwitchDisabled=g('vibSwitch').disabled;
    p.vibState=g('vibState').textContent;
    p.notifPerm=Y.notifPermission();
    Y.state.todos.length=0;
    Y.state.todos.push({id:'x1',text:'验收：不支持振动',done:false,from:'探针',
      at:Date.now()+30,mode:'vibrate',reminded:false,snooze:0,firedAt:null});
    Y.scheduleAll();
  }catch(e){ p.setupErr=String(e.message); }
  setTimeout(function(){
    try{
      var t=Y.state.todos[0];
      p.fired={ modeAfter:t.mode, stillInList:Y.state.todos.length,
                notifLive:Y.notif.live.length,
                notifCalls:window.__seq.filter(function(x){return x[0]==='notify'}).length,
                dlgOpen:!g('remindDlg').hidden,
                active:Y.remind.activeTodo?Y.remind.activeTodo.id:null,
                srStatus:g('srStatus').textContent,
                srAlert:g('srAlert').textContent,
                toast:(document.querySelector('.toast')||{}).textContent||'' };
      p.errs=window.__seq.filter(function(x){return x[0]==='error'}).length;
    }catch(e){ p.err1=String(e.message); }
    var pre=document.createElement('pre');pre.id='probe-json';pre.textContent=JSON.stringify(p,null,1);
    document.body.appendChild(pre);
  },400);
});
</script>
'@

# ================================================================ 场景 3：过期待办汇总 + 后台延迟 + 多条串行（F3/F4/F5）
$probe3 = @'
<script>
window.__p={};
window.addEventListener('DOMContentLoaded',function(){
  var Y=window.__yuyi,p=window.__p,g=function(s){return document.getElementById(s)};
  var now=Date.now();
  p.hasYuyi=!!Y;
  try{
    Y.state.todos.length=0;
    Y.state.todos.push({id:'o1',text:'验收：过期丁',done:false,from:'探针',
      at:now-300000,mode:'vibrate',reminded:false,snooze:0,firedAt:null,_plannedAt:now-300000});
    Y.state.todos.push({id:'o2',text:'验收：过期戊',done:false,from:'探针',
      at:now-60000,mode:'ring',reminded:false,snooze:0,firedAt:null,_plannedAt:now-60000});
    Y.remind.activeTodo={id:'__blocker__'};        /* 临时占位，先读「汇总播报」文本 */
    p.overdueCount=Y.overdueList().length;
    p.overdueOrder=Y.overdueList().map(function(t){return t.id});
    p.announced=Y.announceOverdue();
  }catch(e){ p.setupErr=String(e.message); }

  setTimeout(function(){
    try{
      p.srAlertSummary=g('srAlert').textContent;
      p.srAlertRole=g('srAlert').getAttribute('role');
      p.srAlertLive=g('srAlert').getAttribute('aria-live');
      Y.remind.activeTodo=null;
      Y.scheduleAll();
    }catch(e){ p.err0=String(e.message); }

    setTimeout(function(){
      try{
        p.first={ active:Y.remind.activeTodo?Y.remind.activeTodo.id:null,
                  overdue:Y.remind.overdue,
                  meta:g('remindMeta').textContent.replace(/\s+/g,' '),
                  body:g('remindBody').textContent,
                  notifBodies:window.__seq.filter(function(x){return x[0]==='notify'}).map(function(x){
                    return x[2]?JSON.parse(x[2]).body:''; }),
                  ttsTexts:window.__seq.filter(function(x){return x[0]==='tts'}).map(function(x){return String(x[1]);}),
                  activeCount:Y.remind.activeTodo?1:0 };
        Y.ackReminder();
        p.mid={ active:Y.remind.activeTodo?Y.remind.activeTodo.id:null,
                o1reminded:Y.state.todos.filter(function(t){return t.id==='o1'})[0].reminded };
      }catch(e){ p.err1=String(e.message); }

      setTimeout(function(){
        try{
          p.second={ active:Y.remind.activeTodo?Y.remind.activeTodo.id:null,
                     overdue:Y.remind.overdue, body:g('remindBody').textContent,
                     dlgOpen:!g('remindDlg').hidden };
          p.muteSystemHint=Y.muteSystemHint;
          p.micFn=typeof Y.checkMicPermission;
          p.errs=window.__seq.filter(function(x){return x[0]==='error'}).length;
        }catch(e){ p.err2=String(e.message); }
        var pre=document.createElement('pre');pre.id='probe-json';pre.textContent=JSON.stringify(p,null,1);
        document.body.appendChild(pre);
      },600);
    },1800);   /* 留出 >400ms 余量：TTS 在「第一组振动结束后」启动，其时刻 = VIB_GROUP_MS，
                  1800ms 可避免该断言与节拍长度耦合（改节拍不该连累 F4d） */
  },150);
});
</script>
'@

# ================================================================ 场景 4：手机端系统通知走 Service Worker
# 背景：Chrome for Android 上 `new Notification()` 会抛 TypeError，
#       必须用 ServiceWorkerRegistration.showNotification()。这里把 register() 换成假的，
#       断言页面**优先**走 SW 路径（而不是退回构造器）。
$stubSW = @'
(function(){
  window.__seq=[]; window.__fakeSW={ showCalls:[], closeCalls:[], registerCalls:0 };
  Object.defineProperty(Navigator.prototype,'vibrate',{configurable:true,writable:true,
    value:function(p){ window.__seq.push(['vibrate', Array.isArray(p)?p.join('/'):String(p)]); return true; }});
  var fakeReg = {
    scope: 'https://example.test/',
    showNotification: function(title, opts){ window.__fakeSW.showCalls.push([title, opts]); },
    getNotifications: function(){ window.__fakeSW.closeCalls.push(true); return Promise.resolve([]); }
  };
  Object.defineProperty(navigator,'serviceWorker',{configurable:true, value:{
    register: function(){ window.__fakeSW.registerCalls++; return Promise.resolve(fakeReg); },
    controller: null
  }});
  function DesktopNotif(title,opts){ this.title=title; this.opts=opts||{}; this._l={}; this.__todoId=null;
    window.__seq.push(['desktop-notify', title]); }
  DesktopNotif.prototype.addEventListener=function(k,f){(this._l[k]=this._l[k]||[]).push(f);};
  DesktopNotif.prototype.close=function(){var s=this;(this._l.close||[]).forEach(function(f){f.call(s)});};
  DesktopNotif.permission='granted';
  DesktopNotif.requestPermission=function(){ return Promise.resolve('granted'); };
  window.Notification=DesktopNotif;
  if(!window.speechSynthesis){ window.speechSynthesis={}; }
  window.speechSynthesis.speak=function(){}; window.speechSynthesis.cancel=function(){};
  window.addEventListener('error',function(e){ window.__seq.push(['error', String(e.message)+'@'+e.lineno]); });
})();
'@
$probe4 = @'
<script>
window.__p={};
window.addEventListener('DOMContentLoaded',function(){
  var Y=window.__yuyi,p=window.__p;
  p.hasYuyi=!!Y;
  try{
    Y.state.todos.length=0;
    Y.state.todos.push({id:'sw1',text:'验收：手机端通知',done:false,from:'探针',
      at:Date.now()+30,mode:'vibrate',reminded:false,snooze:0,firedAt:null});
    Y.scheduleAll();
  }catch(e){ p.setupErr=String(e.message); }
  setTimeout(function(){
    try{
      var F=window.__fakeSW;
      p.registerCalls=F.registerCalls;
      p.showCalls=F.showCalls.map(function(c){ return [c[0], c[1] && c[1].body, c[1] && c[1].tag,
                                                        c[1] && c[1].requireInteraction]; });
      p.desktopNotifyCalls=window.__seq.filter(function(x){return x[0]==='desktop-notify'}).length;
      p.swRegSet=!!Y.notif.swReg;
      p.notifLive=Y.notif.live.length;
      Y.ackReminder();
      p.closeCalls=F.closeCalls.length;
      p.notifLiveAfterAck=Y.notif.live.length;
      p.errs=window.__seq.filter(function(x){return x[0]==='error'}).length;
    }catch(e){ p.err1=String(e.message); }
    var pre=document.createElement('pre');pre.id='probe-json';pre.textContent=JSON.stringify(p,null,1);
    document.body.appendChild(pre);
  },500);
});
</script>
'@

# ================================================================ 场景 6：本轮真机反馈的改动
# （手机端布局 / 笔记两选项 / 我的入口 / 朗读 / 导出三格式 / 录音结束三步 / 语音唤醒）
$probe6 = @'
<script>
window.addEventListener('DOMContentLoaded',function(){
  var q=function(s){return document.querySelector(s)},
      qa=function(s){return Array.prototype.slice.call(document.querySelectorAll(s))};
  var p={}, Y=window.__yuyi;
  p.hasYuyi=!!Y;
  var dlg=function(){return {title:(q('#dlgTitle')||{}).textContent||'',
                             buttons:qa('#dlgActions .btn').map(function(b){return b.textContent}).join(' / ')};};
  try{
    /* 语音：固定指令解析（直接喂文本，等价于识别结果） */
    var cases=['小语','小语结束','小雨','小语打开原音频','小语，AI总结',
               '小语，打开待办','小语，导出盲文','小语，帮助','小语，今天天气怎么样'];   /* 原为「待办事项提醒」：P0-F 后它会进入语音待办流程并吞掉后续用例（该五步已由专项探针验证），改用等价的「打开待办」 */
    p.voice=[];
    for (var i=0;i<cases.length;i++){ try{ p.voice.push(Y.handleVoiceText(cases[i])); }catch(e){ p.voice.push('ERR'); } }
    /* P0-F 之后「待办事项提醒」会进入语音待办流程且停在那里（设计如此），
       不退出的话后面每一句都会被它吞掉、返回 true → 必须显式退出（说「取消」）。 */
    try{ Y.handleVoiceText('取消'); }catch(e){}
    p.voiceSupported=Y.voiceSupported();
    p.wakeState=q('#wakePill').dataset.state;
    p.wakeText=q('#wakeTxt').textContent;
    p.wakeH=q('#wakePill').offsetHeight;
    /* 手机端布局 */
    p.frameH=q('.app-frame').offsetHeight; p.winH=window.innerHeight;
    p.tabBottom=Math.round(q('.tabbar').getBoundingClientRect().bottom);
    p.docOverflow=getComputedStyle(document.body).overflow;
    /* 朗读 */
    var rb=q('#noteList [data-act="read"]');
    p.readBtnLabel=rb?rb.textContent.trim():'';
    p.ttsOk=Y.ttsSupported();
    /* 笔记入口（P0 之后）：不再是「看哪一边」确认弹窗，而是**全屏笔记页**；
       底部 Tab【笔记】与侧边栏【笔记】的落点必须一致（用户明确要求过） */
    q('#sideNote').click();
    p.notePage = { open: !q('#noteScreen').hidden,
                   tabs: qa('#noteScreen [role="tab"]').length,
                   selected: qa('#noteScreen [role="tab"][aria-selected="true"]').length,
                   dlgOpen: !q('#confirmDialog').hidden };
    q('#tabNote').click();
    p.notePageViaTab = { open: !q('#noteScreen').hidden,
                         tabs: qa('#noteScreen [role="tab"]').length,
                         selected: qa('#noteScreen [role="tab"][aria-selected="true"]').length };
    /* 切到「AI 总结笔记」那一边（分段控件第二个 tab）再取导出 */
    var seg = qa('#noteScreen [role="tab"]');
    if (seg[1]) seg[1].click();
    p.notesOpen=!q('#notesPanel').hidden;
    /* 导出：三种格式 */
    var eb=q('#noteList [data-act="export"]'); if(eb) eb.click();
    p.exportChooser=dlg();
    var b2=qa('#dlgActions .btn'); if(b2.length) b2[b2.length-1].click();
    /* 关掉笔记页：用真实控件，且**必须容错**——原来这行没有判空，
       一旦控件不存在就抛 TypeError 被 catch 吞掉，会跳过后面的录音步骤，
       连带把 O10/O11 打红（是探针断了，不是功能坏了） */
    var nc = q('#noteScreen [data-close]'); if (nc) nc.click();
    /* 录音 → 语音结束 → 三步引导 */
    p.audiosBefore=Y.state.audios.length; p.notesBefore=Y.state.notes.length;
    q('#recordBtn').click();
  }catch(e){ p.throwAt=String(e.message); }
  setTimeout(function(){ try{ Y.handleVoiceText('小语结束'); }catch(e){ p.errStop=String(e.message); }
    /* P0-G #6 之后录音中「结束」要二次确认：不补这一步，后面四步引导会整体后移一格 */
    try{ Y.handleVoiceText('是'); }catch(e){ p.errConfirm=String(e.message); } },300);
  setTimeout(function(){ try{ p.step1=dlg(); var b=qa('#dlgActions .btn'); if(b[0]) b[0].click(); }catch(e){ p.err1=String(e.message); } },800);
  setTimeout(function(){ try{ p.step2=dlg(); var b=qa('#dlgActions .btn'); if(b[0]) b[0].click(); }catch(e){ p.err2=String(e.message); } },1300);
  setTimeout(function(){
    try{
      p.step3=dlg();                                  /* ③ 笔记放到哪个类目 */
      p.audios=Y.state.audios.length; p.notes=Y.state.notes.length;
      var b=qa('#dlgActions .btn'); if(b[0]) b[0].click();   /* 与原音频同类目 */
    }catch(e){ p.err3=String(e.message); }
    setTimeout(function(){
      try{
        p.step4=dlg();                                /* ④ 要导出到本地吗 */
        p.firstNoteGroup=Y.state.notes[0]?Y.state.notes[0].group:null;
        p.firstAudioSize=Y.state.audios[0]?Y.state.audios[0].size:null;
        var b=qa('#dlgActions .btn'); if(b.length) b[b.length-1].click();  /* 先不导出 */
      }catch(e){ p.err4=String(e.message); }
      /* O7/O9 在四步之后取：页面已不再预置假数据，四步跑完才真有一条笔记。
         若此时仍无笔记（例如 ② 选了"不用"），字段留空、由断言报出来 —— 不静默跳过。 */
      try{
        var rb2=q('#noteList [data-act="read"]'); p.readBtnLabel2=rb2?rb2.textContent.trim():'';
        var eb2=q('#noteList [data-act="export"]'); if(eb2) eb2.click();
        p.exportChooser2=dlg();
        var bx=qa("#dlgActions .btn"); if(bx.length) bx[bx.length-1].click();
      }catch(e){ p.errO79=String(e.message); }
      var pre=document.createElement('pre');pre.id='probe-json';pre.textContent=JSON.stringify(p,null,1);
      document.body.appendChild(pre);
    }, 900);
  },2600);
});
</script>
'@

# ================================================================ 执行
Write-Host '=========== 场景 1：正常路径（A/B/C/D/E/G/H） ==========='
$r1 = Invoke-Scenario -Stub $stubCommon -Probe $probe1 -Budget 9000

$s1ids = @('A1','A2','A3','A4','A5','A6','B1','B2','B3','B4','B5','C1','C2','C3','C4','C5','C6',
            'D1','D2','D3','D4','D5','E1','E2','E3','E4','E5','G1','G2','G3','G4','G5','G6',
            'H1','H2','H3','H4','H5','H6')
if ($r1 -and $r1.hasYuyi) {
  # --- A 振动节奏 ---
  $eg = @($r1.consts.group) -join ','
  Check 'A1' '单组节奏 = [200,100,600,150,200]' ($eg -eq '200,100,600,150,200') $eg
  Check 'A2' '共 3 组 / 组间隔 2000ms' (($r1.consts.groups -eq 3) -and ($r1.consts.gap -eq 2000)) ("groups=$($r1.consts.groups) gap=$($r1.consts.gap)")
  Check 'A3' '单组时长 = 1250ms' ($r1.consts.groupMs -eq 1250) $r1.consts.groupMs
  $rhythm = @($r1.s1.vibrateCalls | Where-Object { $_ -eq '200,100,600,150,200' })
  Check 'A4' '触发时真实发出三段式节奏' ($rhythm.Count -ge 1) ($r1.s1.vibrateCalls -join ' | ')
  $d = @($r1.s1.delays) -join ','
  Check 'A5' '组间重排定时器 = 3250ms（1250+2000）' ($d -match 'T3250') $d
  Check 'A6' 'TTS 在第一组振动结束后启动（延迟 1250ms）' ($d -match 'T1250') $d

  # --- B 提醒方式二选一 ---
  Check 'B1' '「震动/振动」→ vibrate' (($r1.mode[0] -eq 'vibrate') -and ($r1.mode[1] -eq 'vibrate')) ($r1.mode -join ',')
  Check 'B2' '「闹钟/声音」→ ring' (($r1.mode[2] -eq 'ring') -and ($r1.mode[3] -eq 'ring')) ($r1.mode -join ',')
  Check 'B3' '无法识别 → null' ($r1.mode[4] -eq $null) ($r1.mode -join ',')
  Check 'B4' '助手新增 知道了 / 延后十分钟 指令 chip' ($r1.reg.chipAck -and $r1.reg.chipSnooze) "ack=$($r1.reg.chipAck) snooze=$($r1.reg.chipSnooze)"
  Check 'B5' '契约 §4 新增 DOM id 齐全（缺失列表为空）' ((@($r1.reg.ids) | Where-Object { $_ }).Count -eq 0) (@($r1.reg.ids) -join ',')

  # --- C 触发顺序与通知参数 ---
  $sv = [array]::IndexOf(@($r1.s1b.seq), (@($r1.s1b.seq) | Where-Object { $_ -like 'vibrate:200/100/600/150/200*' } | Select-Object -First 1))
  $sn = [array]::IndexOf(@($r1.s1b.seq), (@($r1.s1b.seq) | Where-Object { $_ -like 'notify:*' } | Select-Object -First 1))
  $st = [array]::IndexOf(@($r1.s1b.seq), (@($r1.s1b.seq) | Where-Object { $_ -like 'tts:*' } | Select-Object -First 1))
  Check 'C1' '顺序：振动 → 通知 → TTS' (($sv -ge 0) -and ($sn -gt $sv) -and ($st -gt $sn)) "vibrate@$sv notify@$sn tts@$st"
  $opts = @($r1.s1.notifOpts)[0]
  Check 'C2' '通知标题 = 待办提醒' ($r1.s1.title -eq '待办提醒') $r1.s1.title
  Check 'C3' '通知 requireInteraction = true（常驻）' ($opts.requireInteraction -eq $true) "requireInteraction=$($opts.requireInteraction)"
  Check 'C4' '通知 tag 以 yuyi-todo- 开头（同一待办可复用）' ([string]$opts.tag -like 'yuyi-todo-*') $opts.tag
  Check 'C5' '通知正文 = 待办全文' ($opts.body -eq '验收：交作业') $opts.body
  $ttsN = @($r1.s1b.tts).Count
  $ttsR = if ($ttsN) { [double](@($r1.s1b.tts)[0])[1] } else { -1 }
  Check 'C6' 'TTS 慢速重复 2 遍（rate≈0.85）' (($ttsN -eq 2) -and ([math]::Abs($ttsR - 0.85) -lt 0.01)) "count=$ttsN rate=$ttsR"

  # --- D 应答 ---
  Check 'D1' '知道了：立即停止振动（末次调用为 0）' ($r1.s2.vibrateLast -eq '0') $r1.s2.vibrateLast
  Check 'D2' '知道了：标记为已提醒' ($r1.s2.reminded -eq $true) $r1.s2.reminded
  Check 'D3' '知道了：关闭弹窗 / 关闭通知 / 回到待机' (($r1.s2.dlgOpen -eq $false) -and ($r1.s2.notifLive -eq 0) -and ($r1.s2.active -eq $null)) "dlg=$($r1.s2.dlgOpen) live=$($r1.s2.notifLive) active=$($r1.s2.active)"
  Check 'D4' '延后十分钟：snooze 自增 / 取消已提醒 / 顺延 600s / 重新进入调度' `
        (($r1.s4.snooze -eq 1) -and ($r1.s4.reminded -eq $false) -and ([math]::Abs($r1.s4.atDeltaSec - 600) -le 5) -and ($r1.s4.next -eq 'v2')) `
        "snooze=$($r1.s4.snooze) reminded=$($r1.s4.reminded) delta=$($r1.s4.atDeltaSec) next=$($r1.s4.next)"
  Check 'D5' '延后后弹窗已关闭' ($r1.s4.dlgOpen -eq $false) $r1.s4.dlgOpen

  # --- E 保活四层 ---
  Check 'E1' '阈值：60s 校验 / 90s 心跳 / 30s 唤醒锁' `
        (($r1.consts.hidden -eq 60000) -and ($r1.consts.heartbeat -eq 90000) -and ($r1.consts.wakelead -eq 30000)) `
        "hidden=$($r1.consts.hidden) hb=$($r1.consts.heartbeat) wl=$($r1.consts.wakelead)"
  Check 'E2' '隐藏态装/卸 60s 校验 + 90s 心跳定时器' `
        ($r1.watch.hidden -and $r1.watch.heartbeat -and $r1.watchCleared.hidden -and $r1.watchCleared.heartbeat) `
        "on=$($r1.watch.hidden)/$($r1.watch.heartbeat) off=$($r1.watchCleared.hidden)/$($r1.watchCleared.heartbeat)"
  Check 'E3' '心跳与校验的实际 delay 值出现 60000 / 90000' (($d -match 'I60000') -and ($d -match 'I90000')) $d
  $seqAll = @($r1.s1b.seq) -join ' | '
  Check 'E4' '触发前申请唤醒锁（wakeLock.request screen）' ($seqAll -match 'wakelock-request:screen') $seqAll
  $seqAck = @($r1.s2b.seqAfterAck) -join ' | '
  Check 'E5' '提醒结束立即释放唤醒锁' ($seqAck -match 'wakelock-release') $seqAck

  # --- G 无障碍 ---
  Check 'G1' '提醒弹窗 role=alertdialog + aria-modal' (($r1.a11y.role -eq 'alertdialog') -and ($r1.a11y.ariaModal -eq 'true')) "role=$($r1.a11y.role) modal=$($r1.a11y.ariaModal)"
  Check 'G2' '新增控件 aria-label 齐全（缺失列表为空）' ((@($r1.a11y.labels) | Where-Object { $_ }).Count -eq 0) (@($r1.a11y.labels) -join ',')
  Check 'G3' '待办条目朗读串含「震动提醒模式」+「待办内容」' `
        (($r1.aria[0] -like '*震动提醒模式*待办内容*') -and ($r1.aria[1] -like '*无提醒*待办内容*')) ($r1.aria -join ' / ')
  Check 'G4' '提醒弹窗打开后焦点进入 知道了 按钮' ($r1.s1.focusId -eq 'remindAckBtn') $r1.s1.focusId
  Check 'G5' '关闭后焦点归还（延后 250ms 观测，浏览器焦点修正异步）' ($r1.s2b.insideDialog -eq $false) "insideDialog=$($r1.s2b.insideDialog) focus=$($r1.s2b.focusTag)#$($r1.s2b.focusId)"
  Check 'G6' '两个操作按钮高度 ≥48dp（offsetHeight）' (($r1.s1.ackOffsetH -ge 48) -and ($r1.s1.snzOffsetH -ge 48)) "ack=$($r1.s1.ackOffsetH) snooze=$($r1.s1.snzOffsetH)"

  # --- H 回归 ---
  /* 原来断言"待办列表仍有 3 条（既有演示数据未被破坏）"。
       用户已要求删净演示数据 → 空态下合法值是 0。
       改成**一致性断言**：列表条数 == state.todos.length（空态 0/0 通过，有数据也必须一致）。
       这不是放宽：从"等于魔数 3"变成"与真实状态一致"，语义更准，也不会因产品数据变化而假红。 */
  Check 'H1' '待办列表条数与 state.todos 一致（空态 0/0 也算通过）' ($r1.reg.todoItems -eq $r1.todoCount) "列表=$($r1.reg.todoItems) state=$($r1.todoCount)"
  Check 'H2' '通用二次确认弹窗与会话浮层仍在' ($r1.reg.confirmDlg -and $r1.reg.assistant) "confirm=$($r1.reg.confirmDlg) assistant=$($r1.reg.assistant)"
  Check 'H3' '待办以外四个面板仍在' ($r1.reg.audioPanel -and $r1.reg.notesPanel -and $r1.reg.dirPanel -and $r1.reg.exportsPanel) `
        "audio=$($r1.reg.audioPanel) notes=$($r1.reg.notesPanel) dir=$($r1.reg.dirPanel) exports=$($r1.reg.exportsPanel)"
  Check 'H4' '旧免责声明已替换为安卓振动提醒能力卡' ($r1.reg.banner -like '*安卓振动提醒*') $r1.reg.banner.Substring(0,[Math]::Min(40,$r1.reg.banner.Length))
  Check 'H5' '业务指令 chip 数量 ≥15（新增 2 个）' ($r1.reg.chips -ge 15) $r1.reg.chips
  Check 'H6' '全程无 JS 运行时错误' ($r1.errs -eq 0) $r1.errs
} else {
  # 改造前的基线页面不会暴露 window.__yuyi —— 逐项记为 FAIL，用于证明探针具备鉴别力
  foreach ($id in $s1ids) { Check $id '场景1：页面未暴露 window.__yuyi（改造前基线必然如此）' $false 'no __yuyi' }
}

Write-Host '=========== 场景 2：不支持振动 API + 通知权限被拒（F1/F2） ==========='
$r2 = Invoke-Scenario -Stub $stub2 -Probe $probe2 -Budget 8000
if ($r2 -and $r2.hasYuyi) {
  Check 'F1a' '探测到不支持振动 API' ($r2.vibSupported -eq $false) $r2.vibSupported
  Check 'F1b' '试振按钮隐藏 / 振动开关禁用' ($r2.vibTestHidden -and $r2.vibSwitchDisabled) "hidden=$($r2.vibTestHidden) disabled=$($r2.vibSwitchDisabled)"
  Check 'F1c' '状态文案说明已降级' ($r2.vibState -like '*不支持振动*') $r2.vibState
  Check 'F1d' '该待办自动降级为铃声（mode=ring）' ($r2.fired.modeAfter -eq 'ring') $r2.fired.modeAfter
  $ch = "$($r2.fired.srStatus)|$($r2.fired.srAlert)|$($r2.fired.toast)"
  Check 'F1e' '播报「当前浏览器不支持震动，已切换为声音提醒」（任一无障碍/提示通道）' ($ch -like '*当前浏览器不支持震动，已切换为声音提醒*') $ch
  Check 'F2a' '通知权限被拒时待办仍保留' ($r2.fired.stillInList -eq 1) $r2.fired.stillInList
  Check 'F2b' '权限被拒时不发通知' (($r2.fired.notifCalls -eq 0) -and ($r2.fired.notifLive -eq 0)) "calls=$($r2.fired.notifCalls) live=$($r2.fired.notifLive)"
  Check 'F2c' '权限被拒时前台弹窗仍触发（不阻塞）' ($r2.fired.dlgOpen -eq $true) $r2.fired.dlgOpen
  Check 'F2d' '播报「未获得通知权限…建议在设置中开启」' ($r2.fired.srAlert -like '*未获得通知权限*建议在设置中开启*') $r2.fired.srAlert
  Check 'F6' '无 JS 运行时错误' ($r2.errs -eq 0) $r2.errs
} else {
  foreach ($id in @('F1a','F1b','F1c','F1d','F1e','F2a','F2b','F2c','F2d','F6')) {
    Check $id '场景2：页面未暴露 window.__yuyi（改造前基线必然如此）' $false 'no __yuyi' }
}

Write-Host '=========== 场景 3：过期待办汇总 + 后台延迟 + 多条串行（F3/F4/F5） ==========='
$r3 = Invoke-Scenario -Stub $stubCommon -Probe $probe3 -Budget 9000
if ($r3 -and $r3.hasYuyi) {
  Check 'F3a' '过期待办按时间升序识别' (($r3.overdueCount -eq 2) -and ((@($r3.overdueOrder) -join ',') -eq 'o1,o2')) "n=$($r3.overdueCount) order=$(@($r3.overdueOrder) -join ',')"
  Check 'F3b' '汇总播报「您有X条已过期的待办提醒，分别是…」' ($r3.srAlertSummary -like '您有2条已过期的待办提醒，分别是：*') $r3.srAlertSummary
  Check 'F3c' '汇总用 alert/assertive 通道' (($r3.srAlertRole -eq 'alert') -and ($r3.srAlertLive -eq 'assertive')) "role=$($r3.srAlertRole) live=$($r3.srAlertLive)"
  Check 'F4a' '后台挂起延迟被识别（overdue=true）' ($r3.first.overdue -eq $true) $r3.first.overdue
  Check 'F4b' '弹窗说明「后台挂起导致延迟，原定提醒时间」' ($r3.first.meta -like '*后台挂起导致延迟*原定提醒时间*') $r3.first.meta
  Check 'F4c' '通知正文附带原定提醒时间' ((@($r3.first.notifBodies) -join '|') -like '*原定提醒时间*') (@($r3.first.notifBodies) -join '|')
  Check 'F4d' 'TTS 播报附带原定提醒时间（不静默修正）' ((@($r3.first.ttsTexts) -join '|') -like '*原定提醒时间*') (@($r3.first.ttsTexts) -join '|')
  Check 'F5a' '多条同时到点：同一时刻只有一个在提醒（不叠加）' ($r3.first.active -eq 'o1') $r3.first.active
  Check 'F5b' '处理完第一条后才轮到第二条' (($r3.mid.active -eq $null) -and ($r3.mid.o1reminded -eq $true) -and ($r3.second.active -eq 'o2')) `
        "mid=$($r3.mid.active) o1reminded=$($r3.mid.o1reminded) second=$($r3.second.active)"
  Check 'F5c' '静音/勿扰：只发标准振动请求，不伪造系统静音检测' ($r3.muteSystemHint -eq $false) $r3.muteSystemHint
  Check 'F7' '麦克风权限不足分支已实现（checkMicPermission）' ($r3.micFn -eq 'function') $r3.micFn
  Check 'F8' '无 JS 运行时错误' ($r3.errs -eq 0) $r3.errs
} else {
  foreach ($id in @('F3a','F3b','F3c','F4a','F4b','F4c','F4d','F5a','F5b','F5c','F7','F8')) {
    Check $id '场景3：页面未暴露 window.__yuyi（改造前基线必然如此）' $false 'no __yuyi' }
}

Write-Host '=========== 场景 4：手机端系统通知走 Service Worker（M1/M2/M3） ==========='
$r4 = Invoke-Scenario -Stub $stubSW -Probe $probe4 -Budget 8000
if ($r4 -and $r4.hasYuyi) {
  $show = @($r4.showCalls)
  Check 'M1' '页面注册了 Service Worker（手机端通知的前提）' (($r4.registerCalls -ge 1) -and $r4.swRegSet) "register=$($r4.registerCalls) swReg=$($r4.swRegSet)"
  Check 'M2' '走 registration.showNotification（而非 new Notification）' (($show.Count -ge 1) -and ($r4.desktopNotifyCalls -eq 0)) "show=$($show.Count) desktop=$($r4.desktopNotifyCalls)"
  if ($show.Count -ge 1) {
    $c = @($show)[0]
    Check 'M3' 'SW 通知参数正确（标题 待办提醒 / 正文全文 / tag / requireInteraction）' `
          (($c[0] -eq '待办提醒') -and ($c[1] -eq '验收：手机端通知') -and ([string]$c[2] -like 'yuyi-todo-*') -and ($c[3] -eq $true)) `
          "title=$($c[0]) body=$($c[1]) tag=$($c[2]) require=$($c[3])"
  } else { Check 'M3' 'SW 通知参数正确' $false '未调用 showNotification' }
  Check 'M4' '应答后通过 getNotifications 关闭 SW 通知' (($r4.closeCalls -ge 1) -and ($r4.notifLiveAfterAck -eq 0)) "close=$($r4.closeCalls) live=$($r4.notifLiveAfterAck)"
  Check 'M5' '无 JS 运行时错误' ($r4.errs -eq 0) $r4.errs
} else {
  foreach ($id in @('M1','M2','M3','M4','M5')) {
    Check $id '场景4：页面未暴露 window.__yuyi' $false 'no __yuyi' }
}

Write-Host '=========== 场景 5：静态资源与文案（N1–N5，不开浏览器） ==========='
$dir = Split-Path -Parent $Page                                # yuyi-preview/
$swPath = Join-Path $dir 'sw.js'
$srvPath = Join-Path $dir '_tools\serve-mobile.py'
$batPath = Join-Path $dir '手机预览.bat'
$htmlText = Get-Content -LiteralPath $Page -Raw -Encoding UTF8

if (Test-Path -LiteralPath $swPath) {
  $sw = Get-Content -LiteralPath $swPath -Raw -Encoding UTF8
  Check 'N1' 'sw.js 存在且处理 notificationclick / 立即接管' `
        (($sw -match 'notificationclick') -and ($sw -match 'skipWaiting') -and ($sw -match 'clients\.claim')) 'ok'
} else { Check 'N1' 'sw.js 存在' $false 'missing' }

Check 'N2' '手机预览服务器脚本存在' (Test-Path -LiteralPath $srvPath) $srvPath
Check 'N3' 'UI 文案不再承诺「静音/勿扰下仍会振动」（MDN 明确取决于设备设置）' `
      (-not ($htmlText -match '静音/勿扰下仍会振动')) 'ok'
Check 'N4' 'UI 给出 https + 先点一下页面的使用前提' `
      (($htmlText -match 'https') -and ($htmlText -match '先点一下页面')) 'ok'
Check 'N5' '页面暴露「是否已交互」探测（振动激活引导）' ($htmlText -match 'vibrationArmed') 'ok'
if (Test-Path -LiteralPath $batPath) {
  $bb = [System.IO.File]::ReadAllBytes($batPath)
  $lf = 0; $crlf = 0
  for ($i = 0; $i -lt $bb.Length; $i++) {
    if ($bb[$i] -eq 10) { if ($i -gt 0 -and $bb[$i-1] -eq 13) { $crlf++ } else { $lf++ } }
  }
  Check 'N6' '手机预览.bat 全部 CRLF（LF 会让 goto/for 块解析出错）' ($lf -eq 0 -and $crlf -gt 0) "crlf=$crlf lf=$lf"
} else { Check 'N6' '手机预览.bat 存在' $false 'missing' }

# 既有探针 verify-newflows.ps1 用 `#todoPanel .banner` 读「安卓振动提醒」能力卡文案，
# 所以新增的激活提示条**不能**复用 .banner 类，否则会把那条选择器抢走（实测踩过：H4 变红）。
Check 'N7' '能力卡仍带 .banner 类（既有探针依赖该选择器）' ($htmlText -match 'class="banner vib-card" id="vibPanelCard"') 'ok'
Check 'N8' '振动激活提示条未占用 .banner 类名' `
      ((-not ($htmlText -match 'class="banner"[^>]*id="armCard"')) -and (-not ($htmlText -match 'id="armCard"[^>]*class="banner"'))) 'ok'

Write-Host '=========== 场景 6：真机反馈的 8 条改动（O1–O10） ==========='
$r6 = Invoke-Scenario -Stub '' -Probe $probe6 -Budget 12000
if ($r6 -and $r6.hasYuyi) {
  $v = @($r6.voice)
  Check 'O1' '语音：唤醒词与固定指令都能命中（含「小语结束」）' `
        (($v.Count -eq 9) -and ($v[0] -eq $true) -and ($v[1] -eq $true) -and ($v[2] -eq $true) -and
         ($v[3] -eq $true) -and ($v[4] -eq $true) -and ($v[5] -eq $true) -and ($v[6] -eq $true) -and ($v[7] -eq $true)) `
        ($v -join ',')
  Check 'O2' '语音：听不懂时明确返回 false（不装懂）' ($v[8] -eq $false) $v[8]
  Check 'O3' '语音药丸不再假装"正在监听"（未开启显示可点开启）' `
        (($r6.wakeState -eq 'off') -and ($r6.wakeText -like '*开启语音唤醒*')) "$($r6.wakeState) / $($r6.wakeText)"
  Check 'O4' '语音药丸可点区域 ≥44px（原来 35px）' ($r6.wakeH -ge 44) $r6.wakeH
  Check 'O5' '手机端布局：外框高度 = 可见视口，页面本身不滚' `
        (($r6.frameH -eq $r6.winH) -and ($r6.docOverflow -eq 'hidden')) "frame=$($r6.frameH) win=$($r6.winH) overflow=$($r6.docOverflow)"
  Check 'O6' '手机端布局：底部 Tab 贴住视口底边' ($r6.tabBottom -eq $r6.winH) "tabBottom=$($r6.tabBottom) win=$($r6.winH)"
  Check 'O7' '朗读：按钮存在 + 设备支持语音播报（在四步之后取，此时已有真实笔记）' (($r6.readBtnLabel2 -like '*朗读*') -and ($r6.ttsOk -eq $true)) "$($r6.readBtnLabel2) tts=$($r6.ttsOk)"
  Check 'O8' '笔记入口 = 全屏笔记页（不再是弹窗）：两个入口落点一致 + 分段控件有且仅有一个选中' `
        (($r6.notePage.open -eq $true) -and ($r6.notePage.dlgOpen -eq $false) -and
         ($r6.notePage.tabs -eq 2) -and ($r6.notePage.selected -eq 1) -and
         ($r6.notePageViaTab.open -eq $true) -and ($r6.notePageViaTab.tabs -eq 2) -and ($r6.notePageViaTab.selected -eq 1)) `
        "侧边栏: open=$($r6.notePage.open) tabs=$($r6.notePage.tabs) selected=$($r6.notePage.selected) 弹窗=$($r6.notePage.dlgOpen) ｜ 底部Tab: open=$($r6.notePageViaTab.open) tabs=$($r6.notePageViaTab.tabs) selected=$($r6.notePageViaTab.selected)"
  Check 'O9' '导出先选格式：中文 Word / 中文盲文 Word / 盲文 BRF' `
        (($r6.exportChooser2.title -like '*导出格式*') -and ($r6.exportChooser2.buttons -like '*中文 Word*') -and
         ($r6.exportChooser2.buttons -like '*中文盲文 Word*') -and ($r6.exportChooser2.buttons -like '*盲文 BRF*')) `
        "$($r6.exportChooser2.title) => $($r6.exportChooser2.buttons)"
  Check 'O10' '录音结束四步引导：① 音频归类 → ② 是否做 AI 笔记总结 → ③ 笔记归类 → ④ 是否导出（条数断言改成增量 +1）' `
        (($r6.step1.title -like '*①*哪个大类*') -and ($r6.step2.title -like '*②*AI 笔记总结*') -and
         ($r6.step3.title -like '*③*笔记*哪个类目*') -and ($r6.step4.title -like '*④*导出*') -and
         ($r6.step4.buttons -like '*中文 Word*') -and ($r6.step4.buttons -like '*中文盲文 Word*') -and
         ($r6.step4.buttons -like '*盲文 BRF*') -and (($r6.audios - $r6.audiosBefore) -eq 1) -and (($r6.notes - $r6.notesBefore) -eq 1)) `
        "$($r6.step1.title) / $($r6.step2.title) / $($r6.step3.title) / $($r6.step4.title) / audios=$($r6.audios) notes=$($r6.notes)"
  Check 'O11' '④ 导出里带「AI 笔记总结」说明（转写 + 总结两件事都讲清）' `
        (($r6.step2.buttons -like '*做 AI 笔记总结*') -and ($r6.step2.buttons -like '*先看看这段原音频*')) $r6.step2.buttons
} else {
  foreach ($id in @('O1','O2','O3','O4','O5','O6','O7','O8','O9','O10')) {
    Check $id '场景6：页面未暴露 window.__yuyi' $false 'no __yuyi' }
}

# ================================================================ 汇总
Write-Host ''
$script:lines | ForEach-Object { Write-Host $_ }
Write-Host ''
Write-Host ('========================= 汇总：PASS {0} / FAIL {1} =========================' -f $script:pass, $script:fail)
if ($script:fail -gt 0) { Write-Host '结论：未达标'; exit 1 }
Write-Host '结论：全部通过'
exit 0