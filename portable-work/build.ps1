param([string]$Output='',[string]$Artifact='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Hash([string]$p){$s=[IO.File]::OpenRead($p);$h=[Security.Cryptography.SHA256]::Create();try{return ([BitConverter]::ToString($h.ComputeHash($s))).Replace('-','').ToLowerInvariant()}finally{$s.Dispose();$h.Dispose()}}
function Safe([string]$p){$p=[IO.Path]::GetFullPath($p);if($p -ne $root -and -not $p.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Path outside project'};while($p){if(Test-Path -LiteralPath $p){if((Get-Item -Force -LiteralPath $p).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked path refused'}};$p=[IO.Path]::GetDirectoryName($p)}}
try{
 Set-Location -LiteralPath $root
 Safe $root
 $lock=Get-Content -LiteralPath (Join-Path $root 'dev/runtime-lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
 if(-not $Artifact){$Artifact=Join-Path $root ('.dev/artifacts/'+$lock.artifact.filename)}
 Safe $Artifact
 if((Hash $Artifact) -ne $lock.artifact.sha256){throw 'Runtime ZIP SHA mismatch'}
 $runtime=Join-Path $root '.dev/runtime';Safe $runtime
 if(-not(Test-Path -LiteralPath $runtime)){throw 'Fixed runtime missing. Run Setup-Dev.cmd with the locked local ZIP first.'}
 $files=@(Get-ChildItem -LiteralPath $runtime -Recurse -Force)
 foreach($f in $files){Safe $f.FullName}
 if(@($files | Where-Object {-not $_.PSIsContainer}).Count -ne $lock.files.Count){throw 'Runtime file count mismatch'}
 foreach($row in $lock.files){$p=Join-Path $runtime $row.path;Safe $p;if((Get-Item -LiteralPath $p).Length -ne $row.bytes -or (Hash $p) -ne $row.sha256){throw ('Runtime content mismatch: '+$row.path)}}
 if(-not $Output){$Output=Join-Path $root ('.dev/builds/TradingLabPortable-'+[guid]::NewGuid().ToString('N'))}
 Safe $Output
 $env:PYTHONHOME=$null;$env:PYTHONPATH=$null;$env:PYTHONDONTWRITEBYTECODE='1';$env:PYTHONUTF8='1';$env:NODE_OPTIONS=$null
 & (Join-Path $runtime 'python/python.exe') -I -B -X utf8 (Join-Path $PSScriptRoot 'build_portable.py') --output $Output --artifact $Artifact
 exit $LASTEXITCODE
}catch{Write-Output ('BUILD_BLOCKED: '+$_.Exception.Message);exit 1}
