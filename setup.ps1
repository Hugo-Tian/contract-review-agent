$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv; if ($LASTEXITCODE) { throw 'venv failed' } }
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements-lock.txt
if ($LASTEXITCODE) { throw 'Python dependencies failed' }
if (!(Test-Path 'backend\.env')) { Copy-Item backend\.env.example backend\.env }
& .\.venv\Scripts\python.exe scripts\create_examples.py
if ($LASTEXITCODE) { throw 'Example generation failed' }
Push-Location frontend
try {
    npm.cmd ci
    if ($LASTEXITCODE) { throw 'npm ci failed' }
    npm.cmd run build
    if ($LASTEXITCODE) { throw 'Frontend build failed' }
} finally { Pop-Location }
Write-Host 'Ready. Double click start.bat or run .\start.ps1'
