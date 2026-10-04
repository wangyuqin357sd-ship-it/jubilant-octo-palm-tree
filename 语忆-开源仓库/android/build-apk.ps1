<#
  语忆 · 手动 APK 构建脚本（无 Gradle / 无 Android Studio / 无 androidx）
  ==========================================================================
  为什么手动：
    本机原先没有 java/javac/gradle/Android SDK。Gradle 路线还要再拉一堆 Maven
    依赖，任何一个下载失败整条链就断。所以这里只依赖三个可直接下载的压缩包：
      · JDK 17          Adoptium / 清华 TUNA 镜像
          https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jdk/x64/windows/OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip
      · build-tools r34 (aapt2 / d8 / zipalign / apksigner)
          https://dl.google.com/android/repository/build-tools_r34-windows.zip
      · platform-34     (android.jar)
          https://dl.google.com/android/repository/platform-34-ext7_r03.zip
    解压到 android\.toolchain\{jdk17,build-tools_r34,platform-34}\ 即可，脚本不联网。

  构建链：
    aapt2 compile --dir res -o res.zip
    aapt2 link -o base.apk -I android.jar --manifest AndroidManifest.xml -R res.zip --java gen -A assets
    javac -source 8 -target 8 -bootclasspath android.jar -d classes  gen/**/*.java src/**/*.java
    d8 --lib android.jar --min-api 21 --output dex  classes/**/*.class
    (把 classes.dex 塞进 base.apk)
    zipalign -f 4 unsigned.apk aligned.apk
    keytool -genkeypair (自签 debug 密钥，密码写死见下)
    apksigner sign --ks ... aligned.apk -> dist\yuyi-offline-v1.0.0.apk

  用法：
    powershell -ExecutionPolicy Bypass -File build-apk.ps1 [-SkipAssets] [-Clean]
    本机执行策略是 RemoteSigned，直接 & 脚本会被拒，所以必须带 -ExecutionPolicy Bypass。
#>
[CmdletBinding()]
param(
    [switch]$SkipAssets,   # 跳过 assets 重新拷贝（只改 Java 时省 50MB 拷贝）
    [switch]$Clean         # 清掉 %TEMP% 里的中间产物
)

$ErrorActionPreference = 'Stop'

$Root    = Split-Path -Parent $PSCommandPath          # ...\yuyi-preview\android
$Proj    = Split-Path -Parent $Root                   # ...\yuyi-preview
$Tc      = Join-Path $Root '.toolchain'
# 中间产物**不能**放 %TEMP%：实测本机 aapt2 往 C:\Users\HP\...\Temp 写输出会直接
# 报 "数据无效。(13)"（普通 PowerShell 写同一目录却没问题），换到工程目录下即正常。
# 所以 .build\ 放工程里，反正也在允许的写范围内。
$Work    = Join-Path $Root '.build'
$Dist    = Join-Path $Root 'dist'
$OutApk  = Join-Path $Dist 'yuyi-offline-v1.0.0.apk'
$KsPath  = Join-Path $Root 'yuyi-debug.keystore'
$KsPass  = 'yuyi123456'
$KsAlias = 'yuyi'

function Say($m)  { Write-Host "[build] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn ] $m" -ForegroundColor Magenta }
function Die($m)  { Write-Host "[FAIL ] $m" -ForegroundColor Red; exit 1 }
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Yellow }

<#
  Windows PowerShell 5.1 的坑：把原生命令的 stderr 用 2>&1 并进管道后，
  PowerShell 会把每一行 stderr 包成 ErrorRecord；此时 $ErrorActionPreference='Stop'
  会把 javac/aapt2 的一条普通 warning 直接升级成终止错误。
  所以所有原生命令都走这个 helper：临时把 EA 调成 Continue，只认退出码。
#>
function Invoke-Native {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [switch]$Echo
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out  = & $Exe @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($Echo -and $out) {
        foreach ($line in $out) { Write-Host "    $line" -ForegroundColor DarkGray }
    }
    return $code
}

# 注意：Get-ChildItem 不支持「中间路径段带通配符 + -Recurse」，
# 所以这里自己按相对 .toolchain 的路径做正则匹配，* 表示任意一层目录名。
function Find-One([string]$relPattern, [string]$what) {
    $rx = '^' + ([regex]::Escape($relPattern) -replace '\\\*', '[^\\]+') + '$'
    $hit = Get-ChildItem $Tc -Recurse -File -ErrorAction SilentlyContinue |
           Where-Object { $_.FullName.Substring($Tc.Length + 1) -match $rx } |
           Select-Object -First 1
    if (-not $hit) { Die "找不到 $what （在 $Tc 下按模式 $relPattern 找）" }
    return $hit.FullName
}

# ------------------------------------------------------------------ 工具链定位
Step '0/9 定位工具链'

$javaExe = Find-One 'jdk17\*\bin\java.exe' 'java.exe (JDK)'
$jdkBin  = Split-Path $javaExe -Parent
$javac   = Join-Path $jdkBin 'javac.exe'
$keytool = Join-Path $jdkBin 'keytool.exe'
$jarExe  = Join-Path $jdkBin 'jar.exe'
foreach ($t in @($javac, $keytool, $jarExe)) {
    if (-not (Test-Path $t)) { Die "JDK 里找不到 $(Split-Path $t -Leaf)" }
}
$jdkHome = Split-Path $jdkBin -Parent
$env:JAVA_HOME = $jdkHome
$env:PATH = $jdkBin + ';' + $env:PATH

$aapt2      = Find-One 'build-tools_r34\*\aapt2.exe'        'aapt2.exe'
$zipalign   = Find-One 'build-tools_r34\*\zipalign.exe'     'zipalign.exe'
$d8Jar      = Find-One 'build-tools_r34\*\lib\d8.jar'       'lib\d8.jar'
$signerJar  = Find-One 'build-tools_r34\*\lib\apksigner.jar' 'lib\apksigner.jar'
$androidJar = Find-One 'platform-34\*\android.jar'          'android.jar (platform-34)'

Say "JDK      : $jdkHome"
# java -version 只写 stderr，必须走 Invoke-Native，不能直接 2>&1（见上面的坑）
[void](Invoke-Native -Exe $javaExe -Arguments @('-version') -Echo)
Say "aapt2    : $aapt2"
Say "d8.jar   : $d8Jar"
Say "android  : $androidJar"

if ($Clean -and (Test-Path $Work)) { Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue }
foreach ($d in @($Work, (Join-Path $Work 'gen'), (Join-Path $Work 'classes'),
                 (Join-Path $Work 'dex'), $Dist)) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

# ------------------------------------------------------------------ assets 暂存
Step '1/9 把整站资源拷进 assets\'

$assets = Join-Path $Root 'assets'
if ($SkipAssets -and (Test-Path (Join-Path $assets 'index.html'))) {
    Say '跳过（-SkipAssets）'
} else {
    if (Test-Path $assets) { Remove-Item $assets -Recurse -Force }
    foreach ($d in @((Join-Path $assets 'data\asr'), (Join-Path $assets 'lib'),
                     (Join-Path $assets '_tools'))) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
    }

    Copy-Item (Join-Path $Proj 'index.html') (Join-Path $assets 'index.html') -Force
    Copy-Item (Join-Path $Proj 'sw.js')      (Join-Path $assets 'sw.js')      -Force
    Copy-Item (Join-Path $Proj 'data\asr\*') (Join-Path $assets 'data\asr')  -Recurse -Force
    Copy-Item (Join-Path $Proj 'data\braille-zh.json')  (Join-Path $assets 'data\braille-zh.json')  -Force
    Copy-Item (Join-Path $Proj 'data\asr-phrases.json') (Join-Path $assets 'data\asr-phrases.json') -Force

    # 内置自检页（不是我方页面，是壳自己的诊断页）：独立文件，不碰 index.html。
    # 用 --es yuyi_page selftest.html 启动即可看到 /lib/* 通不通、TTS 引擎起没起来。
    Copy-Item (Join-Path $Root 'selftest.html') (Join-Path $assets 'selftest.html') -Force

    # 记录这次到底打包了哪个 index.html（它经常被改，出问题先对指纹）
    $idx = Get-Item (Join-Path $Proj 'index.html')
    $idxHash = (Get-FileHash $idx.FullName -Algorithm SHA256).Hash
    Say ("打包的 index.html: {0} 字节 / sha256 {1} / mtime {2}" -f `
         $idx.Length, $idxHash.Substring(0,16), $idx.LastWriteTime)
    Set-Content -Path (Join-Path $Work 'index-fingerprint.txt') -Encoding UTF8 -Value `
        ("path=$($idx.FullName)`nbytes=$($idx.Length)`nsha256=$idxHash`nmtime=$($idx.LastWriteTime)")

    # 页面按 "lib/docx-mini.js" / "lib/braille-zh.js" 引用（拦截器把根路径映射到 assets）
    # _tools\ 下再放一份别名，防止哪里按 _tools/... 引用
    foreach ($pair in @(@('docx-mini.js','docx-mini.js'), @('braille-zh.js','braille-zh.js'))) {
        Copy-Item (Join-Path $Proj ('_tools\' + $pair[0])) (Join-Path $assets ('lib\'   + $pair[1])) -Force
        Copy-Item (Join-Path $Proj ('_tools\' + $pair[0])) (Join-Path $assets ('_tools\' + $pair[1])) -Force
    }
    Say '不打包：_shots\  _tools\*.ps1  _tools\*.py  design\  README 等'
}

$allA = Get-ChildItem $assets -Recurse -File
$asrA = Get-ChildItem (Join-Path $assets 'data\asr') -File
Say ("assets 总计 {0:N1} MB / {1} 个文件（其中 data\asr {2:N1} MB）" -f `
     (($allA | Measure-Object Length -Sum).Sum / 1MB), $allA.Count,
     (($asrA | Measure-Object Length -Sum).Sum / 1MB))
foreach ($f in ($allA | Sort-Object FullName)) {
    Write-Host ("    {0,-46} {1,10:N0}" -f $f.FullName.Replace("$assets\",''), $f.Length) -ForegroundColor DarkGray
}

# ------------------------------------------------------------------ aapt2 compile
Step '2/9 aapt2 compile'
$resZip = Join-Path $Work 'res.zip'
if (Test-Path $resZip) { Remove-Item $resZip -Force }
$rc = Invoke-Native -Exe $aapt2 -Arguments @('compile','--dir',(Join-Path $Root 'res'),'-o',$resZip) -Echo
if ($rc -ne 0) { Die "aapt2 compile 退出码 $rc" }
Say ("OK -> res.zip {0:N0} bytes" -f (Get-Item $resZip).Length)

# ------------------------------------------------------------------ aapt2 link
Step '3/9 aapt2 link'
$baseApk = Join-Path $Work 'base.apk'
if (Test-Path $baseApk) { Remove-Item $baseApk -Force }

# 注意：本机 aapt2 2.19 的 --no-compress 是**无参开关**（不压缩任何资源），
# 带参数会把它当成输入文件。要按扩展名排除压缩得用 --no-compress-regex。
# 43MB 的 model.tar.gz 必须原样 STORED，否则每次读都要 inflate 一遍。
$linkArgs = @(
    'link', '-o', $baseApk,
    '-I', $androidJar,
    '--manifest', (Join-Path $Root 'AndroidManifest.xml'),
    '-R', $resZip,
    '--java', (Join-Path $Work 'gen'),
    '-A', $assets,
    '--no-compress-regex', '\.gz$',
    '--auto-add-overlay'
)
$rc = Invoke-Native -Exe $aapt2 -Arguments $linkArgs -Echo
if ($rc -ne 0) {
    Warn "--no-compress-regex 姿势失败（退出码 $rc），改用无参 --no-compress 重试"
    $linkArgs2 = @(
        'link', '-o', $baseApk, '-I', $androidJar,
        '--manifest', (Join-Path $Root 'AndroidManifest.xml'),
        '-R', $resZip, '--java', (Join-Path $Work 'gen'), '-A', $assets,
        '--no-compress', '--auto-add-overlay'
    )
    if (Test-Path $baseApk) { Remove-Item $baseApk -Force }
    $rc = Invoke-Native -Exe $aapt2 -Arguments $linkArgs2 -Echo
    if ($rc -ne 0) { Die "aapt2 link 退出码 $rc" }
}
Say ("OK -> base.apk {0:N2} MB" -f ((Get-Item $baseApk).Length / 1MB))

# 看一眼 aapt2 到底把 assets 条目名写成了什么
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    $z = [System.IO.Compression.ZipFile]::OpenRead($baseApk)
    $back = @($z.Entries | Where-Object { $_.FullName.Contains('\') })
    Say ("base.apk 条目数 {0}，其中条目名带反斜杠的 {1} 个" -f $z.Entries.Count, $back.Count)
    if ($back.Count -gt 0) {
        # ⚠️ 实测 aapt2 2.19 在 Windows 上用 -A 收 assets 时，zip 条目名用的是**反斜杠**
        #    （assets/data\asr\model.tar.gz）。设备上 AssetManager 按 '/' 精确查表，
        #    这种包装上去 getAssets().open("data/asr/model.tar.gz") 必然找不到 —— 页面白屏。
        #    第 6 步会原样重打包把名字改回来。
        Warn 'aapt2 在 Windows 上把 assets 条目名写成了反斜杠，第 6 步会规范化'
        $back | Select-Object -First 3 | ForEach-Object { Write-Host ("      " + $_.FullName) -ForegroundColor DarkGray }
    }
    $z.Dispose()
} catch {
    Warn ("检查 base.apk 内容失败：" + $_.Exception.Message)
}

# ------------------------------------------------------------------ javac
Step '4/9 javac'
$srcs = @()
$srcs += Get-ChildItem (Join-Path $Work 'gen') -Recurse -Filter *.java | ForEach-Object FullName
$srcs += Get-ChildItem (Join-Path $Root 'src') -Recurse -Filter *.java | ForEach-Object FullName
if ($srcs.Count -eq 0) { Die '没有 .java 可编译' }
Say ("源文件 {0} 个：" -f $srcs.Count)
foreach ($s in $srcs) { Write-Host "    $s" -ForegroundColor DarkGray }

$classesDir = Join-Path $Work 'classes'
Get-ChildItem $classesDir -Recurse -File -ErrorAction SilentlyContinue | Remove-Item -Force -Recurse -ErrorAction SilentlyContinue

# 经典 Android 手动编译姿势：-source 8 -target 8 + android.jar 当 bootclasspath
$rc = Invoke-Native -Exe $javac -Arguments (@('-encoding','UTF-8','-nowarn','-source','8','-target','8',
        '-bootclasspath',$androidJar,'-d',$classesDir) + $srcs) -Echo
$javacOk = ($rc -eq 0)

if (-not $javacOk) {
    Warn "bootclasspath 姿势失败（退出码 $rc），退回 -classpath android.jar"
    $rc = Invoke-Native -Exe $javac -Arguments (@('-encoding','UTF-8','-nowarn','-source','8','-target','8',
            '-classpath',$androidJar,'-d',$classesDir) + $srcs) -Echo
    $javacOk = ($rc -eq 0)
}
if (-not $javacOk) { Die "javac 编译失败（退出码 $rc）" }
Say ("OK -> classes\ 共 {0} 个 .class" -f (Get-ChildItem $classesDir -Recurse -Filter *.class).Count)

# ------------------------------------------------------------------ d8
Step '5/9 d8 -> classes.dex'
$dexDir = Join-Path $Work 'dex'
Get-ChildItem $dexDir -File -ErrorAction SilentlyContinue | Remove-Item -Force
$classFiles = Get-ChildItem $classesDir -Recurse -Filter *.class | ForEach-Object FullName
$rc = Invoke-Native -Exe $javaExe -Arguments (@('-cp',$d8Jar,'com.android.tools.r8.D8',
        '--lib',$androidJar,'--min-api','21','--output',$dexDir) + $classFiles) -Echo
if ($rc -ne 0) { Die "d8 退出码 $rc" }
$dexFile = Join-Path $dexDir 'classes.dex'
if (-not (Test-Path $dexFile)) { Die 'd8 没产出 classes.dex' }
Say ("OK -> classes.dex {0:N2} MB" -f ((Get-Item $dexFile).Length / 1MB))

# ------------------------------------------------ 重打包：规范化条目名 + 塞 dex
Step '6/9 重打包 base.apk：条目名反斜杠 -> / ，并加入 classes.dex'
$unsigned = Join-Path $Work 'unsigned.apk'
if (Test-Path $unsigned) { Remove-Item $unsigned -Force }

# 为什么用自己写的 RepackApk.java 而不是 .NET 的 ZipArchive：
#   .NET 的 CompressionLevel.NoCompression 并不产出 zip STORED(method 0)，
#   它只是让 deflate 输出 stored block，条目仍是 method 8、体积反而变大
#   （实测 resources.arsc raw=1348 -> stored=1353）。而 targetSdk>=30 时
#   Android 硬性要求 resources.arsc 未压缩，否则装不上。所以必须自己控制
#   条目压缩方式，用纯 JDK 的 ZipOutputStream 显式写 method 0 + size + CRC32。
$repackSrc = Join-Path $Root '_tools\RepackApk.java'
$repackOut = Join-Path $Work 'repack'
New-Item -ItemType Directory -Force -Path $repackOut | Out-Null
$rc = Invoke-Native -Exe $javac -Arguments @('-encoding','UTF-8','-nowarn','-d',$repackOut,$repackSrc) -Echo
if ($rc -ne 0) { Die "编译 RepackApk.java 失败（退出码 $rc）" }

$rc = Invoke-Native -Exe $javaExe -Arguments @('-Xmx1g','-cp',$repackOut,'RepackApk',
        $baseApk, $dexFile, $unsigned) -Echo
if ($rc -ne 0) { Die "RepackApk 退出码 $rc" }
if (-not (Test-Path $unsigned)) { Die 'RepackApk 没产出 unsigned.apk' }

# 复核：条目名必须全是正斜杠，resources.arsc / model.tar.gz 必须真 STORED
$z = [System.IO.Compression.ZipFile]::OpenRead($unsigned)
$stillBad = @($z.Entries | Where-Object { $_.FullName.Contains('\') })
$e    = $z.Entries | Where-Object { $_.FullName -eq 'assets/data/asr/model.tar.gz' }
$dexN = @($z.Entries | Where-Object { $_.FullName -eq 'classes.dex' }).Count
$arsc = $z.Entries | Where-Object { $_.FullName -eq 'resources.arsc' }
$total = $z.Entries.Count
$z.Dispose()

if ($stillBad.Count -gt 0) { Die ("还有 {0} 个条目名带反斜杠，没规范化干净" -f $stillBad.Count) }
if (-not $e)               { Die 'APK 里没有 assets/data/asr/model.tar.gz' }
if ($dexN -ne 1)           { Die ("classes.dex 数量不对：{0}" -f $dexN) }
if (-not $arsc)            { Die 'APK 里没有 resources.arsc' }
if ($arsc.CompressedLength -ne $arsc.Length) {
    Die ("resources.arsc 被压缩了（raw={0} stored={1}）—— targetSdk 30+ 会直接装不上" -f `
         $arsc.Length, $arsc.CompressedLength)
}
if ($e.CompressedLength -ne $e.Length) {
    Warn ("model.tar.gz 不是 STORED（raw={0} stored={1}），读的时候会多一次 inflate" -f `
          $e.Length, $e.CompressedLength)
}
Say ("复核 OK：条目 {0} 个，无反斜杠；resources.arsc STORED {1} 字节；model.tar.gz STORED {2:N0} 字节" -f `
     $total, $arsc.Length, $e.Length)

# ------------------------------------------------------------------ zipalign
Step '7/9 zipalign -f 4'
$aligned = Join-Path $Work 'aligned.apk'
if (Test-Path $aligned) { Remove-Item $aligned -Force }
$rc = Invoke-Native -Exe $zipalign -Arguments @('-f','-p','4',$unsigned,$aligned) -Echo
if ($rc -ne 0) { Die "zipalign 退出码 $rc" }
Say ("OK -> aligned.apk {0:N2} MB" -f ((Get-Item $aligned).Length / 1MB))

# ------------------------------------------------------------------ 签名
Step '8/9 keytool + apksigner'
if (-not (Test-Path $KsPath)) {
    Say '生成自签 debug 密钥（PKCS12，密码写死 yuyi123456）'
    $rc = Invoke-Native -Exe $keytool -Arguments @(
        '-genkeypair','-v','-keystore',$KsPath,'-storetype','PKCS12','-alias',$KsAlias,
        '-keyalg','RSA','-keysize','2048','-validity','10950',
        '-storepass',$KsPass,'-keypass',$KsPass,
        '-dname','CN=Yuyi Offline, OU=Dev, O=Yuyi, L=Beijing, ST=Beijing, C=CN') -Echo
    if ($rc -ne 0) { Die "keytool 退出码 $rc" }
} else {
    Say "复用已有密钥：$KsPath"
}
if (Test-Path $OutApk) { Remove-Item $OutApk -Force }
$rc = Invoke-Native -Exe $javaExe -Arguments @(
    '-jar',$signerJar,'sign',
    '--ks',$KsPath,'--ks-key-alias',$KsAlias,
    '--ks-pass',("pass:" + $KsPass),'--key-pass',("pass:" + $KsPass),
    '--v1-signing-enabled','true','--v2-signing-enabled','true','--v3-signing-enabled','true',
    '--out',$OutApk,$aligned) -Echo
if ($rc -ne 0) { Die "apksigner 退出码 $rc" }

Step '9/9 apksigner verify'
$rc = Invoke-Native -Exe $javaExe -Arguments @('-jar',$signerJar,'verify','--verbose','--print-certs',$OutApk) -Echo
$verifyCode = $rc

# ------------------------------------------------------------------ 汇总
$fi = Get-Item $OutApk
Write-Host ''
Write-Host '================ 构建结果 ================' -ForegroundColor Green
Write-Host ("APK      : {0}" -f $fi.FullName)
Write-Host ("字节数   : {0}  ({1:N2} MB)" -f $fi.Length, ($fi.Length / 1MB))
Write-Host ("verify   : exit={0}" -f $verifyCode)
Write-Host ("密钥     : {0} (alias={1} pass={2})" -f $KsPath, $KsAlias, $KsPass)
Write-Host '=========================================' -ForegroundColor Green
if ($verifyCode -ne 0) { Die 'apksigner verify 没过' }
exit 0