#!/usr/bin/env python3
"""Generate the bounded runtime lexicon from rime-pinyin-simp.

The full source remains an external build input.  The package carries only a
deterministic high-frequency projection plus the small MSYS seed vocabulary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


SCHEMA = "msys.pinyin-dictionary.v1"
MAX_ENTRIES = 4096
MAX_CANDIDATES = 48
SOURCE_REVISION = "0c6861ef7420ee780270ca6d993d18d4101049d0"
PINYIN = re.compile(r"[a-z]+(?:'[a-z]+)*")


def normalized_code(value: str) -> str:
    return "".join(value.strip().lower().split()).replace("'", "")


def load_seed(path: Path) -> dict[str, list[str]]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if document.get("schema") != SCHEMA or not isinstance(document.get("entries"), dict):
        raise ValueError("seed dictionary has an invalid schema")
    result: dict[str, list[str]] = {}
    for raw_key, raw_candidates in document["entries"].items():
        key = str(raw_key).strip().lower()
        if PINYIN.fullmatch(key) is None or not isinstance(raw_candidates, list):
            raise ValueError(f"invalid seed entry: {raw_key!r}")
        candidates = [str(item).strip() for item in raw_candidates if str(item).strip()]
        if any(len(item) > 16 for item in candidates):
            raise ValueError(f"seed candidate is too long: {raw_key!r}")
        result[key] = candidates
    return result


def load_rime(path: Path) -> tuple[dict[str, dict[str, int]], set[str]]:
    entries: dict[str, dict[str, int]] = {}
    single_syllable: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        candidate = fields[0].strip()
        raw_code = fields[1].strip().lower()
        key = normalized_code(raw_code)
        if (
            not candidate
            or len(candidate) > 16
            or re.fullmatch(r"[a-z]+", key) is None
        ):
            continue
        try:
            weight = int(fields[2]) if len(fields) > 2 else 0
        except ValueError:
            weight = 0
        previous = entries.setdefault(key, {}).get(candidate)
        if previous is None or weight > previous:
            entries[key][candidate] = weight
        if re.fullmatch(r"[a-z]+", raw_code) is not None:
            single_syllable.add(key)
    return entries, single_syllable


def generate(source: Path, seed_path: Path) -> dict[str, object]:
    seed = load_seed(seed_path)
    rime, single_syllable = load_rime(source)
    ranked_keys = sorted(
        rime,
        key=lambda key: (-max(rime[key].values(), default=0), key),
    )
    selected = list(seed)
    selected_set = set(selected)
    for key in sorted(single_syllable):
        if key not in selected_set:
            selected.append(key)
            selected_set.add(key)
    for key in ranked_keys:
        if key not in selected_set:
            selected.append(key)
            selected_set.add(key)
        if len(selected) >= MAX_ENTRIES:
            break
    entries: dict[str, list[str]] = {}
    for key in selected:
        candidates: list[str] = []
        seen: set[str] = set()
        for candidate in seed.get(key, []):
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
        ranked = sorted(
            rime.get(key.replace("'", ""), {}).items(),
            key=lambda item: (-item[1], item[0]),
        )
        for candidate, _weight in ranked:
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
            if len(candidates) >= MAX_CANDIDATES:
                break
        if candidates:
            entries[key] = candidates[:MAX_CANDIDATES]
    return {
        "schema": SCHEMA,
        "description": "Bounded high-frequency Simplified Chinese Pinyin lexicon",
        "source": {
            "name": "rime-pinyin-simp",
            "revision": SOURCE_REVISION,
            "license": "Apache-2.0",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "limits": {
            "entries": MAX_ENTRIES,
            "candidates_per_entry": MAX_CANDIDATES,
        },
        "selection": "seed, then every upstream single-syllable key, then remaining keys by highest candidate weight",
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--seed", type=Path, default=Path("scripts/pinyin_seed.json"))
    parser.add_argument("--output", type=Path, default=Path("files/share/pinyin/basic.json"))
    args = parser.parse_args()
    document = generate(args.source.resolve(), args.seed.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
