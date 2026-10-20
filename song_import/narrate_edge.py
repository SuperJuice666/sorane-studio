"""Synthesize each reading speed with Edge TTS and retain its word-boundary evidence."""

import asyncio
import hashlib
import json
import re
import subprocess

from .build import write_json

RATES = {"normal": "+0%", "slow": "-25%", "verySlow": "-50%"}


def compact(text):
    return re.sub(r"[^\w]", "", text).lower()


def token_times(parts, boundaries):
    """Map engine words to display tokens; interpolation is local to each engine word."""
    chars = []
    for mark in boundaries:
        word = compact(mark["text"])
        start, duration = mark["offset"] / 1e7, mark["duration"] / 1e7
        chars.extend(
            (char, start + duration * i / len(word), start + duration * (i + 1) / len(word))
            for i, char in enumerate(word)
        )
    if "".join(c[0] for c in chars) != "".join(compact(p) for p in parts):
        raise ValueError("Speech boundaries differ from the requested reading")
    result, cursor = [], 0
    for part in parts:
        length = len(compact(part))
        if not length:
            raise ValueError("An empty reading token cannot be timed")
        result.append({"start": chars[cursor][1], "end": chars[cursor + length - 1][2]})
        cursor += length
    return result


def phrase_groups(tokens):
    import fugashi

    tagger, groups = fugashi.Tagger(), []
    for i, token in enumerate(tokens):
        words = list(tagger(token["jp"]))
        first = words[0].feature if words else None
        attach = first and (
            first.pos1 in ("助詞", "助動詞", "接尾辞")
            or first.pos1 == "動詞"
            and first.pos2 == "非自立可能"
        )
        if groups:
            previous = list(tagger(tokens[groups[-1][-1]]["jp"]))
            attach = attach or previous and previous[-1].feature.pos1 in ("接頭辞", "連体詞")
        if groups and attach:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def narrate(directory, config, ffmpeg="ffmpeg"):
    import edge_tts
    import numpy as np
    import soundfile as sf

    path = directory / "song.json"
    song = json.loads(path.read_text("utf-8"))
    output, cache = directory / "reading", directory.parents[2] / "edge-cache"
    output.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    evidence = directory.parent / "narration-queries"
    evidence.mkdir(exist_ok=True)
    voice = config.get("voice", "ja-JP-NanamiNeural")

    async def main():
        semaphore = asyncio.Semaphore(3)

        async def one(index, line, speed, rate):
            parts = [
                "".join(
                    chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c
                    for c in t.get("narrationKana", t["kana"])
                )
                for t in line["tokens"]
            ]
            groups = phrase_groups(line["tokens"])
            text = "、".join("".join(parts[i] for i in g) for g in groups) + "。"
            key = hashlib.sha256((voice + "|" + rate + "|" + text).encode()).hexdigest()
            raw, meta = cache / (key + ".mp3"), cache / (key + ".json")
            async with semaphore:
                if not raw.exists() or not meta.exists():
                    audio, boundaries = [], []
                    async for event in edge_tts.Communicate(
                        text, voice=voice, rate=rate, boundary="WordBoundary"
                    ).stream():
                        if event["type"] == "audio":
                            audio.append(event["data"])
                        elif event["type"] == "WordBoundary":
                            boundaries.append(event)
                    if not audio or not boundaries:
                        raise ValueError("TTS returned empty audio or timing")
                    token_times(parts, boundaries)
                    raw.write_bytes(b"".join(audio))
                    write_json(meta, boundaries)
                boundaries = json.loads(meta.read_text("utf-8"))
                marks = token_times(parts, boundaries)
                decoded = subprocess.run(
                    [
                        str(ffmpeg),
                        "-v",
                        "error",
                        "-i",
                        str(raw),
                        "-ar",
                        "24000",
                        "-ac",
                        "1",
                        "-f",
                        "f32le",
                        "-",
                    ],
                    capture_output=True,
                    check=True,
                ).stdout
                pcm = np.frombuffer(decoded, np.float32)
                cuts = []
                for left, right in zip(groups, groups[1:]):
                    a, b = marks[left[-1]]["end"] + 0.08, marks[right[0]]["start"] - 0.15
                    gap = pcm[round(a * 24000) : round(b * 24000)]
                    if b > a and len(gap) and np.sqrt(np.mean(gap * gap)) < 0.022:
                        cuts.append((a, b))
                pieces, cursor = [], 0
                for a, b in cuts:
                    pieces.append(pcm[cursor : round(a * 24000)])
                    cursor = round(b * 24000)
                pieces.append(pcm[cursor : round((marks[-1]["end"] + 0.15) * 24000)])
                pcm = np.concatenate(pieces)
                for mark in marks:
                    for edge in ("start", "end"):
                        mark[edge] -= sum(
                            max(0, min(mark[edge], b) - a) for a, b in cuts if mark[edge] > a
                        )
                name = f"reading/{index + 1}-{speed}.wav"
                sf.write(directory / name, pcm, 24000, subtype="PCM_16")
                write_json(
                    evidence / f"{index + 1}-{speed}.json",
                    {
                        "provider": "edge",
                        "voice": voice,
                        "rate": rate,
                        "text": text,
                        "boundaries": boundaries,
                        "removedSilence": cuts,
                        "timing": "engine word boundaries; kana interpolation within each engine word",
                    },
                )
                line.setdefault("narration", {})[speed] = {
                    "src": name,
                    "duration": len(pcm) / 24000,
                    "tokens": marks,
                }
                print(f"Nanami {index + 1}/{len(song['lines'])} {speed}", flush=True)

        await asyncio.gather(
            *(
                one(i, line, speed, rate)
                for i, line in enumerate(song["lines"])
                for speed, rate in RATES.items()
            )
        )

    asyncio.run(main())
    song["narrationVoice"] = voice
    write_json(path, song)
