from __future__ import annotations

import random
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import anno_save_probe as probe
from decompression import (
    DEFAULT_DECOMPRESSION_CHUNK_BYTES,
    zlib_to_file as candidate_zlib_to_file,
)


REFERENCE_CHUNK_BYTES = 1 << 20
CANDIDATE_CHUNK_BYTES = DEFAULT_DECOMPRESSION_CHUNK_BYTES


def _decompress_with_chunk(compressed: bytes, chunk_size: int) -> bytes:
    dec = zlib.decompressobj()
    out = bytearray()
    view = memoryview(compressed)
    for offset in range(0, len(view), chunk_size):
        out.extend(dec.decompress(view[offset:offset + chunk_size]))
    out.extend(dec.flush())
    return bytes(out)


class DecompressionChunkOracleTests(unittest.TestCase):
    @staticmethod
    def _payload() -> bytes:
        # Deterministic, poorly-compressible data keeps the compressed stream above
        # the historical 1 MiB step so both reference and production/candidate
        # paths exercise multiple input chunks.
        return random.Random(0xA1800).randbytes(1_200_000)

    def test_reference_and_candidate_chunks_produce_identical_bytes(self) -> None:
        payload = self._payload()
        compressed = zlib.compress(payload, level=6)
        self.assertGreater(len(compressed), REFERENCE_CHUNK_BYTES)

        reference = _decompress_with_chunk(compressed, REFERENCE_CHUNK_BYTES)
        candidate = _decompress_with_chunk(compressed, CANDIDATE_CHUNK_BYTES)

        self.assertEqual(payload, reference)
        self.assertEqual(reference, candidate)

    def test_candidate_helper_matches_reference_and_production(self) -> None:
        payload = self._payload()
        compressed = zlib.compress(payload, level=6)
        reference = _decompress_with_chunk(compressed, REFERENCE_CHUNK_BYTES)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            production_output = tmp_path / "production.bin"
            candidate_output = tmp_path / "candidate.bin"

            production_total = probe.zlib_to_file(compressed, production_output)
            candidate_total = candidate_zlib_to_file(compressed, candidate_output)

            self.assertEqual(len(payload), production_total)
            self.assertEqual(production_total, candidate_total)
            self.assertEqual(reference, production_output.read_bytes())
            self.assertEqual(reference, candidate_output.read_bytes())

    def test_production_uses_named_16_kib_input_chunk(self) -> None:
        payload = self._payload()
        compressed = zlib.compress(payload, level=6)
        original_decompressobj = probe.zlib.decompressobj
        observed_input_sizes: list[int] = []

        class RecordingDecompressor:
            def __init__(self):
                self._inner = original_decompressobj()

            def decompress(self, data):
                observed_input_sizes.append(len(data))
                return self._inner.decompress(data)

            def flush(self):
                return self._inner.flush()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "production.bin"
            with mock.patch.object(
                probe.zlib,
                "decompressobj",
                side_effect=lambda: RecordingDecompressor(),
            ):
                total = probe.zlib_to_file(compressed, output)

            self.assertEqual(CANDIDATE_CHUNK_BYTES, probe.DECOMPRESSION_CHUNK_BYTES)
            self.assertGreater(len(observed_input_sizes), 1)
            self.assertLessEqual(max(observed_input_sizes), CANDIDATE_CHUNK_BYTES)
            self.assertEqual(len(payload), total)
            self.assertEqual(payload, output.read_bytes())

    def test_candidate_helper_rejects_non_positive_chunk_size(self) -> None:
        compressed = zlib.compress(b"payload")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "data.bin"
            for chunk_size in (0, -1):
                with self.subTest(chunk_size=chunk_size):
                    with self.assertRaisesRegex(ValueError, "chunk size must be positive"):
                        candidate_zlib_to_file(
                            compressed,
                            output,
                            chunk_bytes=chunk_size,
                        )


if __name__ == "__main__":
    unittest.main()
