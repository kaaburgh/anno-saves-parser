#!/usr/bin/env python3
"""Operator-side target validation for lazy canonical session ordering (#36)."""
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
    CANONICAL_SCHEMA,
    CANONICAL_SCHEMA_VERSION,
    _required_rda_member,
    build_canonical_state,
    extract_sessions,
    parse_session,
    rda_entries,
    zlib_to_file,
)
from canonical_sort import sort_canonical_sessions


REPORT_SCHEMA = "anno-saves-parser/canonical-sort-target-check"
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
    """Copy one source save and prove its bytes stayed stable across the snapshot."""
    before = _file_identity(source)
    snapshot = work_dir / "source.a7s"
    shutil.copyfile(source, snapshot)
    snapshot_identity = _file_identity(snapshot)
    after = _file_identity(source)
    if before != snapshot_identity or after != snapshot_identity:
        raise ValueError("source save changed while creating verified snapshot")
    return snapshot, snapshot_identity[0], snapshot_identity[1]


def _validate_repeats(repeats: int) -> None:
    if repeats <= 0 or repeats % 2:
        raise ValueError("repeats must be a positive even integer")


def _prepare_raw_sessions(save: Path, work_dir: Path) -> list[dict]:
    entries = rda_entries(save)
    member = _required_rda_member(entries, save, "data.a7s")
    with save.open("rb") as stream:
        stream.seek(member["offset"])
        compressed = stream.read(member["compressed_size"])
    if member["flags"] & 0x1:
        compressed = zlib.decompress(compressed)

    data_bin = work_dir / "data.bin"
    zlib_to_file(compressed, data_bin)
    descriptors = extract_sessions(data_bin)
    if not descriptors:
        raise ValueError("no GameSession descriptors recognized")

    parsed_sessions = []
    for descriptor in descriptors:
        current = dict(descriptor)
        binary_offset = current.pop("binary_offset")
        binary_size = current["binary_size"]
        parsed = parse_session(
            data_bin,
            base_offset=binary_offset,
            blob_size=binary_size,
        )
        parsed_sessions.append({**current, **parsed})
    return parsed_sessions


def _project_sessions(raw_sessions: list[dict]) -> list[dict]:
    """Project sessions one at a time so production multi-session ordering is excluded."""
    return [
        build_canonical_state("target.a7s", [raw])["sessions"][0]
        for raw in raw_sessions
    ]


def _eager_reference_key(session: dict) -> tuple:
    guid = session.get("session_guid")
    session_id = session.get("session_id")
    return (
        guid is None,
        guid if guid is not None else 0,
        session_id is None,
        session_id if session_id is not None else 0,
        session.get("map") or "",
        json.dumps(
            session,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
    )


def _canonical_state_from_sessions(sessions: list[dict]) -> dict:
    return {
        "schema": CANONICAL_SCHEMA,
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "source": {"save_name": "target.a7s"},
        "sessions": sessions,
    }


def _canonical_digest(state: dict) -> str:
    payload = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timed_sort(sorter: Callable[[list[dict]], list[dict]], sessions: list[dict]) -> tuple[list[dict], float]:
    started = time.perf_counter()
    ordered = sorter(list(sessions))
    return ordered, time.perf_counter() - started


def compare_projected_sessions(
    sessions: list[dict], repeats: int = DEFAULT_REPEATS
) -> dict:
    """Compare retained eager ordering with the lazy helper on projected sessions."""
    _validate_repeats(repeats)

    reference_times: list[float] = []
    candidate_times: list[float] = []
    reference_expected: list[dict] | None = None
    candidate_expected: list[dict] | None = None

    def reference(items: list[dict]) -> list[dict]:
        return sorted(items, key=_eager_reference_key)

    def candidate(items: list[dict]) -> list[dict]:
        return sort_canonical_sessions(items)

    for repeat in range(repeats):
        order = (
            (("reference", reference), ("candidate", candidate))
            if repeat % 2 == 0
            else (("candidate", candidate), ("reference", reference))
        )
        for label, sorter in order:
            ordered, elapsed = _timed_sort(sorter, sessions)
            if label == "reference":
                reference_times.append(elapsed)
                if reference_expected is None:
                    reference_expected = ordered
                elif ordered != reference_expected:
                    raise ValueError("eager canonical session ordering is nondeterministic")
            else:
                candidate_times.append(elapsed)
                if candidate_expected is None:
                    candidate_expected = ordered
                elif ordered != candidate_expected:
                    raise ValueError("lazy canonical session ordering is nondeterministic")

    assert reference_expected is not None
    assert candidate_expected is not None
    if candidate_expected != reference_expected:
        raise ValueError("lazy canonical session ordering differs from eager reference")

    state = _canonical_state_from_sessions(reference_expected)
    return {
        "session_count": len(reference_expected),
        "canonical_sha256": _canonical_digest(state),
        "reference_ordering_seconds": reference_times,
        "candidate_ordering_seconds": candidate_times,
    }


def compare_raw_sessions(
    raw_sessions: list[dict], repeats: int = DEFAULT_REPEATS
) -> dict:
    """Check target projection/order equality without relying on production multi-session sort."""
    _validate_repeats(repeats)
    production = build_canonical_state("target.a7s", raw_sessions)
    projected = _project_sessions(raw_sessions)
    comparison = compare_projected_sessions(projected, repeats)
    candidate = _canonical_state_from_sessions(sort_canonical_sessions(projected))
    if candidate != production:
        raise ValueError("lazy canonical state differs from current production canonical state")
    if _canonical_digest(candidate) != comparison["canonical_sha256"]:
        raise ValueError("canonical digest mismatch inside target-check harness")
    return comparison


def build_report(saves: list[Path], repeats: int = DEFAULT_REPEATS) -> dict:
    """Run the bounded comparison on operator-owned saves without returning paths."""
    _validate_repeats(repeats)
    if len(saves) < 2:
        raise ValueError("target validation requires at least two saves")

    results = []
    for save in saves:
        resolved = save.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"save does not exist: {save}")
        if resolved.suffix.lower() != ".a7s":
            raise ValueError(f"not an .a7s save: {save}")
        with tempfile.TemporaryDirectory(prefix="anno-canonical-sort-target-check-") as temp:
            work_dir = Path(temp)
            snapshot, source_sha256, source_size = _copy_verified_snapshot(resolved, work_dir)
            raw_sessions = _prepare_raw_sessions(snapshot, work_dir)
            comparison = compare_raw_sessions(raw_sessions, repeats)
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
        "runner": "canonical_sort_target_check.py",
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "platform": platform.platform(),
        "repeats": repeats,
        "timing_order": "balanced alternating eager/lazy ordering pairs",
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
            "Compare current eager and candidate lazy canonical session ordering "
            "on operator-owned Anno 1800 saves."
        )
    )
    parser.add_argument("saves", nargs="+", type=Path, help="At least two private .a7s saves")
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        help="Positive even paired ordering-timing repeat count (default: 4)",
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
