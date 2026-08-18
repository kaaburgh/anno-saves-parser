"""Optional operator tool for exporting GUID/name mappings from asset-extractor.

The core parser does not import or depend on ``assetextractor``. This module only
loads that package when the operator explicitly invokes the exporter CLI.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from guid_mapping import GUID_MAPPING_SCHEMA, GUID_MAPPING_SCHEMA_VERSION, validate_guid_mapping

_SHA256_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


class GuidMappingExportError(ValueError):
    """Raised when exporter inputs cannot produce deterministic mapping evidence."""


def _asset_name(asset: Any, language: str) -> str | None:
    text = getattr(asset, "text", None)
    values = getattr(text, "values", None)
    if isinstance(values, dict):
        candidate = values.get(language)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    fallback = getattr(asset, "name", None)
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return None


def build_mapping_document(
    assets: Iterable[Any],
    *,
    language: str,
    source_version: str,
    source_hash: str,
    mapping_version: str,
) -> dict[str, Any]:
    """Build mapping schema v1 from resolved asset-extractor asset objects."""
    if not language.strip():
        raise GuidMappingExportError("language must be a non-empty string")
    if not source_version.strip():
        raise GuidMappingExportError("source_version must be a non-empty string")
    if not mapping_version.strip():
        raise GuidMappingExportError("mapping_version must be a non-empty string")
    if not _SHA256_RE.fullmatch(source_hash):
        raise GuidMappingExportError("source_hash must be sha256:<64 hex characters>")

    names_by_guid: dict[int, str] = {}
    for asset in assets:
        guid = getattr(asset, "guid", None)
        if not isinstance(guid, int) or isinstance(guid, bool) or not 0 <= guid <= 0xFFFFFFFF:
            raise GuidMappingExportError(f"asset has invalid uint32 GUID: {guid!r}")
        name = _asset_name(asset, language)
        if name is None:
            continue
        previous = names_by_guid.get(guid)
        if previous is not None and previous != name:
            raise GuidMappingExportError(
                f"conflicting names for GUID {guid}: {previous!r} vs {name!r}"
            )
        names_by_guid[guid] = name

    if not names_by_guid:
        raise GuidMappingExportError("asset-extractor produced no named GUID entries")

    document = {
        "schema": GUID_MAPPING_SCHEMA,
        "schema_version": GUID_MAPPING_SCHEMA_VERSION,
        "provenance": {
            "source": "operator-owned-anno1800-installation",
            "source_version": source_version.strip(),
            "mapping_version": mapping_version.strip(),
            "source_hash": source_hash.lower(),
        },
        "entries": {str(guid): names_by_guid[guid] for guid in sorted(names_by_guid)},
    }
    validate_guid_mapping(document)
    return document


@contextmanager
def _heartbeat(message: str) -> Iterator[None]:
    stop = threading.Event()
    print(message, file=sys.stderr, flush=True)

    def run() -> None:
        while not stop.wait(1.0):
            print(f"{message} still working...", file=sys.stderr, flush=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=0.1)


def _path_is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _validate_output_path(
    output_path: Path,
    *,
    config_path: Path,
    extractor_root: Path,
    config: Any,
) -> Path:
    """Return a resolved output path that cannot overwrite exporter/source inputs."""
    output = output_path.resolve()
    resolved_config = config_path.resolve()
    if output == resolved_config:
        raise GuidMappingExportError("output path must not overwrite asset-extractor config")

    protected_roots = {
        "asset-extractor root": extractor_root.resolve(),
        "game_path": Path(config.game_path).resolve(),
        "cache_path": Path(config.cache_path).resolve(),
        "assetbrowser_dir": Path(config.assetbrowser_dir).resolve(),
    }
    for label, root in protected_roots.items():
        if _path_is_within(output, root):
            raise GuidMappingExportError(
                f"output path must be outside protected {label}: {root}"
            )
    return output


def _atomic_write_text(path: Path, text: str) -> None:
    """Publish UTF-8 text atomically without exposing a partially written mapping."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _load_asset_extractor_assets(
    extractor_root: Path,
    config_path: Path,
    output_path: Path,
) -> tuple[list[Any], Path]:
    root = extractor_root.resolve()
    if not root.is_dir():
        raise GuidMappingExportError(f"asset-extractor root is not a directory: {root}")
    sys.path.insert(0, str(root))
    try:
        try:
            from assetextractor.extraction.utils import Config
            from assetextractor.parsing.core.assets import AssetCache
        except ImportError as exc:
            raise GuidMappingExportError(
                "could not import assetextractor from the supplied root; use a pinned checkout "
                "with its environment installed"
            ) from exc

        config = Config.from_json(config_path)
        safe_output = _validate_output_path(
            output_path,
            config_path=config_path,
            extractor_root=root,
            config=config,
        )
        with _heartbeat("Loading resolved asset-extractor cache"):
            cache = AssetCache.load(config)
        return list(cache.elements.values()), safe_output
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a provenance-aware GUID/name mapping from a pinned asset-extractor checkout."
    )
    parser.add_argument("--asset-extractor-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path, help="asset-extractor config.json")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--language", default="english")
    parser.add_argument(
        "--source-version",
        required=True,
        help="exact operator-visible Anno 1800 build/version identity",
    )
    parser.add_argument(
        "--source-hash",
        required=True,
        help="sha256 digest of the operator's manifest of material extracted inputs",
    )
    parser.add_argument(
        "--mapping-version",
        required=True,
        help="mapping revision including pinned extractor and exporter identity",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        assets, output_path = _load_asset_extractor_assets(
            args.asset_extractor_root,
            args.config,
            args.output,
        )
        document = build_mapping_document(
            assets,
            language=args.language,
            source_version=args.source_version,
            source_hash=args.source_hash,
            mapping_version=args.mapping_version,
        )
        _atomic_write_text(
            output_path,
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    except (GuidMappingExportError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Wrote {len(document['entries'])} GUID names to {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
