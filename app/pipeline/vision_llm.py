from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from app.core.model_config import reasoning_kwargs
from openai import APIConnectionError, APIError, OpenAI

from app.core.model_config import get_vision_model_config


load_dotenv()


@dataclass(frozen=True)
class VisionTextBlock:
    text: str
    bbox_norm: tuple[int, int, int, int]


def _file_to_data_url(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if not mime_type:
        mime_type = "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


class VisionLLMClient:
    """OpenAI-compatible vision client for OCR-like extraction from page images or crops."""

    def __init__(self) -> None:
        config = get_vision_model_config()
        self.api_url = config.api_url
        self.api_key = config.api_key
        self.model = config.model
        self.client = OpenAI(
            base_url=self.api_url,
            api_key=self.api_key,
        )

    def extract_visible_text(
        self,
        image_path: Path,
        *,
        prompt: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        user_prompt = prompt or (
            "Read all visible text in this image. Preserve reading order. "
            "Return only the extracted text, without commentary."
        )

        try:
            response = self.client.chat.completions.create(
                **reasoning_kwargs(),
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": _file_to_data_url(image_path)},
                            },
                        ],
                    }
                ],
                temperature=0.0,
                max_tokens=max_tokens,
            )
        except (APIConnectionError, APIError) as exc:
            raise RuntimeError(f"Vision model request failed: {exc}") from exc

        content = response.choices[0].message.content
        if isinstance(content, str):
            return content.strip()
        if not content:
            return ""

        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(text.strip())
        return "\n".join(part for part in parts if part).strip()

    def extract_figure_text_blocks(
        self,
        image_path: Path,
        *,
        max_tokens: int = 4096,
    ) -> list[VisionTextBlock]:
        prompt = (
            "Read only text that is embedded inside figures, diagrams, charts, photos, logos, screenshots, "
            "or other image-like regions on this document page. Exclude the main body paragraphs, headings, "
            "running headers, footers, page numbers, and normal document text. "
            'Return JSON only in the form {"blocks":[{"text":"...", "bbox":[x1,y1,x2,y2]}]}. '
            "Each bbox must use integer coordinates normalized from 0 to 1000 relative to the full image width and height. "
            'If there is no figure/image-embedded text to translate, return {"blocks":[]}.'
        )
        raw = self.extract_visible_text(image_path, prompt=prompt, max_tokens=max_tokens)
        if not raw:
            return []

        raw = raw.strip()
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []

        blocks_raw = payload.get("blocks")
        if not isinstance(blocks_raw, list):
            return []

        blocks: list[VisionTextBlock] = []
        for item in blocks_raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            bbox = item.get("bbox")
            if not text or not isinstance(bbox, list) or len(bbox) != 4:
                continue
            try:
                x1, y1, x2, y2 = (max(0, min(1000, int(round(float(v))))) for v in bbox)
            except (TypeError, ValueError):
                continue
            if x2 <= x1 or y2 <= y1:
                continue
            blocks.append(VisionTextBlock(text=text, bbox_norm=(x1, y1, x2, y2)))

        return blocks
