param([ValidateSet('setup','check','start','stop')][string]$Action='check', [string]$Artifact='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Set-Location -LiteralPath $root
function File-Hash([string]$p) {
  $stream=[IO.File]::OpenRead($p);$hasher=[Security.Cryptography.SHA256]::Create();try {return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-','').ToLowerInvariant()} finally {$stream.Dispose();$hasher.Dispose()}
}
function Safe-Path([string]$p) {
  $full=[IO.Path]::GetFullPath($p)
  if ($full -ne $root -and -not $full.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {throw '路径越出工程边界'}
  $item=$full
  while ($item) {
    if (Test-Path -LiteralPath $item) {if ((Get-Item -Force -LiteralPath $item).Attributes -band [IO.FileAttributes]::ReparsePoint) {throw ('检测到链接：'+$item)}}
    $item=[IO.Path]::GetDirectoryName($item)
  }
}
function Check-Runtime([string]$dir,$lock) {
  Safe-Path $dir
  $actual=@(Get-ChildItem -LiteralPath $dir -Force -Recurse)
  foreach($p in $actual){if($p.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Runtime 含链接'}}
  if (@($actual | Where-Object {-not $_.PSIsContainer}).Count -ne $lock.files.Count){throw 'Runtime 文件数不符'}
  foreach($row in $lock.files){$p=Join-Path $dir $row.path;Safe-Path $p
    if (-not(Test-Path -LiteralPath $p -PathType Leaf) -or (Get-Item -LiteralPath $p).Length -ne $row.bytes -or (File-Hash $p) -ne $row.sha256){throw ('Runtime 校验失败：'+$row.path)}
  }
}
try {
  if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64'){throw '只支持 Windows x64'}
  Safe-Path $root
  $lock=Get-Content -LiteralPath (Join-Path $root 'dev/runtime-lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($lock.python -ne '3.12.14' -or $lock.node -ne '24.19.0'){throw '版本锁不符'}
  $dev=Join-Path $root '.dev';Safe-Path $dev
  $runtime=Join-Path $dev 'runtime'
  if ($Action -eq 'setup') {
    if (-not $Artifact){$Artifact=Join-Path $dev ('artifacts/'+$lock.artifact.filename)}
    if (-not(Test-Path -LiteralPath $Artifact -PathType Leaf)){throw '缺少固定制品。请将 runtime-lock.json 指定 ZIP 放入 .dev/artifacts，或使用 -Artifact 指定本地文件；不回退系统 Python'}
    if((File-Hash $Artifact) -ne $lock.artifact.sha256){throw '制品 SHA-256 不符，请重新获取已审核制品'}
    if((Get-PSDrive -Name ([IO.Path]::GetPathRoot($root).Substring(0,1))).Free -lt 1GB){throw '磁盘可用空间不足 1 GiB'}
    New-Item -ItemType Directory -Force -Path $dev | Out-Null
    $probe=Join-Path $dev ('write-check-'+[guid]::NewGuid());[IO.File]::WriteAllText($probe,'probe');Remove-Item -LiteralPath $probe
    if(-not(Test-Path -LiteralPath $runtime)){
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      $zip=[IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($Artifact))
      $stage=Join-Path $dev ('runtime-stage-'+[guid]::NewGuid());Safe-Path $stage
      try {
        $expected=@{};foreach($row in $lock.files){$expected[$row.path]=$row}
        $seen=@{}
        foreach($entry in $zip.Entries){
          $name=$entry.FullName
          if($name -match '(^/|\\|:|(^|/)\.\.?(/|$)|[. ]($|/))' -or -not $expected.ContainsKey($name) -or $seen.ContainsKey($name)){throw ('压缩包路径不安全或清单外文件：'+$name)}
          $mode=($entry.ExternalAttributes -shr 16) -band 0xF000
          if($mode -eq 0xA000 -or ($entry.ExternalAttributes -band 0x400) -ne 0 -or $entry.Length -ne $expected[$name].bytes){throw '压缩包链接或大小不合法'}
          $seen[$name]=$true
        }
        if($seen.Count -ne $expected.Count){throw '压缩包缺少文件'}
        New-Item -ItemType Directory -Path $stage | Out-Null
        foreach($entry in $zip.Entries){$dest=Join-Path $stage $entry.FullName;Safe-Path $dest
          New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($dest)) | Out-Null
          [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$dest,$false)
        }
        Check-Runtime $stage $lock
        Move-Item -LiteralPath $stage -Destination $runtime
      } finally {$zip.Dispose()}
    }
  }
  if(-not(Test-Path -LiteralPath $runtime)){throw '开发 Runtime 不存在，请先运行 Setup-Dev.cmd'}
  Check-Runtime $runtime $lock
  foreach($key in @('PYTHONHOME','PYTHONPATH','NODE_OPTIONS','NODE_PATH')){Remove-Item -LiteralPath ('Env:'+ $key) -ErrorAction SilentlyContinue}
  $env:PYTHONDONTWRITEBYTECODE='1';$env:PYTHONUTF8='1';$env:PYTHONNOUSERSITE='1'
  $python=Join-Path $runtime 'python/python.exe'
  if($Action -ne 'setup'){$python=Join-Path $root '.venv/Scripts/python.exe';Safe-Path $python;if(-not(Test-Path -LiteralPath $python)){throw '开发虚拟环境缺失，请运行 Setup-Dev.cmd'}}
  if($Action -ne 'setup'){
    $sealPath=Join-Path $dev 'venv-seal.json';Safe-Path $sealPath
    $seal=Get-Content -LiteralPath $sealPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if($seal.project -ne $root -or $seal.runtime_sha256 -ne $lock.artifact.sha256){throw '虚拟环境归属或版本不符'}
    $venvItems=@(Get-ChildItem -LiteralPath (Join-Path $root '.venv') -Force -Recurse)
    foreach($item in $venvItems){if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw '虚拟环境含链接'}}
    if(@($venvItems | Where-Object {-not $_.PSIsContainer}).Count -ne @($seal.files.PSObject.Properties).Count){throw '虚拟环境出现缺失或清单外文件'}
    foreach($row in $seal.files.PSObject.Properties){$p=Join-Path (Join-Path $root '.venv') $row.Name;Safe-Path $p;if((File-Hash $p) -ne $row.Value){throw ('虚拟环境校验失败：'+$row.Name)}}
  }
  & $python -I -B -X utf8 (Join-Path $PSScriptRoot 'control.py') $Action
  exit $LASTEXITCODE
} catch {
  [Console]::Error.WriteLine('FAIL：'+$_.Exception.Message+'。已停止；请检查锁清单、日志与项目权限。不要换用全局环境。')
  exit 1
}
