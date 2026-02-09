import os
from PIL import Image
import pytesseract

# 👇 Change this ONLY if tesseract is not in PATH
pytesseract.pytesseract.tesseract_cmd = r"C:\Users\jasee\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"

# Folder containing images
IMAGE_FOLDER = "sampleFew"

# Supported image extensions
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".tiff")

for filename in os.listdir(IMAGE_FOLDER):
    if filename.lower().endswith(IMAGE_EXTENSIONS):
        image_path = os.path.join(IMAGE_FOLDER, filename)

        print("=" * 60)
        print(f"OCR Result for: {filename}")
        print("=" * 60)

        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img)

            print(text.strip() if text.strip() else "[NO TEXT DETECTED]")

        except Exception as e:
            print(f"[ERROR] Failed to process {filename}: {e}")
