from __future__ import annotations

from pathlib import Path

from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright


def _validate_chromium_path(executable_path: str) -> None:
    path = Path(executable_path)
    if path.exists():
        return

    raise RuntimeError(
        "Playwright Chromium is not installed. "
        "Run '.venv/bin/playwright install chromium' and retry."
    )


def ensure_chromium_installed() -> None:
    """
    Fail fast with a concise error if the Playwright Chromium binary
    has not been installed on the current machine.
    """
    with sync_playwright() as playwright:
        executable_path = playwright.chromium.executable_path

    _validate_chromium_path(executable_path)


async def ensure_chromium_installed_async() -> None:
    """
    Async variant for request handlers already running inside an event loop.
    """
    async with async_playwright() as playwright:
        executable_path = playwright.chromium.executable_path

    _validate_chromium_path(executable_path)
