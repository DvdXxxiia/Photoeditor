# Office Applications

A local web app with two separate tools:

- **Photo Editor** — upload a photo, identify objects, edit or delete them, and draw on top.
- **PDF Compare** — upload two PDF documents, get a summary of each, and see what differs.

## Run

```bash
python -m pip install -r requirements.txt
python app.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

- Home: `/`
- Photo Editor: `/photo`
- PDF Compare: `/pdf`

## Photo Editor

The first **Identify objects** run uses a vision-language model so names are semantic (`ornamental metal fence`, `window security grille`) instead of color fragments (`blue line`).

1. Detect regions in the image (Florence-2 dense captions when the model is available, otherwise connected drawings / units).
2. Crop each region and send it to **Florence-2** (`microsoft/Florence-2-base`) or **GPT-4o Vision** if `OPENAI_API_KEY` is set.
3. Store `{ label, confidence, bbox: [x, y, w, h] }`.

The first Florence-2 run downloads the model weights. Set `PHOTOEDITOR_DISABLE_VLM=1` to skip it. Optional: `PHOTOEDITOR_FLORENCE_MODEL`, `PHOTOEDITOR_OPENAI_MODEL`.

You can still add extra regions with the magic wand or box tool.

- **Upload** a JPG, PNG, or similar image (drag and drop works too).
- **Identify objects** to outline things the detector finds.
- **Select** an object, then change brightness, contrast, saturation, blur, grayscale, pixelate, invert, sharpen, or tint.
- **Copy / Paste** a selected object onto the photo (`Ctrl+C` / `Ctrl+V`). Paste offsets the duplicate; `Ctrl+click` the photo to place it.
- **Delete** a selected object; the hole is filled in with inpainting.
- **Draw** and **erase** on a separate layer. Download keeps the drawing. **Merge drawing** bakes it into the photo.
- **Undo / Redo** photo edits (not the live brush strokes).

Keyboard: `V` select, `W` wand, `M` box, `B` brush, `E` eraser, `Ctrl+C` copy, `Ctrl+V` paste, `Ctrl+Z` undo, `Delete` remove object.

## PDF Compare

Upload two PDFs on `/pdf`, then **Summarize & compare**.

- Each document gets an extractive summary (main sentences in document order).
- The comparison lists statements only in the first PDF, only in the second, and wording that changed.
- If `OPENAI_API_KEY` is set (and VLM is not disabled), GPT-4o writes the summaries and difference lists. Otherwise the built-in comparer is used.
- Text is read from the PDF. Scanned image-only PDFs are not supported yet.

## Tests

```bash
python -m pytest -q
```
