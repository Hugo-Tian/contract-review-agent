param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$url = 'http://127.0.0.1:8000'
function Test-ProjectReady {
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
        return ($health.mode -eq 'single-user-local' -and $null -ne $health.capabilities)
    } catch { return $false }
}
try {
    if (!(Test-ProjectReady)) {
        $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
        if (!(Test-Path -LiteralPath $python)) { throw 'Python environment missing. Run setup.ps1 first.' }
        if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Frontend build missing. Run setup.ps1 first.' }
        $logDir = Join-Path $projectRoot 'work'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        $service = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--no-access-log') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'server-out.log') -RedirectStandardError (Join-Path $logDir 'server-error.log') -PassThru
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if (Test-ProjectReady) { $ready = $true; break }
            $service.Refresh()
            if ($service.HasExited) { break }
            Start-Sleep -Milliseconds 500
        }
        if (!$ready) { throw "Service failed to start. Check $logDir\server-error.log. Port 8000 may be occupied." }
    }
    Write-Host "Contract assistant is ready: $url"
    if (!$NoBrowser) { Start-Process $url }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if (!$NoBrowser) { Read-Host 'Press Enter to close' | Out-Null }
    exit 1
}
