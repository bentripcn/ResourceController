$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $project '.runtime'
& (Join-Path $project 'install_runtime.ps1')
$ffmpeg = Get-ChildItem (Join-Path $runtime 'imageio_ffmpeg/binaries') -Filter 'ffmpeg*.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $ffmpeg) { throw 'imageio-ffmpeg did not provide its bundled ffmpeg.exe' }
$pyinstallerArgs = @(
    '--noconfirm', '--clean', '--windowed', '--name', 'ResourceController',
    '--paths', $project,
    # media_tools discovers imageio-ffmpeg dynamically at runtime; include the
    # module explicitly so a packaged build can still locate its bundled
    # executable instead of relying on a developer machine's PATH.
    '--hidden-import', 'imageio_ffmpeg',
    '--runtime-hook', (Join-Path $project 'pyi_rth_qt.py'),
    '--add-binary', "$($ffmpeg.FullName);imageio_ffmpeg/binaries",
    (Join-Path $project 'qt_app.py')
)
# install_runtime.ps1 installs build tools into the project runtime so a clean
# machine does not need a global PyInstaller installation.
$oldPythonPath = $env:PYTHONPATH
if ($oldPythonPath) {
    $env:PYTHONPATH = "$runtime;$project;$oldPythonPath"
} else {
    $env:PYTHONPATH = "$runtime;$project"
}
python -m PyInstaller @pyinstallerArgs
$buildExit = $LASTEXITCODE
$env:PYTHONPATH = $oldPythonPath
if ($buildExit -ne 0) { throw "PyInstaller failed with exit code $buildExit" }
Write-Host 'Build complete: dist/ResourceController/ResourceController.exe'
