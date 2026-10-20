"""Resumable song preparation. Models produce candidates; evidence gates installation."""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import uuid
import wave
from pathlib import Path

from .build import PROJECT, build, write_json
from .media import pack
from .media import run as ffmpeg_run
from .phonemes import phones
from .schema import validate


def read(path):
    return json.loads(path.read_text("utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def tree(path):
    return {p.relative_to(path).as_posix(): sha(p) for p in sorted(path.rglob("*")) if p.is_file()}


def atomic_json(path, value):
    temp = path.with_suffix(".pending")
    write_json(temp, value)
    temp.replace(path)


def start(audio, job, song_id, title, artist, config=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", song_id):
        raise ValueError("Use a lowercase song id containing letters, digits and hyphens")
    if job.exists():
        raise ValueError("Job already exists; use run to resume it")
    if not audio.is_file() or not title.strip() or not artist.strip():
        raise ValueError("Audio, title and artist are required")
    settings = read(config) if config else read(PROJECT / "examples/import-config.json")
    instructions = (PROJECT / "prompts/import-agent.md").read_text("utf-8")
    instructions_sha = hashlib.sha256(instructions.encode("utf-8")).hexdigest()
    job.mkdir(parents=True)
    source = job / ("source" + audio.suffix.lower())
    shutil.copyfile(audio, source)
    write_json(
        job / "job.json",
        {
            "schemaVersion": 1,
            "id": song_id,
            "title": title,
            "artist": artist,
            "source": source.name,
            "originalFilename": audio.name,
            "sourceSha256": sha(source),
            "agentInstructionsSha256": instructions_sha,
            "settings": settings,
        },
    )
    write_json(job / "sources.json", {"version": "", "sources": [], "issues": []})
    write_json(
        job / "draft.json",
        {
            "schemaVersion": 1,
            "id": song_id,
            "title": title,
            "artist": artist,
            "lines": [],
            "issues": [],
        },
    )
    (job / "TASK.md").write_text(
        "# 导入任务\n\n"
        f"任务目录：`{job.resolve().as_posix()}`\n\n"
        f"曲名：{title}\n\n歌手：{artist}\n\n"
        f"提示词 SHA256：`{instructions_sha}`\n\n"
        "先阅读以下文件：\n\n"
        f"- 执行规范：`{(PROJECT / 'docs/agent-import.md').as_posix()}`\n"
        f"- 经验与故障判断：`{(PROJECT / 'docs/import-lessons.md').as_posix()}`\n"
        f"- 文字与分词规则：`{(PROJECT / 'prompts/lyrics.md').as_posix()}`\n"
        f"- 复核规则：`{(PROJECT / 'prompts/review.md').as_posix()}`\n\n"
        "以下是创建任务时保存的执行提示词。状态和配置以 job.json 为准。\n\n" + instructions,
        encoding="utf-8",
    )
    return job


def text_signature(song):
    return [
        (line["jp"], [(t["jp"], t["kana"], t.get("phonemes")) for t in line["tokens"]])
        for line in song["lines"]
    ]


def check_text(draft, sources, job):
    if not sources.get("version") or not sources.get("sources"):
        raise ValueError("Record the recording version and lyric sources in sources.json")
    if sources.get("issues") or draft.get("issues"):
        raise ValueError("Resolve text/version issues before alignment")
    for source in sources["sources"]:
        if not all(source.get(k) for k in ("reference", "retrievedAt", "textFile", "sha256")):
            raise ValueError("Each source needs reference, retrievedAt, textFile and sha256")
        path = (job / source["textFile"]).resolve()
        if (
            not path.is_relative_to(job.resolve())
            or not path.is_file()
            or sha(path) != source["sha256"]
        ):
            raise ValueError("Source snapshot is missing, changed or outside the job")
    if not draft.get("lines"):
        raise ValueError("Agent must prepare the lyric draft before alignment")

    def compact(s):
        return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", s), flags=re.UNICODE)

    if "canonicalLines" in sources:
        canonical = sources["canonicalLines"]
        if (
            not isinstance(canonical, list)
            or not canonical
            or any(not isinstance(line, str) or not compact(line) for line in canonical)
        ):
            raise ValueError("canonicalLines must contain nonempty source lyric lines")
        if sources.get("lineSource") not in {source["reference"] for source in sources["sources"]}:
            raise ValueError("lineSource must identify a recorded lyric source")
        if [compact(line["jp"]) for line in draft["lines"]] != [
            compact(line) for line in canonical
        ]:
            raise ValueError("Lyric lines differ from canonicalLines; preserve source line breaks")
    if "canonicalSections" in sources:
        sections = sources["canonicalSections"]
        if "canonicalLines" not in sources or not isinstance(sections, list) or not sections:
            raise ValueError("canonicalSections requires canonicalLines and nonempty source groups")
        expected_sections = []
        for section in sections:
            if not isinstance(section, dict):
                raise ValueError("Invalid canonicalSections entry")
            start, end, name = section.get("startLine"), section.get("endLine"), section.get("name")
            if (
                type(start) is not int
                or type(end) is not int
                or start != len(expected_sections) + 1
                or not start <= end <= len(draft["lines"])
                or not isinstance(name, str)
                or not name.strip()
            ):
                raise ValueError("canonicalSections must cover source lines once in order")
            expected_sections.extend([name] * (end - start + 1))
        if len(expected_sections) != len(draft["lines"]) or expected_sections != [
            line.get("section") for line in draft["lines"]
        ]:
            raise ValueError("Lyric sections differ from canonicalSections; preserve source groups")
    for line in draft["lines"]:
        if not line.get("section") or not line.get("tokens"):
            raise ValueError("Each line needs section and tokens")
        if compact(line["jp"]) != compact("".join(t["jp"] for t in line["tokens"])):
            raise ValueError("Display tokens do not reconstruct their lyric line")
        for token in line["tokens"]:
            if not token.get("kana") or not token.get("romaji"):
                raise ValueError("Every token needs verified kana and romaji")
            if not token.get("phonemes"):
                phones(token["kana"])


class Job:
    def __init__(self, path):
        self.path = path.resolve()
        self.spec = read(self.path / "job.json")
        self.config = self.spec["settings"]
        self.state = read(self.path / "state.json") if (self.path / "state.json").exists() else {}
        self.ffmpeg = self.config.get("ffmpeg", "ffmpeg")
        self.python = self.config.get("modelPython") or sys.executable

    def save(self):
        atomic_json(self.path / "state.json", self.state)

    def event(self, stage, status, **fields):
        with (self.path / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "stage": stage,
                        "status": status,
                        **fields,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def stage(self, name, inputs, action):
        key = fingerprint(inputs)
        old = self.state.get(name)
        if old and old["input"] == key:
            directory = self.path / old["directory"]
            if directory.is_dir() and tree(directory) == old["files"]:
                return directory
        if name == "align":
            attempts = len(list((self.path / "runs").glob("align-*")))
            if attempts >= self.config.get("maxAlignmentRuns", 3):
                raise ValueError(
                    "Alignment run limit reached; inspect evidence before increasing it"
                )
        directory = self.path / "runs" / (name + "-" + uuid.uuid4().hex[:12])
        directory.mkdir(parents=True)
        self.event(name, "started", directory=str(directory.relative_to(self.path)))
        try:
            action(directory)
        except Exception as error:
            self.event(name, "failed", errorType=type(error).__name__)
            raise
        self.state[name] = {
            "input": key,
            "directory": str(directory.relative_to(self.path)),
            "files": tree(directory),
        }
        self.save()
        self.event(name, "complete")
        return directory

    def command(self, args, directory):
        with (directory / "process.log").open("wb") as log:
            subprocess.run(
                list(map(str, args)), cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT, check=True
            )

    def prepare(self):
        source = self.path / self.spec["source"]
        if sha(source) != self.spec["sourceSha256"]:
            raise ValueError("Original audio changed; create a new job for this recording")
        normalized = self.stage(
            "normalize",
            [sha(source), self.ffmpeg],
            lambda out: ffmpeg_run(
                self.ffmpeg,
                "-i",
                source,
                "-ar",
                44100,
                "-ac",
                2,
                "-c:a",
                "pcm_s16le",
                out / "mix.wav",
            ),
        )
        mix = normalized / "mix.wav"
        supplied = self.config.get("vocals")

        def separate(out):
            if supplied:
                vocal = Path(supplied).resolve()
            else:
                self.command(
                    [
                        self.python,
                        "-m",
                        "demucs",
                        "--two-stems",
                        "vocals",
                        "-n",
                        "htdemucs",
                        "--out",
                        out / "stems",
                        mix,
                    ],
                    out,
                )
                vocal = out / "stems/htdemucs/mix/vocals.wav"
            ffmpeg_run(
                self.ffmpeg,
                "-i",
                vocal,
                "-ar",
                44100,
                "-ac",
                2,
                "-c:a",
                "pcm_s16le",
                out / "vocals.wav",
            )
            with wave.open(str(mix), "rb") as a, wave.open(str(out / "vocals.wav"), "rb") as b:
                if a.getnframes() != b.getnframes():
                    raise ValueError(
                        "Vocal stem duration differs; do not pad or shift automatically"
                    )
            ffmpeg_run(
                self.ffmpeg,
                "-i",
                out / "vocals.wav",
                "-ar",
                44100,
                "-ac",
                1,
                "-c:a",
                "pcm_s16le",
                out / "alignment.wav",
            )

        stems = self.stage(
            "separate",
            [sha(mix), sha(Path(supplied)) if supplied else "htdemucs", self.python, self.ffmpeg],
            separate,
        )
        return mix, stems

    def align(self, stems):
        draft, sources = read(self.path / "draft.json"), read(self.path / "sources.json")
        check_text(draft, sources, self.path)
        for key in ("id", "title", "artist"):
            if draft.get(key) != self.spec[key]:
                raise ValueError(f"Draft {key} differs from job metadata")
        checkpoint = Path(self.config["sofaCheckpoint"]).resolve()
        sofa = Path(self.config["sofaSource"]).resolve()
        if not (sofa / "modules/task/forced_alignment.py").is_file():
            raise ValueError(
                "sofaSource must be the SOFA checkout containing modules/task/forced_alignment.py"
            )
        model_code = {str(p.relative_to(sofa)): sha(p) for p in sorted(sofa.rglob("*.py"))}
        if not model_code:
            raise ValueError("SOFA source directory is empty")
        deps = [
            sha(self.path / "draft.json"),
            sha(self.path / "sources.json"),
            sha(stems / "alignment.wav"),
            sha(checkpoint),
            model_code,
            sha(PROJECT / "song_import/align.py"),
            sha(PROJECT / "song_import/phonemes.py"),
            self.python,
        ]
        return (
            self.stage(
                "align",
                deps,
                lambda out: self.command(
                    [
                        self.python,
                        "-m",
                        "song_import.align",
                        self.path / "draft.json",
                        "--vocals",
                        stems / "alignment.wav",
                        "--sofa-source",
                        sofa,
                        "--checkpoint",
                        checkpoint,
                        "--output",
                        out / "result",
                    ],
                    out,
                ),
            )
            / "result"
        )

    def advance(self):
        mix, stems = self.prepare()
        alignment = self.align(stems)
        from .import_review import create_review

        create_review(self.path, alignment, mix, stems / "vocals.wav")
        approval = self.path / "alignment-approved.json"
        if not approval.exists():
            return "Review alignment at review.html, then run accept with a completed report"
        report = read(approval)
        self.check_alignment_review(report, alignment)
        reviewed = self.path / "reviewed.json"

        media = self.stage(
            "media",
            [
                sha(reviewed),
                sha(mix),
                sha(stems / "vocals.wav"),
                self.ffmpeg,
                sha(PROJECT / "song_import/media.py"),
            ],
            lambda out: pack(reviewed, mix, stems / "vocals.wav", out / "song", self.ffmpeg),
        )

        def package(out):
            shutil.copytree(media / "song", out / "song")
            narration = self.config.get("narration", {"provider": "voicevox"})
            if narration["provider"] == "voicevox":
                from .narrate import narrate

                narrate(out / "song", narration)
            elif narration["provider"] != "none":
                raise ValueError("Unknown narration provider")
            validate(read(out / "song/song.json"), out / "song")

        packaged = self.stage(
            "package",
            [
                sha(reviewed),
                sha(mix),
                sha(stems / "vocals.wav"),
                self.config.get("narration"),
                self.ffmpeg,
                sha(PROJECT / "song_import/media.py"),
                sha(PROJECT / "song_import/narrate.py"),
            ],
            package,
        )
        package_hash = fingerprint(tree(packaged / "song"))
        self.stage(
            "preview",
            [package_hash, sha(PROJECT / "song_import/package-preview.html")],
            lambda out: build(packaged, out / "site"),
        )
        write_json(
            self.path / "playback-template.json",
            {
                "packageSha256": package_hash,
                "reviewer": "",
                "checks": {
                    key: {"passed": False, "evidence": ""}
                    for key in playback_checks(read(packaged / "song/song.json"))
                },
                "issues": [],
            },
        )
        return "Package ready; test the local preview and complete playback-template.json before install"

    def check_alignment_review(self, report, alignment):
        if report.get("inputSha256") != self.state["align"]["input"]:
            raise ValueError("Sources, model or draft changed after review")
        if report.get("alignmentSha256") != sha(alignment / "audit.json"):
            raise ValueError("Review belongs to another alignment run")
        reviewed = self.path / "reviewed.json"
        if report.get("reviewedSha256") != sha(reviewed):
            raise ValueError("Reviewed lyrics changed after review")
        song = read(reviewed)
        for key in ("id", "title", "artist"):
            if song.get(key) != self.spec[key]:
                raise ValueError("Reviewed metadata differs from the import task")
        if song.get("duration") != read(alignment / "draft.json")["duration"]:
            raise ValueError("Reviewed duration must match the source recording")
        if text_signature(song) != text_signature(read(self.path / "draft.json")):
            raise ValueError("Text or token grouping changed; update draft.json and realign")
        validate({**song, "audio": {r: {"src": "pending"} for r in ("1", "0.75", "0.5")}})
        require_checks(report, ("sources", "fullSong", "boundaries", "pronunciation", "structure"))
        flags = {
            item["index"] for item in read(alignment / "audit.json")["tokens"] if item["flags"]
        }
        decisions = report.get("decisions", [])
        if {d.get("index") for d in decisions} != flags or len(decisions) != len(flags):
            raise ValueError("Every flagged token needs exactly one review decision")
        for decision in decisions:
            if decision.get("status") not in ("corrected", "confirmed") or not decision.get(
                "evidence"
            ):
                raise ValueError("Review decisions need a result and evidence")

    def accept(self, path):
        # Refresh dependent stages: changed input cannot inherit an old approval.
        _, stems = self.prepare()
        alignment = self.align(stems)
        report = read(path)
        self.check_alignment_review(report, alignment)
        atomic_json(self.path / "alignment-approved.json", report)
        self.event("alignment-review", "accepted", reviewedSha256=report["reviewedSha256"])

    def install(self, report_path, library):
        self.advance()
        if "package" not in self.state or not (self.path / "alignment-approved.json").exists():
            raise ValueError("Alignment review must be accepted before installation")
        packaged = self.path / self.state["package"]["directory"] / "song"
        report = read(report_path)
        if report.get("packageSha256") != fingerprint(tree(packaged)):
            raise ValueError("Playback report belongs to another package")
        song = validate(read(packaged / "song.json"), packaged)
        require_checks(report, playback_checks(song))
        library.mkdir(parents=True, exist_ok=True)
        destination = library / self.spec["id"]
        if destination.exists():
            raise ValueError(
                "Song already installed; compare and migrate explicitly instead of overwriting"
            )
        # Keep partial copies outside the library glob until the directory rename completes.
        staging = library.parent / (".import-" + uuid.uuid4().hex)
        shutil.copytree(packaged, staging)
        staging.rename(destination)
        self.event(
            "install",
            "complete",
            destination=str(destination.resolve()),
            packageSha256=report["packageSha256"],
        )
        return destination


@contextlib.contextmanager
def locked(job):
    path = job / ".import.lock"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        raise ValueError(
            "Job is locked; check the recorded process before removing .import.lock"
        ) from None
    try:
        yield
    finally:
        path.unlink()


def require_checks(report, names):
    if not report.get("reviewer") or report.get("issues") != []:
        raise ValueError("Review needs a reviewer and no unresolved issues")
    for name in names:
        check = report.get("checks", {}).get(name, {})
        if (
            check.get("passed") is not True
            or not isinstance(check.get("evidence"), str)
            or not check["evidence"].strip()
        ):
            raise ValueError("Missing review evidence: " + name)


def playback_checks(song):
    return [
        "fullSong",
        "lineLoop",
        "sectionLoop",
        "seekAndSwitch",
        "threeSpeeds",
        "mobileStart",
    ] + (["narration"] if any(line.get("narration") for line in song["lines"]) else [])


def status(job):
    current = Job(job)
    result = {
        "song": current.spec["id"],
        "stages": {
            key: {
                "directory": value["directory"],
                "intact": tree(current.path / value["directory"]) == value["files"],
            }
            for key, value in current.state.items()
        },
        "task": str(current.path / "TASK.md"),
        "usage": [read(p) for p in current.path.rglob("*.usage.json")],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def doctor(job):
    checks = {}
    try:
        result = subprocess.run(
            [job.ffmpeg, "-version"], capture_output=True, text=True, check=True
        )
        checks["ffmpeg"] = {"ready": True, "version": result.stdout.splitlines()[0]}
    except (OSError, subprocess.CalledProcessError):
        checks["ffmpeg"] = {"ready": False, "needed": "Set ffmpeg to an installed executable"}
    for field, child in (
        ("sofaSource", "modules/task/forced_alignment.py"),
        ("sofaCheckpoint", ""),
    ):
        path = Path(job.config.get(field, ""))
        checks[field] = {
            "ready": bool(job.config.get(field)) and (path / child if child else path).is_file()
        }
    try:
        names = ["torch", "torchaudio"] + ([] if job.config.get("vocals") else ["demucs"])
        code = (
            "import importlib.metadata as m,json; names="
            + repr(names)
            + "; print(json.dumps({n:m.version(n) for n in names}))"
        )
        result = subprocess.run(
            [job.python, "-c", code], capture_output=True, text=True, check=True
        )
        versions = json.loads(result.stdout)
        checks["modelPython"] = {
            "ready": all(versions[n].split("+")[0] == "2.8.0" for n in ("torch", "torchaudio")),
            "versions": versions,
        }
    except (OSError, subprocess.CalledProcessError, ValueError):
        checks["modelPython"] = {
            "ready": False,
            "needed": "Install the model requirements in modelPython",
        }
    config = job.config.get("narration", {"provider": "voicevox"})
    if config["provider"] == "voicevox":
        from .narrate import request

        try:
            # A synthesis query is local and does not generate or publish an audio asset.
            query = json.loads(
                request(
                    config.get("url", "http://127.0.0.1:50021"),
                    "/audio_query",
                    {"text": "あさ", "speaker": config.get("speaker", 3)},
                )
            )
            checks["narration"] = {"ready": bool(query.get("accent_phrases"))}
        except (OSError, ValueError):
            checks["narration"] = {
                "ready": False,
                "needed": "Start the local VOICEVOX engine and check speaker",
            }
    else:
        checks["narration"] = {
            "ready": config["provider"] == "none",
            "provider": config["provider"],
        }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return all(item["ready"] for item in checks.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start")
    p.add_argument("audio", type=Path)
    p.add_argument("--job", type=Path, required=True)
    for name in ("id", "title", "artist"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--config", type=Path)
    for name in ("run", "status", "doctor", "agent", "accept", "install"):
        p = sub.add_parser(name)
        p.add_argument("job", type=Path)
        if name in ("accept", "install"):
            p.add_argument("--report", type=Path, required=True)
        if name == "install":
            p.add_argument("--library", type=Path, default=Path("data/songs"))
    args = parser.parse_args()
    if args.command == "start":
        print(start(args.audio, args.job, args.id, args.title, args.artist, args.config))
    elif args.command == "status":
        status(args.job)
    else:
        job = Job(args.job)
        if args.command == "doctor":
            if not doctor(job):
                raise SystemExit(1)
        elif args.command == "agent":
            command = job.config.get("agentCommand", [])
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(x, str) for x in command)
            ):
                raise ValueError("Set agentCommand or open TASK.md in your coding agent")
            subprocess.run(
                [
                    arg.replace("{task}", str(job.path / "TASK.md")).replace("{job}", str(job.path))
                    for arg in command
                ],
                cwd=PROJECT,
                check=True,
            )
        elif args.command == "run":
            with locked(job.path):
                print(job.advance())
        elif args.command == "accept":
            with locked(job.path):
                job.accept(args.report)
            print("Alignment review recorded")
        else:
            with locked(job.path):
                print(job.install(args.report, args.library))


if __name__ == "__main__":
    main()
