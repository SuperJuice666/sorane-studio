"""Optional JSON drafting through an explicitly configured chat completion API."""

import argparse
import datetime
import hashlib
import json
import os
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .build import PROJECT, write_json


def assist(task, source, output):
    if output.exists():
        raise ValueError("Output already exists; choose a new review artifact")
    base = os.environ["AI_BASE_URL"].rstrip("/")
    model = os.environ["AI_MODEL"]
    parsed = urlsplit(base)
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Use HTTPS for remote model endpoints")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("AI_BASE_URL must not contain credentials or query parameters")
    instruction = (PROJECT / "prompts" / f"{task}.md").read_text("utf-8")
    data = json.loads(source.read_text("utf-8"))
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["AI_API_KEY"],
            "Content-Type": "application/json",
        },
    )
    # Only the caller-selected JSON file is sent. No audio, environment, keys or repository scan.
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    record = {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "task": task,
        "model": result.get("model", model),
        "instructionSha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "inputSha256": hashlib.sha256(
            json.dumps(data, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "usage": result.get("usage", {}),
    }
    # Keep token usage even when the provider returns malformed content.
    write_json(output.with_suffix(".usage.json"), record)
    content = json.loads(result["choices"][0]["message"]["content"])
    if not isinstance(content, dict) or not isinstance(content.get("issues"), list):
        raise ValueError("Model response must be an object with an issues array")
    if task == "lyrics" and not isinstance(content.get("lines"), list):
        raise ValueError("Lyrics draft must contain a lines array")
    write_json(output, content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("lyrics", "review"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assist(args.task, args.input, args.output)


if __name__ == "__main__":
    main()
