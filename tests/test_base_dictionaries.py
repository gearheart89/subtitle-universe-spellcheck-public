import unittest
from pathlib import Path
from unittest.mock import patch

from subtitle_cleanup import SubtitleCleanupTool, application_root


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_DICTIONARY_DIR = PROJECT_ROOT / "dictionaries" / "base"


class BaseDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.american_path = BASE_DICTIONARY_DIR / "american_words.txt"
        self.british_path = BASE_DICTIONARY_DIR / "british_words.txt"

    def load_words(self, path: Path) -> set[str]:
        return {
            line.strip().casefold()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    def test_packaged_base_dictionaries_are_substantial_and_distinct(self):
        american = self.load_words(self.american_path)
        british = self.load_words(self.british_path)

        self.assertGreater(len(american), 50_000)
        self.assertGreater(len(british), 50_000)
        self.assertNotEqual(american, british)

    def test_american_dictionary_uses_american_spelling(self):
        american = self.load_words(self.american_path)

        self.assertIn("color", american)
        self.assertIn("organize", american)
        self.assertNotIn("colour", american)
        self.assertNotIn("organise", american)

    def test_british_dictionary_accepts_ise_and_oxford_ize(self):
        british = self.load_words(self.british_path)

        self.assertIn("colour", british)
        self.assertIn("organise", british)
        self.assertIn("organize", british)
        self.assertNotIn("color", british)

    def test_provenance_and_required_license_are_packaged(self):
        source = (BASE_DICTIONARY_DIR / "README.md").read_text(encoding="utf-8")
        license_text = (BASE_DICTIONARY_DIR / "SCOWL-COPYRIGHT.txt").read_text(encoding="utf-8")

        self.assertIn("2026.02.25", source)
        self.assertIn("7e99edab8e32f9f9ea2b15f249ca8d4d67237410", source)
        self.assertIn("Copyright 2000-2026 by Kevin Atkinson", license_text)
        self.assertIn("Permission to use, copy, modify, distribute", license_text)

    def test_runtime_loads_the_selected_packaged_dictionary(self):
        tool = SubtitleCleanupTool.__new__(SubtitleCleanupTool)
        tool.base_dir = BASE_DICTIONARY_DIR

        american = tool.load_word_set(self.american_path)
        british = tool.load_word_set(self.british_path)

        self.assertIn("color", american)
        self.assertNotIn("colour", american)
        self.assertIn("colour", british)
        self.assertIn("organise", british)
        self.assertIn("organize", british)

    def test_application_root_is_the_source_folder_for_python_execution(self):
        expected = Path(__import__("subtitle_cleanup").__file__).resolve().parent

        with patch("subtitle_cleanup.sys.frozen", False, create=True):
            self.assertEqual(application_root(), expected)

    def test_application_root_is_beside_the_frozen_executable(self):
        executable = Path("C:/Portable/SubtitleUniverseSpellcheck.exe")

        with (
            patch("subtitle_cleanup.sys.frozen", True, create=True),
            patch("subtitle_cleanup.sys.executable", str(executable)),
        ):
            self.assertEqual(application_root(), executable.resolve().parent)


if __name__ == "__main__":
    unittest.main()
