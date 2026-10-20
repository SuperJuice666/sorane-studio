import copy
import functools
import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from song_import.build import write_json
from song_import.import_job import Job, check_text, fingerprint, locked, read, sha, start, tree
from song_import.narrate import FRAME_RATE, SPEEDS, narrate, timing
from song_import.phonemes import phones
from song_import.preview import Handler
from song_import.schema import validate


def wav(seconds=2, rate=44100):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * round(seconds * rate))
    return buffer.getvalue()


def lyric():
    return {
        "schemaVersion": 1,
        "id": "sample",
        "title": "朝",
        "artist": "Test",
        "lines": [
            {
                "jp": "朝",
                "section": "主歌",
                "tokens": [{"jp": "朝", "kana": "あさ", "romaji": "asa"}],
            }
        ],
        "issues": [],
    }


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.wav"
        self.source.write_bytes(wav())
        self.config = self.root / "config.json"
        write_json(
            self.config,
            {
                "vocals": str(self.source),
                "narration": {"provider": "none"},
                "ffmpeg": os.environ.get("TEST_FFMPEG", "ffmpeg"),
            },
        )
        self.path = start(self.source, self.root / "job", "sample", "朝", "Test", self.config)
        (self.path / "source-text.txt").write_text("朝", encoding="utf-8")
        write_json(
            self.path / "sources.json",
            {
                "version": "test recording",
                "issues": [],
                "sources": [
                    {
                        "reference": "original test fixture",
                        "retrievedAt": "2026-10-20",
                        "textFile": "source-text.txt",
                        "sha256": sha(self.path / "source-text.txt"),
                    }
                ],
            },
        )
        write_json(self.path / "draft.json", lyric())
        self.job = Job(self.path)

    def test_task_keeps_instruction_snapshot_when_template_changes(self):
        checkout = self.root / "checkout"
        template = checkout / "prompts/import-agent.md"
        template.parent.mkdir(parents=True)
        template.write_text("First instruction revision\n", encoding="utf-8")
        first_sha = hashlib.sha256(template.read_text("utf-8").encode("utf-8")).hexdigest()
        with patch("song_import.import_job.PROJECT", checkout):
            first = start(self.source, self.root / "snapshot", "first", "朝", "Test", self.config)
            saved = (first / "TASK.md").read_text("utf-8")
            self.assertIn("First instruction revision", saved)
            self.assertIn("docs/import-lessons.md", saved)
            self.assertIn("prompts/lyrics.md", saved)
            self.assertEqual(read(first / "job.json")["agentInstructionsSha256"], first_sha)
            template.write_text("Second instruction revision\n", encoding="utf-8")
            second = start(self.source, self.root / "new-task", "second", "朝", "Test", self.config)
        self.assertEqual((first / "TASK.md").read_text("utf-8"), saved)
        self.assertIn("Second instruction revision", (second / "TASK.md").read_text("utf-8"))
        self.assertNotEqual(read(second / "job.json")["agentInstructionsSha256"], first_sha)

    def test_source_snapshot_and_unknown_text_block_alignment(self):
        check_text(lyric(), read(self.path / "sources.json"), self.path)
        (self.path / "source-text.txt").write_text("changed")
        with self.assertRaisesRegex(ValueError, "snapshot"):
            check_text(lyric(), read(self.path / "sources.json"), self.path)
        with self.assertRaisesRegex(ValueError, "already exists"):
            start(self.source, self.path, "sample", "朝", "Test")

    def test_source_line_breaks_reject_splitting_and_merging_same_text(self):
        song = lyric()
        song["lines"][0].update(
            jp="朝の光",
            tokens=[
                {"jp": "朝", "kana": "あさ", "romaji": "asa"},
                {"jp": "の", "kana": "の", "romaji": "no"},
                {"jp": "光", "kana": "ひかり", "romaji": "hikari"},
            ],
        )
        text = self.path / "source-text.txt"
        text.write_text("朝の光！", encoding="utf-8")
        sources = read(self.path / "sources.json")
        sources["sources"][0]["sha256"] = sha(text)
        sources.update(lineSource=sources["sources"][0]["reference"], canonicalLines=["朝 の光！"])
        check_text(song, sources, self.path)
        split = copy.deepcopy(song)
        split["lines"] = [
            {"jp": "朝の", "section": "主歌", "tokens": song["lines"][0]["tokens"][:2]},
            {"jp": "光", "section": "主歌", "tokens": song["lines"][0]["tokens"][2:]},
        ]
        with self.assertRaisesRegex(ValueError, "source line breaks"):
            check_text(split, sources, self.path)
        sources["canonicalLines"] = ["朝の", "光"]
        check_text(split, sources, self.path)
        with self.assertRaisesRegex(ValueError, "source line breaks"):
            check_text(song, sources, self.path)
        sources["lineSource"] = "unrecorded source"
        with self.assertRaisesRegex(ValueError, "lineSource"):
            check_text(split, sources, self.path)

    def test_source_sections_preserved_and_ranges_cover_each_line(self):
        song = lyric()
        song["lines"] = [copy.deepcopy(song["lines"][0]) for _ in range(3)]
        for line, name in zip(song["lines"], ["第1段", "第1段", "第2段"]):
            line["section"] = name
        sources = read(self.path / "sources.json")
        sources.update(
            lineSource=sources["sources"][0]["reference"],
            canonicalLines=[line["jp"] for line in song["lines"]],
            canonicalSections=[
                {"startLine": 1, "endLine": 2, "name": "第1段"},
                {"startLine": 3, "endLine": 3, "name": "第2段"},
            ],
        )
        check_text(song, sources, self.path)
        song["lines"][1]["section"] = "第2段"
        with self.assertRaisesRegex(ValueError, "preserve source groups"):
            check_text(song, sources, self.path)
        song["lines"][1]["section"] = "第1段"
        sources["canonicalSections"][1]["startLine"] = 2
        with self.assertRaisesRegex(ValueError, "cover source lines"):
            check_text(song, sources, self.path)
        sources["canonicalSections"] = []
        with self.assertRaisesRegex(ValueError, "nonempty source groups"):
            check_text(song, sources, self.path)

    def test_stage_resume_detects_inputs_and_output_tampering(self):
        calls = []

        def action(out):
            calls.append(out)
            (out / "result").write_text("first")

        first = self.job.stage("example", {"source": 1}, action)
        self.assertEqual(first, self.job.stage("example", {"source": 1}, action))
        (first / "result").write_text("tampered")
        second = self.job.stage("example", {"source": 1}, action)
        self.assertNotEqual(first, second)
        self.job.stage("example", {"source": 2}, action)
        self.assertEqual(len(calls), 3)

    def test_failure_keeps_last_success_and_retry_does_not_overwrite(self):
        first = self.job.stage("example", 1, lambda out: (out / "ok").write_text("ok"))

        def fail(out):
            (out / "partial").write_text("partial")
            raise RuntimeError("failed")

        with self.assertRaises(RuntimeError):
            self.job.stage("example", 2, fail)
        self.assertEqual(self.path / self.job.state["example"]["directory"], first)
        self.assertEqual(len(list((self.path / "runs").glob("example-*"))), 2)

    def test_lock_prevents_concurrent_mutation(self):
        with locked(self.path):
            with self.assertRaisesRegex(ValueError, "locked"):
                with locked(self.path):
                    pass
        self.assertFalse((self.path / ".import.lock").exists())

    @staticmethod
    def fake_alignment(job, stems):
        def action(out):
            song = read(job.path / "draft.json")
            song["duration"] = 2
            song["lines"][0].update(start=0.2, end=1.5)
            song["lines"][0]["tokens"][0].update(start=0.2, end=1.5)
            write_json(out / "result/draft.json", song)
            write_json(
                out / "result/audit.json",
                {
                    "tokens": [
                        {
                            "index": 0,
                            "jp": "朝",
                            "start": 0.2,
                            "end": 1.5,
                            "flags": ["ctc-disagreement"],
                            "candidates": [],
                            "ctc": {"start": 0.3, "end": 1.5},
                        }
                    ]
                },
            )

        return (
            job.stage(
                "align", [sha(job.path / "draft.json"), sha(job.path / "sources.json")], action
            )
            / "result"
        )

    def approve(self):
        report = read(self.path / "alignment-template.json")
        report["reviewer"] = "test fixture; not a listening claim"
        for check in report["checks"].values():
            check.update(passed=True, evidence="synthetic fixture assertion")
        report["decisions"][0].update(status="confirmed", evidence="fixture assertion")
        write_json(self.path / "alignment-review.json", report)
        self.job.accept(self.path / "alignment-review.json")

    def test_review_rejects_missing_checks_stale_times_and_changed_sources(self):
        alignment = self.fake_alignment(self.job, None)
        from song_import.import_review import create_review

        create_review(self.path, alignment, self.path / "source.wav", self.path / "source.wav")
        report = read(self.path / "alignment-template.json")
        with self.assertRaises(ValueError):
            self.job.check_alignment_review(report, alignment)
        report["reviewer"] = "fixture"
        for check in report["checks"].values():
            check.update(passed=True, evidence="fixture")
        report["decisions"][0].update(status="confirmed", evidence="fixture")
        self.job.check_alignment_review(report, alignment)
        report["reviewedSha256"] = "stale"
        with self.assertRaisesRegex(ValueError, "changed after review"):
            self.job.check_alignment_review(report, alignment)
        report["reviewedSha256"] = sha(self.path / "reviewed.json")
        report["inputSha256"] = "stale"
        with self.assertRaisesRegex(ValueError, "Sources, model"):
            self.job.check_alignment_review(report, alignment)

    @unittest.skipUnless(
        shutil.which(os.environ.get("TEST_FFMPEG", "ffmpeg")), "FFmpeg not installed"
    )
    def test_audio_to_preview_and_install_with_stub_alignment(self):
        with patch.object(Job, "align", self.fake_alignment):
            self.assertIn("Review alignment", self.job.advance())
            self.assertNotIn("package", self.job.state)
            self.approve()
            self.assertIn("Package ready", self.job.advance())
            packaged = self.path / self.job.state["package"]["directory"] / "song"
            validate(read(packaged / "song.json"), packaged)
            self.assertTrue(
                (self.path / self.job.state["preview"]["directory"] / "site/index.html").exists()
            )
            report = read(self.path / "playback-template.json")
            write_json(self.path / "playback-review.json", report)
            with self.assertRaises(ValueError):
                self.job.install(self.path / "playback-review.json", self.root / "library")
            report["reviewer"] = "automated fixture; not a listening claim"
            for check in report["checks"].values():
                check.update(passed=True, evidence="fixture assertion")
            write_json(self.path / "playback-review.json", report)
            destination = self.job.install(
                self.path / "playback-review.json", self.root / "library"
            )
            self.assertEqual(fingerprint(tree(destination)), report["packageSha256"])
            with self.assertRaisesRegex(ValueError, "already installed"):
                self.job.install(self.path / "playback-review.json", self.root / "library")


class PreviewTests(unittest.TestCase):
    def test_audio_ranges_head_suffix_and_invalid_ranges(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "test.wav").write_bytes(b"0123456789")
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), functools.partial(Handler, directory=folder)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/test.wav"
                for header, expected in (
                    ("bytes=2-5", b"2345"),
                    ("bytes=-3", b"789"),
                    ("bytes=7-", b"789"),
                ):
                    req = urllib.request.Request(url, headers={"Range": header})
                    with urllib.request.urlopen(req) as response:
                        self.assertEqual(response.status, 206)
                        self.assertEqual(response.read(), expected)
                        self.assertEqual(response.headers["Accept-Ranges"], "bytes")
                with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as response:
                    self.assertEqual(response.headers["Content-Length"], "10")
                    self.assertEqual(response.read(), b"")
                for header in ("bytes=99-", "bytes=8-2", "bytes=-0", "bytes=0-1,4-5"):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(
                            urllib.request.Request(url, headers={"Range": header})
                        )
                    self.assertEqual(error.exception.code, 416)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class NarrationTests(unittest.TestCase):
    def test_reading_fallback_is_checked_and_keeps_both_queries(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "song"
            directory.mkdir()
            write_json(directory / "song.json", lyric())
            queried = []

            def engine(base, endpoint, params, data=None):
                if endpoint == "/audio_query":
                    queried.append(params["text"])
                    query = self.query()
                    if params["text"] == "朝":
                        query["accent_phrases"][0]["moras"][0]["vowel"] = "i"
                    return json.dumps(query).encode()
                _, duration = timing(data, lyric()["lines"][0]["tokens"])
                return wav(duration, 24000)

            with patch("song_import.narrate.request", side_effect=engine):
                narrate(directory, {"provider": "voicevox"})
            self.assertEqual(queried, ["朝", "アサ"])
            evidence = directory.parent / "narration-queries"
            self.assertEqual(read(evidence / "1-input-1.json")["text"], "朝")
            self.assertEqual(read(evidence / "1-input-2.json")["text"], "アサ")
            self.assertEqual(len(list((directory / "reading").glob("*.wav"))), 3)

    def test_voicevox_long_vowel_labels_and_foreign_mora(self):
        self.assertEqual(phones("でぃす"), ["d", "i", "s", "u"])
        self.assertEqual(phones("ちぇんじ"), ["ch", "e", "N", "j", "i"])
        self.assertEqual(phones("きれい"), ["k", "i", "r", "e", "e"])
        query = self.query()
        query["accent_phrases"][0]["moras"] = [
            {
                "text": "キ",
                "consonant": "k",
                "consonant_length": 0.05,
                "vowel": "i",
                "vowel_length": 0.1,
            },
            {
                "text": "レ",
                "consonant": "r",
                "consonant_length": 0.05,
                "vowel": "e",
                "vowel_length": 0.1,
            },
            {"text": "イ", "consonant_length": None, "vowel": "i", "vowel_length": 0.1},
            {
                "text": "ディ",
                "consonant": "d",
                "consonant_length": 0.05,
                "vowel": "i",
                "vowel_length": 0.1,
            },
            {
                "text": "ス",
                "consonant": "s",
                "consonant_length": 0.05,
                "vowel": "U",
                "vowel_length": 0.1,
            },
        ]
        tokens = [{"kana": "きれい"}, {"kana": "でぃす"}]
        marks, duration = timing(query, tokens)
        self.assertEqual(len(marks), 2)
        self.assertEqual(marks[0]["end"], marks[1]["start"])
        query["accent_phrases"][0]["moras"][2]["vowel"] = "e"
        self.assertEqual(timing(query, tokens), (marks, duration))
        query["accent_phrases"][0]["moras"][2]["vowel"] = "a"
        with self.assertRaisesRegex(ValueError, "reading differs"):
            timing(query, tokens)

    def test_incompatible_engine_duration_is_not_scaled_to_fit(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "song"
            directory.mkdir()
            write_json(directory / "song.json", lyric())

            def engine(base, endpoint, params, data=None):
                return (
                    json.dumps(self.query()).encode()
                    if endpoint == "/audio_query"
                    else wav(5, 24000)
                )

            with patch("song_import.narrate.request", side_effect=engine):
                with self.assertRaisesRegex(ValueError, "duration differs"):
                    narrate(directory, {"provider": "voicevox"})
            self.assertNotIn("narration", read(directory / "song.json")["lines"][0])

    def query(self):
        return {
            "speedScale": 1,
            "prePhonemeLength": 0.06,
            "postPhonemeLength": 0.1,
            "accent_phrases": [
                {
                    "moras": [
                        {"text": "ア", "vowel": "a", "vowel_length": 0.1, "consonant_length": None},
                        {
                            "text": "サ",
                            "vowel": "a",
                            "vowel_length": 0.1,
                            "consonant": "s",
                            "consonant_length": 0.05,
                        },
                    ],
                    "pause_mora": None,
                }
            ],
        }

    def test_timing_uses_engine_frames_and_rejects_changed_pronunciation(self):
        query = self.query()
        tokens = lyric()["lines"][0]["tokens"]
        marks, duration = timing(query, tokens)
        self.assertAlmostEqual(marks[0]["start"], round(0.06 * FRAME_RATE) / FRAME_RATE)
        query["speedScale"] = 0.55
        slower, longer = timing(query, tokens)
        self.assertGreater(longer, duration)
        self.assertGreater(slower[0]["end"], marks[0]["end"])
        with self.assertRaisesRegex(ValueError, "reading differs"):
            timing(query, [{"kana": "よる"}])

    def test_three_syntheses_and_duration_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "song"
            directory.mkdir()
            write_json(directory / "song.json", lyric())
            scales = []

            def engine(base, endpoint, params, data=None):
                if endpoint == "/audio_query":
                    self.assertEqual(params["text"], "朝")
                    return json.dumps(self.query()).encode()
                scales.append(data["speedScale"])
                _, length = timing(data, lyric()["lines"][0]["tokens"])
                return wav(length, 24000)

            with patch("song_import.narrate.request", side_effect=engine):
                narrate(directory, {"provider": "voicevox"})
            result = read(directory / "song.json")["lines"][0]["narration"]
            self.assertEqual(set(result), set(SPEEDS))
            self.assertEqual(scales, list(SPEEDS.values()))
            self.assertGreater(result["verySlow"]["duration"], result["normal"]["duration"])
            bad = copy.deepcopy(self.query())
            bad["accent_phrases"][0]["moras"][0]["vowel"] = "i"
            with self.assertRaises(ValueError):
                timing(bad, lyric()["lines"][0]["tokens"])


if __name__ == "__main__":
    unittest.main()
