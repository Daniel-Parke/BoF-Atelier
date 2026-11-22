# Maintain the browser Field Guide

The desktop app and browser preview read the same guide records. Edit those records and regenerate the preview whenever you change the content, artwork or reader. Readers can open the finished HTML without Python, a server or a network connection.

## Make a change

| You want to change | Edit here |
| --- | --- |
| Walkthrough steps, items, encounters, missables, sources or wiki articles | [III volume](../design/field-guide/wiki/bof3.json) or [IV volume](../design/field-guide/wiki/bof4.json). Start with the game and existing page ID. |
| Shared guide data and validation | [Guide model](../shell/guide_book.py). Keep the desktop and browser consumers compatible. |
| Browser navigation or layout | [Browser reader template](../templates/public-guide/index.html) and its adjacent style or script files. |
| How the standalone file is assembled | [Public guide builder](../tools/build_public_guide.py). Only add reviewed public inputs. |

Keep page IDs stable. A new stop needs a unique ID. A reference to an item, encounter, source or related page must resolve in the same volume. Use original writing and record evidence against the exact edition. A public map can show an original schematic with a text route. A privately decoded game map stays in the local Player.

## Build and check

From the repository root, run the following with Python 3.11 or later. The guide builder uses the standard library.

```sh
python tools/build_public_guide.py
python tools/build_public_guide.py --check
python -m unittest discover -s tests -p "test_public_guide.py" -v
```

On Windows, use `py -3` if `python` does not select your installed version. On Linux and macOS, the command may be `python3`.

1. Open **docs/index.html** in a browser. Turn off the network temporarily or use the browser's offline mode. Select the changed volume and page.
2. Check its route directions, item and encounter links, keyboard navigation and narrow-window layout. Try a deep link and the browser Back button. Check that later names stay hidden until the reader chooses to reveal them.
3. Include the changed sources and regenerated **docs/index.html** in the same pull request. `--check` checks for stale output without rewriting the file. If it fails, rerun the builder and inspect the changes. A hand edit to the generated HTML will disappear on the next build.

### Publish an approved revision with GitHub Pages

The repository owner enables this once for each repository or fork. In **Settings → Pages → Build and deployment**, choose **Deploy from a branch**, then **main** and **/docs**. Save. When the deployment completes, open the URL shown by GitHub. Add that verified URL to the repository's **About → Website** field. Do this only for the public, reviewed repository. [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)

Once a public deployment is verified, link the actual address from the first action in the README. Its two volume captions can then link straight to the hosted reader at `#bof3/walk` and `#bof4/walk`. Keep the offline instructions. Fork owners should use their own verified deployment address.

Subsequent merged changes to that branch update the hosted preview from the checked-in HTML. Check both the published site and the downloaded copy. Other stable fragments include `#bof4/wiki` and `#bof4/dam-kyria?area=Dam`.
