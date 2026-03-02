# translator_llm.py

from __future__ import annotations

import json
import os
import re
import sys
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError, APIError

# Load environment variables
load_dotenv()

EN_STOPWORDS = {
    "the", "and", "of", "to", "in", "for", "with", "on", "by", "as", "is", "are",
    "that", "this", "from", "or", "be", "an", "at", "it", "which", "can", "also",
    "not", "under", "within", "without", "was", "were", "has", "have", "had",
}


def _normalize_compare_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def should_retry_translation(
    source_text: str,
    translated_text: str,
    source_lang: str,
    target_lang: str,
) -> bool:
    """
    Heuristic guard against contaminated translations that keep too much source text.
    """
    if source_lang == target_lang:
        return False

    src = _normalize_compare_text(source_text)
    dst = _normalize_compare_text(translated_text)

    if not dst:
        return True
    if src == dst:
        return True

    # Large exact overlap usually means source text leaked into output.
    if len(src) >= 40:
        matcher = SequenceMatcher(None, src, dst)
        longest_common = matcher.find_longest_match(0, len(src), 0, len(dst)).size
        if longest_common >= max(28, int(len(src) * 0.45)):
            return True
        if matcher.ratio() > 0.82:
            return True

    # For non-English targets, too many English stopwords implies leakage.
    if source_lang == "en" and target_lang != "en":
        tokens = re.findall(r"[a-zA-Z']+", dst)
        if len(tokens) >= 10:
            hits = sum(1 for tok in tokens if tok in EN_STOPWORDS)
            if hits >= 6 and hits / max(1, len(tokens)) >= 0.22:
                return True

    return False


@dataclass(frozen=True)
class TranslationStats:
    nodes_translated: int
    nodes_skipped: int
    api_calls: int
    source_lang: str


@dataclass
class TextNode:
    node_id: int
    node: NavigableString
    parent: Tag
    original_text: str

    # derived fields to preserve layout spacing
    stripped_text: str
    prefix_ws: str
    suffix_ws: str

    translated_text: Optional[str] = None
    is_translatable: bool = True


class LLMTranslator:
    """OpenAI-compatible LLM translator for document translation."""
    
    def __init__(self):
        # Support both naming conventions for flexibility
        self.api_url = os.getenv("RUNPOD_VLLM_HOST") or os.getenv("LLM_API_URL", "http://localhost:8000/v1")
        self.api_key = os.getenv("VLLM_API_KEY") or os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("VLLM_MODEL") or os.getenv("LLM_MODEL", "qwen3-30b-a3b-awq")
        # Use larger max_tokens for translation
        combine_max = os.getenv("COMBINE_NUM_PREDICT")
        default_max = combine_max if combine_max else "8192"
        self.max_tokens = int(os.getenv("DEFAULT_NUM_PREDICT") or os.getenv("LLM_MAX_TOKENS", default_max))
        if self.max_tokens < 4096:
            self.max_tokens = 8192
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        self.batch_size = int(os.getenv("LLM_BATCH_SIZE", "50"))  # More nodes per batch
        self.timeout = int(os.getenv("PER_REQUEST_TIMEOUT", "600"))
        
        # Ensure API URL has /v1 suffix
        if self.api_url and not self.api_url.rstrip("/").endswith("/v1"):
            self.api_url = self.api_url.rstrip("/") + "/v1"
        
        print(f"Connecting to LLM API: {self.api_url}")
        print(f"Using model: {self.model}")
        
        self.client = OpenAI(
            base_url=self.api_url,
            api_key=self.api_key,
            timeout=self.timeout
        )
    
    def detect_language(self, text_samples: List[str]) -> str:
        """Detect the source language from text samples."""
        samples = text_samples[:10]
        combined = "\n".join(f"- {s[:200]}" for s in samples if s.strip())
        
        prompt = f"""Analyze these text samples and identify the language.

Text samples:
{combined}

Respond with ONLY the ISO 639-1 language code (e.g., "en", "es", "fr", "de")."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a language detection expert. Respond only with the ISO 639-1 code."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=10
            )
            
            lang_code = response.choices[0].message.content.strip().lower()
            lang_code = re.sub(r'[^a-z]', '', lang_code)[:2]
            return lang_code if lang_code else "en"
            
        except APIConnectionError as e:
            print(f"\n❌ ERROR: Cannot connect to LLM API at {self.api_url}")
            print(f"   Details: {e}")
            sys.exit(1)
        except APIError as e:
            print(f"\n❌ ERROR: LLM API returned an error: {e}")
            sys.exit(1)
    
    def translate_nodes(
        self, 
        nodes: List[TextNode], 
        source_lang: str, 
        target_lang: str
    ) -> Dict[int, str]:
        """Translate multiple nodes in batches."""
        translations = {}
        
        for i in range(0, len(nodes), self.batch_size):
            batch = nodes[i:i + self.batch_size]
            batch_translations = self._translate_batch(batch, source_lang, target_lang)
            translations.update(batch_translations)
        
        return translations
    
    def _translate_batch(
        self, 
        batch: List[TextNode], 
        source_lang: str, 
        target_lang: str
    ) -> Dict[int, str]:
        """Translate a single batch of nodes."""
        
        items = []
        for node in batch:
            safe_text = json.dumps(node.stripped_text, ensure_ascii=False)
            items.append(f'"{node.node_id}": {safe_text}')
        
        items_json = ",\n    ".join(items)
        
        system_prompt = f"""You are an expert document translator. Translate text accurately while preserving meaning and formatting.

CRITICAL RULES:
1. Translate ONLY the natural language content
2. PRESERVE exactly: numbers, dates, emails, URLs, codes, acronyms in ALL CAPS
3. Maintain the same length and structure where possible
4. Respond ONLY with valid JSON in the format: {{"id": "translation", ...}}"""

        user_prompt = f"""Translate from {source_lang} to {target_lang}.

Each item is a separate text snippet. Translate each independently:

{{
    {items_json}
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
        except (APIConnectionError, APIError) as e:
            print(f"\n⚠️  API Error: {e}")
            return {}
        
        content = response.choices[0].message.content.strip()
        
        # Extract JSON
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        
        try:
            result = json.loads(content)
            return {int(k): v for k, v in result.items()}
        except json.JSONDecodeError:
            # Try partial recovery
            pattern = r'"(\d+)"\s*:\s*"([^"]*(?:\\"[^"]*)*)"'
            matches = re.findall(pattern, content)
            if matches:
                return {int(k): v.replace('\\"', '"') for k, v in matches}
            return {}

    def translate_single_strict(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
    ) -> Optional[str]:
        """
        Retry path for suspicious translations: single snippet, strict output.
        """
        system_prompt = (
            "You are a translation engine. Translate fully and accurately. "
            "Output only the translated text. Do not include the source text."
        )
        user_prompt = (
            f"Translate from {source_lang} to {target_lang}. "
            f"Return only the translation:\n\n{source_text}"
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=min(self.max_tokens, 1024),
            )
        except (APIConnectionError, APIError):
            return None

        content = (response.choices[0].message.content or "").strip()
        if not content:
            return None
        # If model wraps in fences, unwrap.
        fence = re.search(r"```(?:text)?\s*(.*?)\s*```", content, re.DOTALL)
        if fence:
            content = fence.group(1).strip()
        return content or None


def is_translatable_text(text: str) -> bool:
    """Determine if text is worth translating."""
    if not text or not text.strip():
        return False
    
    stripped = text.strip()
    
    # Skip pure whitespace
    if not stripped:
        return False
    
    # Skip pure HTML entities (like &#160;)
    if re.match(r'^&\w+;$', stripped) or re.match(r'^&#\d+;$', stripped):
        return False
    
    # Skip pure numbers
    if stripped.replace('.', '').replace(',', '').replace('-', '').isdigit():
        return False
    
    # Skip very short strings
    if len(stripped) < 3:
        return False
    
    # Skip if mostly non-letters
    letters = sum(1 for c in stripped if c.isalpha())
    if letters < 2:
        return False
    
    return True


def extract_text_nodes(soup: BeautifulSoup) -> List[TextNode]:
    """
    Extract all text nodes from HTML.
    
    This finds all NavigableString nodes (leaf text) in the document,
    skipping script/style tags and other non-content areas.
    """
    nodes = []
    node_id = 0
    
    # Walk through all elements
    for tag in soup.find_all(True):
        # Skip script, style, and head content
        if tag.name in ('script', 'style', 'meta', 'link', 'title'):
            continue
        
        # Find all direct text node children
        for child in tag.children:
            if isinstance(child, NavigableString):
                # Skip HTML comments (Comment is a subclass of NavigableString)
                if isinstance(child, Comment):
                    continue
                
                text = str(child)

                # IMPORTANT: keep whitespace-only nodes too, otherwise you destroy spacing
                stripped = text.strip()

                # Capture leading/trailing whitespace
                m = re.match(r"^(\s*)(.*?)(\s*)$", text, re.DOTALL)
                prefix_ws = m.group(1) if m else ""
                core = m.group(2) if m else text
                suffix_ws = m.group(3) if m else ""

                # If it's purely whitespace, keep it but mark non-translatable
                is_translatable = is_translatable_text(core) if stripped else False

                nodes.append(TextNode(
                    node_id=node_id,
                    node=child,
                    parent=tag,
                    original_text=text,
                    stripped_text=core.strip() if stripped else "",
                    prefix_ws=prefix_ws,
                    suffix_ws=suffix_ws,
                    is_translatable=is_translatable,
                ))
                node_id += 1
    
    return nodes


def apply_translations(nodes: List[TextNode]) -> int:
    """
    Apply translations back to the text nodes.
    Returns number of nodes successfully applied.
    """
    applied = 0
    
    for text_node in nodes:
        if not text_node.translated_text:
            continue
        
        try:
            # Replace the text node content directly
            # This preserves all surrounding HTML structure
            translated_core = text_node.translated_text
            if translated_core is None:
                continue
            # Prevent model-inserted hard line breaks from inflating fixed-position boxes.
            translated_core = re.sub(r"\s*\n+\s*", " ", translated_core).strip()

            # Preserve original spacing around the core text
            replacement = f"{text_node.prefix_ws}{translated_core}{text_node.suffix_ws}"
            text_node.node.replace_with(replacement)
            applied += 1
            
        except Exception as e:
            print(f"Warning: Failed to apply translation for node {text_node.node_id}: {e}")
    
    return applied


def translate_html_content(
    html_in: Path,
    html_out: Path,
    target_lang: str,
    source_lang: Optional[str] = None
) -> TranslationStats:
    """
    Main entry point: Translate HTML content using LLM.
    """
    print(f"Loading HTML from {html_in}...")
    soup = BeautifulSoup(
        html_in.read_text(encoding="utf-8", errors="ignore"),
        "lxml"
    )
    
    print(f"Extracting text nodes...")
    nodes = extract_text_nodes(soup)
    print(f"Found {len(nodes)} text nodes")
    
    if not nodes:
        html_out.write_text(str(soup), encoding="utf-8")
        return TranslationStats(0, 0, 0, "unknown")
    
    # Show stats
    total_chars = sum(len(n.original_text) for n in nodes)
    print(f"  Total chars: {total_chars}")
    
    translator = LLMTranslator()
    
    # Detect source language
    if source_lang is None:
        print("Detecting source language...")
        samples = [n.original_text for n in nodes if len(n.original_text) > 20][:15]
        source_lang = translator.detect_language(samples)
        print(f"Detected source language: {source_lang}")

    if source_lang == target_lang:
        print(f"Detected {source_lang}. Continuing anyway (mixed-language safe mode).")
        print(f"Source and target language are the same ({source_lang}), skipping translation")
        html_out.write_text(str(soup), encoding="utf-8")
        return TranslationStats(0, len(nodes), 0, source_lang)
    
    print(f"Translating from {source_lang} to {target_lang}...")
    
    # Separate translatable and non-translatable
    translatable_nodes = [n for n in nodes if n.is_translatable]
    skipped_nodes = [n for n in nodes if not n.is_translatable]
    
    print(f"Translatable nodes: {len(translatable_nodes)}, Skipped: {len(skipped_nodes)}")
    
    # Translate in batches
    api_calls = 0
    batch_size = translator.batch_size
    retried_nodes = 0
    rejected_nodes = 0
    
    for i in range(0, len(translatable_nodes), batch_size):
        batch = translatable_nodes[i:i + batch_size]
        print(f"  Batch {i//batch_size + 1}/{(len(translatable_nodes) + batch_size - 1)//batch_size}: "
              f"{len(batch)} nodes...")
        
        translations = translator.translate_nodes(batch, source_lang, target_lang)
        api_calls += 1
        
        for node in batch:
            if node.node_id in translations:
                candidate = translations[node.node_id]
                if candidate is None:
                    continue

                if should_retry_translation(
                    node.stripped_text,
                    candidate,
                    source_lang,
                    target_lang,
                ):
                    retry = translator.translate_single_strict(
                        node.stripped_text,
                        source_lang,
                        target_lang,
                    )
                    api_calls += 1
                    retried_nodes += 1

                    if not retry or should_retry_translation(
                        node.stripped_text,
                        retry,
                        source_lang,
                        target_lang,
                    ):
                        rejected_nodes += 1
                        continue
                    candidate = retry

                node.translated_text = candidate

    if retried_nodes:
        print(f"Retried suspicious nodes: {retried_nodes} (rejected: {rejected_nodes})")
    
    # Apply translations
    applied = apply_translations(translatable_nodes)
    print(f"Applied {applied} translations")
    
    # Write output
    html_out.write_text(str(soup), encoding="utf-8")
    print(f"Wrote translated HTML to {html_out}")
    
    return TranslationStats(
        nodes_translated=applied,
        nodes_skipped=len(skipped_nodes) + (len(translatable_nodes) - applied),
        api_calls=api_calls,
        source_lang=source_lang
    )
