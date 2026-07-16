from __future__ import annotations

import json
from pathlib import Path
import unittest

from msys_input_touch import __version__


ROOT = Path(__file__).resolve().parents[1]


class InputMethodManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        components = {row["id"]: row for row in cls.manifest["components"]}
        cls.component = components["keyboard"]
        cls.lvgl_component = components["keyboard-lvgl"]

    def test_package_and_build_metadata_versions_match(self) -> None:
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(self.manifest["schema"], "msys.manifest.v1")
        self.assertEqual(self.manifest["package"]["id"], "org.msys.input.touch")
        self.assertEqual(self.manifest["package"]["version"], __version__)
        self.assertIn(f'version = "{__version__}"', project)
        self.assertIn('requires-python = ">=3.10"', project)
        self.assertIn(
            'msys-touch-input = "msys_input_touch.service:main"', project
        )
        self.assertIn(
            'msys-touch-input-lvgl = "msys_input_touch.native_bridge:main"',
            project,
        )
        self.assertIn('where = ["files/app"]', project)

    def test_component_is_lazy_overlay_with_stable_identity(self) -> None:
        self.assertEqual(self.component["id"], "keyboard")
        self.assertEqual(self.component["lifecycle"], "on-demand")
        # The process releases itself after a local hide.  Do not use Core's
        # RPC idle timer because ordinary touch typing has no mIPC traffic.
        self.assertNotIn("idle_timeout_ms", self.component)
        # A hidden process requests an explicit Core stop; restart remains
        # disabled because the next role call is the deliberate wake-up path.
        self.assertEqual(self.component["restart"], "never")
        self.assertEqual(self.component["windowing"]["mode"], "overlay")
        identity = self.component["windowing"]["identity"]
        self.assertEqual(identity["app_id"], "org.msys.input.touch")
        self.assertEqual(identity["x11_wm_class"], "org.msys.input.touch")
        self.assertEqual(identity["x11_wm_instance"], "keyboard")
        self.assertEqual(self.component["env"]["MSYS_WINDOW_ROLE"], "input-method")

    def test_replaceable_role_and_minimal_declared_permissions(self) -> None:
        self.assertEqual(self.component["provides"], [
            {"role": "input-method", "exclusive": True, "priority": 10}
        ])
        self.assertEqual(
            self.component["x-msys-ui-provider"],
            {"id": "tk", "default": False},
        )
        self.assertEqual(set(self.component["permissions"]), {
            "display:x11",
            "x11:inject-input",
            "mipc.call:msys.core.stop",
            "mipc.call:role:window-manager",
            "mipc.event:subscribe:msys.lifecycle.transition",
            "mipc.event:publish:msys.role.ready",
        })
        self.assertEqual(self.component["isolation"], "baseline")

    def test_i18n_metadata_points_inside_immutable_package(self) -> None:
        metadata = self.manifest["package"]["x-msys-i18n"]
        self.assertEqual(metadata, {
            "catalog": "files/share/i18n/catalog.json",
            "name_key": "app.name",
            "summary_key": "app.summary",
        })
        self.assertTrue((ROOT / metadata["catalog"]).is_file())

    def test_lvgl_provider_is_default_and_keeps_the_same_business_permissions(self) -> None:
        component = self.lvgl_component
        self.assertEqual(component["id"], "keyboard-lvgl")
        self.assertEqual(component["runtime"], "python")
        self.assertEqual(component["lifecycle"], "on-demand")
        self.assertEqual(component["restart"], "never")
        self.assertGreater(
            component["provides"][0]["priority"],
            self.component["provides"][0]["priority"],
        )
        self.assertEqual(component["provides"], [
            {"role": "input-method", "exclusive": True, "priority": 100}
        ])
        self.assertEqual(
            component["x-msys-ui-provider"],
            {
                "id": "lvgl",
                "default": True,
                "fallback_component": "org.msys.input.touch:keyboard",
            },
        )
        self.assertEqual(
            set(component["permissions"]), set(self.component["permissions"])
        )
        entry = component["exec"][1]
        self.assertTrue((ROOT / entry.removeprefix("@package/")).is_file())

    def test_entrypoint_and_every_manifest_path_exist(self) -> None:
        entry = self.component["exec"][1]
        self.assertTrue(entry.startswith("@package/"))
        self.assertTrue((ROOT / entry.removeprefix("@package/")).is_file())


if __name__ == "__main__":
    unittest.main()
