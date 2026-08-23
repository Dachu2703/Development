$ErrorActionPreference = "Stop"
$port = 8504

Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }

Set-Location (Join-Path $PSScriptRoot "..")
& streamlit run auto_shorts/streamlit_app.py --server.port $port
