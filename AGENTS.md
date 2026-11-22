# Working on BoF Atelier

Read [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md) and the [licensing guide](docs/LICENSING.md) first. The repository contains the public browser guide and a desktop development snapshot. See the [roadmap](docs/ROADMAP.md) for the difference between available features, Lab evidence and planned work.

## Guide changes

- Edit `design/field-guide/wiki/bof3.json` or `bof4.json` for guide content. Preserve published page IDs and source attribution. Keep game-specific names and rules distinct.
- Use original writing. Record the edition, method and result of a check. Label reported facts that still need confirmation. Put a missable warning before the relevant decision.
- Rebuild with `python tools/build_public_guide.py`, then run `python tools/build_public_guide.py --check`. Review the rendered article and both volume indexes. Include the generated output with the source. [Maintenance and tests](docs/MAINTAINING.md)
- Keep private-disc-derived floors, raw game tables, game images, BIOS, personal saves and build caches outside the public repository. Use synthetic fixtures for public tests. Read the final diff and review staged files before handing over changes.

## Player and asset work

- Preserve Original and keep Play and Lab writable data separate. Direct game tests to disposable Lab copies. Keep the owner's desktop available. Run UI checks offscreen.
- Use reviewed input formats, validate paths, preserve track layout and record compatible runtime versions. Test failures, restores and cold reloads before claiming save safety.
- Declare art and audio provenance, existing licences, tools and in-game verification. Keep provider spending and publication subject to explicit owner approval.
- Report exact commands, results and untested routes. A synthetic test or boot screen cannot establish completion of a campaign or a real-controller test.
