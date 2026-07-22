[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VirtualEnvironment = Join-Path $ProjectRoot ".venv"
$Python = Join-Path $VirtualEnvironment "Scripts\python.exe"

Push-Location $ProjectRoot
try {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "The Python launcher 'py' was not found. Install 64-bit Python 3.12 first."
    }

    Write-Host "Creating the Python 3.12 build environment..."
    & py -3.12 -m venv $VirtualEnvironment

    Write-Host "Installing the application and Windows build tools..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install ".[build]"

    Write-Host "Building FAI-Geometry-Explorer.exe..."
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name "FAI-Geometry-Explorer" `
        --collect-data "fai_explorer" `
        --collect-data "ppigrf" `
        "fai_gui_launcher.py"

    Write-Host ""
    Write-Host "Windows executable created at:"
    Write-Host (Join-Path $ProjectRoot "dist\FAI-Geometry-Explorer.exe")
}
finally {
    Pop-Location
}
