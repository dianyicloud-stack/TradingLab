param([ValidateSet('start','stop','check')][string]$Action='check')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$root=$PSScriptRoot
function Hash([string]$p){$s=[IO.File]::OpenRead($p);$h=[Security.Cryptography.SHA256]::Create();try{return ([BitConverter]::ToString($h.ComputeHash($s))).Replace('-','').ToLowerInvariant()}finally{$s.Dispose();$h.Dispose()}}
function Safe([string]$p){$p=[IO.Path]::GetFullPath($p);if($p -ne $root -and -not $p.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Path outside package'};while($p){if(Test-Path -LiteralPath $p){if((Get-Item -Force -LiteralPath $p).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked path refused'}};$p=[IO.Path]::GetDirectoryName($p)}}
try{
 Safe $root
 if(Test-Path -LiteralPath (Join-Path $root 'BUILD_INCOMPLETE')){throw 'Incomplete build'}
 if(Test-Path -LiteralPath (Join-Path $root 'MIGRATION_INCOMPLETE')){throw 'Incomplete migration'}
 $lock=Get-Content -LiteralPath (Join-Path $root 'runtime/files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
 foreach($row in $lock.PSObject.Properties){$p=Join-Path $root $row.Name;Safe $p;if((Hash $p) -ne $row.Value){throw ('Integrity mismatch: '+$row.Name)}}
 $runtime=Get-Content -LiteralPath (Join-Path $root 'runtime/runtime-lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
 $actual=@(Get-ChildItem -LiteralPath (Join-Path $root 'runtime/python'),(Join-Path $root 'runtime/node') -Recurse -Force)
 foreach($p in $actual){Safe $p.FullName}
 if(@($actual | Where-Object {-not $_.PSIsContainer}).Count -ne $runtime.files.Count){throw 'Unexpected runtime files'}
 $env:PYTHONHOME=$null;$env:PYTHONPATH=$null;$env:PYTHONUTF8='1';$env:PYTHONDONTWRITEBYTECODE='1';$env:NODE_OPTIONS=$null
 Set-Location -LiteralPath $root
 & (Join-Path $root 'runtime/python/python.exe') -I -B -X utf8 (Join-Path $root 'portable_control.py') $Action --deep --no-browser
 exit $LASTEXITCODE
}catch{Write-Output ('PORTABLE_BLOCKED: '+$_.Exception.Message);exit 1}
