import struct
import unittest

import anno_save_probe as probe


class TransformDecodingTests(unittest.TestCase):
    def test_position_decodes_observed_float32_triplet(self):
        raw = struct.pack("<fff", 1506.0, 0.55, 1946.5)

        self.assertEqual(
            probe._decode_position(raw),
            [1506.0, 0.550000011920929, 1946.5],
        )

    def test_position_rejects_unobserved_sizes(self):
        self.assertIsNone(probe._decode_position(struct.pack("<ii", 1506, 1946)))
        self.assertIsNone(probe._decode_position(b"\x00" * 16))

    def test_direction_decodes_observed_float32(self):
        raw = struct.pack("<f", 4.71238899230957)

        self.assertEqual(probe._decode_direction(raw), 4.71238899230957)

    def test_direction_rejects_unobserved_sizes(self):
        self.assertIsNone(probe._decode_direction(b"\x00" * 8))


class MovementDiffTests(unittest.TestCase):
    @staticmethod
    def _state(source, position):
        return {
            "source": source,
            "sessions": [
                {
                    "guid": 180025,
                    "id": 3,
                    "player_buildings": [
                        {
                            "area_id": 8836,
                            "id": 37950331027457,
                            "guid": 101290,
                            "position": position,
                            "components": ["Building", "LogisticNode", "Warehouse"],
                        }
                    ],
                }
            ],
        }

    def test_stable_object_position_change_is_one_move_without_lifecycle_noise(self):
        before = self._state("Autosave 711.a7s", [1506.0, 0.550000011920929, 1946.5])
        after = self._state("Autosave 712.a7s", [1386.5, 0.550000011920929, 1873.0])

        diff = probe.diff_states(before, after)

        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(diff["moved_count"], 1)
        self.assertEqual(
            diff["moved"],
            [
                {
                    "session_guid": 180025,
                    "area_id": 8836,
                    "id": 37950331027457,
                    "guid": 101290,
                    "from": [1506.0, 0.550000011920929, 1946.5],
                    "to": [1386.5, 0.550000011920929, 1873.0],
                    "components": ["Building", "LogisticNode", "Warehouse"],
                }
            ],
        )

    def test_unchanged_position_does_not_emit_move(self):
        position = [1376.5, 2.3828125, 1280.5]
        diff = probe.diff_states(
            self._state("before.a7s", position),
            self._state("after.a7s", list(position)),
        )

        self.assertEqual(diff["moved_count"], 0)
        self.assertEqual(diff["moved"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
