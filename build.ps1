$ErrorActionPreference = "Stop"

Write-Host "[1/6] Creating virtual environment..."
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

Write-Host "[2/6] Activating environment and installing dependencies..."
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host "[3/6] Building executable with PyInstaller..."
pyinstaller --noconfirm --clean --onefile --windowed --name InventoryOCRApp app.py

Write-Host "[4/6] Preparing bundled Tesseract runtime..."
$tesseractSource = "C:\Users\jasee\AppData\Local\Programs\Tesseract-OCR"
if (-not (Test-Path $tesseractSource)) {
    throw "Tesseract source path not found: $tesseractSource"
}
New-Item -ItemType Directory -Force -Path .\tesseract-runtime | Out-Null
Copy-Item -Path "$tesseractSource\*" -Destination .\tesseract-runtime -Recurse -Force

Write-Host "[5/6] Building installer with Inno Setup..."
$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

$isccPath = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $isccPath) {
    throw "ISCC.exe not found. Install Inno Setup 6, then re-run build.ps1."
}

& $isccPath "installer.iss"

Write-Host "[6/6] Done."
Write-Host "EXE built at: .\dist\InventoryOCRApp.exe"
Write-Host "Installer built at: .\installer-output\InventoryOCRApp-Setup.exe"
