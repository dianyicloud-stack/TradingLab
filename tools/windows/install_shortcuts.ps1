$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$entries = @(
    @{Name='TradingLab 启动'; Script='TradingLab_Start.cmd'; Icon=24},
    @{Name='TradingLab 停止'; Script='TradingLab_Stop.cmd'; Icon=27},
    @{Name='TradingLab 状态'; Script='TradingLab_Status.cmd'; Icon=23}
)
foreach ($entry in $entries) {
    $path = Join-Path $desktop ($entry.Name + '.lnk')
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = Join-Path $PSScriptRoot $entry.Script
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = $entry.Name
    $shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',' + $entry.Icon
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Output $path
}
