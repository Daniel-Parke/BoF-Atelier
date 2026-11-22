"""Render the three reviewed editorial route drawings for Qt's image reader."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ATLAS = Path(__file__).resolve().parents[1] / "design/field-guide/atlas"


def main() -> None:
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 760, "height": 390}, device_scale_factor=2,
                                    offline=True, reduced_motion="reduce")
            for name in ("cedar", "kurok", "dam"):
                page.goto((ATLAS / f"{name}.svg").as_uri())
                page.evaluate("document.fonts.ready")
                drawing = page.locator("svg")
                if drawing.locator("[data-step]").count() != 4:
                    raise ValueError(f"Missing numbered landmark in {name}")
                with Image.open(BytesIO(drawing.screenshot())) as rendered:
                    if rendered.size != (1520, 780):
                        raise ValueError(f"Unexpected dimensions for {name}: {rendered.size}")
                    rendered.convert("RGB").save(ATLAS / f"{name}.webp", lossless=True, method=6)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
