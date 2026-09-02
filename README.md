# Photo Editor

A local web app for uploading a photo, identifying objects in it, editing or deleting those objects, and drawing on top of the image.

## Run

```bash
python -m pip install -r requirements.txt
python app.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The first **Identify objects** run may download a small [YOLOv8](https://github.com/ultralytics/ultralytics) model (`yolov8n-seg.pt`) so named objects (people, cars, cups, and other COCO classes) can be detected. If that model is unavailable, the app falls back to color-region grouping. You can always select extra regions with the magic wand or box tool.

## What you can do

- **Upload** a JPG, PNG, or similar image (drag and drop works too).
- **Identify objects** to outline things the detector finds.
- **Select** an object, then change brightness, contrast, saturation, blur, grayscale, pixelate, invert, sharpen, or tint.
- **Delete** a selected object; the hole is filled in with inpainting.
- **Draw** and **erase** on a separate layer. Download keeps the drawing. **Merge drawing** bakes it into the photo.
- **Undo / Redo** photo edits (not the live brush strokes).

Keyboard: `V` select, `W` wand, `M` box, `B` brush, `E` eraser, `Ctrl+Z` undo, `Delete` remove object.

## Tests

```bash
python -m pytest -q
```
