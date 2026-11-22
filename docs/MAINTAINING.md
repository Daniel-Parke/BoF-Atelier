# Maintain the browser Field Guide

The desktop app and browser preview read the same guide records. Edit those records and regenerate the preview whenever you change the content, artwork or reader. Readers can open the finished HTML without Python, a server or a network connection.

The published books declare their format in `version`. This reader accepts versions 1 and 2. Version 2 gives each grouped route an explicit list of floors and each item or encounter its own area membership. When changing that contract, test an earlier volume as well as the new one. Build the native reader with the matching books, then open one illustrated page from each volume in the finished package before distributing it.

## Make a change

For directions, timings, rewards and skill conditions, follow the [editorial standard](FIELD-GUIDE-STYLE.md) and check the [community sources](WALKTHROUGH-SOURCES.md). Cite the author and chapter in the shared record. Keep each illustrated route’s pin numbers aligned with its steps. Additions to the full area ledger also appear in the reference index.

| You want to change | Edit here |
| --- | --- |
| Walkthrough steps, items, encounters, missables, sources or wiki articles | [III volume](../design/field-guide/wiki/bof3.json) or [IV volume](../design/field-guide/wiki/bof4.json). Start with the game and existing page ID. |
| Shared guide data and validation | [Guide model](../shell/guide_book.py). Keep the desktop and browser consumers compatible. |
| Browser navigation or layout | [Browser reader template](../templates/public-guide/index.html) and its adjacent style or script files. |
| How the standalone file is assembled | [Public guide builder](../tools/build_public_guide.py). Only add reviewed public inputs. |

Keep page IDs stable. A new stop needs a unique ID. A reference to an item, encounter, source or related page must resolve in the same volume. Use original writing and record evidence against the exact edition. A public map can show an original schematic with a text route. A privately decoded game map stays in the local Player.

When one direction needs a longer explanation, add its exact landmark title to the stop’s optional `stepTopics` object. Set the value to an existing page ID in the stop’s `links`. For example, **Boiler lever** in III links to `lighthouse-gauge`. The reader shows the page title beside that instruction and can return to the same step. Keep a short action in the walkthrough so the link remains optional.

If a room matters to an article, use `floorRef` to open its floor directly. Supply the chapter’s `stop` ID, the integer `mapId` and `section` from its floor list. Include that chapter in the article’s `links`. A grouped chapter also needs to open the right area. McNeil’s shops, for example, point to map 7, section 0 of the Cedar chapter. Check the actual room in both readers, then check Back.

## Build and check

From the repository root, run the following with Python 3.11 or later. The guide builder uses the standard library.

```sh
python tools/build_public_guide.py
python tools/build_public_guide.py --check
python -m unittest discover -s tests -p "test_public_guide.py" -v
python -m unittest discover -s tests -p "test_guide_books.py" -v
python -m unittest discover -s tests -p "test_guide_editorial.py" -v
```

On Windows, use `py -3` if `python` does not select your installed version. On Linux and macOS, the command may be `python3`.

For a desktop layout or reading-position change, run `python -m unittest discover -s tests -p "test_field_guide_native.py" -v` from the configured [Player development environment](PLAYER-DEVELOPMENT.md). These tests open the actual Qt reader offscreen with disposable data. A skip for missing PySide6 means the native reader still needs testing.

1. Open **docs/index.html** in a browser. Turn off the network temporarily or use the browser's offline mode. Select the changed volume and page.
2. Check its route directions, item and encounter links, keyboard navigation and narrow-window layout. Try a deep link and the browser Back button. Check that later names stay hidden until the reader chooses to reveal them.
3. Include the changed sources and regenerated **docs/index.html** in the same pull request. `--check` checks for stale output without rewriting the file. If it fails, rerun the builder and inspect the changes. A hand edit to the generated HTML will disappear on the next build.

### Publish an approved revision with GitHub Pages

The repository owner enables this once for each repository or fork. In **Settings → Pages → Build and deployment**, choose **Deploy from a branch**, then **main** and **/docs**. Save. When the deployment completes, open the URL shown by GitHub. Add that verified URL to the repository's **About → Website** field. Do this only for the public, reviewed repository. [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)

The [public Field Guide](https://daniel-parke.github.io/BoF-Atelier/) serves both volumes. The two paintings and walkthrough links in the README open `#bof3/walk` and `#bof4/walk`. If you publish a fork under your own address, update the website field and the links in the README and player documentation.

After a change reaches `main`, wait for the Pages deployment to finish. Open both README walkthrough links. From the guide footer, download the offline copy and open it with the network disconnected.

For a repeatable browser check, install Playwright in your development environment and run `python tests/check_public_guide_browser.py --browser PATH_TO_CHROME --live-url PAGES_URL`. Use your installed Chrome or Edge executable and your published HTTPS URL ending in a slash. The check compares the served HTML to the local build, opens every walkthrough and wiki page, and checks the downloaded file.

Each illustrated route has one record in the volume's `fieldSheets`. Its numbered pins, text directions and diagram under `design/field-guide/atlas` share the same keys. For a chapter covering several places, assign each place a stable ID, its floor IDs and the items and encounters that belong there. This keeps the village and the woods distinct even when their names overlap.

The browser embeds the SVG. Windows uses a matching high-resolution WebP. With Pillow, Playwright and Chrome installed, run `python -m tools.render_field_maps kyria kyria-woods` to refresh selected drawings. Omit the names to rebuild all of them. Check both renderings at reading size. Review the new SHA-256 values in `tools/atlas_assets.py` before rebuilding the standalone book.

The four original Ogg recordings have SDL-compatible copies for the desktop menu. Regenerate those with `python -m tools.render_menu_audio` and Python SoundFile. Review the changed audio digest, listen to the edit and keep the credits. These are contributor tools. Reading the offline guide requires only a browser.
