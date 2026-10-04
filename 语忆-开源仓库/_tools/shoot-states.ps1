param(
  [string]$Page = 'C:\Users\HP\Desktop\yuyi-preview\index.html',
  [string]$OutDir = 'C:\Users\HP\Desktop\yuyi-preview\_shots'
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$exe = (Get-ChildItem 'D:\DevCache\ms-playwright\chromium_headless_shell-*' -Recurse -Filter 'chrome-headless-shell.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1).FullName
if (-not $exe) { Write-Host 'NO SHELL'; return }
$base = Get-Content $Page -Raw -Encoding UTF8

function Shoot([string]$name, [string]$js, [int]$settle = 900){
  $dom = Join-Path $OutDir ("s-$name.html")
  $code = "<script>window.addEventListener('DOMContentLoaded',function(){ setTimeout(function(){ try{ $js }catch(e){ document.title='ERR:'+e.message; } }, 250); });</script>"
  [System.IO.File]::WriteAllText($dom, ($base -replace '</body>', ($code + "`r`n</body>")), (New-Object System.Text.UTF8Encoding($false)))
  $png = Join-Path $OutDir ("$name.png")
  if (Test-Path $png) { Remove-Item $png -Force }
  $prof = Join-Path $env:TEMP ('sp' + [guid]::NewGuid().ToString('N'))
  & $exe --headless --no-sandbox --disable-gpu --hide-scrollbars --force-device-scale-factor=2 `
         --user-data-dir=$prof --window-size=430,932 --virtual-time-budget=$settle `
         --screenshot=$png ("file:///" + ($dom -replace '\\','/')) 2>&1 | Out-Null
  Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue
  $state = '?'
  if ($js -ne '') {
    $p2 = Join-Path $env:TEMP ('sp' + [guid]::NewGuid().ToString('N'))
    $d2 = Join-Path $OutDir ("d-$name.html")
    $code2 = "<script>window.addEventListener('DOMContentLoaded',function(){ setTimeout(function(){ try{ $js }catch(e){ document.title='ERR:'+e.message; } setTimeout(function(){ var pre=document.createElement('pre'); pre.id='st'; pre.textContent=document.title+'|'+(document.getElementById('confirmDialog').hidden?'dlgClosed':'dlgOpen')+'|'+(document.getElementById('assistant').hidden?'asstClosed':'asstOpen')+'|note:'+(document.getElementById('notesPanel').hidden?'c':'o')+'|todo:'+(document.getElementById('todoPanel').hidden?'c':'o')+'|dir:'+(document.getElementById('dirPanel').hidden?'c':'o')+'|rec:'+document.getElementById('recordCard').dataset.state+'|'+document.getElementById('recordBtnText').textContent; document.body.appendChild(pre); }, 320); }, 250); });</script>"
    [System.IO.File]::WriteAllText($d2, ($base -replace '</body>', ($code2 + "`r`n</body>")), (New-Object System.Text.UTF8Encoding($false)))
    $raw = & $exe --headless --no-sandbox --disable-gpu --user-data-dir=$p2 --window-size=430,932 --virtual-time-budget=$settle --dump-dom ("file:///" + ($d2 -replace '\\','/')) 2>&1 | Out-String
    if ($raw -match '(?s)<pre id="st">(.*?)</pre>') { $state = $Matches[1] }
    Remove-Item $p2 -Recurse -Force -ErrorAction SilentlyContinue
  }
  if (Test-Path $png) { Write-Host ("OK  {0,-16} {1:n0} B  {2}" -f $name, (Get-Item $png).Length, $state) } else { Write-Host ("FAIL {0}  {1}" -f $name, $state) }
}

Shoot 'home'      "" 1200
Shoot 'recording' "document.getElementById('recordBtn').click();" 3200
Shoot 'confirm'   "document.getElementById('recordBtn').click(); var c=document.getElementById('recordBtn'); c.click(); c.click(); document.querySelectorAll('.chip')[5].click();" 2600
Shoot 'assistant' "document.getElementById('callBtn').click();" 1800
Shoot 'catalog'   "document.getElementById('sideDir').click();" 1600
Shoot 'audio'     "document.getElementById('sideDir').click(); document.getElementById('dirOpenAudio').click();" 1800
Shoot 'notes'     "document.getElementById('sideDir').click(); document.getElementById('dirOpenNotes').click();" 1800
Shoot 'todos'     "document.getElementById('sideTodo').click();" 1600
Shoot 'directory' "document.getElementById('sideDir').click();" 1600
Shoot 'export'    "document.getElementById('sideExport').click();" 1800
Shoot 'me'        "document.getElementById('tabMe').click();" 1600
Shoot 'exports'   "document.getElementById('tabMe').click(); document.querySelector('#meScreen [data-goto=`"exports`"]').click();" 1800
Shoot 'helpfull'  "document.getElementById('tabMe').click(); document.querySelector('#meScreen [data-goto=`"help`"]').click();" 1800
Shoot 'saved'     "document.getElementById('recordBtn').click(); document.querySelectorAll('.chip')[5].click();" 2600
Write-Host '--- desktop frame check ---'
$dom = Join-Path $OutDir 's-home.html'
$prof = Join-Path $env:TEMP ('sp' + [guid]::NewGuid().ToString('N'))
$png = Join-Path $OutDir 'desktop.png'
& $exe --headless --no-sandbox --disable-gpu --hide-scrollbars --user-data-dir=$prof `
       --window-size=1440,1000 --virtual-time-budget=1500 `
       --screenshot=$png ("file:///" + ($dom -replace '\\','/')) 2>&1 | Out-Null
Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $png) { Write-Host ("OK  desktop {0:n0} bytes" -f (Get-Item $png).Length) }