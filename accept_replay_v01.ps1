param([switch]$External, [string]$PythonPath)
$ErrorActionPreference = 'Stop'
if ($PythonPath) { $replayPython = (Resolve-Path -LiteralPath $PythonPath).Path }
elseif (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')) { $replayPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
else { $replayPython = (Get-Command python -ErrorAction Stop).Source }
$results = [ordered]@{}
function Run-Check([string]$Name, [string[]]$Arguments) {
    Write-Host "`n$Name"
    & $replayPython @Arguments
    $results[$Name] = if ($LASTEXITCODE -eq 0) { 'PASS' } else { 'FAIL' }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    Run-Check 'FOUNDATION' @('-m','unittest','tests.test_foundation','-v')
    Run-Check 'LEGACY BASELINE' @('trading_lab.py','--verify-baselines')
    Run-Check 'REPLAY UNIT' @('-m','unittest','tests.test_replay','-v')
    Run-Check 'FUTURE GUARD' @('-m','unittest','tests.test_replay.FutureGuardTests','tests.test_replay.ApiTests.test_api_future_guard_all_views_and_direct_storage_denied','-v')
    Run-Check 'FIXTURE' @('tools/replay_acceptance.py','--fixture')
    if ($External) {
        Run-Check 'REAL MARKET' @('tools/replay_acceptance.py','--real','--symbol','bj920161','--start','2026-08-01','--end','2026-09-04','--visible','2026-08-14')
        Run-Check 'DEEPSEEK' @('tools/deepseek_smoke.py')
    } else {
        $results['REAL MARKET'] = 'NOT_RUN'
        $results['DEEPSEEK'] = 'NOT_RUN'
    }
    Run-Check 'LEGACY FINAL' @('trading_lab.py','--verify-baselines')
    $failed = @($results.Values | Where-Object { $_ -eq 'FAIL' }).Count -gt 0
    $results['OVERALL'] = if ($failed) { 'FAIL' } else { 'PASS' }
    Write-Host "`nACCEPTANCE SUMMARY ($(@('OFFLINE','EXTERNAL')[[int]$External.IsPresent]))"
    foreach ($entry in $results.GetEnumerator()) { Write-Host ($entry.Key + ': ' + $entry.Value) }
    if (-not $External) { Write-Host 'Offline checks only. REAL MARKET / DEEPSEEK require -External; browser acceptance is separate.' }
    $resultCode = if ($failed) { 1 } else { 0 }
} finally { Pop-Location }
exit $resultCode
