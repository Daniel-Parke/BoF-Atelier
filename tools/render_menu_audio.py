"""Rebuild the four SDL-compatible menu cues from the reviewed listening copies."""
from pathlib import Path

import soundfile


def main():
    directory = Path(__file__).resolve().parents[1] / "design/field-guide/atlas/sound"
    for name in ("after-the-rain", "copper-morning", "distant-water", "western-ridge"):
        signal, rate = soundfile.read(directory / (name + ".ogg"), dtype="int16")
        if rate != 32000 or signal.ndim != 2 or signal.shape[1] != 2:
            raise ValueError(f"Expected the original 32 kHz stereo recording of {name}")
        soundfile.write(directory / (name + ".wav"), signal, rate, subtype="IMA_ADPCM")


if __name__ == "__main__":
    main()
