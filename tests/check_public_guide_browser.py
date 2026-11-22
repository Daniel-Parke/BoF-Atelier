"""Check the release Field Guide in headless Chromium over file and project-site HTTP.

Developer check: install Playwright in the developer environment, then pass the path
to an installed Chrome or Edge executable with --browser. No game data is used.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shell.guide_book import read_book


@contextmanager
def project_site(document: bytes):
    """Serve only the tested artifact at a repository subpath on loopback."""
    site_path = "/BoF-Atelier/"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if self.path not in {site_path, site_path + "index.html"}:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(document)))
            self.end_headers()
            self.wfile.write(document)

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}{site_path}"
        finally:
            server.shutdown()
            thread.join()


def set_route(page, base: str, game: str, entry: str):
    page.goto(f"{base}#{game}/{entry}")


def no_overflow(page):
    dimensions = page.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
    assert dimensions[0] <= dimensions[1] + 1, (page.url, dimensions)


def screenshot(page, destination: Path | None, name: str):
    if destination:
        destination.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=destination / f"{name}.png", animations="disabled")


def check_art_and_content(page, volumes: dict):
    for game, source in volumes.items():
        embedded = page.locator("#guide-data").evaluate("(e, game) => JSON.parse(e.textContent)[game]", game)
        assert embedded == source, f"{game} browser content differs from the native book"
    art = page.evaluate("""async () => {
        const css = getComputedStyle(document.documentElement);
        const names = Array.from(css).filter(name => name.startsWith('--art-'));
        for (const name of names) {
            const value = css.getPropertyValue(name).trim();
            const src = value.slice(4, -1).replace(/^['"]|['"]$/g, '');
            if (!src.startsWith('data:image/webp;base64,')) throw Error(name + ' is not embedded');
            const img = new Image();
            img.src = src;
            await img.decode();
            if (!img.naturalWidth || !img.naturalHeight) throw Error(name + ' has no dimensions');
        }
        return names;
    }""")
    expected = {row["art"] for b in volumes.values() for row in b["route"] + b["articles"]}
    actual = {name.removeprefix("--art-") for name in art}
    assert expected <= actual, f"Missing illustrations: {expected - actual}"
    return len(actual)


def check_all_pages(page, volumes: dict):
    # Change fragments as a reader would. Reloading the multi-megabyte file on
    # each case would test initial paint in place of actual page navigation.
    totals = {}
    for game, volume in volumes.items():
        pages = volume["route"] + volume["articles"]
        for row in pages:
            page.evaluate(
                """async hash => {
                    location.hash = hash;
                    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                }""", f"{game}/{row['id']}"
            )
            expect(page.get_by_role("heading", level=1)).to_have_text(row["title"])
            no_overflow(page)
        totals[game] = len(pages)
    return totals


def check_reader_actions(page, base: str, volumes: dict, destination: Path | None):
    main = page.get_by_role("main")
    set_route(page, base, "bof4", "walk")
    expect(main.get_by_text(volumes["bof4"]["route"][-1]["title"], exact=True)).to_be_hidden()
    reveal_stops = main.get_by_role("button", name="Show later stops")
    reveal_stops.click()
    expect(main.get_by_text(volumes["bof4"]["route"][-1]["title"], exact=True)).to_be_visible()
    main.get_by_role("button", name="Hide later stops").click()
    expect(main.get_by_text(volumes["bof4"]["route"][-1]["title"], exact=True)).to_be_hidden()
    search = page.get_by_role("searchbox", name="Search this volume")
    search.fill("Deep Diver")
    search.press("Enter")
    reveal = page.get_by_role("button", name="Show later matches")
    expect(reveal).to_be_visible()
    reveal.click()
    item_link = main.locator('a[href$="/dam-kyria-items"]')
    expect(item_link).to_be_visible()
    item_link.click()
    expect(main.get_by_role("row").filter(has_text="Deep Diver")).to_be_visible()
    item_url = page.url
    page.go_back()
    expect(page).to_have_url(re.compile(r"#bof4/search"))
    page.go_forward()
    expect(page).to_have_url(item_url)

    search.fill("unlisted-query-1234")
    search.press("Enter")
    expect(main).to_contain_text("No matching pages")
    set_route(page, base, "bof3", "genes")
    for name in ("Flame", "Frost", "Thunder"):
        button = page.get_by_role("button", name=re.compile(name))
        button.focus()
        page.keyboard.press("Enter")
        expect(button).to_have_attribute("aria-pressed", "true")
    expect(main.get_by_text("Trygon", exact=True)).to_be_visible()
    expect(main).to_contain_text(re.compile("15.*AP", re.I))
    screenshot(page, destination, "genes")
    for name in ("Flame", "Frost", "Thunder"):
        page.get_by_role("button", name=name, exact=True).click()
    expect(page.get_by_role("button", name=re.compile("Flame"))).to_have_attribute("aria-pressed", "false")
    expect(main.get_by_role("status")).to_contain_text("Choose a gene")
    set_route(page, base, "bof4", "dam-kyria")
    expect(main.get_by_text("Kurok, the Dam and Kyria Woods", exact=True).first).to_be_visible()
    screenshot(page, destination, "kurok")
    main.get_by_text(re.compile("^Route diagram")).click()
    expect(main.get_by_role("listitem").filter(has_text="Chamba approach")).to_be_visible()
    main.get_by_role("navigation", name="Area").get_by_role("link", name="Dam", exact=True).click()
    expect(main.get_by_role("table", name="Items")).to_contain_text("Sluice Key")
    expect(main.get_by_text("Missable", exact=True)).to_be_visible()
    floor = main.get_by_role("combobox", name="Floor")
    floors = floor.locator("option").all_text_contents()
    selected = next(name for name in floors if "gate tunnel" in name)
    floor.select_option(label=selected)
    expect(main.get_by_text("Flywheel controls", exact=True)).to_be_visible()
    main.get_by_text("Sources", exact=True).click()
    for key in next(row for row in volumes["bof4"]["route"] if row["id"] == "dam-kyria")["sources"]:
        source = volumes["bof4"]["sources"][key]
        expect(main.get_by_text(source["title"], exact=True)).to_be_visible()
    main.get_by_role("button", name="Bookmark page").click()
    expect(main.get_by_role("button", name="Bookmarked")).to_have_attribute("aria-pressed", "true")
    page.reload()
    expect(main.get_by_role("button", name="Bookmarked")).to_have_attribute("aria-pressed", "true")
    set_route(page, base, "bof4", "page-without-an-entry")
    expect(main.get_by_role("heading", level=1)).to_have_text("Page not found")
    main.get_by_role("link", name="Back to the volume").click()
    expect(main.get_by_role("heading", level=1)).to_have_text("Breath of Fire IV")


def check_transport(browser, base: str, document: bytes, volumes: dict,
                    destination: Path | None, offline: bool):
    errors, external = [], []
    context = browser.new_context(
        offline=offline, reduced_motion="reduce", viewport={"width": 1360, "height": 900}
    )
    context.set_default_timeout(5000)

    def guard(route):
        url = route.request.url
        if urlsplit(url).scheme in {"http", "https", "file"} and (
                url.split("#")[0] != base and url != base + "index.html"):
            external.append(url)
            route.abort()
        else:
            route.continue_()

    context.route("**/*", guard)
    context.on("page", lambda p: p.on("pageerror", lambda err: errors.append(str(err))))
    page = context.new_page()
    try:
        response = page.goto(base)
        if not offline:
            assert response and response.status == 200 and response.body() == document
        expect(page.get_by_role("heading", level=1)).to_be_visible()
        no_overflow(page)
        art_count = check_art_and_content(page, volumes)
        offline_link = page.get_by_role("link", name="Download for offline reading")
        if offline:
            expect(offline_link).to_have_count(0)
        else:
            with page.expect_download() as event:
                offline_link.click()
            download = event.value
            assert download.suggested_filename == "BoF-Atelier-Field-Guide.html"
            assert download.path().read_bytes() == document
            page.evaluate("window.scrollTo(0,0)")
        screenshot(page, destination, "desktop")
        check_reader_actions(page, base, volumes, destination)
        totals = check_all_pages(page, volumes)
        page.set_viewport_size({"width": 375, "height": 812})
        for game, entry in (("bof3", "genes"), ("bof4", "dam-kyria"), ("bof4", "wiki")):
            set_route(page, base, game, entry)
            no_overflow(page)
        screenshot(page, destination, "mobile")
        page.get_by_role("navigation", name="Choose a game").get_by_role("link", name="Breath of Fire IV", exact=True).click()
        expect(page.get_by_role("heading", level=1)).to_have_text("Breath of Fire IV")
        screenshot(page, destination, "mobile-cover")
        page.get_by_role("link", name="Open walkthrough").click()
        page.get_by_role("main").locator("a[href$='/north-desert']").click()
        expect(page.get_by_role("heading", level=1)).to_have_text(volumes["bof4"]["route"][1]["title"])
        for entry in ("genes", "walk", "wiki"):
            set_route(page, base, "bof3", entry)
            page.set_viewport_size({"width": 320, "height": 568})
            no_overflow(page)
        assert not errors, errors
        assert not external, external
        return {"pages": totals, "decoded_illustrations": art_count,
                "page_errors": errors, "external_requests": external}
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True, help="Installed Chromium-based browser")
    parser.add_argument("--book", type=Path, default=ROOT / "docs/index.html")
    parser.add_argument("--canonical", type=Path, default=ROOT / "design/field-guide/wiki",
                        help="Source books to compare with the selected HTML file")
    parser.add_argument("--captures", type=Path, help="Write review screenshots and a check receipt here")
    parser.add_argument("--live-url", help="Also verify the published HTTPS project page against this build")
    args = parser.parse_args()
    if args.live_url and (urlsplit(args.live_url).scheme != "https" or not args.live_url.endswith("/")):
        parser.error("--live-url must be the HTTPS address of the published guide ending in /")
    book = args.book.resolve(strict=True)
    volumes = {game: read_book(args.canonical, game) for game in ("bof3", "bof4")}
    document = book.read_bytes()
    receipt = {"document_sha256": sha256(document).hexdigest()}
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=str(args.browser.resolve(strict=True)),
                                         headless=True, chromium_sandbox=True)
        try:
            receipt["browser_version"] = browser.version
            receipt["file"] = check_transport(browser, book.as_uri(), document, volumes,
                                              args.captures / "file" if args.captures else None, True)
            with project_site(document) as base:
                receipt["http"] = check_transport(browser, base, document, volumes,
                                                  args.captures / "http" if args.captures else None, False)
            if args.live_url:
                receipt["live_url"] = args.live_url
                receipt["live"] = check_transport(browser, args.live_url, document, volumes,
                                                  args.captures / "live" if args.captures else None, False)
        finally:
            browser.close()
    result = json.dumps(receipt, indent=2)
    print(result)
    if args.captures:
        (args.captures / "browser-results.json").write_text(result + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
