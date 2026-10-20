"""Local package preview and shared job file helpers."""

import json
import shutil
from pathlib import Path

from .schema import validate

PROJECT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(source, output):
    output = output.resolve()
    source = source.resolve()
    if (
        output == PROJECT
        or output == source
        or output in source.parents
        or source in output.parents
    ):
        raise ValueError("Preview output must be separate from source and project directories")
    songs = list(source.glob("*/song.json"))
    if len(songs) != 1:
        raise ValueError("Package preview expects exactly one song")
    path = songs[0]
    validate(json.loads(path.read_text("utf-8")), path.parent)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(path.parent, output / "song", dirs_exist_ok=True)
    shutil.copyfile(PROJECT / "song_import/package-preview.html", output / "index.html")
