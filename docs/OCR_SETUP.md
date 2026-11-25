# OCR setup (Document Intelligence)

Campus Copilot uses **Tesseract OCR** only when ordinary text extraction is insufficient (scanned PDFs, sparse PDF pages, JPG/PNG notices).

## Docker (recommended)

The backend image installs `tesseract-ocr` and `tesseract-ocr-eng`. After `docker compose up --build`, OCR works inside `campus_copilot_backend` with no host install.

```powershell
docker exec campus_copilot_backend tesseract --version
```

## Python packages

Already listed in `backend/requirements.txt`:

- `pytesseract`
- `Pillow`
- `pypdfium2` (PDF page rendering for page-level OCR)

```powershell
cd backend
.\.venv\Scripts\pip install -r requirements.txt
```

## Host / local (non-Docker) dependency

Installing the Python packages does **not** install the OCR engine on Windows.

1. Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) for Windows.
2. Ensure `tesseract.exe` is on your `PATH`, **or** set:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

3. Verify:

```powershell
tesseract --version
```

## Behaviour when Tesseract is missing

- Text/DOCX/Markdown/text-based PDFs continue to work.
- Image uploads and scanned PDFs record `extraction_method` such as `ocr_unavailable` and `processing_status=extraction_failed` when no text can be extracted.
- The API does not crash; OCR is skipped gracefully.

## Detection and pipeline

1. PDF pages are extracted with PyPDF first.
2. A page is treated as insufficient when it has fewer than 40 alphanumeric characters.
3. Only insufficient pages are rendered with `pypdfium2` and OCR'd (pages with enough text are not re-processed).
4. JPG/JPEG/PNG always go through OCR.
5. Extracted units enter the same chunk → embed → SQLite → retrieval path as normal uploads.
