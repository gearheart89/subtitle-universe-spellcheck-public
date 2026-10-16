import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.subtitle_cleanup import (
    PROJECT_URL,
    SCOWL_CREDIT,
    SCOWL_URL,
    DictionaryContext,
    SubtitleBlock,
    SubtitleCleanupTool,
)


class InterfaceGroupingTests(unittest.TestCase):
    def test_main_menu_is_grouped_without_changing_action_numbers(self):
        tool = SubtitleCleanupTool()
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", output),
        ):
            tool.run()

        rendered = output.getvalue()
        self.assertIn("Subtitle Scan:", rendered)
        self.assertIn("Dictionary Maintenance:", rendered)
        self.assertIn("Info/Maintenance:", rendered)
        self.assertIn("3. Run spellcheck with optional universe dictionary", rendered)
        self.assertIn("11. Flush session log", rendered)

    def test_cli_about_includes_project_license_and_scowl_attribution(self):
        tool = SubtitleCleanupTool()
        output = io.StringIO()

        with (
            patch("app.subtitle_cleanup.clear_screen"),
            patch("builtins.input", return_value=""),
            patch("sys.stdout", output),
        ):
            tool.show_about_screen()

        rendered = output.getvalue()
        self.assertIn(PROJECT_URL, rendered)
        self.assertIn("Application source: MIT License", rendered)
        self.assertIn(SCOWL_CREDIT, rendered)
        self.assertIn(SCOWL_URL, rendered)
        self.assertIn("dictionaries/base/SCOWL-COPYRIGHT.txt", rendered)

    def test_options_use_category_submenus_with_inline_cleanup_examples(self):
        tool = SubtitleCleanupTool()
        output = io.StringIO()

        with (
            patch("subtitle_cleanup.clear_screen"),
            patch("builtins.input", side_effect=["4", "0", "0"]),
            patch("sys.stdout", output),
        ):
            tool.options_menu()

        rendered = output.getvalue()
        self.assertIn("1. File Discovery and Safety", rendered)
        self.assertIn("4. Common Error Cleanup", rendered)
        self.assertIn("[â™ª → ♪] [â™« → ♫]", rendered)
        self.assertIn("[â€™ → ’] [â€œ → “]", rendered)
        self.assertIn("[<i>Hello<i> → <i>Hello</i>]", rendered)
        self.assertIn("[reports only—does not edit]", rendered)

    def test_main_menu_flush_help_explains_scope_without_flushing(self):
        tool = SubtitleCleanupTool()
        log_path = Path(__file__).with_name("_main_menu_flush_help.jsonl")
        try:
            log_path.write_text('{"event": "dictionary_add"}\n', encoding="utf-8")
            tool.session_log_path = log_path
            output = io.StringIO()

            with (
                patch("subtitle_cleanup.clear_screen"),
                patch("subtitle_cleanup.pause"),
                patch("builtins.input", side_effect=["11?", "0"]),
                patch("sys.stdout", output),
            ):
                tool.run()

            rendered = output.getvalue()
            self.assertIn("Flush session log — Help", rendered)
            self.assertIn("does not remove dictionary entries", rendered)
            self.assertIn("does not clear or abandon", rendered)
            self.assertEqual(
                log_path.read_text(encoding="utf-8"),
                '{"event": "dictionary_add"}\n',
            )
        finally:
            log_path.unlink(missing_ok=True)


class CommonErrorCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tool = SubtitleCleanupTool()
        self.context = DictionaryContext(language="american")
        self.tool.options["adjust_subtitle_line_count"] = False
        self.tool.options["detect_dropped_speaker_breaks"] = False

    def test_repairs_music_symbols_and_mojibake_punctuation(self):
        result = self.tool.format_text_lines(
            ["â™ª Donâ€™t â€œgoâ€ â™«"],
            self.context,
        )
        self.assertEqual(result, ["♪ Don’t “go” ♫"])

    def test_removes_only_safe_invisible_characters(self):
        result = self.tool.format_text_lines(
            ["zero\u200bwidth\ufeff soft\u00adhyphen non\u00a0breaking"],
            self.context,
        )
        self.assertEqual(result, ["zerowidth softhyphen non breaking"])

    def test_cleans_duplicate_and_punctuation_spaces_without_touching_tag_attributes(self):
        result = self.tool.format_text_lines(
            ['<font  color="#fff">Hello  ,world. What ?</font>'],
            self.context,
        )
        self.assertEqual(
            result,
            ['<font  color="#fff">Hello, world. What?</font>'],
        )

    def test_punctuation_spacing_preserves_leading_decimal_and_ambiguous_period(self):
        source = ["A pair of .50 cals.", "Still doubting me? ."]
        self.assertEqual(self.tool.format_text_lines(source, self.context), source)

    def test_repairs_only_unambiguous_italic_tag_errors(self):
        result = self.tool.format_text_lines(
            ["<i>Hello<i> <i></i> <i><i>again</i></i>"],
            self.context,
        )
        self.assertEqual(result, ["<i>Hello</i> <i>again</i>"])

    def test_cleanup_is_idempotent(self):
        source = ["â™ª  Hello ,world. <i>Again<i>"]
        once = self.tool.format_text_lines(source, self.context)
        twice = self.tool.format_text_lines(once, self.context)
        self.assertEqual(twice, once)

    def test_each_cleanup_can_be_disabled(self):
        for key in (
            "repair_corrupted_music_symbols",
            "repair_common_mojibake_punctuation",
            "remove_safe_invisible_characters",
            "remove_duplicate_spaces",
            "fix_spaces_around_punctuation",
            "repair_unambiguous_italic_tag_errors",
        ):
            self.tool.options[key] = False

        source = ["â™ª  Hello ,world. <i>Again<i>\u200b"]
        self.assertEqual(self.tool.format_text_lines(source, self.context), source)

    def test_validator_reports_without_editing(self):
        source = ['"Hello [world!!!! <i>']
        findings = self.tool.validate_common_error_text(source)

        self.assertIn("Unmatched double quote", findings)
        self.assertIn("Unmatched square bracket", findings)
        self.assertIn("Unclosed italic tag", findings)
        self.assertIn("Repeated punctuation", findings)
        self.assertEqual(source, ['"Hello [world!!!! <i>'])

    def test_formatting_run_collects_report_only_findings_without_forcing_a_write(self):
        self.tool.options["report_suspicious_text"] = True
        self.tool.validation_findings = []
        target = Path("C:/Example")
        subtitle = target / "episode.srt"
        block = SubtitleBlock(
            "1",
            "00:00:00,000 --> 00:00:01,000",
            ['"Hello [world!!!!'],
        )
        self.tool.parse_srt = Mock(return_value=[block])
        self.tool.write_srt = Mock()

        changed = self.tool.format_file(subtitle, self.context, target=target)

        self.assertFalse(changed)
        self.tool.write_srt.assert_not_called()
        issues = {item["issue"] for item in self.tool.validation_findings}
        self.assertIn("Unmatched double quote", issues)
        self.assertIn("Unmatched square bracket", issues)
        self.assertIn("Repeated punctuation", issues)

    def test_quote_validation_balances_quotes_across_subtitle_cues(self):
        self.tool.validation_findings = []
        blocks = [
            SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ['"Hello']),
            SubtitleBlock("2", "00:00:01,100 --> 00:00:02,000", ['world"']),
        ]

        self.tool.collect_file_validation_findings(
            Path("C:/Example/episode.srt"),
            Path("C:/Example"),
            blocks,
        )

        self.assertNotIn(
            "Unmatched double quote",
            {item["issue"] for item in self.tool.validation_findings},
        )

    def test_validation_option_can_be_disabled(self):
        self.tool.options["report_suspicious_text"] = False
        self.tool.validation_findings = []
        blocks = [
            SubtitleBlock("1", "00:00:00,000 --> 00:00:01,000", ['"Hello!!!!']),
        ]

        self.tool.collect_file_validation_findings(
            Path("C:/Example/episode.srt"),
            Path("C:/Example"),
            blocks,
        )

        self.assertEqual(self.tool.validation_findings, [])


if __name__ == "__main__":
    unittest.main()
