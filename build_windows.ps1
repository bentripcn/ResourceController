$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $project '.runtime'
& (Join-Path $project 'install_runtime.ps1')
$ffmpeg = Get-ChildItem (Join-Path $runtime 'imageio_ffmpeg/binaries') -Filter 'ffmpeg*.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $ffmpeg) { throw 'imageio-ffmpeg did not provide its bundled ffmpeg.exe' }
$icon = Join-Path $project 'assets/resource-organizer-logo.ico'
if (-not (Test-Path -LiteralPath $icon)) { throw "Application icon not found: $icon" }
$pyinstallerArgs = @(
    '--noconfirm', '--clean', '--noupx', '--windowed', '--name', 'ResourceController', '--icon', $icon,
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

# Qt 6.11 expects the Windows ICU ABI (icuuc.dll).  The PyInstaller Qt hook
# can otherwise pick up an unrelated ICU from tools such as Poppler on PATH;
# that DLL exports version-suffixed symbols and makes Qt6Core fail with
# WinError 127 (which PySide reports only as "QtWidgets DLL not found").
# Ship the Windows ICU binary beside Qt so the package does not depend on the
# target machine's system ICU installation.
$qtInternal = Join-Path $project 'dist/ResourceController/_internal'
$systemIcu = Join-Path $env:WINDIR 'System32/icuuc.dll'
if (Test-Path -LiteralPath $systemIcu) {
    Copy-Item -LiteralPath $systemIcu -Destination (Join-Path $qtInternal 'icuuc.dll') -Force
}
# Remove an unrelated versioned ICU data file collected from another toolchain.
Remove-Item -LiteralPath (Join-Path $qtInternal 'icudt78.dll') -Force -ErrorAction SilentlyContinue
Write-Host 'Build complete: dist/ResourceController/ResourceController.exe'
