# Photo Editor

A local web app for uploading a photo, identifying objects in it, editing or deleting those objects, and drawing on top of the image.

## Run

```bash
python -m pip install -r requirements.txt
python app.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The first **Identify objects** run uses a vision-language model so names are semantic (`ornamental metal fence`, `window security grille`) instead of color fragments (`blue line`).

1. Detect regions in the image (Florence-2 dense captions when the model is available, otherwise connected drawings / units).
2. Crop each region and send it to **Florence-2** (`microsoft/Florence-2-base`) or **GPT-4o Vision** if `OPENAI_API_KEY` is set.
3. Store `{ label, confidence, bbox: [x, y, w, h] }`.

The first Florence-2 run downloads the model weights. Set `PHOTOEDITOR_DISABLE_VLM=1` to skip it. Optional: `PHOTOEDITOR_FLORENCE_MODEL`, `PHOTOEDITOR_OPENAI_MODEL`.

You can still add extra regions with the magic wand or box tool.

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
