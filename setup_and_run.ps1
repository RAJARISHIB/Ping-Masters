<#
.SYNOPSIS
One-command local setup and startup for Ping Masters (Windows).

.DESCRIPTION
- Creates Python virtual environment (.venv) if missing
- Installs backend dependencies
- Installs frontend dependencies
- Starts backend and frontend in separate PowerShell windows

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\setup_and_run.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Ensure-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

try {
    $repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $backendDir = Join-Path $repoRoot "backend"
    $uiDir = Join-Path $repoRoot "ping_masters_ui"
    $venvDir = Join-Path $repoRoot ".venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"

    Ensure-Command -Name "npm"

    if (-not $SkipInstall) {
        Write-Step "Preparing Python environment"
        if (-not (Test-Path $venvPython)) {
            if (Get-Command py -ErrorAction SilentlyContinue) {
                & py -3 -m venv $venvDir
            } elseif (Get-Command python -ErrorAction SilentlyContinue) {
                & python -m venv $venvDir
            } else {
                throw "Python was not found. Install Python 3.10+ and rerun."
            }
        }

        Write-Step "Installing backend dependencies"
        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -r (Join-Path $backendDir "requirement.txt")

        Write-Step "Installing frontend dependencies"
        Push-Location $uiDir
        npm install
        Pop-Location
    } else {
        Write-Step "SkipInstall enabled: dependency installation skipped"
    }

    Write-Step "Starting backend server"
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$backendDir'; & '$venvPython' .\main.py"
    ) | Out-Null

    Write-Step "Starting frontend server"
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$uiDir'; npm start"
    ) | Out-Null

    Write-Host ""
    Write-Host "Ping Masters startup initiated." -ForegroundColor Green
    Write-Host "Backend:  http://127.0.0.1:8000/docs"
    Write-Host "Frontend: http://localhost:4200"
} catch {
    Write-Error $_
    exit 1
}

