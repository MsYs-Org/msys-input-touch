from __future__ import annotations

import json
from pathlib import Path
import tomllib
import unittest

from msys_input_touch import __version__


ROOT = Path(__file__).resolve().parents[1]


class InputMethodManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        cls.component = cls.manifest["components"][0]

    def test_package_and_build_metadata_versions_match(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(self.manifest["schema"], "msys.manifest.v1")
        self.assertEqual(self.manifest["package"]["id"], "org.msys.input.touch")
        self.assertEqual(self.manifest["package"]["version"], __version__)
        self.assertEqual(project["project"]["version"], __version__)
        self.assertEqual(project["project"]["requires-python"], ">=3.10")
        self.assertEqual(
            project["project"]["scripts"]["msys-touch-input"],
            "msys_input_touch.service:main",
        )
        self.assertEqual(project["tool"]["setuptools"]["packages"]["find"]["where"], ["files/app"])

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
            {"role": "input-method", "exclusive": True, "priority": 50}
        ])
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

    def test_entrypoint_and_every_manifest_path_exist(self) -> None:
        entry = self.component["exec"][1]
        self.assertTrue(entry.startswith("@package/"))
        self.assertTrue((ROOT / entry.removeprefix("@package/")).is_file())


if __name__ == "__main__":
    unittest.main()
