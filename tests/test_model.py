from __future__ import annotations

import unittest

from msys_input_touch.model import INPUT_MODES, KeyboardModel
from msys_input_touch.pinyin import PinyinDictionary


def dictionary() -> PinyinDictionary:
    return PinyinDictionary.from_mapping({
        "schema": "msys.pinyin-dictionary.v1",
        "entries": {"ni": ["你", "呢"], "nihao": ["你好"]},
    })


class KeyboardModelTests(unittest.TestCase):
    def test_english_shift_is_one_shot_and_special_keys_are_typed(self) -> None:
        model = KeyboardModel(dictionary(), "en")
        self.assertEqual(model.handle("shift")[0].kind, "refresh")
        action = model.handle("char:a")[0]
        self.assertEqual((action.kind, action.value), ("key", "A"))
        self.assertTrue(action.refresh)
        self.assertFalse(model.shift)
        self.assertFalse(model.handle("char:b")[0].refresh)
        self.assertEqual(model.handle("backspace")[0].value, "BackSpace")
        self.assertEqual(model.handle("enter")[0].value, "Return")
        self.assertEqual(model.handle("space")[0].value, "space")

    def test_chinese_letters_compose_and_candidate_commits_as_text(self) -> None:
        model = KeyboardModel(dictionary(), "zh")
        for character in "nihao":
            self.assertEqual(model.handle(f"char:{character}")[0].kind, "refresh")
        self.assertEqual(model.composition, "nihao")
        self.assertEqual(model.candidates, ("你好",))
        action = model.handle("candidate:0")[0]
        self.assertEqual((action.kind, action.value), ("text", "你好"))
        self.assertEqual(model.composition, "")

    def test_chinese_backspace_and_punctuation_have_phone_like_order(self) -> None:
        model = KeyboardModel(dictionary(), "zh")
        model.handle("char:n")
        model.handle("char:i")
        self.assertEqual(model.handle("backspace")[0].kind, "refresh")
        self.assertEqual(model.composition, "n")
        actions = model.handle("char:。")
        self.assertEqual([(item.kind, item.value) for item in actions], [
            ("text", "你"),
            ("text", "。"),
        ])

    def test_mode_switch_and_hide_clear_transient_composition(self) -> None:
        model = KeyboardModel(dictionary(), "zh")
        model.handle("char:n")
        model.handle("mode:numeric")
        self.assertEqual(model.mode, "numeric")
        self.assertEqual(model.composition, "")
        model.handle("mode:zh")
        model.handle("char:n")
        self.assertEqual(model.handle("hide")[0].kind, "hide")
        self.assertEqual(model.composition, "")

    def test_every_mode_has_four_bounded_rows_and_core_controls(self) -> None:
        model = KeyboardModel(dictionary())
        for mode in sorted(INPUT_MODES):
            with self.subTest(mode=mode):
                model.set_mode(mode)
                rows = model.layout()
                self.assertEqual(len(rows), 4)
                self.assertTrue(all(1 <= len(row) <= 10 for row in rows))
                tokens = {key.token for row in rows for key in row}
                self.assertIn("backspace", tokens)
                self.assertIn("enter", tokens)
                self.assertIn("space", tokens)


if __name__ == "__main__":
    unittest.main()
