$ErrorActionPreference = "Stop"

Write-Host "Creating virtual environment (.venv) if missing..."
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

Write-Host "Activating .venv..."
.\.venv\Scripts\Activate.ps1

Write-Host "Upgrading pip..."
python -m pip install --upgrade pip

Write-Host "Installing required packages from requirements.txt..."
pip install -r requirements.txt

Write-Host "Done. Build dependencies are installed."
Write-Host "Next: run .\build.ps1"

