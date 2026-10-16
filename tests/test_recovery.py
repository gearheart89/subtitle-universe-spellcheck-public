import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.subtitle_cleanup import DEFAULT_OPTIONS, DictionaryContext, SubtitleCleanupTool


def make_tool() -> SubtitleCleanupTool:
    tool = SubtitleCleanupTool.__new__(SubtitleCleanupTool)
    tool.options = dict(DEFAULT_OPTIONS)
    tool.undo_stack = []
    tool.current_session_ignores = set()
    tool.current_session_substitutions = {}
    tool.block_ignores = set()
    tool.dict_dir = Path("C:/Example/dictionaries")
    tool.base_dir = tool.dict_dir / "base"
    tool.user_dir = tool.dict_dir / "user"
    tool.universe_dir = tool.dict_dir / "universes"
    tool.options_path = tool.dict_dir / "options.ini"
    tool.session_state_path = tool.dict_dir / "session_state.json"
    tool.session_log_path = tool.dict_dir / "session_log.jsonl"
    tool.log_event = Mock()
    return tool


def saved_state(target: Path) -> dict:
    return {
        "session_active": True,
        "scan_completed": False,
        "target_root": str(target),
        "base_language": "british",
        "universe": "Stargate",
        "mode": "spellcheck_with_universe",
        "recursive": False,
        "options_snapshot": {
            **DEFAULT_OPTIONS,
            "prefer_sentence_ending_line_breaks_when_reasonably_balanced": False,
            "create_backup_subtitles_zip_before_editing": True,
        },
        "current_file": "second.srt",
        "current_subtitle_index": 7,
        "current_word": "Goauld",
        "completed_files": ["first.srt"],
        "session_ignore_words": ["zelenka"],
        "session_substitutions": {"goauld": "Goa'uld"},
        "undo_stack": [
            {
                "type": "block_ignore",
                "file": "second.srt",
                "subtitle_index": 7,
                "word": "Zelenka",
            }
        ],
        "started_at": "2026-09-26T10:00:00",
    }


class RecoveryConfigurationTests(unittest.TestCase):
    def test_resume_restores_context_progress_options_choices_and_undo(self):
        tool = make_tool()
        state = saved_state(Path("C:/Shows/Stargate"))

        recovered = tool.configure_recovered_session(state, "resume")

        self.assertEqual(recovered["target"], Path("C:/Shows/Stargate"))
        self.assertEqual(recovered["language"], "british")
        self.assertEqual(recovered["universe"], "Stargate")
        self.assertEqual(recovered["start_file"], "second.srt")
        self.assertEqual(recovered["start_index"], 7)
        self.assertEqual(tool.current_session_ignores, {"zelenka"})
        self.assertEqual(tool.current_session_substitutions, {"goauld": "Goa'uld"})
        self.assertEqual(len(tool.undo_stack), 1)
        self.assertIn(("second.srt", 7, "zelenka"), tool.block_ignores)
        self.assertFalse(tool.options["scan_folders_recursively"])
        self.assertFalse(tool.options["prefer_sentence_ending_line_breaks_when_reasonably_balanced"])
        self.assertTrue(tool.options["create_backup_subtitles_zip_before_editing"])

    def test_fresh_keep_reuses_saved_context_and_choices_but_resets_progress(self):
        tool = make_tool()
        recovered = tool.configure_recovered_session(
            saved_state(Path("C:/Shows/Stargate")), "fresh_keep"
        )

        self.assertEqual(recovered["language"], "british")
        self.assertEqual(recovered["universe"], "Stargate")
        self.assertIsNone(recovered["start_file"])
        self.assertEqual(recovered["start_index"], 0)
        self.assertEqual(tool.current_session_ignores, {"zelenka"})
        self.assertEqual(tool.current_session_substitutions, {"goauld": "Goa'uld"})
        self.assertEqual(tool.undo_stack, [])
        self.assertEqual(tool.block_ignores, set())

    def test_fresh_discard_reuses_saved_context_and_discards_choices(self):
        tool = make_tool()
        recovered = tool.configure_recovered_session(
            saved_state(Path("C:/Shows/Stargate")), "fresh_discard"
        )

        self.assertEqual(recovered["target"], Path("C:/Shows/Stargate"))
        self.assertEqual(recovered["mode"], "spellcheck_with_universe")
        self.assertEqual(tool.current_session_ignores, set())
        self.assertEqual(tool.current_session_substitutions, {})
        self.assertEqual(tool.undo_stack, [])

    def test_blank_saved_target_is_rejected(self):
        tool = make_tool()
        state = saved_state(Path("C:/Shows/Stargate"))
        state["target_root"] = "   "
        self.assertIsNone(tool.configure_recovered_session(state, "resume"))

    def test_invalid_saved_option_types_do_not_override_current_options(self):
        tool = make_tool()
        state = saved_state(Path("C:/Shows/Stargate"))
        state["options_snapshot"] = {
            "adjust_subtitle_line_count": "false",
            "preferred_max_chars_per_line": -1,
        }
        state["recursive"] = "false"

        tool.apply_saved_options(state)

        self.assertTrue(tool.options["adjust_subtitle_line_count"])
        self.assertEqual(tool.options["preferred_max_chars_per_line"], 40)
        self.assertTrue(tool.options["scan_folders_recursively"])


class ManifestRecoveryTests(unittest.TestCase):
    def test_manifest_reports_missing_new_and_changed_files(self):
        tool = make_tool()
        saved = [
            {"path": "missing.srt", "size_bytes": 10, "modified_time_ns": 1},
            {"path": "changed.srt", "size_bytes": 20, "modified_time_ns": 2},
            {"path": "same.srt", "size_bytes": 30, "modified_time_ns": 3},
        ]
        current = [
            {"path": "changed.srt", "size_bytes": 21, "modified_time_ns": 2},
            {"path": "same.srt", "size_bytes": 30, "modified_time_ns": 3},
            {"path": "new.srt", "size_bytes": 40, "modified_time_ns": 4},
        ]

        self.assertEqual(
            tool.manifest_differences(saved, current),
            [
                "Missing file: missing.srt",
                "New file: new.srt",
                "Changed file: changed.srt",
            ],
        )

    def test_legacy_manifest_uses_second_resolution_timestamp(self):
        tool = make_tool()
        saved = [{"path": "same.srt", "size_bytes": 30, "modified_time": "2026-09-26T10:00:00"}]
        current = [{
            "path": "same.srt",
            "size_bytes": 30,
            "modified_time": "2026-09-26T10:00:00",
            "modified_time_ns": 123,
        }]
        self.assertEqual(tool.manifest_differences(saved, current), [])

    def test_refresh_manifest_entry_records_tool_owned_write(self):
        tool = make_tool()
        target = Path("C:/Shows")
        subtitle = target / "episode.srt"
        manifest = [{"path": "episode.srt", "size_bytes": 3, "modified_time_ns": 1}]
        refreshed = {"path": "episode.srt", "size_bytes": 11, "modified_time_ns": 2}
        tool.build_manifest = Mock(return_value=[refreshed])

        tool.refresh_manifest_entry(manifest, target, subtitle)

        self.assertEqual(manifest, [refreshed])
        self.assertEqual(tool.manifest_differences(manifest, [refreshed]), [])

    def test_manifest_drift_prompt_reprompts_then_allows_safe_restart(self):
        tool = make_tool()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("builtins.input", side_effect=["bad", "1"]),
            patch("sys.stdout", io.StringIO()) as output,
        ):
            choice = tool.prompt_manifest_drift(["Changed file: episode.srt"])

        self.assertEqual(choice, "fresh_keep")
        self.assertIn("exact resume is unsafe", output.getvalue())


class RecoveryFlowTests(unittest.TestCase):
    def test_exact_resume_skips_completed_file_and_starts_at_saved_cue(self):
        tool = make_tool()
        target = Path("C:/Shows/Stargate")
        first = target / "first.srt"
        second = target / "second.srt"
        manifest = [
            {"path": "first.srt", "size_bytes": 5, "modified_time_ns": 1},
            {"path": "second.srt", "size_bytes": 6, "modified_time_ns": 2},
        ]
        state = saved_state(target)
        state["file_manifest"] = manifest
        tool.load_session_state = Mock(return_value=state)
        tool.prompt_aborted_session = Mock(return_value="resume")
        tool.find_srt_files = Mock(return_value=[first, second])
        tool.build_manifest = Mock(return_value=manifest)
        tool.refresh_manifest_entry = Mock()
        tool.create_backup_if_needed = Mock(return_value=True)
        tool.load_dictionary_context = Mock(
            return_value=DictionaryContext(language="british", universe="Stargate")
        )
        tool.spellcheck_file = Mock(return_value=(False, False, 8))
        tool.save_session_state = Mock()

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "is_dir", return_value=True),
            patch("subtitle_cleanup.pause"),
            patch("sys.stdout", io.StringIO()),
        ):
            tool.run_spellcheck(use_universe=False)

        tool.spellcheck_file.assert_called_once()
        args = tool.spellcheck_file.call_args.args
        self.assertEqual(args[0].name, "second.srt")
        self.assertEqual(args[3], 7)
        self.assertEqual(tool.options, DEFAULT_OPTIONS)

    def test_file_boundary_saves_latest_session_choices(self):
        tool = make_tool()
        target = Path("C:/Shows/Stargate")
        first = target / "first.srt"
        second = target / "second.srt"
        manifest = [
            {"path": "first.srt", "size_bytes": 5, "modified_time_ns": 1},
            {"path": "second.srt", "size_bytes": 6, "modified_time_ns": 2},
        ]
        state = saved_state(target)
        state["file_manifest"] = manifest
        state["completed_files"] = []
        tool.load_session_state = Mock(return_value=state)
        tool.prompt_aborted_session = Mock(return_value="fresh_discard")
        tool.find_srt_files = Mock(return_value=[first, second])
        tool.build_manifest = Mock(return_value=manifest)
        tool.refresh_manifest_entry = Mock()
        tool.create_backup_if_needed = Mock(return_value=True)
        tool.load_dictionary_context = Mock(return_value=DictionaryContext(language="british"))
        tool.save_session_state = Mock()
        boundary_state = {}

        def scan_file(
            path,
            target_root,
            context,
            start_index,
            session_state,
            file_number=1,
            total_files=1,
        ):
            if path == first:
                tool.current_session_ignores.add("newchoice")
                tool.current_session_substitutions["wrong"] = "right"
                tool.undo_stack.append({"type": "session_ignore", "word": "newchoice"})
            else:
                boundary_state.update({
                    "ignores": list(session_state["session_ignore_words"]),
                    "substitutions": dict(session_state["session_substitutions"]),
                    "undo": list(session_state["undo_stack"]),
                })
            return False, False, 1

        tool.spellcheck_file = Mock(side_effect=scan_file)
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "is_dir", return_value=True),
            patch("subtitle_cleanup.pause"),
            patch("sys.stdout", io.StringIO()),
        ):
            tool.run_spellcheck(use_universe=False)

        self.assertEqual(boundary_state["ignores"], ["newchoice"])
        self.assertEqual(boundary_state["substitutions"], {"wrong": "right"})
        self.assertEqual(boundary_state["undo"], [{"type": "session_ignore", "word": "newchoice"}])

    def test_drift_can_return_without_scanning(self):
        tool = make_tool()
        target = Path("C:/Shows/Stargate")
        subtitle = target / "episode.srt"
        state = saved_state(target)
        state["file_manifest"] = [
            {"path": "episode.srt", "size_bytes": 1, "modified_time_ns": 1}
        ]
        tool.load_session_state = Mock(return_value=state)
        tool.prompt_aborted_session = Mock(return_value="resume")
        tool.prompt_manifest_drift = Mock(return_value="back")
        tool.find_srt_files = Mock(return_value=[subtitle])
        tool.build_manifest = Mock(return_value=[
            {"path": "episode.srt", "size_bytes": 7, "modified_time_ns": 2}
        ])
        tool.spellcheck_file = Mock()

        with patch.object(Path, "exists", return_value=True), patch.object(Path, "is_dir", return_value=True):
            tool.run_spellcheck(use_universe=True)

        tool.prompt_manifest_drift.assert_called_once()
        tool.spellcheck_file.assert_not_called()


class StateFileTests(unittest.TestCase):
    def test_dictionary_and_option_saves_use_atomic_text_replacement(self):
        tool = make_tool()
        word_path = Path("C:/Example/dictionaries/user/american_words.txt")
        substitution_path = Path(
            "C:/Example/dictionaries/user/american_substitutions.tsv"
        )
        with (
            patch.object(Path, "mkdir"),
            patch.object(tool, "atomic_write_text") as atomic_write_text,
        ):
            tool.save_word_list(word_path, ["Beta", "Alpha"])
            tool.save_substitutions(substitution_path, {"teh": "the"})
            tool.save_options()

        self.assertEqual(
            atomic_write_text.call_args_list[0].args,
            (word_path, "Alpha\nBeta\n"),
        )
        self.assertEqual(
            atomic_write_text.call_args_list[1].args,
            (substitution_path, "teh\tthe\n"),
        )
        self.assertEqual(atomic_write_text.call_args_list[2].args[0], tool.options_path)
        self.assertIn("[options]", atomic_write_text.call_args_list[2].args[1])

    def test_missing_and_malformed_state_are_treated_as_no_session(self):
        tool = make_tool()
        with patch.object(Path, "exists", return_value=False):
            self.assertEqual(tool.load_session_state(), {})
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value="{not json"),
        ):
            self.assertEqual(tool.load_session_state(), {})
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value="[]"),
        ):
            self.assertEqual(tool.load_session_state(), {})

    def test_state_save_is_atomic_and_leaves_valid_json(self):
        tool = make_tool()
        state = {"session_active": True}
        with (
            patch.object(Path, "mkdir") as mkdir,
            patch.object(tool, "atomic_write_text") as atomic_write_text,
        ):
            tool.save_session_state(state)

        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        payload = json.loads(atomic_write_text.call_args.args[1])
        self.assertTrue(payload["session_active"])
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            atomic_write_text.call_args.args[0], tool.session_state_path
        )

    def test_atomic_writer_retries_a_transient_windows_replace_lock(self):
        tool = make_tool()
        path = Path(__file__).with_name("_atomic_retry_state.json")
        try:
            path.unlink(missing_ok=True)
            real_replace = os.replace
            attempts = 0

            def transient_lock(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError("temporarily locked")
                real_replace(source, destination)

            with (
                patch("subtitle_cleanup.os.replace", side_effect=transient_lock),
                patch("subtitle_cleanup.time.sleep") as sleep,
            ):
                tool.atomic_write_text(path, '{"ok": true}')

            self.assertEqual(attempts, 2)
            sleep.assert_called_once_with(0.05)
            self.assertEqual(path.read_text(encoding="utf-8"), '{"ok": true}')
        finally:
            path.unlink(missing_ok=True)


class RecoveryPromptTests(unittest.TestCase):
    def test_flush_log_explains_that_recovery_state_is_unchanged(self):
        tool = make_tool()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value=""),
            patch("sys.stdout", io.StringIO()) as output,
        ):
            tool.flush_session_log()

        self.assertIn(
            "does not clear or abandon an interrupted spellcheck session",
            output.getvalue(),
        )

    def test_aborted_session_prompt_reprompts_after_invalid_input(self):
        tool = make_tool()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("builtins.input", side_effect=["x", "2"]),
            patch("sys.stdout", io.StringIO()) as output,
        ):
            choice = tool.prompt_aborted_session()

        self.assertEqual(choice, "fresh_keep")
        self.assertIn("Please choose 1, 2, 3, 4, or 5.", output.getvalue())

    def test_recovery_prompt_can_abandon_saved_target_and_choose_another(self):
        tool = make_tool()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="4"),
            patch("sys.stdout", io.StringIO()) as output,
        ):
            choice = tool.prompt_aborted_session()

        self.assertEqual(choice, "new_scan")
        self.assertIn("Restart the same folder", output.getvalue())
        self.assertIn("start the normal new scan", output.getvalue())

    def test_abandon_recovery_marks_session_inactive_and_discards_transient_choices(self):
        tool = make_tool()
        tool.save_session_state = Mock()
        state = saved_state(Path("C:/Shows/Stargate"))

        tool.abandon_recovered_session(state)

        saved = tool.save_session_state.call_args.args[0]
        self.assertFalse(saved["session_active"])
        self.assertFalse(saved["scan_completed"])
        self.assertTrue(saved["session_abandoned"])
        self.assertIsNone(saved["current_file"])
        self.assertIsNone(saved["current_word"])
        self.assertEqual(saved["session_ignore_words"], [])
        self.assertEqual(saved["session_substitutions"], {})
        self.assertEqual(saved["undo_stack"], [])


class RecoveryNewTargetFlowTests(unittest.TestCase):
    def test_new_scan_recovery_choice_uses_normal_scan_and_countdown_workflow(self):
        tool = make_tool()
        tool.options["capitalization_mode"] = "subtitle"
        target = Path("C:/Shows/New Target")
        subtitle = target / "episode.srt"
        tool.load_session_state = Mock(
            return_value=saved_state(Path("C:/Shows/Old Target"))
        )
        tool.prompt_aborted_session = Mock(return_value="new_scan")
        tool.select_target_folder = Mock(return_value=target)
        tool.choose_language = Mock(return_value="american")
        tool.choose_spellcheck_universe = Mock(return_value=(True, None))
        tool.find_srt_files = Mock(return_value=[subtitle])
        tool.build_manifest = Mock(return_value=[])
        tool.refresh_manifest_entry = Mock()
        tool.create_backup_if_needed = Mock(return_value=True)
        tool.load_dictionary_context = Mock(
            return_value=DictionaryContext(language="american")
        )
        tool.spellcheck_file = Mock(return_value=(False, False, 1))
        tool.save_session_state = Mock()

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "is_dir", return_value=True),
            patch("subtitle_cleanup.pause"),
            patch("sys.stdout", io.StringIO()),
        ):
            tool.run_spellcheck(use_universe=True)

        tool.select_target_folder.assert_called_once_with(
            "Spellcheck with optional universe dictionary and formatting correction"
        )
        self.assertEqual(tool.spellcheck_file.call_args.args[1], target)


if __name__ == "__main__":
    unittest.main()
