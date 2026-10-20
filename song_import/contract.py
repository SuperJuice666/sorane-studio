"""Verify the pinned song-package contract, optionally against a player checkout."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(player=None):
    contract = json.loads((ROOT / "contract.json").read_text("utf-8"))
    if digest(ROOT / contract["validator"]) != contract["validatorSha256"]:
        raise ValueError("Local validator differs from pinned contract")
    if digest(ROOT / "docs/data-format.md") != contract["specSha256"]:
        raise ValueError("Local format specification differs from pinned contract")
    if player:
        version = json.loads((player / "format-version.json").read_text("utf-8"))
        if any(version[k] != contract[k] for k in ("schemaVersion", "formatRevision")):
            raise ValueError("Player format version differs from importer contract")
        if digest(player / contract["upstreamValidator"]) != contract["validatorSha256"]:
            raise ValueError("Player validator differs from importer contract")
        if digest(player / "docs/data-format.md") != contract["specSha256"]:
            raise ValueError("Player format specification differs from importer contract")
    return contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", type=Path)
    args = parser.parse_args()
    result = check(args.player)
    print(f"Compatible: schemaVersion {result['schemaVersion']}, format {result['formatRevision']}")


if __name__ == "__main__":
    main()
