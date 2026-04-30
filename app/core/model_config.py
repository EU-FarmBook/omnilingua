from __future__ import annotations

import os
from dataclasses import dataclass


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


@dataclass(frozen=True)
class ModelEndpointConfig:
    api_url: str
    api_key: str
    model: str


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
        model=_env_first("VISION_MODEL_NAME", "VISION_MODEL", default="internvl3-5-14b"),
    )
