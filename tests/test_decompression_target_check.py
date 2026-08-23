import json
import tempfile
import unittest
import zlib
from pathlib import Path

import anno_save_probe as probe
import decompression_target_check as target_check
from decompression import zlib_to_file as stream_zlib_to_file


class DecompressionTargetCheckTests(unittest.TestCase):
    def test_compare_save_binds_input_and_requires_equal_canonical_state(self):
        payload = (b"decompression-target-check-" * 10000) + bytes(range(256)) * 64
        compressed = zlib.compress(payload)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save = root / "private-name-is-not-emitted.a7s"
            save.write_bytes(b"synthetic-source-identity")

            def canonicalize_fn(_save, work_dir, _progress):
                dest = work_dir / "data.bin"
                probe.zlib_to_file(compressed, dest, None)
                decoded = dest.read_bytes()
                return {
                    "schema": "test/canonical",
                    "schema_version": 1,
                    "source": {"save_name": "redacted"},
                    "payload_sha256": __import__("hashlib").sha256(decoded).hexdigest(),
                }

            result = target_check.compare_save(
                save,
                repeats=2,
                canonicalize_fn=canonicalize_fn,
                decompressor_fn=stream_zlib_to_file,
            )

        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(
            [run["chunk_bytes"] for run in result["runs"]],
            [target_check.REFERENCE_CHUNK_BYTES, target_check.DEFAULT_DECOMPRESSION_CHUNK_BYTES],
        )
        self.assertEqual(
            result["runs"][0]["canonical_sha256"],
            result["runs"][1]["canonical_sha256"],
        )
        self.assertEqual([len(run["elapsed_seconds"]) for run in result["runs"]], [2, 2])
        self.assertNotIn("private-name-is-not-emitted", json.dumps(result))

    def test_compare_save_fails_when_candidate_changes_canonical_state(self):
        payload = b"candidate-mismatch" * 1000
        compressed = zlib.compress(payload)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save = root / "source.a7s"
            save.write_bytes(b"synthetic-source")

            def canonicalize_fn(_save, work_dir, _progress):
                dest = work_dir / "data.bin"
                probe.zlib_to_file(compressed, dest, None)
                return {"size": dest.stat().st_size}

            def mismatching_decompressor(compressed_bytes, dest, progress=None, *, chunk_bytes):
                written = stream_zlib_to_file(
                    compressed_bytes,
                    dest,
                    progress,
                    chunk_bytes=chunk_bytes,
                )
                if chunk_bytes == target_check.DEFAULT_DECOMPRESSION_CHUNK_BYTES:
                    with dest.open("ab") as out:
                        out.write(b"x")
                    written += 1
                return written

            with self.assertRaisesRegex(RuntimeError, "canonical state differs"):
                target_check.compare_save(
                    save,
                    canonicalize_fn=canonicalize_fn,
                    decompressor_fn=mismatching_decompressor,
                )

    def test_atomic_report_contains_no_source_paths(self):
        report = {
            "schema": target_check.SCHEMA,
            "schema_version": target_check.SCHEMA_VERSION,
            "inputs": [{"source_sha256": "0" * 64, "source_size": 1, "runs": []}],
        }
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "evidence.json"
            target_check._write_json_atomic(output, report)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
            self.assertEqual(list(Path(td).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
