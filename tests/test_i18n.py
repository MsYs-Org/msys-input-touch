from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from msys_input_touch.i18n import I18N, InputI18n, text


class InputMethodI18nTests(unittest.TestCase):
    def test_catalog_has_localized_package_and_keyboard_copy(self) -> None:
        previous = I18N.locale
        try:
            I18N.set_locale("en-US")
            self.assertEqual(text("app.name"), "Touch keyboard")
            self.assertEqual(text("keyboard.mode.zh"), "Chinese")
            self.assertEqual(
                text("keyboard.status.inject_failed", {"error": "focus"}),
                "Input failed: focus",
            )
            I18N.set_locale("zh-CN")
            self.assertEqual(text("app.name"), "触摸键盘")
            self.assertEqual(text("keyboard.mode.zh"), "中文")
            self.assertEqual(text("keyboard.space"), "空格")
        finally:
            I18N.set_locale(previous)

    def test_default_catalog_is_complete_and_has_no_missing_fallback(self) -> None:
        english = I18N.catalog.messages["en-US"]
        chinese = I18N.catalog.messages["zh-CN"]
        generic_chinese = I18N.catalog.messages["zh"]
        self.assertEqual(set(chinese), set(english))
        self.assertEqual(set(generic_chinese), set(english))
        self.assertEqual(dict(generic_chinese), dict(chinese))
        self.assertIn("app.summary", english)

    def test_environment_locale_normalizes_and_exposes_fallback_chain(self) -> None:
        i18n = InputI18n(environ={"MSYS_LOCALE": "zh_CN.UTF-8"})
        self.assertEqual(i18n.locale, "zh-CN")
        self.assertEqual(i18n.fallback_chain, ("zh-CN", "zh", "en-US"))
        self.assertEqual(i18n("keyboard.hide"), "隐藏")
        self.assertEqual(i18n.set_locale("en_GB"), "en-US")
        self.assertEqual(i18n.fallback_chain, ("en-US",))

    def test_missing_catalog_keeps_safe_english_recovery_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.json"
            i18n = InputI18n(missing, locale="zh-CN")
        self.assertTrue(i18n.load_error)
        self.assertEqual(i18n("keyboard.status.inject_failed", {"error": "focus"}), "Input failed: focus")

    def test_script_locale_uses_generic_chinese_parent_not_english(self) -> None:
        i18n = InputI18n(locale="zh_Hans_CN.UTF-8")
        self.assertEqual(i18n.locale, "zh")
        self.assertEqual(i18n.fallback_chain, ("zh", "en-US"))
        self.assertEqual(i18n("keyboard.hide"), "隐藏")


if __name__ == "__main__":
    unittest.main()
