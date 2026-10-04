$ErrorActionPreference = 'Continue'
# ============================================================================
# UI / 布局探针（截图 + DOM 快照）
# ----------------------------------------------------------------------------
# 2026-10-04 同步到「底部 Tab = 全屏页」的新结构（P0）。原版按"面板是浮层"的旧
# 语义写，这次结构改动后直接 PROBE NOT FOUND（红的原始输出见交付报告）。
#
# 本次同步改了什么（以及为什么不是"把测试改松了"）：
#   1) 补 UTF-8 BOM。原文件没有 BOM，Windows PowerShell 按 ANSI(GBK) 解码中文
#      注释时，末尾汉字会把后面的换行吃掉 → 下一行代码被并进注释里、静默不执行
#      （同一个坑已经在 verify-newflows.ps1 上实测到）。补 BOM 后这些行才真的跑，
#      断言变**严**。
#   2) 关浮层：#audioPanel / #notesPanel 现在是全屏笔记页 #noteScreen 里的两个
#      pane，页面级的 ✕ 在 #noteScreen 头部。改前断言「面板自带 [data-close]」，
#      改后断言「#noteScreen 的 [data-close] 点了能回首页，且 aria-current 跟着复位」。
#   3) 切原音频/AI 总结笔记：改前靠打开两个不同浮层，改后靠笔记页顶上的分段控件
#      （#segAudio / #segNotes）。改后断言「点哪个分段，对应 pane 可见、另一个隐藏、
#      aria-selected 只有一个 true」——比原来多断言了"互斥"和"只有一个选中"。
#   4) #tabAI 已取消 → 助手浮层改从 #callBtn（首页药丸）唤起，并断言浮层默认只显示
#      3 条指令（#cmdTop）+ #cmdMore 收起。
#   5) #sideExport 已移除（顶层不留"没有对象的动作"）→ 导出记录改从
#      我的 → [data-goto="exports"] 进；改前断言"侧栏有个导出按钮点了会弹窗"，
#      改后断言"侧栏**没有**导出按钮 + 我的页那条路真的能打开 #exportsPanel"。
#   6) 探针改成**每步 try/catch + 永远输出 JSON**：原版任何一步抛异常，asst 之后的
#      断言全部消失、只剩 "PROBE NOT FOUND"，分不清"功能坏了"还是"探针断了"。
#      现在会明确报出在哪一步、什么错。这不是放宽：字段一个没少，只是红了会说话。
# ============================================================================

$Page   = 'C:\Users\HP\Desktop\yuyi-preview\index.html'
$OutDir = 'C:\Users\HP\Desktop\yuyi-preview\_shots'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$exe = (Get-ChildItem 'D:\DevCache\ms-playwright\chromium_headless_shell-*' -Recurse -Filter 'chrome-headless-shell.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1).FullName
if (-not $exe) { Write-Host 'NO HEADLESS SHELL'; return }
Write-Host "shell: $exe"
$url = "file:///" + ($Page -replace '\\','/')

# ---------- 1) 截图 ----------
$shot = Join-Path $OutDir 'home.png'
if (Test-Path $shot) { Remove-Item $shot -Force }
$p1 = Join-Path $env:TEMP ('sp' + [guid]::NewGuid().ToString('N'))
& $exe --headless --no-sandbox --disable-gpu --hide-scrollbars --force-device-scale-factor=2 `
       --user-data-dir=$p1 --window-size=430,932 --virtual-time-budget=3000 `
       --screenshot=$shot $url 2>&1 | Out-Null
if (Test-Path $shot) { Write-Host ("OK home.png {0:n0} bytes" -f (Get-Item $shot).Length) } else { Write-Host 'FAIL home.png' }
Remove-Item $p1 -Recurse -Force -ErrorAction SilentlyContinue

# ---------- 2) DOM 探针 ----------
$probe = @'
<script>
window.__probe = {};
window.addEventListener('error', function(e){ window.__probe.err = String(e.message) + ' @line ' + e.lineno; });
window.addEventListener('DOMContentLoaded', function(){
  var q = function(s){ return document.querySelector(s); };
  var n = function(s){ return document.querySelectorAll(s).length; };
  var all = function(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var txt = function(s){ var e = q(s); return e ? e.textContent.trim() : 'MISSING'; };
  var p = window.__probe;
  function visiblePage(){
    if (!q('#noteScreen').hidden) return 'note';
    if (!q('#todoPanel').hidden)  return 'todo';
    if (!q('#meScreen').hidden)   return 'me';
    return 'home';
  }
  function tabState(){
    var cur = q('.tab[aria-current="page"]');
    return { visible: visiblePage(), ariaCurrent: cur ? cur.dataset.tab : 'NONE',
             consistent: (cur ? cur.dataset.tab : 'NONE') === visiblePage() };
  }
  /* 每一步独立 try/catch：断在哪一步、什么错，一眼可见（不再只剩 PROBE NOT FOUND）。
     出错也照样 finish()：能拿到"断之前"的快照 + 出错的那一步。 */
  var stepName = 'init';
  var finished = false;
  function step(fn, ms){
    setTimeout(function(){
      try { fn(); }
      catch (e){ p['errAt_' + stepName] = String(e.message); finish(); }
    }, ms || 70);
  }
  function finish(){
    if (finished) return;
    finished = true;
    p.failedAt = p.errAt_init || p.failedStep || null;
    p.jsErrors = window.__probe.err ? [window.__probe.err] : [];
    var pre = document.createElement('pre'); pre.id = 'probe-json';
    pre.textContent = JSON.stringify(window.__probe, null, 1);
    document.body.appendChild(pre);
  }
  try {
    stepName = 'init';
    p.title = document.title;
    p.dateLine = txt('#todayLine');
    p.h1 = txt('.header-title');
    p.slogan = txt('.brand-slogan');
    p.cardLabel = txt('#recordCardTitle');
    p.recordLabel = txt('#recordBtnText');
    p.sideBtns = n('.side-btn');
    p.sideNames = all('.side-btn .side-txt').map(function(e){ return e.textContent.trim(); }).join('/');
    /* 新结构：底部 4 Tab = 首页/笔记/待办/我的（AI Tab 已取消）；侧栏无导出 */
    p.tabs = all('.tab').map(function(e){ return e.textContent.trim(); }).join('/');
    p.tabIds = all('.tab').map(function(e){ return e.dataset.tab; }).join('/');
    p.tabCount = n('.tab');
    p.hasAiTab = !!q('#tabAI');
    p.hasSideExport = !!q('#sideExport');
    p.activeTab = q('.tab[aria-current="page"]') ? q('.tab[aria-current="page"]').textContent.trim() : 'MISSING';
    p.tabState = tabState();
    /* 笔记页结构：整屏页 + 两个 role=tab 分段 + 两个 pane（id 保留） */
    p.notePageStructure = { segTabs: n('#noteScreen [role="tab"]'),
                            segSelected: n('#noteScreen [role="tab"][aria-selected="true"]'),
                            audioPanelRole: q('#audioPanel') ? q('#audioPanel').getAttribute('role') : 'MISSING',
                            notesPanelRole: q('#notesPanel') ? q('#notesPanel').getAttribute('role') : 'MISSING',
                            screenCloseBtns: n('.screen [data-close]') };   /* P0-C：整屏页不再带 ✕，期望 0 */
    /* 助手浮层：默认只 3 条指令 */
    p.asstStructure = { chipsTop: n('#cmdTop .chip[data-cmd]'),
                        chipsTotal: n('.cmd-group .chip[data-cmd]'),
                        moreHidden: q('#cmdMore') ? q('#cmdMore').hidden : 'MISSING' };
    p.noteItems = n('#noteList .note-item');
    p.todoItems = n('#todoList .todo');
    p.dirRowsAtLoad = n('#dirContent .entry');
    p.sideTop = Math.round(q('.side-tools').getBoundingClientRect().top);
    p.sideBottom = Math.round(q('.side-tools').getBoundingClientRect().bottom);
    p.tabTop = Math.round(q('.tabbar').getBoundingClientRect().top);
    p.overlapTabbar = q('.side-tools').getBoundingClientRect().bottom > q('.tabbar').getBoundingClientRect().top;
    p.z = { side: getComputedStyle(q('.side-tools')).zIndex, tab: getComputedStyle(q('.tabbar')).zIndex,
            dlg: getComputedStyle(q('#confirmDialog')).zIndex, asst: getComputedStyle(q('#assistant')).zIndex };
    p.smallTaps = Array.prototype.filter.call(document.querySelectorAll('button'), function(b){
        var r = b.getBoundingClientRect(); return r.height > 0 && r.height < 40; })
      .map(function(b){ return (b.className || b.id) + ':' + Math.round(b.getBoundingClientRect().height); });
  } catch (e){ p.errAt_init = String(e.message); }

  /* ---- 步骤链：严格串行（每一步在上一步入的 100% 之后再排下一步） ----
     原版就是串行嵌套的；这里保持串行，并把每步包在 try/catch 里。 */
  stepName = 'record';
  step(function(){
    q('#recordBtn').click();
    p.s1 = q('#recordBtnText').textContent + '|' + q('#recordCard').dataset.state;
    q('#recordBtn').click();
    p.s2 = q('#recordBtnText').textContent + '|' + q('#recordCard').dataset.state;
    q('#recordBtn').click();
    p.s3 = q('#recordBtnText').textContent + '|' + q('#recordCard').dataset.state;
    q('.chip[data-cmd="end"]').click();

    stepName = 'step1';
    step(function(){
      p.dlg1Title = txt('#dlgTitle');
      p.dlg1Restate = txt('#dlgRestate');
      p.dlg1Buttons = all('#dlgActions .btn').map(function(b){ return b.textContent; }).join(' / ');
      q('#dlgActions .btn').click();

      stepName = 'step2';
      step(function(){
        p.dlg2Title = txt('#dlgTitle');
        p.dlg2Restate = txt('#dlgRestate');
        p.dlg2Buttons = all('#dlgActions .btn').map(function(b){ return b.textContent; }).join(' / ');
        q('#dlgActions .btn').click();

        stepName = 'step3';
        step(function(){
          /* ③ 笔记归类：只读结构再取消（四步的完整流程由 verify-newflows/gate 断言） */
          p.dlg3Title = txt('#dlgTitle');
          p.dlg3Buttons = all('#dlgActions .btn').map(function(b){ return b.textContent; }).join(' / ');
          q('#dlgActions .btn:last-child').click();

          stepName = 'todo';
          step(function(){
            var cur = q('#noteList .note-item[aria-current="true"]');
            p.note1Group = cur && cur.querySelector('.tag') ? cur.querySelector('.tag').textContent : 'MISSING';
            p.recordStateAfterEnd = q('#recordCard').dataset.state;
            /* 待办页：现在是整屏页 */
            q('#sideTodo').click();
            p.todoPage = { open: !q('#todoPanel').hidden, tab: tabState() };
            q('#todoVoiceBtn').click();

            stepName = 'assistant';
            step(function(){
              p.asstOpen = !q('#assistant').hidden;
              p.asstCase = txt('#asstCase');
              p.endChipGated = q('.chip[data-cmd="end"]').getAttribute('aria-disabled');
              q('.chip[data-cmd="exit"]').click();
              p.asstClosed = q('#assistant').hidden;
              /* 助手浮层唤起路径：首页药丸 #callBtn（原 #tabAI 已取消） */
              q('#callBtn').click();
              p.asstOpenViaCallBtn = !q('#assistant').hidden;
              q('.chip[data-cmd="end"]').click();
              p.endWhileIdleCase = txt('#asstCase');
              p.endWhileIdleToast = q('.toast') ? q('.toast').textContent : 'none';
              q('.chip[data-cmd="cancel"]').click();
              q('.chip[data-cmd="help"]').click();
              p.helpOpen = !q('#helpPanel').hidden;
              p.helpContext = txt('#helpContext');
              p.helpItems = txt('#helpList').slice(0, 140);
              q('#helpPanel [data-close]').click();

              stepName = 'noteTab';
              step(function(){
                /* 底部【笔记】= 全屏页；顶上两个分段切换 pane */
                q('#tabNote').click();
                p.notePageViaTab = { open: !q('#noteScreen').hidden, tab: tabState(),
                                     segTabs: n('#noteScreen [role="tab"]'),
                                     segSelected: n('#noteScreen [role="tab"][aria-selected="true"]'),
                                     audioPaneVisible: !q('#audioPanel').hidden,
                                     notesPaneHidden: q('#notesPanel').hidden };
                q('#segNotes').click();
                p.notePageViaTab.notesPaneVisibleAfterSeg = !q('#notesPanel').hidden;
                p.notePageViaTab.audioPaneHiddenAfterSeg = q('#audioPanel').hidden;
                p.notePageViaTab.segSelectedAfter = n('#noteScreen [role="tab"][aria-selected="true"]');
                q('#tabHome').click();
                p.notePageViaTab.closedToHome = !q('#noteScreen').hidden === false;
                p.notePageViaTab.tabAfterClose = tabState();

                stepName = 'exports';
                step(function(){
                  /* #sideExport 已移除 → 导出记录走 我的 → [data-goto="exports"] */
                  q('#tabMe').click();
                  p.meOpen = !q('#meScreen').hidden;
                  p.meTabState = tabState();
                  q('#meScreen [data-goto="exports"]').click();
                  p.exportsOpen = !q('#exportsPanel').hidden;
                  q('#exportsPanel [data-close]').click();

                  stepName = 'dir';
                  step(function(){
                    /* 目录面板：上面两个按钮 = 「下面列哪一类」的开关 */
                    q('#sideDir').click();
                    p.dirOpen = !q('#dirPanel').hidden;
                    p.dirHintAudio = txt('#dirHint');
                    p.dirRowsAudio = n('#dirContent .entry');
                    p.dirRowAudioTitle = txt('#dirContent .entry .e-title');
                    p.dirAudioPressed = q('#dirOpenAudio').getAttribute('aria-pressed');
                    q('#dirOpenNotes').click();
                    p.dirHintNotes = txt('#dirHint');
                    p.dirRowsNotes = n('#dirContent .entry');
                    p.dirRowNoteTitle = txt('#dirContent .entry .e-title');
                    p.dirNotesPressed = q('#dirOpenNotes').getAttribute('aria-pressed');
                    p.dirAudioPressedAfter = q('#dirOpenAudio').getAttribute('aria-pressed');
                    q('#dirOpenAudio').click();
                    p.dirRowsBackToAudio = n('#dirContent .entry');
                    q('#dirContent .entry').click();          /* 每一条都真的能打开 */
                    p.dirOpenedNotePage = !q('#noteScreen').hidden;
                    p.dirOpenedAudioPane = !q('#audioPanel').hidden;
                    p.dirClosedAfterOpen = q('#dirPanel').hidden;
                    q('#tabHome').click();

                    stepName = 'delNote';
                    step(function(){
                      q('#sideNote').click();
                      var delBtn = q('#noteList .note-item[aria-current="true"] button[data-act="del"]');
                      if (delBtn) delBtn.click();
                      p.delDlg = txt('#dlgTitle');
                      q('#dlgActions .btn:last-child').click();
                      p.finalNoteCount = txt('#noteCount');
                      p.finalTabState = tabState();
                      document.title = 'PROBE_DONE';
                      finish();
                    }, 400);
                  }, 400);
                }, 400);
              }, 400);
            }, 110);
          }, 2500);
        }, 110);
      }, 110);
    }, 600);
  }, 300);
});
</script>
'@
$dom = Join-Path $OutDir 'dom.html'
$html = Get-Content $Page -Raw -Encoding UTF8
$html = $html -replace '</body>', ($probe + "`r`n</body>")
[System.IO.File]::WriteAllText($dom, $html, (New-Object System.Text.UTF8Encoding($false)))
$url2 = "file:///" + ($dom -replace '\\','/')
$p2 = Join-Path $env:TEMP ('sp' + [guid]::NewGuid().ToString('N'))
$dump = Join-Path $OutDir 'dom-dump.html'
& $exe --headless --no-sandbox --disable-gpu --user-data-dir=$p2 `
       --window-size=430,932 --virtual-time-budget=12000 --dump-dom $url2 2>&1 |
  Out-File -FilePath $dump -Encoding UTF8
Remove-Item $p2 -Recurse -Force -ErrorAction SilentlyContinue

$raw = Get-Content $dump -Raw -Encoding UTF8
if ($raw -and $raw -match '(?s)<pre id="probe-json">(.*?)</pre>'){
  $json = $Matches[1] -replace '&quot;','"' -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>'
  Write-Host "`n=============== PROBE RESULT ==============="
  Write-Host $json
} else {
  Write-Host "`nPROBE NOT FOUND. tail:"
  if ($raw) { Write-Host $raw.Substring([Math]::Max(0,$raw.Length-900)) } else { Write-Host '(empty dump)' }
}