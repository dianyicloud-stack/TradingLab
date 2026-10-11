param([int]$Port=8765)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -B (Join-Path $PSScriptRoot 'runtime_control.py') restart web --port $Port
exit $LASTEXITCODE
