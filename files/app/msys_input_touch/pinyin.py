from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


DICTIONARY_SCHEMA = "msys.pinyin-dictionary.v1"
MAX_DICTIONARY_ENTRIES = 4096
MAX_CANDIDATES_PER_ENTRY = 48
MAX_CANDIDATES_SHOWN = 32
MAX_PINYIN_LENGTH = 24
MAX_CANDIDATE_LENGTH = 16
_PINYIN_KEY = re.compile(r"[a-z]+(?:'[a-z]+)*")
DEFAULT_DICTIONARY_PATH = (
    Path(__file__).resolve().parents[2] / "share" / "pinyin" / "basic.json"
)


class PinyinDictionaryError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PinyinDictionaryError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class PinyinDictionary:
    entries: Mapping[str, tuple[str, ...]]
    source: str = ""

    @classmethod
    def from_mapping(
        cls,
        document: object,
        *,
        source: str = "<mapping>",
    ) -> "PinyinDictionary":
        if not isinstance(document, dict):
            raise PinyinDictionaryError("dictionary must be an object")
        if document.get("schema") != DICTIONARY_SCHEMA:
            raise PinyinDictionaryError(f"schema must be {DICTIONARY_SCHEMA}")
        raw_entries = document.get("entries")
        if not isinstance(raw_entries, dict):
            raise PinyinDictionaryError("entries must be an object")
        if len(raw_entries) > MAX_DICTIONARY_ENTRIES:
            raise PinyinDictionaryError(
                f"entries exceeds {MAX_DICTIONARY_ENTRIES}"
            )
        entries: dict[str, tuple[str, ...]] = {}
        for raw_key, raw_candidates in raw_entries.items():
            key = str(raw_key).strip().lower()
            if _PINYIN_KEY.fullmatch(key) is None or len(key) > 32:
                raise PinyinDictionaryError(f"invalid Pinyin key: {raw_key!r}")
            if not isinstance(raw_candidates, list) or not raw_candidates:
                raise PinyinDictionaryError(f"{key} candidates must be a non-empty list")
            if len(raw_candidates) > MAX_CANDIDATES_PER_ENTRY:
                raise PinyinDictionaryError(
                    f"{key} exceeds {MAX_CANDIDATES_PER_ENTRY} candidates"
                )
            candidates: list[str] = []
            seen: set[str] = set()
            for raw_candidate in raw_candidates:
                if not isinstance(raw_candidate, str):
                    raise PinyinDictionaryError(f"{key} candidate must be text")
                candidate = raw_candidate.strip()
                if not candidate or len(candidate) > MAX_CANDIDATE_LENGTH:
                    raise PinyinDictionaryError(
                        f"{key} candidate length must be 1..{MAX_CANDIDATE_LENGTH}"
                    )
                if candidate not in seen:
                    candidates.append(candidate)
                    seen.add(candidate)
            entries[key] = tuple(candidates)
        return cls(MappingProxyType(entries), str(source))

    @classmethod
    def load(cls, path: os.PathLike[str] | str) -> "PinyinDictionary":
        source = Path(path).expanduser().resolve()
        try:
            document = json.loads(
                source.read_text(encoding="utf-8-sig"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except PinyinDictionaryError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PinyinDictionaryError(f"cannot load {source}: {exc}") from exc
        return cls.from_mapping(document, source=str(source))

    def candidates(
        self,
        pinyin: str,
        *,
        limit: int = MAX_CANDIDATES_SHOWN,
    ) -> tuple[str, ...]:
        key = str(pinyin or "").strip().lower()
        bound = min(MAX_CANDIDATES_SHOWN, max(1, int(limit)))
        exact = self.entries.get(key)
        if exact is None and "'" in key:
            exact = self.entries.get(key.replace("'", ""))
        if exact is not None:
            return exact[:bound]
        if not key:
            return ()
        # Prefix hints make the tiny dictionary useful while a word is still
        # being composed. Ordering is deterministic and remains tightly bound.
        result: list[str] = []
        seen: set[str] = set()
        for entry_key in sorted(self.entries):
            if not entry_key.startswith(key):
                continue
            for candidate in self.entries[entry_key]:
                if candidate not in seen:
                    result.append(candidate)
                    seen.add(candidate)
                    if len(result) >= bound:
                        return tuple(result)
        return tuple(result)


def load_dictionary(path: os.PathLike[str] | str | None = None) -> PinyinDictionary:
    configured = path or os.environ.get("MSYS_INPUT_DICTIONARY")
    return PinyinDictionary.load(configured or DEFAULT_DICTIONARY_PATH)


@dataclass(slots=True)
class PinyinComposer:
    dictionary: PinyinDictionary
    buffer: str = field(default="")

    @property
    def candidates(self) -> tuple[str, ...]:
        return self.dictionary.candidates(self.buffer) if self.buffer else ()

    def feed(self, character: str) -> bool:
        value = str(character or "").lower()
        if len(value) != 1 or value not in "abcdefghijklmnopqrstuvwxyz'":
            return False
        if len(self.buffer) >= MAX_PINYIN_LENGTH:
            return False
        if value == "'" and (not self.buffer or self.buffer.endswith("'")):
            return False
        self.buffer += value
        return True

    def backspace(self) -> bool:
        if not self.buffer:
            return False
        self.buffer = self.buffer[:-1]
        return True

    def clear(self) -> None:
        self.buffer = ""

    def commit(self, index: int = 0) -> str:
        candidates = self.candidates
        if candidates and 0 <= int(index) < len(candidates):
            result = candidates[int(index)]
        else:
            result = self.buffer
        self.clear()
        return result


__all__ = [
    "DEFAULT_DICTIONARY_PATH",
    "DICTIONARY_SCHEMA",
    "MAX_CANDIDATES_PER_ENTRY",
    "MAX_CANDIDATES_SHOWN",
    "MAX_DICTIONARY_ENTRIES",
    "MAX_PINYIN_LENGTH",
    "PinyinComposer",
    "PinyinDictionary",
    "PinyinDictionaryError",
    "load_dictionary",
]
