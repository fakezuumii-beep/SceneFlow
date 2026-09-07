param([string]$OutputFolder = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$parts = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter 'SOLO-v0.1.0-beta.1-Full-NVIDIA-cu126.zip.part*' -File | Sort-Object Name)
if ($parts.Count -lt 1) { throw '请把所有 Full-NVIDIA-cu126.zip.partXX 文件放到本脚本旁边。' }
$zip = Join-Path $PSScriptRoot 'SOLO-v0.1.0-beta.1-Full-NVIDIA-cu126.zip'
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
$out = [IO.File]::Open($zip, [IO.FileMode]::CreateNew)
try {
    foreach ($part in $parts) {
        Write-Host "合并 $($part.Name)…"
        $in = [IO.File]::OpenRead($part.FullName)
        try { $in.CopyTo($out) } finally { $in.Dispose() }
    }
} finally { $out.Dispose() }
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
$expectedFile = Join-Path $PSScriptRoot 'SOLO-v0.1.0-beta.1-Full-NVIDIA-cu126.zip.sha256'
if (Test-Path -LiteralPath $expectedFile) {
    $expected = ([IO.File]::ReadAllText($expectedFile)).Split()[0].ToLowerInvariant()
    if ($hash -ne $expected) { throw "完整包校验失败：$hash" }
}
if (-not $OutputFolder) { $OutputFolder = Join-Path $PSScriptRoot 'SOLO-v0.1.0-beta.1-Full-NVIDIA-cu126' }
if (Test-Path -LiteralPath $OutputFolder) { Remove-Item -LiteralPath $OutputFolder -Recurse -Force }
Expand-Archive -LiteralPath $zip -DestinationPath $OutputFolder -Force
Write-Host "已解压到：$OutputFolder"
Write-Host '下一步：进入该目录，双击「安装工作台.bat」，安装器会使用包内依赖离线创建环境。'
