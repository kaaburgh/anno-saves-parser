from __future__ import annotations

import random
import tempfile
import unittest
import zlib
from pathlib import Path

from anno_save_probe import zlib_to_file


REFERENCE_CHUNK_BYTES = 1 << 20
CANDIDATE_CHUNK_BYTES = 16 << 10


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
        # the current 1 MiB production step so both reference and candidate paths
        # exercise multiple input chunks.
        return random.Random(0xA1800).randbytes(1_200_000)

    def test_reference_and_candidate_chunks_produce_identical_bytes(self) -> None:
        payload = self._payload()
        compressed = zlib.compress(payload, level=6)
        self.assertGreater(len(compressed), REFERENCE_CHUNK_BYTES)

        reference = _decompress_with_chunk(compressed, REFERENCE_CHUNK_BYTES)
        candidate = _decompress_with_chunk(compressed, CANDIDATE_CHUNK_BYTES)

        self.assertEqual(payload, reference)
        self.assertEqual(reference, candidate)

    def test_production_decompressor_matches_candidate_oracle(self) -> None:
        payload = self._payload()
        compressed = zlib.compress(payload, level=6)
        candidate = _decompress_with_chunk(compressed, CANDIDATE_CHUNK_BYTES)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "data.bin"
            total = zlib_to_file(compressed, output)

            self.assertEqual(len(payload), total)
            self.assertEqual(candidate, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
