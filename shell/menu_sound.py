"""Play an original menu cue through SDL. The game owns its own audio."""
from __future__ import annotations

import ctypes as ct
import os
from pathlib import Path
from random import choice

from shell.native_input import load_sdl


CUES = {"bof3": ("copper-morning", "after-the-rain"), "bof4": ("western-ridge", "distant-water")}
SDL_INIT_AUDIO = 0x10
SDL_DEFAULT_PLAYBACK = 0xffffffff


class AudioSpec(ct.Structure):
    _fields_ = [("format", ct.c_int), ("channels", ct.c_int), ("freq", ct.c_int)]


class CuePlayer:
    def __init__(self):
        self.dll = load_sdl()
        self.stream = None
        pointer = ct.c_void_p
        definitions = {
            "SDL_InitSubSystem": (ct.c_bool, [ct.c_uint32]),
            "SDL_QuitSubSystem": (None, [ct.c_uint32]),
            "SDL_LoadWAV": (ct.c_bool, [ct.c_char_p, ct.POINTER(AudioSpec), ct.POINTER(pointer), ct.POINTER(ct.c_uint32)]),
            "SDL_OpenAudioDeviceStream": (pointer, [ct.c_uint32, ct.POINTER(AudioSpec), pointer, pointer]),
            "SDL_PutAudioStreamData": (ct.c_bool, [pointer, pointer, ct.c_int]),
            "SDL_SetAudioStreamGain": (ct.c_bool, [pointer, ct.c_float]),
            "SDL_FlushAudioStream": (ct.c_bool, [pointer]),
            "SDL_ResumeAudioStreamDevice": (ct.c_bool, [pointer]),
            "SDL_DestroyAudioStream": (None, [pointer]),
            "SDL_free": (None, [pointer]),
        }
        for name, (result, parameters) in definitions.items():
            function = getattr(self.dll, name)
            function.restype, function.argtypes = result, parameters
        if not self.dll.SDL_InitSubSystem(SDL_INIT_AUDIO):
            raise OSError("Menu music could not open an audio output.")

    def play(self, path: Path, volume: int):
        self.stop()
        spec, buffer, size = AudioSpec(), ct.c_void_p(), ct.c_uint32()
        if not self.dll.SDL_LoadWAV(os.fsencode(path), ct.byref(spec), ct.byref(buffer), ct.byref(size)):
            raise OSError("The menu audio file could not be read.")
        try:
            self.stream = self.dll.SDL_OpenAudioDeviceStream(SDL_DEFAULT_PLAYBACK, ct.byref(spec), None, None)
            if not self.stream:
                raise OSError("Menu music could not open an audio output.")
            self.gain(volume)
            if not (self.dll.SDL_PutAudioStreamData(self.stream, buffer, size.value)
                    and self.dll.SDL_FlushAudioStream(self.stream)
                    and self.dll.SDL_ResumeAudioStreamDevice(self.stream)):
                raise OSError("Menu music could not start on the selected audio output.")
        except OSError:
            self.stop()
            raise
        finally:
            self.dll.SDL_free(buffer)

    def gain(self, volume: int):
        if self.stream:
            self.dll.SDL_SetAudioStreamGain(self.stream, volume / 100)

    def stop(self):
        if self.stream:
            self.dll.SDL_DestroyAudioStream(self.stream)
            self.stream = None

    def close(self):
        self.stop()
        self.dll.SDL_QuitSubSystem(SDL_INIT_AUDIO)


class MenuSound:
    def __init__(self, directory: Path):
        self.directory = directory
        self.player = None
        self.current_game = None
        self.previous = {}
        self.audition = False

    def update(self, service, *, audible: bool, audition: bool = False):
        eligible = (audible and service.focus and not service.starting_game and not service.process
                    and service.page in {"Journey", "Controls", "Library & setup"})
        if not eligible or not (service.settings.get("menu_music") is True or audition or self.audition):
            self.stop()
            return
        if service.game == self.current_game and not audition:
            if self.player:
                self.player.gain(service._menu_volume())
            return
        self.audition = audition
        self.current_game = service.game
        last = self.previous.get(service.game) or service.settings.get("last_menu_cue_" + service.game)
        cue = choice([name for name in CUES[service.game] if name != last])
        try:
            if self.player is None:
                self.player = CuePlayer()
            self.player.play(self.directory / (cue + ".wav"), service._menu_volume())
        except (OSError, AttributeError) as error:
            service.message = str(error)
            service.version += 1
            return
        self.previous[service.game] = cue
        if service.settings.get("menu_music") is True and not service.settings_damaged:
            service.settings["last_menu_cue_" + service.game] = cue
            service._save()

    def stop(self):
        if self.current_game and self.player:
            self.player.stop()
        self.current_game = None
        self.audition = False

    def close(self):
        if self.player:
            self.player.close()
            self.player = None
