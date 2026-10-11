param(
    [switch]$External,
    [Parameter(DontShow)]
    [ValidateSet('PASS','STDERR','FAIL')]
    [string]$NativeCommandProbe
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Install the project virtual environment and requirements-lock.txt first.' }
$artifact = Join-Path $PSScriptRoot 'artifacts\m1_acceptance'
New-Item -ItemType Directory -Path $artifact -Force | Out-Null
$results = [ordered]@{}

function ConvertTo-NativeArgument([AllowEmptyString()][string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes++; continue }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (2 * $slashes + 1)))
            [void]$builder.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) { [void]$builder.Append(('\' * $slashes)); $slashes = 0 }
        [void]$builder.Append([string]$character)
    }
    if ($slashes -gt 0) { [void]$builder.Append(('\' * (2 * $slashes))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-PythonLogged([string[]]$Arguments, [string]$LogPath) {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $python
    $startInfo.WorkingDirectory = $PSScriptRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $startInfo.StandardOutputEncoding = $utf8
    $startInfo.StandardErrorEncoding = $utf8
    if ($null -ne $startInfo.PSObject.Properties['ArgumentList']) {
        foreach ($argument in $Arguments) { [void]$startInfo.ArgumentList.Add($argument) }
    } else {
        $startInfo.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $exitCode = $process.ExitCode
    } catch {
        $failure = "Unable to start Python acceptance command: $($_.Exception.Message)"
        [System.IO.File]::WriteAllText($LogPath, $failure, $utf8)
        [Console]::Error.WriteLine($failure)
        return 9009
    } finally {
        $process.Dispose()
    }

    $logText = $stdout
    if ($stderr.Length -gt 0) {
        if ($logText.Length -gt 0 -and -not $logText.EndsWith("`n")) { $logText += "`r`n" }
        $logText += "[stderr]`r`n$stderr"
    }
    [System.IO.File]::WriteAllText($LogPath, $logText, $utf8)
    if ($stdout.Length -gt 0) { [Console]::Out.Write($stdout) }
    if ($stderr.Length -gt 0) { [Console]::Error.Write($stderr) }
    return [int]$exitCode
}

function Run-Check([string]$Name, [string[]]$Arguments) {
    $log = Join-Path $artifact ($Name.ToLower() + '.log')
    $exitCode = Invoke-PythonLogged $Arguments $log
    $results[$Name] = if ($exitCode -eq 0) { 'PASS' } else { 'FAIL' }
}

if ($NativeCommandProbe) {
    $probeArguments = switch ($NativeCommandProbe) {
        'PASS' { @('-c', 'print("probe stdout")') }
        'STDERR' { @('-c', 'import sys; print("probe stdout"); print("probe stderr", file=sys.stderr)') }
        'FAIL' { @('-c', 'import sys; print("probe failure", file=sys.stderr); sys.exit(7)') }
    }
    Run-Check 'NATIVE_COMMAND_PROBE' $probeArguments
    Write-Host ('NATIVE_COMMAND_PROBE: ' + $results['NATIVE_COMMAND_PROBE'])
    exit $(if ($results['NATIVE_COMMAND_PROBE'] -eq 'PASS') { 0 } else { 1 })
}
Push-Location -LiteralPath $PSScriptRoot
try {
    $productionSnapshot = Join-Path $artifact 'production_learning_before.json'
    & $python 'tools/production_data_guard.py' '--capture' $productionSnapshot | Out-Null
    Run-Check 'FOUNDATION' @('-m','unittest','tests.test_foundation','-v')
    Run-Check 'REPLAY' @('-m','unittest','tests.test_replay','-v')
    Run-Check 'LEARNING' @('-m','unittest','tests.test_m1.LearningTests','-v')
    Run-Check 'DAILY_AI' @('-m','unittest','tests.test_m1.DailyAITests','-v')
    Run-Check 'DAILY_AI_UI' @('-m','unittest','tests.test_m1.DailyAIUITests','-v')
    Run-Check 'HUMAN_FIRST_AI_GUARD' @('-m','unittest','tests.test_m1.HumanFirstAIGuardTests','-v')
    Run-Check 'HUMAN_VS_AI_UI' @('-m','unittest','tests.test_m1.HumanVsAIUITests','-v')
    Run-Check 'LEARNING_UI_RUNTIME' @('-m','unittest','tests.test_m1.LearningUIRuntimeTests','-v')
    Run-Check 'CASE_SELECTOR_SYNC' @('-m','unittest','tests.test_m1.CaseSelectorSyncTests','-v')
    Run-Check 'REPLAY_ACCOUNT' @('-m','unittest','tests.test_m1.AccountTests','-v')
    Run-Check 'FUTURE_GUARD' @('-m','unittest','tests.test_m1.FutureGuardTests','-v')
    Run-Check 'INTEGRATION' @('-m','unittest','tests.test_m1.IntegrationTests','-v')
    Run-Check 'LEGACY_REGRESSION' @('-m','unittest','tests.test_m1.LegacyRegressionTests','-v')
    Run-Check 'TEST_DATA_ISOLATION' @('-m','unittest','tests.test_m11.TestDataIsolationTests','-v')
    Run-Check 'DIRECT_LEARNING_CREATE' @('-m','unittest','tests.test_m11.DirectLearningCreateTests','-v')
    Run-Check 'TRAINING_REPLAY_ISOLATION' @('-m','unittest','tests.test_m11.TrainingReplayIsolationTests','-v')
    Run-Check 'ACCOUNT_ACTION_UX' @('-m','unittest','tests.test_m11.AccountActionUXTests','-v')
    Run-Check 'CASE_LIFECYCLE' @('-m','unittest','tests.test_m11.CaseLifecycleTests','-v')
    Run-Check 'AI_EVALUATION' @('-m','unittest','tests.test_m11.AIEvaluationTests','-v')
    Run-Check 'CASE_FILTER' @('-m','unittest','tests.test_m11.CaseFilterTests','-v')
    Run-Check 'DECISION_FILTER' @('-m','unittest','tests.test_m11.DecisionFilterTests','-v')
    $results['FILTERS'] = if ($results['CASE_FILTER'] -eq 'PASS' -and $results['DECISION_FILTER'] -eq 'PASS') { 'PASS' } else { 'FAIL' }
    Run-Check 'UI_LANGUAGE' @('-m','unittest','tests.test_m11.UILanguageTests','-v')
    if ($External) {
        Run-Check 'EXTERNAL' @('tools/m1_external.py')
        $externalResult = Get-Content -LiteralPath (Join-Path $artifact 'external.json') -Raw | ConvertFrom-Json
        $results['REAL_MARKET'] = $externalResult.REAL_MARKET
        $results['DEEPSEEK'] = $externalResult.DEEPSEEK
        $results['API_EXTERNAL'] = $externalResult.API_INTEGRATION
        # CUA owns actual browser interaction; stale/missing evidence makes external acceptance fail.
        Run-Check 'BROWSER_PAGEERROR_SCAN' @('tools/m1_browser_evidence.py')
        $results['BROWSER'] = $results['BROWSER_PAGEERROR_SCAN']
        $results['BROWSER_RUNTIME'] = $results['BROWSER_PAGEERROR_SCAN']
    } else {
        $results['REAL_MARKET']='NOT_RUN'; $results['DEEPSEEK']='NOT_RUN'; $results['BROWSER_PAGEERROR_SCAN']='NOT_RUN'; $results['BROWSER']='NOT_RUN'; $results['BROWSER_RUNTIME']='NOT_RUN'
    }
    Run-Check 'PRODUCTION_DATA_UNCHANGED' @('tools/production_data_guard.py','--verify',$productionSnapshot)
    Run-Check 'LEGACY' @('trading_lab.py','--verify-baselines')
    $failed = @($results.Values | Where-Object { $_ -eq 'FAIL' }).Count -gt 0
    if ($External -and @($results.Values | Where-Object { $_ -ne 'PASS' }).Count -gt 0) { $failed = $true }
    $results['OVERALL'] = if ($failed) { 'FAIL' } else { 'PASS' }
    $summary = [ordered]@{ scope = if ($External) { 'EXTERNAL' } else { 'OFFLINE_ONLY' }; timestamp = [DateTimeOffset]::UtcNow.ToString('o'); results = $results }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $artifact 'summary.json') -Encoding utf8
    Write-Host "`nM1 ACCEPTANCE SUMMARY"
    foreach ($entry in $results.GetEnumerator()) { Write-Host ($entry.Key + ': ' + $entry.Value) }
    if (-not $External) { Write-Host 'Offline PASS does not claim real DeepSeek or browser acceptance.' }
    $code = if ($failed) { 1 } else { 0 }
} finally { Pop-Location }
exit $code
