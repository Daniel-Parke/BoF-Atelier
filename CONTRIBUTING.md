# Contribute to BoF Atelier

## Report a correction

[Report a Field Guide correction](https://github.com/Daniel-Parke/BoF-Atelier/issues/new?template=guide-correction.md). GitHub asks you to sign in to send the report. Give the game, area, route page and edition or region if known. Describe what the page says, what you saw and how another player could check it. For a missable, give the last safe moment to act. Keep spoilers out of the issue title. A report in plain English is enough.

For example, on IV's *Kurok, the Dam and Kyria Woods* page, identify the fork and say which entrance you used. A direction such as “take the western path when entering from Chamba” is easier to reproduce than “turn left”. Say whether you played the route or found the information in a reference. Please keep private saves, disc images, firmware and screenshots containing identifying information off issues and pull requests.

## Edit a guide page

The [guide editing and layout standard](docs/FIELD-GUIDE-STYLE.md) gives worked examples from Cedar Woods and the Dam. Use it for both readers. Check a community walkthrough for omissions before calling a route complete.

1. Fork this repository. Find the entry in [III's volume](design/field-guide/wiki/bof3.json) or [IV's volume](design/field-guide/wiki/bof4.json) by its displayed title or area. Use the pencil on GitHub for a small change, or make a branch in your local copy.
2. Edit that entry in place. Preserve its ID so existing page links keep working. Write your own concise directions. Place a warning **before** the action that closes an opportunity. Keep optional lore out of the main sequence.
3. Add the source or describe your own check. A reference needs an author, title and page or section where available. Prefer links to the creator, publisher or a legitimate catalogue record. Attribution alone does not permit copying another guide's prose, maps or tables.
4. If you have Python, [rebuild the HTML and check it](docs/MAINTAINING.md). Review the exact page you changed in your browser. For a browser-only edit, mention that the generated preview needs rebuilding so a maintainer can do it before merge.
5. Open a pull request against the default branch. Name the game and area, explain the change and record the checks you actually ran. Reviewers can reproduce a small, focused correction more easily than a whole rewritten volume.

## Contribute art, audio or code

| Contribution | What helps a reviewer |
| --- | --- |
| An original illustration or map | Identify the scene, original artist, source files, edits, tools and permission. Mark diagrams as schematic when distances or geometry are approximate. Provide a short text description. |
| A sprite or animation proposal | Identify its use, palette, frame count, timing, pivots and loop. Show the proposed change with an original or cleared example. Keep extracted game graphics on your own device. |
| Music or sound | Identify the composition, arrangement and recording separately. Name the rights holder and permission for each. For a cue, describe start, loop, transition and fallback. |
| A bug fix or test | Give the entry point, expected result, actual result and smallest reproducible case. Use synthetic fixtures. For save changes, test on a disposable copy and check cold reload. |
| AI-assisted work | Follow the same process. Check facts and routes yourself, identify generated artwork and its inputs, and record tool and version where known. A contributor takes responsibility for the submission. Keep private game files and reference art out of external services unless use and transfer are authorised. [Agent instructions](AGENTS.md) |

Only submit work you have the right to contribute under the relevant project terms. Original code uses MIT. Original guide text and project artwork use CC BY 4.0 to the extent the contributor holds the rights. Credit previous authors, identify changes and retain separate third-party notices. PatterTech marks have separate terms. [Licences and attribution](docs/LICENSING.md)
