"""Render the illustrated routes in the two editorial volumes for Qt's image reader."""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ATLAS = Path(__file__).resolve().parents[1] / "design/field-guide/atlas"


def main() -> None:
    sheets = {}
    for volume in ("bof3", "bof4"):
        book = json.loads((ATLAS.parent / "wiki" / (volume + ".json")).read_bytes())
        sheets.update(book["fieldSheets"])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("routes", nargs="*", metavar="ROUTE", help="Render only these illustrated routes")
    names = parser.parse_args().routes or list(sheets)
    if set(names) - sheets.keys():
        parser.error("Unknown route. Choose from " + ", ".join(sheets))
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 760, "height": 390}, device_scale_factor=2,
                                    offline=True, reduced_motion="reduce")
            for name in names:
                page.goto((ATLAS / f"{name}.svg").as_uri())
                page.evaluate("document.fonts.ready")
                drawing = page.locator("svg")
                markers = drawing.locator("[data-step]").evaluate_all("els => els.map(e => Number(e.dataset.step))")
                if sorted(markers) != [step["key"] for step in sheets[name]["steps"]]:
                    raise ValueError(f"Landmarks disagree with the directions for {name}")
                with Image.open(BytesIO(drawing.screenshot())) as rendered:
                    if rendered.size != (1520, 780):
                        raise ValueError(f"Unexpected dimensions for {name}: {rendered.size}")
                    rendered.convert("RGB").save(ATLAS / f"{name}.webp", lossless=True, method=6)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
