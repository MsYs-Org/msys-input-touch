from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "files/app/msys_input_touch"


class TkFontIntegrationTests(unittest.TestCase):
    def test_input_method_uses_the_sdk_policy_without_a_local_copy(self) -> None:
        self.assertFalse((PACKAGE / "tk_fonts.py").exists())
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py")
        )
        self.assertIn(
            "from msys_sdk.ui_fonts import configure_tk_fonts",
            source,
        )
        self.assertIn("from msys_sdk.ui_fonts import font_spec", source)
        self.assertNotIn('font=("Sans",', source)

    def test_self_contained_overlay_is_importable_from_files_app(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("msys-sdk/msys_sdk=files/app/msys_sdk", readme)


if __name__ == "__main__":
    unittest.main()
