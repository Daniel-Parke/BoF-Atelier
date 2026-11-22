"""Acquire the reviewed PCSX-Redux reference packages for an explicitly chosen private Lab."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlsplit

import httpx

from . import runtime_setup as runtime


async def fetch_reference(
    private_root: Path,
    backend: str = "pcsx-redux-cli",
    *,
    progress: Callable[[int, int], None] | None = None,
    cancel: asyncio.Event | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Fetch one exact Lab pin. The normal Player has no automatic DuckStation route."""
    if backend not in {"pcsx-redux", "pcsx-redux-cli"}:
        raise runtime.RuntimeSetupError(
            "Only the two pinned Lab reference builds use this acquisition route."
        )
    runtime._check_windows()
    entry = runtime._component(backend, "lab")
    package = entry["package"]
    cache = runtime._archive(private_root, backend, entry)
    if cache.is_file():
        return await asyncio.to_thread(
            runtime.prepare_runtime, private_root, "lab", backend
        )
    for key in ("url", "metadata"):
        parsed = urlsplit(package[key])
        if (
            parsed.scheme != "https"
            or parsed.netloc != "distrib.app"
            or not parsed.path.startswith("/storage/")
            or parsed.query
            or parsed.fragment
        ):
            raise runtime.RuntimeSetupError(
                "The reference package URL differs from the approved upstream source."
            )
    cache.parent.mkdir(parents=True, exist_ok=True)
    size = package["bytes"]
    if shutil.disk_usage(cache.parent).free < 2 * size + 16 * 1024**2:
        raise runtime.RuntimeSetupError(
            "Insufficient free space to download and verify this reference package."
        )

    def check_cancelled():
        if cancel is not None and cancel.is_set():
            raise runtime.RuntimeSetupError(
                "Reference download cancelled. You can retry safely."
            )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(45, connect=12),
        follow_redirects=False,
        transport=transport,
        limits=httpx.Limits(max_connections=1),
        headers={"Accept-Encoding": "identity"},
    ) as client:
        with tempfile.TemporaryDirectory(dir=cache.parent, prefix=".fetch-") as stage:
            temporary = Path(stage) / "package.zip"
            for attempt in range(3):
                check_cancelled()
                try:
                    async with client.stream("GET", package["metadata"]) as response:
                        response.raise_for_status()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            check_cancelled()
                            if len(raw) + len(chunk) > 128 * 1024:
                                raise runtime.RuntimeSetupError(
                                    "The official reference manifest exceeds its size limit."
                                )
                            raw.extend(chunk)
                    metadata = json.loads(raw)
                    identity = metadata["manifest"]
                    if (
                        metadata["id"] != package["release_id"]
                        or identity["buildId"] != package["release_id"]
                        or identity["changeset"] != package["source_commit"]
                        or identity["version"] != entry["version"]
                        or int(metadata["size"]) != size
                        or metadata["hashes"]["sha3"] != package["publisher_sha3_256"]
                        or metadata["path"] != urlsplit(package["url"]).path
                    ):
                        raise runtime.RuntimeSetupError(
                            "The upstream reference manifest differs from the reviewed pin."
                        )
                    received = 0
                    async with client.stream("GET", package["url"]) as response:
                        response.raise_for_status()
                        with temporary.open("wb") as output:
                            async for chunk in response.aiter_bytes(
                                chunk_size=256 * 1024
                            ):
                                check_cancelled()
                                received += len(chunk)
                                if received > size:
                                    raise runtime.RuntimeSetupError(
                                        "The reference download exceeds its pinned size."
                                    )
                                output.write(chunk)
                                if progress:
                                    progress(received, size)
                            output.flush()
                            os.fsync(output.fileno())
                    if received != size:
                        raise httpx.RemoteProtocolError(
                            "Incomplete reference download."
                        )
                    break
                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                    httpx.HTTPStatusError,
                ) as error:
                    if isinstance(
                        error, httpx.HTTPStatusError
                    ) and error.response.status_code not in {
                        408,
                        429,
                        500,
                        502,
                        503,
                        504,
                    }:
                        raise
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.25 * 2**attempt)
            check_cancelled()
            await asyncio.to_thread(runtime._verify_download, temporary, entry)
            result = await asyncio.to_thread(
                runtime.import_runtime_package, private_root, temporary, "lab", backend
            )
            runtime._atomic_json(
                cache.parent / f"manifest-{package['release_id']}.json", metadata
            )
            return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, default=runtime.DEFAULT_PRIVATE)
    parser.add_argument(
        "--backend", choices=("pcsx-redux", "pcsx-redux-cli"), default="pcsx-redux-cli"
    )
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                asyncio.run(fetch_reference(args.private_root, args.backend)), indent=2
            )
        )
    except (
        OSError,
        ValueError,
        KeyError,
        httpx.HTTPError,
        runtime.RuntimeSetupError,
    ) as error:
        parser.exit(1, str(error) + "\n")
