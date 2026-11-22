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

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from shell.guide_book import public_gene_recipe, read_book
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


def render(root: Path) -> dict[str, bytes]:
    guide = root / "design/field-guide"
    templates = root / "templates/public-guide"
    books = {game: read_book(guide / "wiki", game) for game in ("bof3", "bof4")}
    names = ("flame", "frost", "thunder")
    recipes = {"+".join(names[i] for i in group): public_gene_recipe(group)
               for size in (1, 2, 3) for group in itertools.combinations(range(3), size)}
    books["extras"] = {"recipes": recipes}
    data = json.dumps(books, ensure_ascii=False, separators=(",", ":"))
    plates = illustrations(root)
    artwork = "\n".join(f"--art-{key}:url('data:image/webp;base64,{base64.b64encode(raw).decode('ascii')}');"
                        for key, raw in plates.items())
    js = ((guide / "content.js").read_text(encoding="utf-8") + "\n"
          + (templates / "reader.js").read_text(encoding="utf-8"))
    css = (templates / "reader.css").read_text(encoding="utf-8")
    if re.search(r"</script", js, re.I) or re.search(r"</style", css, re.I):
        raise ValueError("Inline source contains an HTML closing tag")
    licence = root / "LICENSE.md"
    if not licence.is_file():
        licence = root / "templates/public-repo/LICENSE.md"
    notice = licence.read_text(encoding="utf-8").split("## MIT License\n", 1)[1].strip()
    parts = {"GUIDE_NOTICE": html.escape(notice), "GUIDE_ART": ":root {\n" + artwork + "\n}", "GUIDE_CSS": css, "GUIDE_JS": js,
             "GUIDE_DATA": data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")}
    template = (templates / "index.html").read_text(encoding="utf-8")
    marker = re.compile(r"{{(GUIDE_[A-Z]+)}}")
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
