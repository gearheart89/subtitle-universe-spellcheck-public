import io
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from app.subtitle_cleanup import DEFAULT_OPTIONS, DictionaryContext, SubtitleCleanupTool


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
    tool.undo_stack = []
    return tool


class DelimitedEntryTests(unittest.TestCase):
    def test_short_comma_delimited_addition_is_split_and_deduplicated(self):
        tool = make_tool()
        with (
            patch("builtins.input", side_effect=["alpha,beta,ALPHA", "2", ""]),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_entries_for_addition("words")

        self.assertEqual(result, (["alpha", "beta"], []))

    def test_long_input_can_still_be_one_entry(self):
        tool = make_tool()
        with (
            patch("builtins.input", side_effect=["a-very-long-single-entry", "1"]),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_entries_for_addition("words")

        self.assertEqual(result, (["a-very-long-single-entry"], []))

    def test_custom_delimiter_is_supported_for_removal(self):
        tool = make_tool()
        with (
            patch("builtins.input", side_effect=["alpha / beta / gamma", "2", "/"]),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_entries_for_removal()

        self.assertEqual(result, ["alpha", "beta", "gamma"])

    def test_multiword_word_can_be_redirected_to_names(self):
        tool = make_tool()
        with (
            patch(
                "builtins.input",
                side_effect=["Jack O'Neill,SG-1", "2", "", "2"],
            ),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_entries_for_addition("words")

        self.assertEqual(result, (["SG-1"], ["Jack O'Neill"]))

    def test_canceling_multiword_review_cancels_all_additions(self):
        tool = make_tool()
        with (
            patch("builtins.input", side_effect=["two words", "0"]),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_entries_for_addition("words")

        self.assertIsNone(result)


class AcronymStorageTests(unittest.TestCase):
    def test_runtime_layout_creates_user_acronym_files_for_both_languages(self):
        tool = make_tool()
        tool.save_options = Mock()
        written_paths = []
        with (
            patch.object(Path, "mkdir", new=lambda *_args, **_kwargs: None),
            patch.object(Path, "exists", new=lambda _path: False),
            patch.object(
                Path,
                "write_text",
                new=lambda path, *_args, **_kwargs: written_paths.append(path),
            ),
        ):
            tool.ensure_folder_structure()

        self.assertIn(tool.user_dir / "american_acronyms.txt", written_paths)
        self.assertIn(tool.user_dir / "british_acronyms.txt", written_paths)

    def test_acronym_validation_rejects_single_letters_and_punctuation(self):
        tool = make_tool()

        for value in ("A", "S.G.C.", "SG C", "SG-C"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tool.validate_acronym_entry(value)

        self.assertEqual(tool.validate_acronym_entry("SG1"), "SG1")

    def test_contextual_time_markers_cannot_be_added_as_acronyms(self):
        tool = make_tool()

        for value in ("AM", "am", "PM", "pm"):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "time expressions"
            ):
                tool.validate_acronym_entry(value)

    def test_acronym_conflict_reports_matching_active_word_layers(self):
        tool = make_tool()
        context = DictionaryContext(
            language="american",
            universe="Stargate",
            base_words={"us"},
            user_words={"us"},
            universe_words={"us"},
        )

        self.assertEqual(
            tool.acronym_word_conflicts("US", context),
            [
                "American English Base Dictionary",
                "American English User Dictionary",
                "Stargate Universe Dictionary",
            ],
        )

    def test_user_acronym_checks_every_universe_word_list(self):
        tool = make_tool()
        tool.load_dictionary_context = Mock(
            return_value=DictionaryContext(language="american")
        )
        tool.list_universes = Mock(return_value=["Alpha", "Beta"])
        tool.load_word_set = Mock(
            side_effect=lambda path: {"us"} if path.parent.name == "Beta" else set()
        )
        tool.load_name_map = Mock(return_value={})

        conflicts = tool.acronym_word_conflicts_for_location(
            "US", "user", language="american"
        )

        self.assertEqual(conflicts, ["Beta Universe Dictionary"])

    def test_universe_acronym_ignores_other_universe_word_lists(self):
        tool = make_tool()
        tool.load_dictionary_context = Mock(
            side_effect=lambda language: DictionaryContext(language=language)
        )
        tool.list_universes = Mock(return_value=["Selected", "Other"])
        tool.load_word_set = Mock(
            side_effect=lambda path: {"us"} if path.parent.name == "Other" else set()
        )
        tool.load_name_map = Mock(return_value={})

        conflicts = tool.acronym_word_conflicts_for_location(
            "US", "universe", universe="Selected"
        )

        self.assertEqual(conflicts, [])
        tool.list_universes.assert_not_called()

    def test_user_word_checks_every_universe_acronym_list(self):
        tool = make_tool()
        tool.load_dictionary_context = Mock(
            return_value=DictionaryContext(language="american")
        )
        tool.list_universes = Mock(return_value=["Alpha", "Beta"])
        tool.load_acronym_set = Mock(
            side_effect=lambda path: {"XYZ"} if path.parent.name == "Alpha" else set()
        )

        conflicts = tool.word_acronym_conflicts_for_location(
            "xyz", "user", language="american"
        )

        self.assertEqual(conflicts, ["Alpha Universe Dictionary"])

    def test_universe_word_ignores_other_universe_acronym_lists(self):
        tool = make_tool()
        tool.load_dictionary_context = Mock(
            side_effect=lambda language: DictionaryContext(language=language)
        )
        tool.list_universes = Mock(return_value=["Selected", "Other"])
        tool.load_acronym_set = Mock(
            side_effect=lambda path: {"XYZ"} if path.parent.name == "Other" else set()
        )

        conflicts = tool.word_acronym_conflicts_for_location(
            "xyz", "universe", universe="Selected"
        )

        self.assertEqual(conflicts, [])
        tool.list_universes.assert_not_called()

    def test_user_acronym_checks_every_universe_name_list(self):
        tool = make_tool()
        tool.load_dictionary_context = Mock(
            return_value=DictionaryContext(language="american")
        )
        tool.list_universes = Mock(return_value=["Alpha", "Beta"])
        tool.load_word_set = Mock(return_value=set())
        tool.load_name_map = Mock(
            side_effect=lambda path: {"qelari": "Qelari"}
            if path.parent.name == "Alpha"
            else {}
        )

        conflicts = tool.acronym_word_conflicts_for_location(
            "QELARI", "user", language="american"
        )

        self.assertEqual(conflicts, ["Alpha Universe Dictionary"])


class UserDictionaryMutationTests(unittest.TestCase):
    def test_acronym_addition_preserves_canonical_casing_and_metadata(self):
        tool = make_tool()
        path = tool.universe_dir / "Stargate SG-1" / "acronyms.txt"
        tool.save_word_list = Mock()

        added = tool.add_word_or_name_entries(
            path, "universe", "acronyms", "Stargate SG-1", ["MALP", "GDO"]
        )

        self.assertEqual(added, ["GDO", "MALP"])
        tool.save_word_list.assert_called_once_with(path, ["GDO", "MALP"])
        self.assertEqual(
            [call.args[0]["list"] for call in tool.log_event.call_args_list],
            ["acronyms", "acronyms"],
        )
    def test_gui_recent_move_uses_explicit_user_language_without_prompt(self):
        tool = make_tool()
        event = {
            "target": "universe",
            "universe": "Stargate",
            "list": "names",
            "word": "Harriman",
        }
        tool.add_word_to_file = Mock()
        tool.delete_dictionary_word = Mock()

        moved = tool.move_dictionary_word_to(
            event, "user", None, language="british"
        )

        self.assertTrue(moved)
        tool.add_word_to_file.assert_called_once_with(
            tool.user_dir / "british_names.txt", "Harriman"
        )
        tool.delete_dictionary_word.assert_called_once_with(event, log=False)
        tool.log_event.assert_called_once_with({
            "type": "dictionary_move",
            "word": "Harriman",
            "list": "names",
            "from_target": "universe",
            "from_universe": "Stargate",
            "from_base_language": None,
            "to_target": "user",
            "to_universe": None,
            "to_base_language": "british",
            "base_language": "british",
        })

    def test_gui_style_dictionary_edit_is_published_once_and_logged(self):
        tool = make_tool()
        path = tool.user_dir / "american_names.txt"
        tool.save_word_list = Mock()
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value="Harriman\nO'Neill\n"),
        ):
            changed = tool.replace_maintenance_dictionary_entry(
                path, "user", "names", None, "Harriman", "Walter Harriman"
            )

        self.assertTrue(changed)
        tool.save_word_list.assert_called_once_with(
            path, ["Walter Harriman", "O'Neill"]
        )
        tool.log_event.assert_called_once_with({
            "type": "dictionary_edit",
            "from": "Harriman",
            "to": "Walter Harriman",
            "target": "user",
            "universe": None,
            "list": "names",
            "base_language": "american",
        })

    def test_additions_are_case_insensitive_logged_and_report_actual_changes(self):
        tool = make_tool()
        path = tool.user_dir / "american_words.txt"
        tool.save_word_list = Mock()
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value="Alpha\n"),
        ):
            added = tool.add_word_or_name_entries(
                path,
                target="user",
                list_name="words",
                universe=None,
                entries=["alpha", "Beta", "BETA"],
            )

        self.assertEqual(added, ["Beta"])
        tool.save_word_list.assert_called_once_with(path, ["Alpha", "Beta"])
        tool.log_event.assert_called_once_with({
            "type": "dictionary_add",
            "target": "user",
            "universe": None,
            "base_language": "american",
            "list": "words",
            "word": "Beta",
        })

    def test_user_name_event_resolves_only_its_language_name_file(self):
        tool = make_tool()
        event = {
            "type": "dictionary_add",
            "target": "user",
            "base_language": "british",
            "list": "names",
            "word": "Lethbridge-Stewart",
        }

        self.assertEqual(
            tool.dictionary_paths_for_event(event),
            [tool.user_dir / "british_names.txt"],
        )

    def test_delete_user_name_does_not_touch_word_or_other_language_files(self):
        tool = make_tool()
        tool.remove_entries_from_file = Mock(return_value=[])
        event = {
            "target": "user",
            "base_language": "american",
            "list": "names",
            "word": "O'Neill",
        }

        tool.delete_dictionary_word(event)

        tool.remove_entries_from_file.assert_called_once_with(
            tool.user_dir / "american_names.txt", ["O'Neill"]
        )

    def test_modify_user_name_stays_in_same_language_and_list(self):
        tool = make_tool()
        tool.remove_entries_from_file = Mock(return_value=[])
        tool.add_word_to_file = Mock(return_value=True)
        event = {
            "target": "user",
            "base_language": "british",
            "list": "names",
            "word": "old name",
        }

        tool.modify_dictionary_word(event, "New Name")

        expected_path = tool.user_dir / "british_names.txt"
        tool.remove_entries_from_file.assert_called_once_with(expected_path, ["old name"])
        tool.add_word_to_file.assert_called_once_with(expected_path, "New Name")

    def test_interactive_user_add_events_include_language(self):
        tool = make_tool()
        tool.add_word_to_file = Mock(return_value=True)
        context = Mock(language="british", universe=None)
        context.user_words = set()

        tool.apply_dictionary_add("TARDIS", 4, context)

        event = tool.add_word_to_file.call_args.args[2]
        self.assertEqual(event["base_language"], "british")

    def test_canceling_move_to_user_keeps_source_entry(self):
        tool = make_tool()
        tool.choose_language = Mock(return_value=None)
        tool.delete_dictionary_word = Mock()
        tool.add_word_to_file = Mock()
        event = {
            "target": "universe",
            "universe": "Stargate",
            "list": "names",
            "word": "O'Neill",
        }

        moved = tool.move_dictionary_word(event, "user", None)

        self.assertFalse(moved)
        tool.delete_dictionary_word.assert_not_called()
        tool.add_word_to_file.assert_not_called()
        tool.log_event.assert_not_called()

    def test_move_to_same_universe_is_a_noop(self):
        tool = make_tool()
        tool.delete_dictionary_word = Mock()
        tool.add_word_to_file = Mock()
        event = {
            "target": "universe",
            "universe": "Stargate",
            "list": "names",
            "word": "O'Neill",
        }

        moved = tool.move_dictionary_word(event, "universe", "Stargate")

        self.assertFalse(moved)
        tool.delete_dictionary_word.assert_not_called()
        tool.add_word_to_file.assert_not_called()

    def test_successful_move_logs_source_and_destination_identity(self):
        tool = make_tool()
        tool.add_word_to_file = Mock(return_value=True)
        tool.delete_dictionary_word = Mock()
        event = {
            "target": "user",
            "base_language": "american",
            "list": "names",
            "word": "O'Neill",
        }

        moved = tool.move_dictionary_word(event, "universe", "Stargate")

        self.assertTrue(moved)
        tool.log_event.assert_called_once_with({
            "type": "dictionary_move",
            "word": "O'Neill",
            "list": "names",
            "from_target": "user",
            "from_universe": None,
            "from_base_language": "american",
            "to_target": "universe",
            "to_universe": "Stargate",
            "to_base_language": None,
        })


class UserSubstitutionMaintenanceTests(unittest.TestCase):
    def test_gui_recent_substitution_move_uses_explicit_destination(self):
        tool = make_tool()
        event = {
            "target": "user",
            "base_language": "american",
            "input": "goauld",
            "output": "Goa'uld",
        }
        tool.add_substitution_to_file = Mock()
        tool.delete_substitution = Mock()

        moved = tool.move_substitution_to(
            event, "universe", "Stargate"
        )

        self.assertTrue(moved)
        tool.add_substitution_to_file.assert_called_once_with(
            tool.universe_dir / "Stargate" / "substitutions.tsv",
            "goauld",
            "Goa'uld",
        )
        tool.delete_substitution.assert_called_once_with(event, log=False)
        tool.log_event.assert_called_once_with({
            "type": "substitution_move",
            "input": "goauld",
            "output": "Goa'uld",
            "from_target": "user",
            "from_universe": None,
            "from_base_language": "american",
            "to_target": "universe",
            "to_universe": "Stargate",
            "to_base_language": None,
        })

    def test_gui_style_substitution_edit_is_published_once_and_logged(self):
        tool = make_tool()
        path = tool.user_dir / "british_substitutions.tsv"
        tool.load_substitutions = Mock(return_value={"goauld": "Goauld"})
        tool.save_substitutions = Mock()

        changed = tool.replace_maintenance_substitution(
            path, "user", None, "goauld", "goauld", "Goa'uld"
        )

        self.assertTrue(changed)
        tool.save_substitutions.assert_called_once_with(
            path, {"goauld": "Goa'uld"}
        )
        tool.log_event.assert_called_once_with({
            "type": "substitution_edit",
            "from_input": "goauld",
            "from_output": "Goauld",
            "input": "goauld",
            "output": "Goa'uld",
            "target": "user",
            "universe": None,
            "base_language": "british",
        })

    def test_user_substitution_event_language_is_inferred_from_path(self):
        tool = make_tool()
        path = tool.user_dir / "british_substitutions.tsv"
        tool.load_substitutions = Mock(return_value={})
        tool.save_substitutions = Mock()

        added = tool.set_maintenance_substitution(
            path,
            target="user",
            universe=None,
            source="teh",
            output="the",
        )

        self.assertTrue(added)
        tool.log_event.assert_called_once_with({
            "type": "substitution_add",
            "target": "user",
            "universe": None,
            "base_language": "british",
            "input": "teh",
            "output": "the",
        })

    def test_delete_user_substitution_targets_only_logged_language(self):
        tool = make_tool()
        tool.load_substitutions = Mock(return_value={"teh": "the"})
        tool.save_substitutions = Mock()
        event = {
            "target": "user",
            "base_language": "british",
            "input": "teh",
            "output": "the",
        }

        tool.delete_substitution(event)

        expected_path = tool.user_dir / "british_substitutions.tsv"
        tool.load_substitutions.assert_called_once_with(expected_path)
        tool.save_substitutions.assert_called_once_with(expected_path, {})

    def test_canceling_substitution_move_to_user_keeps_source(self):
        tool = make_tool()
        tool.choose_language = Mock(return_value=None)
        tool.delete_substitution = Mock()
        tool.add_substitution_to_file = Mock()
        event = {
            "target": "universe",
            "universe": "Stargate",
            "input": "goauld",
            "output": "Goa'uld",
        }

        moved = tool.move_substitution(event, "user", None)

        self.assertFalse(moved)
        tool.delete_substitution.assert_not_called()
        tool.add_substitution_to_file.assert_not_called()

    def test_substitution_move_to_same_universe_is_a_noop(self):
        tool = make_tool()
        tool.delete_substitution = Mock()
        tool.add_substitution_to_file = Mock()
        event = {
            "target": "universe",
            "universe": "Stargate",
            "input": "goauld",
            "output": "Goa'uld",
        }

        moved = tool.move_substitution(event, "universe", "Stargate")

        self.assertFalse(moved)
        tool.delete_substitution.assert_not_called()
        tool.add_substitution_to_file.assert_not_called()

    def test_successful_substitution_move_logs_both_locations(self):
        tool = make_tool()
        tool.choose_language = Mock(return_value="british")
        tool.add_substitution_to_file = Mock()
        tool.delete_substitution = Mock()
        event = {
            "target": "universe",
            "universe": "Stargate",
            "input": "goauld",
            "output": "Goa'uld",
        }

        moved = tool.move_substitution(event, "user", None)

        self.assertTrue(moved)
        tool.log_event.assert_called_once_with({
            "type": "substitution_move",
            "input": "goauld",
            "output": "Goa'uld",
            "from_target": "universe",
            "from_universe": "Stargate",
            "from_base_language": None,
            "to_target": "user",
            "to_universe": None,
            "to_base_language": "british",
            "base_language": "british",
        })


if __name__ == "__main__":
    unittest.main()
