param([int]$Port = 8000, [ValidateSet('', 'cn', 'hk')][string]$Region = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv-jiuwen\Scripts\python.exe')) { throw 'Run setup.ps1 first.' }
if (!(Test-Path 'frontend\dist\index.html')) { throw 'Run setup.ps1 first to build the frontend.' }
if (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Run again with -Port <another port>, e.g. .\start.ps1 -Port 8010"
}
if ($Region) { $env:REGION = $Region }
Write-Host "Open http://127.0.0.1:$Port ; press Ctrl+C to stop."
Set-Location backend
& ..\.venv-jiuwen\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $Port --no-access-log
