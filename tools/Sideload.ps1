<#
  Registers (or removes) the add-in manifest with desktop Word for the current user,
  the same developer sideloading that Microsoft's office-addin-debugging tool uses.
  Close Word first, run this, then reopen Word: CD Fit appears on the Home tab.

    .\tools\Sideload.ps1                         # uses manifest.hosted.xml if present, else manifest.xml
    .\tools\Sideload.ps1 -Manifest .\manifest.xml
    .\tools\Sideload.ps1 -Remove
#>
param([string]$Manifest, [switch]$Remove)
$root = Split-Path -Parent $PSScriptRoot
if (-not $Manifest) {
  $Manifest = Join-Path $root 'manifest.hosted.xml'
  if (-not (Test-Path $Manifest)) { $Manifest = Join-Path $root 'manifest.xml' }
}
$Manifest = (Resolve-Path $Manifest).Path
$id = ([xml](Get-Content -Raw -Encoding UTF8 $Manifest)).OfficeApp.Id
$key = 'HKCU:\Software\Microsoft\Office\16.0\WEF\Developer'
if ($Remove) {
  if (Test-Path $key) { Remove-ItemProperty -Path $key -Name $id -ErrorAction SilentlyContinue }
  Write-Host "CD Fit ($id) removed. Restart Word."
  return
}
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
New-ItemProperty -Path $key -Name $id -Value $Manifest -PropertyType String -Force | Out-Null
Write-Host "CD Fit registered from $Manifest"
Write-Host "Restart Word and look for 'CD Fit' on the Home tab."
