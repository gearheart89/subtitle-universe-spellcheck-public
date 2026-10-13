import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from subtitle_cleanup import DictionaryContext, SubtitleBlock
from tests.test_spellcheck import make_tool


class CrossFileSubstitutionTests(unittest.TestCase):
    def test_preexisting_rule_is_not_reapplied_after_formatting(self):
        tool = make_tool()
        block = SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["foo"])
        context = DictionaryContext(
            language="american",
            base_words={"foobar"},
            substitutions={"foo": "foobar"},
        )
        tool.parse_srt = Mock(return_value=[block])
        tool.write_srt = Mock()
        tool.save_session_state = Mock()
        tool.prompt_spellcheck_action = Mock(
            side_effect=AssertionError("The persistent rule should avoid a prompt")
        )

        tool.spellcheck_file(
            Path("C:/Example/episode.srt"), Path("C:/Example"), context, 0, {}
        )

        self.assertEqual(block.text_lines, ["foobar"])

    def test_session_rule_tracks_automatic_changes_in_a_later_file(self):
        tool = make_tool()
        context = DictionaryContext(language="american", base_words={"misspell", "text"})
        origin = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])]
        tool.apply_replacement_action(
            Path("C:/Example/one.srt"), Path("C:/Example"), origin, 0,
            "mispell", "misspell", 2, context, action_name="edit_substitute",
        )
        later = SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])
        tool.parse_srt = Mock(return_value=[later])
        tool.write_srt = Mock()
        tool.save_session_state = Mock()
        tool.prompt_spellcheck_action = Mock(
            side_effect=AssertionError("The active session rule should avoid a prompt")
        )

        changed, quit_requested, last_index = tool.spellcheck_file(
            Path("C:/Example/two.srt"),
            Path("C:/Example"),
            context,
            0,
            {},
        )

        self.assertTrue(changed)
        self.assertFalse(quit_requested)
        self.assertEqual(last_index, 1)
        self.assertEqual(later.text_lines, ["misspell text"])
        self.assertEqual(tool.undo_stack[0]["propagated_changes"], [{
            "file": "two.srt",
            "subtitle_index": 0,
            "before_text_lines": ["mispell text"],
            "after_text_lines": ["misspell text"],
        }])

    def test_global_rule_undo_restores_origin_and_later_completed_file(self):
        tool = make_tool()
        tool.add_substitution_to_file = Mock()
        tool.load_substitutions = Mock(return_value={"mispell": "misspell"})
        tool.save_substitutions = Mock()
        context = DictionaryContext(language="american", base_words={"misspell", "text"})
        origin = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])]
        tool.apply_replacement_action(
            Path("C:/Example/one.srt"), Path("C:/Example"), origin, 0,
            "mispell", "misspell", 4, context, action_name="edit_substitute",
        )
        later = SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])
        tool.apply_active_substitutions_to_block(later, context, "two.srt", 0)

        files = {
            "one.srt": origin,
            "two.srt": [later],
        }
        tool.parse_srt = Mock(side_effect=lambda path: files[path.name])
        tool.write_srt = Mock()

        undone = tool.perform_undo(
            blocks=None,
            ctx=context,
            current_file=None,
            target=Path("C:/Example"),
        )

        self.assertTrue(undone)
        self.assertEqual(origin[0].text_lines, ["mispell text"])
        self.assertEqual(later.text_lines, ["mispell text"])
        self.assertNotIn("mispell", context.substitutions)
        self.assertEqual(tool.undo_stack, [])
        self.assertEqual(tool.write_srt.call_count, 2)

    def test_universe_rule_undo_restores_cross_file_text_and_rule(self):
        tool = make_tool()
        tool.add_substitution_to_file = Mock()
        tool.load_substitutions = Mock(return_value={"goauld": "Goa'uld"})
        tool.save_substitutions = Mock()
        context = DictionaryContext(
            language="american",
            universe="Stargate",
            universe_words={"goa'uld"},
        )
        origin = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["goauld ship"])]
        tool.apply_replacement_action(
            Path("C:/Example/one.srt"), Path("C:/Example"), origin, 0,
            "goauld", "Goa'uld", 3, context, action_name="edit_substitute",
        )
        later = SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["goauld ship"])
        tool.apply_active_substitutions_to_block(later, context, "two.srt", 0)
        files = {"one.srt": origin, "two.srt": [later]}
        tool.parse_srt = Mock(side_effect=lambda path: files[path.name])
        tool.write_srt = Mock()

        undone = tool.perform_undo(target=Path("C:/Example"), ctx=context)

        self.assertTrue(undone)
        self.assertEqual(origin[0].text_lines, ["goauld ship"])
        self.assertEqual(later.text_lines, ["goauld ship"])
        self.assertNotIn("goauld", context.universe_substitutions)
        self.assertNotIn("goauld", context.substitutions)

    def test_cross_file_undo_refuses_if_a_recorded_file_has_drifted(self):
        tool = make_tool()
        context = DictionaryContext(language="american", base_words={"misspell", "text"})
        origin = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])]
        tool.apply_replacement_action(
            Path("C:/Example/one.srt"), Path("C:/Example"), origin, 0,
            "mispell", "misspell", 2, context, action_name="edit_substitute",
        )
        later = SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])
        tool.apply_active_substitutions_to_block(later, context, "two.srt", 0)
        later.text_lines = ["manually edited"]
        files = {"one.srt": origin, "two.srt": [later]}
        tool.parse_srt = Mock(side_effect=lambda path: files[path.name])
        tool.write_srt = Mock()
        tool.pause = Mock()

        with patch("subtitle_cleanup.pause"):
            undone = tool.perform_undo(target=Path("C:/Example"), ctx=context)

        self.assertFalse(undone)
        self.assertEqual(tool.undo_stack[0]["type"], "replace_word")
        self.assertEqual(tool.current_session_substitutions["mispell"], "misspell")
        tool.write_srt.assert_not_called()

    def test_cross_file_undo_rolls_back_earlier_files_when_a_later_write_fails(self):
        tool = make_tool()
        context = DictionaryContext(language="american", base_words={"misspell", "text"})
        origin = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])]
        tool.apply_replacement_action(
            Path("C:/Example/one.srt"), Path("C:/Example"), origin, 0,
            "mispell", "misspell", 2, context, action_name="edit_substitute",
        )
        later = SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])
        tool.apply_active_substitutions_to_block(later, context, "two.srt", 0)
        files = {"one.srt": origin, "two.srt": [later]}
        tool.parse_srt = Mock(side_effect=lambda path: files[path.name])
        writes = []

        def fail_second_file(path, blocks):
            writes.append((path.name, [list(block.text_lines) for block in blocks]))
            if path.name == "two.srt":
                raise OSError("simulated disk failure")

        tool.write_srt = Mock(side_effect=fail_second_file)

        with patch("subtitle_cleanup.pause"):
            undone = tool.perform_undo(target=Path("C:/Example"), ctx=context)

        self.assertFalse(undone)
        self.assertEqual(writes, [
            ("one.srt", [["mispell text"]]),
            ("two.srt", [["mispell text"]]),
            ("one.srt", [["misspell text"]]),
        ])
        self.assertEqual(origin[0].text_lines, ["misspell text"])
        self.assertEqual(later.text_lines, ["misspell text"])
        self.assertEqual(tool.current_session_substitutions["mispell"], "misspell")
        self.assertEqual(len(tool.undo_stack), 1)

    def test_cross_file_undo_marks_recovery_when_compensating_write_also_fails(self):
        tool = make_tool()
        context = DictionaryContext(language="american", base_words={"misspell", "text"})
        origin = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])]
        tool.apply_replacement_action(
            Path("C:/Example/one.srt"), Path("C:/Example"), origin, 0,
            "mispell", "misspell", 2, context, action_name="edit_substitute",
        )
        later = SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])
        tool.apply_active_substitutions_to_block(later, context, "two.srt", 0)
        files = {"one.srt": origin, "two.srt": [later]}
        tool.parse_srt = Mock(side_effect=lambda path: files[path.name])
        tool.refresh_manifest_entry = Mock()
        session_state = {
            "file_manifest": [],
            "completed_files": ["one.srt", "two.srt"],
        }
        writes = []

        def fail_later_write_and_compensation(path, blocks):
            writes.append((path.name, [list(block.text_lines) for block in blocks]))
            if path.name == "two.srt":
                raise OSError("simulated later write failure")
            if len(writes) == 3:
                raise OSError("simulated rollback failure")

        tool.write_srt = Mock(side_effect=fail_later_write_and_compensation)

        with (
            patch("subtitle_cleanup.pause"),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            undone = tool.perform_undo(
                target=Path("C:/Example"),
                ctx=context,
                session_state=session_state,
            )

        self.assertFalse(undone)
        self.assertEqual([name for name, _ in writes], ["one.srt", "two.srt", "one.srt"])
        self.assertEqual(origin[0].text_lines, ["mispell text"])
        self.assertEqual(later.text_lines, ["misspell text"])
        self.assertEqual(tool.current_session_substitutions["mispell"], "misspell")
        self.assertEqual(len(tool.undo_stack), 1)
        self.assertEqual(session_state["completed_files"], ["two.srt"])
        self.assertTrue(session_state["undo_recovery_required"])
        self.assertIn("one.srt", stdout.getvalue())
        self.assertIn("must stop", stdout.getvalue())

    def test_spellcheck_stops_when_failed_undo_requires_recovery(self):
        tool = make_tool()
        context = DictionaryContext(language="american", base_words={"text"})
        block = SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"])
        tool.parse_srt = Mock(return_value=[block])
        tool.format_text_lines = Mock(side_effect=lambda lines, ctx, **kwargs: lines)
        tool.apply_active_substitutions_to_block = Mock()
        tool.find_first_unknown_word = Mock(
            side_effect=[{"word": "mispell"}, AssertionError("spellcheck continued after unsafe rollback")]
        )
        tool.prompt_spellcheck_action = Mock(return_value="undo")
        tool.save_session_state = Mock()

        def require_recovery(*args, **kwargs):
            kwargs["session_state"]["undo_recovery_required"] = True
            return False

        tool.perform_undo = Mock(side_effect=require_recovery)
        session_state = {}

        changed, quit_requested, last_index = tool.spellcheck_file(
            Path("C:/Example/one.srt"),
            Path("C:/Example"),
            context,
            0,
            session_state,
        )

        self.assertFalse(changed)
        self.assertTrue(quit_requested)
        self.assertEqual(last_index, 0)
        self.assertTrue(session_state["undo_recovery_required"])
        self.assertEqual(tool.find_first_unknown_word.call_count, 1)


if __name__ == "__main__":
    unittest.main()
