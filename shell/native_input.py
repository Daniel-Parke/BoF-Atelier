"""Read local SDL3 controller input and isolate launcher button edges."""

from __future__ import annotations

import ctypes as ct
import ctypes.util
from pathlib import Path
import sys
import time


DEFAULT = {
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "select": "south",
    "back": "east",
}
BUTTONS = (
    "south",
    "east",
    "west",
    "north",
    "view",
    "guide",
    "start",
    "left stick",
    "right stick",
    "left shoulder",
    "right shoulder",
    "up",
    "down",
    "left",
    "right",
    "misc",
    "right paddle 1",
    "left paddle 1",
    "right paddle 2",
    "left paddle 2",
    "touchpad",
    "misc 2",
    "misc 3",
    "misc 4",
    "misc 5",
    "misc 6",
)
AXES = ("left", "right", "up", "down")


class Edges:
    """A held input cannot carry across focus, device or remapping boundaries."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = set()
        self.wait_release = True
        self.repeat_at = 0.0

    def advance(self, held, now, mapping):
        held = set(held)
        new = held - self.previous
        self.previous = held
        if self.wait_release:
            self.wait_release = bool(held)
            return None, None
        for action in ("back", "select", "up", "down", "left", "right"):
            if mapping.get(action) in new:
                self.repeat_at = now + 0.48
                return action, mapping[action]
        if now >= self.repeat_at:
            for action in AXES:
                if mapping.get(action) in held:
                    self.repeat_at = now + 0.15
                    return action, None
        return None, next(iter(sorted(new)), None)


class NativeInput:
    def __init__(self):
        self.dll = None
        self.handle = None
        self.device_id = 0
        self.devices = []
        self.edges = Edges()
        self.name = "Keyboard"
        self.profile = ""
        self.family = "position"
        self.raw = False
        self.held = frozenset()
        self.available_buttons = frozenset()
        self.error = ""
        self.check_time = 0.0
        self.last_input = ""
        try:
            if sys.platform == "win32":
                bundle = Path(
                    getattr(
                        sys,
                        "_MEIPASS",
                        Path(__file__).resolve().parents[1] / "private/shell-tools",
                    )
                )
                path = bundle / (
                    "native/SDL3.dll" if hasattr(sys, "_MEIPASS") else "SDL3.dll"
                )
                if not path.is_file():
                    raise OSError("The SDL3 input component is missing.")
                lib = ct.CDLL(str(path))
            else:
                packaged = Path(__file__).resolve().parents[1] / "native/libSDL3.so.0"
                name = (
                    str(packaged)
                    if sys.platform.startswith("linux") and packaged.is_file()
                    else ctypes.util.find_library("SDL3")
                )
                if not name:
                    raise OSError("The SDL3 input component is missing.")
                lib = ct.CDLL(name)
            definitions = {
                "SDL_SetHintWithPriority": (ct.c_bool, [ct.c_char_p, ct.c_char_p, ct.c_int]),
                "SDL_InitSubSystem": (ct.c_bool, [ct.c_uint32]),
                "SDL_QuitSubSystem": (None, [ct.c_uint32]),
                "SDL_GetJoysticks": (ct.POINTER(ct.c_uint32), [ct.POINTER(ct.c_int)]),
                "SDL_free": (None, [ct.c_void_p]),
                "SDL_IsGamepad": (ct.c_bool, [ct.c_uint32]),
                "SDL_OpenGamepad": (ct.c_void_p, [ct.c_uint32]),
                "SDL_OpenJoystick": (ct.c_void_p, [ct.c_uint32]),
                "SDL_CloseGamepad": (None, [ct.c_void_p]),
                "SDL_CloseJoystick": (None, [ct.c_void_p]),
                "SDL_GetGamepadButton": (ct.c_bool, [ct.c_void_p, ct.c_int]),
                "SDL_GamepadHasButton": (ct.c_bool, [ct.c_void_p, ct.c_int]),
                "SDL_GetGamepadAxis": (ct.c_int16, [ct.c_void_p, ct.c_int]),
                "SDL_GetGamepadType": (ct.c_int, [ct.c_void_p]),
                "SDL_GetNumJoystickButtons": (ct.c_int, [ct.c_void_p]),
                "SDL_GetNumJoystickAxes": (ct.c_int, [ct.c_void_p]),
                "SDL_GetJoystickButton": (ct.c_bool, [ct.c_void_p, ct.c_int]),
                "SDL_GetJoystickAxis": (ct.c_int16, [ct.c_void_p, ct.c_int]),
                "SDL_GetNumJoystickHats": (ct.c_int, [ct.c_void_p]),
                "SDL_GetJoystickHat": (ct.c_uint8, [ct.c_void_p, ct.c_int]),
                "SDL_GetJoystickNameForID": (ct.c_char_p, [ct.c_uint32]),
                "SDL_GetJoystickVendorForID": (ct.c_uint16, [ct.c_uint32]),
                "SDL_GetJoystickProductForID": (ct.c_uint16, [ct.c_uint32]),
                "SDL_UpdateJoysticks": (None, []),
                "SDL_PumpEvents": (None, []),
                "SDL_FlushEvents": (None, [ct.c_uint32, ct.c_uint32]),
            }
            for key, (result, args) in definitions.items():
                fn = getattr(lib, key)
                fn.restype, fn.argtypes = result, args
            # The Windows guide shortcut is read by this process while its own
            # runtime is foreground. This hint only affects this SDL instance.
            if sys.platform == "win32":
                lib.SDL_SetHintWithPriority(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1", 2)
            if not lib.SDL_InitSubSystem(0x2000):
                raise OSError("SDL3 could not initialise controller input.")
            self.dll = lib
        except (OSError, AttributeError) as exc:
            self.error = str(exc)

    def _detach(self):
        if self.handle:
            (self.dll.SDL_CloseJoystick if self.raw else self.dll.SDL_CloseGamepad)(
                self.handle
            )
        self.device_id, self.handle, self.profile = 0, None, ""
        self.name, self.family = "Keyboard", "position"
        self.held = self.available_buttons = frozenset()
        self.edges.reset()

    def choose(self, index):
        self._detach()
        if not self.devices:
            return
        key = self.devices[index % len(self.devices)]
        lib = self.dll
        self.raw = not lib.SDL_IsGamepad(key)
        self.handle = (lib.SDL_OpenJoystick if self.raw else lib.SDL_OpenGamepad)(key)
        if not self.handle:
            return
        self.device_id = key
        self.name = (lib.SDL_GetJoystickNameForID(key) or b"Gamepad").decode(
            "utf8", errors="replace"
        )
        self.profile = f"{lib.SDL_GetJoystickVendorForID(key):04x}:{lib.SDL_GetJoystickProductForID(key):04x}:{self.name}"
        kind = 0 if self.raw else lib.SDL_GetGamepadType(self.handle)
        if not self.raw:
            self.available_buttons = frozenset(
                name for index, name in enumerate(BUTTONS)
                if lib.SDL_GamepadHasButton(self.handle, index)
            )
        self.family = (
            "Xbox"
            if kind in (2, 3)
            else "PlayStation"
            if kind in (4, 5, 6)
            else "position"
        )

    def next_device(self):
        if self.device_id in self.devices:
            self.choose(self.devices.index(self.device_id) + 1)

    def glyph(self, physical):
        if self.family == "Xbox":
            return {"south": "A", "east": "B", "west": "X", "north": "Y"}.get(
                physical, physical
            )
        if self.family == "PlayStation":
            return {"south": "×", "east": "○", "west": "□", "north": "△"}.get(
                physical, physical
            )
        return {
            "south": "Bottom button",
            "east": "Right button",
            "west": "Left button",
            "north": "Top button",
        }.get(physical, physical)

    def poll(self, saved, active=True):
        if not self.dll:
            return None, None
        now = time.monotonic()
        lib = self.dll
        lib.SDL_PumpEvents()
        lib.SDL_UpdateJoysticks()
        lib.SDL_FlushEvents(0x600, 0x6FF)
        if now >= self.check_time:
            self.check_time = now + 0.6
            count = ct.c_int()
            ids = lib.SDL_GetJoysticks(ct.byref(count))
            self.devices = (
                [ids[i] for i in range(max(0, min(count.value, 32)))] if ids else []
            )
            if ids:
                lib.SDL_free(ids)
            if self.device_id not in self.devices and (self.devices or self.handle):
                self.choose(0)
        if not self.handle:
            self.held = frozenset()
            self.edges.reset()
            return None, None
        if self.raw:
            held = {
                f"button {i + 1}"
                for i in range(min(64, lib.SDL_GetNumJoystickButtons(self.handle)))
                if lib.SDL_GetJoystickButton(self.handle, i)
            }
            if lib.SDL_GetNumJoystickHats(self.handle) > 0:
                hat = lib.SDL_GetJoystickHat(self.handle, 0)
                held.update(
                    label
                    for bit, label in (
                        (1, "up"),
                        (2, "right"),
                        (4, "down"),
                        (8, "left"),
                    )
                    if hat & bit
                )
            x = (
                lib.SDL_GetJoystickAxis(self.handle, 0)
                if lib.SDL_GetNumJoystickAxes(self.handle) > 0
                else 0
            )
            y = (
                lib.SDL_GetJoystickAxis(self.handle, 1)
                if lib.SDL_GetNumJoystickAxes(self.handle) > 1
                else 0
            )
        else:
            held = {
                name
                for i, name in enumerate(BUTTONS)
                if lib.SDL_GetGamepadButton(self.handle, i)
            }
            x, y = (
                lib.SDL_GetGamepadAxis(self.handle, 0),
                lib.SDL_GetGamepadAxis(self.handle, 1),
            )
            for axis, name in ((4, "left trigger"), (5, "right trigger")):
                if lib.SDL_GetGamepadAxis(self.handle, axis) > 20000:
                    held.add(name)
        for name, value in zip(AXES, (-x, x, -y, y)):
            if value > 20000:
                held.add(name)
        self.held = frozenset(held)
        if not active:
            self.edges.reset()
            return None, None
        mapping = {**DEFAULT, **saved.get(self.profile, {})}
        action, physical = self.edges.advance(held, now, mapping)
        if physical:
            self.last_input = physical
        return action, physical

    def close(self):
        if self.dll:
            self._detach()
            self.dll.SDL_QuitSubSystem(0x2000)
            self.dll = None
