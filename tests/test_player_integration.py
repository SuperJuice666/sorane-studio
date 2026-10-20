"""Optional release check against an independently downloaded player checkout."""

import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

from song_import.contract import check
from song_import.media import pack
from song_import.schema import validate


@unittest.skipUnless(
    os.getenv("PLAYER_SOURCE") and shutil.which(os.getenv("TEST_FFMPEG", "ffmpeg")),
    "Set PLAYER_SOURCE and install FFmpeg for cross-project release checks",
)
class PlayerIntegration(unittest.TestCase):
    def test_generated_media_is_accepted_and_built_by_player(self):
        player = Path(os.environ["PLAYER_SOURCE"]).resolve()
        check(player)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "tone.wav"
            with wave.open(str(audio), "wb") as stream:
                stream.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                stream.writeframes(
                    b"".join(
                        struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / 44100)))
                        for i in range(88200)
                    )
                )
            token = {"jp": "朝", "kana": "あさ", "romaji": "asa", "start": 0.2, "end": 1.5}
            song = {
                "schemaVersion": 1,
                "id": "fixture",
                "title": "朝",
                "artist": "Original tone fixture",
                "duration": 2,
                "lines": [
                    {"jp": "朝", "section": "Verse", "start": 0.2, "end": 1.5, "tokens": [token]}
                ],
            }
            source = root / "draft.json"
            source.write_text(json.dumps(song), encoding="utf-8")
            package = root / "songs/fixture"
            pack(source, audio, audio, package, os.getenv("TEST_FFMPEG", "ffmpeg"))
            validate(json.loads((package / "song.json").read_text("utf-8")), package)
            for arguments in (
                ["validate", str(package / "song.json")],
                ["build", "--songs", str(root / "songs"), "--output", str(root / "site")],
            ):
                subprocess.run(
                    [sys.executable, "-m", "lyric_player", *arguments], cwd=player, check=True
                )
            library = json.loads((root / "site/library.json").read_text("utf-8"))
            self.assertEqual(library["songs"][0]["lines"][0]["tokens"][0], token)
            self.assertEqual(len(library["chunks"]), 3)
            for variant in library["songs"][0]["audio"].values():
                self.assertTrue((root / "site" / variant["src"]).is_file())
