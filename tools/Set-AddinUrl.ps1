<#
  Writes manifest.hosted.xml pointing at the HTTPS address where the src folder is hosted.
  Example:  .\tools\Set-AddinUrl.ps1 -BaseUrl https://yourname.github.io/cdfit
#>
param([Parameter(Mandatory = $true)][string]$BaseUrl)
$BaseUrl = $BaseUrl.TrimEnd('/')
if ($BaseUrl -notmatch '^https://') { throw "Office add-ins must be served over HTTPS." }
$root = Split-Path -Parent $PSScriptRoot
$text = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'manifest.xml')
$out = Join-Path $root 'manifest.hosted.xml'
[IO.File]::WriteAllText($out, $text.Replace('https://localhost:3000', $BaseUrl), (New-Object Text.UTF8Encoding $false))
Write-Host "Wrote $out  (add-in URL: $BaseUrl/taskpane.html)"
