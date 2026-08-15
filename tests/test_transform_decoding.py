import struct
import unittest

import anno_save_probe as probe


class TransformDecodingTests(unittest.TestCase):
    def test_position_decodes_observed_float32_triplet(self):
        raw = struct.pack("<fff", 123.5, 4.25, 987.75)

        self.assertEqual(probe._decode_position(raw), [123.5, 4.25, 987.75])

    def test_position_rejects_unobserved_sizes(self):
        self.assertIsNone(probe._decode_position(struct.pack("<ii", 123, 988)))
        self.assertIsNone(probe._decode_position(b"\x00" * 16))

    def test_direction_decodes_observed_float32(self):
        raw = struct.pack("<f", 1.5)

        self.assertEqual(probe._decode_direction(raw), 1.5)

    def test_direction_rejects_unobserved_sizes(self):
        self.assertIsNone(probe._decode_direction(b"\x00" * 8))


class MovementDiffTests(unittest.TestCase):
    @staticmethod
    def _state(source, position):
        return {
            "source": source,
            "sessions": [
                {
                    "guid": 123456,
                    "id": 7,
                    "player_buildings": [
                        {
                            "area_id": 42,
                            "id": 9001,
                            "guid": 777001,
                            "position": position,
                            "components": ["Building", "Warehouse"],
                        }
                    ],
                }
            ],
        }

    def test_stable_object_position_change_is_one_move_without_lifecycle_noise(self):
        before = self._state("before.a7s", [10.5, 2.25, 30.75])
        after = self._state("after.a7s", [12.5, 2.25, 34.75])

        diff = probe.diff_states(before, after)

        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(diff["moved_count"], 1)
        self.assertEqual(
            diff["moved"],
            [
                {
                    "session_guid": 123456,
                    "area_id": 42,
                    "id": 9001,
                    "guid": 777001,
                    "from": [10.5, 2.25, 30.75],
                    "to": [12.5, 2.25, 34.75],
                    "components": ["Building", "Warehouse"],
                }
            ],
        )

    def test_unchanged_position_does_not_emit_move(self):
        position = [20.0, 3.5, 40.0]
        diff = probe.diff_states(
            self._state("before.a7s", position),
            self._state("after.a7s", list(position)),
        )

        self.assertEqual(diff["moved_count"], 0)
        self.assertEqual(diff["moved"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
