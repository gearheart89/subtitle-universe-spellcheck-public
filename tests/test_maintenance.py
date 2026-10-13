import io
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from subtitle_cleanup import DEFAULT_OPTIONS, SubtitleCleanupTool


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


class UserDictionaryMutationTests(unittest.TestCase):
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
