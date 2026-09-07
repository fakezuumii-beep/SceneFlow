$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$sourceFiles = Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File | Where-Object {
    $_.FullName -ne $PSCommandPath -and $_.FullName -notmatch '[\\/](data|engines|outputs|\.venv|\.runtime|\.release-build|\.git|\.pytest_cache|\.workbuddy|__pycache__)[\\/]'
}
$forbidden = @(
    'Qwen3-4B',
    'qwen3-4b',
    'llama-server',
    'MoneyPrinterTurbo',
    'ComfyUI_windows_portable',
    '127\.0\.0\.1:8189',
    ('Ko' + 'koro'),
    ('ko' + 'koro'),
    'sk-[A-Za-z0-9_-]{16,}',
    'AIza[0-9A-Za-z_-]{20,}'
)
$problems = @()
foreach ($file in $sourceFiles) {
    if ($file.Extension -notin @('.py','.js','.html','.css','.md','.ps1','.bat','.txt','.json','.yaml','.yml','.toml')) { continue }
    $text = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction SilentlyContinue
    foreach ($pattern in $forbidden) {
        if ($text -match $pattern) { $problems += "$($file.FullName): matched $pattern" }
    }
}
if (Test-Path -LiteralPath '.git') {
    $tracked = & git ls-files
    $badTracked = $tracked | Where-Object { $_ -match '^(data|engines|outputs|我的素材|\.venv|\.runtime)/' }
    if ($badTracked) { $problems += $badTracked | ForEach-Object { "Git must not track: $_" } }
}
if ($problems) {
    $problems | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "Release check failed with $($problems.Count) problem(s)."
}
Write-Host 'Release check passed: no credentials, machine-specific paths, removed planner runtime, or tracked local data found.' -ForegroundColor Green
