from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from app.pipeline.translate_docx import translate_docx
from app.pipeline.translate_pptx import translate_pptx
from app.pipeline.translate_text_segments import SegmentTranslationStats
from app.pipeline.translate_txt import translate_txt


class TranslateDocumentsTests(unittest.TestCase):
    def test_translate_txt_preserves_blank_lines_and_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_in = Path(tmpdir) / "input.txt"
            txt_out = Path(tmpdir) / "output.txt"
            txt_in.write_text("Hello world\n\nSecond paragraph\n", encoding="utf-8")

            with patch("app.pipeline.translate_txt.translate_segments") as mock_translate:
                mock_translate.return_value = (
                    ["γειά σου κόσμε\n", "\n", "δεύτερη παράγραφος\n"],
                    SegmentTranslationStats(3, 2, 0, 1, "en"),
                )
                stats = translate_txt(txt_in, txt_out, target_lang="el", source_lang="en")

            self.assertEqual(stats.source_lang, "en")
            self.assertEqual(txt_out.read_text(encoding="utf-8"), "γειά σου κόσμε\n\nδεύτερη παράγραφος\n")

    def test_translate_docx_rewrites_word_document_xml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_in = Path(tmpdir) / "sample.docx"
            docx_out = Path(tmpdir) / "sample_el.docx"
            self._write_docx_fixture(docx_in)

            with patch("app.pipeline.translate_docx.translate_segments") as mock_translate:
                mock_translate.return_value = (
                    ["Γεια σου κόσμε", "Δεύτερη παράγραφος"],
                    SegmentTranslationStats(2, 2, 0, 1, "en"),
                )
                translate_docx(docx_in, docx_out, target_lang="el", source_lang="en")

            with ZipFile(docx_out, "r") as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
                self.assertIn("Γεια σου κόσμε", xml)
                self.assertIn("Δεύτερη παράγραφος", xml)
                self.assertNotIn(">Hello<", xml)

    def test_translate_pptx_rewrites_slide_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pptx_in = Path(tmpdir) / "sample.pptx"
            pptx_out = Path(tmpdir) / "sample_el.pptx"
            self._write_pptx_fixture(pptx_in)

            with patch("app.pipeline.translate_pptx.translate_segments") as mock_translate:
                mock_translate.return_value = (
                    ["Τίτλος", "Σημείωση ομιλητή"],
                    SegmentTranslationStats(2, 2, 0, 1, "en"),
                )
                translate_pptx(pptx_in, pptx_out, target_lang="el", source_lang="en")

            with ZipFile(pptx_out, "r") as archive:
                slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
                notes_xml = archive.read("ppt/notesSlides/notesSlide1.xml").decode("utf-8")
                self.assertIn("Τίτλος", slide_xml)
                self.assertIn("Σημείωση ομιλητή", notes_xml)

    def _write_docx_fixture(self, path: Path) -> None:
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
        relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
        document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Hello</w:t></w:r></w:p>
    <w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>
  </w:body>
</w:document>"""
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", relationships)
            archive.writestr("word/document.xml", document_xml)

    def _write_pptx_fixture(self, path: Path) -> None:
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/notesSlides/notesSlide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>
</Types>"""
        slide_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody>
          <a:p><a:r><a:t>Title</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>"""
        notes_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody>
          <a:p><a:r><a:t>Speaker note</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:notes>"""
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("ppt/slides/slide1.xml", slide_xml)
            archive.writestr("ppt/notesSlides/notesSlide1.xml", notes_xml)


if __name__ == "__main__":
    unittest.main()
