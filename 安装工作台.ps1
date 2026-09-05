param([switch]$CpuOnly, [switch]$SkipModels)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv venv .venv --python 3.12
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else { throw '请先安装 Python 3.12（python.org），勾选 Add Python to PATH，再运行本安装程序。' }
    if ($LASTEXITCODE -ne 0) { throw 'Python 环境创建失败，请安装 Python 3.12 后重试。' }
}
& $runtime -m ensurepip --upgrade
& $runtime -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '工作台依赖安装失败，重新运行可以继续。' }
if (-not $SkipModels) {
    $modelArgs = @('engine_setup.py')
    if ($CpuOnly) { $modelArgs += '--cpu' }
    & $runtime @modelArgs
    if ($LASTEXITCODE -ne 0) { throw '本地媒体引擎安装未完成，重新运行可以继续；下载的文件会保留。' }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Host '还需安装 FFmpeg（包含 ffprobe）并加入 PATH，之后即可导出视频。下载地址：https://www.gyan.dev/ffmpeg/builds/'
}
Write-Host '安装完成。Azure TTS V1 默认可直接联网配音；填写 DeepSeek 与 Pexels API Key 后，双击「启动工作台.bat」开始创作。'
