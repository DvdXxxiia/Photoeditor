# Office Applications

A local web app with two separate tools:

- **Photo Editor** — upload a photo, identify objects, edit or delete them, and draw on top.
- **Quote Intelligence** — upload two vendor quote PDFs and compare them by equipment meaning, not wording.

## Run

```bash
python -m pip install -r requirements.txt
python app.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

- Home: `/`
- Photo Editor: `/photo`
- Quote Intelligence: `/quotes` (also `/pdf`)

## Quote Intelligence

Upload `Quote_A.pdf` and `Quote_B.pdf`. The app:

1. Reads digital PDFs with **pdfplumber** and **PyMuPDF**, uses OCR when text is missing, and prefers **Azure Document Intelligence** when `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` and `AZURE_DOCUMENT_INTELLIGENCE_KEY` are set.
2. Returns structured quote JSON: `vendor`, `quote_number`, `date`, `items`.
3. Matches line items with embeddings + a plastics equipment catalog (`GMP180` Dryer = `Drying Unit GMP-180`).
4. Shows totals, missing/added scope, price deltas, drawing callouts, historical savings, and a procurement summary.
5. Lets you ask *Why is Quote B cheaper?*

Compare-by-function example: `PTUN2500 + GMP180` vs `PTUN2000 + GMP250` is treated as the same drying/storage system with different capacity, not as unrelated text.

Quotes are stored in **SQLite** by default (`quotes.db`). Set `DATABASE_URL` to a PostgreSQL URL in production.

Optional: `OPENAI_API_KEY` for GPT summaries/chat and `text-embedding-3-small`. Tests disable live model calls with `PHOTOEDITOR_DISABLE_VLM=1`.

## Photo Editor

The first **Identify objects** run uses a vision-language model so names are semantic (`ornamental metal fence`) instead of color fragments.

Set `PHOTOEDITOR_DISABLE_VLM=1` to skip Florence-2. Optional: `PHOTOEDITOR_FLORENCE_MODEL`, `PHOTOEDITOR_OPENAI_MODEL`.

- **Upload** a JPG or PNG (drag and drop works).
- **Identify objects**, then edit, copy/paste, or delete them.
- **Draw** on a separate layer. **Undo / Redo** photo edits.

Keyboard: `V` select, `W` wand, `M` box, `B` brush, `E` eraser, `Ctrl+C` copy, `Ctrl+V` paste, `Ctrl+Z` undo, `Delete` remove object.

## Tests

```bash
python -m pytest -q
```
