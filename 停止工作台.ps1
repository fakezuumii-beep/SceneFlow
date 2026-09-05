$pidFile = Join-Path $PSScriptRoot 'data\server.pid'
if (Test-Path -LiteralPath $pidFile) {
    $serverPid = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid" -ErrorAction SilentlyContinue
    $expected = Join-Path $PSScriptRoot 'server.py'
    if ($process -and $process.CommandLine -like "*$expected*") {
        Stop-Process -Id $serverPid
        Remove-Item -LiteralPath $pidFile
    }
}
