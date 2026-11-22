"""Open the Field Guide and return to the same owned Windows game window."""

from __future__ import annotations

import ctypes as ct
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys
import time

from tools.runtime_input import GUIDE_KEYS


class WindowsFocus:
    """The calling thread is the Player's GUI thread."""

    def __init__(self):
        self.user = ct.WinDLL("user32", use_last_error=True)
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.enum_callback = ct.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        hwnd, uint, boolean = wintypes.HWND, wintypes.UINT, wintypes.BOOL
        functions = {
            "GetForegroundWindow": (hwnd, []),
            "GetWindowThreadProcessId": (wintypes.DWORD, [hwnd, ct.POINTER(wintypes.DWORD)]),
            "EnumWindows": (boolean, [self.enum_callback, wintypes.LPARAM]),
            "IsWindowVisible": (boolean, [hwnd]),
            "GetWindow": (hwnd, [hwnd, uint]),
            "GetWindowLongW": (wintypes.LONG, [hwnd, ct.c_int]),
            "IsIconic": (boolean, [hwnd]),
            "ShowWindowAsync": (boolean, [hwnd, ct.c_int]),
            "SetForegroundWindow": (boolean, [hwnd]),
            "BringWindowToTop": (boolean, [hwnd]),
            "AttachThreadInput": (boolean, [uint, uint, boolean]),
            "GetAsyncKeyState": (ct.c_short, [ct.c_int]),
        }
        for name, (result, arguments) in functions.items():
            func = getattr(self.user, name)
            func.restype, func.argtypes = result, arguments
        self.kernel.GetCurrentThreadId.argtypes = []
        self.kernel.GetCurrentThreadId.restype = wintypes.DWORD

    def foreground(self):
        return self.user.GetForegroundWindow() or 0

    def owner(self, hwnd):
        process = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ct.byref(process))
        return process.value

    def window_for(self, pid):
        # EnumWindows returns top-level windows in Z order. Prefer the one
        # we actually observed during play; use this only on a manual open.
        windows = []

        @self.enum_callback
        def collect(window, _):
            if (self.user.IsWindowVisible(window) and self.owner(window) == pid
                    and not self.user.GetWindow(window, 4)  # GW_OWNER
                    and not self.user.GetWindowLongW(window, -20) & 0x80):  # WS_EX_TOOLWINDOW
                windows.append(window)
            return not windows

        self.user.EnumWindows(collect, 0)
        return windows[0] if windows else 0

    def focus(self, target, origin):
        if not target or not origin or self.foreground() != origin:
            return False
        if target == origin:
            return True
        if self.user.IsIconic(target):
            self.user.ShowWindowAsync(target, 9)  # SW_RESTORE
        self.user.SetForegroundWindow(target)
        if self.foreground() == target:
            return True
        # Only join the two live session input queues, for this user action.
        # A different app taking focus always cancels this attempt.
        if self.foreground() != origin:
            return False
        source = self.user.GetWindowThreadProcessId(origin, None)
        current = self.kernel.GetCurrentThreadId()
        attached = source != current and self.user.AttachThreadInput(current, source, True)
        try:
            if self.foreground() == origin:
                self.user.BringWindowToTop(target)
                self.user.SetForegroundWindow(target)
        finally:
            if attached:
                self.user.AttachThreadInput(current, source, False)
        deadline = time.monotonic() + 0.08
        while self.foreground() == origin and time.monotonic() < deadline:
            time.sleep(0.004)
        return self.foreground() == target

    def down(self, vk):
        return bool(self.user.GetAsyncKeyState(vk) & 0x8000)

    def chord(self, shortcut):
        if shortcut not in GUIDE_KEYS:
            return False, False
        keys = [self.down(vk) for vk in (0x11, 0x10, ord(shortcut[-1]))]
        extra = any(self.down(vk) for vk in (0x12, 0x5B, 0x5C))  # Alt or Windows
        return all(keys) and not extra, any(keys)

    def activation_held(self):
        return any(self.down(vk) for vk in (0x0D, 0x20, 0x1B))  # Return, Space, Escape


class _Release:
    """One completed press after observing neutral on this device/focus."""

    def __init__(self):
        self.neutral = False
        self.pressed = False

    def advance(self, full, held):
        if not held:
            fire = self.pressed
            self.pressed = False
            self.neutral = True
            return fire
        if self.neutral and full:
            self.pressed = True
        return False


@dataclass
class _Launch:
    origin: int
    deadline: float
    process: object | None = None
    next_probe: float = 0


class GuideSession:
    def __init__(self, windows=None):
        self.windows = windows or (WindowsFocus() if sys.platform == "win32" else None)
        self.reset()

    def reset(self):
        self._launch = None
        self._reset_reader()

    def _reset_reader(self):
        self.process = None
        self.game_window = 0
        self.reading = False
        self._context = None
        self._pad_source = None
        self._pad = None
        self._keys = _Release()
        self._button = _Release()
        self._waiting_return = False

    def _live(self, process):
        if process is None or process.poll() is not None:
            self.reset()
            return False
        if self.process is not process:
            self._reset_reader()
            self.process = process
        return self.windows is not None

    def arm_launch(self, player_hwnd):
        self.cancel_launch()
        if (not self.player_foreground(player_hwnd)
                or self.windows.owner(player_hwnd) != os.getpid()):
            return False
        # Verification can precede Popen by several seconds on slower disks.
        self._launch = _Launch(player_hwnd, time.monotonic() + 90)
        return True

    def cancel_launch(self):
        self._launch = None

    def poll_launch(self, process, player_hwnd):
        ticket = self._launch
        if ticket is None:
            return False
        now = time.monotonic()
        if (player_hwnd != ticket.origin or now >= ticket.deadline
                or not self.player_foreground(player_hwnd)
                or self.windows.owner(player_hwnd) != os.getpid()):
            self.cancel_launch()
            return False
        if process is None:
            if ticket.process is not None:
                self.cancel_launch()
            return False
        if process.poll() is not None or (ticket.process is not None and ticket.process is not process):
            self.cancel_launch()
            return False
        if ticket.process is None:
            ticket.process = process
            ticket.deadline = min(ticket.deadline, now + 12)
        if now < ticket.next_probe:
            return False
        ticket.next_probe = now + 0.12
        window = self.windows.window_for(process.pid)
        if not window or self.windows.owner(window) != process.pid:
            return False
        # Consume this even when Windows declines. A later Alt+Tab belongs to
        # the player, and a launch must never keep re-activating its window.
        self.cancel_launch()
        return self.windows.focus(window, player_hwnd)

    def player_foreground(self, player_hwnd):
        return bool(self.windows and player_hwnd and self.windows.foreground() == player_hwnd)

    def poll(self, process, player_hwnd, pad, guide_model):
        if not self._live(process) or not player_hwnd:
            return None
        windows = self.windows
        foreground = windows.foreground()
        owner = windows.owner(foreground) if foreground else 0
        if owner == process.pid:
            self.game_window = foreground
        here = foreground == player_hwnd
        eligible = (owner == process.pid) or here
        context = (foreground, self.reading, guide_model.get("key"))
        if self._context != context:
            self._keys = _Release()
            self._button = _Release()
            self._context = context
        self._pad = pad
        if not eligible:
            self._waiting_return = False
            return None
        if self.reading and not here:
            # Alt+Tab or a click has already returned to this game.
            return "return"
        if self.reading and self._waiting_return:
            return None if self._activation_held() else "return"

        key = guide_model.get("key") or GUIDE_KEYS[0]
        keyboard = self._keys.advance(*windows.chord(key))
        button = guide_model.get("pad")
        source = (pad.device_id, pad.profile, len(pad.devices), button)
        if source != self._pad_source:
            self._button = _Release()
            self._pad_source = source
        pad_active = (bool(button) and bool(pad.handle) and not pad.raw and len(pad.devices) == 1
                      and button in pad.available_buttons
                      and (not guide_model.get("profile") or guide_model["profile"] == pad.profile))
        held = pad_active and button in pad.held
        controller = self._button.advance(held, held) if pad_active else False
        if keyboard or controller:
            return "return" if self.reading else "open"
        return None

    def _activation_held(self):
        return bool((self._pad and self._pad.held) or self.windows.activation_held())

    def open(self, process, player_hwnd):
        if not self._live(process):
            raise ValueError("The game session has ended or its window is unavailable.")
        windows = self.windows
        if not player_hwnd or windows.owner(player_hwnd) != os.getpid():
            raise ValueError("The Player window is unavailable.")
        origin = windows.foreground()
        if origin and windows.owner(origin) == process.pid:
            target_game = origin
        elif origin == player_hwnd:
            target_game = self.game_window
            if not target_game or windows.owner(target_game) != process.pid:
                target_game = windows.window_for(process.pid)
        else:
            raise ValueError("Switch to the game or BoF Atelier to open the Field Guide.")
        if not target_game or windows.owner(target_game) != process.pid:
            raise ValueError("The game window is still opening. Try the Field Guide again in a moment.")
        if not windows.focus(player_hwnd, origin):
            raise ValueError("Windows kept focus on the game. Switch to BoF Atelier with Alt+Tab to open the guide.")
        self.game_window = target_game
        self.reading = True
        self._waiting_return = False
        self._context = None
        return True

    def return_to_game(self, process, player_hwnd):
        if self.process is not process or not self._live(process) or not self.reading:
            raise ValueError("This reader no longer has a live game session.")
        windows = self.windows
        origin = windows.foreground()
        if not self.game_window or windows.owner(self.game_window) != process.pid:
            raise ValueError("The original game window is unavailable. Switch to the game with Alt+Tab.")
        if origin != self.game_window:
            if origin != player_hwnd or windows.owner(player_hwnd) != os.getpid():
                raise ValueError("Switch to BoF Atelier to return to your game.")
            if self._activation_held():
                self._waiting_return = True
                return False
            self._waiting_return = False
            if not windows.focus(self.game_window, origin):
                raise ValueError("Windows kept focus on the guide. Use Return to game or switch with Alt+Tab.")
        self.reading = False
        self._waiting_return = False
        self._context = None
        return True
