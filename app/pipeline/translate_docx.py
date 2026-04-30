from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from app.pipeline.translate_text_segments import SegmentTranslationStats, translate_segments


WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TRANSLATABLE_DOCX_PARTS = {
    "word/document.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
    "word/comments.xml",
}


def _iter_docx_text_parts(xml_root: ET.Element) -> list[list[ET.Element]]:
    paragraphs: list[list[ET.Element]] = []
    for paragraph in xml_root.findall(".//w:p", WORD_NAMESPACE):
        text_nodes = [node for node in paragraph.findall(".//w:t", WORD_NAMESPACE) if (node.text or "").strip()]
        if text_nodes:
            paragraphs.append(text_nodes)
    return paragraphs


def translate_docx(
    docx_in: Path,
    docx_out: Path,
    *,
    target_lang: str,
    source_lang: str | None = None,
) -> SegmentTranslationStats:
    paragraph_entries: list[tuple[str, list[ET.Element]]] = []
    part_roots: dict[str, ET.Element] = {}

    with ZipFile(docx_in, "r") as archive:
        for name in archive.namelist():
            if not (
                name in TRANSLATABLE_DOCX_PARTS
                or (name.startswith("word/header") and name.endswith(".xml"))
                or (name.startswith("word/footer") and name.endswith(".xml"))
            ):
                continue
            xml_root = ET.fromstring(archive.read(name))
            part_roots[name] = xml_root
            for text_nodes in _iter_docx_text_parts(xml_root):
                paragraph_entries.append((name, text_nodes))

        texts = ["".join(node.text or "" for node in nodes).strip() for _, nodes in paragraph_entries]
        translated_texts, stats = translate_segments(
            texts,
            target_lang=target_lang,
            source_lang=source_lang,
        )

        for translated, (_, nodes) in zip(translated_texts, paragraph_entries):
            first = nodes[0]
            first.text = translated
            for node in nodes[1:]:
                node.text = ""

        docx_out.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(docx_in, "r") as source_archive, ZipFile(docx_out, "w", compression=ZIP_DEFLATED) as target_archive:
            for item in source_archive.infolist():
                if item.filename in part_roots:
                    xml_bytes = ET.tostring(part_roots[item.filename], encoding="utf-8", xml_declaration=True)
                    target_archive.writestr(item, xml_bytes)
                else:
                    target_archive.writestr(item, source_archive.read(item.filename))

    return stats
