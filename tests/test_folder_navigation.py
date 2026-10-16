import io
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from app.subtitle_cleanup import DEFAULT_OPTIONS, SubtitleCleanupTool


def make_tool(script_dir: Path) -> SubtitleCleanupTool:
    tool = SubtitleCleanupTool.__new__(SubtitleCleanupTool)
    tool.options = dict(DEFAULT_OPTIONS)
    tool.script_dir = script_dir
    return tool


@contextmanager
def workspace_directory():
    path = Path.cwd() / "tests" / f"_folder_navigation_{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


class FolderNavigationTests(unittest.TestCase):
    def test_standard_target_selection_starts_with_recursive_scan_and_countdown(self):
        with workspace_directory() as root:
            season = root / "Series" / "Season 01"
            season.mkdir(parents=True)
            (season / "episode.srt").write_text("1\n", encoding="utf-8")
            tool = make_tool(root)

            with (
                patch("subtitle_cleanup.clear_screen"),
                patch("subtitle_cleanup.wait_for_enter_to_customize", return_value=False) as countdown,
                patch("sys.stdout", io.StringIO()) as output,
            ):
                result = tool.select_target_folder("Spellcheck")

            self.assertEqual(result, root.resolve())
            countdown.assert_called_once_with(5)
            self.assertIn("Recursive scanning: ON", output.getvalue())
            self.assertIn("will proceed in 5 seconds", output.getvalue())
            self.assertIn("Series", output.getvalue())

    def test_enter_during_standard_countdown_opens_existing_folder_picker(self):
        with workspace_directory() as root:
            (root / "episode.srt").write_text("1\n", encoding="utf-8")
            selected = root / "Selected"
            selected.mkdir()
            tool = make_tool(root)
            tool.prompt_target_folder = Mock(return_value=selected)

            with (
                patch("subtitle_cleanup.clear_screen"),
                patch("subtitle_cleanup.wait_for_enter_to_customize", return_value=True),
                patch("sys.stdout", io.StringIO()),
            ):
                result = tool.select_target_folder("Spellcheck")

            self.assertEqual(result, selected)
            tool.prompt_target_folder.assert_called_once_with()

    def test_folder_browser_sorts_and_paginates_ten_per_page(self):
        with workspace_directory() as root:
            folders = []
            for number in range(12, 0, -1):
                folder = root / f"Folder {number:02d}"
                folder.mkdir()
                folders.append(folder)
            target = root / "Folder 12"
            (target / "episode.srt").write_text("1\n", encoding="utf-8")
            tool = make_tool(root)

            with (
                patch("subtitle_cleanup.clear_screen"),
                patch("subtitle_cleanup.pause"),
                patch("builtins.input", side_effect=["33", "2", "s"]),
                patch("sys.stdout", io.StringIO()),
            ):
                result = tool.prompt_target_folder(start_folder=root)

            self.assertEqual(result, target.resolve())

    def test_folder_browser_can_go_up_one_level(self):
        with workspace_directory() as root:
            child = root / "Child"
            child.mkdir()
            (root / "episode.srt").write_text("1\n", encoding="utf-8")
            tool = make_tool(root)

            with (
                patch("subtitle_cleanup.clear_screen"),
                patch("builtins.input", side_effect=["u", "s"]),
                patch("sys.stdout", io.StringIO()),
            ):
                result = tool.prompt_target_folder(start_folder=child)

            self.assertEqual(result, root.resolve())

    def test_folder_browser_preserves_relative_path_entry(self):
        with workspace_directory() as root:
            target = root / "Target"
            target.mkdir()
            (target / "episode.srt").write_text("1\n", encoding="utf-8")
            tool = make_tool(root)

            with (
                patch("subtitle_cleanup.clear_screen"),
                patch("builtins.input", return_value="Target"),
                patch("sys.stdout", io.StringIO()),
            ):
                result = tool.prompt_target_folder(start_folder=root)

            self.assertEqual(result, target.resolve())

    def test_folder_browser_preserves_absolute_path_entry(self):
        with workspace_directory() as root:
            target = root / "Target"
            target.mkdir()
            (target / "episode.srt").write_text("1\n", encoding="utf-8")
            tool = make_tool(root)

            with (
                patch("subtitle_cleanup.clear_screen"),
                patch("builtins.input", return_value=str(target)),
                patch("sys.stdout", io.StringIO()),
            ):
                result = tool.prompt_target_folder(start_folder=root)

            self.assertEqual(result, target.resolve())


if __name__ == "__main__":
    unittest.main()
