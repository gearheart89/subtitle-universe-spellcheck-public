import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

from app.subtitle_cleanup import ReleaseAsset, ReleaseUpdate, SubtitleCleanupTool, UpdateError
from app.update_helper import UpdateApplyError, apply_update_plan
from app.subtitle_gui import complete_update_cleanup


def write_source_update(archive_path: Path, version: str = "2.0.0") -> str:
    root = f"SubtitleUniverseSpellcheck-{version}"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(f"{root}/SubtitleUniverseSpellcheck.pyw", "launcher")
        archive.writestr(
            f"{root}/app/subtitle_cleanup.py",
            f'SCRIPT_VERSION = "{version}"\n',
        )
        archive.writestr(f"{root}/app/subtitle_gui.py", "gui")
        archive.writestr(f"{root}/app/update_helper.py", "helper")
        archive.writestr(f"{root}/dictionaries/base/american_words.txt", "word\n")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    Path(str(archive_path) + ".sha256").write_text(
        f"{digest}  {archive_path.name}\n", encoding="ascii"
    )
    return digest


class TransactionalUpdateTests(unittest.TestCase):
    def test_restarted_launcher_removes_external_helper_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installation = root / "application"
            helper = root / ".subtitle-universe-update-helper-test"
            installation.mkdir()
            helper.mkdir()
            (helper / "updater.exe").write_text("busy", encoding="utf-8")

            self.assertTrue(complete_update_cleanup(helper, root=installation))

            self.assertFalse(helper.exists())
            self.assertFalse(
                (installation / "dictionaries" / "pending_update_cleanup.json").exists()
            )

    def test_failed_helper_cleanup_is_retried_from_persistent_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installation = root / "application"
            helper = root / ".subtitle-universe-update-helper-test"
            installation.mkdir()
            helper.mkdir()
            locked = Mock(side_effect=PermissionError("locked"))

            self.assertFalse(
                complete_update_cleanup(
                    helper,
                    root=installation,
                    remover=locked,
                    sleeper=lambda _delay: None,
                    attempts=2,
                )
            )
            marker = installation / "dictionaries" / "pending_update_cleanup.json"
            self.assertTrue(marker.is_file())

            self.assertTrue(complete_update_cleanup(root=installation))
            self.assertFalse(helper.exists())
            self.assertFalse(marker.exists())

    def test_launcher_rejects_arbitrary_cleanup_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installation = root / "application"
            unrelated = root / "documents"
            installation.mkdir()
            unrelated.mkdir()

            self.assertFalse(complete_update_cleanup(unrelated, root=installation))
            self.assertTrue(unrelated.is_dir())

    def test_helper_replaces_distribution_preserves_data_and_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installation = root / "application"
            payload = root / "payload"
            backup = root / "application.previous"
            installation.mkdir()
            payload.mkdir()
            (installation / "program.txt").write_text("old", encoding="utf-8")
            (payload / "program.txt").write_text("new", encoding="utf-8")
            user_file = installation / "dictionaries" / "user" / "words.txt"
            user_file.parent.mkdir(parents=True)
            user_file.write_text("Vala\n", encoding="utf-8")
            (installation / "launch gui.txt").write_text("gui", encoding="utf-8")
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "installation_root": str(installation),
                        "payload_root": str(payload),
                        "backup_root": str(backup),
                        "wait_for_pid": 42,
                        "health_check_command": ["health"],
                        "expected_health_output": "Subtitle Universe Spellcheck 2.0.0",
                        "restart_command": ["restart-new"],
                        "rollback_restart_command": ["restart-old"],
                        "preserve_paths": [
                            "dictionaries/user",
                            "launch gui.txt",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            runner = Mock(
                return_value=subprocess.CompletedProcess(
                    ["health"], 0, "Subtitle Universe Spellcheck 2.0.0\n", ""
                )
            )
            launcher = Mock()

            apply_update_plan(
                plan_path,
                wait_for_exit=lambda pid, timeout: pid == 42,
                command_runner=runner,
                process_launcher=launcher,
            )

            self.assertEqual((installation / "program.txt").read_text(), "new")
            self.assertEqual(
                (installation / "dictionaries" / "user" / "words.txt").read_text(),
                "Vala\n",
            )
            self.assertEqual((installation / "launch gui.txt").read_text(), "gui")
            self.assertFalse(backup.exists())
            launcher.assert_called_once_with(["restart-new"])

    def test_helper_rolls_back_when_new_runtime_health_check_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installation = root / "application"
            payload = root / "payload"
            backup = root / "application.previous"
            installation.mkdir()
            payload.mkdir()
            (installation / "program.txt").write_text("old", encoding="utf-8")
            (payload / "program.txt").write_text("broken", encoding="utf-8")
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "installation_root": str(installation),
                        "payload_root": str(payload),
                        "backup_root": str(backup),
                        "wait_for_pid": 0,
                        "health_check_command": ["health"],
                        "expected_health_output": "Subtitle Universe Spellcheck 2.0.0",
                        "restart_command": ["restart-new"],
                        "rollback_restart_command": ["restart-old"],
                        "preserve_paths": [],
                    }
                ),
                encoding="utf-8",
            )
            runner = Mock(return_value=subprocess.CompletedProcess(["health"], 1, "", "bad"))
            launcher = Mock()

            with self.assertRaisesRegex(UpdateApplyError, "rolled back"):
                apply_update_plan(
                    plan_path,
                    wait_for_exit=lambda _pid, _timeout: True,
                    command_runner=runner,
                    process_launcher=launcher,
                )

            self.assertEqual((installation / "program.txt").read_text(), "old")
            self.assertFalse(backup.exists())
            launcher.assert_called_once_with(["restart-old"])

    def test_engine_stages_verified_source_update_outside_installation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installation = root / "current"
            installation.mkdir()
            helper_source = installation / "app" / "update_helper.py"
            helper_source.parent.mkdir()
            helper_source.write_text("helper", encoding="utf-8")
            archive = root / "SubtitleUniverseSpellcheck-2.0.0-source.zip"
            digest = write_source_update(archive)
            release = ReleaseUpdate(
                "2.0.0",
                "v2.0.0",
                "Release",
                "https://github.com/release",
                "",
                ReleaseAsset(archive.name, "https://github.com/archive", archive.stat().st_size),
                ReleaseAsset(archive.name + ".sha256", "https://github.com/checksum", 100),
            )
            tool = SubtitleCleanupTool()
            tool.script_dir = installation

            prepared = tool.prepare_update_installation(
                release,
                archive,
                interface="gui",
                frozen=False,
                executable="python",
                staging_parent=root / "staging",
                helper_parent=root / "helper",
            )

            plan = json.loads(prepared.plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["installation_root"], str(installation.resolve()))
            self.assertTrue(Path(plan["payload_root"]).is_dir())
            self.assertFalse(Path(plan["payload_root"]).is_relative_to(installation))
            self.assertEqual(plan["expected_health_output"], "Subtitle Universe Spellcheck 2.0.0")
            self.assertEqual(prepared.archive_digest, digest)
            self.assertEqual(prepared.helper_command[-1], str(prepared.plan_path))

    def test_engine_rejects_modified_local_archive_before_staging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installation = root / "current"
            (installation / "app").mkdir(parents=True)
            (installation / "app" / "update_helper.py").write_text("helper", encoding="utf-8")
            archive = root / "SubtitleUniverseSpellcheck-2.0.0-source.zip"
            write_source_update(archive)
            archive.write_bytes(archive.read_bytes() + b"changed")
            release = Mock(version="2.0.0")
            tool = SubtitleCleanupTool()
            tool.script_dir = installation

            with self.assertRaisesRegex(UpdateError, "checksum"):
                tool.prepare_update_installation(
                    release,
                    archive,
                    interface="cli",
                    frozen=False,
                    executable="python",
                    staging_parent=root / "staging",
                    helper_parent=root / "helper",
                )

            self.assertFalse((root / "staging").exists())

    def test_engine_refuses_to_replace_a_git_working_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installation = root / "current"
            (installation / ".git").mkdir(parents=True)
            archive = root / "SubtitleUniverseSpellcheck-2.0.0-source.zip"
            write_source_update(archive)
            tool = SubtitleCleanupTool()
            tool.script_dir = installation

            with self.assertRaisesRegex(UpdateError, "Git working copy"):
                tool.prepare_update_installation(
                    Mock(version="2.0.0"),
                    archive,
                    interface="gui",
                    frozen=False,
                )


if __name__ == "__main__":
    unittest.main()
