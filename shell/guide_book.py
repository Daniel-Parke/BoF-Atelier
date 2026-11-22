"""Read the two bundled editorial volumes. All identifiers are local to one game."""
from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlsplit


CORE_PAGES = {
    "bof3": {"walk", "genes", "diary", "flame", "frost", "thunder"},
    "bof4": {"walk", "masters", "dragons", "rwolf"},
}
EARLY_PLACES = {"bof3": ("mine", "cedar"), "bof4": ("crash", "north-desert")}
GENE_PLATES = ("flame", "frost", "thunder", "gene-shadow", "gene-radiance", "gene-force", "gene-defender",
               "gene-eldritch", "gene-miracle", "gene-gross", "gene-thorn", "gene-reverse", "gene-mutant",
               "gene-unknown", "gene-trance", "gene-failure", "gene-fusion", "gene-infinity")
ART = {
    "bof3": {"highlands", *GENE_PLATES, "iii-mine", "iii-woods", "iii-port", "iii-desert"},
    "bof4": {"sandsea", "iv-wreck", "iv-tomb", "iv-river", "iv-palace", "iv-fishing", "iv-training", "iv-dragon"},
}
WIKI_FILES = ("bof3.json", "bof4.json", "illustrations.css", "illustrations.json")
ATLAS_ART = {"bof3": set(), "bof4": {"kurok-wind"}}


def teacher_pages(book: dict) -> list[dict]:
    art = {stop["id"]: stop["art"] for stop in book["route"]}
    pages = []
    seen = set()
    for teacher in book.get("teachers", []):
        name = teacher["name"]
        lessons = teacher["lessons"]
        if (name in seen or not teacher["id"].startswith("teacher-") or not lessons
                or not all(isinstance(t.get(key), str) and t[key].strip()
                           for t in lessons for key in ("goal", "skill"))
                or len({t["goal"] for t in lessons}) != len(lessons)):
            raise ValueError(f"Invalid master lessons: {name}")
        seen.add(name)
        growth = teacher["growth"]
        mental_stat = "intelligence" if book["game"] == "bof3" else "wisdom"
        if (set(growth) != {"HP", "AP", "power", "defence", "agility", mental_stat}
                or any(type(value) is not int for value in growth.values())):
            raise ValueError(f"Invalid growth modifiers: {name}")
        sections = [{"title": "Where to find " + name, "text": teacher["where"]}]
        if "will" in teacher:
            sections.append({"title": "Will · " + teacher["will"]["name"], "text": teacher["will"]["effect"]})
        pages.append({
            "id": teacher["id"], "title": name, "category": "Masters & companions",
            "lead": teacher["join"], "art": art[teacher["unlock"]], "unlock": teacher["unlock"],
            "links": teacher["links"], "sources": teacher["sources"],
            "sections": sections,
            "referenceTables": [{"title": "Lessons and rewards",
                                 "columns": [teacher["measure"], "Reward"],
                                 "rows": [[l["goal"], l["skill"]] for l in lessons]},
                                {"title": "Growth per level",
                                 "columns": ["Stat", "Change from no master"],
                                 "rows": [[key if key in {"HP", "AP"} else key.capitalize(),
                                           f"{value:+d}" if value else "0"] for key, value in growth.items()]}],
        })
    return pages


def validate_field_sheets(book: dict, ids: set[str]) -> None:
    stops = {stop["id"]: stop for stop in book["route"]}
    for key, sheet in book.get("fieldSheets", {}).items():
        stop = stops.get(sheet["stop"])
        if (not stop or key != sheet["id"] or not re.fullmatch(r"[a-z][a-z0-9-]*", key)
                or sheet["map"] != key + ".svg" or not sheet["mapAlt"].strip()
                or sheet["art"] not in ART[book["game"]] | ATLAS_ART[book["game"]]
                or set(sheet["links"]) - ids or not sheet["objective"].strip()
                or not sheet["steps"] or not sheet["entry"].strip()
                or any(step["key"] != n or not step["title"].strip() or not step["body"].strip()
                       for n, step in enumerate(sheet["steps"], 1))):
            raise ValueError(f"Incomplete illustrated route: {key}")
        for subset, ledger in (("optional", "items"), ("enemies", "encounters")):
            known = {row["name"] for row in stop.get(ledger, [])}
            if any(row["name"] not in known for row in sheet[subset]):
                raise ValueError(f"Unmatched {ledger} entry in {key}")


def public_gene_recipe(selection: tuple[int, ...] | list[int]) -> dict:
    """The three documented specimens that can be combined without private disc data."""
    if not 1 <= len(selection) <= 3 or any(type(i) is not int or i not in (0, 1, 2) for i in selection):
        return {}
    genes = set(selection)
    if len(genes) != len(selection):
        return {}
    if len(genes) == 3:
        return {"cost": 15, "kind": "special", "form": "Trygon",
                "detail": "Carries fire, ice and lightning breath attacks."}
    detail = ("Fire and ice cancel out. This dragon has neutral affinity." if genes == {0, 1} else
              " · ".join(("Fire", "Ice", "Lightning")[i] for i in sorted(genes)))
    return {"cost": 5 * len(genes), "kind": "general", "form": "Whelp" if len(genes) == 1 else "Dragon",
            "detail": detail}


def read_book(directory: Path, game: str) -> dict:
    if game not in CORE_PAGES:
        raise ValueError("Unknown guide volume")
    book = json.loads((directory / f"{game}.json").read_text(encoding="utf-8-sig"))
    if book["game"] != game or book["version"] != 1:
        raise ValueError(f"Wrong Field Guide volume or version: {game}")
    route, articles, sources = book["route"], book["articles"], book["sources"]
    if tuple(row["id"] for row in route[:2]) != EARLY_PLACES[game]:
        raise ValueError(f"The legacy reading places must remain available: {game}")
    articles.extend(teacher_pages(book))
    pages = route + articles
    ids = {row["id"] for row in pages}
    reserved = CORE_PAGES[game] | {"guide", "wiki", "route"}
    if len(ids) != len(pages) or ids & reserved or any(not re.fullmatch(r"[a-z][a-z0-9-]*", i) for i in ids):
        raise ValueError(f"Duplicate, invalid or reserved page ID: {game}")
    places = {row["id"] for row in route}
    validate_field_sheets(book, ids | reserved)
    entities = {}
    book["entities"] = entities
    for key, source in sources.items():
        if source.get("kind") == "print" and source.get("title", "").strip() and "url" not in source:
            continue
        url = urlsplit(source.get("url", ""))
        if not source["title"].strip() or url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError(f"Invalid guide source: {key}")
    for row in pages:
        if (not row["title"].strip() or not row["lead"].strip() or row["art"] not in ART[game]
                or not row["sources"] or set(row["sources"]) - sources.keys()
                or set(row["links"]) - (ids | reserved)):
            raise ValueError(f"Incomplete guide page: {game}/{row['id']}")
        for citation in row.get("sourceSections", []):
            if (citation.get("source") not in row["sources"] or not isinstance(citation.get("section"), str)
                    or not citation["section"].strip()):
                raise ValueError(f"Invalid source chapter: {game}/{row['id']}")
    for row in route:
        if not all(row[key].strip() for key in ("region", "hint", "tip")) or not row["steps"] or not all(row["steps"]):
            raise ValueError(f"Incomplete walkthrough: {row['id']}")
    for row in articles:
        if (row["unlock"] not in places or not row["category"].strip() or not row["sections"]
                or not all(s["title"].strip() and s["text"].strip() for s in row["sections"])):
            raise ValueError(f"Incomplete wiki article: {row['id']}")
        for table in row.get("referenceTables", []):
            columns = table["columns"]
            if (not table["title"] or len(columns) < 2 or not all(columns) or not table["rows"]
                    or any(len(line) != len(columns) or not all(isinstance(c, str) and c.strip() for c in line)
                           for line in table["rows"])):
                raise ValueError(f"Invalid reference table: {row['id']}")
    for stop in route:
        floors = stop.get("floors", [])
        floor_keys = set()
        for floor in floors:
            key = (floor.get("mapId"), floor.get("section"))
            if (not isinstance(floor.get("name"), str) or not floor["name"].strip()
                    or any(type(i) is not int for i in key) or not 0 <= key[0] <= 0x1fff
                    or not 0 <= key[1] <= 255 or key in floor_keys):
                raise ValueError(f"Invalid floor reference: {stop['id']}")
            floor_keys.add(key)
            if any(not p.get("name") or any(type(p.get(k)) is not int or not 0 <= p[k] < 256
                       for k in ("x", "z")) for p in floor.get("landmarks", [])):
                raise ValueError(f"Invalid floor landmark: {stop['id']}")
        sections = stop.get("sectionsByArea", [])
        next_step = 0
        for area in sections:
            if (not all(isinstance(area.get(k), str) and area[k].strip() for k in ("name", "lead", "hint", "tip"))
                    or area.get("firstStep") != next_step or type(area.get("endStep")) is not int
                    or not next_step < area["endStep"] <= len(stop["steps"])
                    or not any(f["mapId"] == area.get("firstFloor") and
                               f["name"].startswith(area["name"]) for f in floors)):
                raise ValueError(f"Invalid area directions: {stop['id']}")
            next_step = area["endStep"]
        if sections and next_step != len(stop["steps"]):
            raise ValueError(f"Unassigned area directions: {stop['id']}")
        names = stop.get("landmarks", [])
        if len(names) != len(stop["steps"]) or not all(isinstance(s, str) and s.strip() for s in names):
            raise ValueError(f"Walkthrough landmarks must match the directions: {stop['id']}")
        chart = stop.get("map")
        if chart:
            points = chart["points"]
            if (not chart["title"] or len(points) < 2 or not chart["paths"]
                    or any(not p["name"] or not p["note"] or not (0 < p["x"] < 100 and 0 < p["y"] < 100) for p in points)
                    or any(len(edge) != 2 or edge[0] == edge[1] or any(type(i) is not int or not 0 <= i < len(points)
                           for i in edge) for edge in chart["paths"])):
                raise ValueError(f"Invalid landmark map: {stop['id']}")
        for field, category in (("items", "Item ledger"), ("encounters", "Bestiary")):
            records = stop.get(field, [])
            if not records:
                continue
            if any(not all(r[k].strip() for k in ("name", "where", "detail")) for r in records):
                raise ValueError(f"Incomplete {field} record: {stop['id']}")
            for record in records:
                entity_id = ("item." if field == "items" else "enemy.") + record["name"].strip().lower()
                entity = entities.setdefault(entity_id, {"id": entity_id, "name": record["name"],
                                             "category": category, "unlock": stop["id"], "observations": []})
                entity["observations"].append({"stop": stop["id"], **record})
            page_id = f"{stop['id']}-{field}"
            if page_id in ids | reserved:
                raise ValueError(f"Duplicate atlas article: {page_id}")
            ids.add(page_id)
            articles.append({"id": page_id, "title": stop["title"], "category": category,
                             "lead": ("Items found along this route" if field == "items" else "Encounters along this route")
                                     + " · " + ", ".join(r["name"] for r in records), "unlock": stop["id"],
                             "art": stop["art"], "sources": stop["sources"], "links": [stop["id"]],
                             "sections": [], "table": field, "records": records})
    return book
