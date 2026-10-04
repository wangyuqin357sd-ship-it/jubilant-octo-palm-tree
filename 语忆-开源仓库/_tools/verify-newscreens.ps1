$ErrorActionPreference = 'Continue'
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
  var p = window.__p;
  try {
    // 我的
    q('#tabMe').click();
    p.me = { open: !q('#meScreen').hidden, title: q('#meTitle').textContent,
             rows: n('#meScreen .row-item'), groups: Array.prototype.map.call(document.querySelectorAll('#meScreen .group-label'), function(e){return e.textContent;}).join('/'),
             notify: q('#meNotify').getAttribute('aria-pressed'),
             contrast: q('#meContrast').getAttribute('aria-pressed'),
             size: q('#meFontSize').textContent,
             speed: q('#meSpeedLabel').textContent,
             hint: q('#meScreen .hint-line').textContent };
    // 开关
    q('#meNotify').click();
    p.notifyAfter = q('#meNotify').getAttribute('aria-pressed');
    q('#meContrast').click();
    p.contrastAfter = { pressed: q('#meContrast').getAttribute('aria-pressed'), filter: document.documentElement.style.filter };
    q('#meContrast').click();
    p.filterReset = document.documentElement.style.filter === '';
    // 字号里的语速滑块
    var r = q('#meSpeed'); r.value = 160; r.dispatchEvent(new Event('input'));
    p.speedAfter = q('#meSpeedLabel').textContent;
    // 我的 → 导出记录
    q('#meScreen [data-goto="exports"]').click();
    p.exports = { open: !q('#exportsPanel').hidden, meClosed: q('#meScreen').hidden,
                  title: q('#exportsTitle').textContent, count: q('#exportsCount').textContent,
                  items: n('#exportsList .row-item'),
                  infoCard: q('#exportsPanel .info-card .info-t').textContent,
                  infoBody: q('#exportsPanel .info-card .info-s').textContent.slice(0,20),
                  buttons: Array.prototype.map.call(document.querySelectorAll('#exportsPanel .sheet-foot .btn'), function(b){return b.textContent;}).join('/') };
    // 重新下载
    q('#exportsList .row-item button[data-act="again"]').click();
    p.downloadToast = q('.toast') ? q('.toast').textContent.slice(0,16) : 'none';
    // 清空记录：取消不动数据
    var before = n('#exportsList .row-item');
    q('#exportsClear').click();
    p.clearDlg = { title: q('#dlgTitle').textContent, body: q('#dlgBody').textContent,
                   buttons: Array.prototype.map.call(document.querySelectorAll('#dlgActions .btn'), function(b){return b.textContent;}).join('/') };
    document.querySelector('#dlgActions .btn:last-child').click();
    p.afterCancelClear = n('#exportsList .row-item') + '/' + before;
    // 我的 → 帮助
    q('#exportsPanel [data-close]').click();
    q('#tabMe').click();
    q('#meScreen [data-goto="help"]').click();
    p.help = { open: !q('#helpFull').hidden, title: q('#helpFullTitle').textContent,
               infoCard: q('#helpFull .info-card .info-t').textContent,
               onItems: n('#helpFull .list:nth-of-type(1) .row-item'),
               offItems: n('#helpFull .list:nth-of-type(2) .row-item'),
               offLabels: Array.prototype.map.call(document.querySelectorAll('#helpFull .list:nth-of-type(2) .row-t'), function(e){return e.textContent;}).join(' / ') };
    q('#helpFull [data-close]').click();
    p.helpClosed = q('#helpFull').hidden;
    // 我的 → AI 总结笔记（这一行原来错指向原音频面板，已按反馈改成 notes）
    q('#tabMe').click();
    q('#meScreen [data-goto="notes"]').click();
    p.meToNotes = !q('#notesPanel').hidden;
    q('#notesPanel [data-close]').click();
    // 从我的返回首页 Tab
    q('#tabMe').click();
    p.meAgain = !q('#meScreen').hidden;
    q('#tabHome').click();
    p.backHome = { meClosed: q('#meScreen').hidden, active: q('.tab[aria-current="page"]').textContent.trim() };
  } catch (e) { p.throwAt = String(e.message); }
  var pre = document.createElement('pre'); pre.id = 'probe-json';
  pre.textContent = JSON.stringify(window.__p, null, 1);
  document.body.appendChild(pre);
  document.title = 'PROBE_DONE';
});
</script>
'@
$dom = Join-Path $OutDir 'p-new4.html'
$html = Get-Content $Page -Raw -Encoding UTF8
[System.IO.File]::WriteAllText($dom, ($html -replace '</body>', ($probe + "`r`n</body>")), (New-Object System.Text.UTF8Encoding($false)))
$prof = Join-Path $env:TEMP ('sp' + [guid]::NewGuid().ToString('N'))
$raw = & $exe --headless --no-sandbox --disable-gpu --user-data-dir=$prof --window-size=430,1240 `
        --virtual-time-budget=8000 --dump-dom ("file:///" + ($dom -replace '\\','/')) 2>&1 | Out-String
Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $dom -Force -ErrorAction SilentlyContinue
$m = [regex]::Match($raw, '(?s)<pre id="probe-json">(.*?)</pre>')
if ($m.Success){
  $json = $m.Groups[1].Value -replace '&quot;','"' -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>'
  Write-Host "=========== 新 4 屏探针 ==========="
  Write-Host $json
} else {
  Write-Host 'PROBE NOT FOUND'
  Write-Host $raw.Substring([Math]::Max(0,$raw.Length-500))
}