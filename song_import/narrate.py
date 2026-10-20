"""Generate Japanese speech and token times from a local VOICEVOX engine query."""

import copy
import io
import json
import urllib.request
import wave
from urllib.parse import urlencode, urlsplit

from .build import write_json
from .phonemes import phones

FRAME_RATE = 24000 / 256
SPEEDS = {"normal": 1.0, "slow": 0.75, "verySlow": 0.55}


def request(base, endpoint, parameters, data=None):
    parsed = urlsplit(base)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        raise ValueError("The bundled VOICEVOX adapter only connects to a local engine")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("VOICEVOX URL must not contain credentials or query parameters")
    req = urllib.request.Request(
        base.rstrip("/") + endpoint + "?" + urlencode(parameters),
        data=json.dumps(data).encode() if data is not None else b"",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return response.read()


def timing(query, tokens):
    """Use the same per-phoneme frame rounding as the engine, never character averaging."""
    scale = query["speedScale"]

    def frames(seconds):
        return round(seconds / scale * FRAME_RATE)

    cursor = frames(query["prePhonemeLength"])
    observed, intervals = [], []
    for phrase in query["accent_phrases"]:
        for mora in phrase["moras"]:
            start = cursor
            cursor += frames(mora.get("consonant_length") or 0) + frames(mora["vowel_length"])
            group = []
            if mora.get("consonant"):
                group.append(mora["consonant"])
            vowel = mora["vowel"]
            group.append("cl" if vowel == "cl" else vowel if vowel == "N" else vowel.lower())
            observed.extend(group)
            intervals.extend([(start / FRAME_RATE, cursor / FRAME_RATE)] * len(group))
        if phrase.get("pause_mora"):
            pause = query.get("pauseLength")
            if pause is None:
                pause = phrase["pause_mora"]["vowel_length"]
            cursor += frames(pause * query.get("pauseLengthScale", 1))
    # Speech queries may retain /e i/ where singing alignment normalizes /e e/.
    # Both have the same two mora positions; use the engine's actual durations.
    expected = [
        phones(token.get("narrationKana", token["kana"]), normalize_long_vowels=False)
        for token in tokens
    ]
    allowed = []
    for group in expected:
        for index, phone in enumerate(group):
            alternatives = {phone}
            if index and (group[index - 1], phone) in (("e", "i"), ("o", "u")):
                alternatives.add(group[index - 1])
            allowed.append(alternatives)
    if len(observed) != len(allowed) or any(
        phone not in options for phone, options in zip(observed, allowed)
    ):
        raise ValueError(
            "TTS reading differs from token kana; inspect the saved query before changing text"
        )
    marks, offset = [], 0
    for group in expected:
        selected = intervals[offset : offset + len(group)]
        offset += len(group)
        marks.append({"start": selected[0][0], "end": selected[-1][1]})
    cursor += frames(query["postPhonemeLength"])
    return marks, cursor / FRAME_RATE


def narrate(directory, config):
    song_path = directory / "song.json"
    song = json.loads(song_path.read_text("utf-8"))
    output = directory / "reading"
    output.mkdir()
    base, speaker = config.get("url", "http://127.0.0.1:50021"), config.get("speaker", 3)
    # Query JSON belongs to processing evidence, not the public song package.
    evidence = directory.parent / "narration-queries"
    evidence.mkdir()
    for index, line in enumerate(song["lines"]):
        tokens = line["tokens"]
        # Explicit phrase ends let an agent preserve particles and auxiliaries with their word.
        breaks = line.get("narrationBreaks", [])
        if any(type(i) is not int or not 0 <= i < len(tokens) - 1 for i in breaks):
            raise ValueError("narrationBreaks must be token indexes before the final token")
        text = "".join(
            t.get("narrationKana", t["kana"]) + ("、" if i in breaks else "")
            for i, t in enumerate(tokens)
        )
        # The input is an explicit reading. Katakana prevents the text frontend
        # from treating hiragana loanwords as historical Japanese inflections.
        text = "".join(chr(ord(c) + 96) if "ぁ" <= c <= "ゖ" else c for c in text)
        # Let the text frontend use normal word boundaries and accents first.
        # Accept either frontend only when its phonemes match the requested reading.
        display_text = "".join(
            t["jp"] + ("、" if i in breaks else "") for i, t in enumerate(tokens)
        )
        for attempt, query_text in enumerate(dict.fromkeys((display_text, text)), 1):
            query = json.loads(
                request(base, "/audio_query", {"text": query_text, "speaker": speaker})
            )
            write_json(
                evidence / f"{index + 1}-input-{attempt}.json",
                {"text": query_text, "query": query},
            )
            try:
                timing(query, tokens)
            except ValueError:
                if query_text == text:
                    raise
            else:
                break
        query.update(
            prePhonemeLength=0.06,
            postPhonemeLength=0.1,
            pauseLength=0.12,
            pauseLengthScale=1,
            outputSamplingRate=24000,
            outputStereo=False,
        )
        line["narration"] = {}
        for speed, scale in SPEEDS.items():
            current = copy.deepcopy(query)
            current["speedScale"] = scale
            write_json(evidence / f"{index + 1}-{speed}.json", current)
            marks, duration = timing(current, tokens)
            audio = request(
                base,
                "/synthesis",
                {"speaker": speaker, "enable_interrogative_upspeak": "false"},
                current,
            )
            with wave.open(io.BytesIO(audio), "rb") as stream:
                actual = stream.getnframes() / stream.getframerate()
            if abs(actual - duration) > 1 / FRAME_RATE:
                raise ValueError(
                    "Engine duration differs from its timing query; do not scale timestamps to fit"
                )
            name = f"reading/{index + 1}-{speed}.wav"
            (directory / name).write_bytes(audio)
            line["narration"][speed] = {"src": name, "duration": actual, "tokens": marks}
    write_json(song_path, song)
