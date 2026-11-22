"""Translate portable gameplay bindings for the pinned Lab runtimes."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from .local_store import member_path, plain_path

# SDL3's standard gamepad buttons use these numeric IDs. 100 and 101 are
# PCSX-Redux's trigger sentinels in controller binding format 1.
HOST_BUTTONS = {
    "south": (0, "A"), "east": (1, "B"), "west": (2, "X"), "north": (3, "Y"),
    "view": (4, "Back"), "start": (6, "Start"),
    "left stick": (7, "LeftStick"), "right stick": (8, "RightStick"),
    "left shoulder": (9, "LeftShoulder"), "right shoulder": (10, "RightShoulder"),
    "up": (11, "DPadUp"), "down": (12, "DPadDown"),
    "left": (13, "DPadLeft"), "right": (14, "DPadRight"),
    "left trigger": (100, "+LeftTrigger"), "right trigger": (101, "+RightTrigger"),
}

GAMEPLAY_DEFAULTS = {
    "Cross": "south", "Circle": "east", "Square": "west", "Triangle": "north",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "Start": "start", "Select": "view",
    "L1": "left shoulder", "R1": "right shoulder",
    "L2": "left trigger", "R2": "right trigger",
}
PAUSE_BUTTON = "right stick"
SHORTCUT_KEYS = {"quick": "F2", "suspend": "F9", "speed": "Tab"}
REMAPPABLE_KEYS = ("F2", "F7", "F9", "Tab")
GUIDE_KEYS = ("Ctrl+Shift+G", "Ctrl+Shift+H", "Ctrl+Shift+B")
_GUIDE_EXTRA_BUTTONS = ("right paddle 1", "left paddle 1", "right paddle 2", "left paddle 2",
                        "touchpad", "misc", "misc 2", "misc 3", "misc 4", "misc 5", "misc 6")
_ALL_GUIDE_BUTTONS = frozenset((*HOST_BUTTONS, *_GUIDE_EXTRA_BUTTONS))
_DUCK_INPUT_SECTIONS = {"hotkeys", *(f"pad{slot}" for slot in range(1, 9))}
KEYBOARD_FALLBACK = {
    "Cross": "K", "Circle": "L", "Square": "J", "Triangle": "I",
    "Up": "UpArrow", "Down": "DownArrow", "Left": "LeftArrow", "Right": "RightArrow",
    "Start": "Enter", "Select": "Backspace", "L1": "Q", "R1": "E", "L2": "1", "R2": "3",
}


def resolve_gameplay(overrides: dict[str, str]) -> dict[str, str]:
    if any(action not in GAMEPLAY_DEFAULTS or button not in HOST_BUTTONS or button == PAUSE_BUTTON
           for action, button in overrides.items()):
        raise ValueError("The gameplay button mapping is unsupported.")
    mapping = GAMEPLAY_DEFAULTS | overrides
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Gameplay buttons must have distinct assignments.")
    return mapping


def _retained_bindings(path: Path, sections: dict[str, set[str]], *,
                       keep_sdl: bool = False) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = {}
    section = ""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif "=" in line and not line.startswith(("#", ";")):
            key, value = (part.strip() for part in line.split("=", 1))
            if key in sections.get(section, ()) and value and (keep_sdl or not value.startswith("SDL-0/")):
                result.setdefault((section, key), []).append(value)
    return result


def duckstation_changes(path: Path, overrides: dict[str, str]) -> dict[str, dict[str, str | list[str]]]:
    mapping = resolve_gameplay(overrides)
    retained = _retained_bindings(path, {"Pad1": set(mapping), "Hotkeys": {"OpenPauseMenu"}})
    pad = {}
    for action, button in mapping.items():
        inputs = retained.get(("Pad1", action), [])
        if not any(binding.startswith("Keyboard/") for binding in inputs):
            inputs.append("Keyboard/" + KEYBOARD_FALLBACK[action])
        pad[action] = [*inputs, "SDL-0/" + HOST_BUTTONS[button][1]]
    for direction, axis in {"Up": "-LeftY", "Down": "+LeftY", "Left": "-LeftX", "Right": "+LeftX"}.items():
        pad[direction].append("SDL-0/" + axis)
    pause = retained.get(("Hotkeys", "OpenPauseMenu"), [])
    if not any(binding.startswith("Keyboard/") for binding in pause):
        pause.append("Keyboard/Escape")
    return {
        "Pad1": pad,
        "InputSources": {"SDL": "true"},
        "Hotkeys": {"OpenPauseMenu": [*pause, "SDL-0/" + HOST_BUTTONS[PAUSE_BUTTON][1]]},
        # The pinned runtime remembers whether focus loss caused the pause.
        "Main": {"PauseOnControllerDisconnection": "true", "PauseOnFocusLoss": "true"},
    }


def redux_port(overrides: dict[str, str]) -> dict[str, int | bool]:
    mapping = resolve_gameplay(overrides)
    bindings = {
        "Controller_Pad" + ("Sstart" if action == "Start" else action): HOST_BUTTONS[button][0]
        for action, button in mapping.items()
    }
    return {"Connected": True, "ID": 0, "PadType": 0, "DeviceType": 0,
            "ControllerBindingsVersion": 1, **bindings}


def hold_bindings(baseline: Path, gameplay: dict[str, str] | None) -> list[str]:
    bindings = _retained_bindings(baseline, {"Hotkeys": {"FastForward"}}, keep_sdl=True)
    buttons = [*bindings.get(("Hotkeys", "FastForward"), []), "Keyboard/Tab"]
    if gameplay is not None and "left stick" not in gameplay.values():
        buttons.append("SDL-0/LeftStick")
    return list(dict.fromkeys(buttons))


def shortcut_bindings(keys: dict[str, str], pad_choices: dict[str, str],
                      gameplay: dict[str, str] | None, fast: bool, *, reserved=()) -> dict[str, list[str]]:
    result = {action: ["Keyboard/" + keys[action]] for action in SHORTCUT_KEYS}
    if gameplay is None:
        return result
    free = set(HOST_BUTTONS) - set(gameplay.values()) - set(reserved) - {
        PAUSE_BUTTON, "left trigger", "right trigger",
    }
    actions = ("speed", "quick", "suspend") if fast else ("quick", "suspend")
    for action in actions:
        choice = pad_choices.get(action, "none" if action == "suspend" else "auto")
        if choice in free:
            result[action].append("SDL-0/" + HOST_BUTTONS[choice][1])
            free.remove(choice)
    for action in actions:
        if pad_choices.get(action, "none" if action == "suspend" else "auto") == "auto" and free:
            button = min(free, key=lambda button: (button != "left stick", HOST_BUTTONS[button][0]))
            result[action].append("SDL-0/" + HOST_BUTTONS[button][1])
            free.remove(button)
    return result


def guide_binding(key: str, choice: str, gameplay: dict[str, str] | None,
                  pad_choices: dict[str, str], available=None, *, navigation=(),
                  reference=False, runtime_buttons=()) -> dict:
    """Reserve one physical control before assigning automatic runtime shortcuts."""
    # A standard pad without known capabilities can be hot-plugged later. Only
    # assume the usual standard controls in that case, never its paddles or extras.
    supported = set(HOST_BUTTONS if available is None else available)
    occupied = set(gameplay.values()) if gameplay is not None else set()
    occupied.update(navigation)
    occupied.update(runtime_buttons)
    occupied.update(("left trigger", "right trigger"))
    if not reference:
        occupied.add(PAUSE_BUTTON)
        occupied.update(pad_choices.get(action) for action in SHORTCUT_KEYS)
    paddles = _GUIDE_EXTRA_BUTTONS[:4]
    ordered = dict.fromkeys((*paddles, "left stick", *HOST_BUTTONS, *_GUIDE_EXTRA_BUTTONS))
    buttons = [button for button in ordered if gameplay is not None
               and button in supported and button not in occupied]
    known = {*HOST_BUTTONS, *_GUIDE_EXTRA_BUTTONS, "auto", "none"}
    choice = choice if isinstance(choice, str) and choice in known else "auto"
    # SDL's "misc" can be the OS capture button. Extras other than paddles
    # are available by explicit choice, never an automatic system shortcut.
    automatic = next((button for button in buttons if button in paddles or button in HOST_BUTTONS), "")
    button = automatic if choice == "auto" else (choice if choice in buttons else "")
    return {"key": key if key in GUIDE_KEYS else GUIDE_KEYS[0], "keys": list(GUIDE_KEYS),
            "pad": button, "padChoice": choice, "buttons": buttons}


def _guide_ini(path: Path) -> dict[tuple[str, str], list[str]]:
    """Read repeated DuckStation INI assignments without dropping older chords."""
    with plain_path(path).open("rb") as stream:
        data = stream.read(512 * 1024 + 1)
    if len(data) > 512 * 1024:
        raise ValueError("Runtime settings exceed the guide input review limit.")
    result: dict[tuple[str, str], list[str]] = {}
    section = ""
    for raw in data.decode("utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().casefold()
            continue
        key, equal, value = line.partition("=")
        if not section or not equal or not key.strip():
            raise ValueError("Unrecognised DuckStation input configuration.")
        result.setdefault((section, key.strip().casefold()), []).append(value.strip())
    return result


def stock_guide_occupied(directory: Path, game: str, *, checkpoints: bool = False,
                         fast: bool = False) -> frozenset[str]:
    """Read only this stock Lab profile and its active serial-specific override."""
    serial = {"bof3": "SLUS-00422", "bof4": "SLUS-01324"}.get(game)
    if not serial:
        return _ALL_GUIDE_BUTTONS
    try:
        base = _guide_ini(directory / "settings.ini")
        if not base:
            return _ALL_GUIDE_BUTTONS
        profiles = [base]
        apply = base.get(("main", "applygamesettings"), ["true"])[-1].casefold()
        if apply not in ("0", "false", "no", "off"):
            folder = base.get(("folders", "gamesettings"), ["gamesettings"])[-1]
            relative = member_path(PureWindowsPath(folder).as_posix())
            override = plain_path(directory / relative / (serial + ".ini"))
            if override.is_file():
                profiles.append(_guide_ini(override))
    except (OSError, ValueError):
        return _ALL_GUIDE_BUTTONS

    # The managed controller recipe replaces these SDL-0 entries. Higher
    # priority game overrides and other runtime bindings still consume buttons.
    updated = {("pad1", control.casefold()) for control in GAMEPLAY_DEFAULTS}
    updated.add(("hotkeys", "openpausemenu"))
    if checkpoints:
        updated.update(("hotkeys", key) for key in (
            "savegamestate1", "saveselectedsavestate", "loadselectedsavestate", "poweroff"))
        if fast:
            updated.add(("hotkeys", "fastforward"))
    translated = {binding.casefold(): name for name, (_, binding) in HOST_BUTTONS.items()}
    translated.update({name.replace(" ", ""): name for name in _GUIDE_EXTRA_BUTTONS})
    translated["misc1"] = "misc"
    safe_axes = {"leftx", "lefty", "rightx", "righty", "lefttrigger", "righttrigger"}
    occupied = set()
    for profile in profiles:
        separate = profile.get(("controllerports", "usegamesettingsforcontroller"), ["false"])[-1]
        if (separate.casefold() not in ("0", "false", "no", "off")
                or profile.get(("controllerports", "inputprofilename"), [""])[-1]):
            return _ALL_GUIDE_BUTTONS
        for (section, key), lines in profile.items():
            if section not in _DUCK_INPUT_SECTIONS:
                continue
            for line in lines:
                for part in line.casefold().split("&"):
                    source, _, control = part.strip().partition("/")
                    if source.startswith(("xinput-", "dinput-", "rawinput-")):
                        return _ALL_GUIDE_BUTTONS
                    if source != "sdl-0":
                        continue
                    if profile is base and (section, key) in updated and "&" not in line:
                        continue
                    if control in translated:
                        occupied.add(translated[control])
                    elif control != "guide" and control.lstrip("+-") not in safe_axes:
                        # Numbered joystick controls have no proven physical
                        # equivalent on this controller's standard SDL mapping.
                        return _ALL_GUIDE_BUTTONS
    return frozenset(occupied)

