"""Allow one managed Player game at a time in a private library."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys

from tools import runtime_linux, runtime_reference_play, runtime_setup as runtime


ALREADY_OPEN = "A game is already open. Close it before starting another."


def _process_identity(pid: int) -> tuple[str, int] | None:
    probe = runtime_linux.process_identity if sys.platform.startswith("linux") else runtime._process_identity
    return probe(pid)


def _session_running(receipt: Path) -> bool:
    if not receipt.exists():
        return False
    try:
        with receipt.open("rb") as stream:
            payload = json.loads(stream.read(4097))
        if len(payload) != 2:
            raise ValueError("Unexpected session fields.")
        pid, created = payload["pid"], payload["created"]
        if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF or type(created) is not int or created < 0:
            raise ValueError("Invalid session identity.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise runtime.RuntimeSetupError("The last Player session record could not be read.") from error
    observed = _process_identity(pid)
    return observed is not None and observed[1] == created


def _existing_windows_game(root: Path) -> bool:
    if sys.platform != "win32":
        return False
    # Find a runtime started by the earlier Player build or directly from its
    # managed installation. Paths remain scoped to this library.
    if any(runtime._is_active(root, channel) for channel in ("play", "lab")):
        return True
    backend = runtime_reference_play.BACKEND
    installation = runtime._installation(root, "lab", backend)
    name = runtime._component(backend, "lab")["package"]["executable"]
    return runtime._matching_process(runtime._path(installation, name))


def launch(root: Path, start: Callable[[], subprocess.Popen]) -> subprocess.Popen:
    lock = runtime._path(root, "atelier", "player-launch.lock")
    receipt = runtime._path(root, "atelier", "active-player-game.json")
    with runtime._operation_lock(lock, "A game is already opening."):
        if _session_running(receipt) or _existing_windows_game(root):
            raise runtime.RuntimeSetupError(ALREADY_OPEN)
        process = start()
        try:
            identity = _process_identity(process.pid)
            if identity is None:
                raise runtime.RuntimeSetupError("The game closed before Atelier could start the session.")
            runtime._atomic_json(receipt, {"pid": process.pid, "created": identity[1]})
        except Exception:
            runtime._stop_unregistered_runtime(process)
            raise
    return process


@contextmanager
def idle(root: Path):
    lock = runtime._path(root, "atelier", "player-launch.lock")
    receipt = runtime._path(root, "atelier", "active-player-game.json")
    with runtime._operation_lock(lock, "Another game is opening."):
        if _session_running(receipt) or _existing_windows_game(root):
            raise runtime.RuntimeSetupError(ALREADY_OPEN)
        yield


def backup(root: Path, operation: dict) -> dict | None:
    from tools.campaigns import CampaignStore

    with idle(root):
        return CampaignStore(root).capture_cards(
            operation["game"], operation["paths"], operation["lock"],
            operation["channel"], operation["route"], parent=operation["parent"],
        )

