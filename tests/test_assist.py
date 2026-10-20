import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from song_import.assist import assist
from song_import.build import PROJECT


class AssistTests(unittest.TestCase):
    def test_request_uses_current_rules_and_records_input_identity_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.json"
            data = {"title": "Example", "artist": "Test", "sources": []}
            source.write_text(json.dumps(data), encoding="utf-8")
            output = root / "candidate.json"
            response = {
                "model": "returned-model",
                "usage": {"total_tokens": 12},
                "choices": [{"message": {"content": "invalid JSON"}}],
            }
            with patch.dict(
                os.environ,
                {
                    "AI_BASE_URL": "http://127.0.0.1:9999",
                    "AI_MODEL": "requested-model",
                    "AI_API_KEY": "test",
                },
            ):
                with patch(
                    "song_import.assist.urllib.request.urlopen",
                    return_value=io.BytesIO(json.dumps(response).encode()),
                ) as request:
                    with self.assertRaises(json.JSONDecodeError):
                        assist("lyrics", source, output)
            body = json.loads(request.call_args.args[0].data)
            rules = (PROJECT / "prompts/lyrics.md").read_text("utf-8")
            self.assertEqual(body["messages"][0], {"role": "system", "content": rules})
            self.assertEqual(json.loads(body["messages"][1]["content"]), data)
            record = json.loads(output.with_suffix(".usage.json").read_text("utf-8"))
            self.assertEqual(
                record["instructionSha256"], hashlib.sha256(rules.encode()).hexdigest()
            )
            self.assertEqual(
                record["inputSha256"],
                hashlib.sha256(body["messages"][1]["content"].encode()).hexdigest(),
            )
            self.assertEqual(record["model"], "returned-model")
            self.assertEqual(record["usage"], {"total_tokens": 12})
            self.assertFalse(output.exists())
