# SlideToPDF

A macOS desktop app that converts photographed/screenshotted presentation slides into a single perspective-corrected PDF.

## Architecture

Single-file Tkinter GUI (`slide_to_pdf.py`) with no external UI framework. The app flows through three screens: start (folder picker) → editor (corner marking canvas) → batch preview → PDF generation. All state lives in the `SlideToPDFApp` class.

Image processing uses OpenCV for perspective transforms and Pillow for image I/O and PDF export. HEIC support is optional via `pillow-heif`.

## Key constants

- Output resolution: 1920×1080 (16:9)
- Batch preview every 10 images
- Corner order: Top-Left → Top-Right → Bottom-Right → Bottom-Left

## Build & run

Requires macOS with Homebrew. Run `setup.sh` to install Python 3.13, dependencies, and build the `.app` bundle via PyInstaller. Or run directly: `python3 slide_to_pdf.py`.

Dependencies: `opencv-python`, `pillow`, `pillow-heif` (optional).

## Project structure

- `slide_to_pdf.py` — entire application
- `setup.sh` — one-step install + build script (targets `/opt/homebrew/bin/python3.13`)
- `SlideToPDF.spec` — PyInstaller spec (auto-generated, `--windowed --onedir`)
- `build/`, `dist/` — PyInstaller output (dist contains `SlideToPDF.app`)
- `requirements.txt` — pip dependencies

## Output files

The app writes to the same folder the user selects:
- `{folder_name}_slides.pdf` — the corrected slide deck
- `{folder_name}_training_data.json` — corner selection data for future ML training

## Style notes

- Dark UI theme (`#2b2b2b` background, white/gray text)
- Canvas-based image viewer with zoom-to-fit and coordinate mapping
- Keyboard-driven workflow: Enter (confirm), R (reset), Z (undo), S (skip), arrow keys (rotate), Esc (quit)

## When modifying

- All image coordinate math converts between canvas coords and original image coords via `self.scale` and `self.offset_x/y`. Rotation transforms must be applied before corner mapping.
- The `_rotate_image` method clears existing points when rotating since coordinates become invalid.
- PDF generation re-loads each image from disk (doesn't cache), so memory stays bounded for large batches.
- Training data JSON uses version field for forward compatibility.
