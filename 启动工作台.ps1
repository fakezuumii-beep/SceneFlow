$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot
$pythonRuntime = Join-Path $workspace '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonRuntime)) {
    $foundPython = Get-Command python -ErrorAction SilentlyContinue
    if ($foundPython) { $pythonRuntime = $foundPython.Source }
}
if (-not (Test-Path -LiteralPath $pythonRuntime)) { throw '请先双击「安装工作台.bat」安装独立运行环境。' }
$alreadyRunning = $false
try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/api/projects' -TimeoutSec 2; $alreadyRunning = $true } catch {}
if (-not $alreadyRunning) {
    $logFolder = Join-Path $workspace 'data'
    New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
    $proc = Start-Process -FilePath $pythonRuntime -ArgumentList @('"' + (Join-Path $workspace 'server.py') + '"') -WorkingDirectory $workspace -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'server.log') -RedirectStandardError (Join-Path $logFolder 'server-error.log') -PassThru
    Set-Content -LiteralPath (Join-Path $logFolder 'server.pid') -Value $proc.Id
    for ($attempt = 0; $attempt -lt 25; $attempt++) {
        Start-Sleep -Milliseconds 400
        try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/api/projects' -TimeoutSec 1; $alreadyRunning = $true; break } catch {}
    }
}
if (-not $alreadyRunning) { throw '启动未完成，请查看 data\server-error.log。' }
Start-Process 'http://127.0.0.1:8766'
