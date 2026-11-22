"""Inventory private disc audio evidence and map an owner's PCM tracks for offline preview."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import wave

from .inspect_disc import RAW_SECTOR_BYTES, inspect_disc
from .local_store import StoreError, atomic_bytes, canonical_bytes, member_path, plain_path


EVENTS = ("field", "battle", "victory", "boss", "menu", "cutscene")
CLASSES = ("user-supplied", "faithful-arrangement", "alternative-interpretation")
MAX_WAV_BYTES = 256 * 1024**2


def disc_audio(private: Path, game: str) -> dict:
    if game not in {"bof3", "bof4"}:
        raise StoreError("Choose an imported title.")
    directory = plain_path(private / "games" / game)
    receipt = json.loads(plain_path(directory / "import-receipt.json").read_bytes())
    track = receipt["tracks"][0]
    cue_dir = Path(member_path(receipt["working_cue"])).parent
    image = plain_path(directory / cue_dir / member_path(track["file"]))
    relative = image.relative_to(directory).as_posix()
    expected = next(entry for entry in receipt["entries"] if entry["path"] == relative)
    with image.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != expected["sha256"]:
            raise StoreError("The source track no longer matches its import receipt.")
        filesystem = inspect_disc(image)
        streams = []
        for entry in filesystem["file_table"]:
            if entry["directory"] or not entry["path"].split(";")[0].upper().endswith(".STR"):
                continue
            # Use a fixed first-extent probe. ISO file length alone does not establish
            # the complete interleaved recording length of a Form 2 stream.
            count = min(128, (entry["bytes"] + 2047) // 2048,
                        filesystem["raw_sector_count"] - entry["lba"])
            source.seek(entry["lba"] * RAW_SECTOR_BYTES)
            samples = source.read(count * RAW_SECTOR_BYTES)
            channels: Counter = Counter()
            for offset in range(0, len(samples), RAW_SECTOR_BYTES):
                header = samples[offset:offset + 24]
                if (len(header) == 24 and header[:12] == b"\0" + b"\xff" * 10 + b"\0"
                        and header[15] == 2 and header[16:20] == header[20:24] and header[18] & 0x04):
                    channels[(header[16], header[17], header[19])] += 1
            streams.append({"path": entry["path"], "start_lba": entry["lba"], "sectors_probed": count,
                            "audio_subheaders": [{"file": k[0], "channel": k[1], "coding": k[2], "sectors": v}
                                                 for k, v in sorted(channels.items())]})
    result = {"schema_version": 1, "game": game, "fingerprint": receipt["content_fingerprint"],
              "cdda_tracks": [t["number"] for t in receipt["tracks"] if t["mode"].upper() == "AUDIO"],
              "stream_containers": streams, "in_game_event_mapping": "unqualified",
              "default_playback": "original", "rights": "private source inspection"}
    atomic_bytes(private / "lab" / "workshop-audio" / game / "disc-catalogue.json", canonical_bytes(result))
    return result


def describe_wav(path: Path) -> dict:
    path = plain_path(path)
    if not path.is_file() or not 44 <= path.stat().st_size <= MAX_WAV_BYTES:
        raise StoreError("Choose a PCM WAV file up to 256 MiB.")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        source.seek(0)
        try:
            with wave.open(source, "rb") as wav:
                channels, rate, frames = wav.getnchannels(), wav.getframerate(), wav.getnframes()
                width = wav.getsampwidth()
                if (wav.getcomptype() != "NONE" or channels not in {1, 2} or width not in {1, 2, 3, 4}
                        or not 8000 <= rate <= 192000 or not 0 < frames <= rate * 60 * 60
                        or frames * channels * width > MAX_WAV_BYTES):
                    raise StoreError("Unsupported PCM channel count, sample rate, width or duration.")
                received = 0
                while block := wav.readframes(32768):
                    received += len(block)
                if received != frames * channels * width:
                    raise StoreError("The PCM sample data is incomplete.")
        except (wave.Error, EOFError) as error:
            raise StoreError("The file is not a readable PCM WAV.") from error
    return {"sha256": digest, "channels": channels, "rate_hz": rate, "frames": frames,
            "sample_bytes": width}


class AudioLibrary:
    def __init__(self, private: Path):
        self.root = plain_path(private / "lab" / "workshop-audio")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = plain_path(self.root / "mappings.sqlite3")
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS tracks (game TEXT, event TEXT, track TEXT, PRIMARY KEY(game,event))")

    def assign(self, game: str, event: str, path: Path, *, category: str, creator: str, rights: str,
               loop_start: int = 0, loop_end: int | None = None) -> dict:
        if game not in {"bof3", "bof4"} or event not in EVENTS or category not in CLASSES:
            raise StoreError("Choose a supported title, event and arrangement category.")
        if any(not value.strip() or len(value) > 512 for value in (creator, rights)):
            raise StoreError("Enter the creator and permission evidence for private preview.")
        track = describe_wav(path)
        loop_end = track["frames"] if loop_end is None else loop_end
        if not (type(loop_start) is int and type(loop_end) is int and 0 <= loop_start < loop_end <= track["frames"]):
            raise StoreError("Loop boundaries must be valid PCM frame positions.")
        track.update(path=str(plain_path(path)), category=category, creator=creator, rights=rights,
                     loop_start=loop_start, loop_end=loop_end)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT OR REPLACE INTO tracks VALUES (?,?,?)", (game, event, canonical_bytes(track).decode()))
        return track

    def preview(self, game: str, event: str) -> dict:
        with closing(sqlite3.connect(self.db)) as db:
            row = db.execute("SELECT track FROM tracks WHERE game=? AND event=?", (game, event)).fetchone()
        if row:
            track = json.loads(row[0])
            try:
                if describe_wav(Path(track["path"]))["sha256"] == track["sha256"]:
                    return {"source": "local-preview", "track": track, "gameplay_playback": "original"}
            except (OSError, StoreError):
                pass
        return {"source": "original", "gameplay_playback": "original"}

    def review(self, game: str) -> Path:
        if game not in {"bof3", "bof4"}:
            raise StoreError("Choose one of the two titles.")
        cards = []
        for event in EVENTS:
            resolved = self.preview(game, event)
            if resolved["source"] == "original":
                cards.append(f"<section><h2>{event.title()}</h2><p>Original soundtrack</p></section>")
                continue
            t = resolved["track"]
            url = html.escape(Path(t["path"]).as_uri(), quote=True)
            start, end = (t[key] / t["rate_hz"] for key in ("loop_start", "loop_end"))
            cards.append(f'<section><h2>{event.title()}</h2><p>{html.escape(t["creator"])}'
                         f' · {html.escape(t["category"])}</p><audio controls preload="none" src="{url}"'
                         f' data-start="{start}" data-end="{end}"></audio>'
                         '<label><input type="checkbox"> Loop selection</label></section>')
        title = "Breath of Fire III" if game == "bof3" else "Breath of Fire IV"
        script = """for(const player of document.querySelectorAll('audio')){
          const loop=player.parentElement.querySelector('input');
          function repeat(){if(loop.checked){player.currentTime=Number(player.dataset.start)}}
          player.addEventListener('timeupdate',()=>{if(player.currentTime>=Number(player.dataset.end)){repeat()}});
          player.addEventListener('ended',()=>{if(loop.checked){repeat();player.play().catch(()=>{})}});
        }"""
        page = (f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title} audio review</title>'
                '<meta name="viewport" content="width=device-width,initial-scale=1"><style>'
                'body{max-width:50rem;margin:auto;padding:2rem;font:1.125rem/1.55 system-ui;'
                'background:#16282a;color:#f5eee2}section{padding:1rem 0;border-top:1px solid #557477}'
                'h1,h2{font-family:Georgia,serif}label{display:block}audio{max-width:100%}</style>'
                f'<main><h1>{title} audio review</h1><p>Preview local recordings. The game uses its original soundtrack.</p>'
                + "".join(cards) + f"</main><script>{script}</script></html>")
        output = self.root / game / "review.html"
        atomic_bytes(output, page.encode("utf-8"))
        return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, default=Path("private"))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("catalogue", "assign", "preview", "review"):
        p = sub.add_parser(name)
        p.add_argument("game", choices=["bof3", "bof4"])
        if name in {"assign", "preview"}:
            p.add_argument("event", choices=EVENTS)
        if name == "assign":
            p.add_argument("path", type=Path)
            p.add_argument("--category", choices=CLASSES, default="user-supplied")
            p.add_argument("--creator", required=True)
            p.add_argument("--rights", required=True)
            p.add_argument("--loop-start", type=int, default=0)
            p.add_argument("--loop-end", type=int)
    args = parser.parse_args()
    try:
        if args.command == "catalogue":
            result = disc_audio(args.private, args.game)
        elif args.command == "assign":
            result = AudioLibrary(args.private).assign(args.game, args.event, args.path, category=args.category,
                         creator=args.creator, rights=args.rights, loop_start=args.loop_start, loop_end=args.loop_end)
        elif args.command == "review":
            result = {"review_file": str(AudioLibrary(args.private).review(args.game))}
        else:
            result = AudioLibrary(args.private).preview(args.game, args.event)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
