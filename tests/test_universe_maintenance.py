import io
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from app.subtitle_cleanup import DEFAULT_OPTIONS, SubtitleCleanupTool


def make_tool() -> SubtitleCleanupTool:
    tool = SubtitleCleanupTool.__new__(SubtitleCleanupTool)
    tool.options = dict(DEFAULT_OPTIONS)
    tool.dict_dir = Path("C:/Example/dictionaries")
    tool.base_dir = tool.dict_dir / "base"
    tool.user_dir = tool.dict_dir / "user"
    tool.universe_dir = tool.dict_dir / "universes"
    tool.options_path = tool.dict_dir / "options.ini"
    tool.session_state_path = tool.dict_dir / "session_state.json"
    tool.session_log_path = tool.dict_dir / "session_log.jsonl"
    tool.log_event = Mock()
    return tool


class UniverseNameTests(unittest.TestCase):
    def test_valid_universe_names_are_preserved(self):
        tool = make_tool()
        self.assertIsNone(tool.universe_name_error("Stargate SG-1"))
        self.assertIsNone(tool.universe_name_error("Doctor Who (1963)"))
        self.assertIsNone(tool.universe_name_error("Marvel's Agents"))

    def test_path_and_windows_device_names_are_rejected(self):
        tool = make_tool()
        invalid = [
            ".",
            "..",
            "../Escape",
            "Star/Gate",
            "Star\\Gate",
            "C:Stargate",
            "Bad<Name",
            "Trailing.",
            "Trailing ",
            "CON",
            "con.txt",
            "LPT9",
            "line\nbreak",
            ".__universe_copy_1234",
        ]
        for name in invalid:
            with self.subTest(name=name):
                self.assertIsNotNone(tool.universe_name_error(name))

    def test_case_insensitive_existing_name_detection(self):
        tool = make_tool()
        tool.list_universes = Mock(return_value=["Stargate", "Doctor Who"])
        self.assertTrue(tool.universe_name_exists("STARGATE"))
        self.assertFalse(tool.universe_name_exists("Star Trek"))


class UniverseSpellcheckSelectionTests(unittest.TestCase):
    def test_editing_picker_separates_universes_from_controls(self):
        tool = make_tool()
        tool.list_universes = Mock(return_value=["Stargate SG-1"])
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", output),
        ):
            tool.choose_universe()

        self.assertIn("1. Stargate SG-1\n\n\n0. Go back", output.getvalue())

    def test_spellcheck_picker_separates_universes_from_controls(self):
        tool = make_tool()
        tool.list_universes = Mock(return_value=["Stargate SG-1"])
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", output),
        ):
            tool.choose_spellcheck_universe()

        self.assertIn(
            "1. Stargate SG-1\n\n\nC. Create a new universe dictionary",
            output.getvalue(),
        )

    def test_editing_picker_without_universes_returns_after_message(self):
        tool = make_tool()
        tool.list_universes = Mock(return_value=[])

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause") as pause_mock,
            patch("builtins.input") as input_mock,
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.choose_universe()

        self.assertIsNone(result)
        pause_mock.assert_called_once_with()
        input_mock.assert_not_called()

    def test_editing_universe_picker_is_sorted_and_paginated(self):
        tool = make_tool()
        tool.list_universes = Mock(
            return_value=[f"Universe {number:02d}" for number in range(12, 0, -1)]
        )

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", side_effect=["33", "2"]),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.choose_universe()

        self.assertEqual(result, "Universe 12")

    def test_editing_universe_picker_supports_previous_page(self):
        tool = make_tool()
        tool.list_universes = Mock(
            return_value=[f"Universe {number:02d}" for number in range(1, 13)]
        )

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", side_effect=["33", "11", "1"]),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.choose_universe()

        self.assertEqual(result, "Universe 01")

    def test_spellcheck_can_continue_without_universe(self):
        tool = make_tool()
        tool.list_universes = Mock(return_value=["Stargate SG-1"])

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="n"),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.choose_spellcheck_universe()

        self.assertEqual(result, (True, None))

    def test_spellcheck_universe_picker_is_sorted_and_paginated(self):
        tool = make_tool()
        tool.list_universes = Mock(
            return_value=[f"Universe {number:02d}" for number in range(12, 0, -1)]
        )

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", side_effect=["33", "2"]),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.choose_spellcheck_universe()

        self.assertEqual(result, (True, "Universe 12"))

    def test_spellcheck_can_create_then_select_universe(self):
        tool = make_tool()
        tool.list_universes = Mock(
            side_effect=[["Stargate SG-1"], ["New Universe", "Stargate SG-1"]]
        )
        tool.create_universe_dictionary = Mock(return_value=True)

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", side_effect=["c", "1"]),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.choose_spellcheck_universe()

        self.assertEqual(result, (True, "New Universe"))
        tool.create_universe_dictionary.assert_called_once_with()

    def test_spellcheck_universe_selection_can_go_back(self):
        tool = make_tool()
        tool.list_universes = Mock(return_value=[])

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.choose_spellcheck_universe()

        self.assertEqual(result, (False, None))


class UniverseLifecycleTests(unittest.TestCase):
    def test_named_lifecycle_operations_support_gui_without_cli_prompts(self):
        tool = make_tool()
        tool.universe_name_exists = Mock(return_value=False)
        tool.create_universe_files = Mock()
        tool.copy_universe_files = Mock()
        tool.ensure_universe_files = Mock()
        tool.update_active_session_universe = Mock()
        tool.active_session_uses_universe = Mock(return_value=False)

        with patch.object(Path, "rename", autospec=True) as rename:
            self.assertTrue(tool.create_universe_named("Stargate"))
            self.assertTrue(
                tool.duplicate_universe_named("Stargate", "Stargate Atlantis")
            )
            self.assertTrue(tool.rename_universe_named("Stargate", "Stargate SG-1"))

        tool.create_universe_files.assert_called_once_with(
            tool.universe_dir / "Stargate"
        )
        tool.copy_universe_files.assert_called_once_with(
            tool.universe_dir / "Stargate",
            tool.universe_dir / "Stargate Atlantis",
        )
        rename.assert_called_once_with(
            tool.universe_dir / "Stargate", tool.universe_dir / "Stargate SG-1"
        )

    def test_named_lifecycle_rejects_invalid_or_duplicate_destination(self):
        tool = make_tool()
        tool.universe_name_exists = Mock(return_value=True)
        tool.create_universe_files = Mock()
        tool.copy_universe_files = Mock()

        with self.assertRaisesRegex(ValueError, "cannot contain"):
            tool.create_universe_named("Bad/Name")
        with self.assertRaisesRegex(ValueError, "already exists"):
            tool.create_universe_named("Stargate")
        with self.assertRaisesRegex(ValueError, "already exists"):
            tool.duplicate_universe_named("Stargate", "STARGATE")

        tool.create_universe_files.assert_not_called()
        tool.copy_universe_files.assert_not_called()

    def test_named_delete_honors_recovery_guard_and_exact_target(self):
        tool = make_tool()
        tool.active_session_uses_universe = Mock(return_value=True)
        with patch("subtitle_cleanup.shutil.rmtree") as rmtree:
            with self.assertRaisesRegex(ValueError, "cannot contain"):
                tool.delete_universe_named("../Outside")
            with self.assertRaisesRegex(RuntimeError, "interrupted spellcheck"):
                tool.delete_universe_named("Stargate")
            rmtree.assert_not_called()

            tool.active_session_uses_universe.return_value = False
            self.assertTrue(tool.delete_universe_named("Stargate"))

        rmtree.assert_called_once_with(tool.universe_dir / "Stargate")
        tool.log_event.assert_called_once_with(
            {"type": "universe_delete", "universe": "Stargate"}
        )

    def test_required_layout_contains_exact_runtime_files(self):
        tool = make_tool()
        root = tool.universe_dir / "Stargate"
        with (
            patch.object(Path, "mkdir", autospec=True) as mkdir,
            patch.object(Path, "write_text", autospec=True) as write_text,
        ):
            tool.create_universe_files(root)

        mkdir.assert_called_once_with(root, parents=True, exist_ok=False)
        self.assertEqual(
            write_text.call_args_list,
            [
                call(root / "words.txt", "", encoding="utf-8"),
                call(root / "names.txt", "", encoding="utf-8"),
                call(root / "acronyms.txt", "", encoding="utf-8"),
                call(root / "substitutions.tsv", "", encoding="utf-8"),
            ],
        )

    def test_create_initializes_all_required_files_and_logs(self):
        tool = make_tool()
        tool.universe_name_exists = Mock(return_value=False)
        tool.create_universe_files = Mock()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("builtins.input", return_value="Stargate"),
            patch("sys.stdout", io.StringIO()),
        ):
            created = tool.create_universe_dictionary()

        self.assertTrue(created)
        tool.create_universe_files.assert_called_once_with(tool.universe_dir / "Stargate")
        tool.log_event.assert_called_once_with({"type": "universe_create", "universe": "Stargate"})

    def test_create_rejects_case_insensitive_duplicate(self):
        tool = make_tool()
        tool.universe_name_exists = Mock(return_value=True)
        tool.create_universe_files = Mock()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("builtins.input", return_value="STARGATE"),
        ):
            created = tool.create_universe_dictionary()

        self.assertFalse(created)
        tool.create_universe_files.assert_not_called()

    def test_duplicate_repairs_required_file_layout(self):
        tool = make_tool()
        tool.choose_universe = Mock(return_value="Stargate")
        tool.universe_name_exists = Mock(return_value=False)
        tool.copy_universe_files = Mock()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("builtins.input", return_value="Stargate Atlantis"),
        ):
            duplicated = tool.duplicate_universe_dictionary()

        self.assertTrue(duplicated)
        tool.copy_universe_files.assert_called_once_with(
            tool.universe_dir / "Stargate",
            tool.universe_dir / "Stargate Atlantis",
        )
        tool.log_event.assert_called_once_with({
            "type": "universe_duplicate",
            "from": "Stargate",
            "to": "Stargate Atlantis",
        })

    def test_copy_uses_staging_and_never_cleans_destination_on_failure(self):
        tool = make_tool()
        source = tool.universe_dir / "Stargate"
        destination = tool.universe_dir / "Atlantis"
        staging = tool.universe_dir / ".__universe_copy_1234"
        tool.ensure_universe_files = Mock()
        with (
            patch("subtitle_cleanup.os.getpid", return_value=1234),
            patch("subtitle_cleanup.shutil.copytree") as copytree,
            patch.object(Path, "exists", return_value=False),
            patch.object(Path, "rename", autospec=True) as rename,
        ):
            tool.copy_universe_files(source, destination)

        copytree.assert_called_once_with(source, staging)
        tool.ensure_universe_files.assert_called_once_with(staging)
        rename.assert_called_once_with(staging, destination)

    def test_rename_updates_interrupted_session_reference(self):
        tool = make_tool()
        source_path = tool.universe_dir / "Stargate"
        tool.choose_universe = Mock(return_value="Stargate")
        tool.universe_name_exists = Mock(return_value=False)
        tool.ensure_universe_files = Mock()
        tool.update_active_session_universe = Mock()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("builtins.input", return_value="Stargate SG-1"),
            patch.object(Path, "rename") as rename,
        ):
            renamed = tool.rename_universe_dictionary()

        self.assertTrue(renamed)
        rename.assert_called_once_with(tool.universe_dir / "Stargate SG-1")
        tool.ensure_universe_files.assert_called_once_with(tool.universe_dir / "Stargate SG-1")
        tool.update_active_session_universe.assert_called_once_with("Stargate", "Stargate SG-1")

    def test_case_only_rename_uses_safe_intermediate_path(self):
        tool = make_tool()
        source = tool.universe_dir / "Stargate"
        destination = tool.universe_dir / "STARGATE"
        temporary = tool.universe_dir / ".__universe_rename_1234"
        tool.choose_universe = Mock(return_value="Stargate")
        tool.universe_name_exists = Mock(return_value=False)
        tool.ensure_universe_files = Mock()
        tool.update_active_session_universe = Mock()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("subtitle_cleanup.os.getpid", return_value=1234),
            patch("builtins.input", return_value="STARGATE"),
            patch.object(Path, "exists", return_value=False),
            patch.object(Path, "rename") as rename,
        ):
            renamed = tool.rename_universe_dictionary()

        self.assertTrue(renamed)
        self.assertEqual(rename.call_args_list, [call(temporary), call(destination)])

    def test_delete_is_blocked_for_active_interrupted_session(self):
        tool = make_tool()
        tool.choose_universe = Mock(return_value="Stargate")
        tool.active_session_uses_universe = Mock(return_value=True)
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("subtitle_cleanup.shutil.rmtree") as rmtree,
            patch("builtins.input") as user_input,
        ):
            deleted = tool.delete_universe_dictionary()

        self.assertFalse(deleted)
        user_input.assert_not_called()
        rmtree.assert_not_called()

    def test_delete_requires_exact_typed_confirmation(self):
        tool = make_tool()
        tool.choose_universe = Mock(return_value="Stargate")
        tool.active_session_uses_universe = Mock(return_value=False)
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("subtitle_cleanup.shutil.rmtree") as rmtree,
            patch("builtins.input", return_value="delete"),
        ):
            deleted = tool.delete_universe_dictionary()

        self.assertFalse(deleted)
        rmtree.assert_not_called()

    def test_confirmed_delete_removes_only_selected_universe(self):
        tool = make_tool()
        tool.choose_universe = Mock(return_value="Stargate")
        tool.active_session_uses_universe = Mock(return_value=False)
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.pause"),
            patch("subtitle_cleanup.shutil.rmtree") as rmtree,
            patch("builtins.input", return_value="DELETE"),
        ):
            deleted = tool.delete_universe_dictionary()

        self.assertTrue(deleted)
        rmtree.assert_called_once_with(tool.universe_dir / "Stargate")
        tool.log_event.assert_called_once_with({"type": "universe_delete", "universe": "Stargate"})


class UniverseSessionTests(unittest.TestCase):
    def test_active_session_reference_is_updated_after_rename(self):
        tool = make_tool()
        state = {
            "session_active": True,
            "scan_completed": False,
            "universe": "Stargate",
        }
        tool.load_session_state = Mock(return_value=state)
        tool.save_session_state = Mock()

        updated = tool.update_active_session_universe("Stargate", "Stargate SG-1")

        self.assertTrue(updated)
        self.assertEqual(state["universe"], "Stargate SG-1")
        tool.save_session_state.assert_called_once_with(state)

    def test_completed_session_does_not_block_delete(self):
        tool = make_tool()
        tool.load_session_state = Mock(return_value={
            "session_active": False,
            "scan_completed": True,
            "universe": "Stargate",
        })
        self.assertFalse(tool.active_session_uses_universe("Stargate"))


class UniverseStatisticsAndDispatchTests(unittest.TestCase):
    def test_statistics_count_unique_valid_dictionary_entries(self):
        tool = make_tool()
        tool.load_word_set = Mock(return_value={"alpha", "beta"})
        tool.load_name_map = Mock(return_value={"one": "One"})
        tool.load_acronym_set = Mock(return_value={"MALP", "GDO"})
        tool.load_substitutions = Mock(return_value={"teh": "the", "recieve": "receive"})

        stats = tool.universe_statistics("Stargate")

        self.assertEqual(
            stats,
            {"words": 2, "names": 1, "acronyms": 2, "substitutions": 2},
        )

    def test_direct_maintenance_dispatches_to_universe_files(self):
        tool = make_tool()
        tool.choose_universe = Mock(return_value="Stargate")
        tool.ensure_universe_files = Mock()
        tool.maintain_word_or_name_file = Mock()
        tool.maintain_substitution_file = Mock()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", side_effect=["1", "2", "3", "4", "0"]),
        ):
            tool.maintain_universe_dictionary()

        root = tool.universe_dir / "Stargate"
        self.assertEqual(tool.maintain_word_or_name_file.call_args_list, [
            call(root / "words.txt", "universe", "words", "Stargate"),
            call(root / "names.txt", "universe", "names", "Stargate"),
            call(root / "acronyms.txt", "universe", "acronyms", "Stargate"),
        ])
        tool.maintain_substitution_file.assert_called_once_with(
            root / "substitutions.tsv", "universe", "Stargate"
        )


if __name__ == "__main__":
    unittest.main()
