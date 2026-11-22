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
from urllib.parse import quote, urlencode, urlsplit

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


# Use the fragment router throughout. This exercises the published URLs without
# reloading the multi-megabyte book for each of the several hundred entries.
SWEEP = """async paths => {
    const result = [];
    for (const path of paths) {
        const hash = '#' + path;
        if (location.hash !== hash) await new Promise(resolve => {
            window.addEventListener('hashchange', resolve, {once:true});
            location.hash = hash;
        });
        const main = document.querySelector('main');
        result.push({
            path,
            game:document.body.dataset.game,
            title:main.querySelector('h1')?.textContent,
            floor:main.querySelector('#floor option:checked')?.textContent,
            floorOpen:main.querySelector('[data-panel=floor]')?.open,
            overflow:document.documentElement.scrollWidth - document.documentElement.clientWidth,
            links:[...document.querySelectorAll('main a, #spine a')].map(a=>a.getAttribute('href'))
                .filter(url=>url && url.startsWith('#bof')).map(url=>url.slice(1))
        });
    }
    return result;
}"""


def sweep(page, addresses):
    return page.evaluate(SWEEP, list(addresses))


def check_pages_and_links(page, volumes: dict):
    names = {}
    floors = {}
    for game, book in volumes.items():
        for stop in book["route"]:
            destination = f"{game}/{stop['id']}"
            names[destination] = book["fieldSheets"].get(stop["id"], {}).get("title", stop["title"])
            parts = stop.get("sectionsByArea") or [{"name": ""}]
            for part in parts:
                area = part["name"]
                local = [f for f in stop.get("floors", []) if not area or f["mapId"] in part["floorIds"]]
                for number, floor in enumerate(local):
                    query = {"floor": number, "map": floor["mapId"], "section": floor["section"]}
                    if area:
                        query["area"] = area
                    floors[destination + "?" + urlencode(query)] = floor["name"]
        names.update({f"{game}/{article['id']}": article["title"] for article in book["articles"]})
        names.update({f"{game}/{quote(entry['id'], safe='')}": entry["name"] for entry in book["entities"].values()})
        for key, field in book["fieldSheets"].items():
            names[f"{game}/{key}"] = field["title"]
    names.update({
        "bof3/genes": "Dragon genes", "bof3/flame":"Flame", "bof3/frost":"Frost",
        "bof3/thunder":"Thunder", "bof3/diary":"Using a diary", "bof4/masters":"Master training",
        "bof4/dragons":"Dragons & evocation", "bof4/rwolf":"Rwolf",
    })
    snapshots = sweep(page, names)
    for snap in snapshots:
        assert (snap["title"], snap["game"]) == (names[snap["path"]], snap["path"].split("/")[0]), snap
        assert snap["overflow"] <= 1, snap["path"]
    floor_results = sweep(page, floors)
    for result in floor_results:
        assert result["floorOpen"] and result["floor"] == floors[result["path"]], result
    legacy = {"bof3/cedar?floor=3": ("McNeil village", 7), **{
        f"bof4/dam-kyria?area=Kyria&floor={i}": ("Kyria Woods", mid)
        for i, mid in enumerate((1043, 1045, 1046), 1)}}
    town = next(s for s in volumes["bof4"]["route"] if s["id"] == "synesta")
    # All eight links published before the passage was illustrated must still open the same floor.
    for i, (map_id, section) in enumerate(((4098, 0), (1093, 0), (1093, 1), (1093, 3),
                                           (1093, 4), (1093, 5), (1138, 0), (4103, 0))):
        expected = next(f["name"] for f in town["floors"] if (f["mapId"], f["section"]) == (map_id, section))
        for path in (f"bof4/synesta?floor={i}", f"bof4/synesta?floor={i}&map={map_id}&section={section}"):
            result, = sweep(page, [path])
            assert (result["title"], result["floor"], result["floorOpen"]) == (town["title"], expected, True), result
    for result in sweep(page, legacy):
        title, map_id = legacy[result["path"]]
        expected = next(f["name"] for stop in volumes[result["game"]]["route"] for f in stop.get("floors", [])
                        if f["mapId"] == map_id)
        assert result["title"] == title and result["floorOpen"] and result["floor"] == expected, result
    # Include both the spoiler-limited and the opt-in indexes when gathering links.
    indexes = []
    for game in volumes:
        for slug in ("", "guide", "index", "walk", "route", "wiki"):
            indexes += sweep(page, [f"{game}/{slug}"])
        for reveal in (True, False):
            for slug in ("walk", "wiki"):
                fragment = f"{game}/{slug}"
                sweep(page, [fragment])
                toggle = page.locator("main button[data-action=reveal]").first
                if (toggle.get_attribute("aria-expanded") == "true") != reveal:
                    toggle.click()
                indexes += sweep(page, [fragment])
    links = {target for s in [*snapshots,*floor_results,*indexes] for target in s["links"]}
    followed = sweep(page, sorted(links - names.keys() - floors.keys()))
    assert all(s["title"] and s["title"] != "Page not found" for s in followed), [
        s["path"] for s in followed if not s["title"] or s["title"] == "Page not found"]
    return {"route_and_article_pages":sum(len(b["route"])+len(b["articles"]) for b in volumes.values()),
            "named_entries":sum(len(b["entities"]) for b in volumes.values()), "special_pages":8,
            "floor_links":len(floors), "distinct_internal_link_targets":len(links)}


def check_reader_actions(page, base: str, volumes: dict, destination: Path | None):
    main = page.get_by_role("main")
    set_route(page, base, "bof4", "walk")
    last = volumes["bof4"]["route"][-1]["title"]
    expect(main.get_by_text(last, exact=True)).to_be_hidden()
    main.get_by_role("button", name="Show later stops").click()
    expect(main.get_by_text(last, exact=True)).to_be_visible()
    main.get_by_role("button", name="Hide later names").click()
    expect(main.get_by_text(last, exact=True)).to_be_hidden()
    page.keyboard.press("/")
    search = page.get_by_role("searchbox", name="Place, item, enemy or skill")
    expect(search).to_be_focused()
    search.fill("Deep Diver")
    expect(main.get_by_role("link",name="Deep Diver", exact=False)).to_have_count(0)
    main.get_by_role("button", name="Show later matches").click()
    item_link = main.locator("a[href$='/item.deep%20diver']")
    expect(item_link).to_be_visible()
    item_link.click()
    expect(main.get_by_role("heading", level=1)).to_have_text("Deep Diver")
    expect(main).to_contain_text("upper western path")
    page.go_back()
    expect(search).to_have_value("Deep Diver")
    page.go_forward()
    expect(main.get_by_role("heading", level=1)).to_have_text("Deep Diver")
    page.get_by_role("link", name="Search guide").click()
    search.fill("unlisted-query-1234")
    expect(main).to_contain_text("No matching pages.")
    main.get_by_role("button", name="Hide later names").click()
    for game, term, target in (("bof3","Mount Glaus","glaus"),("bof3","McNeil village","mcneil"),
            ("bof3","D'Lonzo","teacher-dlonzo"),("bof4","Kyria Woods","kyria-woods"),
            ("bof4","Synesta Pathway","kyria-passage"),("bof4","Kyria passage","kyria-passage"),("bof4","Synesta","synesta"),
            ("bof4","Synesta orphanage","synesta"),("bof4","Find Chino","synesta"),("bof4","Synesta Cellar","synesta"),
            ("bof4","Kurok","kurok"),("bof4","Dam","dam"),("bof3","Momo's Tower","momo-tower"),
            ("bof4","Bandit's Hideout","bandit-hideout"),("bof4","Wyndia Castle Basement","wyndia-basement"),
            ("bof4","Mt. Grom","mt-glom"),("bof4","Yaen","enemy.yaen")):
        set_route(page,base,game,"search")
        if main.locator("button[data-action=reveal]").get_attribute("aria-expanded") != "true":
            main.get_by_role("button", name="Show later matches").click()
        search.fill(term)
        first = main.locator("#matches a").first
        expect(first).to_have_attribute("href",f"#{game}/{target}")
        first.click()
        expect(main.get_by_role("heading",level=1)).to_be_visible()
    for game in ("bof3","bof4"):
        set_route(page,base,game,"search")
        main.get_by_role("button", name="Hide later names").click()
    set_route(page,base,"bof4","masters")
    expect(main.get_by_role("combobox",name="Apprentice under")).to_have_count(0)
    main.get_by_role("button",name="Show later masters").click()
    teachers = volumes["bof4"]["teachers"]
    roster = main.get_by_role("combobox",name="Apprentice under")
    assert roster.locator("option").all_text_contents() == [t["name"] for t in teachers]
    stats = ["HP","AP","power","defence","agility","wisdom"]
    for teacher, baseline in zip(teachers, teachers[1:] + teachers[:1]):
        roster.select_option(teacher["id"])
        main.get_by_role("combobox",name="Compare with").select_option(baseline["id"])
        observed = [int(cell) for cell in main.locator(".stat-grid dd").all_text_contents()]
        assert observed == [teacher["growth"][key] - baseline["growth"][key] for key in stats]
        for lesson in teacher["lessons"]:
            expect(main.get_by_role("table",name="Lessons and rewards")).to_contain_text(lesson["skill"])
    roster.select_option("teacher-rwolf")
    main.get_by_role("combobox",name="Compare with").select_option("")
    main.get_by_role("button",name="Hide later names").first.click()

    set_route(page, base, "bof3", "genes")
    names = ("Flame", "Frost", "Thunder")
    recipes = page.locator("#guide-data").evaluate("el=>JSON.parse(el.textContent).extras.recipes")
    for key, recipe in recipes.items():
        for name in names:
            gene = main.get_by_role("button", name=name, exact=True)
            selected = gene.get_attribute("aria-pressed") == "true"
            if (name.lower() in key.split("+")) != selected:
                gene.focus()
                page.keyboard.press("Enter")
        result = main.get_by_role("status")
        expect(result.get_by_text(recipe["form"], exact=True)).to_be_visible()
        expect(result).to_contain_text(f"{recipe['cost']} initial AP")
    screenshot(page, destination, "genes")
    main.get_by_role("button", name="Clear").click()
    expect(main.get_by_role("status")).to_contain_text("Choose a gene")

    set_route(page, base, "bof4", "dam-kyria")
    chapter = next(s for s in volumes["bof4"]["route"] if s["id"] == "dam-kyria")
    expect(main.get_by_role("heading", level=1)).to_have_text(chapter["title"])
    main.locator("a[href='#bof4/kurok']").click()
    expect(main.get_by_text("Missable", exact=True)).to_be_hidden()
    for game, location in ((game, key) for game, book in volumes.items() for key in book["fieldSheets"]):
        set_route(page, base, game, location)
        sheet = volumes[game]["fieldSheets"][location]
        figure = main.get_by_role("img", name=sheet["mapAlt"])
        expect(figure).to_be_visible()
        assert figure.evaluate("el=>el.complete && el.naturalWidth>0"), location
        for direction in sheet["steps"]:
            number = direction["key"]
            main.locator(f".map-pin[data-number='{number}']").click()
            step = main.locator(f".step-button[data-number='{number}']")
            expect(step).to_contain_text(direction["title"])
            expect(step).to_have_attribute("aria-pressed","true")
            expect(step.locator(".step-body")).to_have_text(direction["body"])
            expect(step.locator(".step-body")).to_be_visible()
        stop = next(s for s in volumes[game]["route"] if s["id"] == sheet["stop"])
        for kind, label in (("items","Items"), ("encounters","Enemies")):
            expected = [r["name"] for r in stop.get(kind,[]) if not stop.get("sectionsByArea") or location in r["areaIds"]]
            tab = main.get_by_role("tab", name=label, exact=True)
            if expected:
                tab.click()
                assert main.get_by_role("table",name=label).locator("tbody th a").all_text_contents() == expected, (location,label)
            else:
                expect(tab).to_have_count(0)
        main.get_by_role("tab",name="Directions").click()
        screenshot(page, destination, location)
        opener = main.get_by_role("button", name="Enlarge map")
        opener.click()
        modal = page.get_by_role("dialog")
        expect(modal).to_be_visible()
        modal.locator(".map-pin[data-number='4']").click()
        expect(modal.locator("#enlarged-direction")).to_have_text(sheet["steps"][3]["body"])
        page.keyboard.press("Escape")
        expect(opener).to_be_focused()
        expect(main.locator(".step-button[data-number='4']")).to_have_attribute("aria-pressed", "true")
        main.get_by_role("button",name="Read all steps").click()
        for direction in sheet["steps"]:
            expect(main.get_by_text(direction["body"],exact=True)).to_be_visible()
        main.get_by_role("button",name="Show selected step").click()

    set_route(page,base,"bof4","kurok")
    main.locator(".map-pin[data-number='3']").click()
    main.get_by_role("tab",name="Items").click()
    treasure = main.get_by_role("table", name="Items").get_by_role("link",name="Deep Diver")
    treasure.click()
    expect(main.get_by_text(re.compile("Open the chest on the upper western path"))).to_be_visible()
    main.get_by_role("navigation",name="Reader navigation").get_by_role("link").click()
    expect(treasure).to_be_focused()
    expect(main.locator(".step-button[data-number='3']")).to_have_attribute("aria-pressed", "true")
    main.get_by_role("tab",name="Enemies").click()
    main.get_by_role("table", name="Enemies").get_by_role("link",name="Mage Goo").click()
    expect(main.get_by_role("heading",level=1)).to_have_text("Mage Goo")
    page.go_back()
    main.get_by_role("link",name="The Dam",exact=True).click()
    danger = main.get_by_label("Missable", exact=True)
    for name in ("Short Sword", "two Vitamins", "two Swallow Eyes"):
        expect(danger).to_contain_text(name)
    main.get_by_role("tab",name="Items").click()
    for name in ("Sluice Key","Flywheel prize","Crank"):
        expect(main.get_by_role("table",name="Items")).to_contain_text(name)
    main.get_by_role("tab",name="Enemies").click()
    expect(main.get_by_role("table",name="Enemies")).to_contain_text("Army Bat")
    for key,panel in (("opening","before"),("after","after")):
        main.get_by_role("tab",name="Directions" if key == "opening" else "Notes").click()
        detail = main.locator(f"details[data-panel='{panel}']")
        detail.locator("summary").click()
        for line in volumes["bof4"]["fieldSheets"]["dam"][key]["steps"]:
            expect(detail.get_by_text(line,exact=True)).to_be_visible()
    main.get_by_role("tab",name="Floors").click()
    floor = main.get_by_role("combobox",name="Floor")
    floors = floor.locator("option").all_text_contents()
    floor.select_option(label=next(name for name in floors if "gate tunnel" in name))
    expect(main.get_by_text("Flywheel controls",exact=True)).to_be_visible()
    expect(floor).to_be_focused()
    main.get_by_role("tab",name="Notes").click()
    main.locator(".bibliography summary").click()
    stop = next(r for r in volumes["bof4"]["route"] if r["id"] == "dam-kyria")
    for key in stop["sources"]:
        expect(main.get_by_text(volumes["bof4"]["sources"][key]["title"],exact=True)).to_be_visible()
    for ref in stop.get("sourceSections", []):
        expect(main.locator(".bibliography").get_by_text(ref["section"], exact=True)).to_be_visible()
    main.get_by_role("button",name="Bookmark page").click()
    main.get_by_role("button",name="Mark my place").click()
    page.reload()
    expect(main.get_by_role("button",name="Bookmarked")).to_have_attribute("aria-pressed","true")
    expect(main.get_by_role("button",name="Reading place saved")).to_be_visible()

    set_route(page, base, "bof4", "synesta")
    expect(main.get_by_role("heading", level=1)).to_have_text("The children of Synesta")
    directions = main.locator("ol.written")
    for landmark in ("orphanage", "bookcase", "Chino"):
        expect(directions).to_contain_text(re.compile(landmark, re.I))
    main.get_by_role("tab",name="Items").click()
    town_items = main.get_by_role("table", name="Items")
    for item in ("Ammonia", "Protein", "80 zenny", "Raptor Claws"):
        expect(town_items.get_by_role("rowheader").filter(has_text=item)).to_be_visible()
    expect(town_items.get_by_role("rowheader").filter(has_text="Water Bomb")).to_have_count(0)
    screenshot(page, destination, "synesta-town")

    for slug in ("masters","rwolf","teacher-rwolf"):
        set_route(page,base,"bof4",slug)
        lessons = main.get_by_role("table",name="Lessons and rewards")
        rwolf = next(t for t in volumes["bof4"]["teachers"] if t["name"] == "Rwolf")
        for row in rwolf["lessons"]:
            expect(lessons.get_by_role("row").filter(has_text=row["skill"])).to_contain_text(row["goal"])
    set_route(page,base,"bof4","combination-magic")
    article = next(a for a in volumes["bof4"]["articles"] if a["id"] == "combination-magic")
    for table in article["referenceTables"]:
        rows = main.get_by_role("table",name=table["title"]).locator("tbody tr")
        expect(rows).to_have_count(len(table["rows"]))
        for i, entry in enumerate(table["rows"]):
            assert rows.nth(i).locator("th,td").all_text_contents() == entry

    set_route(page,base,"bof4","page-without-an-entry")
    expect(main.get_by_role("heading",level=1)).to_have_text("Page not found")
    main.get_by_role("link",name="Back to the volume").click()
    expect(main.get_by_role("heading",level=1)).to_have_text("Breath of Fire IV")

def check_responsive(page, base, destination):
    wide_routes = [("bof3","cedar"),("bof3","mcneil"),("bof3","glaus"),("bof4","kurok"),("bof4","dam"),
                   ("bof4","kyria"),("bof4","kyria-woods"),("bof4","kyria-passage"),("bof4","teacher-rwolf"),
                   ("bof4","synesta?step=11"),("bof4","marloks-house"),("bof4","bandit-hideout"),
                   ("bof3","item.vitamin?at=mcneil&sighting=Manor+approach"),("bof4","enemy.mouse?at=synesta"),
                   ("bof3","genes"),("bof4","combination-magic"),("bof3","wiki")]
    for width,height in ((1920,1080),(1280,720),(850,800),(768,900),(390,844),(320,568)):
        page.set_viewport_size({"width":width, "height":height})
        for game,leaf in wide_routes:
            set_route(page,base,game,leaf)
            no_overflow(page)
        set_route(page,base,"bof4","kurok")
        if width == 390:
            screenshot(page,destination,"mobile-kurok")
        if width == 1280:
            screenshot(page,destination,"kurok-720p")
    page.get_by_role("button",name="Contents").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("link",name="Breath of Fire III").click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("heading",level=1)).to_have_text("Breath of Fire III")
    page.get_by_role("main").locator("a[href$='/walk']").click()
    page.get_by_role("main").locator("a[href$='/cedar']").click()
    expect(page.get_by_role("heading",level=1)).to_have_text("Cedar Woods")
    # Equal CSS viewport to a 1280px screen at 200% zoom, then text-only scaling.
    page.set_viewport_size({"width":640,"height":540})
    no_overflow(page)
    page.set_viewport_size({"width":1280,"height":900})
    page.evaluate("document.documentElement.style.fontSize='200%'")
    for game,leaf in wide_routes:
        set_route(page,base,game,leaf)
        no_overflow(page)
    set_route(page,base,"bof4","dam")
    expect(page.get_by_role("button",name="Contents")).to_be_visible()
    expect(page.locator("#spine")).to_be_hidden()
    screenshot(page,destination,"dam-large-text")
    page.evaluate("document.documentElement.style.removeProperty('font-size')")
    page.set_viewport_size({"width":1360,"height":900})


def check_detail_navigation(page, base, volumes):
    main = page.get_by_role("main")
    back = main.get_by_role("navigation", name="Reader navigation").get_by_role("link")
    tabs = main.get_by_role("tablist", name="On this page")
    page.set_viewport_size({"width": 390, "height": 844})

    def saved_y(link):
        link.evaluate("el=>el.scrollIntoView({block:'center'})")
        link.focus()
        return page.evaluate("scrollY")

    def returned_to(link, position):
        expect(link).to_be_focused()
        assert abs(page.evaluate("scrollY") - position) <= 2, (page.url, position, page.evaluate("scrollY"))

    def follow_article_floor(game, stop_id, area_id, map_id, section):
        stop = next(s for s in volumes[game]["route"] if s["id"] == stop_id)
        floor = next(f for f in stop["floors"] if (f["mapId"], f["section"]) == (map_id, section))
        article_title = main.get_by_role("heading",level=1).inner_text()
        reference = main.get_by_role("link",name=f"Floor landmarks · {floor['name']}",exact=True)
        expect(reference).to_have_attribute("href",re.compile(rf"^#{game}/{area_id}\?"))
        origin_y = saved_y(reference)
        reference.press("Enter")
        expect(tabs.get_by_role("tab",name="Floors")).to_have_attribute("aria-selected","true")
        current = main.get_by_role("combobox",name="Floor").locator("option:checked")
        expect(current).to_have_text(floor["name"])
        expect(current).to_have_attribute("data-map",str(map_id))
        expect(current).to_have_attribute("data-section",str(section))
        for landmark in floor["landmarks"]:
            expect(main.locator("[data-panel=floor]").get_by_text(landmark["name"],exact=True)).to_be_visible()
        expect(back).to_have_accessible_name("Back to " + article_title)
        back.click()
        returned_to(reference,origin_y)

    set_route(page,base,"bof4","wiki?subject=Walkthrough")
    later = main.get_by_role("button",name="Show later articles")
    house_entry = main.locator("a[href='#bof4/marloks-house']")
    expect(house_entry).to_have_count(0)
    later.click()
    expect(house_entry).to_be_visible()
    main.get_by_role("button",name="Hide later names").click()
    expect(house_entry).to_have_count(0)
    set_route(page,base,"bof4","marloks-house")
    expect(back).to_have_accessible_name("Back to The children of Synesta")
    assert back.get_attribute("data-reading-back") is None
    back.click()
    expect(main.get_by_role("heading",level=1)).to_have_text("The children of Synesta")
    town = next(s for s in volumes["bof4"]["route"] if s["id"] == "synesta")
    part = next(a for a in town["sectionsByArea"] if a["id"] == "synesta")
    first = next(title for title, target in town["stepTopics"].items() if target == "marloks-house")
    step = town["landmarks"].index(first) - part["firstStep"] + 1
    set_route(page, base, "bof4", f"synesta?step={step}")
    chooser = main.get_by_role("combobox",name="Choose a step")
    buttons = main.locator(".directions .step-button:visible")
    expect(buttons).to_have_count(1)
    expect(buttons).to_contain_text(first)
    assert 0 <= buttons.bounding_box()["y"] < 500
    expect(chooser).to_have_value(str(step))
    main.get_by_role("button",name="Next step",exact=True).click()
    expect(chooser).to_have_value(str(step+1))
    main.get_by_role("button",name="Previous step",exact=True).click()
    expect(chooser).to_have_value(str(step))
    chooser.select_option("1")
    expect(main.get_by_role("button",name="Previous step",exact=True)).to_be_disabled()
    last_step = str(part["endStep"] - part["firstStep"])
    chooser.select_option(last_step)
    expect(main.get_by_role("button",name="Next step",exact=True)).to_be_disabled()
    main.get_by_role("button",name="Read all steps").click()
    expect(buttons).to_have_count(int(last_step))
    main.get_by_role("button",name="Show selected step").click()
    chooser.select_option(str(step))
    topic = main.locator(f"[data-step-topic='{step}'] a")
    expect(topic).to_have_text("Marlok’s house")
    route_y = saved_y(topic)
    topic.press("Enter")
    expect(back).to_have_accessible_name("Back to The children of Synesta")
    expect(main.get_by_role("table", name="Kahn at the door")).to_be_visible()
    follow_article_floor("bof4","synesta","synesta",4098,0)
    main.locator("[data-panel=sources] summary").click()
    hideout = main.locator(".related-reading a[href='#bof4/bandit-hideout']")
    house_y = saved_y(hideout)
    hideout.press("Enter")
    expect(back).to_have_accessible_name("Back to Marlok’s house")
    expect(main.get_by_role("table",name="Enemies in the hideout")).to_be_visible()
    follow_article_floor("bof4","synesta","synesta",1138,1)

    # Opening the house again is a fresh visit; Back restores each actual history entry.
    new_house = main.locator(".related-reading a[href='#bof4/marloks-house']")
    hideout_y = saved_y(new_house)
    new_house.press("Enter")
    expect(main.locator("[data-panel=sources]")).not_to_have_attribute("open","")
    back.click()
    returned_to(new_house,hideout_y)
    back.click()
    expect(main.locator("[data-panel=sources]")).to_have_attribute("open","")
    returned_to(hideout,house_y)
    back.click()
    returned_to(topic,route_y)
    expect(main.locator(f".step-button[data-number='{step}']")).to_have_attribute("aria-pressed","true")
    page.go_forward()
    expect(main.get_by_role("heading",level=1)).to_have_text("Marlok’s house")

    # Opening a file from a fresh bookmark has no native parent history.
    set_route(page,base,"bof4","item.ammonia?at=kyria-passage")
    expect(main.locator("article h2").first).to_contain_text("north spur")
    expect(back).to_have_accessible_name("Back to The passage to Synesta")
    assert back.get_attribute("data-reading-back") is None
    back.click()
    expect(tabs.get_by_role("tab",name="Items")).to_have_attribute("aria-selected","true")
    row = main.locator("tr[data-record='Ammonia']")
    expect(row).to_be_focused()
    item = row.get_by_role("link",name="Ammonia")
    row_y = saved_y(item)
    item.press("Enter")
    back.click()
    returned_to(item,row_y)
    active = tabs.get_by_role("tab",name="Items")
    active.focus()
    active.press("ArrowLeft")
    floor_tab = tabs.get_by_role("tab",name="Floors")
    expect(floor_tab).to_be_focused()
    expect(floor_tab).to_have_attribute("aria-selected","true")
    floor = main.get_by_label("Floor",exact=True)
    names = floor.locator("option").all_text_contents()
    floor.select_option(label=names[-1])
    expect(floor).to_be_focused()
    other = main.locator(".related-reading a").first
    floor_y = saved_y(other)
    other.press("Enter")
    back.click()
    returned_to(other,floor_y)
    expect(floor_tab).to_have_attribute("aria-selected","true")
    expect(floor.locator("option:checked")).to_have_text(names[-1])
    floor_tab.focus()
    floor_tab.press("Home")
    expect(tabs.get_by_role("tab",name="Directions")).to_be_focused()
    page.reload()
    expect(tabs.get_by_role("tab",name="Directions")).to_have_attribute("aria-selected","true")
    expect(main.get_by_role("img")).to_be_visible()

    # Two rooms can contain the same item or enemy. Both the chosen sighting and its row matter.
    for game,place,section,entity,room in (
        ("bof4","synesta","Items","Ammonia","Synesta Cellar"),
        ("bof4","synesta","Enemies","Mouse","Synesta Cellar"),
        ("bof3","mcneil","Items","Vitamin","Manor approach"),
    ):
        set_route(page,base,game,place)
        tabs.get_by_role("tab",name=section).click()
        sighting = main.locator("tr[data-record]").filter(has_text=room).get_by_role("link",name=entity,exact=True)
        position = saved_y(sighting)
        sighting.press("Enter")
        expect(main.locator("article h2").first).to_contain_text(room)
        path = page.url
        back.click()
        returned_to(sighting,position)
        # Paste that same book address with no parent. Its local return selects the same row.
        set_route(page,base,game,"walk")
        page.goto(path)
        assert back.get_attribute("data-reading-back") is None
        back.click()
        focused = main.locator("tr:focus")
        expect(focused).to_have_attribute("data-record",entity)
        expect(focused).to_have_attribute("data-sighting",re.compile(re.escape(room)))

    # III's ordinary chapters also put the relevant reference at the selected turn.
    set_route(page,base,"bof3","mcneil-shops")
    follow_article_floor("bof3","cedar","mcneil",7,0)
    stop = next(s for s in volumes["bof3"]["route"] if s["id"] == "contest")
    title,target = next(iter(stop["stepTopics"].items()))
    chosen = stop["landmarks"].index(title) + 1
    set_route(page,base,"bof3",f"contest?step={chosen}")
    reference = main.locator(f"[data-step-topic='{chosen}'] a[href='#bof3/{target}']")
    ref_y = saved_y(reference)
    reference.press("Enter")
    back.click()
    returned_to(reference,ref_y)

    for width in (320,390):
        page.set_viewport_size({"width":width,"height":844})
        set_route(page,base,"bof4",f"synesta?step={step}")
        chosen_body = main.locator(".step-body:visible")
        expect(chosen_body).to_have_count(1)
        instruction_y = chosen_body.bounding_box()["y"]
        assert 0 <= instruction_y < 500, (width, instruction_y, page.evaluate("scrollY"))
        no_overflow(page)
        set_route(page,base,"bof3","cedar?step=1")
        instruction = main.locator(".step-body:visible").first.bounding_box()
        drawing = main.locator(".map-board").bounding_box()
        assert instruction["y"] < 490 and instruction["y"] < drawing["y"], (width,instruction,drawing)
        no_overflow(page)
        view_map = main.get_by_role("button",name="View map")
        view_map.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(view_map).to_be_focused()
    page.set_viewport_size({"width":1360,"height":900})


def check_storage(browser, base):
    store_key = "bof-atelier.public-guide.v1"
    seed = {"bof3":{"through":4,"pins":["diary","cedar"]},"bof4":{"through":5,"pins":["dam-kyria","dragons","kyria-passage"]}}
    with browser.new_context(offline=True) as context:
        page = context.new_page()
        page.goto(base)
        page.evaluate("([key,value])=>localStorage.setItem(key,JSON.stringify(value))",[store_key,seed])
        page.reload()
        for game,ids in (("bof3",("cedar","diary")),("bof4",("dam-kyria","dragons","kyria-passage"))):
            set_route(page,base,game,"bookmarks")
            for page_id in ids:
                expect(page.locator(f"main a[href$='/{page_id}']")).to_be_visible()
            set_route(page,base,game,"walk")
            expect(page.locator("main [data-action=reveal]")).to_have_attribute("aria-expanded","false")
        assert page.evaluate("key=>JSON.parse(localStorage.getItem(key)).bof4.through",store_key) == 5
        main = page.get_by_role("main")
        expect(main.locator("a[href='#bof4/kyria-passage']")).to_be_visible()
        expect(main.locator("a[href='#bof4/synesta']")).to_have_count(0)
        set_route(page,base,"bof4","wiki?subject=Walkthrough")
        main.locator("a[href='#bof4/kyria-passage']").click()
        expect(main.get_by_role("heading",level=1)).to_have_text("The passage to Synesta")
        main.get_by_role("button",name="Mark my place").click()
        assert page.evaluate("key=>JSON.parse(localStorage.getItem(key)).bof4.through",store_key) == 5
        main.get_by_role("tab",name="Items").click()
        main.get_by_role("table",name="Items").get_by_role("link",name="Ammonia",exact=True).click()
        expect(main.get_by_role("heading",level=1)).to_have_text("Ammonia")
        expect(main.locator("article a[href='#bof4/kyria-passage']")).to_be_visible()
        expect(main.get_by_role("button",name="Show later locations")).to_be_visible()
        expect(main.get_by_role("heading",name=re.compile("cellar",re.I))).to_have_count(0)
        main.get_by_role("button",name="Show later locations").click()
        expect(main.get_by_role("heading",name=re.compile("cellar",re.I))).to_be_visible()
    with browser.new_context(offline=True) as context:
        context.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw Error('off')}})")
        page = context.new_page()
        page.goto(base+"#bof3/cedar")
        page.get_by_role("button",name="Bookmark page").click()
        expect(page.locator("#announce")).to_have_text("Bookmarks last for this session.")
        set_route(page,base,"bof3","bookmarks")
        expect(page.locator("main a[href$='/cedar']")).to_be_visible()


def check_transport(browser, base: str, document: bytes, volumes: dict,
                    destination: Path | None, offline: bool):
    errors, external = [], []
    context = browser.new_context(
        offline=offline, reduced_motion="reduce", viewport={"width":1360,"height":900}
    )
    context.set_default_timeout(5000)

    def guard(route):
        url = route.request.url
        if urlsplit(url).scheme in {"http","https","file"} and (
                url.split("#")[0] != base and url != base+"index.html"):
            external.append(url)
            route.abort()
        else:
            route.continue_()

    context.route("**/*",guard)
    context.on("page",lambda p:p.on("pageerror",lambda err:errors.append(str(err))))
    page = context.new_page()
    try:
        response = page.goto(base)
        if not offline:
            assert response and response.status == 200 and response.body() == document
        expect(page.get_by_role("heading",level=1)).to_be_visible()
        no_overflow(page)
        art_count = check_art_and_content(page,volumes)
        fonts = page.evaluate("""async () => {
          await document.fonts.ready;
          return [...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family);
        }""")
        assert set(fonts) == {"Gloock","Barlow"}, fonts
        offline_link = page.get_by_role("link",name="Download for offline reading")
        if offline:
            expect(offline_link).to_have_count(0)
        else:
            with page.expect_download() as event:
                offline_link.click()
            download = event.value
            assert download.suggested_filename == "BoF-Atelier-Field-Guide.html"
            assert download.path().read_bytes() == document
            page.evaluate("window.scrollTo(0,0)")
        screenshot(page,destination,"desktop")
        check_reader_actions(page,base,volumes,destination)
        check_detail_navigation(page,base,volumes)
        counts = check_pages_and_links(page,volumes)
        check_responsive(page,base,destination)
        if offline:
            check_storage(browser,base)
        assert not errors, errors
        assert not external, external
        return {**counts,"decoded_illustrations":art_count,"fonts":fonts,
                "widths_css_px":[320,390,640,768,850,1280,1360,1920],"text_200_percent":True,
                "contextual_step_and_row_returns":True,"floor_return":True,"article_floor_links":3,"nested_article_history":True,
                "gameplay_inputs":False,"page_errors":errors,"external_requests":external}
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
                                         headless=True, chromium_sandbox=True,
                                         args=["--disable-ipc-flooding-protection"])
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
