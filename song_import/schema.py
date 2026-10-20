"""The input format has one timeline, measured in original-song seconds."""

import math
import re
from pathlib import Path

RATES = ("1", "0.75", "0.5")
READ_SPEEDS = ("normal", "slow", "verySlow")


def asset(root, name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError(f"Invalid asset path: {name!r}")
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"Asset escapes song directory: {name!r}")
    if not path.is_file():
        raise ValueError(f"Asset does not exist: {name}")
    return path


def number(value, label):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(f"{label}: expected a finite number")
    return value


def interval(item, label, duration):
    start = number(item.get("start"), label + ".start")
    end = number(item.get("end"), label + ".end")
    if not 0 <= start < end <= duration + 0.001:
        raise ValueError(f"{label}: invalid interval {start}–{end}")
    return start, end


def validate(song, root=None):
    if song.get("schemaVersion") != 1:
        raise ValueError("Unsupported schemaVersion")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", song.get("id", "")):
        raise ValueError("id must be a lowercase slug")
    for key in ("title", "artist"):
        if not isinstance(song.get(key), str) or not song[key].strip():
            raise ValueError(f"Missing {key}")
    duration = number(song.get("duration"), "duration")
    if duration <= 0:
        raise ValueError("duration must be positive")
    if not isinstance(song.get("lines"), list) or not song["lines"]:
        raise ValueError("At least one line is required")
    previous = -1
    for index, line in enumerate(song["lines"]):
        label = f"line {index + 1}"
        start, end = interval(line, label, duration)
        if start < previous:
            raise ValueError(f"{label}: overlapping lines")
        previous = end
        if not all(isinstance(line.get(k), str) and line[k] for k in ("jp", "section")):
            raise ValueError(f"{label}: jp and section are required")
        clip_start = number(line.get("clipStart", start), label + ".clipStart")
        clip_end = number(line.get("clipEnd", end), label + ".clipEnd")
        if not 0 <= clip_start <= start < end <= clip_end <= duration + 0.001:
            raise ValueError(f"{label}: invalid clip bounds")
        if not line.get("tokens"):
            raise ValueError(f"{label}: missing tokens")
        prior = start
        for token in line["tokens"]:
            a, b = interval(token, label + " token", duration)
            if a < prior - 0.001 or a < start - 0.001 or b > end + 0.001:
                raise ValueError(f"{label}: tokens must be ordered inside the line")
            prior = b
            if not all(
                isinstance(token.get(k), str) and token[k] for k in ("jp", "kana", "romaji")
            ):
                raise ValueError(f"{label}: each token needs jp, kana and romaji")
        if "narration" in line:
            for speed in READ_SPEEDS:
                voice = line["narration"][speed]
                marks = voice["tokens"]
                if len(marks) != len(line["tokens"]):
                    raise ValueError(f"{label}: narration token count differs")
                prior = 0
                for mark in marks:
                    a, b = interval(mark, "narration", voice["duration"])
                    if a < prior:
                        raise ValueError(f"{label}: narration marks overlap")
                    prior = b
                if root:
                    asset(root, voice["src"])
    for rate in RATES:
        source = song["audio"][rate]["src"]
        if root:
            asset(root, source)
        manifest = song.get("chunks", {}).get(source)
        if manifest:
            cursor = 0
            if manifest.get("sampleRate") != 44100:
                raise ValueError("Chunk sample rate must be 44100")
            for chunk in manifest["chunks"]:
                if chunk["first"] != cursor or chunk["last"] <= cursor:
                    raise ValueError("Chunk coverage has a gap or overlap")
                if chunk.get("decodedFrames", chunk["last"] - cursor) < chunk[
                    "last"
                ] - cursor + chunk.get("trimStart", 0):
                    raise ValueError("Chunk has insufficient decoded samples")
                cursor = chunk["last"]
                if root:
                    for name in chunk.get("parts", [chunk["src"]]):
                        asset(root, name)
            if cursor != manifest["frames"] or abs(cursor / 44100 - duration / float(rate)) > 0.15:
                raise ValueError("Chunk duration does not match the original timeline")
    return song
