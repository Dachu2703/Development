$ErrorActionPreference = "Stop"
$port = 8504
$projectRoot = Join-Path $PSScriptRoot ".."
$logDirectory = Join-Path $projectRoot "logs"
$stdoutLog = Join-Path $logDirectory "streamlit.stdout.log"
$stderrLog = Join-Path $logDirectory "streamlit.stderr.log"

Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$streamlit = (Get-Command streamlit -ErrorAction Stop).Source
$process = Start-Process `
    -FilePath $streamlit `
    -ArgumentList @("run", "auto_shorts/streamlit_app.py", "--server.port", $port) `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Write-Host "Streamlit started with PID $($process.Id) at http://localhost:$port"
