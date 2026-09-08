param(
    [string]$Version = 'v0.1.0-beta.1',
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root

if (-not [Environment]::Is64BitOperatingSystem) { throw 'SOLO Portable 构建只支持 Windows x64。' }
$buildRoot = Join-Path $root '.release-build'
$cacheRoot = Join-Path $buildRoot 'cache'
$stageRoot = Join-Path $buildRoot 'stage'
$artifactRoot = Join-Path $buildRoot 'artifacts'
$packageName = "SOLO-Portable-$Version-Windows-x64"
$stage = Join-Path $stageRoot $packageName
$app = Join-Path $stage 'app'
$runtime = Join-Path $app '.runtime'
$wheelhouse = Join-Path $app '.offline\main-wheels'
$modelRoot = Join-Path $app 'engines\faster-whisper\base'
$sourceCommit = (& git rev-parse HEAD).Trim()
$gitStatus = @(& git status --porcelain)

function Ensure-Directory([string]$Path) { New-Item -ItemType Directory -Force -Path $Path | Out-Null }

function Copy-Tree([string]$Source, [string]$Target) {
    Ensure-Directory $Target
    & robocopy $Source $Target /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "复制失败：$Source" }
}

function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Download-Verified([string]$Url, [string]$Target, [string]$Sha256) {
    Ensure-Directory (Split-Path -Parent $Target)
    if (-not (Test-Path -LiteralPath $Target) -or (Hash $Target) -ne $Sha256.ToLowerInvariant()) {
        Write-Host "下载：$Url"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Target
    }
    if ((Hash $Target) -ne $Sha256.ToLowerInvariant()) { throw "下载校验失败：$Target" }
}

function Find-FirstFile([string]$Folder, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Folder)) { return $null }
    Get-ChildItem -LiteralPath $Folder -Filter $Name -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
}

Write-Host "构建 $packageName（source_commit=$sourceCommit）"
if ($gitStatus.Count) { Write-Host '注意：工作区有未提交改动，状态会记录到 manifest；不会复制 data/.venv/engines 等本地目录。' }

foreach ($path in @($stageRoot, $artifactRoot)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    Ensure-Directory $path
}
Ensure-Directory $cacheRoot
Ensure-Directory $app
Ensure-Directory (Join-Path $stage 'data')

$rootFiles = @(
    'server.py','core.py','storyboard.py','storyboard_rules.json','atomic_files.py',
    'aroll.py','musetalk_worker.py','wav2lip_worker.py','wav2lip_setup.py','worker_progress.py','model_client.py',
    'transcribe.py','speech_units.py','local_engines.py','tts_common.py',
    'azure_tts_worker.py','engine_setup.py','requirements.txt','requirements-media.txt','requirements-wav2lip.txt',
    'install-portable.ps1'
)
foreach ($name in $rootFiles) {
    $sourceName = if ($name -eq 'install-portable.ps1') { '安装工作台.ps1' } else { $name }
    $source = Join-Path $root $sourceName
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "发行白名单文件缺失：$name" }
    $destination = Join-Path $app $name
    Copy-Item -LiteralPath $source -Destination $destination -Force
    if ($name -eq 'install-portable.ps1') {
        $scriptText = [IO.File]::ReadAllText($source)
        [IO.File]::WriteAllText($destination, $scriptText, (New-Object Text.UTF8Encoding($true)))
    }
}
Copy-Tree (Join-Path $root 'static') (Join-Path $app 'static')
Copy-Tree (Join-Path $root 'providers') (Join-Path $app 'providers')
Ensure-Directory (Join-Path $app 'assets\hosts')
foreach ($assetName in @('solo-host-v1-1080.jpg')) {
    $asset = Join-Path $root "assets\hosts\$assetName"
    if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) { throw "内置主持人素材缺失：$assetName" }
    Copy-Item -LiteralPath $asset -Destination (Join-Path $app "assets\hosts\$assetName") -Force
}
Copy-Item -LiteralPath (Join-Path $root 'LICENSE') -Destination (Join-Path $stage 'LICENSE') -Force
Copy-Item -LiteralPath (Join-Path $root 'THIRD_PARTY_NOTICES.md') -Destination (Join-Path $stage 'THIRD_PARTY_NOTICES.md') -Force

$uvSha = '5049375aa2a5162f132b2c1cb992e25d42d47d934cab8c174dbe6f60973dcc12'
$uvArchive = Join-Path $cacheRoot 'uv-0.8.22-windows-x64.zip'
$legacyUv = Get-ChildItem -LiteralPath $buildRoot -Filter 'uv.zip' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($legacyUv -and (Hash $legacyUv.FullName) -eq $uvSha) { Copy-Item $legacyUv.FullName $uvArchive -Force }
if (-not (Test-Path -LiteralPath $uvArchive)) {
    Download-Verified 'https://github.com/astral-sh/uv/releases/download/0.8.22/uv-x86_64-pc-windows-msvc.zip' $uvArchive $uvSha
}
$uvStage = Join-Path $cacheRoot 'uv-stage'
if (Test-Path -LiteralPath $uvStage) { Remove-Item -LiteralPath $uvStage -Recurse -Force }
Ensure-Directory $uvStage
Expand-Archive -LiteralPath $uvArchive -DestinationPath $uvStage -Force
$uvExe = Find-FirstFile $uvStage 'uv.exe'
if (-not $uvExe) { throw 'uv 压缩包缺少 uv.exe。' }
Ensure-Directory (Join-Path $runtime 'uv')
Copy-Item -LiteralPath $uvExe.FullName -Destination (Join-Path $runtime 'uv\uv.exe') -Force

$pythonName = 'cpython-3.12.10-windows-x86_64-none'
$pythonSource = Join-Path ([Environment]::GetFolderPath('UserProfile')) "AppData\Roaming\uv\python\$pythonName"
$pythonTarget = Join-Path $runtime "python\$pythonName"
if (Test-Path -LiteralPath $pythonSource) {
    Copy-Tree $pythonSource $pythonTarget
} else {
    Ensure-Directory (Join-Path $runtime 'python')
    & (Join-Path $runtime 'uv\uv.exe') python install 3.12.10 --install-dir (Join-Path $runtime 'python')
    if ($LASTEXITCODE -ne 0) { throw '无法准备 Python 3.12.10 Runtime。' }
}
$bundledPython = Join-Path $pythonTarget 'python.exe'
if (-not (Test-Path -LiteralPath $bundledPython)) {
    $found = Find-FirstFile (Join-Path $runtime 'python') 'python.exe'
    if (-not $found) { throw 'Python Runtime 缺少 python.exe。' }
    $pythonTarget = $found.Directory.FullName
    $bundledPython = $found.FullName
}

$ffmpegSha = 'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9'
$ffmpegArchive = Join-Path $cacheRoot 'ffmpeg-9.0.1-essentials-windows-x64.zip'
$legacyFfmpeg = Get-ChildItem -LiteralPath $buildRoot -Filter 'ffmpeg.zip' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($legacyFfmpeg -and (Hash $legacyFfmpeg.FullName) -eq $ffmpegSha) { Copy-Item $legacyFfmpeg.FullName $ffmpegArchive -Force }
if (-not (Test-Path -LiteralPath $ffmpegArchive)) {
    Download-Verified 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $ffmpegArchive $ffmpegSha
}
$ffmpegStage = Join-Path $cacheRoot 'ffmpeg-stage'
if (Test-Path -LiteralPath $ffmpegStage) { Remove-Item -LiteralPath $ffmpegStage -Recurse -Force }
Ensure-Directory $ffmpegStage
Expand-Archive -LiteralPath $ffmpegArchive -DestinationPath $ffmpegStage -Force
$ffmpeg = Find-FirstFile $ffmpegStage 'ffmpeg.exe'
$ffprobe = Find-FirstFile $ffmpegStage 'ffprobe.exe'
if (-not $ffmpeg -or -not $ffprobe) { throw 'FFmpeg 压缩包缺少 ffmpeg.exe 或 ffprobe.exe。' }
Ensure-Directory (Join-Path $runtime 'ffmpeg\bin')
Copy-Item $ffmpeg.FullName (Join-Path $runtime 'ffmpeg\bin\ffmpeg.exe') -Force
Copy-Item $ffprobe.FullName (Join-Path $runtime 'ffmpeg\bin\ffprobe.exe') -Force

$legacyWheels = Get-ChildItem -LiteralPath $buildRoot -Directory -Filter 'main-wheels' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($legacyWheels) { Copy-Tree $legacyWheels.FullName $wheelhouse }
if (-not (Get-ChildItem -LiteralPath $wheelhouse -File -ErrorAction SilentlyContinue)) {
    Ensure-Directory $wheelhouse
    & $bundledPython -m pip download --disable-pip-version-check --only-binary=:all: --dest $wheelhouse -r (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '无法下载 requirements.txt 的完整 Windows x64 wheelhouse。' }
}
$wheelCount = @(Get-ChildItem -LiteralPath $wheelhouse -File | Where-Object { $_.Extension -in @('.whl','.zip') }).Count
if ($wheelCount -lt 20) { throw "离线 wheelhouse 数量异常：$wheelCount" }
$requirements = Join-Path $root 'requirements.txt'
$bundledUv = Join-Path $runtime 'uv\uv.exe'
& $bundledUv pip install --python $bundledPython --break-system-packages --no-index --find-links $wheelhouse --dry-run -r $requirements | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host '现有 wheelhouse 不完整，补齐 requirements.txt 的离线依赖…'
    & $bundledPython -m pip download --disable-pip-version-check --dest $wheelhouse -r $requirements
    if ($LASTEXITCODE -ne 0) { throw '无法补齐 requirements.txt 的完整 Windows x64 wheelhouse。' }
    & $bundledUv pip install --python $bundledPython --break-system-packages --no-index --find-links $wheelhouse --dry-run -r $requirements | Out-Host
    if ($LASTEXITCODE -ne 0) { throw '离线 wheelhouse 无法解析 requirements.txt。' }
}

$whisperRevision = 'ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66'
$modelSource = Join-Path ([Environment]::GetFolderPath('UserProfile')) ".cache\huggingface\hub\models--Systran--faster-whisper-base\snapshots\$whisperRevision"
if (-not (Test-Path -LiteralPath $modelSource)) {
    throw "缺少 faster-whisper Base 模型缓存（revision $whisperRevision），请先准备模型后再构建。"
}
$modelFiles = @('config.json','model.bin','tokenizer.json','vocabulary.txt')
Ensure-Directory $modelRoot
$modelRecords = @()
foreach ($name in $modelFiles) {
    $source = Join-Path $modelSource $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Whisper Base 缺少文件：$name" }
    Copy-Item -LiteralPath $source -Destination (Join-Path $modelRoot $name) -Force
    $item = Get-Item -LiteralPath (Join-Path $modelRoot $name)
    $modelRecords += [ordered]@{ file=$name; size=$item.Length; sha256=(Hash $item.FullName) }
}
[ordered]@{ repo='Systran/faster-whisper-base'; revision=$whisperRevision; files=$modelRecords } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $modelRoot 'model-manifest.json') -Encoding UTF8

$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { throw '缺少 Windows C# 编译器（Framework64 csc.exe）。' }
$launcherOutput = Join-Path $stage 'SOLO.exe'
& $csc /nologo /target:winexe /platform:x64 /optimize+ /out:$launcherOutput /reference:System.Windows.Forms.dll /reference:System.Drawing.dll (Join-Path $root 'launcher\SOLOLauncher.cs')
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $launcherOutput)) { throw 'SOLO.exe 构建失败。' }

$instructions = @'
SOLO v0.1.0-beta.1 · Windows 10/11 x64

开始使用
1. 将整个文件夹解压到普通文件夹（不要只拖出 SOLO.exe）。
2. 双击 SOLO.exe。
3. 首次启动会自动检查并准备核心环境，然后打开默认浏览器进入 SOLO。
4. 在「连接与设置」填写 DeepSeek API Key 和 Pexels API Key。

你不需要安装 Python、FFmpeg、uv，也不需要打开 PowerShell。
便携版已内置 Python 3.12.10、FFmpeg/ffprobe、基础依赖和 faster-whisper Base。

A-roll / MuseTalk / Wav2Lip
核心工作台可以先启动。第一次使用人物口型时，在界面点击“安装 / 校验 A-roll 组件”；
MuseTalk 运行环境和模型体积较大，会按需下载。Wav2Lip 也不在主包中，选择它并阅读、确认第三方非商业使用限制后才会安装。
A-roll 未安装不会阻止普通音频、分镜和素材功能。

用户数据保存在本文件夹的 data\，更新 app\ 不会删除项目和设置。
遇到启动问题，请把 data\logs\launcher.log 和 server-error.log 一并提供给开发者。
'@
$instructions | Set-Content -LiteralPath (Join-Path $stage 'README-PORTABLE.txt') -Encoding UTF8
$manifest = [ordered]@{
    app_version=$Version; platform='windows-x64'; python='3.12.10'; uv='0.8.22';
    ffmpeg='9.0.1-essentials'; faster_whisper='base'; whisper_revision=$whisperRevision;
    source_commit=$sourceCommit; built_at=[DateTime]::UtcNow.ToString('o');
    git_dirty=[bool]$gitStatus.Count; wheel_count=$wheelCount;
    key_files=[ordered]@{
        'SOLO.exe'=(Hash (Join-Path $stage 'SOLO.exe'));
        'app/.runtime/ffmpeg/bin/ffmpeg.exe'=(Hash (Join-Path $runtime 'ffmpeg\bin\ffmpeg.exe'));
        'app/.runtime/ffmpeg/bin/ffprobe.exe'=(Hash (Join-Path $runtime 'ffmpeg\bin\ffprobe.exe'));
        'app/engines/faster-whisper/base/model.bin'=(Hash (Join-Path $modelRoot 'model.bin'))
    }
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $app 'release-manifest.json') -Encoding UTF8

Ensure-Directory $artifactRoot
$zip = Join-Path $artifactRoot "$packageName.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
tar -a -c -f $zip -C $stageRoot $packageName
if ($LASTEXITCODE -ne 0) { throw 'ZIP 创建失败。' }
$zipHash = Hash $zip
"$zipHash  $([IO.Path]::GetFileName($zip))" | Set-Content -LiteralPath "$zip.sha256" -Encoding ASCII
Write-Host "ZIP: $zip"
Write-Host "SHA256: $zipHash"

if (-not $SkipSmokeTest) {
    $smokeRoot = Join-Path $buildRoot 'smoke'
    if (Test-Path -LiteralPath $smokeRoot) { Remove-Item -LiteralPath $smokeRoot -Recurse -Force }
    Ensure-Directory $smokeRoot
    Expand-Archive -LiteralPath $zip -DestinationPath $smokeRoot -Force
    $smoke = Join-Path $smokeRoot $packageName
    $smokeApp = Join-Path $smoke 'app'
    $smokeData = Join-Path $smoke 'data'
    $smokeRuntimePython = Join-Path $smokeApp '.runtime\python\cpython-3.12.10-windows-x86_64-none\python.exe'
    $smokePython = Join-Path $smokeApp '.venv\Scripts\python.exe'
    $env:SOLO_DATA_DIR = $smokeData
    $env:SOLO_PORTABLE = '1'
    $env:SOLO_PORT = '18766'
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    $env:PATH = (Join-Path $smokeApp '.runtime\ffmpeg\bin') + [IO.Path]::PathSeparator + $env:PATH
    & (Join-Path $smokeApp '.runtime\ffmpeg\bin\ffmpeg.exe') -version | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { throw 'Portable ffmpeg smoke test 失败。' }
    & (Join-Path $smokeApp '.runtime\ffmpeg\bin\ffprobe.exe') -version | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { throw 'Portable ffprobe smoke test 失败。' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $smokeApp 'install-portable.ps1') -Portable -SkipModels
    if ($LASTEXITCODE -ne 0) { throw 'Portable 离线核心安装 smoke test 失败。' }
    $wav = Join-Path $smokeData 'smoke.wav'
    Ensure-Directory (Split-Path -Parent $wav)
    & (Join-Path $smokeApp '.runtime\ffmpeg\bin\ffmpeg.exe') -y -v error -f lavfi -i 'sine=frequency=880:duration=0.6' -ar 16000 -ac 1 $wav
    if (-not (Test-Path -LiteralPath $smokePython)) { throw 'Portable venv 创建失败。' }
    & $smokePython -c "import os,sys; from faster_whisper import WhisperModel; m=WhisperModel(os.path.join(sys.argv[1],'engines','faster-whisper','base'),device='cpu',compute_type='int8'); print('whisper:',len(list(m.transcribe(sys.argv[2],language='en',vad_filter=False)[0])))" $smokeApp $wav
    if ($LASTEXITCODE -ne 0) { throw 'Portable faster-whisper Base 离线加载/推理 smoke test 失败。' }
    $serverLog = Join-Path $smokeData 'logs\server.log'
    Ensure-Directory (Split-Path -Parent $serverLog)
    $serverErr = Join-Path $smokeData 'logs\server-error.log'
    $serverProcess = Start-Process -FilePath $smokePython -ArgumentList @('-u',(Join-Path $smokeApp 'server.py')) -WorkingDirectory $smokeApp -PassThru -WindowStyle Hidden -RedirectStandardOutput $serverLog -RedirectStandardError $serverErr
    $healthy = $false
    for ($i=0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:18766/health' -TimeoutSec 2; if ($h.status -eq 'ok') { $healthy=$true; break } } catch {}
    }
    if (-not $healthy) { if (-not $serverProcess.HasExited) { Stop-Process -Id $serverProcess.Id -Force }; throw 'Portable /health smoke test 失败。' }
    if (-not $serverProcess.HasExited) { Stop-Process -Id $serverProcess.Id -Force }
    Remove-Item Env:SOLO_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:SOLO_PORTABLE -ErrorAction SilentlyContinue
    Remove-Item Env:SOLO_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
    Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
    Write-Host 'Portable offline smoke test passed.' -ForegroundColor Green
}

Get-Item -LiteralPath $zip | Select-Object FullName,Length
