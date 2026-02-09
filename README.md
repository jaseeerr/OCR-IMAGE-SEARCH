# OCR Image Search App (Windows)

Desktop app built with Tkinter + Tesseract OCR to index images and search text found inside them.

## Features
- Select a folder of images (`.jpg`, `.jpeg`, `.png`)
- OCR all images and cache results in SQLite
- Live text search across OCR results
- Click any result to see a large image preview
- Copy full file path or file name from preview panel
- Skips re-OCR for unchanged images

## Build machine requirements
1. Windows 11
2. Python 3.10+ (added to PATH)
3. Inno Setup 6
4. Tesseract installed at:
   `C:\Users\jasee\AppData\Local\Programs\Tesseract-OCR\tesseract.exe`

## Important files
- `app.py`: main OCR Image Search app
- `requirements.txt`: Python packages
- `install-build-deps.ps1`: installs/updates build dependencies
- `build.ps1`: full build (EXE + bundled Tesseract + setup installer)
- `installer.iss`: Inno Setup script

## Install dependencies
Run in this project folder:

```powershell
.\install-build-deps.ps1
```

## Build everything (recommended)
Run:

```powershell
.\build.ps1
```

Build outputs:
- `dist\InventoryOCRApp.exe`
- `installer-output\InventoryOCRApp-Setup.exe`

## Run locally
```powershell
.\dist\InventoryOCRApp.exe
```

## Share with other users
Send only:
- `installer-output\InventoryOCRApp-Setup.exe`

They install and run it normally on Windows 11.  
No manual Python or Tesseract installation is needed.
