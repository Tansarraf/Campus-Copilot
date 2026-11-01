# OCR setup (Document Intelligence)

Campus Copilot uses **Tesseract OCR** only when ordinary text extraction is insufficient (scanned PDFs, sparse PDF pages, JPG/PNG notices).

## Python packages

Already listed in `backend/requirements.txt`:

- `pytesseract`
- `Pillow`
- `pypdfium2` (PDF page rendering for page-level OCR)

```powershell
cd backend
.\.venv\Scripts\pip install -r requirements.txt
```

## System dependency (required for OCR)

Installing the Python packages does **not** install the OCR engine.

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
