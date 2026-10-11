param([switch]$External, [switch]$Resume)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$runnerPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $runnerPython)) { $runnerPython = 'python' }
$runnerArguments = @((Join-Path $PSScriptRoot 'tools/m2_acceptance.py'))
if ($External) { $runnerArguments += '--external' }
if ($Resume) { $runnerArguments += '--resume' }
& $runnerPython @runnerArguments
exit $LASTEXITCODE
