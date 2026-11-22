"""Regressions for the downloadable, disc-independent Field Guide."""
from html.parser import HTMLParser
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
