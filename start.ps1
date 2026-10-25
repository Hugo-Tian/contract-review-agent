$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv\Scripts\python.exe')) { throw 'Run setup.ps1 first.' }
if (!(Test-Path 'frontend\dist\index.html')) { throw 'Run setup.ps1 first to build the frontend.' }
Write-Host 'Open http://127.0.0.1:8000 ; press Ctrl+C to stop.'
Set-Location backend
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
