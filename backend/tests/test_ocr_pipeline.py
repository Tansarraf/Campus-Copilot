"""OCR fallback: scanned PDFs, images, corruption, and text-first behaviour."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _write_text_pdf(path: str, lines: list[str]) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    y = 720
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.save()


def _write_image_pdf(path: str, page_images: list[str]) -> None:
    """Build a PDF whose pages are raster images (typically no useful text layer)."""
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    for img_path in page_images:
        c.drawImage(ImageReader(img_path), 0, 0, width=width, height=height)
        c.showPage()
    c.save()


def _render_notice_png(path: str, text: str, size=(640, 200)) -> None:
    img = Image.new("RGB", size, color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((24, 70), text, fill=(0, 0, 0))
    img.save(path)


class OcrPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_text_pdf_skips_ocr(self):
        from app.ingestion import loaders

        path = os.path.join(self.root, "text.pdf")
        _write_text_pdf(
            path,
            [
                "Fee Payment Circular Academic Year 2026-27",
                "Students must pay tuition fees by 15 November 2026.",
                "Late fee of INR 500 applies after the deadline.",
            ],
        )
        with mock.patch("app.ingestion.loaders.ocr_pdf_pages") as ocr_pdf:
            units, meta = loaders.load_document(path)
            ocr_pdf.assert_not_called()
        self.assertTrue(units)
        self.assertEqual(meta["extraction_method"], "pdf_text")
        self.assertTrue(any(u.get("page_number") == 1 for u in units))
        self.assertTrue(any("tuition" in u["text"].lower() for u in units))

    def test_scanned_pdf_uses_ocr_per_sparse_page(self):
        from app.ingestion import loaders

        img_path = os.path.join(self.root, "scan.png")
        _render_notice_png(img_path, "HOSTEL GATE CLOSES AT 10 PM")
        pdf_path = os.path.join(self.root, "scanned.pdf")
        _write_image_pdf(pdf_path, [img_path])

        fake_units = [
            {
                "text": "HOSTEL GATE CLOSES AT 10 PM",
                "page_number": 1,
                "section_label": None,
                "extraction_method": "ocr",
            }
        ]
        with mock.patch("app.ingestion.loaders.ocr_pdf_pages", return_value=fake_units) as ocr_pdf:
            units, meta = loaders.load_document(pdf_path)
            ocr_pdf.assert_called_once()
        self.assertEqual(units[0]["extraction_method"], "ocr")
        self.assertEqual(units[0]["page_number"], 1)
        self.assertIn("HOSTEL", units[0]["text"])
        self.assertEqual(meta["extraction_method"], "ocr")

    def test_multipage_scanned_pdf_preserves_page_numbers(self):
        from app.ingestion.ocr import ocr_pdf_pages

        p1 = os.path.join(self.root, "p1.png")
        p2 = os.path.join(self.root, "p2.png")
        _render_notice_png(p1, "PAGE ONE LIBRARY HOURS")
        _render_notice_png(p2, "PAGE TWO SCHOLARSHIP DEADLINE")
        pdf_path = os.path.join(self.root, "multi.pdf")
        _write_image_pdf(pdf_path, [p1, p2])

        with mock.patch("app.ingestion.ocr.configure_tesseract", return_value=True), mock.patch(
            "app.ingestion.ocr.ocr_pil_image",
            side_effect=["PAGE ONE LIBRARY HOURS " * 3, "PAGE TWO SCHOLARSHIP DEADLINE " * 3],
        ):
            units = ocr_pdf_pages(pdf_path, page_texts=["", ""])
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]["page_number"], 1)
        self.assertEqual(units[1]["page_number"], 2)
        self.assertIn("LIBRARY", units[0]["text"])
        self.assertIn("SCHOLARSHIP", units[1]["text"])

    def test_jpg_and_png_ocr_success(self):
        from app.ingestion import loaders

        ocr_text = "PLACEMENT DRIVE ON CAMPUS NEXT WEEK FOR FINAL YEAR"
        for name, fmt in (("notice.jpg", "JPEG"), ("notice.png", "PNG")):
            path = os.path.join(self.root, name)
            img = Image.new("RGB", (400, 120), color=(255, 255, 255))
            ImageDraw.Draw(img).text((10, 40), "PLACEMENT DRIVE ON CAMPUS", fill=(0, 0, 0))
            img.save(path, format=fmt)
            with mock.patch(
                "app.ingestion.loaders.ocr_image_path",
                return_value=(ocr_text, {"extraction_method": "ocr", "ocr_engine": "tesseract"}),
            ):
                units, meta = loaders.load_document(path)
            self.assertEqual(meta["extraction_method"], "ocr")
            self.assertIn("PLACEMENT", units[0]["text"])
            self.assertEqual(units[0]["page_number"], 1)

    def test_corrupted_image_graceful(self):
        from app.ingestion import loaders

        path = os.path.join(self.root, "broken.png")
        with open(path, "wb") as f:
            f.write(b"not-a-real-png-file")
        with mock.patch("app.ingestion.ocr.configure_tesseract", return_value=True):
            units, meta = loaders.load_document(path)
        self.assertEqual(meta["extraction_method"], "ocr_failed")
        self.assertEqual(units[0]["text"], "")
        self.assertTrue(units[0].get("ocr_error"))

    def test_poor_quality_image_empty_ocr(self):
        from app.ingestion import loaders

        path = os.path.join(self.root, "noisy.png")
        # Tiny noisy image unlikely to yield text even if OCR runs.
        img = Image.new("RGB", (40, 20), color=(180, 180, 180))
        img.save(path)
        with mock.patch("app.ingestion.ocr.configure_tesseract", return_value=True), mock.patch(
            "pytesseract.image_to_string",
            return_value="   ",
        ):
            units, meta = loaders.load_document(path)
        self.assertEqual(meta["extraction_method"], "ocr_empty")
        self.assertEqual(units[0]["text"], "")

    def test_sufficient_pdf_page_not_reocrd(self):
        from app.ingestion.ocr import ocr_pdf_pages

        path = os.path.join(self.root, "mixed.pdf")
        _write_text_pdf(path, ["Enough alphanumeric content here for page one sufficiency check."])
        with mock.patch("app.ingestion.ocr.configure_tesseract", return_value=True), mock.patch(
            "app.ingestion.ocr.ocr_pil_image"
        ) as ocr_page:
            # Provide sufficient text for page 1 so OCR must be skipped.
            units = ocr_pdf_pages(
                path,
                page_texts=["Enough alphanumeric content here for page one sufficiency check."],
            )
            ocr_page.assert_not_called()
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["extraction_method"], "pdf_text")


if __name__ == "__main__":
    unittest.main()
