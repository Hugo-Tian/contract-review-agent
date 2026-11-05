$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv-jiuwen\Scripts\python.exe')) { py -3.11 -m venv .venv-jiuwen; if ($LASTEXITCODE) { throw 'venv failed' } }
& .\.venv-jiuwen\Scripts\python.exe -m pip install -r backend\requirements-lock.txt
if ($LASTEXITCODE) { throw 'Python dependencies failed' }
if (!(Test-Path 'backend\.env')) { Copy-Item backend\.env.example backend\.env }
# Hong Kong edition OCR models (about 86 MB, SHA-256 checked against rapidocr's manifest)
& .\.venv-jiuwen\Scripts\python.exe scripts\fetch_ocr_models.py
if ($LASTEXITCODE) { throw 'OCR model download failed; rerun setup.ps1 or scripts\fetch_ocr_models.py' }
& .\.venv-jiuwen\Scripts\python.exe scripts\create_examples.py
if ($LASTEXITCODE) { throw 'Example generation failed' }
Push-Location frontend
try {
    npm.cmd ci
    if ($LASTEXITCODE) { throw 'npm ci failed' }
    npm.cmd run build
    if ($LASTEXITCODE) { throw 'Frontend build failed' }
} finally { Pop-Location }
Write-Host 'Ready. Double click start.bat or run .\start.ps1'
