"""Create a local evidence page without changing alignment results."""

import shutil

from .build import PROJECT, write_json
from .import_job import read, sha


def create_review(job, alignment, mix, vocals):
    song = read(alignment / "draft.json")
    audit = read(alignment / "audit.json")
    state = read(job / "state.json")
    write_json(
        job / "review-data.json",
        {
            "song": song,
            "audit": audit,
            "mix": mix.relative_to(job).as_posix(),
            "vocals": vocals.relative_to(job).as_posix(),
        },
    )
    shutil.copyfile(PROJECT / "song_import/review.html", job / "review.html")
    if not (job / "reviewed.json").exists():
        shutil.copyfile(alignment / "draft.json", job / "reviewed.json")
    write_json(
        job / "alignment-template.json",
        {
            "inputSha256": state["align"]["input"],
            "alignmentSha256": sha(alignment / "audit.json"),
            "reviewedSha256": sha(job / "reviewed.json"),
            "reviewer": "",
            "issues": [],
            "checks": {
                key: {"passed": False, "evidence": ""}
                for key in ("sources", "fullSong", "boundaries", "pronunciation", "structure")
            },
            "decisions": [
                {"index": t["index"], "flags": t["flags"], "status": "pending", "evidence": ""}
                for t in audit["tokens"]
                if t["flags"]
            ],
        },
    )
