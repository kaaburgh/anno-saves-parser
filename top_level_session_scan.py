#!/usr/bin/env python3
"""Internal scanners for top-level FileDB GameSession discovery."""
from __future__ import annotations

import mmap
import struct
from pathlib import Path
from typing import BinaryIO, Optional

PAD_BLOCK = 8


def _padded(size: int) -> int:
    return ((size + PAD_BLOCK - 1) // PAD_BLOCK) * PAD_BLOCK


def _ids_named(dictionary: dict[int, str], name: str) -> set[int]:
    return {ident for ident, value in dictionary.items() if value == name}


def _entry_tag_ids(tags: dict[int, str]) -> set[int]:
    result = _ids_named(tags, "#1")
    if 1 not in tags:
        result.add(1)
    return result


def _decode_utf16(raw: bytes) -> str:
    return raw.decode("utf-16le", errors="replace").rstrip("\x00")


def _u32(raw: bytes, field: str) -> int:
    if len(raw) != 4:
        raise ValueError(f"{field} must be exactly 4 bytes; got {len(raw)}")
    return int.from_bytes(raw, "little", signed=False)


def _read_attr(stream: BinaryIO, size: int) -> bytes:
    raw = stream.read(_padded(size))
    return raw[:size]


def scan_top_level_sessions_buffered_reference(
    path: Path,
    tags_off: int,
    tags: dict[int, str],
    attrs: dict[int, str],
) -> list[dict]:
    """Retained buffered scanner used only as an independent evidence oracle."""
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

    with path.open("rb") as stream:
        pos = 0
        while pos < tags_off:
            header = stream.read(8)
            if len(header) != 8:
                raise EOFError("top-level FileDB record header truncated")
            size, raw_id = struct.unpack("<ii", header)
            pos += 8

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
            value_offset = stream.tell()
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
                stream.seek(padded, 1)
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
                raw = _read_attr(stream, size)
                if ident in session_guid_ids:
                    current["guid"] = _u32(raw, "SessionGUID")
                elif ident in session_id_ids:
                    current["id"] = _u32(raw, "SessionID")
                elif ident in session_map_ids:
                    current["map"] = _decode_utf16(raw)
            else:
                stream.seek(padded, 1)
            pos += padded

    for session in sessions:
        if "binary_offset" not in session or "binary_size" not in session:
            raise ValueError("GameSession descriptor is missing BinaryData")
    return sessions


def scan_top_level_sessions_mmap(
    path: Path,
    tags_off: int,
    tags: dict[int, str],
    attrs: dict[int, str],
    progress: Optional[object] = None,
) -> list[dict]:
    """Return GameSession descriptors using read-only mmap/offset traversal.

    ``tags_off``, ``tags`` and ``attrs`` come from the existing FileDB metadata
    reader. Keeping metadata parsing outside this helper avoids a second parser
    implementation while isolating the hot record traversal for differential
    testing and later production integration.
    """
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

    with path.open("rb") as stream:
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            pos = 0
            while pos < tags_off:
                if pos + 8 > tags_off:
                    raise EOFError("top-level FileDB record header truncated")
                size, raw_id = struct.unpack_from("<ii", mapped, pos)
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
                value_offset = pos
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
                    raw = bytes(mapped[value_offset:value_offset + size])
                    if ident in session_guid_ids:
                        current["guid"] = _u32(raw, "SessionGUID")
                    elif ident in session_id_ids:
                        current["id"] = _u32(raw, "SessionID")
                    elif ident in session_map_ids:
                        current["map"] = _decode_utf16(raw)
                pos += padded

    for session in sessions:
        if "binary_offset" not in session or "binary_size" not in session:
            raise ValueError("GameSession descriptor is missing BinaryData")
    return sessions
