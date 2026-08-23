#!/usr/bin/env python3
"""Candidate streaming zlib helper for the bounded #34 optimization."""
from __future__ import annotations

import zlib
from pathlib import Path


DEFAULT_DECOMPRESSION_CHUNK_BYTES = 16 << 10


def zlib_to_file(
    compressed: bytes,
    dest: Path,
    progress=None,
    *,
    chunk_bytes: int = DEFAULT_DECOMPRESSION_CHUNK_BYTES,
) -> int:
    """Stream zlib data to *dest* using a bounded compressed-input chunk."""
    if chunk_bytes <= 0:
        raise ValueError("decompression chunk size must be positive")

    dec = zlib.decompressobj()
    total = 0
    with dest.open("wb") as out:
        mv = memoryview(compressed)
        size = len(mv)
        for offset in range(0, size, chunk_bytes):
            chunk = dec.decompress(mv[offset:offset + chunk_bytes])
            out.write(chunk)
            total += len(chunk)
            if progress is not None:
                done = min(offset + chunk_bytes, size)
                progress.maybe(
                    f"    [data] decompressing {100.0 * done / max(size, 1):5.1f}% "
                    f"({done / 1048576:.1f}/{size / 1048576:.1f} MiB input; "
                    f"{total / 1048576:.1f} MiB output)"
                )
        chunk = dec.flush()
        out.write(chunk)
        total += len(chunk)
    return total
