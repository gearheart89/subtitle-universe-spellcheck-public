import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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


class LogReadingTests(unittest.TestCase):
    def test_log_reader_skips_malformed_and_non_object_json(self):
        tool = make_tool()
        content = '\n'.join([
            '{"type":"dictionary_add","word":"alpha"}',
            '{not json',
            '["valid json", "but not an event"]',
            '42',
            '',
        ])
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=content),
        ):
            events = tool.read_log_events()

        self.assertEqual(events, [{"type": "dictionary_add", "word": "alpha"}])


class DictionaryEventReplayTests(unittest.TestCase):
    def test_edit_replaces_original_recent_entry(self):
        tool = make_tool()
        events = [
            {"type": "dictionary_add", "target": "user", "base_language": "american", "list": "words", "word": "Goauld"},
            {"type": "dictionary_edit", "target": "user", "base_language": "american", "list": "words", "from": "Goauld", "to": "Goa'uld"},
        ]

        entries = tool.reduce_recent_dictionary_events(events)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["word"], "Goa'uld")
        self.assertEqual(entries[0]["base_language"], "american")

    def test_move_relocates_entry_and_preserves_list_type(self):
        tool = make_tool()
        events = [
            {"type": "dictionary_add", "target": "user", "base_language": "american", "list": "names", "word": "O'Neill"},
            {
                "type": "dictionary_move",
                "word": "O'Neill",
                "list": "names",
                "from_target": "user",
                "from_base_language": "american",
                "to_target": "universe",
                "to_universe": "Stargate",
            },
        ]

        entries = tool.reduce_recent_dictionary_events(events)

        self.assertEqual(entries, [{
            "type": "dictionary_add",
            "target": "universe",
            "universe": "Stargate",
            "list": "names",
            "word": "O'Neill",
        }])

    def test_universe_rename_updates_entry_and_delete_removes_it(self):
        tool = make_tool()
        events = [
            {"type": "dictionary_add", "target": "universe", "universe": "Stargate", "list": "words", "word": "Goauld"},
            {"type": "universe_rename", "from": "Stargate", "to": "Stargate SG-1"},
        ]
        renamed = tool.reduce_recent_dictionary_events(events)
        self.assertEqual(renamed[0]["universe"], "Stargate SG-1")

        deleted = tool.reduce_recent_dictionary_events(events + [
            {"type": "universe_delete", "universe": "Stargate SG-1"}
        ])
        self.assertEqual(deleted, [])

    def test_remove_and_duplicate_additions_leave_no_stale_duplicate(self):
        tool = make_tool()
        add = {"type": "dictionary_add", "target": "user", "base_language": "british", "list": "words", "word": "TARDIS"}
        events = [add, dict(add), {"type": "dictionary_remove", "target": "user", "base_language": "british", "list": "words", "word": "tardis"}]
        self.assertEqual(tool.reduce_recent_dictionary_events(events), [])

    def test_legacy_remove_without_list_type_removes_recent_name(self):
        tool = make_tool()
        events = [
            {"type": "dictionary_add", "target": "universe", "universe": "Stargate", "list": "names", "word": "O'Neill"},
            {"type": "dictionary_remove", "target": "universe", "universe": "Stargate", "word": "O'Neill"},
        ]
        self.assertEqual(tool.reduce_recent_dictionary_events(events), [])


class SubstitutionEventReplayTests(unittest.TestCase):
    def test_edit_and_move_replace_original_substitution(self):
        tool = make_tool()
        events = [
            {"type": "substitution_add", "target": "user", "base_language": "american", "input": "goauld", "output": "Goauld"},
            {"type": "substitution_edit", "target": "user", "base_language": "american", "from_input": "goauld", "input": "goauld", "output": "Goa'uld"},
            {
                "type": "substitution_move",
                "input": "goauld",
                "output": "Goa'uld",
                "from_target": "user",
                "from_base_language": "american",
                "to_target": "universe",
                "to_universe": "Stargate",
            },
        ]

        entries = tool.reduce_recent_substitution_events(events)

        self.assertEqual(entries, [{
            "type": "substitution_add",
            "target": "universe",
            "universe": "Stargate",
            "input": "goauld",
            "output": "Goa'uld",
        }])

    def test_rename_then_remove_clears_substitution(self):
        tool = make_tool()
        events = [
            {"type": "substitution_add", "target": "universe", "universe": "Stargate", "input": "goauld", "output": "Goa'uld"},
            {"type": "universe_rename", "from": "Stargate", "to": "SG-1"},
            {"type": "substitution_remove", "target": "universe", "universe": "SG-1", "input": "goauld"},
        ]
        self.assertEqual(tool.reduce_recent_substitution_events(events), [])


class FilesystemVerificationTests(unittest.TestCase):
    def test_recent_dictionary_entries_drop_undone_or_manually_removed_items(self):
        tool = make_tool()
        tool.read_log_events = Mock(return_value=[
            {"type": "dictionary_add", "target": "user", "base_language": "american", "list": "words", "word": "alpha"},
            {"type": "dictionary_add", "target": "user", "base_language": "american", "list": "names", "word": "O'Neill"},
        ])
        tool.load_word_set = Mock(return_value=set())
        tool.load_name_map = Mock(return_value={"o'neill": "O'Neill"})

        entries = tool.recent_dictionary_entries()

        self.assertEqual(entries, [{
            "type": "dictionary_add",
            "target": "user",
            "base_language": "american",
            "list": "names",
            "word": "O'Neill",
        }])

    def test_legacy_user_event_is_resolved_to_language_where_entry_exists(self):
        tool = make_tool()
        tool.read_log_events = Mock(return_value=[
            {"type": "dictionary_add", "target": "user", "list": "words", "word": "TARDIS"},
        ])
        tool.load_word_set = Mock(side_effect=lambda path: {"tardis"} if path.name.startswith("british_") else set())

        entries = tool.recent_dictionary_entries()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["base_language"], "british")

    def test_recent_substitution_uses_current_file_output_and_drops_missing(self):
        tool = make_tool()
        tool.read_log_events = Mock(return_value=[
            {"type": "substitution_add", "target": "user", "base_language": "american", "input": "teh", "output": "old"},
            {"type": "substitution_add", "target": "user", "base_language": "american", "input": "missing", "output": "gone"},
        ])
        tool.load_substitutions = Mock(return_value={"teh": "the"})

        entries = tool.recent_substitution_entries()

        self.assertEqual(entries, [{
            "type": "substitution_add",
            "target": "user",
            "base_language": "american",
            "input": "teh",
            "output": "the",
        }])


class ReviewScreenTests(unittest.TestCase):
    def test_dictionary_review_uses_reconstructed_entries(self):
        tool = make_tool()
        tool.recent_dictionary_entries = Mock(return_value=[{
            "type": "dictionary_add",
            "target": "user",
            "base_language": "british",
            "list": "names",
            "word": "The Doctor",
        }])
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", io.StringIO()) as output,
        ):
            tool.review_recent_dictionary_additions()

        rendered = output.getvalue()
        self.assertIn("User (British English)", rendered)
        self.assertIn("Name", rendered)
        self.assertIn("The Doctor", rendered)

    def test_substitution_review_uses_reconstructed_entries(self):
        tool = make_tool()
        tool.recent_substitution_entries = Mock(return_value=[{
            "type": "substitution_add",
            "target": "user",
            "base_language": "american",
            "input": "teh",
            "output": "the",
        }])
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", io.StringIO()) as output,
        ):
            tool.review_recent_substitution_additions()

        rendered = output.getvalue()
        self.assertIn("User (American English)", rendered)
        self.assertIn("teh", rendered)
        self.assertIn("the", rendered)


if __name__ == "__main__":
    unittest.main()
