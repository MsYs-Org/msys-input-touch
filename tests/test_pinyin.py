from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from msys_input_touch.pinyin import (
    MAX_CANDIDATES_PER_ENTRY,
    MAX_CANDIDATES_SHOWN,
    MAX_DICTIONARY_ENTRIES,
    MAX_PINYIN_LENGTH,
    PinyinComposer,
    PinyinDictionary,
    PinyinDictionaryError,
    load_dictionary,
)


def document() -> dict:
    return {
        "schema": "msys.pinyin-dictionary.v1",
        "entries": {
            "ni": ["你", "呢"],
            "nihao": ["你好"],
            "hao": ["好"],
        },
    }


class PinyinDictionaryTests(unittest.TestCase):
    def test_packaged_dictionary_is_bounded_and_useful(self) -> None:
        dictionary = load_dictionary()
        self.assertLessEqual(len(dictionary.entries), MAX_DICTIONARY_ENTRIES)
        self.assertGreaterEqual(len(dictionary.entries), 4000)
        self.assertEqual(dictionary.candidates("nihao"), ("你好",))
        self.assertEqual(dictionary.candidates("shurufa"), ("输入法",))
        self.assertEqual(dictionary.candidates("xianzai")[:1], ("现在",))
        for syllable in ("ni", "shi", "yi"):
            with self.subTest(syllable=syllable):
                self.assertGreater(len(dictionary.candidates(syllable)), 16)
                self.assertLessEqual(
                    len(dictionary.candidates(syllable)), MAX_CANDIDATES_SHOWN
                )
        self.assertEqual(dictionary.candidates("pengyou")[:1], ("朋友",))
        self.assertTrue(all(
            len(candidates) <= MAX_CANDIDATES_PER_ENTRY
            for candidates in dictionary.entries.values()
        ))

    def test_exact_results_win_and_prefix_hints_are_deterministic(self) -> None:
        dictionary = PinyinDictionary.from_mapping(document())
        self.assertEqual(dictionary.candidates("ni"), ("你", "呢"))
        self.assertEqual(dictionary.candidates("nih"), ("你好",))
        self.assertEqual(dictionary.candidates("ni'hao"), ("你好",))
        self.assertEqual(dictionary.candidates("missing"), ())
        with self.assertRaises(TypeError):
            dictionary.entries["x"] = ("下",)  # type: ignore[index]

    def test_composer_is_bounded_and_commits_candidate_or_raw_text(self) -> None:
        composer = PinyinComposer(PinyinDictionary.from_mapping(document()))
        for character in "nihao":
            self.assertTrue(composer.feed(character))
        self.assertEqual(composer.candidates, ("你好",))
        self.assertEqual(composer.commit(), "你好")
        self.assertEqual(composer.buffer, "")

        for _ in range(MAX_PINYIN_LENGTH + 20):
            composer.feed("a")
        self.assertEqual(len(composer.buffer), MAX_PINYIN_LENGTH)
        self.assertEqual(composer.commit(), "a" * MAX_PINYIN_LENGTH)

    def test_backspace_and_apostrophe_rules_are_predictable(self) -> None:
        composer = PinyinComposer(PinyinDictionary.from_mapping(document()))
        self.assertFalse(composer.feed("'"))
        self.assertTrue(composer.feed("n"))
        self.assertTrue(composer.feed("'"))
        self.assertFalse(composer.feed("'"))
        self.assertTrue(composer.backspace())
        self.assertEqual(composer.buffer, "n")

    def test_invalid_and_duplicate_external_dictionary_is_rejected(self) -> None:
        with self.assertRaisesRegex(PinyinDictionaryError, "invalid Pinyin key"):
            PinyinDictionary.from_mapping({
                "schema": "msys.pinyin-dictionary.v1",
                "entries": {"bad key": ["坏"]},
            })
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dictionary.json"
            path.write_text(
                '{"schema":"msys.pinyin-dictionary.v1",'
                '"entries":{"ni":["你"],"ni":["呢"]}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PinyinDictionaryError, "duplicate JSON key"):
                PinyinDictionary.load(path)

            path.write_text(json.dumps(document(), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(PinyinDictionary.load(path).candidates("hao"), ("好",))


if __name__ == "__main__":
    unittest.main()
