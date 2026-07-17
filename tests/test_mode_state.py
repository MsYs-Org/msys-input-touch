from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from msys_input_touch.mode_state import (
    InputModeStore,
    default_mode_path,
    locale_default_mode,
)


class InputModeStoreTests(unittest.TestCase):
    def test_locale_selects_default_only_when_no_valid_saved_mode_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input-mode.conf"
            store = InputModeStore(path, environ={"MSYS_LOCALE": "zh_CN.UTF-8"})
            self.assertEqual(store.load(), "zh")
            path.write_text("invalid\n", encoding="ascii")
            self.assertEqual(store.load(), "zh")
            path.write_text("symbols\n", encoding="ascii")
            self.assertEqual(store.load(), "symbols")

    def test_non_chinese_or_missing_locale_defaults_to_english(self) -> None:
        self.assertEqual(locale_default_mode({}), "en")
        self.assertEqual(locale_default_mode({"MSYS_LOCALE": "en-US"}), "en")
        self.assertEqual(locale_default_mode({"MSYS_LOCALE": "zh-Hans-CN"}), "zh")

    def test_app_state_is_shared_before_component_specific_state(self) -> None:
        path = default_mode_path(
            {
                "MSYS_APP_STATE_DIR": "/state/package",
                "MSYS_COMPONENT_STATE_DIR": "/state/component",
            }
        )
        self.assertEqual(path, Path("/state/package/input-mode.conf"))

    def test_every_supported_mode_is_atomically_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "input-mode.conf"
            store = InputModeStore(path, environ={})
            for mode in ("en", "zh", "numeric", "symbols"):
                with self.subTest(mode=mode):
                    store.save(mode)
                    self.assertEqual(path.read_text(encoding="ascii"), mode + "\n")
                    self.assertEqual(InputModeStore(path).load(), mode)
            self.assertEqual(list(path.parent.glob(".input-mode.conf.tmp-*")), [])

    def test_unsupported_mode_is_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input-mode.conf"
            with self.assertRaises(ValueError):
                InputModeStore(path).save("emoji")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
