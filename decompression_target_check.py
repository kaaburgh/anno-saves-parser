#!/usr/bin/env python3
"""Bounded private-save validation for decompression chunk candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import anno_save_probe as probe
from decompression import DEFAULT_DECOMPRESSION_CHUNK_BYTES, zlib_to_file as stream_zlib_to_file

SCHEMA = "anno-saves-parser/decompression-target-check"
SCHEMA_VERSION = 1
REFERENCE_CHUNK_BYTES = 1 << 20


def _positive_even_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0 or parsed % 2 != 0:
        raise argparse.ArgumentTypeError("value must be a positive even integer")
    return parsed


def _validate_repeats(repeats: int) -> None:
    if repeats <= 0 or repeats % 2 != 0:
        raise ValueError("repeats must be a positive even integer")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(state: dict) -> bytes:
    return json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _run_once(
    save: Path,
    chunk_bytes: int,
    *,
    canonicalize_fn: Callable = probe.canonicalize_save,
    decompressor_fn: Callable = stream_zlib_to_file,
) -> tuple[str, float]:
    original = probe.zlib_to_file

    def selected_decompressor(compressed, dest, progress=None):
        return decompressor_fn(
            compressed,
            dest,
            progress,
            chunk_bytes=chunk_bytes,
        )

    try:
        probe.zlib_to_file = selected_decompressor
        with tempfile.TemporaryDirectory(prefix="anno-decompression-check-") as td:
            started = time.perf_counter()
            state = canonicalize_fn(save, Path(td), None)
            elapsed_seconds = time.perf_counter() - started
    finally:
        probe.zlib_to_file = original

    return hashlib.sha256(_canonical_bytes(state)).hexdigest(), elapsed_seconds


def compare_save(
    save: Path,
    repeats: int = 2,
    *,
    canonicalize_fn: Callable = probe.canonicalize_save,
    decompressor_fn: Callable = stream_zlib_to_file,
) -> dict:
    _validate_repeats(repeats)
    save = save.resolve()
    chunk_sizes = [REFERENCE_CHUNK_BYTES, DEFAULT_DECOMPRESSION_CHUNK_BYTES]
    results = {
        chunk_bytes: {
            "chunk_bytes": chunk_bytes,
            "canonical_sha256": None,
            "elapsed_seconds": [],
        }
        for chunk_bytes in chunk_sizes
    }

    for repeat_index in range(repeats):
        ordered_chunks = chunk_sizes if repeat_index % 2 == 0 else list(reversed(chunk_sizes))
        for chunk_bytes in ordered_chunks:
            digest, elapsed_seconds = _run_once(
                save,
                chunk_bytes,
                canonicalize_fn=canonicalize_fn,
                decompressor_fn=decompressor_fn,
            )
            result = results[chunk_bytes]
            result["elapsed_seconds"].append(elapsed_seconds)
            if result["canonical_sha256"] is None:
                result["canonical_sha256"] = digest
            elif digest != result["canonical_sha256"]:
                raise RuntimeError(
                    "canonical state changed between repeated runs for one chunk size"
                )

    runs = [results[REFERENCE_CHUNK_BYTES], results[DEFAULT_DECOMPRESSION_CHUNK_BYTES]]
    if runs[0]["canonical_sha256"] != runs[1]["canonical_sha256"]:
        raise RuntimeError(
            "canonical state differs between reference and candidate decompression chunks"
        )
    return {
        "source_sha256": _sha256_file(save),
        "source_size": save.stat().st_size,
        "runs": runs,
    }


def build_report(saves: list[Path], repeats: int) -> dict:
    _validate_repeats(repeats)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "runner": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "repeats": repeats,
        "reference_chunk_bytes": REFERENCE_CHUNK_BYTES,
        "candidate_chunk_bytes": DEFAULT_DECOMPRESSION_CHUNK_BYTES,
        "inputs": [compare_save(save, repeats) for save in saves],
    }


def validate_output_path(output: Path, saves: list[Path]) -> Path:
    resolved_output = output.resolve()
    source_paths = {save.resolve() for save in saves}
    if resolved_output in source_paths:
        raise ValueError("output path must not alias a source save")
    return resolved_output


def _write_json_atomic(path: Path, value: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, indent=2, sort_keys=True)
            out.write("\n")
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the historical 1 MiB and candidate 16 KiB decompression "
            "chunks on operator-owned Anno saves without modifying the source saves."
        )
    )
    parser.add_argument("saves", nargs="+", type=Path)
    parser.add_argument("--repeats", type=_positive_even_int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("decompression-target-check.json"),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)
    try:
        output = validate_output_path(args.output, args.saves)
        report = build_report(args.saves, args.repeats)
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    _write_json_atomic(output, report)
    print(output)


if __name__ == "__main__":
    main()
