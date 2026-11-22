"""Regressions for the downloadable, disc-independent Field Guide."""
from html.parser import HTMLParser
import base64
import html
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shell.guide_book import public_gene_recipe, read_book
from tools import build_public_guide as guide


class EmbeddedBook(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("id") == "guide-data"

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.text.append(data)


class PublicGuideTests(unittest.TestCase):
    def test_reader_includes_native_volumes_with_stable_page_ids(self):
        public = guide.render(guide.ROOT)
        parsed = EmbeddedBook()
        parsed.feed(public["index.html"].decode())
        dataset = json.loads("".join(parsed.text))
        for game in ("bof3", "bof4"):
            book = read_book(guide.ROOT / "design/field-guide/wiki", game)
            self.assertEqual(book, dataset[game])
            self.assertEqual("print", book["sources"]["manual"]["kind"])
            self.assertNotIn("url", book["sources"]["manual"])
        self.assertEqual(7, len(dataset["extras"]["recipes"]))
        self.assertEqual(public_gene_recipe([0, 1, 2]), dataset["extras"]["recipes"]["flame+frost+thunder"])
        for bad in ([0, 0], [True], [3], [], [0, 1, 2, 3]):
            self.assertEqual({}, public_gene_recipe(bad))

    def test_all_editorial_maps_and_font_notices_travel_with_the_single_file(self):
        artifact = guide.render(guide.ROOT)["index.html"].decode()
        parsed = EmbeddedBook()
        parsed.feed(artifact)
        books = json.loads("".join(parsed.text))
        atlas = guide.ROOT / "design/field-guide/atlas"
        diagrams = books["extras"]["diagrams"]
        for game in ("bof3", "bof4"):
            for name, sheet in books[game]["fieldSheets"].items():
                expected = (atlas / sheet["map"]).read_bytes()
                embedded = diagrams[name]["image"].removeprefix("data:image/svg+xml;base64,")
                self.assertEqual(expected, base64.b64decode(embedded, validate=True))
                self.assertEqual({str(step["key"]) for step in sheet["steps"]}, set(diagrams[name]["points"]))
        for filename in ("OFL-Gloock.txt", "OFL-BarlowSemiCondensed.txt"):
            self.assertIn(html.escape((atlas / "type" / filename).read_text("utf-8")), artifact)
        self.assertIn("Wind on Kurok ridge", artifact)
        self.assertNotIn("private/design-review/",artifact)

    def test_route_markers_reject_active_external_and_out_of_bounds_content(self):
        original = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><g data-step="1"><circle class="selection" cx="5" cy="5"/></g></svg>'
        self.assertEqual({"1":[50,50]},guide.route_illustration(original,"fixture")["points"])
        for content in (b'<script/>', b'<use href="https://example.org/pin"/>', b'<g onload="x"/>',
                        b'<g data-step="2"><circle class="selection" cx="15" cy="0"/></g>'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                guide.route_illustration(original.replace(b"</svg>",content+b"</svg>"),"fixture")

    def test_editorial_text_cannot_end_the_inline_json_block(self):
        title = "A page about </ScRiPt> & <specimens>"
        with patch.object(guide, "read_book", return_value={"title": title}):
            document = guide.render(guide.ROOT)["index.html"].decode()
        self.assertNotIn(title, document)
        parsed = EmbeddedBook()
        parsed.feed(document)
        self.assertEqual(title, json.loads("".join(parsed.text))["bof3"]["title"])

    def test_rebuild_detects_stale_html_and_recreates_identical_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            guide.build(folder)
            expected = (folder / "index.html").read_bytes()
            guide.build(folder, check=True)
            (folder / "index.html").write_bytes(b"stale")
            with self.assertRaisesRegex(ValueError, "needs regeneration"):
                guide.build(folder, check=True)
            self.assertEqual(b"stale", (folder / "index.html").read_bytes())
            guide.build(folder)
            self.assertEqual(expected, (folder / "index.html").read_bytes())
