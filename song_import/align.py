"""SOFA full-song alignment, contextual checks and CTC onset evidence.

The adapter targets SOFA commit 584d6b9. Model code and checkpoints are external.
Results are review artifacts; this command never replaces song.json.
"""

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

from .build import write_json
from .phonemes import phones


class Sofa:
    def __init__(self, source, checkpoint, device):
        import torch

        sys.path.insert(0, str(source.resolve()))
        from modules.rmvpe.spec import MelSpectrogram
        from modules.task.forced_alignment import LitForcedAlignmentTask

        self.torch = torch
        self.device = device if device != "auto" else "cuda" if torch.cuda.is_available() else "cpu"
        # PyTorch checkpoints can execute code. Use only a checkpoint you trust.
        saved = torch.load(checkpoint, map_location="cpu", weights_only=False)
        self.model = LitForcedAlignmentTask(**saved["hyper_parameters"])
        self.model.load_state_dict(saved["state_dict"], strict=True)
        self.model = self.model.to(self.device).eval()
        self.model.set_inference_mode("force")
        c = self.model.melspec_config
        self.mel = MelSpectrogram(
            c["n_mels"],
            c["sample_rate"],
            c["win_length"],
            c["hop_length"],
            c["n_fft"],
            c["fmin"],
            c["fmax"],
            c["clamp"],
        ).to(self.device)

    def align(self, signal, groups, capture=False):
        import numpy as np

        torch, model = self.torch, self.model
        c = model.melspec_config
        tensor = torch.from_numpy(np.asarray(signal, dtype=np.float32).copy()).to(self.device)
        original, emissions = model.forward, []

        def bounded_forward(features):
            parts = [[], [], []]
            length = features.shape[1]
            for start in range(0, length, 8192):
                end = min(length, start + 8192)
                left, right = max(0, start - 1024), min(length, end + 1024)
                for dest, item in zip(parts, original(features[:, left:right, :])):
                    dest.append(item[:, start - left : end - left].clone())
            joined = tuple(torch.cat(part, 1) for part in parts)
            if capture:
                emissions.append(joined[2].detach().log_softmax(-1).cpu())
            return joined

        model.forward = bounded_forward
        try:
            with torch.inference_mode():
                feat = self.mel(tensor.unsqueeze(0))
                feat = (feat - feat.mean()) / feat.std().clamp_min(1e-8)
                feat = feat.repeat_interleave(c["scale_factor"], dim=-1)
                phonemes, mapping = ["SP"], [-1]
                for index, group in enumerate(groups):
                    phonemes.extend(group + ["SP"])
                    mapping.extend([index] * len(group) + [-1])
                result = model._infer_once(
                    feat,
                    len(signal) / c["sample_rate"],
                    phonemes,
                    [str(i) for i in range(len(groups))],
                    mapping,
                )
                _, _, words, intervals, confidence, _, _ = result
                if list(map(int, words)) != list(range(len(groups))):
                    raise ValueError("SOFA returned a different token sequence")
                marks = [{"start": float(a), "end": float(b)} for a, b in intervals]
                return {"tokens": marks, "confidence": float(confidence)}, emissions
        finally:
            model.forward = original

    def ctc(self, emissions, groups):
        import math

        import torchaudio.functional as functional

        target = [self.model.vocab[p] for group in groups for p in group]
        path, scores = functional.forced_align(
            emissions, self.torch.tensor([target], dtype=self.torch.int32), blank=0
        )
        spans = functional.merge_tokens(path[0], scores[0], blank=0)
        if [span.token for span in spans] != target:
            raise ValueError("CTC returned a different phone sequence")
        config = self.model.melspec_config
        step = config["hop_length"] / config["scale_factor"] / config["sample_rate"]
        marks, offset = [], 0
        for group in groups:
            part = spans[offset : offset + len(group)]
            offset += len(group)
            marks.append(
                {
                    "start": part[0].start * step,
                    "end": part[-1].end * step,
                    "confidence": math.exp(statistics.mean(float(p.score) for p in part)),
                }
            )
        return marks


def resolve(candidates, core):
    """Conservative agreement clustering; conflicts remain explicit review items."""

    def consensus(edge):
        values = [c[edge] for c in candidates]
        clusters = [[v for v in values if abs(v - anchor) < 0.16] for anchor in values]
        return statistics.median(
            min(
                clusters,
                key=lambda group: (-len(group), abs(statistics.median(group) - core[edge])),
            )
        )

    start, end = consensus("start"), consensus("end")
    if core["confidence"] > 0.025 and abs(core["start"] - start) < 0.14:
        start = min(start, core["start"])
    if (
        core["confidence"] > 0.15
        and abs(core["start"] - start) > 0.25
        and core["start"] < end - 0.04
    ):
        start = max(0, core["start"] - 0.025)
    flags = []
    for edge, threshold in (("start", 0.18), ("end", 0.25)):
        if max(c[edge] for c in candidates) - min(c[edge] for c in candidates) > threshold:
            flags.append(edge + "-disagreement")
    if abs(core["start"] - start) > 0.2:
        flags.append("ctc-disagreement")
    if end - start < 0.025:
        flags.append("collapsed-token")
    if end - start > 2.5:
        flags.append("long-sustain-or-instrument")
    return {"start": start, "end": end, "flags": flags}


def align(args):
    import soundfile

    if args.output.exists():
        raise ValueError("Output exists; use a new run directory")
    song = json.loads(args.draft.read_text("utf-8"))
    tokens = [token for line in song["lines"] for token in line["tokens"]]
    groups = [token.get("phonemes") or phones(token["kana"]) for token in tokens]
    engine = Sofa(args.sofa_source, args.checkpoint, args.device)
    signal, sr = soundfile.read(args.vocals, dtype="float32", always_2d=True)
    if sr != engine.model.melspec_config["sample_rate"]:
        raise ValueError("Resample vocals to the model sample rate before alignment")
    signal = signal.mean(axis=1)
    song["duration"] = len(signal) / sr
    full, emissions = engine.align(signal, groups, capture=True)
    core = engine.ctc(emissions[0], groups)
    write_json(args.output / "full.json", full)
    write_json(args.output / "ctc.json", core)
    boundaries, cursor = [], 0
    for line in song["lines"]:
        boundaries.append((cursor, cursor + len(line["tokens"])))
        cursor += len(line["tokens"])
    candidates = [[mark] for mark in full["tokens"]]
    for index, (first, last) in enumerate(boundaries):
        seen = set()
        for radius in (0, 1, 2):
            low, high = max(0, index - radius), min(len(boundaries) - 1, index + radius)
            a, b = boundaries[low][0], boundaries[high][1]
            start = max(0, full["tokens"][a]["start"] - 0.6)
            end = min(len(signal) / sr, full["tokens"][b - 1]["end"] + 0.6)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            local, _ = engine.align(signal[round(start * sr) : round(end * sr)], groups[a:b])
            for mark in local["tokens"]:
                mark["start"] += start
                mark["end"] += start
            write_json(
                args.output / "contexts" / f"{index + 1}-{radius}.json",
                {"window": [start, end], **local},
            )
            for t in range(first, last):
                mark = local["tokens"][t - a]
                if mark["start"] > start + 0.15 and mark["end"] < end - 0.025:
                    candidates[t].append(mark)
    resolved = [resolve(options, check) for options, check in zip(candidates, core)]
    for i, mark in enumerate(resolved):
        if i and mark["start"] < resolved[i - 1]["end"]:
            mark["flags"].append("overlap-with-previous")
    cursor = 0
    for line in song["lines"]:
        for token in line["tokens"]:
            token.update({key: resolved[cursor][key] for key in ("start", "end")})
            cursor += 1
        line["start"], line["end"] = line["tokens"][0]["start"], line["tokens"][-1]["end"]
        line.pop("clipStart", None)
        line.pop("clipEnd", None)
    with args.checkpoint.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    write_json(args.output / "draft.json", song)
    write_json(
        args.output / "audit.json",
        {
            "checkpointSha256": digest,
            "sampleRate": sr,
            "device": engine.device,
            "tokens": [
                {
                    "index": i,
                    "jp": tokens[i]["jp"],
                    **mark,
                    "candidates": candidates[i],
                    "ctc": core[i],
                }
                for i, mark in enumerate(resolved)
            ],
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--vocals", type=Path, required=True)
    parser.add_argument("--sofa-source", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--output", type=Path, required=True)
    align(parser.parse_args())


if __name__ == "__main__":
    main()
