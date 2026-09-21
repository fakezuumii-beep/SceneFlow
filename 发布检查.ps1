$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# 只检查“会被提交”的文件：已跟踪文件 + 未被 .gitignore 忽略的新文件。
# 晨报快照、导出成片、本地临时帧都已被忽略，不应让发布检查失败。
$root = (Get-Location).Path
$candidates = & git ls-files --cached --others --exclude-standard
$sourceFiles = foreach ($relative in $candidates) {
    $item = Get-Item -LiteralPath $relative -ErrorAction SilentlyContinue
    if ($item -and $item.FullName -ne $PSCommandPath) { $item }
}
$forbidden = @(
    'Qwen3-4B',
    'qwen3-4b',
    'llama-server',
    'MoneyPrinterTurbo',
    ('Ko' + 'koro'),
    ('ko' + 'koro'),
    'sk-[A-Za-z0-9_-]{16,}',
    'AIza[0-9A-Za-z_-]{20,}'
)
$problems = @()
foreach ($file in $sourceFiles) {
    if ($file.Extension -notin @('.py','.js','.html','.css','.md','.ps1','.bat','.txt','.json','.yaml','.yml','.toml')) { continue }
    $text = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $text) { continue }
    foreach ($pattern in $forbidden) {
        if ($text -match $pattern) { $problems += "$($file.FullName): matched $pattern" }
    }
    # Machine-specific absolute paths. The repository's own path and Windows
    # system paths are fine; anything else points at one developer's disk.
    # The product default http://127.0.0.1:8189 is a localhost port, not a
    # machine path, so it is no longer treated as a problem.
    foreach ($hit in [regex]::Matches($text, '[A-Za-z]:\\[^\s"<>|()]*')) {
        $found = $hit.Value
        if ($found -like "$root*") { continue }
        if ($found -like 'C:\Windows\*') { continue }
        $problems += "$($file.FullName): machine-specific path $found"
    }
}
if (Test-Path -LiteralPath '.git') {
    $tracked = & git ls-files
    $badTracked = $tracked | Where-Object {
        $_ -match '^(data|engines|outputs|videos|_tmp_|weekly_recut_|ai_morning_editor/(history|output))/'
    }
    if ($badTracked) { $problems += $badTracked | ForEach-Object { "Git must not track: $_" } }
}
if ($problems) {
    $problems | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "Release check failed with $($problems.Count) problem(s)."
}
Write-Host 'Release check passed: no credentials, machine-specific paths, removed planner runtime, or tracked local data found.' -ForegroundColor Green
