#!/usr/bin/env python3
"""List or explicitly download unchanged official DuckStation release assets.

Requires httpx. No installation, extraction, configuration or execution occurs.
Downloads are private. Listing performs a network request but writes no files.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, AsyncIterator, Callable
from urllib.parse import quote, urljoin, urlparse
try:
    from .local_store import plain_path
except ImportError:
    from local_store import plain_path

try:
    import httpx
except ImportError:
    raise SystemExit('Optional helper requires httpx: python -m pip install -r tools/requirements-network.txt')

API_ROOT = 'https://api.github.com/repos/stenzek/duckstation/releases/tags/'
OFFICIAL_ASSET_PREFIX = 'https://github.com/stenzek/duckstation/releases/download/'
DEFAULT_DESTINATION = Path(__file__).resolve().parents[1] / 'private/downloads/duckstation'
MAX_ASSET_BYTES = 1024**3
LOCK_FILE = Path(__file__).resolve().parents[1] / 'research/duckstation-release-lock.json'
PINNED_TAG = 'v0.1-12442'


class DownloadError(RuntimeError):
    pass


def trusted_url(url: str, *, metadata: bool = False) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    if metadata:
        return parsed.hostname == 'api.github.com' and parsed.path.startswith('/repos/stenzek/duckstation/releases/tags/')
    return parsed.hostname in {'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}


@asynccontextmanager
async def trusted_stream(client: httpx.AsyncClient, url: str) -> AsyncIterator[httpx.Response]:
    """Check each redirect before issuing the next request; never disable TLS."""
    current = url
    for _ in range(6):
        if not trusted_url(current):
            raise DownloadError('Release asset attempted to use an unapproved host or URL scheme.')
        async with client.stream('GET', current, follow_redirects=False,
                                 headers={'Accept-Encoding': 'identity'}) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get('location')
                if not location:
                    raise DownloadError('Redirect has no Location header.')
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            yield response
            return
    raise DownloadError('Too many asset redirects.')


async def get_release(client: httpx.AsyncClient, tag: str) -> dict[str, Any]:
    if not tag or len(tag) > 120:
        raise DownloadError('Invalid release tag.')
    url = API_ROOT + quote(tag, safe='')
    async with client.stream('GET', url, follow_redirects=False) as response:
        response.raise_for_status()
        payload = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65_536):
            if len(payload) + len(chunk) > 2 * 1024**2:
                raise DownloadError('Unexpectedly large release metadata.')
            payload.extend(chunk)
    release = json.loads(payload)
    if not isinstance(release, dict) or not isinstance(release.get('id'), int) or not isinstance(release.get('assets'), list):
        raise DownloadError('Unexpected official release metadata structure.')
    if release.get('draft'):
        raise DownloadError('Draft releases are not accepted.')
    return release


def validate_asset(asset: dict[str, Any]) -> None:
    name = asset.get('name', '')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,180}', name):
        raise DownloadError('Unsafe or unsupported asset filename.')
    size = asset.get('size')
    if not isinstance(size, int) or size <= 0 or size > MAX_ASSET_BYTES:
        raise DownloadError('Unexpected asset size; maximum is 1 GiB.')
    url = asset.get('browser_download_url', '')
    if not isinstance(url, str) or not url.startswith(OFFICIAL_ASSET_PREFIX) or not trusted_url(url):
        raise DownloadError('Asset is not an official DuckStation release URL.')
    digest = asset.get('digest')
    if digest is not None and not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', str(digest)):
        raise DownloadError('Publisher digest uses an unsupported format; review manually.')


async def download_asset(client: httpx.AsyncClient, release: dict[str, Any], asset: dict[str, Any],
                         destination: Path, semaphore: asyncio.Semaphore, *,
                         progress: Callable[[int, int], None] | None = None,
                         cancel: asyncio.Event | None = None) -> dict[str, Any]:
    validate_asset(asset)
    async with semaphore:
        if type(release.get('id')) is not int or release['id'] < 1:
            raise DownloadError('Invalid release identity.')
        output_directory = plain_path(destination / str(release['id']))
        output_directory.mkdir(parents=True, exist_ok=True)
        final = plain_path(output_directory / (asset['name'] + '.asset'))
        legacy = plain_path(output_directory / asset['name'])
        legacy_receipt = plain_path(legacy.with_name(legacy.name + '.receipt.json'))
        if final.exists() or legacy.exists() or legacy_receipt.exists():
            raise DownloadError('A current or legacy download exists. Verify its receipt or select a repair directory.')
        if shutil.disk_usage(output_directory).free < asset['size'] + 2**20:
            raise DownloadError('Insufficient disk space for the component and its receipt.')
        with tempfile.TemporaryDirectory(prefix='.download-', dir=output_directory) as temp:
            staged = Path(temp) / 'component'
            staged.mkdir()
            output_file = staged / asset['name']
            for attempt in range(3):
                received = 0
                digest = hashlib.sha256()
                if cancel is not None and cancel.is_set():
                    raise DownloadError('Download cancelled.')
                try:
                    async with trusted_stream(client, asset['browser_download_url']) as response:
                        with output_file.open('wb') as target:
                            async for chunk in response.aiter_bytes(chunk_size=256 * 1024):
                                if cancel is not None and cancel.is_set():
                                    raise DownloadError('Download cancelled.')
                                received += len(chunk)
                                if received > asset['size']:
                                    raise DownloadError('Download exceeds the declared size.')
                                digest.update(chunk)
                                target.write(chunk)
                                if progress:
                                    progress(received, asset['size'])
                            target.flush()
                            os.fsync(target.fileno())
                    break
                except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.HTTPStatusError) as error:
                    if (isinstance(error, httpx.HTTPStatusError)
                            and error.response.status_code not in {408, 429, 500, 502, 503, 504}):
                        raise
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.25 * 2**attempt)
            if received != asset['size']:
                raise DownloadError('Download ended before the declared size.')
            actual_digest = digest.hexdigest()
            expected_digest = asset.get('digest')
            if expected_digest and actual_digest.lower() != expected_digest.split(':', 1)[1].lower():
                raise DownloadError('Publisher SHA-256 digest does not match downloaded bytes.')
            receipt = {
                'retrieved_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'repository': 'stenzek/duckstation', 'release_id': release['id'],
                'tag_name': release.get('tag_name'), 'release_published_at': release.get('published_at'),
                'asset_id': asset.get('id'), 'name': asset['name'], 'source_url': asset['browser_download_url'],
                'bytes': received, 'sha256': actual_digest, 'publisher_digest': expected_digest,
                'publisher_digest_verified': bool(expected_digest),
                'verification_note': 'Official HTTPS source. A local digest alone is not independent publisher authentication.',
                'installed': False, 'executed': False,
            }
            receipt['relative_path'] = (final / asset['name']).relative_to(destination.resolve()).as_posix()
            with (staged / 'receipt.json').open('x', encoding='utf-8') as stream:
                json.dump(receipt, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            staged.rename(final)
            return receipt


async def run(arguments: argparse.Namespace) -> int:
    timeout = httpx.Timeout(60.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, headers={'Accept': 'application/vnd.github+json',
                                                         'User-Agent': 'BoF-Atelier-Seed/1'}) as client:
        release = await get_release(client, arguments.tag)
        summary = {'release_id': release['id'], 'tag': release.get('tag_name'),
                   'published_at': release.get('published_at'),
                   'assets': [{'name': asset.get('name'), 'bytes': asset.get('size'), 'digest': asset.get('digest')}
                              for asset in release['assets']]}
        print(json.dumps(summary, indent=2))
        if not arguments.download:
            print('Listing only. Nothing downloaded, installed or executed.')
            return 0
        if not arguments.asset:
            raise DownloadError('Use --asset with exact names from the listing and --download.')
        selected_names = list(dict.fromkeys(arguments.asset))
        assets_by_name = {asset['name']: asset for asset in release['assets']}
        missing = [name for name in selected_names if name not in assets_by_name]
        if missing:
            raise DownloadError('Requested assets not present in this release: ' + ', '.join(missing))
        lock = json.loads(LOCK_FILE.read_text(encoding='utf-8'))
        locked = {row['name']: row for row in lock['assets']}
        if release['id'] != lock['release_id'] or release.get('tag_name') != lock['tag']:
            raise DownloadError('Release does not match the reviewed qualification lock.')
        for name in selected_names:
            expected = locked.get(name)
            if not expected or any(assets_by_name[name].get(key) != value for key, value in expected.items()):
                raise DownloadError(f'No matching verified asset lock for {name}.')
        semaphore = asyncio.Semaphore(3)
        results = await asyncio.gather(*(download_asset(client, release, assets_by_name[name],
                                                        arguments.destination, semaphore)
                                         for name in selected_names), return_exceptions=True)
        failed = False
        for name, result in zip(selected_names, results):
            if isinstance(result, BaseException):
                failed = True
                print(f'ERROR {name}: {result}', file=sys.stderr)
            else:
                print(json.dumps(result, indent=2))
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', default=PINNED_TAG, help='Official tag. Downloading requires the reviewed release lock.')
    parser.add_argument('--asset', action='append', help='Exact asset name from metadata. May be repeated.')
    parser.add_argument('--download', action='store_true', help='Explicitly fetch selected assets, without installing them.')
    parser.add_argument('--destination', type=Path, default=DEFAULT_DESTINATION)
    arguments = parser.parse_args()
    try:
        return asyncio.run(run(arguments))
    except (DownloadError, httpx.HTTPError, ValueError, KeyError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
