$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $project '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
python -m pip install --upgrade --target $runtime -r (Join-Path $project 'requirements.txt')
Write-Host "Runtime dependencies installed in $runtime"
Write-Host "FFmpeg: $([bool](Get-ChildItem (Join-Path $runtime 'imageio_ffmpeg/binaries') -Filter 'ffmpeg*' -File -ErrorAction SilentlyContinue))"
