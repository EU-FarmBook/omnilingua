from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def normalize_openai_base_url(url: str) -> str:
    normalized = url.strip()
    if not normalized:
        return normalized
    if not normalized.rstrip("/").endswith("/v1"):
        normalized = normalized.rstrip("/") + "/v1"
    return normalized


def reasoning_kwargs() -> dict:
    """`reasoning_effort` for every chat completion, when configured.

    Scaleway's Generative APIs serve reasoning models: qwen3.5-397b-a17b fills
    `reasoning` before `content`. If that exhausts max_tokens the response ends
    with finish_reason=length and `content` is None — and several call sites
    here do `response.choices[0].message.content.strip()`, which raises
    AttributeError rather than degrading.

    "none" skips the reasoning phase. Sent through `extra_body` so it reaches
    the server verbatim, and empty by default so other providers are unaffected.
    """
    effort = _env_first("LLM_REASONING_EFFORT", default="")
    return {"extra_body": {"reasoning_effort": effort}} if effort else {}


@dataclass(frozen=True)
class ModelEndpointConfig:
    api_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class DeepLConfig:
    api_key: str
    server_url: Optional[str]
    en_variant: str
    pt_variant: str


def get_deepl_config() -> "DeepLConfig":
    return DeepLConfig(
        api_key=_env_first("DEEPL_API_KEY", "DEEPL_AUTH_KEY", default=""),
        server_url=_env_first("DEEPL_SERVER_URL", "DEEPL_API_URL", default="") or None,
        en_variant=_env_first("DEEPL_EN_VARIANT", default="EN-GB"),
        pt_variant=_env_first("DEEPL_PT_VARIANT", default="PT-PT"),
    )


def get_text_model_config() -> ModelEndpointConfig:
    return ModelEndpointConfig(
        api_url=normalize_openai_base_url(
            _env_first(
                "TEXT_MODEL_URL",
                "TEXT_URL",
                "RUNPOD_VLLM_HOST",
                "LLM_API_URL",
                default="http://localhost:8000/v1",
            )
        ),
        api_key=_env_first("TEXT_MODEL_API_KEY", "TEXT_API_KEY", "VLLM_API_KEY", "LLM_API_KEY", default=""),
        model=_env_first("TEXT_MODEL_NAME", "TEXT_MODEL", "VLLM_MODEL", "LLM_MODEL", default="qwen3-30b-a3b-awq"),
    )


def get_vision_model_config() -> ModelEndpointConfig:
    return ModelEndpointConfig(
        api_url=normalize_openai_base_url(
            _env_first("VISION_MODEL_URL", "VISION_URL", default="http://localhost:8001/v1")
        ),
        api_key=_env_first("VISION_MODEL_API_KEY", "VISION_API_KEY", default=""),
        model=_env_first("VISION_MODEL_NAME", "VISION_MODEL", default="qwen3-vl-30b-a3b-awq"),
    )
