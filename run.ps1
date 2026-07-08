# run.ps1 - AI Agent Launcher
param(
    [string]$Script = "main.py"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Try to find Python
$pythonPath = $null

# Check py launcher
$pyPath = Get-Command py -ErrorAction SilentlyContinue
if ($pyPath) {
    Write-Host "[OK] Using py launcher..." -ForegroundColor Green
    & py $Script
    if ($LASTEXITCODE -eq 0) { exit 0 }
}

# Check python3
$py3Path = Get-Command python3 -ErrorAction SilentlyContinue
if ($py3Path) {
    Write-Host "[OK] Using python3..." -ForegroundColor Green
    & python3 $Script
    if ($LASTEXITCODE -eq 0) { exit 0 }
}

# Check common Python paths
$commonPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "C:\Python313\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe"
)

foreach ($p in $commonPaths) {
    if (Test-Path $p) {
        Write-Host "[OK] Using $p" -ForegroundColor Green
        & $p $Script
        exit $LASTEXITCODE
    }
}

# Try python
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    & python $Script
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[ERROR] Python not found!" -ForegroundColor Red
Write-Host ""
Write-Host "Please install Python from https://www.python.org/downloads/"
Write-Host "OR disable Microsoft Store alias:"
Write-Host "  Settings > Apps > Advanced app settings > App execution aliases"
Write-Host "  Turn OFF 'python.exe' and 'python3.exe'"
Write-Host ""
Pause