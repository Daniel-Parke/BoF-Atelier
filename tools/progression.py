"""Read original III gene rules or IV progression records from a registered disc."""
from __future__ import annotations

import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
import struct
import sys

if __package__:
    from .import_games import file_id
    from .inspect_disc import DiscError, RawDiscReader
    from .workshop_assets import WorkshopError, emi_sections, open_imported_disc
else:
    from import_games import file_id
    from inspect_disc import DiscError, RawDiscReader
    from workshop_assets import WorkshopError, emi_sections, open_imported_disc


GENES = ('Flame', 'Frost', 'Thunder', 'Shadow', 'Radiance', 'Force', 'Defender', 'Eldritch',
         'Miracle', 'Gross', 'Thorn', 'Reverse', 'Mutant', '???', 'Trance', 'Failure', 'Fusion', 'Infinity')
MASTERS = ('None', 'Rwolf', 'Momo', 'Kryrik', 'Abbess', 'Njomo', 'Gyosil', 'Stoll', 'Una',
           'Bunyan', 'Lyta', 'Kahn', 'Marlok')
FORMS = ('Aura', 'Kaiser', 'Astral', 'Tyrant', 'Wyvern', 'Weyr', 'Myrmidon', 'Knight', 'Serpent',
         'Peist', 'Behemoth', 'Mammoth', 'Mutant', 'Punk')
STATS = ('HP', 'AP', 'power', 'defence', 'agility', 'wisdom')
III_PATH = 'BIN/BATTLE/BATTLE.EMI;1'
IV_PATH = 'BIN/SYSTEM/GAME.EMI;1'


def fnv32a(data: bytes) -> int:
    state = 0x811C9DC5
    for value in data:
        state = ((state ^ value) * 0x1000193) & 0xffffffff
    return state


def game_tables(game_dir: Path) -> dict:
    return read_game_tables(open_imported_disc(game_dir, lambda: None))


def read_game_tables(verified_disc: tuple) -> dict:
    receipt, track, identity, disc, game = verified_disc
    if game not in ('bof3', 'bof4'):
        raise WorkshopError('This edition has no qualified progression mapping.')
    path, slot = (III_PATH, 15) if game == 'bof3' else (IV_PATH, 0)
    location = next((entry for entry in disc['file_table'] if entry['path'] == path), None)
    if not location:
        raise WorkshopError('The expected rules container is missing.')
    container = RawDiscReader(track).read_logical(location['lba'], location['bytes'])
    sections = emi_sections(container)
    if slot >= len(sections):
        raise WorkshopError('The rules overlay is missing.')
    overlay = sections[slot]
    evidence = {}

    def read(name: str, address: int, size: int, *, check_digest=None, upstream_fnv=None) -> bytes:
        relative = address - overlay['argument']
        if relative < 0 or relative + size > overlay['bytes']:
            raise WorkshopError('A rules table exceeds the identified overlay.')
        start = overlay['offset'] + relative
        content = container[start:start + size]
        digest = hashlib.sha256(content).hexdigest()
        if ((check_digest and digest != check_digest) or
                (upstream_fnv is not None and fnv32a(content) != upstream_fnv)):
            raise WorkshopError(f'The {name} table differs from the qualified revision.')
        evidence[name] = dict(emi_offset=start, address=hex(address), bytes=size, sha256=digest,
                              upstream_fnv1a32=f'{upstream_fnv:08x}' if upstream_fnv is not None else None)
        return content

    if game == 'bof3':
        tables = {
            'costs': read('gene_costs', 0x800b4c7c, 18, check_digest='f6a8b7ac39a10ff0b320d84d4b2c38556b14e23ac979fdc38eae61a0cf892d62'),
            'groups': read('recipe_groups', 0x800b4d4c, 11, check_digest='3d405d11f2b641a979cb3594e897bf9779b578249808d4c4135e4528e512bf21'),
            'recipes': read('recipe_genes', 0x800b4d58, 33, check_digest='14c6247d7d3e537fd2b7237c3fde41ed906fb8c9fd4e6eccbdb54eb5827b148c'),
            'mix_rows': read('gene_mix', 0x800b4d7c, 18 * 14, check_digest='a5a6767df36d5ebbf45f75c4a4a96ba1492ec7a2023cd455487acb9fff848465'),
        }
    else:
        tables = {
            'masters': read('master_modifiers', 0x8019de28, 78, upstream_fnv=0xf47ff88c),
            'growth': read('growth', 0x8019bbf8, 5600, upstream_fnv=0x6b00e5eb),
            'skills': read('skill_records', 0x8019add0, 3072, upstream_fnv=0x6241bb9d),
        }
    if identity != file_id(track):
        raise WorkshopError('The source track changed during the read.')
    return {'game': game, 'serial': receipt['serial'], 'overlay': path, 'slot': slot, 'lba': location['lba'],
            'overlay_sha256': overlay['sha256'], 'evidence': evidence, **tables}


def gene_selection(tables: dict, selection, *, available_ap: int | None = None, party_size: int | None = None) -> dict:
    if tables['game'] != 'bof3':
        raise WorkshopError('The gene selection belongs to Breath of Fire III.')
    ids = tuple(selection)
    if (not 1 <= len(ids) <= 3 or any(type(i) is not int or not 0 <= i < len(GENES) for i in ids) or
            len(set(ids)) != len(ids)):
        raise WorkshopError('Choose one, two or three different III genes by grid ID, from 0 through 17.')
    if available_ap is not None and (type(available_ap) is not int or not 0 <= available_ap <= 65535):
        raise WorkshopError('Enter an available AP value from 0 through 65,535.')
    if party_size is not None and (type(party_size) is not int or not 1 <= party_size <= 3):
        raise WorkshopError('Choose a party size from one through three.')
    cost = sum(tables['costs'][i] for i in ids) & 0xff
    recipe = group = None
    outcome = 'General transformation rules apply outside the special recipe table.'
    for row in range(11):
        if row == 6:
            if 16 in ids and party_size in (None, 3):
                outcome = 'Fusion can require party composition. The final form is unresolved.'
                break
            continue
        required = set(tables['recipes'][row * 3:row * 3 + 3]) - {255}
        if required.issubset(ids):
            recipe, group = row, tables['groups'][row]
            outcome = 'Matched the first eligible special recipe in the original table.'
            break
    return {'gene_ids': list(ids), 'initial_ap': cost, 'available_ap': available_ap,
            'affordable': cost <= available_ap if available_ap is not None else None,
            'special_recipe': recipe, 'group_id': group, 'interpretation': outcome}


SPECIAL_FORMS = (
    ("Kaiser", "You can command Ryu in this form."),
    ("Trygon", "Carries fire, ice and lightning breath attacks."),
    ("Wildfire", "Very low HP. Charge uses defence instead."),
    ("Kaiser", "Controllable, with lower transformed stats than the Trance and Radiance recipe."),
    ("Berserk Kaiser", "Ryu chooses his own targets and can strike allies."),
    ("Whelp", "Failure takes precedence over the ordinary mix."),
    None,  # The party check occupies this slot.
    ("Tiamat", "Uses Doom Breath and Venom Breath."),
    ("Myrmidon", "A warrior form with elemental strikes."),
    ("Mammoth", "A high-HP form with MeteorStrike."),
    ("Pygmy", "A small form with Magma Breath."),
)
HYBRIDS = (
    ({"Garr", "Peco"}, "Nina", 7, "Avian", "Eldritch Avian"),
    ({"Momo", "Nina"}, "Rei", 5, "Tiger", "Flame Tiger"),
    ({"Nina", "Peco"}, "Momo", 13, "Knight", "Golden Knight"),
    ({"Garr", "Rei"}, "Peco", 3, "Onion", "Shadow Onion"),
)


def recipe_preview(tables: dict, selection, allies=None) -> dict:
    """Name the original form, keeping party choices and random results explicit."""
    ids = tuple(selection)
    if allies is not None and (len(allies) > 2 or len(set(allies)) != len(allies)
                               or set(allies) - {"Garr", "Peco", "Nina", "Momo", "Rei"}):
        raise ValueError("Choose up to two different active companions.")
    rule = gene_selection(tables, ids, party_size=None if allies is None else len(allies) + 1)
    preview = {"cost": rule["initial_ap"], "kind": "general"}
    if "party composition" in rule["interpretation"]:
        if allies is None:
            return preview | {"form": "Fusion", "kind": "party", "detail": "Choose the two allies standing with Ryu."}
        for partners, lead, modifier, normal, enhanced in HYBRIDS:
            if lead in allies and partners.intersection(allies):
                variant = enhanced if modifier in ids else normal
                return preview | {"form": "Hybrid", "kind": "party", "detail": variant + " form with " + " and ".join(allies) + "."}
        # A pairing which produces no hybrid continues through the remaining rules.
        rule = gene_selection(tables, ids, party_size=1)
    if rule["special_recipe"] is not None:
        form, detail = SPECIAL_FORMS[rule["special_recipe"]]
        return preview | {"kind": "special", "form": form, "detail": detail}
    rows = tables["mix_rows"]
    traits = [sum(int.from_bytes(rows[g*14+i:g*14+i+1], signed=True) for g in ids if g not in (10, 11, 12))
              for i in range(14)]
    if 11 in ids:
        traits[:10] = [-v for v in traits[:10]]
    if 10 in ids:
        traits = [v*2 for v in traits]
    def mixed_form(size, force, miracle):
        if miracle >= 1:
            return "Behemoth"
        if force >= 1:
            return "Warrior"
        return "Dragon" if size >= 2 else "Whelp"

    if 12 in ids:
        outcomes = {mixed_form(traits[10]+a,traits[11]+b,traits[13]+c)
                    for a,b,c in product((-1,0,1), repeat=3)}
        forms = [f for f in ("Whelp","Dragon","Warrior","Behemoth") if f in outcomes]
        return preview | {"kind": "random", "form": forms[0] if len(forms) == 1 else "Variable form",
                          "detail": "Mutant can change the traits on each cast. Possible forms: " + ", ".join(forms) + "."}
    form = mixed_form(traits[10],traits[11],traits[13])
    affinities = [name for name, score in zip(("Fire", "Ice", "Lightning", "Shadow", "Holy"), traits) if score > 0]
    detail = " · ".join(affinities) if affinities else "Neutral affinity"
    if len(ids) == 2 and set(ids) == {0, 1}:
        detail = "Fire and ice cancel out. This dragon has neutral affinity."
    return preview | {"form": form, "detail": detail}


def master_comparison(tables: dict, first: int, second: int) -> dict:
    if tables['game'] != 'bof4' or any(type(i) is not int or not 0 <= i < len(MASTERS) for i in (first, second)):
        raise WorkshopError('Choose two IV master IDs from 0 through 12.')
    def vector(i):
        return struct.unpack_from('6b', tables['masters'], i * len(STATS))
    a, b = vector(first), vector(second)
    return {'master_ids': [first, second], 'first_modifier': dict(zip(STATS, a)),
            'second_modifier': dict(zip(STATS, b)), 'second_minus_first': dict(zip(STATS, (y-x for x,y in zip(a,b)))),
            'interpretation': 'Original signed modifiers for one level. Final stats depend on character, level and game rules.'}


def original_growth(tables: dict, character: int, row: int) -> dict:
    if (tables['game'] != 'bof4' or type(character) is not int or not 0 <= character < 7 or
            type(row) is not int or not 0 <= row < 100):
        raise WorkshopError('Choose an IV character index from 0 through 6 and a growth-table row from 0 through 99.')
    start = (character * 100 + row) * 8
    record = tables['growth'][start:start + 8]
    return {'character_index': character, 'table_row': row, 'hp_entry': record[2], 'ap_entry': record[3] >> 4,
            'interpretation': 'Two base growth fields in the disc table. A level-up prediction requires the runtime selection and caps.'}


def dragon_records(tables: dict, *, reveal_names: bool = False) -> list[dict]:
    if tables['game'] != 'bof4':
        raise WorkshopError('The IV form records belong to Breath of Fire IV.')
    result = []
    for slot, label in enumerate(FORMS, 211):
        raw = tables['skills'][slot * 12:(slot + 1) * 12]
        item = dict(skill_id=slot, record_sha256=hashlib.sha256(raw).hexdigest(),
                    stored_power=raw[3], stored_ap=raw[4])
        if reveal_names:
            item['name'] = label
        result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game_directory', type=Path)
    parser.add_argument('--names', action='store_true', help='Reveal names, including progression spoilers.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('tables')
    genes = commands.add_parser('genes')
    genes.add_argument('ids', nargs='+', type=int)
    genes.add_argument('--ap', type=int)
    genes.add_argument('--party-size', type=int)
    masters = commands.add_parser('masters')
    masters.add_argument('ids', nargs=2, type=int)
    growth = commands.add_parser('growth')
    growth.add_argument('character', type=int)
    growth.add_argument('row', type=int)
    commands.add_parser('forms')
    args = parser.parse_args()
    try:
        tables = game_tables(args.game_directory)
        if args.command == 'tables':
            result = {k: v for k, v in tables.items() if not isinstance(v, bytes)}
            if args.names:
                result['names'] = dict(enumerate(GENES if tables['game'] == 'bof3' else MASTERS))
        elif args.command == 'genes':
            result = gene_selection(tables, args.ids, available_ap=args.ap, party_size=args.party_size)
            if args.names:
                result['genes'] = [GENES[i] for i in args.ids]
        elif args.command == 'masters':
            result = master_comparison(tables, *args.ids)
            if args.names:
                result['masters'] = [MASTERS[i] for i in args.ids]
        elif args.command == 'growth':
            result = original_growth(tables, args.character, args.row)
        else:
            result = {'records': dragon_records(tables, reveal_names=args.names),
                      'interpretation': 'Disc skill records with externally mapped form names. Stored fields alone do not resolve evocation cost, form evolution or unlock conditions.'}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, DiscError, RuntimeError) as err:
        print(f'Progression Workshop: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
