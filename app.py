import os
import sys
import threading
import sqlite3
import traceback
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageOps
import pytesseract
from shutil import which

# Supported image file extensions.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

# SQLite database file (stored next to executable/script).
DB_NAME = "inventory_ocr.db"
DEFAULT_MAX_OCR_WORKERS = max(1, min(8, (os.cpu_count() or 4)))

# Tesseract path taken from existing script.py on this device.
DEVICE_TESSERACT_PATH = r"C:\Users\jasee\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"


def app_base_dir() -> str:
    """Return folder where app executable (or script) is located."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resolve_tesseract_path() -> str | None:
    """
    Resolve tesseract.exe in this order:
    1) Bundled runtime: <app>/tesseract/tesseract.exe
    2) Device-specific install path from script.py
    3) tesseract found in PATH
    """
    bundled = os.path.join(app_base_dir(), "tesseract", "tesseract.exe")
    candidates = [bundled, DEVICE_TESSERACT_PATH, which("tesseract") or ""]

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def db_path() -> str:
    """Return absolute path of SQLite DB file."""
    return os.path.join(app_base_dir(), DB_NAME)


def init_db() -> None:
    """Create required database schema."""
    conn = sqlite3.connect(db_path())
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ocr_index (
                file_path   TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL,
                file_name   TEXT NOT NULL,
                file_mtime  REAL NOT NULL,
                file_size   INTEGER NOT NULL,
                ocr_text    TEXT NOT NULL,
                search_text TEXT NOT NULL DEFAULT '',
                ocr_error   TEXT,
                indexed_at  TEXT NOT NULL
            )
            """
        )
        # Backward-compatible migration for existing DBs created before search_text was added.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ocr_index)").fetchall()}
        if "search_text" not in columns:
            conn.execute("ALTER TABLE ocr_index ADD COLUMN search_text TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ocr_folder ON ocr_index(folder_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ocr_filename ON ocr_index(file_name)")
        conn.commit()
    finally:
        conn.close()


def list_images(folder: str) -> list[str]:
    """List supported image files in selected folder (recursive)."""
    output = []
    try:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(IMAGE_EXTENSIONS):
                    output.append(os.path.join(root, name))
    except Exception:
        return []
    return sorted(output)


def normalize_for_search(text: str) -> str:
    """
    Normalize OCR and query text so product-code style searches are resilient to
    spaces, dashes, and OCR punctuation noise.
    """
    return re.sub(r"[^A-Z0-9]+", "", text.upper())


def build_search_text(file_name: str, ocr_text: str) -> str:
    base = normalize_for_search(file_name)
    ocr = normalize_for_search(ocr_text)
    return " ".join(part for part in (base, ocr) if part)


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """
    Improve OCR recall on labels/codes by normalizing contrast and resolution.
    """
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    w, h = gray.size
    if max(w, h) < 1400:
        gray = gray.resize((max(1, w * 2), max(1, h * 2)), Image.Resampling.LANCZOS)
    return gray


def resolve_max_ocr_workers() -> int:
    """
    Use OCR_WORKERS env var when present, otherwise a safe CPU-based default.
    """
    raw = os.getenv("OCR_WORKERS", "").strip()
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return min(value, 32)
        except ValueError:
            pass
    return DEFAULT_MAX_OCR_WORKERS


def extract_text_from_image(path: str) -> tuple[str, str | None]:
    """
    OCR helper that can run in worker threads.
    """
    try:
        with Image.open(path) as img:
            raw_text = pytesseract.image_to_string(img, config="--oem 3 --psm 6")
            processed_img = preprocess_for_ocr(img)
            processed_text = pytesseract.image_to_string(processed_img, config="--oem 3 --psm 6")
            text = processed_text if len(processed_text.strip()) >= len(raw_text.strip()) else raw_text
            return text or "", None
    except Exception as ex:
        return "", str(ex)


class OCRApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Inventory OCR Search")
        self.root.geometry("1300x760")
        self.root.minsize(900, 560)

        self.selected_folder = ""
        self.indexing = False

        self.image_count_var = tk.StringVar(value="Images: 0")
        self.status_var = tk.StringVar(value="Select a folder to begin.")
        self.search_var = tk.StringVar()
        self.preview_info_var = tk.StringVar(value="Select a search result to preview.")
        self.current_selected_path = ""
        self.preview_photo = None
        self.preview_size = (520, 520)
        self.preview_resize_job = None
        self.progress_label_var = tk.StringVar(value="Progress: 0 / 0")
        self.progress_value_var = tk.DoubleVar(value=0.0)

        self.build_ui()
        init_db()

        # Configure pytesseract path.
        tesseract_path = resolve_tesseract_path()
        if not tesseract_path:
            messagebox.showerror(
                "Tesseract Not Found",
                "Could not locate tesseract.exe.\n\n"
                "Expected bundled path:\n"
                f"{os.path.join(app_base_dir(), 'tesseract', 'tesseract.exe')}\n\n"
                "Device path from script.py:\n"
                f"{DEVICE_TESSERACT_PATH}",
            )
            self.select_btn.configure(state="disabled")
            return

        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        self.status_var.set(f"Tesseract ready: {tesseract_path}")

    def build_ui(self) -> None:
        """Construct all Tkinter widgets required by the app."""
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief="sunken", anchor="w", padx=8)
        status_bar.pack(fill="x", side="bottom")

        top_frame = tk.Frame(self.root, padx=10, pady=10)
        top_frame.pack(fill="x")

        self.select_btn = tk.Button(top_frame, text="Select Folder", command=self.on_select_folder)
        self.select_btn.pack(side="left")

        tk.Label(top_frame, textvariable=self.image_count_var, padx=12).pack(side="left")

        search_frame = tk.Frame(self.root, padx=10, pady=5)
        search_frame.pack(fill="x")

        tk.Label(search_frame, text="Search Product Code:").pack(side="left")
        search_entry = tk.Entry(search_frame, textvariable=self.search_var, width=50)
        search_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.search_var.trace_add("write", self.on_search_changed)

        progress_frame = tk.Frame(self.root, padx=10, pady=0)
        progress_frame.pack(fill="x", pady=(0, 5))

        tk.Label(progress_frame, textvariable=self.progress_label_var, anchor="w").pack(fill="x")
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            orient="horizontal",
            mode="determinate",
            variable=self.progress_value_var,
            maximum=100,
        )
        self.progress_bar.pack(fill="x", pady=(2, 0))

        content_frame = tk.Frame(self.root, padx=10, pady=10)
        content_frame.pack(fill="both", expand=True)

        left_frame = tk.Frame(content_frame)
        left_frame.pack(side="left", fill="both", expand=True)

        tk.Label(left_frame, text="Matching Images:", anchor="w").pack(fill="x")

        list_container = tk.Frame(left_frame)
        list_container.pack(fill="both", expand=True)

        self.listbox = tk.Listbox(list_container)
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_result_selected)

        scrollbar = tk.Scrollbar(list_container, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=scrollbar.set)

        right_frame = tk.Frame(content_frame, padx=12)
        right_frame.pack(side="right", fill="both", expand=True)

        tk.Label(right_frame, text="Image Preview", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        preview_frame = tk.Frame(right_frame)
        preview_frame.pack(fill="both", expand=True, pady=(6, 10))

        self.preview_canvas = tk.Canvas(
            preview_frame,
            relief="solid",
            bd=1,
            bg="#f4f4f4",
        )
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.bind("<Configure>", self.on_preview_canvas_resized)

        controls_frame = tk.Frame(right_frame)
        controls_frame.pack(fill="x", side="bottom")
        self.preview_info_label = tk.Label(
            controls_frame,
            textvariable=self.preview_info_var,
            justify="left",
            wraplength=self.preview_size[0],
            anchor="w",
        )
        self.preview_info_label.pack(fill="x", pady=(0, 10))

        self.copy_path_btn = tk.Button(
            controls_frame,
            text="Copy Full Path",
            command=self.copy_full_path,
            state="disabled",
        )
        self.copy_path_btn.pack(fill="x", pady=(0, 6))

        self.copy_name_btn = tk.Button(
            controls_frame,
            text="Copy File Name",
            command=self.copy_file_name,
            state="disabled",
        )
        self.copy_name_btn.pack(fill="x")

    def on_select_folder(self) -> None:
        """Ask user for folder and start OCR indexing thread."""
        folder = filedialog.askdirectory(title="Select Folder Containing Inventory Images")
        if not folder:
            return

        self.selected_folder = os.path.abspath(folder)
        images = list_images(self.selected_folder)

        self.image_count_var.set(f"Images: {len(images)}")
        self.listbox.delete(0, tk.END)
        self.status_var.set("Indexing images. Please wait...")
        self._set_progress(0, len(images))

        if self.indexing:
            messagebox.showinfo("Busy", "Indexing is already running.")
            return

        self.indexing = True
        self.select_btn.configure(state="disabled")

        worker = threading.Thread(target=self.index_images_worker, args=(self.selected_folder, images), daemon=True)
        worker.start()

    def index_images_worker(self, folder: str, image_paths: list[str]) -> None:
        """
        OCR all images and upsert into SQLite.
        Repeated runs skip files that have same size + modified time.
        """
        conn = sqlite3.connect(db_path())
        processed = 0
        skipped = 0
        failed = 0

        try:
            total = len(image_paths)
            existing_rows = conn.execute(
                """
                SELECT file_path, file_mtime, file_size, search_text, ocr_text
                FROM ocr_index
                WHERE folder_path = ?
                """,
                (folder,),
            ).fetchall()
            existing_map = {row[0]: row[1:] for row in existing_rows}

            to_process = []
            backfill_count = 0

            for idx, path in enumerate(image_paths, start=1):
                file_name = os.path.basename(path)
                try:
                    st = os.stat(path)
                    file_mtime = st.st_mtime
                    file_size = st.st_size
                    existing = existing_map.get(path)
                    if existing and existing[0] == file_mtime and existing[1] == file_size:
                        if not (existing[2] or "").strip():
                            conn.execute(
                                "UPDATE ocr_index SET search_text = ? WHERE file_path = ?",
                                (build_search_text(file_name, existing[3] or ""), path),
                            )
                            backfill_count += 1
                        skipped += 1
                        self._set_progress(skipped, total)
                        continue
                    to_process.append((path, file_name, file_mtime, file_size))
                except Exception:
                    failed += 1
                    self._set_progress(skipped + failed + len(to_process), total)

            if backfill_count:
                conn.commit()

            workers = resolve_max_ocr_workers()
            self._set_status(
                f"Indexing {len(to_process)} changed image(s) with {workers} worker(s). "
                f"Skipped unchanged: {skipped}"
            )

            if to_process:
                done = 0
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(extract_text_from_image, path): (path, file_name, file_mtime, file_size)
                        for (path, file_name, file_mtime, file_size) in to_process
                    }

                    for future in as_completed(futures):
                        path, file_name, file_mtime, file_size = futures[future]
                        text = ""
                        err_msg = None
                        try:
                            text, err_msg = future.result()
                        except Exception as ex:
                            err_msg = str(ex)

                        if err_msg:
                            failed += 1

                        search_text = build_search_text(file_name, text or "")
                        conn.execute(
                            """
                            INSERT INTO ocr_index (
                                file_path, folder_path, file_name, file_mtime, file_size, ocr_text, search_text, ocr_error, indexed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(file_path) DO UPDATE SET
                                folder_path = excluded.folder_path,
                                file_name   = excluded.file_name,
                                file_mtime  = excluded.file_mtime,
                                file_size   = excluded.file_size,
                                ocr_text    = excluded.ocr_text,
                                search_text = excluded.search_text,
                                ocr_error   = excluded.ocr_error,
                                indexed_at  = excluded.indexed_at
                            """,
                            (
                                path,
                                folder,
                                file_name,
                                file_mtime,
                                file_size,
                                text or "",
                                search_text,
                                err_msg,
                                datetime.now().isoformat(timespec="seconds"),
                            ),
                        )
                        processed += 1
                        done += 1
                        if done % 25 == 0:
                            conn.commit()
                        self._set_status(
                            f"Indexed ({skipped + done}/{total}) - latest: {file_name} "
                            f"(failed: {failed})"
                        )
                        self._set_progress(skipped + done, total)

                conn.commit()

            self._set_status(f"Index complete. OCR: {processed}, skipped: {skipped}, failed: {failed}")
            self._set_progress(total, total)

        except Exception as ex:
            details = traceback.format_exc()
            self.root.after(0, lambda: messagebox.showerror("Indexing Error", f"{ex}\n\n{details}"))
        finally:
            conn.close()
            self.root.after(0, self._finish_indexing)

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _set_progress(self, current: int, total: int) -> None:
        def apply() -> None:
            if total <= 0:
                self.progress_value_var.set(0.0)
                self.progress_label_var.set("Progress: 0 / 0")
                return
            percent = (current / total) * 100
            self.progress_value_var.set(percent)
            self.progress_label_var.set(f"Progress: {current} / {total}")

        self.root.after(0, apply)

    def _finish_indexing(self) -> None:
        self.indexing = False
        self.select_btn.configure(state="normal")
        self.on_search_changed()

    def on_search_changed(self, *_args) -> None:
        """Filter indexed files for current folder using live text search."""
        self.listbox.delete(0, tk.END)
        self.clear_preview()

        if not self.selected_folder:
            return

        query = self.search_var.get().strip()

        conn = sqlite3.connect(db_path())
        try:
            if query:
                normalized_query = normalize_for_search(query)
                rows = conn.execute(
                    """
                    SELECT file_path
                    FROM ocr_index
                    WHERE folder_path = ?
                      AND (
                            ocr_text LIKE ?
                            OR file_name LIKE ?
                            OR (? <> '' AND search_text LIKE ?)
                          )
                    ORDER BY file_name
                    LIMIT 500
                    """,
                    (
                        self.selected_folder,
                        f"%{query}%",
                        f"%{query}%",
                        normalized_query,
                        f"%{normalized_query}%",
                    ),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT file_path
                    FROM ocr_index
                    WHERE folder_path = ?
                    ORDER BY file_name
                    LIMIT 500
                    """,
                    (self.selected_folder,),
                ).fetchall()

            for (path,) in rows:
                self.listbox.insert(tk.END, path)

            if rows:
                self.listbox.selection_set(0)
                self.listbox.activate(0)
                self.on_result_selected()

            if query:
                self.status_var.set(f"Matches for '{query}': {len(rows)}")
            else:
                self.status_var.set(f"Indexed files shown: {len(rows)}")

        except Exception as ex:
            messagebox.showerror("Search Error", str(ex))
        finally:
            conn.close()

    def clear_preview(self) -> None:
        """Reset preview panel and copy buttons."""
        self.current_selected_path = ""
        self.preview_photo = None
        self.preview_canvas.delete("all")
        self.preview_info_var.set("Select a search result to preview.")
        self.copy_path_btn.configure(state="disabled")
        self.copy_name_btn.configure(state="disabled")

    def on_result_selected(self, _event=None) -> None:
        """Load large preview for selected path in the listbox."""
        selection = self.listbox.curselection()
        if not selection:
            self.clear_preview()
            return

        path = self.listbox.get(selection[0])
        if not path or not os.path.isfile(path):
            self.clear_preview()
            self.preview_info_var.set("File not found for selected result.")
            return

        try:
            self.current_selected_path = path
            self.preview_info_var.set(f"{os.path.basename(path)}\n{path}")
            self.copy_path_btn.configure(state="normal")
            self.copy_name_btn.configure(state="normal")
            self.render_preview(path)
        except Exception as ex:
            self.clear_preview()
            self.preview_info_var.set(f"Could not preview image: {ex}")

    def render_preview(self, path: str) -> None:
        canvas_w = max(self.preview_canvas.winfo_width(), 160)
        canvas_h = max(self.preview_canvas.winfo_height(), 160)
        target_size = (canvas_w - 10, canvas_h - 10)
        wrap_len = max(canvas_w, 220)

        with Image.open(path) as img:
            preview = ImageOps.contain(img.convert("RGB"), target_size, Image.Resampling.LANCZOS)

        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        x = canvas_w // 2
        y = canvas_h // 2
        self.preview_canvas.create_image(x, y, image=self.preview_photo, anchor="center")
        self.preview_info_var.set(f"{os.path.basename(path)}\n{path}")
        self.preview_info_label.configure(wraplength=wrap_len)

    def on_preview_canvas_resized(self, _event=None) -> None:
        if not self.current_selected_path:
            return
        if not os.path.isfile(self.current_selected_path):
            return
        if self.preview_resize_job:
            self.root.after_cancel(self.preview_resize_job)
        self.preview_resize_job = self.root.after(120, self._render_preview_after_resize)

    def _render_preview_after_resize(self) -> None:
        self.preview_resize_job = None
        if not self.current_selected_path or not os.path.isfile(self.current_selected_path):
            return
        try:
            self.render_preview(self.current_selected_path)
        except Exception:
            self.clear_preview()
            self.preview_info_var.set("Could not update preview after resize.")

    def copy_full_path(self) -> None:
        """Copy selected image full path to clipboard."""
        if not self.current_selected_path:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.current_selected_path)
        self.status_var.set("Copied full path to clipboard.")

    def copy_file_name(self) -> None:
        """Copy selected image filename to clipboard."""
        if not self.current_selected_path:
            return
        name = os.path.basename(self.current_selected_path)
        self.root.clipboard_clear()
        self.root.clipboard_append(name)
        self.status_var.set("Copied file name to clipboard.")


def main() -> None:
    root = tk.Tk()
    OCRApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
