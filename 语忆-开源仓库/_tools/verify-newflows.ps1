$ErrorActionPreference = 'Continue'
# ============================================================================
# 新流程探针（结构/流程快照）
# ----------------------------------------------------------------------------
# 2026-10-04 同步到「底部 Tab = 全屏页」的新结构（P0）。原版是按"面板是浮层"
# 的旧语义写的，这次结构改动后已经红了，红的原始输出见交付报告。
#
# 本次同步改了什么（以及为什么不是"把测试改松了"）：
#   1) 补 UTF-8 BOM。**这是能不能跑的前提**：文件原来没有 BOM，Windows
#      PowerShell 按 ANSI(GBK) 解码中文注释时，末尾汉字的第二个字节会把后面的
#      换行吃掉 → 下一行代码被并进 // 注释里、静默不执行。实测原版里
#      `q('#sideDir').click();` 就是这么被吃掉的（见 _shots/p-new.html:5592），
#      所以 dirOpen 一直是 false。补 BOM 后这些行才真的会跑 —— 断言变**严**了。
#   2) 关浮层的选择器：原 #audioPanel / #notesPanel 是浮层，各自带 [data-close]；
#      现在它们是全屏笔记页 #noteScreen 里的两个 pane，关页面的 ✕ 在
#      #noteScreen 的头部。改前断言「#audioPanel 里有 [data-close]」（在新结构下
#      必抛 null），改后断言「#noteScreen 里有 [data-close] 且点了能回首页」。
#   3) 切原音频/AI 总结笔记：原来靠打开两个不同的浮层；现在靠笔记页顶上的
#      分段控件（#segAudio / #segNotes，role=tab）。改后断言「点分段的哪一个，
#      对应 pane 可见、另一个隐藏、aria-selected 只有一个 true」。
#   4) #tabAI 已取消（底部只剩 4 个 Tab）。助手浮层改从 #callBtn（首页药丸）与
#      #fabCall（非首页悬浮按钮）唤起，两条路都断言。
#   5) #sideExport 已移除（顶层不留"没有对象的动作"）。导出记录改从
#      我的 → [data-goto="exports"] 进，断言这条路真的通。
#   6) **新增**结构断言：4 个 Tab 恰好是 首页/笔记/待办/我的 且没有 AI Tab；
#      aria-current="page" 必须等于"实际可见的整屏页"（P0 的验收条件）；
#      助手浮层默认只显示 3 条指令（P2#3）。这些都是原版没有的，属于加强。
# ============================================================================

$Page = 'C:\Users\HP\Desktop\yuyi-preview\index.html'
$OutDir = 'C:\Users\HP\Desktop\yuyi-preview\_shots'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$exe = (Get-ChildItem 'D:\DevCache\ms-playwright\chromium_headless_shell-*' -Recurse -Filter 'chrome-headless-shell.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1).FullName
if (-not $exe) { Write-Host 'NO SHELL'; return }

$probe = @'
<script>
window.__p = {};
window.addEventListener('error', function(e){ window.__p.err = String(e.message) + ' @line ' + e.lineno; });
window.addEventListener('DOMContentLoaded', function(){
  var q = function(s){ return document.querySelector(s); };
  var n = function(s){ return document.querySelectorAll(s).length; };
  var all = function(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var txt = function(s){ var e = q(s); return e ? e.textContent.trim() : 'MISSING'; };
  var p = window.__p;
  /* aria-current 与"实际可见的整屏页"必须一致 —— 这是 P0 的验收条件 */
  function visiblePage(){
    if (!q('#noteScreen').hidden) return 'note';
    if (!q('#todoPanel').hidden)  return 'todo';
    if (!q('#meScreen').hidden)   return 'me';
    return 'home';
  }
  function tabState(){
    var cur = q('.tab[aria-current="page"]');
    return { visible: visiblePage(),
             ariaCurrent: cur ? cur.dataset.tab : 'NONE',
             consistent: (cur ? cur.dataset.tab : 'NONE') === visiblePage() };
  }
  try {
    p.title = document.title;
    p.audioCountInit = txt('#audioCount');
    p.noteCountInit = txt('#noteCount');

    /* --- 0) 新结构：底部 4 Tab，没有 AI Tab；aria-current 与可见页一致 --- */
    p.tabsStructure = { count: n('.tab'),
                        ids: all('.tab').map(function(t){ return t.dataset.tab; }).join('/'),
                        names: all('.tab').map(function(t){ return t.textContent.trim(); }).join('/'),
                        hasAiTab: !!q('#tabAI'),
                        state: tabState() };
    /* 侧边栏入口：笔记 / 待办 / 目录；#sideExport 必须不存在 */
    p.sideStructure = { count: n('.side-btn'),
                        names: all('.side-btn .side-txt').map(function(e){ return e.textContent.trim(); }).join('/'),
                        hasSideExport: !!q('#sideExport') };
    /* 笔记页：整屏页 + 两个 role=tab 分段按钮 + 两个 pane 的 id 都还在 */
    p.notePageStructure = { screenExists: !!q('#noteScreen'),
                            segTabs: n('#noteScreen [role="tab"]'),
                            segSelected: n('#noteScreen [role="tab"][aria-selected="true"]'),
                            audioPanelExists: !!q('#audioPanel'),
                            notesPanelExists: !!q('#notesPanel'),
                            audioIsTabpanel: q('#audioPanel') ? q('#audioPanel').getAttribute('role') : 'MISSING',
                            notesIsTabpanel: q('#notesPanel') ? q('#notesPanel').getAttribute('role') : 'MISSING' };

    /* --- 1) 目录面板（仍是浮层，保留）→ 两个按钮 = 「下面列哪一类」的开关 --- */
    q('#sideDir').click();
    p.dirOpen = !q('#dirPanel').hidden;
    p.dirAudioBtnText = txt('#dirOpenAudio');
    p.dirNotesBtnText = txt('#dirOpenNotes');
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

    /* --- 2) 目录里点一条 → 落到**全屏笔记页**的原音频那一边（不再开浮层） --- */
    q('#dirContent .entry').click();
    p.afterCatalogAudio = { notePageOpen: !q('#noteScreen').hidden,
                            audioPaneVisible: !q('#audioPanel').hidden,
                            notesPaneHidden: q('#notesPanel').hidden,
                            dirClosed: q('#dirPanel').hidden,
                            dlgOpen: !q('#confirmDialog').hidden,
                            tab: tabState(),
                            title: txt('#audioTitle'), count: txt('#audioCount') };
    p.audioItems = n('#audioList .audio-item');
    p.audioFirstMeta = txt('#audioList .audio-item .audio-meta');
    p.audioButtons = all('#audioList .audio-item:first-child .icon-btn').map(function(b){ return b.textContent.trim(); }).join('/');
    /* 3) 播放 */
    q('#audioList .audio-item:first-child button[data-act="play"]').click();
    p.afterPlayWave = q('#audioList .audio-item:first-child .wave').className;
    p.playToast = q('.toast') ? q('.toast').textContent.slice(0,18) : 'none';
    /* 4) 查看 AI 总结 → 笔记页切到「AI 总结笔记」那一边（同一个整屏页，换 pane） */
    q('#audioList .audio-item:first-child button[data-act="summary"]').click();
    p.afterSummary = { notePageOpen: !q('#noteScreen').hidden,
                       notesPaneVisible: !q('#notesPanel').hidden,
                       audioPaneHidden: q('#audioPanel').hidden,
                       segSelected: q('#segNotes').getAttribute('aria-selected'),
                       segAudioSelected: q('#segAudio').getAttribute('aria-selected'),
                       title: txt('#notesTitle'), sub: txt('#notesPanel .sub'),
                       firstSummary: txt('#noteList .note-item .note-preview').slice(0,26),
                       firstTags: all('#noteList .note-item:first-child .tag').map(function(e){return e.textContent;}).join('|') };
    /* 5) AI 总结 → 切回原音频 pane */
    q('#noteList .note-item:first-child button[data-act="audio"]').click();
    p.backToAudio = !q('#audioPanel').hidden && q('#notesPanel').hidden;
    /* 6) 重命名（确认后生效） */
    q('#audioList .audio-item:first-child button[data-act="rename"]').click();
    p.renameDlg = txt('#dlgTitle');
    p.renameDlgButtons = all('#dlgActions .btn').map(function(b){ return b.textContent; }).join('/');
    q('#dlgActions .btn').click();          // 确认重命名
    p.renamedTitle = txt('#audioList .audio-item:first-child .audio-title');
    /* 7) 删除：先取消，再确认 */
    var before = n('#audioList .audio-item');
    q('#audioList .audio-item:first-child button[data-act="del"]').click();
    p.delDlgAudio = txt('#dlgTitle');
    p.delDlgBody = txt('#dlgBody');
    q('#dlgActions .btn:last-child').click();   // 取消
    p.audiosAfterCancel = n('#audioList .audio-item') + '/' + before;
    q('#audioList .audio-item:first-child button[data-act="del"]').click();
    q('#dlgActions .btn').click();          // 确认删除
    p.audiosAfterConfirm = n('#audioList .audio-item');
    p.notesAfterAudioDelete = txt('#noteCount');
    /* 8) 侧栏【笔记】→ 同一个全屏笔记页；重新总结 */
    q('#tabHome').click();     // 离开整屏页：P0-C 已去掉页面 ✕，只能切底部 Tab（原来这里是 #audioPanel [data-close]）
    p.afterNoteClose = tabState();
    q('#sideNote').click();
    p.notesFromSidebar = { open: !q('#noteScreen').hidden, tab: tabState(), title: txt('#notesTitle') };
    q('#noteNewBtn').click();
    p.resummarizeDlg = txt('#dlgTitle');
    p.resummarizeButtons = all('#dlgActions .btn').map(function(b){ return b.textContent; }).join('/');
    q('#dlgActions .btn').click();
    p.summaryAfterUpdate = txt('#noteList .note-item .note-preview').slice(0,24);
    /* 底部 Tab【笔记】必须与侧栏【笔记】落点一致（用户明确要求） */
    q('#tabNote').click();
    p.notesViaTab = { open: !q('#noteScreen').hidden, tab: tabState(),
                      segTabs: n('#noteScreen [role="tab"]'),
                      segSelected: n('#noteScreen [role="tab"][aria-selected="true"]') };
    q('#tabHome').click();
    /* 9) 目录页 → AI 总结笔记 → 点一条真的打开（还是同一个整屏页） */
    q('#sideDir').click();
    q('#dirOpenNotes').click();
    p.afterCatalogNotesHint = txt('#dirHint');
    p.afterCatalogNotesRows = n('#dirContent .entry');
    q('#dirContent .entry').click();
    p.afterCatalogNotes = { notePageOpen: !q('#noteScreen').hidden,
                            notesPaneVisible: !q('#notesPanel').hidden,
                            title: txt('#notesTitle') };
    q('#tabHome').click();
    /* 10) 助手浮层：默认只 3 条指令 + 查看全部；两条唤起路径 */
    p.asstStructure = { chipsTop: n('#cmdTop .chip[data-cmd]'),
                        chipsTotal: n('.cmd-group .chip[data-cmd]'),
                        moreHidden: q('#cmdMore').hidden };
    q('#callBtn').click();                              // 首页药丸（原为 #tabAI）
    p.asstOpenHome = !q('#assistant').hidden;
    p.cmdChips = all('#cmdTop .chip[data-cmd]').map(function(b){ return b.textContent.trim(); }).join('/');
    q('#assistant [data-cmd="audio"]').click();
    p.audioViaVoice = { open: !q('#noteScreen').hidden, pane: !q('#audioPanel').hidden,
                        case: txt('#asstCase').slice(0,22) };
    q('#tabHome').click();
    q('#fabCall').click();                              // 非首页的悬浮呼叫按钮
    p.asstOpenFab = !q('#assistant').hidden;
    q('#assistant [data-cmd="summarize"]').click();
    p.summarizeViaVoice = txt('#dlgTitle');
    q('#dlgActions .btn:last-child').click();
    /* 11) 待办页（整屏页）+ 导出流程（原音频条目） */
    q('#sideTodo').click();
    p.todoPage = { open: !q('#todoPanel').hidden, tab: tabState(),
                   banner: txt('#todoPanel .banner').replace(/\s+/g,' ').slice(0,28) };
    q('#tabHome').click();
    p.backHome = tabState();
    q('#sideDir').click(); q('#dirOpenAudio').click(); q('#dirContent .entry').click();
    q('#audioList .audio-item:first-child button[data-act="export"]').click();
    p.exportDlgFromAudio = { title: txt('#dlgTitle'), body: txt('#dlgBody'),
                             buttons: all('#dlgActions .btn').map(function(b){ return b.textContent; }).join('/') };
    q('#dlgActions .btn').click();   // 确认导出
    document.title = 'PROBE_DONE';
  } catch (e) {
    p.throwAt = String(e.message);
  }
  var pre = document.createElement('pre');
  pre.id = 'probe-json';
  pre.textContent = JSON.stringify(window.__p, null, 1);
  document.body.appendChild(pre);
});
</script>
'@
$dom = Join-Path $OutDir 'p-new.html'
$html = Get-Content $Page -Raw -Encoding UTF8
[System.IO.File]::WriteAllText($dom, ($html -replace '</body>', ($probe + "`r`n</body>")), (New-Object System.Text.UTF8Encoding($false)))
$prof = Join-Path $env:TEMP ('sp' + [guid]::NewGuid().ToString('N'))
$raw = & $exe --headless --no-sandbox --disable-gpu --user-data-dir=$prof --window-size=430,932 `
        --virtual-time-budget=12000 --dump-dom ("file:///" + ($dom -replace '\\','/')) 2>&1 | Out-String
Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue
$m = [regex]::Match($raw, '(?s)<pre id="probe-json">(.*?)</pre>')
if ($m.Success){
  $json = $m.Groups[1].Value -replace '&quot;','"' -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>'
  Write-Host "=========== 新流程探针 ==========="
  Write-Host $json
} else {
  Write-Host 'PROBE NOT FOUND. tail:'
  Write-Host $raw.Substring([Math]::Max(0,$raw.Length-600))
}