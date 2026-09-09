param([switch]$CpuOnly, [switch]$SkipModels, [switch]$Portable)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$portableMode = $Portable -or $env:SOLO_PORTABLE -eq '1'
if ($portableMode -and -not [Environment]::Is64BitOperatingSystem) {
    throw 'SceneFlow Portable 仅支持 Windows 10/11 x64。'
}

$runtime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$toolRoot = Join-Path $PSScriptRoot '.runtime'
$uvPath = Join-Path $toolRoot 'uv\uv.exe'
$ffmpegBin = Join-Path $toolRoot 'ffmpeg\bin'
$pythonInstallRoot = Join-Path $toolRoot 'python'
$bundledPython = Join-Path $pythonInstallRoot 'cpython-3.12.10-windows-x86_64-none\python.exe'
$mainWheelhouse = Join-Path $PSScriptRoot '.offline\main-wheels'
$env:UV_PYTHON_INSTALL_DIR = $pythonInstallRoot
$env:UV_CACHE_DIR = Join-Path $toolRoot 'uv-cache'

function Download-File([string]$Url, [string]$Target) {
    $folder = Split-Path -Parent $Target
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    Write-Host "正在下载：$Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Target
}

function Ensure-Uv {
    if (Test-Path -LiteralPath $uvPath) { return $uvPath }
    if ($portableMode) { throw 'Portable 核心文件不完整，请重新下载 SceneFlow Portable。缺少 uv。' }
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    if (-not [Environment]::Is64BitOperatingSystem) {
        throw '当前自动安装器仅支持 Windows 10/11 x64。'
    }
    Write-Host '未检测到 Python，正在准备独立 Python 运行环境…'
    $archive = Join-Path $toolRoot 'downloads\uv-0.8.22.zip'
    $checksum = Join-Path $toolRoot 'downloads\uv-0.8.22.zip.sha256'
    $stage = Join-Path $toolRoot ('uv-stage-' + [guid]::NewGuid().ToString('N'))
    Download-File 'https://github.com/astral-sh/uv/releases/download/0.8.22/uv-x86_64-pc-windows-msvc.zip' $archive
    Download-File 'https://github.com/astral-sh/uv/releases/download/0.8.22/uv-x86_64-pc-windows-msvc.zip.sha256' $checksum
    $checksumText = Get-Content -LiteralPath $checksum -Raw
    if ($checksumText -notmatch '([0-9a-fA-F]{64})') { throw '独立 Python 安装工具校验文件无效。' }
    $expected = $Matches[1].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw '独立 Python 安装工具下载校验失败。' }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $stage -Force
    $downloaded = Get-ChildItem -LiteralPath $stage -Filter 'uv.exe' -File -Recurse | Select-Object -First 1
    if (-not $downloaded) { throw '独立 Python 安装工具下载包不完整。' }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $uvPath) | Out-Null
    Copy-Item -LiteralPath $downloaded.FullName -Destination $uvPath -Force
    Remove-Item -LiteralPath $stage -Recurse -Force
    Remove-Item -LiteralPath $archive -Force
    Remove-Item -LiteralPath $checksum -Force
    return $uvPath
}

function Ensure-Python {
    if (Test-Path -LiteralPath $runtime) { return }
    $uv = Ensure-Uv
    if (Test-Path -LiteralPath $bundledPython) {
        Write-Host '正在使用随包附带的 Python 3.12.10 创建项目独立环境…'
        & $uv venv .venv --python $bundledPython
    } elseif ($portableMode) {
        throw 'Portable 核心文件不完整，请重新下载 SceneFlow Portable。缺少 Python Runtime。'
    } else {
        Write-Host '正在自动下载 Python 3.12.10 并创建项目独立环境…'
        & $uv venv .venv --python 3.12.10
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $runtime)) {
        throw 'Python 3.12 独立环境自动安装失败，重新运行安装程序可以继续。'
    }
}

function Ensure-FFmpeg {
    $localFfmpeg = Join-Path $ffmpegBin 'ffmpeg.exe'
    $localFfprobe = Join-Path $ffmpegBin 'ffprobe.exe'
    if ($portableMode) {
        if ((Test-Path -LiteralPath $localFfmpeg) -and (Test-Path -LiteralPath $localFfprobe)) { return }
        throw 'Portable 核心文件不完整，请重新下载 SceneFlow Portable。缺少 FFmpeg。'
    }
    $systemFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $systemFfprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($systemFfmpeg -and $systemFfprobe) { return }
    if ((Test-Path -LiteralPath $localFfmpeg) -and (Test-Path -LiteralPath $localFfprobe)) { return }

    Write-Host '未检测到 FFmpeg，正在自动安装项目独立版本…'
    $downloadFolder = Join-Path $toolRoot 'downloads'
    $archive = Join-Path $downloadFolder 'ffmpeg-release-essentials.zip'
    $checksum = Join-Path $downloadFolder 'ffmpeg-release-essentials.zip.sha256'
    $stage = Join-Path $toolRoot ('ffmpeg-stage-' + [guid]::NewGuid().ToString('N'))
    Download-File 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $archive
    Download-File 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256' $checksum
    $checksumText = Get-Content -LiteralPath $checksum -Raw
    if ($checksumText -notmatch '([0-9a-fA-F]{64})') { throw 'FFmpeg 校验文件无效。' }
    $expected = $Matches[1].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected -notmatch '^[0-9a-f]{64}$' -or $actual -ne $expected) {
        throw 'FFmpeg 下载校验失败，未安装该文件。'
    }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $stage -Force
    $downloadedFfmpeg = Get-ChildItem -LiteralPath $stage -Filter 'ffmpeg.exe' -File -Recurse | Select-Object -First 1
    if (-not $downloadedFfmpeg) { throw 'FFmpeg 下载包不完整。' }
    $downloadedFfprobe = Join-Path $downloadedFfmpeg.Directory.FullName 'ffprobe.exe'
    if (-not (Test-Path -LiteralPath $downloadedFfprobe)) { throw 'FFmpeg 下载包缺少 ffprobe.exe。' }
    New-Item -ItemType Directory -Force -Path $ffmpegBin | Out-Null
    Copy-Item -LiteralPath $downloadedFfmpeg.FullName -Destination $localFfmpeg -Force
    Copy-Item -LiteralPath $downloadedFfprobe -Destination $localFfprobe -Force
    Remove-Item -LiteralPath $stage -Recurse -Force
    Remove-Item -LiteralPath $archive -Force
    Remove-Item -LiteralPath $checksum -Force
    & $localFfmpeg -version | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { throw 'FFmpeg 自动安装后的运行校验失败。' }
}

Ensure-Python
Ensure-FFmpeg

$uv = Ensure-Uv
if ($portableMode -and -not (Test-Path -LiteralPath $mainWheelhouse)) {
    throw 'Portable 核心文件不完整，请重新下载 SceneFlow Portable。缺少离线依赖。'
}
if (Test-Path -LiteralPath $mainWheelhouse) {
    Write-Host '正在从随包依赖安装工作台环境…'
    & $uv pip install --python $runtime --no-index --find-links $mainWheelhouse -r requirements.txt
} else {
    & $uv pip install --python $runtime -r requirements.txt
}
if ($LASTEXITCODE -ne 0) { throw '工作台依赖安装失败，重新运行可以继续。' }
if ($portableMode) {
    $packagedModel = Join-Path $PSScriptRoot 'engines\faster-whisper\base'
    $requiredModelFiles = @('model.bin','config.json','tokenizer.json','vocabulary.txt')
    if (-not (Test-Path -LiteralPath $packagedModel) -or ($requiredModelFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $packagedModel $_)) })) {
        throw 'Portable 核心文件不完整，请重新下载 SceneFlow Portable。缺少 Whisper Base。'
    }
}
if (-not $SkipModels) {
    $modelArgs = @('engine_setup.py')
    if ($CpuOnly) { $modelArgs += '--cpu' }
    & $runtime @modelArgs
    if ($LASTEXITCODE -ne 0) { throw '本地媒体引擎安装未完成，重新运行可以继续；下载的文件会保留。' }
}
if (Test-Path -LiteralPath $uvPath) {
    & $uvPath cache clean | Out-Host
}
Write-Host '安装完成。Python 与 FFmpeg 均由工作台独立管理；填写 DeepSeek 与 Pexels API Key 后，双击 SceneFlow.exe 开始创作。'
