#!/usr/bin/env python3
"""Dependency-free Anno 1800 .a7s semantic probe.

Prototype: RDA v2.2 -> outer data.a7s -> zlib -> FileDB/BBDom v3 ->
embedded GameSessions -> player-owned area building snapshots -> semantic diffs.

It intentionally extracts only a small canonical subset. No game files or external
Anno tools are required.
"""
from __future__ import annotations

import argparse
import gzip
import json
import mmap
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import unicodedata
import zlib
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import date, datetime
from difflib import get_close_matches
from pathlib import Path
from typing import BinaryIO, Optional

from guid_mapping import GuidMappingError, enrich_structural_diff, load_guid_mapping

__version__ = "0.4.0"

CANONICAL_SCHEMA = "anno-saves-parser/canonical-state"
CANONICAL_SCHEMA_VERSION = 1
RDA_MAGIC = b"Resource File V2.2"
BBDOM_V3_MAGIC = bytes.fromhex("08000000fdffffff")
PAD_BLOCK = 8
AREA_RE = re.compile(r"^AreaManager_(\d+)$")
PARALLEL_RAM_ESTIMATE_BYTES = 384 * 1024 * 1024
PARALLEL_TEMP_ESTIMATE_BYTES = 320 * 1024 * 1024
WINDOWS_PROCESS_WORKER_LIMIT = 61

INTERESTING_COMPONENTS = {
    "Building", "Residence7", "Factory7", "BuildingModule", "Warehouse",
    "ModuleOwner", "HarborBuilding", "PassiveTradeBuilding", "Powerplant",
    "ItemContainer", "Guildhouse", "TrainOwner", "LogisticNode",
}


def _enable_windows_vt(stream) -> bool:
    """Enable and verify Windows virtual-terminal processing for a console stream."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        if handle == -1:
            return False
        kernel32 = ctypes.windll.kernel32
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)):
            return False
        vt_flag = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if not mode.value & vt_flag:
            if not kernel32.SetConsoleMode(ctypes.c_void_p(handle), mode.value | vt_flag):
                return False
            verified = ctypes.c_uint()
            if not kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(verified)):
                return False
            return bool(verified.value & vt_flag)
        return True
    except (AttributeError, ImportError, OSError, ValueError):
        return False


def _supports_in_place_rendering(stream) -> bool:
    if not bool(getattr(stream, "isatty", lambda: False)()):
        return False
    if os.name == "nt":
        return _enable_windows_vt(stream)
    term = os.environ.get("TERM", "").strip().casefold()
    return term not in {"", "dumb", "unknown"}


class Progress:
    """CLI progress reporter with in-place per-save rendering when the TTY supports it."""

    CLEAR_LINE = "\r\x1b[2K"
    CURSOR_UP = "\x1b[1A"

    def __init__(
        self,
        interval: float = 1.0,
        stream=None,
        interactive: Optional[bool] = None,
        terminal_width: Optional[int] = None,
    ):
        self.interval = interval
        self.stream = stream if stream is not None else sys.stdout
        self.interactive = (
            _supports_in_place_rendering(self.stream)
            if interactive is None
            else interactive
        )
        self.terminal_width = terminal_width
        self.last_emit = 0.0
        self._parse_active = False
        self._parse_header = ""
        self._rendered_header = ""
        self._rendered_detail = ""

    @staticmethod
    def _cell_width(char: str) -> int:
        category = unicodedata.category(char)
        if category.startswith("C") or unicodedata.combining(char):
            return 0
        if ord(char) < 128:
            return 1
        # Be conservative for non-ASCII glyphs: terminals disagree on ambiguous
        # width, and over-counting only truncates earlier while under-counting
        # can make the live line wrap and corrupt cursor accounting.
        return 2

    @classmethod
    def _display_clusters(cls, text: str) -> list[tuple[str, int]]:
        clusters: list[str] = []
        current = ""
        for char in text:
            joins_current = (
                bool(current)
                and (
                    unicodedata.combining(char)
                    or char in {"\ufe0e", "\ufe0f", "\u20e3", "\u200d"}
                    or current.endswith("\u200d")
                )
            )
            if joins_current:
                current += char
            else:
                if current:
                    clusters.append(current)
                current = char
        if current:
            clusters.append(current)

        result = []
        for cluster in clusters:
            if "\ufe0f" in cluster or "\u20e3" in cluster or "\u200d" in cluster:
                width = 2
            else:
                width = sum(cls._cell_width(char) for char in cluster)
            result.append((cluster, width))
        return result

    @classmethod
    def _display_width(cls, text: str) -> int:
        return sum(width for _, width in cls._display_clusters(text))

    def _write_line(self, message: str) -> None:
        self.stream.write(f"{message}\n")
        self.stream.flush()

    def _terminal_columns(self) -> int:
        columns = self.terminal_width
        if columns is None:
            columns = shutil.get_terminal_size(fallback=(120, 24)).columns
        return max(int(columns), 1)

    def _fit_live_line(self, message: str, columns: Optional[int] = None) -> str:
        """Prevent live output from wrapping and breaking cursor accounting."""
        message = "".join(
            " " if unicodedata.category(char).startswith("C") else char
            for char in message
        )
        if columns is None:
            columns = self._terminal_columns()
        width = max(int(columns) - 1, 1)
        if self._display_width(message) <= width:
            return message

        suffix = "..."
        if width <= len(suffix):
            return "." * width
        budget = width - len(suffix)
        out = []
        used = 0
        for cluster, cluster_width in self._display_clusters(message):
            if used + cluster_width > budget:
                break
            out.append(cluster)
            used += cluster_width
        return "".join(out) + suffix

    @classmethod
    def _physical_rows(cls, text: str, columns: int) -> int:
        """Rows occupied by previously rendered text after a terminal resize."""
        if not text:
            return 1
        columns = max(int(columns), 1)
        rows = 1
        used = 0
        for _, cluster_width in cls._display_clusters(text):
            if cluster_width <= 0:
                continue
            if used and used + cluster_width > columns:
                rows += 1
                used = 0
            if cluster_width > columns:
                extra_rows, remainder = divmod(cluster_width, columns)
                rows += extra_rows
                if remainder == 0:
                    rows -= 1
                    used = columns
                else:
                    used = remainder
            else:
                used += cluster_width
        return rows

    def _erase_parse_block(self, columns: int) -> None:
        """Erase the current header/detail block, accounting for resize reflow."""
        detail_rows = self._physical_rows(self._rendered_detail, columns)
        header_rows = self._physical_rows(self._rendered_header, columns)

        self.stream.write(self.CLEAR_LINE)
        for _ in range(detail_rows - 1):
            self.stream.write(f"{self.CURSOR_UP}{self.CLEAR_LINE}")
        for _ in range(header_rows):
            self.stream.write(f"{self.CURSOR_UP}{self.CLEAR_LINE}")

    def _render_detail(self, message: str) -> None:
        columns = self._terminal_columns()
        self._erase_parse_block(columns)
        header = self._fit_live_line(self._parse_header, columns)
        detail = self._fit_live_line(message, columns)
        self.stream.write(f"{header}\n{detail}")
        self.stream.flush()
        self._rendered_header = header
        self._rendered_detail = detail

    def _replace_parse_block(self, summary: str) -> None:
        columns = self._terminal_columns()
        self._erase_parse_block(columns)
        self.stream.write(f"{self._fit_live_line(summary, columns)}\n")
        self.stream.flush()

    def say(self, message: str) -> None:
        if self.interactive and self._parse_active:
            self._render_detail(message)
        else:
            self._write_line(message)
        self.last_emit = time.monotonic()

    def maybe(self, message: str) -> None:
        now = time.monotonic()
        if now - self.last_emit >= self.interval:
            if self.interactive and self._parse_active:
                self._render_detail(message)
            else:
                self._write_line(message)
            self.last_emit = now

    def begin_parse(self, header: str) -> None:
        if self._parse_active:
            raise RuntimeError("a parse progress block is already active")
        self._parse_active = True
        self._parse_header = header
        self._rendered_detail = ""
        if self.interactive:
            columns = self._terminal_columns()
            self._rendered_header = self._fit_live_line(header, columns)
            self._write_line(self._rendered_header)
        else:
            self._rendered_header = ""
            self._write_line(header)
        self.last_emit = time.monotonic()

    def _close_parse(self) -> None:
        self._parse_active = False
        self._parse_header = ""
        self._rendered_header = ""
        self._rendered_detail = ""
        self.last_emit = time.monotonic()

    def finish_parse(self, summary: str) -> None:
        if not self._parse_active:
            self.say(summary)
            return
        if self.interactive:
            self._replace_parse_block(summary)
        else:
            self._write_line(summary)
        self._close_parse()

    def abort_parse(self, summary: str) -> None:
        """Close the live block cleanly before an exception is re-raised."""
        if not self._parse_active:
            return
        if self.interactive:
            self._replace_parse_block(summary)
        else:
            self._write_line(summary)
        self._close_parse()


SAVE_META_CACHE: dict[Path, dict] = {}


def _u32(b: bytes) -> int:
    return int.from_bytes(b, "little", signed=False)


def _decode_utf16(raw: bytes) -> str:
    return raw.decode("utf-16le", errors="replace").rstrip("\x00")


def _padded(n: int) -> int:
    return ((n + PAD_BLOCK - 1) // PAD_BLOCK) * PAD_BLOCK


def _decode_position(raw: bytes) -> Optional[list[float]]:
    """Decode the observed root GameObject Position encoding conservatively."""
    if len(raw) != 12:
        return None
    values = struct.unpack("<fff", raw)
    if not all(float("-inf") < value < float("inf") for value in values):
        return None
    return list(values)


def _decode_direction(raw: bytes) -> Optional[float]:
    """Decode the observed root GameObject Direction encoding conservatively."""
    if len(raw) != 4:
        return None
    value = struct.unpack("<f", raw)[0]
    if not float("-inf") < value < float("inf"):
        return None
    return value


def rda_entries(path: Path) -> list[dict]:
    """Read RDA v2.2 directory entries without extracting the whole archive."""
    entries: list[dict] = []
    with path.open("rb") as f:
        magic = f.read(len(RDA_MAGIC))
        if magic != RDA_MAGIC:
            raise ValueError(f"{path}: unsupported RDA magic {magic!r}")
        f.seek(766, 1)
        first_block = struct.unpack("<Q", f.read(8))[0]
        block = first_block
        while block < path.stat().st_size:
            f.seek(block)
            flags, count = struct.unpack("<II", f.read(8))
            directory_size, decompressed_size, next_block = struct.unpack("<QQQ", f.read(24))
            if flags & 0x8:  # deleted block
                block = next_block
                continue
            if flags & 0x6:  # encrypted/memory-resident not expected in save outer archive
                raise ValueError(f"{path}: unsupported outer RDA block flags {flags:#x}")
            f.seek(block - directory_size)
            directory = f.read(directory_size)
            if flags & 0x1:
                directory = zlib.decompress(directory)
            if len(directory) != decompressed_size:
                raise ValueError(f"{path}: bad RDA directory size")
            off = 0
            for _ in range(count):
                name_raw = directory[off:off+520]; off += 520
                name = name_raw.decode("utf-16le", errors="replace").replace("\x00", "")
                data_offset, compressed, filesize, timestamp, unknown = struct.unpack_from("<QQQQQ", directory, off)
                off += 40
                entries.append({
                    "name": name, "offset": data_offset, "compressed_size": compressed,
                    "size": filesize, "flags": flags, "timestamp": timestamp,
                })
            if next_block <= block:
                break
            block = next_block
    return entries


def extract_rda_member(path: Path, name: str) -> bytes:
    entries = rda_entries(path)
    e = next((x for x in entries if x["name"] == name), None)
    if e is None:
        raise KeyError(f"{name} not found in {path}")
    with path.open("rb") as f:
        f.seek(e["offset"])
        raw = f.read(e["compressed_size"])
    if e["flags"] & 0x1:
        raw = zlib.decompress(raw)
    return raw


def zlib_to_file(compressed: bytes, dest: Path, progress: Optional[Progress] = None) -> int:
    dec = zlib.decompressobj()
    total = 0
    with dest.open("wb") as out:
        mv = memoryview(compressed)
        size = len(mv)
        for i in range(0, size, 1 << 20):
            chunk = dec.decompress(mv[i:i+(1 << 20)])
            out.write(chunk); total += len(chunk)
            if progress is not None:
                done = min(i + (1 << 20), size)
                progress.maybe(
                    f"    [data] decompressing {100.0 * done / max(size, 1):5.1f}% "
                    f"({done / 1048576:.1f}/{size / 1048576:.1f} MiB input; "
                    f"{total / 1048576:.1f} MiB output)"
                )
        chunk = dec.flush(); out.write(chunk); total += len(chunk)
    return total


def _read_dictionary(f: BinaryIO, offset: int) -> dict[int, str]:
    f.seek(offset)
    count_raw = f.read(4)
    if len(count_raw) != 4:
        raise ValueError("bad dictionary offset")
    count = struct.unpack("<i", count_raw)[0]
    ids = struct.unpack("<" + "H" * count, f.read(2 * count)) if count else ()
    result: dict[int, str] = {}
    for ident in ids:
        b = bytearray()
        while True:
            c = f.read(1)
            if not c or c == b"\x00":
                break
            b += c
        result[ident] = b.decode("utf-8", errors="replace")
    return result


def bb_meta(path: Path) -> tuple[int, int, dict[int, str], dict[int, str]]:
    file_size = path.stat().st_size
    if file_size < 16:
        raise ValueError("truncated FileDB trailer")
    with path.open("rb") as f:
        f.seek(file_size - 16)
        trailer = f.read(16)
        if len(trailer) != 16:
            raise ValueError("truncated FileDB trailer")
        tags_off, attrs_off = struct.unpack("<ii", trailer[:8])
        if trailer[8:] != BBDOM_V3_MAGIC:
            raise ValueError(f"{path}: not FileDB/BBDom v3")
        data_limit = file_size - 16
        if not (0 <= tags_off < data_limit and 0 <= attrs_off < data_limit):
            raise ValueError("FileDB dictionary offset outside file")
        tags = _read_dictionary_at(f, 0, tags_off, data_limit)
        attrs = _read_dictionary_at(f, 0, attrs_off, data_limit)
    return tags_off, attrs_off, tags, attrs


def _read_attr(f: BinaryIO, size: int) -> bytes:
    raw = f.read(_padded(size))
    return raw[:size]


def _ids_named(dictionary: dict[int, str], name: str) -> set[int]:
    return {ident for ident, value in dictionary.items() if value == name}


def _entry_tag_ids(tags: dict[int, str]) -> set[int]:
    """Return tag IDs that the legacy name-based scanner resolves as ``#1``."""
    result = _ids_named(tags, "#1")
    if 1 not in tags:
        result.add(1)
    return result


def _read_dictionary_at(
    f: BinaryIO, base_offset: int, offset: int, limit_offset: int
) -> dict[int, str]:
    absolute_limit = base_offset + limit_offset
    f.seek(base_offset + offset)

    def read_exact(size: int) -> bytes:
        if size < 0 or f.tell() + size > absolute_limit:
            raise ValueError("dictionary exceeds FileDB slice")
        raw = f.read(size)
        if len(raw) != size:
            raise ValueError("truncated dictionary")
        return raw

    count = struct.unpack("<i", read_exact(4))[0]
    if count < 0:
        raise ValueError("negative dictionary entry count")
    ids_raw = read_exact(2 * count)
    ids = struct.unpack("<" + "H" * count, ids_raw) if count else ()
    result: dict[int, str] = {}
    for ident in ids:
        b = bytearray()
        while True:
            if f.tell() >= absolute_limit:
                raise ValueError("dictionary string exceeds FileDB slice")
            c = read_exact(1)
            if c == b"\x00":
                break
            b += c
        result[ident] = b.decode("utf-8", errors="replace")
    return result

def _filedb_slice_meta(
    path: Path, base_offset: int, blob_size: int
) -> tuple[int, int, dict[int, str], dict[int, str]]:
    """Read FileDB v3 metadata whose offsets are relative to a bounded file slice."""
    if base_offset < 0 or blob_size < 16:
        raise ValueError("invalid FileDB slice bounds")
    file_size = path.stat().st_size
    if base_offset + blob_size > file_size:
        raise ValueError("FileDB slice exceeds source file")
    with path.open("rb") as f:
        f.seek(base_offset + blob_size - 16)
        trailer = f.read(16)
        if len(trailer) != 16:
            raise ValueError("truncated FileDB trailer")
        tags_off, attrs_off = struct.unpack("<ii", trailer[:8])
        if trailer[8:] != BBDOM_V3_MAGIC:
            raise ValueError(f"{path}: not FileDB/BBDom v3")
        data_limit = blob_size - 16
        if not (0 <= tags_off < data_limit and 0 <= attrs_off < data_limit):
            raise ValueError("FileDB dictionary offset outside slice")
        tags = _read_dictionary_at(f, base_offset, tags_off, data_limit)
        attrs = _read_dictionary_at(f, base_offset, attrs_off, data_limit)
    return tags_off, attrs_off, tags, attrs


def extract_sessions(
    meta_data_bin: Path,
    session_dir: Optional[Path] = None,
    progress: Optional[Progress] = None,
) -> list[dict]:
    """Locate embedded BBDom session blobs without copying them to temp files."""
    # ``session_dir`` remains accepted for internal/backward compatibility, but
    # sessions are now represented as bounded offsets into meta_data_bin.
    del session_dir
    tags_off, _, tags, attrs = bb_meta(meta_data_bin)
    entry_ids = _entry_tag_ids(tags)
    game_sessions_ids = _ids_named(tags, "GameSessions")
    session_data_ids = _ids_named(tags, "SessionData")
    session_desc_ids = _ids_named(tags, "SessionDesc")
    binary_data_ids = _ids_named(attrs, "BinaryData")
    session_guid_ids = _ids_named(attrs, "SessionGUID")
    session_id_ids = _ids_named(attrs, "SessionID")
    session_map_ids = _ids_named(attrs, "SessionMap")

    sessions: list[dict] = []
    stack: list[int] = []
    current: Optional[dict] = None
    index = -1
    operations = 0
    next_progress = 10000

    with meta_data_bin.open("rb") as f:
        pos = 0
        while pos < tags_off:
            hdr = f.read(8)
            if len(hdr) != 8:
                raise EOFError("top-level FileDB record header truncated")
            size, raw_id = struct.unpack("<ii", hdr)
            pos += 8
            operations += 1
            if progress is not None and operations == next_progress:
                progress.maybe(
                    f"    [sessions] scanning {100.0 * pos / max(tags_off, 1):5.1f}% "
                    f"sessions_found={len(sessions) + (1 if current is not None else 0)}"
                )
                next_progress += 10000

            ident = raw_id & 0xFFFF
            if ident == 0:
                if stack:
                    popped = stack.pop()
                    if (
                        popped in entry_ids
                        and stack
                        and stack[-1] in game_sessions_ids
                        and current is not None
                    ):
                        sessions.append(current)
                        current = None
                continue

            if ident < 32768:
                stack.append(ident)
                if (
                    ident in entry_ids
                    and len(stack) >= 2
                    and stack[-2] in game_sessions_ids
                ):
                    index += 1
                    current = {"index": index}
                continue

            if size < 0:
                raise ValueError("negative top-level FileDB attribute size")
            padded = _padded(size)
            value_offset = f.tell()
            if value_offset + padded > tags_off:
                raise EOFError("top-level FileDB attribute payload truncated")

            is_session_blob = (
                ident in binary_data_ids
                and len(stack) >= 3
                and stack[-1] in session_data_ids
                and stack[-2] in entry_ids
                and stack[-3] in game_sessions_ids
            )
            if is_session_blob:
                if current is not None:
                    current["binary_offset"] = value_offset
                    current["binary_size"] = size
                f.seek(padded, 1)
                pos += padded
                continue

            descriptor_attr = (
                current is not None
                and len(stack) >= 4
                and stack[-1] in session_desc_ids
                and stack[-2] in entry_ids
                and (
                    ident in session_guid_ids
                    or ident in session_id_ids
                    or ident in session_map_ids
                )
            )
            if descriptor_attr:
                raw = _read_attr(f, size)
                if ident in session_guid_ids:
                    current["guid"] = _u32(raw)
                elif ident in session_id_ids:
                    current["id"] = _u32(raw)
                elif ident in session_map_ids:
                    current["map"] = _decode_utf16(raw)
            else:
                f.seek(padded, 1)
            pos += padded

    for session in sessions:
        if "binary_offset" not in session or "binary_size" not in session:
            raise ValueError("GameSession descriptor is missing BinaryData")
    return sessions


def parse_session(
    path: Path,
    progress: Optional[Progress] = None,
    *,
    base_offset: int = 0,
    blob_size: Optional[int] = None,
) -> dict:
    """Extract area ownership and building state from one bounded GameSession blob."""
    if blob_size is None:
        blob_size = path.stat().st_size - base_offset
    tags_off, _, tags, attrs = _filedb_slice_meta(path, base_offset, blob_size)

    entry_ids = _entry_tag_ids(tags)
    game_session_manager_ids = _ids_named(tags, "GameSessionManager")
    area_info_ids = _ids_named(tags, "AreaInfo")
    owner_ids = _ids_named(tags, "Owner")
    passive_trade_ids = _ids_named(tags, "PassiveTrade")
    game_object_ids = _ids_named(tags, "GameObject")
    objects_ids = _ids_named(tags, "objects")
    component_by_id = {
        ident: name for ident, name in tags.items() if name in INTERESTING_COMPONENTS
    }
    area_by_tag = {}
    for ident, name in tags.items():
        match = AREA_RE.match(name)
        if match:
            area_by_tag[ident] = int(match.group(1))

    owner_id_attrs = _ids_named(attrs, "id")
    area_id_attrs = _ids_named(attrs, "AreaID")
    city_name_guid_attrs = _ids_named(attrs, "CityNameGuid")
    city_name_iterator_attrs = _ids_named(attrs, "CityNameIterator")
    object_id_attrs = _ids_named(attrs, "ID")
    guid_attrs = _ids_named(attrs, "guid")
    position_attrs = _ids_named(attrs, "Position")
    direction_attrs = _ids_named(attrs, "Direction")
    rotation_attrs = _ids_named(attrs, "Rotation90") | _ids_named(attrs, "Rotation")

    stack: list[int] = []
    area_infos: list[dict] = []
    current_area_info: Optional[dict] = None
    area_info_depth = -1
    current_object: Optional[dict] = None
    object_depth = -1
    all_objects: list[dict] = []
    current_area_id: Optional[int] = None
    area_depth = -1
    operations = 0
    next_progress = 10000

    granularity = mmap.ALLOCATIONGRANULARITY
    map_offset = (base_offset // granularity) * granularity
    delta = base_offset - map_offset
    map_length = delta + blob_size

    with path.open("rb") as f:
        with mmap.mmap(
            f.fileno(), map_length, access=mmap.ACCESS_READ, offset=map_offset
        ) as mapped:
            pos = 0
            while pos < tags_off:
                if pos + 8 > tags_off:
                    raise EOFError("session FileDB record header truncated")
                size, raw_id = struct.unpack_from("<ii", mapped, delta + pos)
                pos += 8
                operations += 1
                if progress is not None and operations == next_progress:
                    progress.maybe(
                        f"      scanning {100.0 * pos / max(tags_off, 1):5.1f}% "
                        f"objects={len(all_objects):,} areas={len(area_infos):,}"
                    )
                    next_progress += 10000

                ident = raw_id & 0xFFFF
                if ident == 0:
                    if stack:
                        popped = stack.pop()
                        depth = len(stack)
                        if current_object is not None and depth < object_depth:
                            if (
                                current_object.get("id") is not None
                                and current_object.get("guid") is not None
                            ):
                                all_objects.append(current_object)
                            current_object = None
                            object_depth = -1
                        if (
                            current_area_info is not None
                            and popped in entry_ids
                            and stack
                            and stack[-1] in area_info_ids
                        ):
                            area_infos.append(current_area_info)
                            current_area_info = None
                            area_info_depth = -1
                        if current_area_id is not None and depth < area_depth:
                            current_area_id = None
                            area_depth = -1
                    continue

                if ident < 32768:
                    stack.append(ident)
                    depth = len(stack)
                    if ident in area_by_tag:
                        current_area_id = area_by_tag[ident]
                        area_depth = depth
                    if (
                        ident in entry_ids
                        and depth >= 3
                        and stack[-2] in area_info_ids
                        and stack[-3] in game_session_manager_ids
                    ):
                        current_area_info = {}
                        area_info_depth = depth
                    if (
                        ident in entry_ids
                        and depth >= 6
                        and stack[-2] in objects_ids
                        and stack[-3] in game_object_ids
                        and current_area_id is not None
                    ):
                        current_object = {
                            "area_id": current_area_id,
                            "components": [],
                        }
                        object_depth = depth
                    elif current_object is not None and depth == object_depth + 1:
                        component = component_by_id.get(ident)
                        if component is not None:
                            current_object["components"].append(component)
                    continue

                if size < 0:
                    raise ValueError("negative session FileDB attribute size")
                padded = _padded(size)
                value_offset = pos
                pos += padded
                if pos > tags_off:
                    raise EOFError("session FileDB attribute payload truncated")
                depth = len(stack)
                mapped_offset = delta + value_offset

                if current_area_info is not None:
                    relative_depth = depth - area_info_depth
                    if relative_depth == 0:
                        if ident in city_name_guid_attrs:
                            current_area_info["CityNameGuid"] = _u32(
                                mapped[mapped_offset:mapped_offset + size]
                            )
                        elif ident in city_name_iterator_attrs:
                            current_area_info["CityNameIterator"] = _u32(
                                mapped[mapped_offset:mapped_offset + size]
                            )
                    elif relative_depth == 1:
                        parent = stack[-1]
                        if parent in owner_ids and ident in owner_id_attrs:
                            current_area_info["owner_id"] = _u32(
                                mapped[mapped_offset:mapped_offset + size]
                            )
                        elif parent in passive_trade_ids and ident in area_id_attrs:
                            current_area_info["area_id"] = _u32(
                                mapped[mapped_offset:mapped_offset + size]
                            )

                if current_object is not None and depth == object_depth:
                    if ident in object_id_attrs:
                        current_object["id"] = int.from_bytes(
                            mapped[mapped_offset:mapped_offset + size],
                            "little",
                            signed=False,
                        )
                    elif ident in guid_attrs:
                        current_object["guid"] = _u32(
                            mapped[mapped_offset:mapped_offset + size]
                        )
                    elif ident in position_attrs:
                        decoded = _decode_position(
                            mapped[mapped_offset:mapped_offset + size]
                        )
                        if decoded is not None:
                            current_object["position"] = decoded
                    elif ident in direction_attrs:
                        decoded = _decode_direction(
                            mapped[mapped_offset:mapped_offset + size]
                        )
                        if decoded is not None:
                            current_object["direction"] = decoded
                    elif ident in rotation_attrs and size <= 4:
                        current_object["rotation"] = _u32(
                            mapped[mapped_offset:mapped_offset + size]
                        )

    owner_by_area = {
        area["area_id"]: area.get("owner_id")
        for area in area_infos
        if "area_id" in area
    }
    player_area_ids = sorted(
        area_id for area_id, owner in owner_by_area.items() if owner == 0
    )
    player_set = set(player_area_ids)

    player_buildings = []
    for obj in all_objects:
        if obj["area_id"] not in player_set:
            continue
        components = set(obj["components"])
        if "Building" not in components and not components.intersection(
            {"Residence7", "Factory7", "Warehouse", "BuildingModule"}
        ):
            continue
        obj["components"] = sorted(components)
        player_buildings.append(obj)

    buildings_by_area = {area_id: [] for area_id in player_area_ids}
    for obj in player_buildings:
        buildings_by_area[obj["area_id"]].append(obj)
    info_by_area = {
        area["area_id"]: area for area in area_infos if "area_id" in area
    }

    area_summaries = {}
    for area_id in player_area_ids:
        objs = buildings_by_area[area_id]
        kinds = Counter()
        guids = Counter()
        for obj in objs:
            guids[obj["guid"]] += 1
            components = set(obj["components"])
            if "Residence7" in components:
                kinds["residence"] += 1
            if "Factory7" in components:
                kinds["factory"] += 1
            if "Warehouse" in components:
                kinds["warehouse"] += 1
            if "BuildingModule" in components:
                kinds["module"] += 1
            if "Building" in components:
                kinds["building"] += 1
        info = info_by_area.get(area_id, {})
        area_summaries[str(area_id)] = {
            "owner_id": 0,
            "city_name_guid": info.get("CityNameGuid"),
            "city_name_iterator": info.get("CityNameIterator"),
            "building_objects": len(objs),
            "kind_counts": dict(kinds),
            "guid_counts": {str(key): value for key, value in sorted(guids.items())},
        }

    return {
        "player_area_ids": player_area_ids,
        "areas": area_summaries,
        "player_buildings": player_buildings,
        "total_game_objects": len(all_objects),
    }

def _canonical_building(obj: dict) -> dict:
    building = {
        "area_id": obj["area_id"],
        "id": obj["id"],
        "guid": obj["guid"],
        "components": sorted(set(obj.get("components", []))),
    }
    for field in ("position", "direction", "rotation"):
        if field in obj and obj[field] is not None:
            value = obj[field]
            building[field] = list(value) if field == "position" else value
    return building


def _canonical_session_sort_key(session: dict) -> tuple:
    """Order sessions independently of raw extraction order, even on identity ties."""
    guid = session.get("session_guid")
    session_id = session.get("session_id")
    state_tiebreaker = json.dumps(
        session,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return (
        guid is None,
        guid if guid is not None else 0,
        session_id is None,
        session_id if session_id is not None else 0,
        session.get("map") or "",
        state_tiebreaker,
    )


def build_canonical_state(source_name: str, parsed_sessions: list[dict]) -> dict:
    """Normalize parser-internal session dictionaries into canonical schema v1."""
    sessions = []
    for raw in parsed_sessions:
        session = {
            "session_guid": raw.get("guid"),
            "session_id": raw.get("id"),
            "player_areas": [],
            "buildings": [],
        }
        if raw.get("map") is not None:
            session["map"] = raw["map"]

        area_summaries = raw.get("areas", {})
        for area_id in sorted(raw.get("player_area_ids", [])):
            info = area_summaries.get(str(area_id), {})
            area = {"area_id": area_id, "owner_id": 0}
            if info.get("city_name_guid") is not None:
                area["city_name_guid"] = info["city_name_guid"]
            if info.get("city_name_iterator") is not None:
                area["city_name_iterator"] = info["city_name_iterator"]
            session["player_areas"].append(area)

        buildings = [_canonical_building(obj) for obj in raw.get("player_buildings", [])]
        session["buildings"] = sorted(
            buildings,
            key=lambda obj: (obj["area_id"], obj["id"], obj["guid"]),
        )
        sessions.append(session)

    sessions.sort(key=_canonical_session_sort_key)
    return {
        "schema": CANONICAL_SCHEMA,
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "source": {"save_name": source_name},
        "sessions": sessions,
    }


def _require_canonical_v1(state: dict) -> None:
    if (
        state.get("schema") != CANONICAL_SCHEMA
        or state.get("schema_version") != CANONICAL_SCHEMA_VERSION
    ):
        raise ValueError(
            "structural diff requires canonical state schema "
            f"{CANONICAL_SCHEMA!r} version {CANONICAL_SCHEMA_VERSION}"
        )


def canonicalize_save(save: Path, work_dir: Path, progress: Optional[Progress] = None) -> dict:
    if progress is not None:
        progress.say(f"  [rda] reading archive directory ({save.stat().st_size / 1048576:.2f} MiB)")
    outer = rda_entries(save)
    data_member = next(x for x in outer if x["name"] == "data.a7s")
    if progress is not None:
        names = ", ".join(e["name"] for e in outer)
        progress.say(
            f"  [rda] {len(outer)} members: {names}; "
            f"data.a7s={data_member['compressed_size'] / 1048576:.2f} MiB"
        )
        progress.say("  [data] reading + decompressing data.a7s")
    # Avoid a second RDA directory scan: use the member descriptor we already have.
    with save.open("rb") as f:
        f.seek(data_member["offset"])
        compressed_data = f.read(data_member["compressed_size"])
    if data_member["flags"] & 0x1:
        compressed_data = zlib.decompress(compressed_data)
    data_bin = work_dir / "data.bin"
    uncompressed = zlib_to_file(compressed_data, data_bin, progress)
    if progress is not None:
        progress.say(f"  [data] ready: {uncompressed / 1048576:.1f} MiB FileDB state")

    if progress is not None:
        progress.say("  [sessions] locating embedded GameSessions")
    descriptors = extract_sessions(data_bin, None, progress)
    if not descriptors:
        raise ValueError(
            f"{save}: no GameSession descriptors recognized; "
            "refusing to publish an empty canonical state"
        )
    if progress is not None:
        total_mb = sum(d.get("binary_size", 0) for d in descriptors) / 1048576
        progress.say(f"  [sessions] found {len(descriptors)} session blobs ({total_mb:.1f} MiB total)")

    parsed_sessions = []
    for session_index, d in enumerate(descriptors, 1):
        binary_offset = d.pop("binary_offset")
        binary_size = d["binary_size"]
        label_bits = []
        if d.get("guid") is not None:
            label_bits.append(f"guid={d['guid']}")
        if d.get("id") is not None:
            label_bits.append(f"id={d['id']}")
        if d.get("map"):
            label_bits.append(f"map={d['map']}")
        label = " ".join(label_bits)
        if progress is not None:
            progress.say(
                f"  [session {session_index}/{len(descriptors)}] {label} "
                f"({binary_size / 1048576:.1f} MiB)"
            )
        parsed = parse_session(
            data_bin,
            progress,
            base_offset=binary_offset,
            blob_size=binary_size,
        )
        parsed_sessions.append({**d, **parsed})
        if progress is not None:
            progress.say(
                f"  [session {session_index}/{len(descriptors)}] done: "
                f"player_areas={len(parsed['player_area_ids'])} "
                f"player_buildings={len(parsed['player_buildings']):,} "
                f"game_objects={parsed['total_game_objects']:,}"
            )
    return build_canonical_state(save.name, parsed_sessions)


def session_diff_identity(session: dict) -> tuple:
    """Return a safe session identity for structural diff indexing."""
    guid = session.get("session_guid")
    if guid is not None:
        return (0, guid, False, 0, "")

    session_id = session.get("session_id")
    session_map = session.get("map") or ""
    if session_id is None and not session_map:
        raise ValueError(
            "structural diff cannot identify a session with no SessionGUID, "
            "SessionID, or map"
        )
    return (
        1,
        0,
        session_id is None,
        session_id if session_id is not None else 0,
        session_map,
    )


def building_key(session: dict, obj: dict) -> tuple:
    return (session_diff_identity(session), obj["area_id"], obj["id"])


def building_key_sort(key: tuple) -> tuple:
    """Sort stable object keys without comparing nullable session fields directly."""
    session_identity, area_id, object_id = key
    return (*session_identity, area_id, object_id)


def area_key_sort(key: tuple) -> tuple:
    """Sort stable player-area keys by session identity and area ID."""
    session_identity, area_id = key
    return (*session_identity, area_id)


def _index_state_buildings(state: dict) -> dict:
    indexed = {}
    seen_sessions = set()
    for session in state["sessions"]:
        session_identity = session_diff_identity(session)
        if session_identity in seen_sessions:
            raise ValueError(
                "structural diff cannot disambiguate duplicate canonical session identity"
            )
        seen_sessions.add(session_identity)
        for obj in session["buildings"]:
            key = (session_identity, obj["area_id"], obj["id"])
            if key in indexed:
                raise ValueError(
                    "structural diff found duplicate building identity within a session"
                )
            indexed[key] = (session, obj)
    return indexed


def _index_state_player_areas(state: dict) -> dict:
    indexed = {}
    seen_sessions = set()
    for session in state["sessions"]:
        session_identity = session_diff_identity(session)
        if session_identity in seen_sessions:
            raise ValueError(
                "structural diff cannot disambiguate duplicate canonical session identity"
            )
        seen_sessions.add(session_identity)
        for area in session.get("player_areas", []):
            key = (session_identity, area["area_id"])
            if key in indexed:
                raise ValueError(
                    "structural diff found duplicate player-area identity within a session"
                )
            indexed[key] = (session, area)
    return indexed


def _compact_area_event(pair: tuple[dict, dict]) -> dict:
    session, area = pair
    event = {
        "session_guid": session.get("session_guid"),
        "session_id": session.get("session_id"),
        "area_id": area["area_id"],
    }
    if "map" in session:
        event["map"] = session["map"]
    return event


def diff_states(prev: dict, curr: dict) -> dict:
    _require_canonical_v1(prev)
    _require_canonical_v1(curr)
    a = _index_state_buildings(prev)
    b = _index_state_buildings(curr)
    prev_areas = _index_state_player_areas(prev)
    curr_areas = _index_state_player_areas(curr)
    added_keys = b.keys() - a.keys(); removed_keys = a.keys() - b.keys(); common = a.keys() & b.keys()
    area_added_keys = curr_areas.keys() - prev_areas.keys()
    area_removed_keys = prev_areas.keys() - curr_areas.keys()

    def compact(pair):
        s,o=pair
        return {"session_guid":s.get("session_guid"),"session_id":s.get("session_id"),"area_id":o["area_id"],
                "id":o["id"],"guid":o["guid"],"position":o.get("position"),"components":o.get("components",[])}
    added=[compact(b[k]) for k in sorted(added_keys, key=building_key_sort)]
    removed=[compact(a[k]) for k in sorted(removed_keys, key=building_key_sort)]
    area_added=[_compact_area_event(curr_areas[k]) for k in sorted(area_added_keys, key=area_key_sort)]
    area_removed=[_compact_area_event(prev_areas[k]) for k in sorted(area_removed_keys, key=area_key_sort)]
    moved=[]; changed=[]; guid_changed=[]; direction_changed=[]
    for k in sorted(common, key=building_key_sort):
        sa, oa = a[k]; sb, ob = b[k]
        if oa.get("guid") != ob.get("guid"):
            guid_changed.append({
                "session_guid": sb.get("session_guid"),
                "session_id": sb.get("session_id"),
                "area_id": ob["area_id"],
                "id": ob["id"],
                "from_guid": oa.get("guid"),
                "to_guid": ob.get("guid"),
                "components": ob.get("components", []),
            })
        if oa.get("position") != ob.get("position"):
            moved.append({"session_guid":sb.get("session_guid"),"area_id":ob["area_id"],"id":ob["id"],"guid":ob["guid"],
                          "from":oa.get("position"),"to":ob.get("position"),"components":ob.get("components",[])})
        if oa.get("direction") != ob.get("direction"):
            event = {
                "session_guid": sb.get("session_guid"),
                "session_id": sb.get("session_id"),
                "area_id": ob["area_id"],
                "id": ob["id"],
                "guid": ob["guid"],
                "from_direction": oa.get("direction"),
                "to_direction": ob.get("direction"),
                "components": ob.get("components", []),
            }
            if "map" in sb:
                event["map"] = sb["map"]
            direction_changed.append(event)
        if oa.get("components") != ob.get("components"):
            changed.append({"session_guid":sb.get("session_guid"),"area_id":ob["area_id"],"id":ob["id"],"guid":ob["guid"],
                            "from_components":oa.get("components",[]),"to_components":ob.get("components",[])})
    by_guid_add=Counter(x["guid"] for x in added); by_guid_remove=Counter(x["guid"] for x in removed)
    return {
        "from":prev["source"]["save_name"],"to":curr["source"]["save_name"],
        "added_count":len(added),"removed_count":len(removed),"moved_count":len(moved),"component_changed_count":len(changed),
        "guid_changed_count":len(guid_changed),"direction_changed_count":len(direction_changed),
        "area_added_count":len(area_added),"area_removed_count":len(area_removed),
        "added_by_guid":{str(k):v for k,v in sorted(by_guid_add.items())},
        "removed_by_guid":{str(k):v for k,v in sorted(by_guid_remove.items())},
        "added":added,"removed":removed,"moved":moved,"component_changed":changed,"guid_changed":guid_changed,
        "direction_changed":direction_changed,
        "area_added":area_added,"area_removed":area_removed,
    }


def build_adjacent_diffs(
    states: list[dict], progress: Progress, detailed_timings: bool = False
) -> list[dict]:
    """Build adjacent structural diffs and report execution timing to the CLI only."""
    pair_count = max(len(states) - 1, 0)
    progress.say(f"[diff] comparing {pair_count} adjacent save pair(s)")
    phase_started = time.monotonic()
    diffs = []
    for pair_index, (prev, curr) in enumerate(zip(states, states[1:]), 1):
        pair_started = time.monotonic()
        diff = diff_states(prev, curr)
        diffs.append(diff)
        if detailed_timings:
            pair_elapsed = time.monotonic() - pair_started
            progress.say(
                f"  [diff {pair_index}/{pair_count}] "
                f"{diff['from']} -> {diff['to']}: {pair_elapsed:.3f}s"
            )
    phase_elapsed = time.monotonic() - phase_started
    progress.say(f"[diff] done in {phase_elapsed:.1f}s: {pair_count} pair(s)")
    return diffs


def strip_objects(state: dict) -> dict:
    """Build a non-canonical state projection for the batch summary."""
    _require_canonical_v1(state)
    out = {
        "source": dict(state["source"]),
        "sessions": [],
    }
    for s in state["sessions"]:
        q = {
            "session_guid": s.get("session_guid"),
            "session_id": s.get("session_id"),
            "player_areas": [dict(area) for area in s.get("player_areas", [])],
            "building_count": len(s.get("buildings", [])),
        }
        if "map" in s:
            q["map"] = s["map"]
        out["sessions"].append(q)
    return out


def build_batch_summary(states: list[dict], diffs: list[dict]) -> dict:
    """Build the batch report without representing projections as canonical states."""
    for state in states:
        _require_canonical_v1(state)
    return {
        "canonical_schema": {
            "name": CANONICAL_SCHEMA,
            "version": CANONICAL_SCHEMA_VERSION,
        },
        "states": [strip_objects(state) for state in states],
        "diffs": diffs,
    }


def read_save_meta(save: Path) -> dict:
    """Read tiny internal save metadata without expanding the main game state."""
    compressed = extract_rda_member(save, "meta.a7s")
    raw = zlib.decompress(compressed)
    with tempfile.NamedTemporaryFile(prefix="anno-save-meta-", suffix=".bin", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        tags_off, _, _, attrs = bb_meta(tmp_path)
        result = {}
        with tmp_path.open("rb") as f:
            pos = 0
            while pos < tags_off:
                hdr = f.read(8)
                if len(hdr) != 8:
                    break
                size, raw_id = struct.unpack("<ii", hdr)
                pos += 8
                ident = raw_id & 0xFFFF
                if ident == 0 or ident < 32768:
                    continue
                name = attrs.get(ident, f"@{ident}")
                value = _read_attr(f, size)
                pos += _padded(size)
                if name == "LastModTime" and len(value) <= 8:
                    result["last_mod_time"] = int.from_bytes(value, "little", signed=False)
                elif name == "CorporationSaveGameName":
                    result["save_name"] = _decode_utf16(value)
        return result
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def cached_save_meta(save: Path) -> dict:
    key = save.resolve()
    if key not in SAVE_META_CACHE:
        SAVE_META_CACHE[key] = read_save_meta(save)
    return SAVE_META_CACHE[key]


def _natural_name_key(path: Path) -> tuple:
    parts = re.split(r"(\d+)", path.name.lower())
    return tuple(int(p) if p.isdigit() else p for p in parts)


def discover_saves(inputs: list[Path], progress: Optional[Progress] = None) -> list[Path]:
    """Resolve explicit .a7s files and folders containing .a7s saves."""
    saves: list[Path] = []
    for item in inputs:
        item = item.expanduser()
        if item.is_dir():
            saves.extend(p for p in item.glob("*.a7s") if p.is_file())
        elif item.is_file():
            if item.suffix.lower() != ".a7s":
                raise ValueError(f"Not an .a7s save: {item}")
            saves.append(item)
        else:
            raise FileNotFoundError(f"Path does not exist: {item}")

    unique = {p.resolve(): p for p in saves}
    saves = list(unique.values())

    if progress is not None:
        progress.say(f"[scan] found {len(saves)} .a7s file(s); reading internal save timestamps")

    chronology: dict[Path, float] = {}
    for i, p in enumerate(saves, 1):
        try:
            ts = cached_save_meta(p).get("last_mod_time")
        except Exception:
            ts = None
        if ts is None:
            ts = p.stat().st_mtime
        chronology[p] = ts
        if progress is not None:
            progress.maybe(
                f"[scan] metadata {i}/{len(saves)} ({100.0 * i / max(len(saves), 1):.1f}%) "
                f"current={p.name}"
            )

    saves.sort(key=lambda p: (chronology[p], _natural_name_key(p)))
    if progress is not None and saves:
        progress.say(f"[scan] ready: {len(saves)} save(s), {saves[0].name} -> {saves[-1].name}")
    return saves


def select_from(saves: list[Path], start: Optional[str]) -> list[Path]:
    if not start:
        return saves

    # YYYY-MM-DD means the first save whose internal LastModTime date is
    # on or after this local calendar day; filesystem mtime is fallback only.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
        try:
            wanted = date.fromisoformat(start)
        except ValueError as exc:
            raise ValueError(f"Invalid date for --from: {start}; expected YYYY-MM-DD") from exc
        selected = []
        for p in saves:
            try:
                ts = cached_save_meta(p).get("last_mod_time")
            except Exception:
                ts = None
            if ts is None:
                ts = p.stat().st_mtime
            if datetime.fromtimestamp(ts).date() >= wanted:
                selected.append(p)
        if not selected:
            if saves:
                try:
                    last_ts = cached_save_meta(saves[-1]).get("last_mod_time")
                except Exception:
                    last_ts = None
                if last_ts is None:
                    last_ts = saves[-1].stat().st_mtime
                last = datetime.fromtimestamp(last_ts).date()
            else:
                last = None
            suffix = f"; newest save is {last}" if last else ""
            raise ValueError(f"No saves found on or after {wanted}{suffix}")
        return selected

    # Save names are accepted with or without .a7s, case-insensitively.
    needle = start.casefold()
    needle_stem = Path(start).stem.casefold()
    index = next(
        (
            i for i, p in enumerate(saves)
            if p.name.casefold() == needle or p.stem.casefold() == needle_stem
        ),
        None,
    )
    if index is None:
        names = [p.name for p in saves]
        close = get_close_matches(start, names, n=5, cutoff=0.35)
        hint = f" Close matches: {', '.join(close)}" if close else ""
        raise ValueError(f"Save named {start!r} was not found.{hint}")
    return saves[index:]


def print_save_list(saves: list[Path]) -> None:
    if not saves:
        print("No .a7s saves found.")
        return
    for i, p in enumerate(saves, 1):
        try:
            ts = cached_save_meta(p).get("last_mod_time")
        except Exception:
            ts = None
        source = "internal"
        if ts is None:
            ts = p.stat().st_mtime
            source = "filesystem"
        modified = datetime.fromtimestamp(ts).astimezone()
        size_mb = p.stat().st_size / (1024 * 1024)
        print(
            f"{i:4d}  {modified:%Y-%m-%d %H:%M:%S %z}  {size_mb:7.2f} MB  "
            f"{p.name}  [{source}]"
        )



def _positive_worker_count(value: str) -> int:
    """argparse type for an explicit positive process-worker count."""
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--workers must be a positive integer") from exc
    if workers <= 0:
        raise argparse.ArgumentTypeError("--workers must be greater than zero")
    return workers


def resolve_worker_count(requested: int, save_count: int) -> int:
    """Resolve explicit concurrency and enforce hard platform executor limits."""
    if requested <= 0:
        raise ValueError("worker count must be greater than zero")
    if save_count <= 0:
        return 1
    active = min(requested, save_count)
    if os.name == "nt" and active > WINDOWS_PROCESS_WORKER_LIMIT:
        raise ValueError(
            f"--workers resolves to {active} active workers, but Windows "
            f"ProcessPoolExecutor supports at most {WINDOWS_PROCESS_WORKER_LIMIT}"
        )
    return active


def _available_memory_bytes() -> Optional[int]:
    """Return currently available physical memory when stdlib/platform APIs allow it."""
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
        except (AttributeError, OSError, ValueError):
            return None
        return None

    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None
    if page_size <= 0 or available_pages <= 0:
        return None
    return page_size * available_pages


def _format_gib(value: Optional[int]) -> str:
    return "unknown" if value is None else f"{value / (1024 ** 3):.1f} GiB"


def report_worker_plan(
    requested: int,
    active: int,
    progress: Progress,
) -> None:
    """Report explicit concurrency and conservative resource-pressure warnings."""
    cpu_count = os.cpu_count()
    available_memory = _available_memory_bytes()
    try:
        temp_free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        temp_free = None

    mode = "serial" if active == 1 else "process"
    cpu_text = "unknown" if cpu_count is None else str(cpu_count)
    progress.say(
        f"[workers] requested={requested} active={active} mode={mode} "
        f"cpu={cpu_text} available_ram={_format_gib(available_memory)} "
        f"temp_free={_format_gib(temp_free)}"
    )

    if active <= 1:
        return
    if cpu_count is not None and active > cpu_count:
        progress.say(
            f"  [workers] warning: active workers ({active}) exceed logical CPUs ({cpu_count})"
        )

    estimated_ram = active * PARALLEL_RAM_ESTIMATE_BYTES
    if available_memory is not None and available_memory < estimated_ram:
        progress.say(
            "  [workers] warning: available RAM is below the conservative "
            f"~{estimated_ram / (1024 ** 3):.1f} GiB estimate for {active} workers"
        )

    estimated_temp = active * PARALLEL_TEMP_ESTIMATE_BYTES
    if temp_free is not None and temp_free < estimated_temp:
        progress.say(
            "  [workers] warning: free temp space is below the conservative "
            f"~{estimated_temp / (1024 ** 3):.1f} GiB active-worker estimate"
        )


def _canonicalize_worker(save_path: str) -> tuple[dict, float]:
    """Process-pool entrypoint: canonicalize one save without emitting worker logs."""
    save = Path(save_path)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="anno-save-probe-") as td:
        state = canonicalize_save(save, Path(td), None)
    return state, time.monotonic() - started


def canonical_output_filename(save: Path) -> str:
    """Return the stable canonical snapshot filename for one source save."""
    stem = save.stem.replace(" ", "_")
    return f"{stem}.canonical.json.gz"


def validate_canonical_output_names(saves: list[Path]) -> None:
    """Reject batches whose selected saves would overwrite one canonical snapshot."""
    seen: dict[str, Path] = {}
    for save in saves:
        filename = canonical_output_filename(save)
        # Compare independently of the host OS: the output directory may live on
        # a case-insensitive or Unicode-normalizing volume even when Python itself is
        # running on POSIX. Rejecting conservatively is safer than silent overwrite.
        key = unicodedata.normalize("NFC", filename).casefold()
        previous = seen.get(key)
        if previous is not None:
            raise ValueError(
                "selected saves map to the same canonical output filename "
                f"{filename!r}: {previous} and {save}"
            )
        seen[key] = save


def _write_canonical_state(save: Path, state: dict, output: Path) -> Path:
    canonical_path = output / canonical_output_filename(save)
    with gzip.open(canonical_path, "wt", encoding="utf8") as f:
        json.dump(state, f, separators=(",", ":"))
    return canonical_path


def _parse_completion_line(index: int, total: int, elapsed: float, state: dict) -> str:
    return (
        f"[parse {index}/{total}] done in {elapsed:.1f}s: "
        f"sessions={len(state['sessions'])} "
        f"player_buildings={sum(len(s['buildings']) for s in state['sessions']):,}"
    )


def parse_saves_serial(saves: list[Path], output: Path, progress: Progress) -> list[dict]:
    """Preserve the existing detailed single-process parsing behavior."""
    states = []
    for i, save in enumerate(saves, 1):
        file_started = time.monotonic()
        progress.begin_parse(f"[parse {i}/{len(saves)}] {save.name}")
        try:
            with tempfile.TemporaryDirectory(prefix="anno-save-probe-") as td:
                state = canonicalize_save(save, Path(td), progress)
            states.append(state)
            canonical_path = output / f"{save.stem.replace(' ', '_')}.canonical.json.gz"
            progress.say(f"  [write] {canonical_path.name}")
            _write_canonical_state(save, state, output)
        except BaseException as exc:
            progress.abort_parse(
                f"[parse {i}/{len(saves)}] failed: {type(exc).__name__}: {exc}"
            )
            raise
        elapsed = time.monotonic() - file_started
        progress.finish_parse(_parse_completion_line(i, len(saves), elapsed, state))
    return states


def parse_saves_parallel(
    saves: list[Path],
    output: Path,
    progress: Progress,
    workers: int,
    executor_factory=ProcessPoolExecutor,
    wait_fn=wait,
) -> list[dict]:
    """Canonicalize saves with bounded process submission while preserving input order."""
    total = len(saves)
    if total == 0:
        return []
    workers = resolve_worker_count(workers, total)
    states: list[Optional[dict]] = [None] * total
    completed = 0
    next_index = 0
    futures = {}
    executor = executor_factory(max_workers=workers)

    def submit(index: int) -> None:
        future = executor.submit(_canonicalize_worker, str(saves[index]))
        futures[future] = index

    try:
        while next_index < total and len(futures) < workers:
            submit(next_index)
            next_index += 1

        while futures:
            done, _ = wait_fn(
                set(futures),
                timeout=1.0,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                progress.maybe(
                    f"[parse] completed={completed}/{total} running={len(futures)} "
                    f"pending={total - completed - len(futures)}"
                )
                continue

            completed_batch = []
            batch_failure = None
            for future in sorted(done, key=lambda item: futures[item]):
                index = futures.pop(future)
                save = saves[index]
                try:
                    state, elapsed = future.result()
                except BaseException as exc:
                    if batch_failure is None:
                        batch_failure = (save, exc)
                    continue
                completed_batch.append((index, save, state, elapsed))

            if batch_failure is not None:
                save, exc = batch_failure
                raise RuntimeError(
                    f"{save.name}: parallel parse failed: {type(exc).__name__}: {exc}"
                ) from exc

            for index, save, state, elapsed in completed_batch:
                states[index] = state
                _write_canonical_state(save, state, output)
                completed += 1
                progress.say(
                    _parse_completion_line(index + 1, total, elapsed, state)
                    + f" completed={completed}/{total}"
                )

            while next_index < total and len(futures) < workers:
                submit(next_index)
                next_index += 1
    except BaseException as exc:
        # Future.cancel() cannot stop work that is already running. Surface the
        # failure immediately, then keep the cleanup wait observable instead of
        # blocking silently inside executor.shutdown(wait=True).
        cleanup_pending = set()
        for future in futures:
            if not future.cancel():
                cleanup_pending.add(future)
        progress.say(
            f"[parse] failure detected: {type(exc).__name__}: {exc}; "
            f"waiting for {len(cleanup_pending)} active worker(s) to exit"
        )
        while cleanup_pending:
            done, cleanup_pending = wait_fn(
                cleanup_pending,
                timeout=1.0,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                progress.maybe(
                    f"[parse] failure cleanup: waiting for "
                    f"{len(cleanup_pending)} active worker(s) to exit"
                )
        progress.say("[parse] failure cleanup: finalizing worker processes")
        executor.shutdown(wait=True, cancel_futures=True)
        progress.say("[parse] failure cleanup complete")
        raise
    else:
        executor.shutdown(wait=True)

    if any(state is None for state in states):
        raise RuntimeError("parallel parse completed without producing every canonical state")
    return [state for state in states if state is not None]


def parse_saves_batch(
    saves: list[Path],
    output: Path,
    progress: Progress,
    workers: int,
) -> list[dict]:
    validate_canonical_output_names(saves)
    if workers == 1:
        return parse_saves_serial(saves, output, progress)
    return parse_saves_parallel(saves, output, progress, workers)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser.

    Keep this separate from main() so the command-line contract can be
    regression-tested without parsing a multi-hundred-megabyte save.
    """
    ap = argparse.ArgumentParser(
        description=(
            "Parse a folder/sequence of Anno 1800 .a7s saves into compact "
            "canonical states and diffs."
        )
    )
    ap.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    ap.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="One save folder, or one/more explicit .a7s files.",
    )
    ap.add_argument(
        "--from",
        dest="start",
        metavar="SAVE_OR_DATE",
        help='Start at a save name (e.g. "Autosave 711") or internal save date YYYY-MM-DD.',
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="Only list discovered saves in processing order; do not parse them.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Process at most N saves after applying --from (handy for a quick test).",
    )
    ap.add_argument(
        "--timings",
        action="store_true",
        help=(
            "Report per-adjacent-pair structural diff elapsed time; total diff time "
            "is always reported."
        ),
    )
    ap.add_argument(
        "--workers",
        type=_positive_worker_count,
        default=1,
        metavar="N",
        help=(
            "Parse up to N saves concurrently with worker processes; default 1 "
            "keeps the existing serial behavior."
        ),
    )
    ap.add_argument(
        "--guid-mapping",
        type=Path,
        metavar="PATH",
        help=(
            "Optional provenance-aware GUID/name mapping JSON used to enrich "
            "summary diffs; canonical snapshots and numeric GUIDs stay unchanged."
        ),
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("anno-save-probe-output"),
    )
    return ap


def parse_cli_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments; exposed primarily for regression tests."""
    return build_arg_parser().parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    progress = Progress(interval=1.0)
    progress.say(f"[start] Anno save tutor probe v{__version__}")
    for item in args.inputs:
        progress.say(f"[start] input: {item}")

    guid_mapping = None
    if args.guid_mapping is not None:
        try:
            guid_mapping = load_guid_mapping(args.guid_mapping)
        except (OSError, GuidMappingError) as exc:
            ap.error(f"--guid-mapping {args.guid_mapping}: {exc}")
        progress.say(
            f"[mapping] loaded {len(guid_mapping['entries'])} exact GUID name(s) "
            f"from {args.guid_mapping}"
        )

    try:
        saves = discover_saves(args.inputs, progress)
        if not saves:
            raise ValueError(
                "No .a7s files found. Point the command at the directory that directly contains the saves."
            )
        saves = select_from(saves, args.start)
        if args.limit is not None:
            if args.limit <= 0:
                raise ValueError("--limit must be greater than zero")
            saves = saves[:args.limit]
    except (OSError, ValueError) as exc:
        ap.error(str(exc))

    if args.list:
        print_save_list(saves)
        return

    args.output.mkdir(parents=True, exist_ok=True)
    progress.say(f"[input] selected {len(saves)} save(s); {saves[0].name} -> {saves[-1].name}")
    progress.say(f"[output] {args.output.resolve()}")
    try:
        active_workers = resolve_worker_count(args.workers, len(saves))
        validate_canonical_output_names(saves)
    except ValueError as exc:
        ap.error(str(exc))
    report_worker_plan(args.workers, active_workers, progress)
    states = parse_saves_batch(saves, args.output, progress, active_workers)

    diffs = build_adjacent_diffs(states, progress, detailed_timings=args.timings)
    if guid_mapping is not None:
        diffs = [enrich_structural_diff(diff, guid_mapping) for diff in diffs]
    with (args.output / "summary.json").open("w", encoding="utf8") as f:
        json.dump(
            build_batch_summary(states, diffs),
            f,
            indent=2,
            ensure_ascii=False,
        )
    progress.say(f"[done] {args.output / 'summary.json'}")
    for d in diffs:
        print(
            f"  {d['from']} -> {d['to']}: +{d['added_count']} -{d['removed_count']} "
            f"moved={d['moved_count']} changed={d['component_changed_count']} "
            f"guid_changed={d['guid_changed_count']} direction_changed={d['direction_changed_count']}"
        )


if __name__ == "__main__":
    main()
