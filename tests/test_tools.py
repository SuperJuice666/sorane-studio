import unittest

from song_import.align import resolve
from song_import.narrate_edge import token_times
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


class SpeechBoundaries(unittest.TestCase):
    def test_engine_word_can_span_multiple_display_tokens(self):
        result = token_times(
            ["きみ", "の"], [{"text": "きみの", "offset": 10000000, "duration": 9000000}]
        )
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0]["start"], 1)
        self.assertAlmostEqual(result[0]["end"], 1.6)
        self.assertAlmostEqual(result[1]["start"], 1.6)
        self.assertAlmostEqual(result[1]["end"], 1.9)

    def test_unmatched_engine_reading_stops_packaging(self):
        with self.assertRaises(ValueError):
            token_times(["きみ"], [{"text": "ぼく", "offset": 0, "duration": 1000000}])


if __name__ == "__main__":
    unittest.main()
