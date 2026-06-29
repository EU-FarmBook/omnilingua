from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from app.pipeline.translate_text_segments import SegmentTranslationStats, translate_segments


PPTX_NAMESPACE = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _iter_pptx_paragraph_nodes(xml_root: ET.Element) -> list[list[ET.Element]]:
    paragraphs: list[list[ET.Element]] = []
    for paragraph in xml_root.findall(".//a:p", PPTX_NAMESPACE):
        text_nodes = [node for node in paragraph.findall(".//a:t", PPTX_NAMESPACE) if (node.text or "").strip()]
        if text_nodes:
            paragraphs.append(text_nodes)
    return paragraphs


def translate_pptx(
    pptx_in: Path,
    pptx_out: Path,
    *,
    target_lang: str,
    source_lang: str | None = None,
    engine: str | None = None,
) -> SegmentTranslationStats:
    paragraph_entries: list[tuple[str, list[ET.Element]]] = []
    part_roots: dict[str, ET.Element] = {}

    with ZipFile(pptx_in, "r") as archive:
        for name in archive.namelist():
            if not (
                (name.startswith("ppt/slides/slide") and name.endswith(".xml"))
                or (name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml"))
            ):
                continue
            xml_root = ET.fromstring(archive.read(name))
            part_roots[name] = xml_root
            for text_nodes in _iter_pptx_paragraph_nodes(xml_root):
                paragraph_entries.append((name, text_nodes))

        texts = ["".join(node.text or "" for node in nodes).strip() for _, nodes in paragraph_entries]
        translated_texts, stats = translate_segments(
            texts,
            target_lang=target_lang,
            source_lang=source_lang,
            engine=engine,
        )

        for translated, (_, nodes) in zip(translated_texts, paragraph_entries):
            first = nodes[0]
            first.text = translated
            for node in nodes[1:]:
                node.text = ""

        pptx_out.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(pptx_in, "r") as source_archive, ZipFile(pptx_out, "w", compression=ZIP_DEFLATED) as target_archive:
            for item in source_archive.infolist():
                if item.filename in part_roots:
                    xml_bytes = ET.tostring(part_roots[item.filename], encoding="utf-8", xml_declaration=True)
                    target_archive.writestr(item, xml_bytes)
                else:
                    target_archive.writestr(item, source_archive.read(item.filename))

    return stats
