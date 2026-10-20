"""Prepare three speeds and bounded AAC chunks from a mix and vocal stem."""

import argparse
import json
import subprocess
import tempfile
import wave
from pathlib import Path

from .build import write_json
from .schema import validate

SR = 44100
STEP = 344 * 1024
ROLL = 4 * 1024


def run(executable, *args):
    subprocess.run(
        [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *map(str, args)],
        check=True,
    )


def pack(song_path, mix, vocals, output, ffmpeg="ffmpeg"):
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    song = json.loads(song_path.read_text("utf-8"))
    output.mkdir(parents=True)
    song["audio"], song["chunks"] = {}, {}
    with tempfile.TemporaryDirectory(prefix="lyric-audio-") as temp:
        temp = Path(temp)
        normalized = []
        lengths = []
        for index, source in enumerate((mix, vocals)):
            path = temp / f"input-{index}.wav"
            run(ffmpeg, "-i", source, "-ar", SR, "-ac", 2, "-c:a", "pcm_s16le", path)
            with wave.open(str(path), "rb") as stream:
                lengths.append(stream.getnframes())
            normalized.append(path)
        if abs(lengths[0] - lengths[1]) > 1:
            raise ValueError("Mix and vocal stem must have the same number of samples")
        mix, vocals = normalized
        packed = temp / "packed.wav"
        # A half-gain backing pair followed by a half-gain vocal pair.
        # The browser mixer restores their gain with output headroom.
        graph = "[0:a]aresample=44100,aformat=channel_layouts=stereo[m];[1:a]aresample=44100,aformat=channel_layouts=stereo[v];[m][v]amerge=inputs=2,pan=4c|c0=0.5*c0-0.5*c2|c1=0.5*c1-0.5*c3|c2=0.5*c2|c3=0.5*c3[out]"
        run(
            ffmpeg,
            "-i",
            mix,
            "-i",
            vocals,
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            packed,
        )
        with wave.open(str(packed), "rb") as stream:
            song["duration"] = stream.getnframes() / SR
        for rate in (1, 0.75, 0.5):
            pcm = packed if rate == 1 else temp / f"rate-{rate}.wav"
            if rate != 1:
                run(ffmpeg, "-i", packed, "-af", f"atempo={rate}", "-c:a", "pcm_s16le", pcm)
            name = f"full-{rate}.m4a"
            run(
                ffmpeg,
                "-i",
                pcm,
                "-c:a",
                "aac",
                "-b:a",
                "256k",
                "-movie_timescale",
                SR,
                "-movflags",
                "+faststart",
                output / name,
            )
            song["audio"][str(rate)] = {"src": name}
            with wave.open(str(pcm), "rb") as source:
                frames = source.getnframes()
                chunks = []
                for index, first in enumerate(range(0, frames, STEP)):
                    last = min(first + STEP, frames)
                    begin, end = max(0, first - ROLL), min(frames, last + ROLL)
                    source.setpos(begin)
                    raw = temp / "chunk.wav"
                    with wave.open(str(raw), "wb") as dest:
                        dest.setparams(source.getparams())
                        dest.writeframes(source.readframes(end - begin))
                    parts = []
                    for plane in range(2):
                        part = f"chunk-{rate}-{index}-{plane}.m4a"
                        run(
                            ffmpeg,
                            "-i",
                            raw,
                            "-af",
                            f"pan=stereo|c0=c{plane * 2}|c1=c{plane * 2 + 1}",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "96k",
                            "-movie_timescale",
                            SR,
                            "-movflags",
                            "+faststart",
                            output / part,
                        )
                        parts.append(part)
                    chunks.append(
                        {
                            "src": parts[0],
                            "parts": parts,
                            "first": first,
                            "last": last,
                            "decodedFrames": end - begin,
                            "trimStart": first - begin,
                            "postRoll": end - last,
                            "crossfadeFrames": 1024 if first else 0,
                        }
                    )
            song["chunks"][name] = {"sampleRate": SR, "frames": frames, "chunks": chunks}
    # Input narration paths are relative to the input directory, not this output.
    for line in song["lines"]:
        line.pop("narration", None)
    validate(song, output)
    write_json(output / "song.json", song)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song", type=Path)
    parser.add_argument("--mix", type=Path, required=True)
    parser.add_argument("--vocals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    pack(args.song, args.mix, args.vocals, args.output, args.ffmpeg)


if __name__ == "__main__":
    main()
