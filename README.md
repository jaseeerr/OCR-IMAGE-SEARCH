# Inventory OCR App (Windows)

Tkinter desktop app for OCR indexing/search of inventory images with image preview.

## Requirements (build machine)
1. Windows 11
2. Python 3.10+ (added to PATH)
3. Inno Setup 6
4. Tesseract OCR installed at:
   `C:\Users\jasee\AppData\Local\Programs\Tesseract-OCR\tesseract.exe`

## Project files
- `app.py`: main desktop app
- `requirements.txt`: Python dependencies
- `install-build-deps.ps1`: installs build dependencies into `.venv`
- `build.ps1`: full build script (EXE + Tesseract bundle + installer EXE)
- `installer.iss`: Inno Setup installer definition

## Install dependencies
From this folder, run:

```powershell
.\install-build-deps.ps1
```

## Build setup installer
From this folder, run:

```powershell
.\build.ps1
```

This generates:
- `dist\InventoryOCRApp.exe`
- `installer-output\InventoryOCRApp-Setup.exe`

## Run locally (without installer)
```powershell
.\dist\InventoryOCRApp.exe
```

## Install and run on another PC
1. Copy `installer-output\InventoryOCRApp-Setup.exe` to the other PC.
2. Run the setup.
3. Launch **Inventory OCR App** from Start Menu/Desktop shortcut.

No manual Python or Tesseract install is needed on end-user machines.
