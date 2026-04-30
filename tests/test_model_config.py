from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.model_config import get_text_model_config, get_vision_model_config


class ModelConfigTests(unittest.TestCase):
    def test_prefers_new_text_model_variable_names(self) -> None:
        env = {
            "TEXT_MODEL_URL": "https://text.example.com",
            "TEXT_MODEL_API_KEY": "text-key",
            "TEXT_MODEL_NAME": "qwen-test",
            "RUNPOD_VLLM_HOST": "https://legacy.example.com",
            "VLLM_API_KEY": "legacy-key",
            "VLLM_MODEL": "legacy-model",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_text_model_config()

        self.assertEqual(config.api_url, "https://text.example.com/v1")
        self.assertEqual(config.api_key, "text-key")
        self.assertEqual(config.model, "qwen-test")

    def test_falls_back_to_legacy_text_model_variable_names(self) -> None:
        env = {
            "RUNPOD_VLLM_HOST": "https://legacy.example.com",
            "VLLM_API_KEY": "legacy-key",
            "VLLM_MODEL": "legacy-model",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_text_model_config()

        self.assertEqual(config.api_url, "https://legacy.example.com/v1")
        self.assertEqual(config.api_key, "legacy-key")
        self.assertEqual(config.model, "legacy-model")

    def test_prefers_new_vision_model_variable_names(self) -> None:
        env = {
            "VISION_MODEL_URL": "https://vision.example.com/",
            "VISION_MODEL_API_KEY": "vision-key",
            "VISION_MODEL_NAME": "internvl-test",
            "VISION_URL": "https://legacy-vision.example.com",
            "VISION_API_KEY": "legacy-vision-key",
            "VISION_MODEL": "legacy-vision-model",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_vision_model_config()

        self.assertEqual(config.api_url, "https://vision.example.com/v1")
        self.assertEqual(config.api_key, "vision-key")
        self.assertEqual(config.model, "internvl-test")


if __name__ == "__main__":
    unittest.main()
