"""Build or verify the offline Field Guide and its two README illustrations."""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import itertools
import json
from pathlib import Path
import re
import sys
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from shell.guide_book import public_gene_recipe, read_book
from tools.atlas_assets import ATLAS_HASHES
from tools.local_store import atomic_bytes, plain_path


def illustrations(root: Path) -> dict[str, bytes]:
    guide = root / "design/field-guide"
    originals = json.loads((root / "design/skills/patter-art-chrysm/references/plates.json").read_bytes())["plates"]
    sheets = json.loads((guide / "wiki/illustrations.json").read_bytes())["sheets"]
    regional = {plate["id"]: plate for sheet in sheets for plate in sheet["plates"]}
    result = {}
    for filename, expected in (("plates.css", originals), ("wiki/illustrations.css", regional)):
        css = (guide / filename).read_text(encoding="ascii")
        rows = re.findall(r"--art-([a-z0-9-]+):\s*url\('data:image/webp;base64,([^']+)'\)", css)
        if len(rows) != len(expected) or {name for name, _ in rows} != expected.keys():
            raise ValueError(f"{filename} differs from its illustration inventory")
        for name, encoded in rows:
            raw = base64.b64decode(encoded, validate=True)
            if (name in result or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP"
                    or hashlib.sha256(raw).hexdigest() != expected[name]["sha256"]):
                raise ValueError(f"Invalid public illustration {name}")
            result[name] = raw
    return result


def route_illustration(raw: bytes, name: str) -> dict:
    """Read an authored SVG and locate its numbered route markers in the same coordinate system."""
    svg = ElementTree.fromstring(raw)
    ns = "{http://www.w3.org/2000/svg}"
    x0, y0, width, height = map(float, svg.attrib["viewBox"].split())
    if svg.tag != ns + "svg" or width <= 0 or height <= 0:
        raise ValueError(f"Invalid route drawing: {name}")
    points = {}
    for element in svg.iter():
        if element.tag in {ns + name for name in ("script", "foreignObject", "image", "a")}:
            raise ValueError(f"Unexpected content in route drawing: {name}")
        for attribute, value in element.attrib.items():
            if attribute.startswith("on") or (attribute.endswith("href") and not value.startswith("#")):
                raise ValueError(f"External or active content in route drawing: {name}")
        if "data-step" in element.attrib:
            key = element.attrib["data-step"]
            marker = element.find(f"{ns}circle[@class='selection']")
            if marker is None or not key.isdecimal() or key in points:
                raise ValueError(f"Invalid numbered marker in {name}")
            x = (float(marker.attrib["cx"]) - x0) / width
            y = (float(marker.attrib["cy"]) - y0) / height
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError(f"Marker outside drawing: {name}")
            points[key] = [round(x * 100, 4), round(y * 100, 4)]
    if not points:
        raise ValueError(f"Missing route markers: {name}")
    return {"image": "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii"),
            "points": points}


def reviewed_asset(atlas: Path, name: str) -> bytes:
    data = plain_path(atlas / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != ATLAS_HASHES["design/field-guide/atlas/" + name]:
        raise ValueError(f"Field Guide asset differs from its reviewed version: {name}")
    return data


def typefaces(atlas: Path) -> tuple[str, str]:
    faces = []
    notices = []
    for family, stem, weight, licence in (
            ("Gloock", "Gloock-Regular", 400, "OFL-Gloock.txt"),
            ("Barlow", "BarlowSemiCondensed-SemiBold", 600, "OFL-BarlowSemiCondensed.txt")):
        data = reviewed_asset(atlas, f"type/{stem}.ttf")
        text = reviewed_asset(atlas, f"type/{licence}").decode("utf-8").replace("\r\n", "\n")
        if data[:4] != b"\x00\x01\x00\x00" or "SIL OPEN FONT LICENSE" not in text.upper():
            raise ValueError(f"Missing typeface or licence for {stem}")
        uri = "data:font/ttf;base64," + base64.b64encode(data).decode("ascii")
        faces.append(f'@font-face{{font-family:{family};src:url("{uri}") format("truetype");'
                     f'font-weight:{weight};font-display:swap}}')
        notices.append(f"<details><summary>{html.escape(stem)}</summary><pre>{html.escape(text)}</pre></details>")
    return "\n".join(faces), "\n".join(notices)


def render(root: Path) -> dict[str, bytes]:
    guide = root / "design/field-guide"
    templates = root / "templates/public-guide"
    books = {game: read_book(guide / "wiki", game) for game in ("bof3", "bof4")}
    names = ("flame", "frost", "thunder")
    recipes = {"+".join(names[i] for i in group): public_gene_recipe(group)
               for size in (1, 2, 3) for group in itertools.combinations(range(3), size)}
    atlas = guide / "atlas"
    diagrams = {}
    for volume in books.values():
        for key, sheet in volume.get("fieldSheets", {}).items():
            if key in diagrams:
                raise ValueError(f"Duplicate illustrated route ID: {key}")
            diagram = route_illustration(reviewed_asset(atlas, sheet["map"]), key)
            if {str(step["key"]) for step in sheet["steps"]} != set(diagram["points"]):
                raise ValueError(f"Route markers differ from the directions for {key}")
            diagrams[key] = diagram
    books["extras"] = {"recipes": recipes, "diagrams": diagrams}
    data = json.dumps(books, ensure_ascii=False, separators=(",", ":"))
    plates = illustrations(root)
    plates["kurok-wind"] = reviewed_asset(atlas, "kurok-wind.webp")
    artwork = "\n".join(f"--art-{key}:url('data:image/webp;base64,{base64.b64encode(raw).decode('ascii')}');"
                        for key, raw in plates.items())
    js = ((guide / "content.js").read_text(encoding="utf-8") + "\n"
          + (templates / "reader.js").read_text(encoding="utf-8"))
    css = (templates / "reader.css").read_text(encoding="utf-8")
    fonts, font_notices = typefaces(atlas)
    if re.search(r"</script", js, re.I) or re.search(r"</style", css, re.I):
        raise ValueError("Inline source contains an HTML closing tag")
    licence = root / "LICENSE.md"
    if not licence.is_file():
        licence = root / "templates/public-repo/LICENSE.md"
    notice = licence.read_text(encoding="utf-8").split("## MIT License\n", 1)[1].strip()
    parts = {"GUIDE_NOTICE": html.escape(notice), "GUIDE_FONT_NOTICES": font_notices,
             "GUIDE_ART": fonts + "\n:root {\n" + artwork + "\n}", "GUIDE_CSS": css, "GUIDE_JS": js,
             "GUIDE_DATA": data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")}
    template = (templates / "index.html").read_text(encoding="utf-8")
    marker = re.compile(r"{{(GUIDE_[A-Z_]+)}}")
    if sorted(marker.findall(template)) != sorted(parts):
        raise ValueError("Expected exactly one slot per Field Guide resource")
    document = marker.sub(lambda match: parts[match[1]], template)
    return {"index.html": document.encode(), "art/atelier.webp": plates["highlands"],
            "art/sandsea.webp": plates["sandsea"], ".nojekyll": b""}


def build(output: Path, check: bool = False) -> None:
    for name, data in render(ROOT).items():
        target = plain_path(output / name)
        if target.is_file() and target.read_bytes() == data:
            continue
        if check:
            raise ValueError(f"{name} needs regeneration. Run python tools/build_public_guide.py")
        atomic_bytes(target, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    default_output = ROOT / ("private/design-review/public-guide/site" if (ROOT / "01-MASTER-PROMPT.md").is_file() else "docs")
    parser.add_argument("--output", type=Path, default=default_output)
    parser.add_argument("--check", action="store_true", help="Check the existing outputs without changing them")
    opts = parser.parse_args()
    try:
        build(opts.output, opts.check)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Field Guide {'verified' if opts.check else 'built'} at {opts.output / 'index.html'}")
