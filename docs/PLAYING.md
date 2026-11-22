# Play Breath of Fire III or IV

You can use the [Field Guide](https://daniel-parke.github.io/BoF-Atelier/) alongside whichever version you already play. The walkthroughs use the North American PlayStation editions, so some details can differ on PC or in other regions.

| What do you have? | Start here |
| --- | --- |
| A Windows PC and you want to play **IV** | [Get the PC edition from GOG](https://www.gog.com/en/game/breath_of_fire_iv). Install it from your GOG library and open the game. This version runs on Windows without a PlayStation BIOS. |
| A PlayStation that plays the original disc | Put the disc in your console and play as usual. Open the guide on your phone or computer. |
| A PlayStation copy of **III or IV** that you'd like to play on a PC | Follow [the PlayStation setup](#play-a-playstation-copy-on-your-pc) below. |

The Atelier desktop app is still in development. Downloading this repository gives you its source and the guide. You can follow every player route on this page without writing code.

## Play a PlayStation copy on your PC

DuckStation is an emulator, a program that runs PlayStation games on a computer. Gather two things before you install it.

- **Your game.** If you already have an authorised disc copy in BIN/CUE format, keep the small `.cue` file and **all** the matching `.bin` files in one folder. If they're in an archive, extract the whole archive to one folder first. If you own a physical disc, see [Make a copy of your disc](#make-a-copy-of-your-disc).
- **A PlayStation BIOS.** This is the console's startup software. Your game disc doesn't include it. Use a compatible BIOS you have permission to use. If you own a console and local law permits making a copy, check the dumper author's equipment list before starting. [BIOS dumper instructions](https://github.com/ShendoXT/biosdumper)

### Start the game on Windows

1. Open [DuckStation's Windows download page](https://www.duckstation.org/windl). It has two downloads you'll need. Install **VC++ Runtime**, the Microsoft component DuckStation uses, then **Download Installer (Recommended)** and run the installer. [Other operating systems](https://github.com/stenzek/duckstation#downloading-and-running)
2. Open DuckStation. In its setup wizard, select the folder containing your BIOS. Connect your controller and check the first controller port in DuckStation's controller settings.
3. Use DuckStation's **Start File** command. Choose the game's **CUE** file. The CUE tells DuckStation which tracks belong together.
4. When you reach a save point, use the game's own **Save** option. Exit DuckStation, open the same CUE again and load the save from the game's title screen. This checks that you can return to the campaign before you put hours into it.

### If something goes wrong

| What you see | What to try |
| --- | --- |
| DuckStation asks for a BIOS again | Reopen its BIOS settings. Check that the selected folder contains the extracted firmware file and that DuckStation recognises it. |
| A track is missing or the disc won't open | Check that you extracted every file and kept the track names together. Start from the CUE. Keep the original files if you investigate a mismatch. |
| Your controller works in Windows but the game ignores it | In DuckStation's controller settings, choose port 1, map your controller and check its inputs there. III uses a digital PlayStation controller. |
| You want a backup of your progress | Close DuckStation before copying its memory card to a separate folder. Keep the original card in place. |

### Make a copy of your disc

If local law permits copying your disc for this use, you'll need a compatible optical drive. Media Preservation Frontend lets you choose the Sony PlayStation system and read the disc through a graphical interface. Keep the original CUE and every BIN it produces together. [Tool and downloads](https://github.com/SabreTools/MPF) · [Illustrated instructions](https://github.com/SabreTools/MPF/wiki/MPF-UI)

<details>
<summary>Identify a disc revision or check a track layout</summary>

Atelier's local PlayStation tests used III **SLUS-00422** and IV **SLUS-01324**. Compare the track hashes for your own revision if you need to identify a copy. A tested IV image had a difference in its track description. Preserve the original descriptor and track data when checking it. Replacement firmware such as OpenBIOS has its own game and emulator compatibility requirements. [III disc reference](https://redump.info/disc/184) · [IV disc reference](https://redump.info/disc/1222) · [OpenBIOS](https://pcsx-redux.consoledev.net/openbios/)

</details>
