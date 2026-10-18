$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $project 'dist/ResourceController'
$release = Join-Path $project 'release'
$versionLine = Get-Content -LiteralPath (Join-Path $project 'pyproject.toml') |
    Where-Object { $_ -match '^\s*version\s*=\s*"([^"]+)"' } |
    Select-Object -First 1
if (-not $versionLine -or $versionLine -notmatch '"([^"]+)"') {
    throw 'Could not determine the application version from pyproject.toml'
}
$version = $Matches[1]
$archive = Join-Path $release "ResourceController-$version-windows-x64.zip"

& (Join-Path $project 'build_windows.ps1')
if (-not (Test-Path -LiteralPath (Join-Path $dist 'ResourceController.exe'))) {
    throw "Build did not produce $dist\ResourceController.exe"
}

New-Item -ItemType Directory -Force -Path $release | Out-Null
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
 # Include the application directory itself so extracting the archive creates
 # ResourceController\<application files> instead of scattering files into the
 # user's current extraction directory.
Compress-Archive -Path $dist -DestinationPath $archive -CompressionLevel Optimal
Write-Host "Package complete: $archive"
