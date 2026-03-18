#!/usr/bin/env python3
"""Convert photographed/screenshotted slides into a perspective-corrected PDF.

Double-click the .app bundle or run: python3 slide_to_pdf.py
"""
from __future__ import annotations

import json
import sys
import os
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff", ".tif"}
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
CORNER_LABELS = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]
POINT_RADIUS = 7
LINE_COLOR = "#FFFF00"
POINT_COLOR = "#FF0000"
FILL_COLOR = "#00FF00"
BATCH_SIZE = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_creation_date(filepath: str) -> datetime:
    """Return the best-guess creation date for an image file."""
    try:
        with Image.open(filepath) as img:
            exif = img._getexif()
            if exif and 36867 in exif:
                return datetime.strptime(exif[36867], "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(os.stat(filepath).st_birthtime)
    except AttributeError:
        pass
    return datetime.fromtimestamp(os.path.getmtime(filepath))


def load_image_pil(filepath: str) -> Image.Image | None:
    """Load an image as a PIL RGB Image."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".heic" and not HEIC_SUPPORTED:
        return None
    try:
        return Image.open(filepath).convert("RGB")
    except Exception:
        return None


def load_image_cv(filepath: str) -> np.ndarray | None:
    """Load an image as a BGR numpy array."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".heic":
        pil_img = load_image_pil(filepath)
        if pil_img is None:
            return None
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    img = cv2.imread(filepath, cv2.IMREAD_COLOR)
    return img


def correct_perspective(img: np.ndarray, corners: list) -> Image.Image:
    """Warp the quadrilateral into a 16:9 rectangle."""
    src = np.float32(corners)
    dst = np.float32([
        [0, 0],
        [OUTPUT_WIDTH - 1, 0],
        [OUTPUT_WIDTH - 1, OUTPUT_HEIGHT - 1],
        [0, OUTPUT_HEIGHT - 1],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
    return Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------

class SlideToPDFApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Slide Pictures to PDF")
        self.root.configure(bg="#2b2b2b")

        self.files: list[str] = []
        self.current_index = 0
        self.points: list[tuple[int, int]] = []  # points in original image coords
        self.selections: list[tuple[str, list, int]] = []  # (path, corners, rotation_deg)
        self.batch_preview_enabled = tk.BooleanVar(value=True)

        # Current image state
        self.pil_image: Image.Image | None = None
        self.pil_image_original: Image.Image | None = None
        self.rotation_deg = 0  # cumulative rotation applied to current image
        self.tk_image: ImageTk.PhotoImage | None = None
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0

        # Batch preview state
        self.batch_start = 0  # index in self.selections where current batch started
        self._preview_tk_images: list[ImageTk.PhotoImage] = []  # prevent GC

        # ML data collection
        self.ml_data: list[dict] = []

        self._build_start_screen()
        self.root.mainloop()

    # -- Start screen --

    def _build_start_screen(self):
        for w in self.root.winfo_children():
            w.destroy()

        self.root.geometry("500x300")
        self.root.resizable(False, False)

        frame = tk.Frame(self.root, bg="#2b2b2b")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(frame, text="Slide Pictures to PDF",
                 font=("Helvetica", 22, "bold"), fg="white", bg="#2b2b2b").pack(pady=(0, 10))
        tk.Label(frame, text="Select a folder with slide photos.\nThey will be sorted by date, perspective-corrected,\nand combined into a single PDF.",
                 font=("Helvetica", 13), fg="#cccccc", bg="#2b2b2b", justify="center").pack(pady=(0, 25))

        btn = tk.Button(frame, text="Choose Folder...", font=("Helvetica", 14),
                        command=self._on_choose_folder, padx=20, pady=8)
        btn.pack()

        tk.Checkbutton(frame, text="Show batch preview every 10 slides",
                       variable=self.batch_preview_enabled,
                       font=("Helvetica", 12), fg="#cccccc", bg="#2b2b2b",
                       selectcolor="#2b2b2b", activebackground="#2b2b2b",
                       activeforeground="white").pack(pady=(12, 0))

    def _on_choose_folder(self):
        folder = filedialog.askdirectory(title="Select folder with slide pictures")
        if not folder:
            return

        files = []
        for fname in os.listdir(folder):
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                files.append(os.path.join(folder, fname))

        if not files:
            messagebox.showwarning("No Images", f"No supported images found in:\n{folder}")
            return

        files.sort(key=get_creation_date)
        self.files = files
        self.folder = folder
        self.current_index = 0
        self.selections = []
        self.batch_start = 0
        self.ml_data = []
        self._build_editor()

    # -- Editor screen --

    def _build_editor(self):
        for w in self.root.winfo_children():
            w.destroy()

        # Go (nearly) fullscreen
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")
        self.root.resizable(True, True)

        # Top bar
        top = tk.Frame(self.root, bg="#333333", height=50)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)

        self.lbl_status = tk.Label(top, text="", font=("Helvetica", 14),
                                   fg="white", bg="#333333")
        self.lbl_status.pack(side="left", padx=15)

        self.lbl_hint = tk.Label(top, text="", font=("Helvetica", 13),
                                 fg="#aaaaaa", bg="#333333")
        self.lbl_hint.pack(side="right", padx=15)

        # Canvas for image
        self.canvas = tk.Canvas(self.root, bg="#1a1a1a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Bottom bar
        bottom = tk.Frame(self.root, bg="#333333", height=45)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)

        self.btn_reset = tk.Button(bottom, text="Reset (R)", font=("Helvetica", 12),
                                   command=self._reset_points)
        self.btn_reset.pack(side="left", padx=10, pady=7)

        self.btn_undo = tk.Button(bottom, text="Undo (Z)", font=("Helvetica", 12),
                                  command=self._undo_point)
        self.btn_undo.pack(side="left", padx=5, pady=7)

        self.lbl_rotate = tk.Label(bottom, text="Rotate: \u2190 \u2192 \u2193",
                                   font=("Helvetica", 11), fg="#aaaaaa", bg="#333333")
        self.lbl_rotate.pack(side="left", padx=15, pady=7)

        self.btn_skip = tk.Button(bottom, text="Skip (S)", font=("Helvetica", 12),
                                   command=self._skip_image, fg="#cc6600")
        self.btn_skip.pack(side="right", padx=5, pady=7)

        self.btn_confirm = tk.Button(bottom, text="Confirm (Enter)", font=("Helvetica", 12, "bold"),
                                     command=self._confirm, state="disabled")
        self.btn_confirm.pack(side="right", padx=10, pady=7)

        # Bindings
        self.canvas.bind("<Button-1>", self._on_click)
        self.root.bind("<Return>", lambda e: self._confirm())
        self.root.bind("<r>", lambda e: self._reset_points())
        self.root.bind("<z>", lambda e: self._undo_point())
        self.root.bind("<s>", lambda e: self._skip_image())
        self.root.bind("<Escape>", lambda e: self._abort())
        self.root.bind("<Left>", lambda e: self._rotate_image(-90))
        self.root.bind("<Right>", lambda e: self._rotate_image(90))
        self.root.bind("<Down>", lambda e: self._rotate_image(180))
        self.canvas.bind("<Configure>", lambda e: self._show_image())

        self._load_current_image()

    # -- Image rotation --

    def _rotate_image(self, degrees: int):
        if self.pil_image_original is None:
            return
        self.rotation_deg = (self.rotation_deg + degrees) % 360
        if self.rotation_deg == 0:
            self.pil_image = self.pil_image_original.copy()
        else:
            rot_map = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
            self.pil_image = self.pil_image_original.transpose(rot_map[self.rotation_deg])
        self.points = []
        self._show_image()
        self._update_status()

    # -- Image loading & display --

    def _load_current_image(self):
        self.points = []
        self.rotation_deg = 0
        fpath = self.files[self.current_index]
        self.pil_image_original = load_image_pil(fpath)
        self.pil_image = self.pil_image_original

        if self.pil_image is None:
            # Skip unreadable images
            self.current_index += 1
            if self.current_index < len(self.files):
                self._load_current_image()
            else:
                self._end_of_batch_or_finish()
            return

        self._update_status()
        self._show_image()

    def _update_status(self):
        fname = os.path.basename(self.files[self.current_index])
        rot_text = f"  (rotated {self.rotation_deg}\u00b0)" if self.rotation_deg else ""
        self.lbl_status.config(
            text=f"[{self.current_index + 1}/{len(self.files)}]  {fname}{rot_text}")

        if len(self.points) < 4:
            label = CORNER_LABELS[len(self.points)]
            self.lbl_hint.config(text=f"Click: {label}  ({len(self.points) + 1}/4)")
            self.btn_confirm.config(state="disabled")
        else:
            self.lbl_hint.config(text="Press Enter to confirm")
            self.btn_confirm.config(state="normal")

    def _show_image(self):
        if self.pil_image is None:
            return

        self.canvas.delete("all")

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return

        iw, ih = self.pil_image.size
        self.scale = min(cw / iw, ch / ih)
        disp_w = int(iw * self.scale)
        disp_h = int(ih * self.scale)
        self.offset_x = (cw - disp_w) // 2
        self.offset_y = (ch - disp_h) // 2

        resized = self.pil_image.resize((disp_w, disp_h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized)
        self.canvas.create_image(self.offset_x, self.offset_y,
                                 anchor="nw", image=self.tk_image)

        self._draw_overlay()

    def _draw_overlay(self):
        """Draw points, lines, and polygon fill on the canvas."""
        self.canvas.delete("overlay")

        canvas_pts = []
        for (ox, oy) in self.points:
            cx = int(ox * self.scale) + self.offset_x
            cy = int(oy * self.scale) + self.offset_y
            canvas_pts.append((cx, cy))

        # Lines
        for i in range(1, len(canvas_pts)):
            self.canvas.create_line(canvas_pts[i - 1][0], canvas_pts[i - 1][1],
                                    canvas_pts[i][0], canvas_pts[i][1],
                                    fill=LINE_COLOR, width=2, tags="overlay")

        # Close polygon
        if len(canvas_pts) == 4:
            self.canvas.create_line(canvas_pts[3][0], canvas_pts[3][1],
                                    canvas_pts[0][0], canvas_pts[0][1],
                                    fill=LINE_COLOR, width=2, tags="overlay")
            # Semi-transparent fill via stipple
            coords = []
            for cx, cy in canvas_pts:
                coords.extend([cx, cy])
            self.canvas.create_polygon(*coords, fill=FILL_COLOR,
                                       stipple="gray25", outline="", tags="overlay")

        # Points with labels
        for i, (cx, cy) in enumerate(canvas_pts):
            r = POINT_RADIUS
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    fill=POINT_COLOR, outline="white", width=1, tags="overlay")
            self.canvas.create_text(cx + 12, cy - 12, text=CORNER_LABELS[i],
                                    fill="white", font=("Helvetica", 11, "bold"),
                                    anchor="w", tags="overlay")

    def _on_click(self, event):
        if len(self.points) >= 4:
            return
        # Convert canvas coords to original image coords
        ox = (event.x - self.offset_x) / self.scale
        oy = (event.y - self.offset_y) / self.scale

        # Check bounds
        if self.pil_image is None:
            return
        iw, ih = self.pil_image.size
        if ox < 0 or oy < 0 or ox > iw or oy > ih:
            return

        self.points.append((ox, oy))
        self._draw_overlay()
        self._update_status()

    def _reset_points(self):
        self.points = []
        self._draw_overlay()
        self._update_status()

    def _undo_point(self):
        if self.points:
            self.points.pop()
            self._draw_overlay()
            self._update_status()

    def _confirm(self):
        if len(self.points) != 4:
            return
        fpath = self.files[self.current_index]
        self.selections.append((fpath, list(self.points), self.rotation_deg))

        # Collect ML training data
        iw, ih = self.pil_image.size
        self.ml_data.append({
            "filename": os.path.basename(fpath),
            "image_width": iw,
            "image_height": ih,
            "rotation_deg": self.rotation_deg,
            "corners": [{"x": p[0], "y": p[1]} for p in self.points],
        })

        self.current_index += 1
        batch_count = len(self.selections) - self.batch_start

        if self.current_index >= len(self.files):
            # Last image - show final batch preview then generate PDF
            if self.batch_preview_enabled.get():
                self._show_batch_preview(is_final=True)
            else:
                self._generate_pdf()
        elif batch_count >= BATCH_SIZE and self.batch_preview_enabled.get():
            # Batch complete - show preview
            self._show_batch_preview(is_final=False)
        else:
            self._load_current_image()

    def _skip_image(self):
        self.current_index += 1
        if self.current_index < len(self.files):
            self._load_current_image()
        else:
            self._end_of_batch_or_finish()

    def _abort(self):
        if messagebox.askyesno("Abort", "Quit without generating PDF?"):
            self.root.destroy()

    # -- Batch preview --

    def _end_of_batch_or_finish(self):
        """Called when we run out of images (e.g. all skipped)."""
        if self.selections and self.batch_preview_enabled.get():
            self._show_batch_preview(is_final=True)
        else:
            self._generate_pdf()

    def _show_batch_preview(self, is_final: bool):
        for w in self.root.winfo_children():
            w.destroy()

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")
        self.root.resizable(True, True)

        # Top bar
        top = tk.Frame(self.root, bg="#333333", height=50)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)

        batch_items = self.selections[self.batch_start:]
        batch_num = (self.batch_start // BATCH_SIZE) + 1
        tk.Label(top, text=f"Batch {batch_num} Preview  -  {len(batch_items)} slides",
                 font=("Helvetica", 14, "bold"), fg="white", bg="#333333").pack(side="left", padx=15)

        # Bottom bar with continue/finish button
        bottom = tk.Frame(self.root, bg="#333333", height=50)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)

        if is_final:
            btn_text = "Generate PDF"
            btn_cmd = self._generate_pdf
        else:
            btn_text = "Continue to Next Batch"
            btn_cmd = self._continue_after_preview

        tk.Button(bottom, text=btn_text, font=("Helvetica", 13, "bold"),
                  command=btn_cmd, padx=20, pady=5).pack(side="right", padx=15, pady=7)

        tk.Label(bottom, text="Check that all slides look correct",
                 font=("Helvetica", 12), fg="#aaaaaa", bg="#333333").pack(side="left", padx=15)

        # Scrollable canvas for the grid
        container = tk.Frame(self.root, bg="#1a1a1a")
        container.pack(fill="both", expand=True)

        preview_canvas = tk.Canvas(container, bg="#1a1a1a", highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=preview_canvas.yview)
        preview_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        preview_canvas.pack(side="left", fill="both", expand=True)

        grid_frame = tk.Frame(preview_canvas, bg="#1a1a1a")
        preview_canvas.create_window((0, 0), window=grid_frame, anchor="nw")

        # Render corrected thumbnails in a grid (2 columns)
        self._preview_tk_images = []
        cols = 2
        thumb_w = (screen_w // cols) - 40

        for idx, (fpath, corners, rot_deg) in enumerate(batch_items):
            row = idx // cols
            col = idx % cols

            cell = tk.Frame(grid_frame, bg="#1a1a1a", padx=5, pady=5)
            cell.grid(row=row, column=col, padx=10, pady=10)

            # Generate corrected preview
            pil_img = load_image_pil(fpath)
            if pil_img is not None and rot_deg:
                rot_map = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
                pil_img = pil_img.transpose(rot_map[rot_deg])
            if pil_img is not None:
                cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                corrected = correct_perspective(cv_img, corners)
            else:
                corrected = Image.new("RGB", (OUTPUT_WIDTH, OUTPUT_HEIGHT), (80, 80, 80))

            # Resize to thumbnail
            thumb_h = int(thumb_w * OUTPUT_HEIGHT / OUTPUT_WIDTH)
            thumb = corrected.resize((thumb_w, thumb_h), Image.LANCZOS)
            tk_thumb = ImageTk.PhotoImage(thumb)
            self._preview_tk_images.append(tk_thumb)

            tk.Label(cell, image=tk_thumb, bg="#1a1a1a").pack()
            tk.Label(cell, text=f"{self.batch_start + idx + 1}. {os.path.basename(fpath)}",
                     font=("Helvetica", 11), fg="#cccccc", bg="#1a1a1a").pack(pady=(3, 0))

        grid_frame.update_idletasks()
        preview_canvas.config(scrollregion=preview_canvas.bbox("all"))

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            preview_canvas.yview_scroll(-1 * (event.delta // 120 or (-1 if event.num == 5 else 1)), "units")

        preview_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        preview_canvas.bind_all("<Button-4>", _on_mousewheel)
        preview_canvas.bind_all("<Button-5>", _on_mousewheel)

        # Enter to continue/finish
        self.root.bind("<Return>", lambda e: btn_cmd())

    def _continue_after_preview(self):
        self.batch_start = len(self.selections)
        self._build_editor()

    # -- PDF generation --

    def _generate_pdf(self):
        if not self.selections:
            messagebox.showinfo("Nothing to do", "No images were processed.")
            self.root.destroy()
            return

        # Show progress screen
        for w in self.root.winfo_children():
            w.destroy()

        self.root.geometry("500x200")
        self.root.resizable(False, False)

        frame = tk.Frame(self.root, bg="#2b2b2b")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        lbl = tk.Label(frame, text="Generating PDF...",
                       font=("Helvetica", 18), fg="white", bg="#2b2b2b")
        lbl.pack(pady=(0, 15))

        progress_lbl = tk.Label(frame, text="", font=("Helvetica", 13),
                                fg="#aaaaaa", bg="#2b2b2b")
        progress_lbl.pack()

        self.root.update()

        corrected: list[Image.Image] = []
        for i, (fpath, corners, rot_deg) in enumerate(self.selections):
            progress_lbl.config(text=f"Processing {i + 1}/{len(self.selections)}...")
            self.root.update()
            pil_img = load_image_pil(fpath)
            if pil_img is not None and rot_deg:
                rot_map = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
                pil_img = pil_img.transpose(rot_map[rot_deg])
            if pil_img is not None:
                cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                corrected.append(correct_perspective(cv_img, corners))

        if not corrected:
            messagebox.showerror("Error", "Failed to process any images.")
            self.root.destroy()
            return

        folder_name = os.path.basename(self.folder.rstrip("/"))
        output_path = os.path.join(self.folder, f"{folder_name}_slides.pdf")

        corrected[0].save(
            output_path,
            "PDF",
            save_all=True,
            append_images=corrected[1:],
            resolution=150.0,
        )

        # Save ML training data
        self._save_ml_data()

        # Done screen
        lbl.config(text="Done!")
        progress_lbl.config(text=f"Saved to:\n{output_path}")

        btn_frame = tk.Frame(frame, bg="#2b2b2b")
        btn_frame.pack(pady=15)

        tk.Button(btn_frame, text="Open PDF", font=("Helvetica", 13),
                  command=lambda: os.system(f'open "{output_path}"')).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Quit", font=("Helvetica", 13),
                  command=self.root.destroy).pack(side="left", padx=5)

    # -- ML data collection --

    def _save_ml_data(self):
        """Save corner selection data as JSON for future ML training."""
        if not self.ml_data:
            return
        folder_name = os.path.basename(self.folder.rstrip("/"))
        data_path = os.path.join(self.folder, f"{folder_name}_training_data.json")
        payload = {
            "version": 1,
            "output_width": OUTPUT_WIDTH,
            "output_height": OUTPUT_HEIGHT,
            "timestamp": datetime.now().isoformat(),
            "samples": self.ml_data,
        }
        with open(data_path, "w") as f:
            json.dump(payload, f, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    SlideToPDFApp()
