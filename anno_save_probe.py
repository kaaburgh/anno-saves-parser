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
from datetime import date, datetime
from difflib import get_close_matches
from pathlib import Path
from typing import BinaryIO, Optional

__version__ = "0.2.1"

RDA_MAGIC = b"Resource File V2.2"
BBDOM_V3_MAGIC = bytes.fromhex("08000000fdffffff")
PAD_BLOCK = 8
AREA_RE = re.compile(r"^AreaManager_(\d+)$")

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
    with path.open("rb") as f:
        f.seek(-16, 2)
        trailer = f.read(16)
        tags_off, attrs_off = struct.unpack("<ii", trailer[:8])
        if trailer[8:] != BBDOM_V3_MAGIC:
            raise ValueError(f"{path}: not FileDB/BBDom v3")
        tags = _read_dictionary(f, tags_off)
        attrs = _read_dictionary(f, attrs_off)
    return tags_off, attrs_off, tags, attrs


def _read_attr(f: BinaryIO, size: int) -> bytes:
    raw = f.read(_padded(size))
    return raw[:size]


def extract_sessions(meta_data_bin: Path, session_dir: Path, progress: Optional[Progress] = None) -> list[dict]:
    """Extract embedded BBDom session blobs and descriptors from top-level data.a7s."""
    session_dir.mkdir(parents=True, exist_ok=True)
    tags_off, _, tags, attrs = bb_meta(meta_data_bin)
    sessions: list[dict] = []
    stack: list[str] = []
    current: Optional[dict] = None
    index = -1
    with meta_data_bin.open("rb") as f:
        pos = 0
        operations = 0
        while pos < tags_off:
            hdr = f.read(8)
            if len(hdr) != 8:
                break
            size, raw_id = struct.unpack("<ii", hdr); pos += 8
            operations += 1
            if progress is not None and operations % 10000 == 0:
                progress.maybe(
                    f"    [sessions] scanning {100.0 * pos / max(tags_off, 1):5.1f}% "
                    f"sessions_found={len(sessions) + (1 if current is not None else 0)}"
                )
            ident = raw_id & 0xFFFF
            if ident == 0:
                if stack:
                    popped = stack.pop()
                    if popped == "#1" and stack and stack[-1] == "GameSessions" and current is not None:
                        sessions.append(current); current = None
                continue
            if ident < 32768:
                name = tags.get(ident, f"#{ident}")
                stack.append(name)
                if name == "#1" and len(stack) >= 2 and stack[-2] == "GameSessions":
                    index += 1
                    current = {"index": index}
                continue

            name = attrs.get(ident, f"@{ident}")
            padded = _padded(size)
            # BinaryData can be tens of MB: copy it directly rather than retain in memory.
            is_session_blob = (
                name == "BinaryData" and len(stack) >= 3 and
                stack[-3:] == ["GameSessions", "#1", "SessionData"]
            )
            if is_session_blob:
                out_path = session_dir / f"session-{index}.bin"
                remaining = size
                with out_path.open("wb") as out:
                    while remaining:
                        chunk = f.read(min(1 << 20, remaining))
                        if not chunk: raise EOFError("session blob truncated")
                        out.write(chunk); remaining -= len(chunk)
                pad = padded - size
                if pad: f.seek(pad, 1)
                pos += padded
                if current is not None:
                    current["binary_path"] = str(out_path)
                    current["binary_size"] = size
                continue

            raw = _read_attr(f, size); pos += padded
            if current is not None and len(stack) >= 4 and stack[-2:] == ["#1", "SessionDesc"]:
                if name == "SessionGUID": current["guid"] = _u32(raw)
                elif name == "SessionID": current["id"] = _u32(raw)
                elif name == "SessionMap": current["map"] = _decode_utf16(raw)
    return sessions


def parse_session(path: Path, progress: Optional[Progress] = None) -> dict:
    """Canonicalize area ownership and object/building state from one GameSession blob."""
    tags_off, _, tags, attrs = bb_meta(path)
    stack: list[str] = []
    area_infos: list[dict] = []
    current_area_info: Optional[dict] = None
    current_object: Optional[dict] = None
    object_depth = -1
    all_objects: list[dict] = []

    with path.open("rb") as f:
        pos = 0
        operations = 0
        while pos < tags_off:
            hdr = f.read(8)
            if len(hdr) != 8: break
            size, raw_id = struct.unpack("<ii", hdr); pos += 8
            operations += 1
            if progress is not None and operations % 10000 == 0:
                progress.maybe(
                    f"      scanning {100.0 * pos / max(tags_off, 1):5.1f}% "
                    f"objects={len(all_objects):,} areas={len(area_infos):,}"
                )
            ident = raw_id & 0xFFFF
            if ident == 0:
                if stack:
                    popped = stack.pop()
                    if current_object is not None and len(stack) < object_depth:
                        if current_object.get("id") is not None and current_object.get("guid") is not None:
                            all_objects.append(current_object)
                        current_object = None; object_depth = -1
                    if popped == "#1" and len(stack) >= 2 and stack[-1] == "AreaInfo" and current_area_info is not None:
                        area_infos.append(current_area_info); current_area_info = None
                continue

            if ident < 32768:
                name = tags.get(ident, f"#{ident}")
                stack.append(name)
                if stack[-3:] == ["GameSessionManager", "AreaInfo", "#1"]:
                    current_area_info = {}
                # Object root: .../AreaManager_N/AreaObjectManager/GameObject/objects/#1
                if name == "#1" and len(stack) >= 6 and stack[-3:-1] == ["GameObject", "objects"]:
                    area_name = next((x for x in reversed(stack[:-3]) if AREA_RE.match(x)), None)
                    if area_name:
                        area_id = int(AREA_RE.match(area_name).group(1))
                        current_object = {"area_id": area_id, "components": []}
                        object_depth = len(stack)
                elif current_object is not None and len(stack) == object_depth + 1 and name in INTERESTING_COMPONENTS:
                    current_object["components"].append(name)
                continue

            name = attrs.get(ident, f"@{ident}")
            raw = _read_attr(f, size); pos += _padded(size)

            if current_area_info is not None:
                rel = stack[3:]
                if rel == [] and name in ("CityNameGuid", "CityNameIterator"):
                    current_area_info[name] = _u32(raw)
                elif rel == ["Owner"] and name == "id":
                    current_area_info["owner_id"] = _u32(raw)
                elif rel == ["PassiveTrade"] and name == "AreaID":
                    current_area_info["area_id"] = _u32(raw)

            if current_object is not None and len(stack) == object_depth:
                if name == "ID": current_object["id"] = int.from_bytes(raw, "little", signed=False)
                elif name == "guid": current_object["guid"] = _u32(raw)
                elif name == "Position" and len(raw) == 8:
                    current_object["position"] = list(struct.unpack("<ii", raw))
                elif name in ("Rotation90", "Rotation") and len(raw) <= 4:
                    current_object["rotation"] = _u32(raw)

    owner_by_area = {
        a["area_id"]: a.get("owner_id") for a in area_infos if "area_id" in a
    }
    player_area_ids = sorted(a for a, owner in owner_by_area.items() if owner == 0)
    player_set = set(player_area_ids)

    # Building is the common component; include specialist markers for semantic classification.
    player_buildings = []
    for obj in all_objects:
        if obj["area_id"] not in player_set: continue
        comps = set(obj["components"])
        if "Building" not in comps and not comps.intersection({"Residence7", "Factory7", "Warehouse", "BuildingModule"}):
            continue
        obj["components"] = sorted(comps)
        player_buildings.append(obj)

    area_summaries = {}
    for area_id in player_area_ids:
        objs = [o for o in player_buildings if o["area_id"] == area_id]
        kinds = Counter()
        guids = Counter()
        for o in objs:
            guids[o["guid"]] += 1
            comps = set(o["components"])
            if "Residence7" in comps: kinds["residence"] += 1
            if "Factory7" in comps: kinds["factory"] += 1
            if "Warehouse" in comps: kinds["warehouse"] += 1
            if "BuildingModule" in comps: kinds["module"] += 1
            if "Building" in comps: kinds["building"] += 1
        info = next((a for a in area_infos if a.get("area_id") == area_id), {})
        area_summaries[str(area_id)] = {
            "owner_id": 0,
            "city_name_guid": info.get("CityNameGuid"),
            "city_name_iterator": info.get("CityNameIterator"),
            "building_objects": len(objs),
            "kind_counts": dict(kinds),
            "guid_counts": {str(k): v for k, v in sorted(guids.items())},
        }

    return {
        "player_area_ids": player_area_ids,
        "areas": area_summaries,
        "player_buildings": player_buildings,
        "total_game_objects": len(all_objects),
    }


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

    session_dir = work_dir / "sessions"
    if progress is not None:
        progress.say("  [sessions] locating embedded GameSessions")
    descriptors = extract_sessions(data_bin, session_dir, progress)
    if progress is not None:
        total_mb = sum(d.get("binary_size", 0) for d in descriptors) / 1048576
        progress.say(f"  [sessions] found {len(descriptors)} session blobs ({total_mb:.1f} MiB total)")

    sessions = []
    for session_index, d in enumerate(descriptors, 1):
        session_path = Path(d.pop("binary_path"))
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
                f"({session_path.stat().st_size / 1048576:.1f} MiB)"
            )
        parsed = parse_session(session_path, progress)
        sessions.append({**d, **parsed})
        if progress is not None:
            progress.say(
                f"  [session {session_index}/{len(descriptors)}] done: "
                f"player_areas={len(parsed['player_area_ids'])} "
                f"player_buildings={len(parsed['player_buildings']):,} "
                f"game_objects={parsed['total_game_objects']:,}"
            )
    return {
        "source": save.name,
        "source_size": save.stat().st_size,
        "outer_entries": [{k: e[k] for k in ("name", "size", "compressed_size")} for e in outer],
        "data_uncompressed_size": uncompressed,
        "sessions": sessions,
    }


def building_key(session: dict, obj: dict) -> tuple:
    return (session.get("guid"), obj["area_id"], obj["id"])


def diff_states(prev: dict, curr: dict) -> dict:
    a, b = {}, {}
    for s in prev["sessions"]:
        for o in s["player_buildings"]: a[building_key(s,o)] = (s,o)
    for s in curr["sessions"]:
        for o in s["player_buildings"]: b[building_key(s,o)] = (s,o)
    added_keys = b.keys() - a.keys(); removed_keys = a.keys() - b.keys(); common = a.keys() & b.keys()

    def compact(pair):
        s,o=pair
        return {"session_guid":s.get("guid"),"session_id":s.get("id"),"area_id":o["area_id"],
                "id":o["id"],"guid":o["guid"],"position":o.get("position"),"components":o.get("components",[])}
    added=[compact(b[k]) for k in sorted(added_keys)]
    removed=[compact(a[k]) for k in sorted(removed_keys)]
    moved=[]; changed=[]; guid_changed=[]
    for k in sorted(common):
        sa, oa = a[k]; sb, ob = b[k]
        if oa.get("guid") != ob.get("guid"):
            guid_changed.append({
                "session_guid": k[0],
                "session_id": sb.get("id"),
                "area_id": k[1],
                "id": k[2],
                "from_guid": oa.get("guid"),
                "to_guid": ob.get("guid"),
                "components": ob.get("components", []),
            })
        if oa.get("position") != ob.get("position"):
            moved.append({"session_guid":k[0],"area_id":k[1],"id":k[2],"guid":ob["guid"],
                          "from":oa.get("position"),"to":ob.get("position"),"components":ob.get("components",[])})
        if oa.get("components") != ob.get("components"):
            changed.append({"session_guid":k[0],"area_id":k[1],"id":k[2],"guid":ob["guid"],
                            "from_components":oa.get("components",[]),"to_components":ob.get("components",[])})
    by_guid_add=Counter(x["guid"] for x in added); by_guid_remove=Counter(x["guid"] for x in removed)
    return {
        "from":prev["source"],"to":curr["source"],
        "added_count":len(added),"removed_count":len(removed),"moved_count":len(moved),"component_changed_count":len(changed),
        "guid_changed_count":len(guid_changed),
        "added_by_guid":{str(k):v for k,v in sorted(by_guid_add.items())},
        "removed_by_guid":{str(k):v for k,v in sorted(by_guid_remove.items())},
        "added":added,"removed":removed,"moved":moved,"component_changed":changed,"guid_changed":guid_changed,
    }


def strip_objects(state: dict) -> dict:
    """Compact summary safe for a human-readable report."""
    out={k:v for k,v in state.items() if k!="sessions"};out["sessions"]=[]
    for s in state["sessions"]:
        q={k:v for k,v in s.items() if k!="player_buildings"}
        q["player_building_count"] = len(s["player_buildings"])
        out["sessions"].append(q)
    return out





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
    states = []
    for i, save in enumerate(saves, 1):
        file_started = time.monotonic()
        progress.begin_parse(f"[parse {i}/{len(saves)}] {save.name}")
        try:
            with tempfile.TemporaryDirectory(prefix="anno-save-probe-") as td:
                state = canonicalize_save(save, Path(td), progress)
            states.append(state)
            stem = save.stem.replace(" ", "_")
            canonical_path = args.output / f"{stem}.canonical.json.gz"
            progress.say(f"  [write] {canonical_path.name}")
            with gzip.open(canonical_path, "wt", encoding="utf8") as f:
                json.dump(state, f, separators=(",", ":"))
        except BaseException as exc:
            progress.abort_parse(
                f"[parse {i}/{len(saves)}] failed: {type(exc).__name__}: {exc}"
            )
            raise
        elapsed = time.monotonic() - file_started
        progress.finish_parse(
            f"[parse {i}/{len(saves)}] done in {elapsed:.1f}s: "
            f"sessions={len(state['sessions'])} "
            f"player_buildings={sum(len(s['player_buildings']) for s in state['sessions']):,}"
        )

    progress.say(f"[diff] comparing {max(len(states) - 1, 0)} adjacent save pair(s)")
    diffs = [diff_states(a, b) for a, b in zip(states, states[1:])]
    with (args.output / "summary.json").open("w", encoding="utf8") as f:
        json.dump(
            {"states": [strip_objects(s) for s in states], "diffs": diffs},
            f,
            indent=2,
            ensure_ascii=False,
        )
    progress.say(f"[done] {args.output / 'summary.json'}")
    for d in diffs:
        print(
            f"  {d['from']} -> {d['to']}: +{d['added_count']} -{d['removed_count']} "
            f"moved={d['moved_count']} changed={d['component_changed_count']} "
            f"guid_changed={d['guid_changed_count']}"
        )


if __name__ == "__main__":
    main()