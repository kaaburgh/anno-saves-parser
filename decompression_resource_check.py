#!/usr/bin/env python3
"""Bounded private-save resource validation for decompression chunk candidates."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import anno_save_probe as probe
import decompression_target_check as target_check
from decompression import DEFAULT_DECOMPRESSION_CHUNK_BYTES, zlib_to_file as stream_zlib_to_file

SCHEMA = "anno-saves-parser/decompression-resource-check"
SCHEMA_VERSION = 1
REFERENCE_CHUNK_BYTES = 1 << 20
WORKER_COUNTS = (1, 2)
POLL_INTERVAL_SECONDS = 0.02


def _positive_even_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0 or parsed % 2 != 0:
        raise argparse.ArgumentTypeError("value must be a positive even integer")
    return parsed


def _validate_repeats(repeats: int) -> None:
    if repeats <= 0 or repeats % 2 != 0:
        raise ValueError("repeats must be a positive even integer")


def _canonical_bytes(state: dict) -> bytes:
    return json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _worker_result(save: Path, chunk_bytes: int) -> dict:
    original = probe.zlib_to_file

    def selected_decompressor(compressed, dest, progress=None):
        return stream_zlib_to_file(
            compressed,
            dest,
            progress,
            chunk_bytes=chunk_bytes,
        )

    try:
        probe.zlib_to_file = selected_decompressor
        with tempfile.TemporaryDirectory(prefix="anno-decompression-resource-worker-") as td:
            started = time.perf_counter()
            state = probe.canonicalize_save(save, Path(td), None)
            elapsed_seconds = time.perf_counter() - started
    finally:
        probe.zlib_to_file = original

    return {
        "canonical_sha256": hashlib.sha256(_canonical_bytes(state)).hexdigest(),
        "elapsed_seconds": elapsed_seconds,
    }


def _parse_linux_smaps_rollup(text: str) -> int:
    for line in text.splitlines():
        if line.startswith("Pss:"):
            parts = line.split()
            if len(parts) >= 2:
                return int(parts[1]) * 1024
    raise ValueError("Pss field missing from smaps_rollup")


def _linux_pss_bytes(pid: int) -> int:
    return _parse_linux_smaps_rollup(
        Path(f"/proc/{pid}/smaps_rollup").read_text(encoding="utf-8")
    )


def _windows_working_set_bytes(pid: int) -> int:
    from ctypes import wintypes

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")
    try:
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return int(counters.WorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)


def _memory_reader() -> tuple[str, Callable[[int], int]]:
    if sys.platform.startswith("linux"):
        return "pss", _linux_pss_bytes
    if sys.platform == "win32":
        return "working_set", _windows_working_set_bytes
    raise RuntimeError(
        "resource check supports Linux PSS and Windows working-set measurements only"
    )


def _worker_command(snapshot: Path, chunk_bytes: int) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        str(snapshot),
        "--chunk-bytes",
        str(chunk_bytes),
    ]


def _decode_worker_stdout(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("resource worker produced no JSON result")
    return json.loads(lines[-1])


def _run_batch(
    snapshots: list[Path],
    chunk_bytes: int,
    workers: int,
    *,
    popen_factory: Callable = subprocess.Popen,
    sleep_fn: Callable[[float], None] = time.sleep,
    memory_reader: Optional[tuple[str, Callable[[int], int]]] = None,
) -> dict:
    if workers <= 0:
        raise ValueError("workers must be positive")
    if not snapshots:
        raise ValueError("at least one snapshot is required")

    metric, read_memory = memory_reader if memory_reader is not None else _memory_reader()
    pending = list(enumerate(snapshots))
    active: dict[object, int] = {}
    results: list[Optional[dict]] = [None] * len(snapshots)
    peak_memory_bytes = 0
    started = time.perf_counter()

    def start_available() -> None:
        while pending and len(active) < workers:
            index, snapshot = pending.pop(0)
            process = popen_factory(
                _worker_command(snapshot, chunk_bytes),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            active[process] = index

    start_available()
    while active:
        total_memory = 0
        sampled = False
        for process in list(active):
            try:
                total_memory += read_memory(process.pid)
                sampled = True
            except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
                pass
        if sampled:
            peak_memory_bytes = max(peak_memory_bytes, total_memory)

        completed = []
        for process, index in list(active.items()):
            if process.poll() is None:
                continue
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                message = stderr.strip() or stdout.strip() or f"exit {process.returncode}"
                raise RuntimeError(f"resource worker failed: {message}")
            results[index] = _decode_worker_stdout(stdout)
            completed.append(process)
        for process in completed:
            active.pop(process)
        start_available()
        if active:
            sleep_fn(POLL_INTERVAL_SECONDS)

    if peak_memory_bytes <= 0:
        raise RuntimeError("resource worker memory could not be sampled")
    return {
        "canonical_sha256": [result["canonical_sha256"] for result in results if result],
        "elapsed_seconds": time.perf_counter() - started,
        "peak_memory_bytes": peak_memory_bytes,
        "memory_metric": metric,
    }


def _copy_verified_snapshots(saves: list[Path], root: Path) -> tuple[list[Path], list[dict]]:
    if len(saves) < 2:
        raise ValueError("at least two distinct source saves are required")
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    snapshots: list[Path] = []
    identities: list[dict] = []

    for index, save in enumerate(saves):
        source = save.resolve()
        if source in seen_paths:
            raise ValueError("source save paths must be distinct")
        seen_paths.add(source)
        if not source.is_file():
            raise FileNotFoundError(f"save does not exist: {save}")
        work_dir = root / f"source-{index}"
        work_dir.mkdir()
        snapshot, source_sha256, source_size = target_check._copy_verified_snapshot(
            source, work_dir
        )
        if source_sha256 in seen_hashes:
            raise ValueError("source save contents must be distinct")
        seen_hashes.add(source_sha256)
        snapshots.append(snapshot)
        identities.append({"source_sha256": source_sha256, "source_size": source_size})
    return snapshots, identities


def _record_run(target: dict, batch: dict, expected_inputs: int) -> None:
    digests = batch["canonical_sha256"]
    if len(digests) != expected_inputs:
        raise RuntimeError("resource worker result count does not match input count")
    target["elapsed_seconds"].append(batch["elapsed_seconds"])
    target["peak_memory_bytes"].append(batch["peak_memory_bytes"])
    if target["canonical_sha256"] is None:
        target["canonical_sha256"] = digests
    elif digests != target["canonical_sha256"]:
        raise RuntimeError("canonical state changed between repeated resource runs")


def build_report(
    saves: list[Path],
    repeats: int,
    *,
    run_batch_fn: Callable = _run_batch,
) -> dict:
    _validate_repeats(repeats)
    with tempfile.TemporaryDirectory(prefix="anno-decompression-resource-source-") as td:
        snapshots, identities = _copy_verified_snapshots(saves, Path(td))
        results = []
        report_metric: Optional[str] = None
        expected_canonical_sha256: Optional[list[str]] = None
        for workers in WORKER_COUNTS:
            reference = {
                "chunk_bytes": REFERENCE_CHUNK_BYTES,
                "canonical_sha256": None,
                "elapsed_seconds": [],
                "peak_memory_bytes": [],
            }
            candidate = {
                "chunk_bytes": DEFAULT_DECOMPRESSION_CHUNK_BYTES,
                "canonical_sha256": None,
                "elapsed_seconds": [],
                "peak_memory_bytes": [],
            }
            by_chunk = {
                REFERENCE_CHUNK_BYTES: reference,
                DEFAULT_DECOMPRESSION_CHUNK_BYTES: candidate,
            }
            chunks = [REFERENCE_CHUNK_BYTES, DEFAULT_DECOMPRESSION_CHUNK_BYTES]
            for repeat_index in range(repeats):
                order = chunks if repeat_index % 2 == 0 else list(reversed(chunks))
                for chunk_bytes in order:
                    batch = run_batch_fn(snapshots, chunk_bytes, workers)
                    metric = batch["memory_metric"]
                    if report_metric is None:
                        report_metric = metric
                    elif metric != report_metric:
                        raise RuntimeError("resource memory metric changed within one report")
                    _record_run(by_chunk[chunk_bytes], batch, len(snapshots))
            if reference["canonical_sha256"] != candidate["canonical_sha256"]:
                raise RuntimeError(
                    "canonical state differs between reference and candidate resource runs"
                )
            if expected_canonical_sha256 is None:
                expected_canonical_sha256 = reference["canonical_sha256"]
            elif reference["canonical_sha256"] != expected_canonical_sha256:
                raise RuntimeError(
                    "canonical state differs between worker-count configurations"
                )
            results.append(
                {
                    "workers": workers,
                    "reference": reference,
                    "candidate": candidate,
                }
            )

        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "runner": {
                "python_implementation": platform.python_implementation(),
                "python_version": platform.python_version(),
                "platform": platform.platform(),
            },
            "repeats": repeats,
            "worker_counts": list(WORKER_COUNTS),
            "memory_metric": report_metric,
            "inputs": identities,
            "results": results,
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


def _worker_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("save", type=Path)
    parser.add_argument("--chunk-bytes", type=int, required=True)
    args = parser.parse_args(argv)
    if args.chunk_bytes <= 0:
        raise SystemExit("chunk size must be positive")
    result = _worker_result(args.save, args.chunk_bytes)
    print(json.dumps(result, sort_keys=True))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure whole-parser wall time and aggregate worker memory for the historical "
            "1 MiB and candidate 16 KiB decompression chunks on operator-owned saves."
        )
    )
    parser.add_argument("saves", nargs="+", type=Path)
    parser.add_argument("--repeats", type=_positive_even_int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("decompression-resource-check.json"),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--worker":
        _worker_main(args[1:])
        return
    parsed = build_arg_parser().parse_args(args)
    try:
        output = validate_output_path(parsed.output, parsed.saves)
        report = build_report(parsed.saves, parsed.repeats)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    _write_json_atomic(output, report)
    print(output)


if __name__ == "__main__":
    main()
