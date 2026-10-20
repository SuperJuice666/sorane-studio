import unittest

from song_import.align import resolve
from song_import.phonemes import phones


class Alignment(unittest.TestCase):
    def test_japanese_phone_groups(self):
        self.assertEqual(phones("きょう"), ["ky", "o", "o"])
        self.assertEqual(phones("カッタ"), ["k", "a", "cl", "t", "a"])

    def test_ctc_onset_check_does_not_extend_a_release(self):
        candidates = [
            {"start": 1.1, "end": 2},
            {"start": 1.12, "end": 2.02},
            {"start": 0, "end": 4},
        ]
        result = resolve(candidates, {"start": 1.05, "end": 3, "confidence": 0.8})
        self.assertEqual(result["start"], 1.05)
        self.assertAlmostEqual(result["end"], 2.01)
        self.assertIn("end-disagreement", result["flags"])


if __name__ == "__main__":
    unittest.main()
