#!/usr/bin/env python3
"""Operator-side target validation for top-level session discovery (#35)."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import Callable

from anno_save_probe import (
    _required_rda_member,
    bb_meta,
    extract_sessions,
    rda_entries,
    zlib_to_file,
)
from top_level_session_scan import scan_top_level_sessions_mmap


REPORT_SCHEMA = "anno-saves-parser/top-level-session-target-check"
REPORT_VERSION = 1
DEFAULT_REPEATS = 4


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[str, int]:
    return _sha256_file(path), path.stat().st_size


def _copy_verified_snapshot(source: Path, work_dir: Path) -> tuple[Path, str, int]:
    """Copy one source save and prove the bytes stayed stable across the snapshot."""
    before = _file_identity(source)
    snapshot = work_dir / "source.a7s"
    shutil.copyfile(source, snapshot)
    snapshot_identity = _file_identity(snapshot)
    after = _file_identity(source)
    if before != snapshot_identity or after != snapshot_identity:
        raise ValueError("source save changed while creating verified snapshot")
    return snapshot, snapshot_identity[0], snapshot_identity[1]


def _descriptor_digest(descriptors: list[dict]) -> str:
    payload = json.dumps(
        descriptors,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_repeats(repeats: int) -> None:
    if repeats <= 0 or repeats % 2:
        raise ValueError("repeats must be a positive even integer")


def _prepare_data_bin(save: Path, work_dir: Path) -> Path:
    entries = rda_entries(save)
    member = _required_rda_member(entries, save, "data.a7s")
    with save.open("rb") as stream:
        stream.seek(member["offset"])
        compressed = stream.read(member["compressed_size"])
    if member["flags"] & 0x1:
        compressed = zlib.decompress(compressed)
    data_bin = work_dir / "data.bin"
    zlib_to_file(compressed, data_bin)
    return data_bin


def _timed_scan(scan: Callable[[], list[dict]]) -> tuple[list[dict], float]:
    started = time.perf_counter()
    descriptors = scan()
    return descriptors, time.perf_counter() - started


def compare_data_bin(data_bin: Path, repeats: int = DEFAULT_REPEATS) -> dict:
    """Compare current buffered discovery with the mmap candidate on one FileDB."""
    _validate_repeats(repeats)
    tags_off, _, tags, attrs = bb_meta(data_bin)

    reference_times: list[float] = []
    candidate_times: list[float] = []
    reference_expected: list[dict] | None = None
    candidate_expected: list[dict] | None = None

    def reference() -> list[dict]:
        return extract_sessions(data_bin)

    def candidate() -> list[dict]:
        return scan_top_level_sessions_mmap(data_bin, tags_off, tags, attrs)

    for repeat in range(repeats):
        order = (
            (("reference", reference), ("candidate", candidate))
            if repeat % 2 == 0
            else (("candidate", candidate), ("reference", reference))
        )
        for label, scan in order:
            descriptors, elapsed = _timed_scan(scan)
            if label == "reference":
                reference_times.append(elapsed)
                if reference_expected is None:
                    reference_expected = descriptors
                elif descriptors != reference_expected:
                    raise ValueError("buffered session discovery is nondeterministic")
            else:
                candidate_times.append(elapsed)
                if candidate_expected is None:
                    candidate_expected = descriptors
                elif descriptors != candidate_expected:
                    raise ValueError("mmap session discovery is nondeterministic")

    assert reference_expected is not None
    assert candidate_expected is not None
    if candidate_expected != reference_expected:
        raise ValueError("mmap session descriptors differ from buffered reference")

    return {
        "descriptor_count": len(reference_expected),
        "descriptor_sha256": _descriptor_digest(reference_expected),
        "reference_seconds": reference_times,
        "candidate_seconds": candidate_times,
    }


def build_report(saves: list[Path], repeats: int = DEFAULT_REPEATS) -> dict:
    """Run the bounded comparison on distinct operator-owned saves without returning paths."""
    _validate_repeats(repeats)
    if len(saves) < 2:
        raise ValueError("target validation requires at least two saves")

    resolved_saves: list[Path] = []
    for save in saves:
        resolved = save.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"save does not exist: {save}")
        if resolved.suffix.lower() != ".a7s":
            raise ValueError(f"not an .a7s save: {save}")
        resolved_saves.append(resolved)

    if len(set(resolved_saves)) != len(resolved_saves):
        raise ValueError("target validation requires distinct save paths")

    results = []
    seen_source_sha256: set[str] = set()
    for resolved in resolved_saves:
        with tempfile.TemporaryDirectory(prefix="anno-session-target-check-") as temp:
            work_dir = Path(temp)
            snapshot, source_sha256, source_size = _copy_verified_snapshot(resolved, work_dir)
            if source_sha256 in seen_source_sha256:
                raise ValueError("target validation requires distinct save contents")
            seen_source_sha256.add(source_sha256)
            data_bin = _prepare_data_bin(snapshot, work_dir)
            comparison = compare_data_bin(data_bin, repeats)
        results.append(
            {
                "source_sha256": source_sha256,
                "source_size": source_size,
                **comparison,
            }
        )

    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_VERSION,
        "runner": "top_level_session_target_check.py",
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "platform": platform.platform(),
        "repeats": repeats,
        "timing_order": "balanced alternating buffered/mmap pairs",
        "saves": results,
    }


def _write_report_atomic(report: dict, output: Path, source_saves: list[Path]) -> None:
    output = output.resolve()
    source_paths = {save.resolve() for save in source_saves}
    if output in source_paths:
        raise ValueError("output path aliases a source save")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temp_path = Path(stream.name)
        json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    try:
        temp_path.replace(output)
    except BaseException:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare buffered and mmap top-level GameSession discovery on "
            "operator-owned Anno 1800 saves."
        )
    )
    parser.add_argument("saves", nargs="+", type=Path, help="At least two distinct private .a7s saves")
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        help="Positive even paired timing repeat count (default: 4)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Detached JSON evidence output path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        source_paths = [save.resolve() for save in args.saves]
        output = args.output.resolve()
        if output in set(source_paths):
            raise ValueError("output path aliases a source save")
        report = build_report(args.saves, args.repeats)
        _write_report_atomic(report, args.output, args.saves)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
