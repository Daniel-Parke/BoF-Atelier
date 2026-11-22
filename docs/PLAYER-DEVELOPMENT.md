# Run the Windows Player source

This page is for contributors who want to change the Windows app. If you came here to play, [choose your game and setup](PLAYING.md). If you want help with a route, [open the Field Guide](../README.md#read-the-field-guide).

## Inspect the app in an empty Lab

Start at the repository root on Windows x64. The reference development environment used 64-bit Python 3.14. Install Python from the Python project if needed. The commands below create an isolated environment under `private`. They use the versions recorded on the Windows development host. [Python for Windows](https://www.python.org/downloads/windows/) · [Virtual environments](https://docs.python.org/3/library/venv.html)

```powershell
py -3.14 -m venv private/dev-env
private/dev-env/Scripts/python.exe -m pip install PySide6-Essentials==6.12.0 jsonschema==4.26.0 packaging==26.3 httpx==0.28.1
private/dev-env/Scripts/python.exe -m shell.qt_player --library private/contributor-lab --channel lab
```

Choose a fresh development library for the first run. The window can open with an empty library. Campaign, Field Guide, settings and setup live in `shell/qml/`. `shell/qt_player.py` starts Qt and `shell/service.py` handles Player operations. Local testing of a game requires authorised media, compatible firmware and a separately obtained runtime. Keep the only copy of a campaign outside the development library.

For an automated UI check, render the Field Guide offscreen instead of starting an interactive session. This example writes an image beneath `private/` and exits.

```powershell
private/dev-env/Scripts/python.exe -m shell.qt_player --channel lab --library private/contributor-lab --title bof4 --view "Field guide" --review private/guide-review.png
```

## Optional native components

| Feature | Requirement |
| --- | --- |
| Windows controller input | The source looks for `private/shell-tools/SDL3.dll`. The reference environment used the official Windows x64 SDL 3.4.20 release. Retain its accompanying licence. Keyboard input is available independently. [Official SDL release](https://github.com/libsdl-org/SDL/releases/tag/release-3.4.20) |
| 7-Zip disc import | The importer uses libarchive. On Windows it can use the System32 archive reader available on the test host. If that component is unavailable, import a local CUE with its complete track set. [libarchive](https://www.libarchive.org/) |
| Emulation | Use authorised components and a disposable Lab library for gameplay tests. Versions, writable data paths, region and track layout matter. External packages retain their own licensing terms. [Disc and firmware guide](PLAYING.md) |

Do not publish a binary made from this development setup as an official Atelier release. Public Player packaging still needs a verified dependency inventory, notices, clean-machine testing and recovery checks. [Roadmap](ROADMAP.md) · [Licence scope](LICENSING.md)
