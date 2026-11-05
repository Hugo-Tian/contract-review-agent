param([switch]$NoBrowser, [int]$Port = 8000, [ValidateSet('', 'cn', 'hk')][string]$Region = '')
# Starts the assistant in the background and opens it. Reuses a running instance of this app
# (of the requested region, if given); if the port is held by another program, the next free port is used.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

function Get-Health([int]$p) {
    try { return Invoke-RestMethod -Uri "http://127.0.0.1:$p/api/health" -TimeoutSec 2 } catch { return $null }
}
function Test-OurApp([int]$p) {
    $health = Get-Health $p
    if (!$health -or $health.mode -ne 'single-user-local' -or $health.workflow_engine -ne 'openJiuwen') { return $false }
    return (!$Region -or $health.region -eq $Region)
}
function Test-PortFree([int]$p) {
    return -not (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

try {
    $chosen = $null
    for ($candidate = $Port; $candidate -lt $Port + 20; $candidate++) {
        if (Test-OurApp $candidate) { $chosen = $candidate; break }
        if (Test-PortFree $candidate) {
            $python = Join-Path $projectRoot '.venv-jiuwen\Scripts\python.exe'
            if (!(Test-Path -LiteralPath $python)) { throw 'Python environment missing. Run setup.ps1 first.' }
            if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Frontend build missing. Run setup.ps1 first.' }
            $logDir = Join-Path $projectRoot 'work'
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null
            if ($Region) { $env:REGION = $Region }
            $service = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$candidate",'--no-access-log') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'server-out.log') -RedirectStandardError (Join-Path $logDir 'server-error.log') -PassThru
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                if (Test-OurApp $candidate) { $chosen = $candidate; break }
                $service.Refresh()
                if ($service.HasExited) { break }
                Start-Sleep -Milliseconds 500
            }
            if (!$chosen) { throw "Service failed to start. Check $logDir\server-error.log." }
            break
        }
        if ($candidate -eq $Port) { Write-Host "Port $Port is in use (another program, or this app for another region); trying the next free port." }
    }
    if (!$chosen) { throw "No free port between $Port and $($Port + 19)." }
    $url = "http://127.0.0.1:$chosen"
    Write-Host "Contract assistant is ready: $url"
    if (!$NoBrowser) { Start-Process $url }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if (!$NoBrowser) { Read-Host 'Press Enter to close' | Out-Null }
    exit 1
}
