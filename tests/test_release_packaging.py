import hashlib
import unittest
import zipfile
from pathlib import Path

from tools import build_multiplatform_release


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingTests(unittest.TestCase):
    def test_multiplatform_manifest_is_an_explicit_runtime_allowlist(self):
        destinations = {
            destination.as_posix()
            for _source, destination in build_multiplatform_release.release_manifest(
                PROJECT_ROOT
            )
        }

        self.assertIn("README.md", destinations)
        self.assertIn("LICENSE", destinations)
        self.assertIn("app/__init__.py", destinations)
        self.assertIn("app/subtitle_cleanup.py", destinations)
        self.assertIn("app/subtitle_gui.py", destinations)
        self.assertIn("app/update_helper.py", destinations)
        self.assertIn("SubtitleUniverseSpellcheck.pyw", destinations)
        self.assertIn("assets/subtitle-universe-quill.png", destinations)
        self.assertIn("assets/subtitle-universe-quill.ico", destinations)
        self.assertNotIn("app/SubtitleUniverseSpellcheck.pyw", destinations)
        self.assertIn("dictionaries/base/american_words.txt", destinations)
        self.assertIn("dictionaries/base/british_words.txt", destinations)
        self.assertIn("docs/USER_GUIDE.md", destinations)
        self.assertNotIn("SPEC.md", destinations)
        self.assertNotIn("STATUS.md", destinations)
        self.assertFalse(any(path.startswith("tests/") for path in destinations))
        self.assertFalse(any("user" in path for path in destinations))

    def test_multiplatform_archive_contains_only_manifest_files(self):
        output_directory = Path(__file__).with_name("_release_artifacts_test")
        output_directory.mkdir(exist_ok=True)
        try:
            archive_path, checksum_path = (
                build_multiplatform_release.build_source_release(
                    project_root=PROJECT_ROOT,
                    output_directory=output_directory,
                )
            )

            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            self.assertEqual(
                checksum_path.read_text(encoding="ascii"),
                f"{digest}  {archive_path.name}\n",
            )
            with zipfile.ZipFile(archive_path) as archive:
                files = {
                    name
                    for name in archive.namelist()
                    if name and not name.endswith("/")
                }

            expected_tail_paths = {
                destination.as_posix()
                for _source, destination in build_multiplatform_release.release_manifest(
                    PROJECT_ROOT
                )
            }
            archive_roots = {name.split("/", 1)[0] for name in files}
            self.assertEqual(len(archive_roots), 1)
            root = archive_roots.pop()
            self.assertEqual(
                files,
                {f"{root}/{path}" for path in expected_tail_paths},
            )
        finally:
            for path in output_directory.iterdir():
                path.unlink()
            output_directory.rmdir()

    def test_public_readme_documents_source_python_requirement(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Python 3.9 or later", readme)
        self.assertIn("Tkinter", readme)

    def test_public_readme_opens_with_release_platform_and_capability_summary(self):
        introduction = (PROJECT_ROOT / "README.md").read_text(
            encoding="utf-8"
        )[:3000]

        self.assertIn("graphical", introduction.casefold())
        self.assertIn("command-line", introduction.casefold())
        self.assertIn("formatting", introduction.casefold())
        self.assertIn("spellcheck", introduction.casefold())
        self.assertIn("dictionary", introduction.casefold())
        self.assertIn("recovery", introduction.casefold())
        self.assertIn("Python 3.9 or later", introduction)
        self.assertIn("Windows", introduction)
        self.assertIn("macOS", introduction)
        self.assertIn("Linux", introduction)
        self.assertIn("not yet been validated on physical systems", introduction)

    def test_windows_builder_uses_dual_interface_launcher_and_includes_readme(self):
        script = (PROJECT_ROOT / "tools" / "build_windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('"app\\subtitle_gui.py"', script)
        self.assertIn("--console", script)
        self.assertIn("--paths", script)
        self.assertIn('"README.md"', script)
        self.assertIn("--version", script)
        self.assertIn("Forbidden runtime data", script)
        self.assertIn("SubtitleUniverseUpdater.exe", script)
        self.assertIn('"app\\update_helper.py"', script)
        self.assertIn("--icon", script)
        self.assertIn('"assets\\subtitle-universe-quill.ico"', script)
        self.assertIn('"assets\\subtitle-universe-quill.png"', script)

    def test_windows_builder_pin_matches_build_requirements(self):
        script = (PROJECT_ROOT / "tools" / "build_windows.ps1").read_text(
            encoding="utf-8"
        )
        requirements = (PROJECT_ROOT / "requirements-build.txt").read_text(
            encoding="utf-8"
        )

        self.assertIn('$expectedPyInstallerVersion = "6.22.3"', script)
        self.assertEqual(requirements.strip().casefold(), "pyinstaller==6.22.3")


if __name__ == "__main__":
    unittest.main()
