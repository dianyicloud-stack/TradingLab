param(
    [ValidateRange(0,65535)][int]$Port = 8765,
    [string]$PythonPath,
    [switch]$InitOnly,
    [switch]$VerifyBaselines,
    [switch]$Test,
    [switch]$CheckAgent,
    [switch]$StopAgent
)
$ErrorActionPreference = 'Stop'
$pythonArguments = @()
if ($PythonPath) {
    $interpreter = (Resolve-Path -LiteralPath $PythonPath).Path
} elseif (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')) {
    $interpreter = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $interpreter = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $interpreter = (Get-Command py).Source
    $pythonArguments = @('-3')
} else {
    throw 'Python 3.11+ not found. Install locally, recreate .venv, and install requirements-lock.txt. Do not copy another PC venv.'
}
& $interpreter @pythonArguments -c "import sys; assert sys.version_info >= (3,11)"
if ($LASTEXITCODE -ne 0) { throw 'Python/venv is unusable. Recreate .venv with local Python 3.11+; see docs/MACHINE_MIGRATION.md.' }
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($Test) {
        & $interpreter @pythonArguments -m unittest discover -s tests -v
    } elseif (-not ($InitOnly -or $VerifyBaselines -or $CheckAgent -or $StopAgent)) {
        # Daily entry delegates lifecycle to Supervisor; trading_lab.py remains internal.
        & $interpreter @pythonArguments -B (Join-Path $PSScriptRoot 'tools/runtime_control.py') start --desktop --port $Port
    } else {
        $launchArguments = @((Join-Path $PSScriptRoot 'trading_lab.py'), '--port', $Port)
        if ($InitOnly) { $launchArguments += '--init-only' }
        if ($VerifyBaselines) { $launchArguments += '--verify-baselines' }
        if ($CheckAgent) { $launchArguments += '--check-agent' }
        if ($StopAgent) { $launchArguments += '--stop-agent' }
        & $interpreter @pythonArguments @launchArguments
    }
    $resultCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $resultCode
