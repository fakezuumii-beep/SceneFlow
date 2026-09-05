param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot
$scriptPath = Join-Path $workspace 'server.py'
$projects = @()
try { $projects = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/api/projects' -TimeoutSec 3 } catch {}
foreach ($project in $projects) {
    if ($project.job.status -eq 'running') { throw '项目仍在处理，请完成或在页面停止任务后再重启。' }
}
$listeners = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    $serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if ($serverProcess.CommandLine -notlike "*$scriptPath*") { throw '8766 端口属于其他程序，未停止该程序。' }
}
if ($CheckOnly) { Write-Host 'Restart script checks passed. No process was stopped.'; return }
foreach ($listener in $listeners) {
    Stop-Process -Id $listener.OwningProcess
    Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue | Wait-Process -Timeout 15
}
& (Join-Path $workspace '启动工作台.ps1')
