import io
import unittest
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

from subtitle_cleanup import (
    ConsoleProgressReporter,
    DEFAULT_OPTIONS,
    DictionaryContext,
    SubtitleBlock,
    SubtitleCleanupTool,
)


class TtyStringIO(io.StringIO):
    def isatty(self):
        return True


def make_tool() -> SubtitleCleanupTool:
    """Build an isolated tool without creating runtime dictionary files."""
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


class SpellcheckChoiceTests(unittest.TestCase):
    def setUp(self):
        self.tool = make_tool()
        self.standard = DictionaryContext(language="american")
        self.universe = DictionaryContext(language="american", universe="Stargate")

    def test_documented_shortcuts_are_valid(self):
        suggestions = ["one", "two", "three", "four", "five", "six"]
        self.assertEqual(self.tool.parse_spellcheck_choice("71", suggestions, self.standard), (7, 1))
        self.assertEqual(self.tool.parse_spellcheck_choice("82", suggestions, self.standard), (8, 2))
        self.assertEqual(self.tool.parse_spellcheck_choice("94", suggestions, self.standard), (9, 4))
        self.assertEqual(self.tool.parse_spellcheck_choice("73", suggestions, self.universe), (7, 3))

    def test_scope_matrix_rejects_unavailable_or_invalid_scopes(self):
        suggestions = ["one"]
        self.assertIsNone(self.tool.parse_spellcheck_choice("13", suggestions, self.standard))
        self.assertIsNone(self.tool.parse_spellcheck_choice("84", suggestions, self.standard))
        self.assertIsNone(self.tool.parse_spellcheck_choice("91", suggestions, self.universe))
        self.assertIsNone(self.tool.parse_spellcheck_choice("93", suggestions, self.standard))

    def test_shortcut_cannot_select_a_missing_suggestion(self):
        self.assertIsNone(self.tool.parse_spellcheck_choice("63", ["only"], self.universe))

    def test_invalid_ignore_scope_explains_valid_alternatives(self):
        message = self.tool.spellcheck_choice_guidance("84", ["one"], self.standard)
        self.assertIn("81 or 82", message)
        self.assertIn("93 or 94", message)

    def test_ignore_action_alone_still_prompts_for_scope(self):
        with patch.object(self.tool, "prompt_scope", return_value=2) as prompt_scope:
            result = self.tool.parse_spellcheck_choice("8", ["one"], self.standard)

        self.assertEqual(result, (8, 2))
        prompt_scope.assert_called_once_with(8, self.standard)


class SpellcheckPresentationTests(unittest.TestCase):
    def test_progress_reporter_shows_position_and_throttles_updates(self):
        output = TtyStringIO()
        reporter = ConsoleProgressReporter(output, interval_seconds=1.0)

        with patch("subtitle_cleanup.time.monotonic", side_effect=[10.0, 10.5, 11.0]):
            reporter.update("Spellchecking", 2, 3, 10, 100)
            reporter.update("Spellchecking", 2, 3, 11, 100)
            reporter.update("Spellchecking", 2, 3, 12, 100)

        rendered = output.getvalue()
        self.assertEqual(rendered.count("\rSpellchecking:"), 2)
        self.assertIn("File 2 of 3 | Subtitle 10 of 100", rendered)
        self.assertNotIn("Subtitle 11 of 100", rendered)
        self.assertIn("Subtitle 12 of 100", rendered)

    def test_progress_reporter_is_silent_for_redirected_output(self):
        output = io.StringIO()
        ConsoleProgressReporter(output).update("Preparing", 1, 2, 3, 100)
        self.assertEqual(output.getvalue(), "")

    def test_action_menu_places_standard_scope_list_beside_actions(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:01,000 --> 00:00:01,500",
                ["That wyrd appears."],
            )
        ]
        context = DictionaryContext(language="american")
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", output),
        ):
            tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "wyrd",
                context,
            )

        rendered = output.getvalue()
        self.assertRegex(rendered, r"7 - Edit/Substitute\s+Scope:")
        self.assertRegex(rendered, r"8 - Ignore\s+1 - This time")
        self.assertRegex(rendered, r"9 - Add word/name/phrase\s+2 - This session")
        self.assertRegex(rendered, r"0 - Quit spellcheck\s+4 - Always")
        self.assertNotIn("3 - This universe", rendered)
        self.assertNotIn("Valid scope keys", rendered)
        self.assertFalse(
            any(line.startswith("    Scope:") for line in rendered.splitlines())
        )

    def test_action_menu_places_universe_scope_list_beside_actions(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:01,000 --> 00:00:01,500",
                ["That wyrd appears."],
            )
        ]
        context = DictionaryContext(language="american", universe="Stargate")
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", output),
        ):
            tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "wyrd",
                context,
            )

        rendered = output.getvalue()
        self.assertRegex(rendered, r"7 - Edit/Substitute\s+Scope:")
        self.assertRegex(rendered, r"8 - Ignore\s+1 - This time")
        self.assertRegex(rendered, r"9 - Add word/name/phrase\s+2 - This session")
        self.assertRegex(rendered, r"U - Undo last action\s+3 - This universe")
        self.assertRegex(rendered, r"0 - Quit spellcheck\s+4 - Always")

    def test_search_action_opens_google_for_the_dialogue_line_and_returns_to_prompt(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:01,000 --> 00:00:01,500",
                ["An unrelated first line.", "<i>That wyrd appears.</i>"],
            )
        ]
        context = DictionaryContext(language="american")
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("subtitle_cleanup.webbrowser.open", return_value=True) as open_browser,
            patch("builtins.input", side_effect=["s", "", "0"]),
            patch("sys.stdout", output),
        ):
            result = tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "wyrd",
                context,
            )

        self.assertEqual(result, "quit")
        open_browser.assert_called_once_with(
            "https://www.google.com/search?q=That+wyrd+appears.",
            new=2,
        )
        self.assertIn("S - Search this subtitle line in Google", output.getvalue())
        self.assertIn("Opened a Google search", output.getvalue())

    def test_search_action_reports_browser_failure_without_changing_the_subtitle(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:01,000 --> 00:00:01,500",
                ["That wyrd appears."],
            )
        ]
        context = DictionaryContext(language="american")
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("subtitle_cleanup.webbrowser.open", side_effect=RuntimeError("no browser")),
            patch("builtins.input", side_effect=["S", "", "0"]),
            patch("sys.stdout", output),
        ):
            tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "wyrd",
                context,
            )

        self.assertEqual(blocks[0].text_lines, ["That wyrd appears."])
        self.assertIn("could not open a web browser", output.getvalue().casefold())

    def test_current_unknown_word_is_highlighted_when_color_is_available(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:01,000 --> 00:00:01,500",
                ["That wyrd appears."],
            )
        ]
        context = DictionaryContext(language="american")
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=True),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", output),
        ):
            tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "wyrd",
                context,
            )

        self.assertIn("\x1b[30;103mwyrd\x1b[0m", output.getvalue())

    def test_prompt_remains_plain_when_terminal_color_is_unavailable(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:01,000 --> 00:00:01,500",
                ["That wyrd appears."],
            )
        ]
        context = DictionaryContext(language="american")
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", output),
        ):
            tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "wyrd",
                context,
            )

        self.assertIn("That wyrd appears.", output.getvalue())
        self.assertNotIn("\x1b[", output.getvalue())

    def test_prompt_shows_two_previous_current_two_next_and_six_slots(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(str(index), f"00:00:0{index},000 --> 00:00:0{index},500", [f"cue{index}"])
            for index in range(1, 6)
        ]
        context = DictionaryContext(language="american", base_words={"cue"})

        output = io.StringIO()
        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", output),
        ):
            result = tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                2,
                "cue3",
                context,
                file_number=2,
                total_files=4,
            )

        rendered = output.getvalue()
        self.assertEqual(result, "quit")
        self.assertIn("Progress: File 2 of 4 | Subtitle 3 of 5", rendered)
        for cue in ("cue1", "cue2", "cue3", "cue4", "cue5"):
            self.assertIn(cue, rendered)
        for index in range(1, 7):
            self.assertIn(f"{index} -", rendered)

    def test_suggestions_are_deterministic_and_limited_to_six(self):
        context = DictionaryContext(
            language="american",
            base_words={"responsibly", "responsibility", "responsive", "response", "respond", "responder", "responses"},
        )
        first = context.suggestions_for("responsibably")
        second = context.suggestions_for("responsibably")
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 6)


class InformalApostropheVariantTests(unittest.TestCase):
    def test_option_is_enabled_by_default(self):
        self.assertTrue(DEFAULT_OPTIONS["recognize_dropped_g_apostrophe_forms"])

    def test_known_ing_word_accepts_straight_and_curly_in_apostrophe_forms(self):
        context = DictionaryContext(
            language="american",
            base_words={"going"},
            recognize_dropped_g_apostrophe_forms=True,
        )

        self.assertTrue(context.is_known_word("goin'"))
        self.assertTrue(context.is_known_word("goin’"))

    def test_loaded_context_receives_the_persisted_option(self):
        tool = make_tool()
        tool.load_word_set = Mock(side_effect=[{"going"}, set()])
        tool.load_name_map = Mock(return_value={})
        tool.load_substitutions = Mock(return_value={})

        context = tool.load_dictionary_context("american")

        self.assertTrue(context.recognize_dropped_g_apostrophe_forms)
        self.assertTrue(context.is_known_word("goin'"))

    def test_variant_requires_both_enabled_option_and_known_completed_word(self):
        disabled = DictionaryContext(
            language="american",
            base_words={"going"},
            recognize_dropped_g_apostrophe_forms=False,
        )
        missing_completion = DictionaryContext(
            language="american",
            base_words={"go"},
            recognize_dropped_g_apostrophe_forms=True,
        )

        self.assertFalse(disabled.is_known_word("goin'"))
        self.assertFalse(missing_completion.is_known_word("goin'"))

    def test_unknown_detection_keeps_trailing_apostrophe_as_part_of_token(self):
        tool = make_tool()
        block = SubtitleBlock(
            "1",
            "00:00:01,000 --> 00:00:01,500",
            ["goin'"],
        )
        context = DictionaryContext(
            language="american",
            base_words={"going"},
            recognize_dropped_g_apostrophe_forms=False,
        )

        unknown = tool.find_first_unknown_word(block, context, "episode.srt", 0)

        self.assertIsNotNone(unknown)
        self.assertEqual(unknown["word"], "goin'")


class PhraseScopedDictionaryTests(unittest.TestCase):
    def test_name_phrase_is_known_only_as_complete_sequence(self):
        tool = make_tool()
        context = DictionaryContext(
            language="american",
            base_words={"vala", "arrived"},
            universe_names={"vala mal doran": "Vala Mal Doran"},
        )
        phrase_block = SubtitleBlock(
            "1", "00:00:00,000 --> 00:00:01,000", ["Vala Mal Doran arrived."]
        )
        isolated_block = SubtitleBlock(
            "2", "00:00:02,000 --> 00:00:03,000", ["Mal arrived."]
        )

        self.assertIsNone(tool.find_first_unknown_word(phrase_block, context, "episode.srt", 0))
        unknown = tool.find_first_unknown_word(isolated_block, context, "episode.srt", 1)

        self.assertIsNotNone(unknown)
        self.assertEqual(unknown["word"], "Mal")

    def test_name_phrase_can_span_wrapped_subtitle_lines(self):
        tool = make_tool()
        context = DictionaryContext(
            language="american",
            base_words={"vala", "arrived"},
            universe_names={"vala mal doran": "Vala Mal Doran"},
        )
        block = SubtitleBlock(
            "1", "00:00:00,000 --> 00:00:01,000", ["Vala Mal", "Doran arrived."]
        )

        self.assertIsNone(tool.find_first_unknown_word(block, context, "episode.srt", 0))

    def test_accepted_word_phrase_does_not_accept_its_components(self):
        tool = make_tool()
        context = DictionaryContext(
            language="american",
            base_words={"bracelets"},
            universe_words={"kor mak"},
        )
        phrase_block = SubtitleBlock(
            "1", "00:00:00,000 --> 00:00:01,000", ["kor mak bracelets"]
        )
        isolated_block = SubtitleBlock(
            "2", "00:00:02,000 --> 00:00:03,000", ["kor bracelets"]
        )

        self.assertIsNone(tool.find_first_unknown_word(phrase_block, context, "episode.srt", 0))
        unknown = tool.find_first_unknown_word(isolated_block, context, "episode.srt", 1)

        self.assertIsNotNone(unknown)
        self.assertEqual(unknown["word"], "kor")

    def test_phrase_match_does_not_cross_punctuation(self):
        tool = make_tool()
        context = DictionaryContext(
            language="american",
            universe_words={"kor mak"},
        )
        block = SubtitleBlock(
            "1", "00:00:00,000 --> 00:00:01,000", ["kor, mak"]
        )

        unknown = tool.find_first_unknown_word(block, context, "episode.srt", 0)

        self.assertIsNotNone(unknown)
        self.assertEqual(unknown["word"], "kor")

    def test_dictionary_prompt_can_store_exact_name_phrase_from_cue(self):
        tool = make_tool()
        block = SubtitleBlock(
            "1", "00:00:00,000 --> 00:00:01,000", ["Vala Mal Doran arrived."]
        )

        with patch("builtins.input", side_effect=["4", "Vala Mal Doran", ""]):
            result = tool.prompt_dictionary_entry("Mal", block)

        self.assertEqual(result, ("names", "Vala Mal Doran"))

    def test_spellcheck_adds_recases_and_undoes_name_phrase_as_one_action(self):
        tool = make_tool()
        tool.add_word_to_file = Mock(return_value=True)
        tool.remove_entries_from_file = Mock(return_value=[])
        block = SubtitleBlock(
            "1", "00:00:00,000 --> 00:00:01,000", ["Vala mal doran arrived."]
        )
        blocks = [block]
        context = DictionaryContext(
            language="american",
            universe="Stargate",
            base_words={"vala", "arrived"},
        )

        with (
            patch(
                "builtins.input",
                side_effect=["93", "4", "Vala mal doran", "Vala Mal Doran"],
            ),
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "mal",
                context,
            )

        self.assertEqual(result, "continue")
        self.assertEqual(block.text_lines, ["Vala Mal Doran arrived."])
        self.assertIsNone(tool.find_first_unknown_word(block, context, "episode.srt", 0))

        self.assertTrue(tool.perform_undo(blocks, context, "episode.srt"))
        self.assertEqual(block.text_lines, ["Vala mal doran arrived."])
        self.assertNotIn("vala mal doran", context.universe_names)


class DictionaryLookupPerformanceTests(unittest.TestCase):
    def test_known_word_lookup_does_not_rebuild_combined_dictionary(self):
        context = DictionaryContext(
            language="american",
            base_words={"known"},
            user_words={"personal"},
            universe_words={"fictional"},
        )

        with patch.object(
            DictionaryContext,
            "all_words",
            new_callable=PropertyMock,
            side_effect=AssertionError("combined dictionary was rebuilt"),
        ) as combined:
            self.assertTrue(context.is_known_word("known"))
            self.assertTrue(context.is_known_word("personal"))
            self.assertTrue(context.is_known_word("fictional"))

        combined.assert_not_called()


class SpellcheckActionTests(unittest.TestCase):
    def test_selected_word_replacement_can_change_one_part_of_hyphenated_term(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:00,000 --> 00:00:01,000",
                ["Get re-assed to NASA."],
            )
        ]
        context = DictionaryContext(language="american", base_words={"sassed"})

        applied = tool.apply_replacement_action(
            Path("C:/Example/episode.srt"),
            Path("C:/Example"),
            blocks,
            0,
            "assed",
            "sassed",
            1,
            context,
            action_name="suggestion",
        )

        self.assertTrue(applied)
        self.assertEqual(blocks[0].text_lines, ["Get re-sassed to NASA."])

    def test_edit_can_replace_hyphenated_term_containing_selected_word(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:00,000 --> 00:00:01,000",
                ["Get re-assed to NASA."],
            )
        ]
        context = DictionaryContext(language="american", base_words={"reassessed"})

        with (
            patch("builtins.input", side_effect=["71", "2", "reassessed"]),
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "assed",
                context,
            )

        self.assertEqual(result, "continue")
        self.assertEqual(blocks[0].text_lines, ["Get reassessed to NASA."])
        self.assertEqual(tool.undo_stack[-1]["from"], "re-assed")
        self.assertTrue(tool.perform_undo(blocks, context, "episode.srt"))
        self.assertEqual(blocks[0].text_lines, ["Get re-assed to NASA."])

    def test_edit_can_replace_custom_text_from_current_subtitle(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:00,000 --> 00:00:01,000",
                ["It could of worked."],
            )
        ]
        context = DictionaryContext(language="american", base_words={"could", "have", "worked"})

        with (
            patch(
                "builtins.input",
                side_effect=["71", "3", "could of", "could have"],
            ),
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "of",
                context,
            )

        self.assertEqual(result, "continue")
        self.assertEqual(blocks[0].text_lines, ["It could have worked."])
        self.assertEqual(tool.undo_stack[-1]["from"], "could of")

    def test_session_edit_uses_larger_term_as_substitution_source(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:00,000 --> 00:00:01,000",
                ["Get re-assed to NASA."],
            )
        ]
        context = DictionaryContext(language="american", base_words={"reassessed"})

        with (
            patch("builtins.input", side_effect=["72", "2", "reassessed"]),
            patch("subtitle_cleanup.clear_screen"),
            patch("subtitle_cleanup.terminal_color_supported", return_value=False),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "assed",
                context,
            )

        self.assertEqual(result, "continue")
        self.assertEqual(
            tool.current_session_substitutions,
            {"re-assed": "reassessed"},
        )

    def test_dictionary_add_prompt_distinguishes_word_from_name(self):
        tool = make_tool()

        with patch("builtins.input", side_effect=["2", "Vala"]):
            result = tool.prompt_dictionary_entry("vala")

        self.assertEqual(result, ("names", "Vala"))

    def test_dictionary_add_can_target_universe_names(self):
        tool = make_tool()
        tool.add_word_to_file = Mock(return_value=True)
        context = DictionaryContext(language="american", universe="Stargate")

        tool.apply_dictionary_add("Vala", 3, context, list_name="names")

        expected_path = tool.universe_dir / "Stargate" / "names.txt"
        event = {
            "type": "dictionary_add",
            "target": "universe",
            "universe": "Stargate",
            "list": "names",
            "word": "Vala",
        }
        tool.add_word_to_file.assert_called_once_with(expected_path, "Vala", event)
        self.assertEqual(context.universe_names["vala"], "Vala")
        self.assertEqual(tool.undo_stack, [event])

    def test_adding_name_from_spellcheck_recases_current_occurrence(self):
        tool = make_tool()
        tool.add_word_to_file = Mock(return_value=True)
        tool.remove_entries_from_file = Mock(return_value=1)
        blocks = [
            SubtitleBlock(
                "1",
                "00:00:00,000 --> 00:00:01,000",
                ["I spoke with vala."],
            )
        ]
        context = DictionaryContext(
            language="american",
            universe="Stargate",
            base_words={"i", "spoke", "with"},
        )

        with (
            patch("builtins.input", side_effect=["93", "2", "Vala"]),
            patch("subtitle_cleanup.clear_screen"),
            patch("sys.stdout", io.StringIO()),
        ):
            result = tool.prompt_spellcheck_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "vala",
                context,
            )

        self.assertEqual(result, "continue")
        self.assertEqual(blocks[0].text_lines, ["I spoke with Vala."])
        self.assertEqual(tool.undo_stack[-1]["before_text_lines"], ["I spoke with vala."])
        self.assertEqual(tool.undo_stack[-1]["after_text_lines"], ["I spoke with Vala."])

        self.assertTrue(tool.perform_undo(blocks, context, "episode.srt"))
        self.assertEqual(blocks[0].text_lines, ["I spoke with vala."])
        self.assertNotIn("vala", context.universe_names)

    def test_dictionary_add_undo_removes_name_from_active_context(self):
        tool = make_tool()
        tool.remove_entries_from_file = Mock(return_value=1)
        context = DictionaryContext(
            language="american",
            universe="Stargate",
            universe_names={"vala": "Vala"},
        )
        event = {
            "type": "dictionary_add",
            "target": "universe",
            "universe": "Stargate",
            "list": "names",
            "word": "Vala",
        }
        tool.undo_stack.append(event)

        tool.perform_undo(ctx=context)

        self.assertNotIn("vala", context.universe_names)
        tool.remove_entries_from_file.assert_called_once_with(
            tool.universe_dir / "Stargate" / "names.txt",
            ["Vala"],
        )

    def test_this_occurrence_replaces_exactly_one_occurrence_in_block(self):
        tool = make_tool()
        blocks = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell mispell", "mispell"])]
        context = DictionaryContext(language="american", base_words={"misspell"})

        applied = tool.apply_replacement_action(
            Path("C:/Example/episode.srt"),
            Path("C:/Example"),
            blocks,
            0,
            "mispell",
            "misspell",
            1,
            context,
            action_name="suggestion",
        )

        self.assertTrue(applied)
        self.assertEqual(blocks[0].text_lines, ["misspell mispell", "mispell"])

    def test_canceling_unknown_permanent_replacement_changes_nothing(self):
        tool = make_tool()
        tool.add_word_to_file = Mock()
        tool.add_substitution_to_file = Mock()
        blocks = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell"])]
        context = DictionaryContext(language="american")

        with (
            patch("builtins.input", return_value="2"),
            patch("subtitle_cleanup.clear_screen"),
            patch("sys.stdout", io.StringIO()),
        ):
            applied = tool.apply_replacement_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "mispell",
                "inventedword",
                4,
                context,
                action_name="edit_substitute",
            )

        self.assertFalse(applied)
        self.assertEqual(blocks[0].text_lines, ["mispell"])
        tool.add_word_to_file.assert_not_called()
        tool.add_substitution_to_file.assert_not_called()

    def test_unknown_universe_replacement_can_be_added_as_name(self):
        tool = make_tool()
        tool.add_word_to_file = Mock(return_value=True)
        tool.add_substitution_to_file = Mock()
        blocks = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["teald"])]
        context = DictionaryContext(language="american", universe="Stargate")

        with (
            patch("builtins.input", side_effect=["1", "2", "Teal'c"]),
            patch("subtitle_cleanup.clear_screen"),
            patch("sys.stdout", io.StringIO()),
        ):
            applied = tool.apply_replacement_action(
                Path("C:/Example/episode.srt"),
                Path("C:/Example"),
                blocks,
                0,
                "teald",
                "Teal'c",
                3,
                context,
                action_name="edit_substitute",
            )

        self.assertTrue(applied)
        self.assertEqual(blocks[0].text_lines, ["Teal'c"])
        self.assertEqual(context.universe_names["teal'c"], "Teal'c")
        event = tool.undo_stack[-1]["dictionary_add"]
        self.assertEqual(event["list"], "names")
        self.assertEqual(event["word"], "Teal'c")

    def test_session_substitution_applies_to_later_cues_without_reprompting(self):
        tool = make_tool()
        blocks = [
            SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell text"]),
            SubtitleBlock("2", "00:00:02,000 --> 00:00:03,000", ["mispell text"]),
        ]
        context = DictionaryContext(language="american", base_words={"misspell", "text"})
        tool.parse_srt = Mock(return_value=blocks)
        tool.write_srt = Mock()
        tool.save_session_state = Mock()

        calls = []

        def choose_once(
            path,
            target,
            current_blocks,
            block_index,
            word,
            ctx,
            file_number=1,
            total_files=1,
        ):
            calls.append((block_index, word))
            if len(calls) > 1:
                self.fail("The session substitution should prevent a second prompt")
            tool.apply_replacement_action(
                path,
                target,
                current_blocks,
                block_index,
                word,
                "misspell",
                2,
                ctx,
                action_name="edit_substitute",
            )
            return "continue"

        tool.prompt_spellcheck_action = choose_once
        state = {}
        changed, quit_requested, last_index = tool.spellcheck_file(
            Path("C:/Example/episode.srt"),
            Path("C:/Example"),
            context,
            0,
            state,
        )

        self.assertTrue(changed)
        self.assertFalse(quit_requested)
        self.assertEqual(last_index, 2)
        self.assertEqual(calls, [(0, "mispell")])
        self.assertEqual(blocks[0].text_lines, ["misspell text"])
        self.assertEqual(blocks[1].text_lines, ["misspell text"])
        self.assertEqual(state["session_substitutions"], {"mispell": "misspell"})
        self.assertEqual(len(state["undo_stack"]), 1)

    def test_session_substitution_takes_precedence_over_persistent_substitution(self):
        tool = make_tool()
        tool.current_session_substitutions["mispell"] = "session-choice"
        context = DictionaryContext(
            language="american",
            substitutions={"mispell": "persistent-choice"},
        )

        self.assertEqual(
            tool.apply_active_substitutions("mispell", context),
            "session-choice",
        )

    def test_known_global_replacement_is_persisted_in_context(self):
        tool = make_tool()
        tool.add_substitution_to_file = Mock()
        blocks = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell"])]
        context = DictionaryContext(language="american", base_words={"misspell"})

        applied = tool.apply_replacement_action(
            Path("C:/Example/episode.srt"),
            Path("C:/Example"),
            blocks,
            0,
            "mispell",
            "misspell",
            4,
            context,
            action_name="suggestion",
        )

        self.assertTrue(applied)
        self.assertEqual(context.user_substitutions["mispell"], "misspell")
        self.assertEqual(context.substitutions["mispell"], "misspell")
        tool.add_substitution_to_file.assert_called_once()

    def test_one_undo_reverts_session_rule_and_visible_replacement(self):
        tool = make_tool()
        blocks = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell"])]
        context = DictionaryContext(language="american", base_words={"misspell"})

        tool.apply_replacement_action(
            Path("C:/Example/episode.srt"),
            Path("C:/Example"),
            blocks,
            0,
            "mispell",
            "misspell",
            2,
            context,
            action_name="edit_substitute",
        )

        self.assertEqual(len(tool.undo_stack), 1)
        self.assertEqual(tool.current_session_substitutions["mispell"], "misspell")
        tool.perform_undo(blocks, context, "episode.srt")
        self.assertEqual(blocks[0].text_lines, ["mispell"])
        self.assertNotIn("mispell", tool.current_session_substitutions)
        self.assertEqual(tool.undo_stack, [])

    def test_one_undo_reverts_global_rule_context_and_visible_replacement(self):
        tool = make_tool()
        tool.add_substitution_to_file = Mock()
        tool.load_substitutions = Mock(return_value={"mispell": "misspell"})
        tool.save_substitutions = Mock()
        blocks = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["mispell"])]
        context = DictionaryContext(language="american", base_words={"misspell"})

        tool.apply_replacement_action(
            Path("C:/Example/episode.srt"),
            Path("C:/Example"),
            blocks,
            0,
            "mispell",
            "misspell",
            4,
            context,
            action_name="suggestion",
        )

        tool.perform_undo(blocks, context, "episode.srt")
        self.assertEqual(blocks[0].text_lines, ["mispell"])
        self.assertNotIn("mispell", context.user_substitutions)
        self.assertNotIn("mispell", context.substitutions)
        self.assertEqual(tool.undo_stack, [])
        tool.save_substitutions.assert_called_once()

    def test_repeatable_undo_restores_replacement_and_ignores(self):
        tool = make_tool()
        blocks = [SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ["corrected"])]
        tool.current_session_ignores.add("sessionword")
        tool.block_ignores.add(("episode.srt", 0, "blockword"))
        tool.undo_stack.extend([
            {
                "type": "replace_word",
                "file": "episode.srt",
                "subtitle_index": 0,
                "before_text_lines": ["mispell"],
                "after_text_lines": ["corrected"],
            },
            {"type": "session_ignore", "word": "sessionword"},
            {"type": "block_ignore", "file": "episode.srt", "subtitle_index": 0, "word": "blockword"},
        ])

        tool.perform_undo(blocks)
        tool.perform_undo(blocks)
        tool.perform_undo(blocks)

        self.assertEqual(blocks[0].text_lines, ["mispell"])
        self.assertNotIn("sessionword", tool.current_session_ignores)
        self.assertNotIn(("episode.srt", 0, "blockword"), tool.block_ignores)


if __name__ == "__main__":
    unittest.main()
