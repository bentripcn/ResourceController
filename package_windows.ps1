$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $project 'dist/ResourceController'
$release = Join-Path $project 'release'
$archive = Join-Path $release 'ResourceController-1.0.0-windows-x64.zip'

& (Join-Path $project 'build_windows.ps1')
if (-not (Test-Path -LiteralPath (Join-Path $dist 'ResourceController.exe'))) {
    throw "Build did not produce $dist\ResourceController.exe"
}

New-Item -ItemType Directory -Force -Path $release | Out-Null
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Compress-Archive -Path (Join-Path $dist '*') -DestinationPath $archive -CompressionLevel Optimal
Write-Host "Package complete: $archive"
