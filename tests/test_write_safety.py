import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from app.subtitle_cleanup import DEFAULT_OPTIONS
from tests.test_spellcheck import make_tool


class AtomicSubtitleWriteTests(unittest.TestCase):
    def test_atomic_write_flushes_and_replaces_from_same_directory(self):
        tool = make_tool()
        target = Path("C:/Example/episode.srt")
        handle = Mock()
        handle.name = "C:/Example/.episode.srt.random.tmp"
        manager = Mock()
        manager.__enter__ = Mock(return_value=handle)
        manager.__exit__ = Mock(return_value=False)

        with (
            patch("subtitle_cleanup.tempfile.NamedTemporaryFile", return_value=manager) as temporary,
            patch("subtitle_cleanup.os.fsync") as fsync,
            patch("subtitle_cleanup.os.replace") as replace,
            patch.object(Path, "unlink") as unlink,
        ):
            tool.atomic_write_bytes(target, b"complete subtitle")

        temporary.assert_called_once_with(
            mode="wb",
            dir=target.parent,
            prefix=".episode.srt.",
            suffix=".tmp",
            delete=False,
        )
        handle.write.assert_called_once_with(b"complete subtitle")
        handle.flush.assert_called_once_with()
        fsync.assert_called_once_with(handle.fileno.return_value)
        replace.assert_called_once_with(Path(handle.name), target)
        unlink.assert_called_once_with(missing_ok=True)

    def test_atomic_write_cleans_temporary_file_when_replace_fails(self):
        tool = make_tool()
        target = Path("C:/Example/episode.srt")
        handle = Mock()
        handle.name = "C:/Example/.episode.srt.random.tmp"
        manager = Mock()
        manager.__enter__ = Mock(return_value=handle)
        manager.__exit__ = Mock(return_value=False)

        with (
            patch("subtitle_cleanup.tempfile.NamedTemporaryFile", return_value=manager),
            patch("subtitle_cleanup.os.fsync"),
            patch("subtitle_cleanup.os.replace", side_effect=OSError("replace failed")),
            patch.object(Path, "unlink") as unlink,
        ):
            with self.assertRaisesRegex(OSError, "replace failed"):
                tool.atomic_write_bytes(target, b"complete subtitle")

        unlink.assert_called_once_with(missing_ok=True)


class BackupFailureTests(unittest.TestCase):
    def test_cli_backup_restore_confirmation_restores_exact_bytes(self):
        tool = make_tool()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subtitle = root / "episode.srt"
            archive_path = root / "backup_subtitles.zip"
            original = b"1\r\n00:00:01,000 --> 00:00:02,000\r\nOriginal line.\r\n"
            subtitle.write_bytes(b"changed")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("episode.srt", original)
            tool.select_target_folder = Mock(return_value=root)

            with (
                patch("builtins.input", side_effect=["YES", ""]),
                patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                tool.restore_subtitles_from_backup_cli()

            self.assertEqual(subtitle.read_bytes(), original)
            self.assertTrue(archive_path.is_file())
            self.assertIn(
                "Restored 1 subtitle file(s) from 1 archive(s).",
                output.getvalue(),
            )
            self.assertIn("The backup archives were retained.", output.getvalue())

    def test_restore_discovers_and_restores_root_and_child_archives(self):
        tool = make_tool()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            child = root / "Season 1"
            child.mkdir()
            (root / "episode.srt").write_text("changed", encoding="utf-8")
            (child / "episode.srt").write_text("changed", encoding="utf-8")
            with zipfile.ZipFile(root / "backup_subtitles.zip", "w") as archive:
                archive.writestr("episode.srt", "root original")
            with zipfile.ZipFile(child / "backup_subtitles.zip", "w") as archive:
                archive.writestr("episode.srt", "child original")

            result = tool.restore_backup_archives(root)

            self.assertEqual(result, (2, 2))
            self.assertEqual((root / "episode.srt").read_text(), "root original")
            self.assertEqual((child / "episode.srt").read_text(), "child original")
            self.assertTrue((root / "backup_subtitles.zip").exists())
            self.assertTrue((child / "backup_subtitles.zip").exists())

    def test_restore_rejects_traversal_before_overwriting_files(self):
        tool = make_tool()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            subtitle = root / "episode.srt"
            subtitle.write_text("current", encoding="utf-8")
            with zipfile.ZipFile(root / "backup_subtitles.zip", "w") as archive:
                archive.writestr("episode.srt", "original")
                archive.writestr("../outside.srt", "unsafe")

            with self.assertRaisesRegex(ValueError, "unsafe path"):
                tool.restore_backup_archives(root)

            self.assertEqual(subtitle.read_text(), "current")
            self.assertFalse((root.parent / "outside.srt").exists())

    def test_disabled_backups_can_be_enabled_before_editing(self):
        tool = make_tool()
        tool.options = dict(DEFAULT_OPTIONS)
        tool.save_options = Mock()
        tool.backup_groups = Mock(return_value={})
        root = Path("C:/Example")
        subtitle = root / "episode.srt"

        with (
            patch("builtins.input", return_value="1"),
            patch("sys.stdout", io.StringIO()),
        ):
            succeeded = tool.create_backup_if_needed(root, [subtitle])

        self.assertTrue(succeeded)
        self.assertTrue(tool.options["create_backup_subtitles_zip_before_editing"])
        tool.save_options.assert_called_once_with()
        tool.backup_groups.assert_called_once_with(root, [subtitle])

    def test_disabled_backups_can_be_explicitly_bypassed_for_one_run(self):
        tool = make_tool()
        tool.options = dict(DEFAULT_OPTIONS)
        tool.backup_groups = Mock()

        with (
            patch("builtins.input", return_value="2"),
            patch("sys.stdout", io.StringIO()),
        ):
            succeeded = tool.create_backup_if_needed(
                Path("C:/Example"),
                [Path("C:/Example/episode.srt")],
            )

        self.assertTrue(succeeded)
        self.assertFalse(tool.options["create_backup_subtitles_zip_before_editing"])
        tool.backup_groups.assert_not_called()

    def test_disabled_backups_can_cancel_editing(self):
        tool = make_tool()
        tool.options = dict(DEFAULT_OPTIONS)
        tool.backup_groups = Mock()

        with (
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", io.StringIO()),
        ):
            succeeded = tool.create_backup_if_needed(
                Path("C:/Example"),
                [Path("C:/Example/episode.srt")],
            )

        self.assertFalse(succeeded)
        tool.backup_groups.assert_not_called()

    def test_backup_creation_failure_removes_partial_archive_and_blocks_editing(self):
        tool = make_tool()
        tool.options = dict(DEFAULT_OPTIONS)
        tool.options["create_backup_subtitles_zip_before_editing"] = True
        root = Path("C:/Example")
        subtitle = root / "episode.srt"
        tool.backup_groups = Mock(return_value={root: [subtitle]})

        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(Path, "unlink") as unlink,
            patch("subtitle_cleanup.zipfile.ZipFile", side_effect=OSError("disk full")),
            patch("subtitle_cleanup.os.replace") as replace,
            patch("sys.stdout", io.StringIO()),
        ):
            succeeded = tool.create_backup_if_needed(root, [subtitle])

        self.assertFalse(succeeded)
        self.assertEqual(unlink.call_count, 2)
        replace.assert_not_called()

    def test_completed_backup_is_flushed_then_atomically_published(self):
        tool = make_tool()
        tool.options = dict(DEFAULT_OPTIONS)
        tool.options["create_backup_subtitles_zip_before_editing"] = True
        root = Path("C:/Example")
        subtitle = root / "episode.srt"
        backup = root / "backup_subtitles.zip"
        temporary = root / ".backup_subtitles.zip.tmp"
        tool.backup_groups = Mock(return_value={root: [subtitle]})
        archive = Mock()
        archive_manager = Mock()
        archive_manager.__enter__ = Mock(return_value=archive)
        archive_manager.__exit__ = Mock(return_value=False)
        handle = Mock()
        file_manager = Mock()
        file_manager.__enter__ = Mock(return_value=handle)
        file_manager.__exit__ = Mock(return_value=False)

        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(Path, "unlink"),
            patch.object(Path, "open", return_value=file_manager),
            patch("subtitle_cleanup.zipfile.ZipFile", return_value=archive_manager),
            patch("subtitle_cleanup.os.fsync") as fsync,
            patch("subtitle_cleanup.os.replace") as replace,
            patch("sys.stdout", io.StringIO()),
        ):
            succeeded = tool.create_backup_if_needed(root, [subtitle])

        self.assertTrue(succeeded)
        archive.write.assert_called_once_with(subtitle, Path("episode.srt"))
        fsync.assert_called_once_with(handle.fileno.return_value)
        replace.assert_called_once_with(temporary, backup)


if __name__ == "__main__":
    unittest.main()
