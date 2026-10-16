import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import subtitle_gui
from app.subtitle_cleanup import (
    DictionaryContext,
    SpellcheckReviewPaused,
    SubtitleCleanupTool,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GuiLauncherTests(unittest.TestCase):
    def test_gui_backup_restore_confirmation_restores_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subtitle = root / "episode.srt"
            archive_path = root / "backup_subtitles.zip"
            original = b"1\r\n00:00:01,000 --> 00:00:02,000\r\nOriginal line.\r\n"
            subtitle.write_bytes(b"changed")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("episode.srt", original)

            tool = SubtitleCleanupTool()
            tool.gui_session_state_path = root / "gui_session_state.json.gz"
            gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
                subtitle_gui.SubtitleSpellcheckGUI
            )
            gui.prepare_thread = None
            gui.review_session = None
            gui.folder_value = Mock()
            gui.folder_value.get.return_value = str(root)
            gui.tool = tool
            gui._prompt_typed_confirmation = Mock(return_value=True)
            gui.messagebox = Mock()
            gui.status_value = Mock()
            gui._refresh_backup_restore_control = Mock()

            gui._restore_subtitles_from_backup()

            self.assertEqual(subtitle.read_bytes(), original)
            self.assertTrue(archive_path.is_file())
            gui._prompt_typed_confirmation.assert_called_once()
            gui.messagebox.showinfo.assert_called_once()
            gui.messagebox.showerror.assert_not_called()
            gui.status_value.set.assert_called_with(
                "Restored 1 subtitle file(s) • Backup archives retained"
            )

    def test_scan_window_uses_scrollable_readable_workspace_on_small_displays(self):
        self.assertLessEqual(subtitle_gui.WINDOW_MIN_WIDTH, 1060)
        self.assertLessEqual(subtitle_gui.WINDOW_MIN_HEIGHT, 700)
        self.assertGreaterEqual(subtitle_gui.REVIEW_PANEL_MIN_WIDTH, 700)

        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.scan_canvas = Mock()
        gui.scan_canvas.winfo_width.return_value = 600
        gui.scan_canvas.winfo_height.return_value = 420
        gui.scan_workspace = Mock()
        gui.scan_workspace.winfo_reqwidth.return_value = 980
        gui.scan_workspace.winfo_reqheight.return_value = 760
        gui.scan_window_id = 12
        gui.scan_horizontal_scrollbar = Mock()
        gui.scan_vertical_scrollbar = Mock()

        gui._update_scan_scrollbars()

        gui.scan_canvas.itemconfigure.assert_called_once_with(
            12, width=980, height=760
        )
        gui.scan_canvas.configure.assert_called_once_with(
            scrollregion=(0, 0, 980, 760)
        )
        gui.scan_horizontal_scrollbar.grid.assert_called_once_with(
            row=1, column=0, sticky="ew"
        )
        gui.scan_vertical_scrollbar.grid.assert_called_once_with(
            row=0, column=1, sticky="ns"
        )

        gui.scan_canvas.reset_mock()
        gui.scan_horizontal_scrollbar.reset_mock()
        gui.scan_vertical_scrollbar.reset_mock()
        gui.scan_canvas.winfo_width.return_value = 1200
        gui.scan_canvas.winfo_height.return_value = 900

        gui._update_scan_scrollbars()

        gui.scan_horizontal_scrollbar.grid_remove.assert_called_once_with()
        gui.scan_vertical_scrollbar.grid_remove.assert_called_once_with()
        gui.scan_canvas.xview_moveto.assert_called_once_with(0)
        gui.scan_canvas.yview_moveto.assert_called_once_with(0)

    def test_prompt_free_option_update_validates_and_persists(self):
        options_path = Path(__file__).with_name("_gui_options_test.ini")
        try:
            tool = SubtitleCleanupTool()
            tool.options_path = options_path
            tool.set_option_value("scan_folders_recursively", False)
            tool.set_option_value("preferred_max_chars_per_line", 44)

            self.assertFalse(tool.options["scan_folders_recursively"])
            self.assertEqual(tool.options["preferred_max_chars_per_line"], 44)
            saved = options_path.read_text(encoding="utf-8")
            self.assertIn("scan_folders_recursively = False", saved)
            self.assertIn("preferred_max_chars_per_line = 44", saved)
        finally:
            options_path.unlink(missing_ok=True)

    def test_prompt_free_option_update_rejects_invalid_values(self):
        options_path = Path(__file__).with_name("_gui_options_validation_test.ini")
        try:
            tool = SubtitleCleanupTool()
            tool.options_path = options_path

            with self.assertRaisesRegex(ValueError, "true or false"):
                tool.set_option_value("scan_folders_recursively", "no")
            with self.assertRaisesRegex(ValueError, "positive whole number"):
                tool.set_option_value("preferred_max_chars_per_line", 0)
            with self.assertRaisesRegex(ValueError, "longer than 32"):
                tool.set_option_value("maximum_universe_display_name_length", 40)

            tool.set_option_value(
                "maximum_universe_display_name_length",
                40,
                allow_long_universe_names=True,
            )
            self.assertEqual(tool.options["maximum_universe_display_name_length"], 40)
        finally:
            options_path.unlink(missing_ok=True)

    def test_gui_option_categories_cover_every_runtime_option_once(self):
        keys = [key for _title, group in subtitle_gui.OPTION_GROUPS for key in group]

        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(subtitle_gui.DEFAULT_OPTIONS))

    def test_option_rows_alternate_white_and_light_gray(self):
        self.assertEqual(
            [subtitle_gui.option_row_color(index) for index in range(4)],
            ["#ffffff", "#f2f3f5", "#ffffff", "#f2f3f5"],
        )

    def test_option_toggle_uses_green_for_on_and_red_for_off(self):
        self.assertEqual(subtitle_gui.option_toggle_color(True), "#2f8f5b")
        self.assertEqual(subtitle_gui.option_toggle_color(False), "#b84a4a")

    def test_option_toggle_adds_non_color_check_and_x_state_cues(self):
        self.assertEqual(subtitle_gui.option_toggle_symbol(True), "✓")
        self.assertEqual(subtitle_gui.option_toggle_symbol(False), "×")

        toggle = subtitle_gui.OptionToggle.__new__(subtitle_gui.OptionToggle)
        toggle.canvas = Mock()
        toggle.palette = subtitle_gui.resolve_theme("Dark")

        toggle.value = True
        toggle._draw()
        toggle.canvas.create_text.assert_called_once_with(
            44,
            14,
            text="✓",
            fill=toggle.palette["toggle_symbol"],
            font=("TkDefaultFont", 9, "bold"),
        )

        toggle.canvas.reset_mock()
        toggle.value = False
        toggle._draw()
        toggle.canvas.create_text.assert_called_once_with(
            12,
            14,
            text="×",
            fill=toggle.palette["toggle_symbol"],
            font=("TkDefaultFont", 9, "bold"),
        )

    def test_ocean_is_the_default_registered_theme(self):
        palette = subtitle_gui.resolve_theme()

        self.assertEqual(subtitle_gui.DEFAULT_THEME_NAME, "Ocean")
        self.assertIn("Ocean", subtitle_gui.BUILTIN_THEMES)
        self.assertEqual(palette, subtitle_gui.BUILTIN_THEMES["Ocean"])
        self.assertIsNot(palette, subtitle_gui.BUILTIN_THEMES["Ocean"])

    def test_ocean_is_active_by_default_and_dark_remains_selectable(self):
        dark = subtitle_gui.resolve_theme("Dark")

        self.assertEqual(subtitle_gui.ACTIVE_THEME_NAME, "Ocean")
        self.assertIn("Dark", subtitle_gui.BUILTIN_THEMES)
        self.assertNotEqual(
            dark["surface"],
            subtitle_gui.BUILTIN_THEMES["Ocean"]["surface"],
        )
        self.assertNotEqual(dark["row_white"], dark["row_light"])

    def test_theme_preferences_default_custom_to_ocean_and_round_trip(self):
        preferences_path = Path(__file__).with_name("_gui_theme_test.json")
        try:
            selected, custom = subtitle_gui.load_theme_preferences(
                preferences_path
            )
            self.assertEqual(selected, "Ocean")
            self.assertEqual(custom, subtitle_gui.OCEAN_THEME)
            self.assertIsNot(custom, subtitle_gui.OCEAN_THEME)

            custom["accent"] = "#123456"
            text = subtitle_gui.theme_preferences_text("Custom", custom)
            preferences_path.write_text(text, encoding="utf-8")

            selected, loaded = subtitle_gui.load_theme_preferences(
                preferences_path
            )
            self.assertEqual(selected, "Custom")
            self.assertEqual(loaded["accent"], "#123456")
            self.assertEqual(set(loaded), set(subtitle_gui.OCEAN_THEME))
            self.assertEqual(json.loads(text)["selected"], "Custom")
        finally:
            preferences_path.unlink(missing_ok=True)

    def test_custom_theme_field_descriptions_cover_every_palette_color(self):
        described = {key for key, _label, _description in subtitle_gui.THEME_COLOR_FIELDS}

        self.assertEqual(described, set(subtitle_gui.OCEAN_THEME))
        self.assertTrue(
            all(label and description for _key, label, description in subtitle_gui.THEME_COLOR_FIELDS)
        )

    def test_gui_theme_preferences_use_shared_atomic_runtime_storage(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui.theme_settings_path = Path("C:/Example/dictionaries/gui_theme.json")
        custom = dict(subtitle_gui.OCEAN_THEME)
        custom["accent"] = "#123456"

        gui._save_theme_preferences("Custom", custom)

        path, text = gui.tool.atomic_write_text.call_args.args
        self.assertEqual(path, gui.theme_settings_path)
        saved = json.loads(text)
        self.assertEqual(saved["selected"], "Custom")
        self.assertEqual(saved["custom"]["accent"], "#123456")
        self.assertEqual(gui.saved_custom_theme["accent"], "#123456")

    def test_custom_theme_can_reset_from_ocean_or_dark_without_aliasing(self):
        ocean = subtitle_gui.theme_seed("Ocean")
        dark = subtitle_gui.theme_seed("Dark")

        self.assertEqual(ocean, subtitle_gui.OCEAN_THEME)
        self.assertEqual(dark, subtitle_gui.DARK_THEME)
        self.assertIsNot(ocean, subtitle_gui.OCEAN_THEME)
        self.assertIsNot(dark, subtitle_gui.DARK_THEME)
        with self.assertRaises(ValueError):
            subtitle_gui.theme_seed("Custom")

    def test_theme_restart_detection_compares_selection_and_custom_colors(self):
        ocean = dict(subtitle_gui.OCEAN_THEME)
        custom = dict(ocean)

        self.assertFalse(
            subtitle_gui.theme_change_requires_restart(
                "Ocean", ocean, "Ocean", custom
            )
        )
        self.assertTrue(
            subtitle_gui.theme_change_requires_restart(
                "Ocean", ocean, "Dark", custom
            )
        )
        self.assertFalse(
            subtitle_gui.theme_change_requires_restart(
                "Custom", custom, "Custom", custom
            )
        )
        custom["accent"] = "#123456"
        self.assertTrue(
            subtitle_gui.theme_change_requires_restart(
                "Custom", ocean, "Custom", custom
            )
        )

    def test_cross_platform_restart_spawns_python_or_frozen_arguments(self):
        process_launcher = Mock()

        subtitle_gui.restart_current_process(
            executable="C:/Python/pythonw.exe",
            argv=["subtitle_gui.py", "--version"],
            frozen=False,
            process_launcher=process_launcher,
        )
        process_launcher.assert_called_once_with(
            ["C:/Python/pythonw.exe", "subtitle_gui.py", "--version"],
            close_fds=True,
        )

        process_launcher.reset_mock()
        subtitle_gui.restart_current_process(
            executable="C:/App/SubtitleUniverseSpellcheck.exe",
            argv=["C:/App/SubtitleUniverseSpellcheck.exe"],
            frozen=True,
            process_launcher=process_launcher,
        )
        process_launcher.assert_called_once_with(
            ["C:/App/SubtitleUniverseSpellcheck.exe"],
            close_fds=True,
        )

    def test_theme_restart_checkpoints_retained_review_before_process_replace(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.review_session = object()
        gui.editing_cue = False
        gui.scan_paused = True
        gui._checkpoint_review = Mock(return_value=True)
        gui.messagebox = Mock()
        gui.status_value = Mock()
        gui.root = Mock()

        with patch("app.subtitle_gui.restart_current_process") as restart:
            gui._restart_for_theme_change()

        gui._checkpoint_review.assert_called_once_with(paused=True)
        restart.assert_called_once_with()
        gui.root.destroy.assert_called_once_with()

    def test_theme_restart_keeps_current_window_when_replacement_launch_fails(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.review_session = None
        gui.editing_cue = False
        gui.messagebox = Mock()
        gui.status_value = Mock()
        gui.root = Mock()

        with patch(
            "app.subtitle_gui.restart_current_process",
            side_effect=OSError("replacement could not start"),
        ):
            gui._restart_for_theme_change()

        gui.root.destroy.assert_not_called()
        gui.messagebox.showerror.assert_called_once()
        gui.status_value.set.assert_called_once_with(
            "Theme saved • Close and reopen the application to apply it"
        )

    def test_theme_navigation_guard_can_cancel_discard_or_save_draft(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.active_navigation_key = "themes"
        gui.theme_draft_is_dirty = Mock(return_value=True)
        gui.save_theme_draft = Mock(return_value=True)
        gui.messagebox = Mock()

        gui.messagebox.askyesnocancel.return_value = None
        self.assertFalse(gui._confirm_theme_navigation("about"))
        gui.save_theme_draft.assert_not_called()

        gui.messagebox.askyesnocancel.return_value = False
        discard_save = gui.save_theme_draft
        self.assertTrue(gui._confirm_theme_navigation("about"))
        discard_save.assert_not_called()
        self.assertIsNone(gui.theme_draft_is_dirty)
        self.assertIsNone(gui.save_theme_draft)

        gui.theme_draft_is_dirty = Mock(return_value=True)
        save_action = Mock(return_value=True)
        gui.save_theme_draft = save_action
        gui.messagebox.askyesnocancel.return_value = True
        self.assertTrue(gui._confirm_theme_navigation("options"))
        save_action.assert_called_once_with()
        self.assertIsNone(gui.theme_draft_is_dirty)
        self.assertIsNone(gui.save_theme_draft)

    def test_theme_navigation_guard_stays_when_draft_save_fails(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.active_navigation_key = "themes"
        gui.theme_draft_is_dirty = Mock(return_value=True)
        gui.save_theme_draft = Mock(return_value=False)
        gui.messagebox = Mock()
        gui.messagebox.askyesnocancel.return_value = True

        self.assertFalse(gui._confirm_theme_navigation("recent"))
        self.assertIsNotNone(gui.theme_draft_is_dirty)
        self.assertIsNotNone(gui.save_theme_draft)

    def test_custom_theme_overrides_valid_colors_and_inherits_ocean_defaults(self):
        palette = subtitle_gui.resolve_theme(
            "Custom",
            {"nav": "#010203", "row_light": "#aabbcc"},
        )

        self.assertEqual(palette["nav"], "#010203")
        self.assertEqual(palette["row_light"], "#aabbcc")
        self.assertEqual(
            palette["row_white"],
            subtitle_gui.BUILTIN_THEMES["Ocean"]["row_white"],
        )
        with self.assertRaises(ValueError):
            subtitle_gui.resolve_theme("Custom", {"nav": "blue"})

    def test_dictionary_and_option_stripes_share_theme_row_colors(self):
        palette = subtitle_gui.resolve_theme()
        dictionary_colors = subtitle_gui.dictionary_row_colors(palette)

        self.assertEqual(dictionary_colors["dictionary_even"], palette["row_light"])
        self.assertEqual(dictionary_colors["dictionary_odd"], palette["row_white"])
        self.assertEqual(subtitle_gui.option_row_color(0, palette), palette["row_white"])
        self.assertEqual(subtitle_gui.option_row_color(1, palette), palette["row_light"])

    def test_themeable_ttk_engine_prefers_clam_over_native_vista(self):
        self.assertEqual(
            subtitle_gui.preferred_ttk_theme(("vista", "default", "clam")),
            "clam",
        )

    def test_ttk_style_layer_covers_remaining_application_controls(self):
        palette = subtitle_gui.resolve_theme("Dark")
        configurations, mappings = subtitle_gui.ttk_style_layer(palette)

        for style_name in (
            "TButton",
            "TEntry",
            "TCombobox",
            "Treeview",
            "Treeview.Heading",
            "Vertical.TScrollbar",
            "Horizontal.TScrollbar",
        ):
            self.assertIn(style_name, configurations)
        self.assertEqual(configurations["TEntry"]["fieldbackground"], palette["card"])
        self.assertEqual(configurations["Treeview"]["background"], palette["card"])
        self.assertEqual(
            configurations["CardTitle.TLabel"]["background"], palette["card"]
        )
        self.assertNotIn("card_title", palette)
        self.assertEqual(
            dict(mappings["TButton"]["background"])["active"],
            palette["nav_active"],
        )

    def test_classic_listbox_colors_come_from_active_palette(self):
        palette = subtitle_gui.resolve_theme("Dark")
        settings = subtitle_gui.listbox_theme_options(palette)

        self.assertEqual(settings["background"], palette["card"])
        self.assertEqual(settings["foreground"], palette["text"])
        self.assertEqual(settings["selectbackground"], palette["nav_active"])
        self.assertEqual(settings["selectforeground"], palette["nav_text"])

    def test_option_tooltips_have_one_labeled_fixed_column(self):
        self.assertEqual(subtitle_gui.OPTION_TOOLTIP_HEADING, "Tooltips")
        self.assertEqual(subtitle_gui.OPTION_SWITCH_COLUMN, 0)
        self.assertEqual(subtitle_gui.OPTION_TOOLTIP_COLUMN, 2)
        self.assertEqual(subtitle_gui.OPTION_NUMERIC_CONTROL_COLUMN, 3)
        self.assertEqual(
            subtitle_gui.OPTION_RIGHT_ZONE_WIDTH,
            subtitle_gui.OPTION_TOOLTIP_COLUMN_WIDTH
            + subtitle_gui.OPTION_NUMERIC_CONTROL_COLUMN_WIDTH,
        )
        self.assertEqual(
            subtitle_gui.option_tooltip_position(),
            {
                "x": subtitle_gui.OPTION_TOOLTIP_COLUMN_WIDTH // 2,
                "rely": 0.5,
                "anchor": "center",
            },
        )

    def test_gui_flush_session_log_confirms_and_uses_engine_operation(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = True
        gui.status_value = Mock()

        gui._flush_session_log_from_gui()

        gui.tool.clear_session_log.assert_called_once_with()
        gui.messagebox.showinfo.assert_called_once()
        self.assertIn("flushed", gui.status_value.set.call_args.args[0].lower())

    def test_gui_flush_session_log_cancel_leaves_log_unchanged(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = False
        gui.status_value = Mock()

        gui._flush_session_log_from_gui()

        gui.tool.clear_session_log.assert_not_called()

    def test_gui_boolean_option_saves_immediately_and_reverts_on_error(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock(options={"scan_folders_recursively": True})
        gui.status_value = Mock()
        gui.messagebox = Mock()
        variable = Mock()
        variable.get.return_value = False

        gui._save_gui_boolean_option("scan_folders_recursively", variable)

        gui.tool.set_option_value.assert_called_once_with(
            "scan_folders_recursively", False
        )
        gui.tool.set_option_value.side_effect = OSError("disk unavailable")
        gui._save_gui_boolean_option("scan_folders_recursively", variable)
        variable.set.assert_called_once_with(True)
        gui.messagebox.showerror.assert_called_once()

    def test_gui_long_universe_display_limit_requires_confirmation(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock(options={"maximum_universe_display_name_length": 24})
        gui.status_value = Mock()
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = True
        variable = Mock()
        variable.get.return_value = "40"

        gui._save_gui_integer_option(
            "maximum_universe_display_name_length", variable
        )

        gui.messagebox.askyesno.assert_called_once()
        gui.tool.set_option_value.assert_called_once_with(
            "maximum_universe_display_name_length",
            40,
            allow_long_universe_names=True,
        )

    def test_formatting_review_prepares_changes_and_validation_without_writing(self):
        subtitle_path = Path(__file__).with_name("_gui_formatting_review_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\ni am here.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nWait [what!\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(language="american")
            session = tool.create_formatting_review(
                [subtitle_path], subtitle_path.parent, context
            )

            tool.resume_formatting_review(session)

            self.assertEqual(session.mode, "formatting")
            self.assertEqual(session.prepared_blocks[0][0].text_lines, ["I am here."])
            self.assertEqual(tool.review_changed_files(session), (subtitle_path,))
            self.assertTrue(
                any(
                    finding["issue"] == "Unmatched square bracket"
                    for finding in session.validation_findings
                )
            )
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_formatting_review_pauses_and_resumes_from_retained_cue(self):
        subtitle_path = Path(__file__).with_name("_gui_formatting_pause_test.srt")
        try:
            subtitle_path.write_text(
                "1\n00:00:01,000 --> 00:00:02,000\ni am here.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\ni am back.\n",
                encoding="utf-8",
            )
            tool = SubtitleCleanupTool()
            tool.options["adjust_subtitle_line_count"] = False
            session = tool.create_formatting_review(
                [subtitle_path],
                subtitle_path.parent,
                DictionaryContext(language="american"),
            )
            pause = {"requested": False}

            def progress(*_values):
                pause["requested"] = True

            with self.assertRaises(SpellcheckReviewPaused):
                tool.resume_formatting_review(
                    session,
                    progress_callback=progress,
                    pause_requested=lambda: pause["requested"],
                )

            self.assertEqual(session.subtitle_index, 1)
            pause["requested"] = False
            tool.resume_formatting_review(
                session, pause_requested=lambda: pause["requested"]
            )
            self.assertEqual(session.file_index, 1)
            self.assertEqual(
                [block.text_lines for block in session.prepared_blocks[0]],
                [["I am here."], ["I am back."]],
            )
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_formatting_review_recovery_retains_mode_changes_and_findings(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_formatting_recovery_test.srt"
        journal_path = root / "_gui_formatting_recovery_state.json.gz"
        try:
            subtitle_path.write_text(
                "1\n00:00:01,000 --> 00:00:02,000\ni wait [here.\n",
                encoding="utf-8",
            )
            tool = SubtitleCleanupTool()
            tool.gui_session_state_path = journal_path
            tool.options["adjust_subtitle_line_count"] = False
            tool.options["capitalization_mode"] = "subtitle"
            context = DictionaryContext(language="american")
            session = tool.create_formatting_review([subtitle_path], root, context)
            tool.resume_formatting_review(session)
            session.options_snapshot["capitalization_mode"] = "all_caps"
            tool.save_gui_review_session(session)
            tool.options["capitalization_mode"] = "ask_always"

            with patch.object(tool, "load_dictionary_context", return_value=context):
                restored = tool.load_gui_review_session()

            self.assertEqual(restored.mode, "formatting")
            self.assertEqual(restored.options_snapshot["capitalization_mode"], "all_caps")
            self.assertEqual(tool.options["capitalization_mode"], "all_caps")
            self.assertEqual(restored.prepared_blocks[0][0].text_lines, ["I wait [here."])
            self.assertEqual(
                restored.validation_findings[0]["issue"],
                "Unmatched square bracket",
            )
            self.assertEqual(tool.review_changed_files(restored), (subtitle_path,))
        finally:
            subtitle_path.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)

    def test_formatting_progress_uses_the_complete_progress_range(self):
        self.assertEqual(
            subtitle_gui.scan_progress_percent("Formatting", 1, 2, 2, 2),
            50,
        )
        self.assertEqual(
            subtitle_gui.scan_progress_percent("Formatting", 2, 2, 2, 2),
            100,
        )

    def test_recent_additions_category_width_fits_longest_label(self):
        longest = max(len(value) for value in subtitle_gui.RECENT_ADDITION_CATEGORIES)

        self.assertGreaterEqual(
            subtitle_gui.RECENT_ADDITION_CATEGORY_WIDTH,
            longest + 2,
        )

    def test_dictionary_rows_alternate_between_two_tags(self):
        self.assertEqual(
            [subtitle_gui.dictionary_row_tag(index) for index in range(4)],
            ["dictionary_even", "dictionary_odd", "dictionary_even", "dictionary_odd"],
        )

    def test_horizontal_scrollbar_is_needed_only_for_partial_view(self):
        self.assertFalse(subtitle_gui.horizontal_scroll_needed("0.0", "1.0"))
        self.assertTrue(subtitle_gui.horizontal_scroll_needed("0.0", "0.7"))
        self.assertTrue(subtitle_gui.horizontal_scroll_needed("0.2", "1.0"))

    def test_dictionary_cell_text_uses_ellipsis_only_when_clipped(self):
        measure = lambda value: len(value) * 10

        self.assertEqual(
            subtitle_gui.elide_cell_text("short", 80, measure),
            "short",
        )
        clipped = subtitle_gui.elide_cell_text(
            "a much longer dictionary value", 80, measure
        )
        self.assertTrue(clipped.endswith("…"))
        self.assertLessEqual(measure(clipped), 68)
        self.assertNotEqual(clipped, "a much longer dictionary value")

    def test_substitution_columns_preserve_manual_widths(self):
        self.assertFalse(subtitle_gui.dictionary_column_should_stretch("substitutions"))
        self.assertTrue(subtitle_gui.dictionary_column_should_stretch("words"))

    def test_new_dictionary_view_starts_with_window_fitting_columns(self):
        self.assertEqual(
            subtitle_gui.initial_dictionary_column_widths("substitutions", 1000),
            (497, 497),
        )
        self.assertEqual(
            subtitle_gui.initial_dictionary_column_widths("words", 1000),
            (994, None),
        )

    def test_base_language_help_explains_dialect_and_oxford_variants(self):
        help_text = subtitle_gui.BASE_LANGUAGE_HELP

        for example in (
            "color",
            "colour",
            "center",
            "centre",
            "organise",
            "organize",
            "standard British",
            "Oxford British",
        ):
            self.assertIn(example, help_text)

    def test_standard_universe_help_points_to_universe_spellcheck(self):
        self.assertIn("Standard spellcheck", subtitle_gui.STANDARD_UNIVERSE_HELP)
        self.assertIn("Universe spellcheck", subtitle_gui.STANDARD_UNIVERSE_HELP)
        self.assertIn("left pane", subtitle_gui.STANDARD_UNIVERSE_HELP)

    def test_acronym_help_explains_word_conflicts_and_contextual_time_markers(self):
        help_text = subtitle_gui.ACRONYM_HELP

        self.assertIn("already a word", help_text)
        self.assertIn("AM", help_text)
        self.assertIn("PM", help_text)
        self.assertIn("time", help_text)

    def test_gui_acronym_word_conflict_requires_confirmation(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui.tool.acronym_word_conflicts.return_value = [
            "American English Base Dictionary"
        ]
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = False
        context = DictionaryContext(language="american", base_words={"us"})

        confirmed = gui._confirm_acronym_addition("US", context=context)

        self.assertFalse(confirmed)
        gui.messagebox.askyesno.assert_called_once()
        self.assertIn(
            "American English Base Dictionary",
            gui.messagebox.askyesno.call_args.args[1],
        )

    def test_gui_word_acronym_conflict_requires_confirmation(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui.tool.word_acronym_conflicts.return_value = [
            "American English User Dictionary"
        ]
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = False
        context = DictionaryContext(
            language="american", user_acronyms={"XYZ"}
        )

        confirmed = gui._confirm_word_addition("xyz", context=context)

        self.assertFalse(confirmed)
        gui.messagebox.askyesno.assert_called_once()
        self.assertIn(
            "American English User Dictionary",
            gui.messagebox.askyesno.call_args.args[1],
        )

    def test_recent_destination_options_exclude_current_location(self):
        user_event = {
            "target": "user",
            "base_language": "american",
        }
        options = subtitle_gui.recent_destination_options(
            user_event, ["Stargate", "Star Trek"]
        )
        self.assertEqual(
            options,
            [
                ("User — British English", "user", None, "british"),
                ("Universe — Star Trek", "universe", "Star Trek", None),
                ("Universe — Stargate", "universe", "Stargate", None),
            ],
        )

    def test_recent_destination_groups_separate_languages_and_universes(self):
        groups = subtitle_gui.recent_destination_groups(
            {"target": "user", "base_language": "american"},
            ["Stargate", "Star Trek"],
        )

        self.assertEqual(
            groups["user"],
            [("British English", "user", None, "british")],
        )
        self.assertEqual(
            groups["universe"],
            [
                ("Star Trek", "universe", "Star Trek", None),
                ("Stargate", "universe", "Stargate", None),
            ],
        )

    def test_batch_move_destinations_exclude_every_selected_current_location(self):
        groups = subtitle_gui.recent_destination_groups(
            [
                {"target": "user", "base_language": "american"},
                {"target": "universe", "universe": "Stargate"},
            ],
            ["Stargate", "Star Trek"],
        )

        self.assertEqual(
            groups["user"],
            [("British English", "user", None, "british")],
        )
        self.assertEqual(
            groups["universe"],
            [("Star Trek", "universe", "Star Trek", None)],
        )

    def test_table_selection_entries_returns_all_control_or_shift_selections(self):
        entries = ["one", "two", "three", "four"]

        selected = subtitle_gui.table_selection_entries(
            ("0", "2", "3"), entries
        )

        self.assertEqual(selected, ["one", "three", "four"])

    def test_edit_rejects_multiple_selected_entries_with_explanation(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.messagebox = Mock()

        selected = gui._single_selected_entry(["one", "two"])

        self.assertIsNone(selected)
        gui.messagebox.showinfo.assert_called_once_with(
            "Select one entry",
            "Edit works with one entry at a time. Move and Remove support multiple selections.",
        )
    def test_centered_child_position_uses_parent_center_and_screen_edges(self):
        self.assertEqual(
            subtitle_gui.centered_child_position(
                (100, 80, 1200, 800), (700, 300), (1920, 1080)
            ),
            (350, 330),
        )
        self.assertEqual(
            subtitle_gui.centered_child_position(
                (0, 0, 400, 300), (700, 500), (1920, 1080)
            ),
            (0, 0),
        )
        self.assertEqual(
            subtitle_gui.centered_child_position(
                (2000, 100, 1000, 700), (600, 300), (1920, 1080)
            ),
            (2200, 300),
        )

    def test_windows_app_identity_is_set_before_tk_for_taskbar_icon(self):
        setter = Mock()

        configured = subtitle_gui.configure_windows_app_identity(
            platform="win32", setter=setter
        )

        self.assertTrue(configured)
        setter.assert_called_once_with(subtitle_gui.WINDOWS_APP_ID)
        self.assertFalse(
            subtitle_gui.configure_windows_app_identity(
                platform="linux", setter=setter
            )
        )

    def test_application_icon_is_applied_and_retained_by_the_window(self):
        window = Mock()
        image = object()
        image_factory = Mock(return_value=image)

        applied = subtitle_gui.apply_application_window_icon(
            window,
            icon_path=PROJECT_ROOT / "assets" / "subtitle-universe-quill.png",
            image_factory=image_factory,
        )

        self.assertTrue(applied)
        image_factory.assert_called_once_with(
            file=str(PROJECT_ROOT / "assets" / "subtitle-universe-quill.png")
        )
        window.iconphoto.assert_called_once_with(True, image)
        self.assertIs(window._subtitle_universe_icon, image)

    def test_application_icon_missing_is_nonfatal(self):
        window = Mock()
        applied = subtitle_gui.apply_application_window_icon(
            window,
            icon_path=PROJECT_ROOT / "assets" / "missing.png",
            image_factory=Mock(),
        )

        self.assertFalse(applied)
        window.iconphoto.assert_not_called()

    def test_dictionary_prompt_uses_one_two_field_form_for_substitutions(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui._prompt_text_fields = Mock(return_value=("long find phrase", "replacement"))

        result = gui._prompt_maintenance_values(
            "substitutions",
            title="Add substitution",
            entry="long find phrase",
            output="replacement",
        )

        self.assertEqual(result, ("long find phrase", "replacement"))
        gui._prompt_text_fields.assert_called_once_with(
            "Add substitution",
            (
                ("Find word or phrase", "long find phrase"),
                ("Replace with", "replacement"),
            ),
        )

    def test_about_project_link_uses_public_github_page(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.messagebox = Mock()
        gui.status_value = Mock()
        with patch("app.subtitle_gui.webbrowser.open", return_value=True) as opened:
            gui._open_project_page()

        opened.assert_called_once_with(subtitle_gui.PROJECT_URL, new=2)
        gui.status_value.set.assert_called_once()

    def test_about_scowl_link_uses_the_bundled_release_tag(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.messagebox = Mock()
        gui.status_value = Mock()
        with patch("app.subtitle_gui.webbrowser.open", return_value=True) as opened:
            gui._open_scowl_page()

        self.assertEqual(
            subtitle_gui.SCOWL_URL,
            "https://github.com/en-wl/wordlist/tree/rel-2026.02.25",
        )
        opened.assert_called_once_with(subtitle_gui.SCOWL_URL, new=2)
        gui.status_value.set.assert_called_once()

    def test_scan_navigation_restores_main_scan_workspace(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.maintenance_workspace = Mock()
        gui.scan_view = Mock()
        gui.scan_mode = Mock()
        gui.universe_combo = Mock()
        gui.universe_value = Mock()
        gui.status_value = Mock()
        gui._activate_navigation = Mock()
        gui._refresh_context = Mock()

        gui._select_mode("universe")

        gui.maintenance_workspace.grid_remove.assert_called_once_with()
        gui.scan_view.grid.assert_called_once_with()
        gui.scan_mode.set.assert_called_once_with("universe")
        gui._activate_navigation.assert_called_once_with("universe")
        gui.universe_combo.configure.assert_called_once_with(state="readonly")
        gui._refresh_context.assert_called_once_with()

    def test_scan_navigation_replaces_maintenance_status_for_every_scan_mode(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.maintenance_workspace = Mock()
        gui.scan_view = Mock()
        gui.scan_mode = Mock()
        gui.universe_combo = Mock()
        gui.universe_value = Mock()
        gui.status_value = Mock()
        gui._activate_navigation = Mock()
        gui._refresh_context = Mock()

        for mode in ("formatting", "standard", "universe"):
            with self.subTest(mode=mode):
                gui.status_value.reset_mock()

                gui._select_mode(mode)

                gui.status_value.set.assert_called_once()
                status = gui.status_value.set.call_args.args[0]
                self.assertIn("Start scan", status)
                self.assertNotIn("Maintenance", status)

    def test_universe_help_icon_is_visible_only_for_standard_spellcheck(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.maintenance_workspace = Mock()
        gui.scan_view = Mock()
        gui.scan_mode = Mock()
        gui.universe_combo = Mock()
        gui.universe_value = Mock()
        gui.universe_help_icon = Mock()
        gui.status_value = Mock()
        gui._activate_navigation = Mock()
        gui._refresh_context = Mock()

        gui._select_mode("standard")
        gui.universe_help_icon.pack.assert_called_once_with(
            side="left", padx=(5, 0)
        )

        gui.universe_help_icon.reset_mock()
        gui._select_mode("formatting")
        gui.universe_help_icon.pack_forget.assert_called_once_with()

        gui.universe_help_icon.reset_mock()
        gui._select_mode("universe")
        gui.universe_help_icon.pack_forget.assert_called_once_with()

    def test_language_selector_uses_full_labels_and_stable_internal_keys(self):
        self.assertEqual(
            subtitle_gui.language_display_name("american"), "American English"
        )
        self.assertEqual(
            subtitle_gui.language_display_name("british"), "British English"
        )
        self.assertEqual(
            subtitle_gui.language_key("American English"), "american"
        )
        self.assertEqual(
            subtitle_gui.language_key("British English"), "british"
        )

    def test_scan_universe_selector_pins_add_action_before_no_universe(self):
        self.assertEqual(
            subtitle_gui.universe_selector_values(("Zulu", "Alpha")),
            (subtitle_gui.ADD_UNIVERSE_LABEL, "No universe", "Alpha", "Zulu"),
        )

    def test_auto_hiding_scrollbar_is_visible_only_for_overflow(self):
        scrollbar = Mock()

        subtitle_gui.update_auto_hiding_scrollbar(scrollbar, "0.0", "0.6")
        scrollbar.set.assert_called_once_with("0.0", "0.6")
        scrollbar.grid.assert_called_once_with()

        scrollbar.reset_mock()
        subtitle_gui.update_auto_hiding_scrollbar(scrollbar, "0.0", "1.0")
        scrollbar.set.assert_called_once_with("0.0", "1.0")
        scrollbar.grid_remove.assert_called_once_with()

    def test_scan_selector_can_create_and_select_a_universe(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui._prompt_text_fields = Mock(return_value=("New Universe",))
        gui._refresh_universes = Mock()
        gui._refresh_context = Mock()
        gui.universe_value = Mock()
        gui._selected_universe = "No universe"
        gui.status_value = Mock()
        gui.messagebox = Mock()

        created = gui._create_universe_from_scan_selector()

        self.assertEqual(created, "New Universe")
        gui.tool.create_universe_named.assert_called_once_with("New Universe")
        gui._refresh_universes.assert_called_once_with()
        gui.universe_value.set.assert_called_once_with("New Universe")
        gui._refresh_context.assert_called_once_with()
        self.assertEqual(gui._selected_universe, "New Universe")

    def test_gui_user_maintenance_add_uses_selected_language_and_shared_engine(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.language_value = Mock()
        gui.language_value.get.return_value = "American English"
        gui.tool = Mock()
        gui.tool.user_dir = Path("C:/Example/dictionaries/user")
        gui.tool.word_acronym_conflicts_for_location.return_value = []
        gui.tool.add_word_or_name_entries.return_value = ["Qelari"]

        changed = gui._add_maintenance_entry(
            "user", "names", None, "Qelari"
        )

        self.assertTrue(changed)
        gui.tool.add_word_or_name_entries.assert_called_once_with(
            Path("C:/Example/dictionaries/user/american_names.txt"),
            "user",
            "names",
            None,
            ["Qelari"],
        )

    def test_gui_universe_acronym_maintenance_uses_acronym_file(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.language_value = Mock()
        gui.language_value.get.return_value = "American English"
        gui.tool = Mock()
        gui.tool.universe_dir = Path("C:/Example/dictionaries/universes")
        gui.tool.validate_acronym_entry.return_value = "MALP"
        gui.tool.acronym_word_conflicts_for_location.return_value = []
        gui.tool.add_word_or_name_entries.return_value = ["MALP"]

        changed = gui._add_maintenance_entry(
            "universe", "acronyms", "Stargate SG-1", "MALP"
        )

        self.assertTrue(changed)
        gui.tool.add_word_or_name_entries.assert_called_once_with(
            Path(
                "C:/Example/dictionaries/universes/Stargate SG-1/acronyms.txt"
            ),
            "universe",
            "acronyms",
            "Stargate SG-1",
            ["MALP"],
        )

    def test_gui_universe_substitution_maintenance_uses_shared_engine(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.language_value = Mock()
        gui.language_value.get.return_value = "British English"
        gui.tool = Mock()
        gui.tool.universe_dir = Path("C:/Example/dictionaries/universes")
        gui.tool.set_maintenance_substitution.return_value = True

        changed = gui._add_maintenance_entry(
            "universe", "substitutions", "Stargate", "goauld", "Goa'uld"
        )

        self.assertTrue(changed)
        gui.tool.set_maintenance_substitution.assert_called_once_with(
            Path("C:/Example/dictionaries/universes/Stargate/substitutions.tsv"),
            "universe",
            "Stargate",
            "goauld",
            "Goa'uld",
        )

    def test_gui_maintenance_move_dispatches_selected_source_and_destination(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.language_value = Mock()
        gui.language_value.get.return_value = "American English"
        gui.tool = Mock()
        gui.tool.word_acronym_conflicts_for_location.return_value = []
        gui.tool.move_dictionary_word_to.return_value = True

        moved = gui._move_maintenance_entry(
            "user",
            "names",
            None,
            "Harriman",
            source_language="american",
            destination_target="universe",
            destination_universe="Stargate",
        )

        self.assertTrue(moved)
        gui.tool.move_dictionary_word_to.assert_called_once_with(
            {
                "target": "user",
                "universe": None,
                "base_language": "american",
                "list": "names",
                "word": "Harriman",
            },
            "universe",
            "Stargate",
            language=None,
        )

    def test_scan_navigation_button_calls_mode_selection(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tk = Mock()
        button = Mock()
        gui.tk.Button.return_value = button
        gui.nav_buttons = {}
        gui._select_mode = Mock()
        gui._show_planned_feature = Mock()

        gui._nav_button(None, "standard", "Standard spellcheck")
        command = gui.tk.Button.call_args.kwargs["command"]
        command()

        gui._select_mode.assert_called_once_with("standard")
        gui._show_planned_feature.assert_not_called()

    def test_default_launch_opens_gui(self):
        gui = Mock()
        gui.run.return_value = None
        gui_factory = Mock(return_value=gui)
        cli_runner = Mock()

        result = subtitle_gui.launch_application(
            [], gui_factory=gui_factory, cli_runner=cli_runner
        )

        self.assertEqual(result, 0)
        gui_factory.assert_called_once_with()
        gui.run.assert_called_once_with()
        cli_runner.assert_not_called()

    def test_default_gui_detaches_frozen_console_but_cli_does_not(self):
        gui = Mock()
        gui_factory = Mock(return_value=gui)
        cli_runner = Mock()
        console_detacher = Mock()

        subtitle_gui.launch_application(
            [],
            gui_factory=gui_factory,
            cli_runner=cli_runner,
            console_detacher=console_detacher,
        )
        console_detacher.assert_called_once_with()

        console_detacher.reset_mock()
        subtitle_gui.launch_application(
            ["--cli"],
            gui_factory=gui_factory,
            cli_runner=cli_runner,
            console_detacher=console_detacher,
        )
        console_detacher.assert_not_called()

    def test_gui_console_detach_is_limited_to_frozen_windows_builds(self):
        free_console = Mock(return_value=1)

        self.assertTrue(
            subtitle_gui.detach_frozen_gui_console(
                platform_name="win32",
                frozen=True,
                free_console=free_console,
            )
        )
        free_console.assert_called_once_with()

        free_console.reset_mock()
        self.assertFalse(
            subtitle_gui.detach_frozen_gui_console(
                platform_name="linux",
                frozen=True,
                free_console=free_console,
            )
        )
        self.assertFalse(
            subtitle_gui.detach_frozen_gui_console(
                platform_name="win32",
                frozen=False,
                free_console=free_console,
            )
        )
        free_console.assert_not_called()

    def test_cli_argument_routes_to_existing_console_application(self):
        gui_factory = Mock()
        cli_runner = Mock(return_value=None)

        result = subtitle_gui.launch_application(
            ["--cli"], gui_factory=gui_factory, cli_runner=cli_runner
        )

        self.assertEqual(result, 0)
        cli_runner.assert_called_once_with()
        gui_factory.assert_not_called()

    def test_version_argument_does_not_initialize_an_interface(self):
        gui_factory = Mock()
        cli_runner = Mock()
        output = io.StringIO()

        with patch("sys.stdout", output):
            result = subtitle_gui.launch_application(
                ["--version"], gui_factory=gui_factory, cli_runner=cli_runner
            )

        self.assertEqual(result, 0)
        self.assertIn("Subtitle Universe Spellcheck", output.getvalue())
        self.assertIn(subtitle_gui.SCRIPT_VERSION, output.getvalue())
        gui_factory.assert_not_called()
        cli_runner.assert_not_called()

    def test_gui_only_launcher_opens_gui_without_cli_arguments(self):
        gui = Mock()
        gui_factory = Mock(return_value=gui)
        error_reporter = Mock()

        result = subtitle_gui.launch_gui_only(
            gui_factory=gui_factory, error_reporter=error_reporter
        )

        self.assertEqual(result, 0)
        gui.run.assert_called_once_with()
        error_reporter.assert_not_called()

    def test_gui_only_launcher_reports_startup_failure_visibly(self):
        gui_factory = Mock(side_effect=RuntimeError("Tkinter unavailable"))
        error_reporter = Mock()

        result = subtitle_gui.launch_gui_only(
            gui_factory=gui_factory, error_reporter=error_reporter
        )

        self.assertEqual(result, 1)
        error_reporter.assert_called_once()
        self.assertIn("Tkinter unavailable", error_reporter.call_args.args[0])

    def test_posix_pyw_launcher_detaches_from_the_calling_terminal(self):
        process_launcher = Mock()
        environment = {"EXISTING": "value"}

        self.assertTrue(
            subtitle_gui.should_detach_gui_launcher("linux", environment)
        )
        self.assertTrue(
            subtitle_gui.should_detach_gui_launcher("darwin", environment)
        )
        self.assertFalse(
            subtitle_gui.should_detach_gui_launcher("win32", environment)
        )
        self.assertFalse(
            subtitle_gui.should_detach_gui_launcher(
                "linux",
                {subtitle_gui.DETACHED_GUI_ENVIRONMENT_VARIABLE: "1"},
            )
        )

        result = subtitle_gui.launch_detached_gui_only(
            Path("/opt/subtitle/SubtitleUniverseSpellcheck.pyw"),
            executable="/usr/bin/python3",
            environment=environment,
            process_launcher=process_launcher,
        )

        self.assertEqual(result, 0)
        process_launcher.assert_called_once()
        arguments, options = process_launcher.call_args
        self.assertEqual(
            arguments[0],
            [
                "/usr/bin/python3",
                str(Path("/opt/subtitle/SubtitleUniverseSpellcheck.pyw")),
            ],
        )
        self.assertEqual(
            options["env"][subtitle_gui.DETACHED_GUI_ENVIRONMENT_VARIABLE],
            "1",
        )
        self.assertEqual(environment, {"EXISTING": "value"})
        self.assertIs(options["stdin"], subtitle_gui.subprocess.DEVNULL)
        self.assertIs(options["stdout"], subtitle_gui.subprocess.DEVNULL)
        self.assertIs(options["stderr"], subtitle_gui.subprocess.DEVNULL)
        self.assertTrue(options["start_new_session"])

    def test_portable_launcher_first_run_repeats_until_valid_and_saves_choice(self):
        root = Path(__file__).with_name("_launcher_first_run_test")
        root.mkdir(exist_ok=True)
        try:
            answers = iter(["invalid", "2"])
            output = io.StringIO()

            mode = subtitle_gui.choose_portable_launch_mode(
                root,
                has_console=True,
                input_func=lambda _prompt: next(answers),
                output_stream=output,
            )

            self.assertEqual(mode, "cli")
            self.assertTrue((root / subtitle_gui.LAUNCH_CLI_MARKER).is_file())
            self.assertFalse((root / subtitle_gui.LAUNCH_GUI_MARKER).exists())
            self.assertIn("Enter 1 or 2", output.getvalue())
        finally:
            for path in root.iterdir():
                path.unlink()
            root.rmdir()

    def test_portable_launcher_saved_choice_can_be_kept_or_switched(self):
        root = Path(__file__).with_name("_launcher_saved_choice_test")
        root.mkdir(exist_ok=True)
        try:
            subtitle_gui.save_portable_launch_mode(root, "gui")
            prompt = Mock(return_value="2")

            kept = subtitle_gui.choose_portable_launch_mode(
                root,
                has_console=True,
                input_func=prompt,
                output_stream=io.StringIO(),
                wait_for_change=lambda _seconds: False,
            )
            self.assertEqual(kept, "gui")
            prompt.assert_not_called()

            switched = subtitle_gui.choose_portable_launch_mode(
                root,
                has_console=True,
                input_func=prompt,
                output_stream=io.StringIO(),
                wait_for_change=lambda _seconds: True,
            )
            self.assertEqual(switched, "cli")
            self.assertFalse((root / subtitle_gui.LAUNCH_GUI_MARKER).exists())
            self.assertTrue((root / subtitle_gui.LAUNCH_CLI_MARKER).is_file())
        finally:
            for path in root.iterdir():
                path.unlink()
            root.rmdir()

    def test_portable_launcher_uses_gui_selector_without_a_console(self):
        root = Path(__file__).with_name("_launcher_gui_selector_test")
        root.mkdir(exist_ok=True)
        try:
            selector = Mock(return_value="gui")

            mode = subtitle_gui.choose_portable_launch_mode(
                root,
                has_console=False,
                gui_selector=selector,
            )

            self.assertEqual(mode, "gui")
            selector.assert_called_once_with(None, 5)
            self.assertTrue((root / subtitle_gui.LAUNCH_GUI_MARKER).is_file())
        finally:
            for path in root.iterdir():
                path.unlink()
            root.rmdir()

    def test_windows_cli_choice_opens_a_new_console(self):
        process_launcher = Mock()
        script_path = Path("C:/Subtitle/SubtitleUniverseSpellcheck.pyw")

        result = subtitle_gui.launch_cli_in_new_console(
            script_path,
            executable="C:/Python/pythonw.exe",
            process_launcher=process_launcher,
        )

        self.assertEqual(result, 0)
        process_launcher.assert_called_once_with(
            [
                str(Path("C:/Python/python.exe")),
                str(script_path.parent / "app" / "subtitle_gui.py"),
                "--cli",
            ],
            creationflags=subtitle_gui.WINDOWS_NEW_CONSOLE,
            close_fds=True,
        )

    def test_detached_gui_child_bypasses_portable_choice(self):
        chooser = Mock()
        gui_launcher = Mock(return_value=0)
        environment = {
            subtitle_gui.DETACHED_GUI_ENVIRONMENT_VARIABLE: "1",
        }

        with (
            patch.object(subtitle_gui.os, "environ", environment),
            patch("app.subtitle_gui.choose_portable_launch_mode", chooser),
            patch("app.subtitle_gui.launch_gui_only", gui_launcher),
        ):
            result = subtitle_gui.launch_portable_wrapper(
                Path("/opt/subtitle/SubtitleUniverseSpellcheck.pyw")
            )

        self.assertEqual(result, 0)
        chooser.assert_not_called()
        gui_launcher.assert_called_once_with()

    def test_scan_preview_is_read_only_and_reports_first_cues(self):
        subtitle_path = Path(__file__).with_name("_gui_preview_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nFirst line.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nSecond line.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)

            preview = subtitle_gui.build_scan_preview([subtitle_path])

            self.assertEqual(preview.file_count, 1)
            self.assertEqual(preview.cue_count, 2)
            self.assertEqual(preview.current_text, "First line.")
            self.assertEqual(preview.next_text, "Second line.")
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_shared_engine_finds_first_unknown_with_context_and_suggestions(self):
        subtitle_path = Path(__file__).with_name("_gui_issue_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nKnown line.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nKnown wrod.\n\n"
            "3\n00:00:05,000 --> 00:00:06,000\nKnown next.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                base_words={"known", "line", "word", "next"},
            )
            progress = []

            issue = tool.find_next_spellcheck_issue(
                [subtitle_path],
                subtitle_path.parent,
                context,
                progress_callback=lambda *values: progress.append(values),
            )

            self.assertIsNotNone(issue)
            self.assertEqual(issue.word, "wrod")
            self.assertEqual(issue.subtitle_index, 1)
            self.assertEqual(issue.total_subtitles, 3)
            self.assertEqual(issue.previous_blocks, ("1\n00:00:01,000 --> 00:00:02,000\nKnown line.",))
            self.assertEqual(issue.next_blocks, ("3\n00:00:05,000 --> 00:00:06,000\nKnown next.",))
            self.assertEqual(issue.suggestions[0], "word")
            self.assertTrue(progress)
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_shared_engine_reports_when_preview_has_no_unknowns(self):
        subtitle_path = Path(__file__).with_name("_gui_known_test.srt")
        original = b"1\n00:00:01,000 --> 00:00:02,000\nKnown line.\n"
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options["adjust_subtitle_line_count"] = False
            context = DictionaryContext(
                language="american", base_words={"known", "line"}
            )

            issue = tool.find_next_spellcheck_issue(
                [subtitle_path], subtitle_path.parent, context
            )

            self.assertIsNone(issue)
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_gui_review_uses_shared_lowercase_pronoun_i_cleanup(self):
        subtitle_path = Path(__file__).with_name("_gui_pronoun_i_test.srt")
        original = (
            '1\n00:00:01,000 --> 00:00:02,000\nWas that "i told you so," colonel samuels?\n'
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                base_words={"was", "that", "i", "told", "you", "so", "colonel"},
            )

            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )

            self.assertEqual(session.current_issue.word, "samuels")
            self.assertEqual(
                session.current_issue.current_text,
                'Was that "I told you so," colonel samuels?',
            )
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_gui_review_accepts_curly_contraction_from_straight_dictionary_entry(self):
        subtitle_path = Path(__file__).with_name("_gui_curly_contraction_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:04,000\n♪ Don’t go ♪\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american", base_words={"don't", "go"}
            )

            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )

            self.assertIsNone(session.current_issue)
            self.assertEqual(
                session.prepared_blocks[0][0].text_lines,
                ["♪ Don’t go ♪"],
            )
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_session_ignores_exact_occurrences_and_reuses_prepared_blocks(self):
        subtitle_path = Path(__file__).with_name("_gui_ignore_occurrence_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nWrod wrod.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nKnown anothr.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american", base_words={"known", "word", "another"}
            )

            with patch.object(tool, "parse_srt", wraps=tool.parse_srt) as parse_srt:
                session = tool.start_spellcheck_review(
                    [subtitle_path], subtitle_path.parent, context
                )
                first = session.current_issue
                second = tool.ignore_review_occurrence(session)
                third = tool.ignore_review_occurrence(session)
                finished = tool.ignore_review_occurrence(session)

            self.assertEqual(first.word, "Wrod")
            self.assertEqual((first.line_index, first.start, first.end), (0, 0, 4))
            self.assertEqual(second.word, "wrod")
            self.assertEqual((second.line_index, second.start, second.end), (0, 5, 9))
            self.assertEqual(third.word, "anothr")
            self.assertIsNone(finished)
            self.assertIsNone(session.current_issue)
            self.assertEqual(parse_srt.call_count, 1)
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_session_ignore_word_skips_all_later_occurrences(self):
        subtitle_path = Path(__file__).with_name("_gui_ignore_session_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nWrod wrod.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nWROD and anothr.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                base_words={"word", "and", "another"},
            )

            with patch.object(tool, "parse_srt", wraps=tool.parse_srt) as parse_srt:
                session = tool.start_spellcheck_review(
                    [subtitle_path], subtitle_path.parent, context
                )
                first = session.current_issue
                next_issue = tool.ignore_review_word_for_session(session)

            self.assertEqual(first.word, "Wrod")
            self.assertEqual(next_issue.word, "anothr")
            self.assertEqual(session.ignored_words, {"wrod"})
            self.assertEqual(parse_srt.call_count, 1)
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_session_undoes_ignore_actions_in_lifo_order(self):
        subtitle_path = Path(__file__).with_name("_gui_ignore_undo_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nWrod wrod.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nWROD and anothr.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                base_words={"word", "and", "another"},
            )

            with patch.object(tool, "parse_srt", wraps=tool.parse_srt) as parse_srt:
                session = tool.start_spellcheck_review(
                    [subtitle_path], subtitle_path.parent, context
                )
                first = session.current_issue
                second = tool.ignore_review_occurrence(session)
                after_session_ignore = tool.ignore_review_word_for_session(session)
                restored_second = tool.undo_review_ignore(session)
                restored_first = tool.undo_review_ignore(session)

            self.assertEqual(first.word, "Wrod")
            self.assertEqual(second.word, "wrod")
            self.assertEqual(after_session_ignore.word, "anothr")
            self.assertEqual(restored_second.word, "wrod")
            self.assertEqual(restored_first.word, "Wrod")
            self.assertEqual(session.ignored_words, set())
            self.assertEqual(session.ignored_occurrences, set())
            self.assertEqual(session.undo_actions, [])
            self.assertEqual(parse_srt.call_count, 1)
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_session_replaces_exact_occurrence_in_memory_and_undoes_it(self):
        subtitle_path = Path(__file__).with_name("_gui_suggestion_undo_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\n<i>Wrod</i> wrod.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                base_words={"word"},
            )

            with patch.object(tool, "parse_srt", wraps=tool.parse_srt) as parse_srt:
                session = tool.start_spellcheck_review(
                    [subtitle_path], subtitle_path.parent, context
                )
                first = session.current_issue
                second = tool.ignore_review_occurrence(session)
                finished = tool.replace_review_occurrence(session, "word")
                edited_line = session.prepared_blocks[0][0].text_lines[0]
                restored_second = tool.undo_review_action(session)
                restored_first = tool.undo_review_action(session)

            self.assertEqual(first.word, "Wrod")
            self.assertEqual(second.word, "wrod")
            self.assertIsNone(finished)
            self.assertEqual(edited_line, "<i>Wrod</i> word.")
            self.assertEqual(restored_second.word, "wrod")
            self.assertEqual(restored_first.word, "Wrod")
            self.assertEqual(
                session.prepared_blocks[0][0].text_lines[0],
                "<i>Wrod</i> wrod.",
            )
            self.assertEqual(parse_srt.call_count, 1)
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_session_replacement_scope_propagates_and_undoes_as_one_action(self):
        subtitle_path = Path(__file__).with_name("_gui_session_replacement_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nWrod now.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nWrod later.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                base_words={"word", "now", "later"},
            )
            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )

            finished = tool.replace_review_with_scope(session, "word", "session")

            self.assertIsNone(finished)
            self.assertEqual(session.substitutions, {"wrod": "word"})
            self.assertEqual(
                [block.text_lines for block in session.prepared_blocks[0]],
                [["word now."], ["word later."]],
            )
            restored = tool.undo_review_action(session)
            self.assertEqual(restored.word, "Wrod")
            self.assertEqual(session.substitutions, {})
            self.assertEqual(
                [block.text_lines for block in session.prepared_blocks[0]],
                [["Wrod now."], ["Wrod later."]],
            )
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_session_replacement_remains_active_after_intermediate_save(self):
        subtitle_path = Path(__file__).with_name("_gui_session_after_save_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nWrod now.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nAnothr pause.\n\n"
            "3\n00:00:05,000 --> 00:00:06,000\nWrod later.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                base_words={"word", "now", "another", "pause", "later"},
            )
            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )
            next_issue = tool.replace_review_with_scope(session, "word", "session")
            self.assertEqual(next_issue.word, "Anothr")

            tool.commit_spellcheck_review(session, create_backups=False)
            self.assertEqual(session.undo_actions, [])
            finished = tool.ignore_review_occurrence(session)

            self.assertIsNone(finished)
            self.assertEqual(session.prepared_blocks[0][2].text_lines, ["word later."])
        finally:
            subtitle_path.write_bytes(original)
            subtitle_path.unlink(missing_ok=True)

    def test_review_universe_replacement_persists_propagates_and_undoes(self):
        subtitle_path = Path(__file__).with_name("_gui_universe_replacement_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nWrod now.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nWrod later.\n"
        ).encode("utf-8")
        universe_dir = Path(__file__).with_name("_gui_universe_replacement_dicts")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.universe_dir = universe_dir
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                universe="Test Universe",
                base_words={"word", "now", "later"},
            )
            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )

            finished = tool.replace_review_with_scope(session, "word", "universe")

            substitutions_path = (
                universe_dir / "Test Universe" / "substitutions.tsv"
            )
            self.assertIsNone(finished)
            self.assertEqual(context.universe_substitutions, {"wrod": "word"})
            self.assertIn("wrod\tword", substitutions_path.read_text(encoding="utf-8"))
            self.assertEqual(session.prepared_blocks[0][1].text_lines, ["word later."])

            restored = tool.undo_review_action(session)

            self.assertEqual(restored.word, "Wrod")
            self.assertEqual(context.universe_substitutions, {})
            self.assertEqual(context.substitutions, {})
            self.assertEqual(tool.load_substitutions(substitutions_path), {})
            self.assertEqual(session.prepared_blocks[0][1].text_lines, ["Wrod later."])
        finally:
            subtitle_path.unlink(missing_ok=True)
            if universe_dir.exists():
                for path in sorted(universe_dir.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    else:
                        path.rmdir()
                universe_dir.rmdir()

    def test_review_always_replacement_uses_selected_language_dictionary(self):
        subtitle_path = Path(__file__).with_name("_gui_always_replacement_test.srt")
        user_dir = Path(__file__).with_name("_gui_always_replacement_dicts")
        original = "1\n00:00:01,000 --> 00:00:02,000\nWrod.\n".encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.user_dir = user_dir
            tool.options["adjust_subtitle_line_count"] = False
            context = DictionaryContext(language="british", base_words={"word"})
            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )

            tool.replace_review_with_scope(session, "word", "always")

            path = user_dir / "british_substitutions.tsv"
            self.assertEqual(tool.load_substitutions(path), {"wrod": "word"})
            self.assertEqual(context.user_substitutions, {"wrod": "word"})
            tool.undo_review_action(session)
            self.assertEqual(tool.load_substitutions(path), {})
            self.assertEqual(context.user_substitutions, {})
        finally:
            subtitle_path.unlink(missing_ok=True)
            if user_dir.exists():
                for path in sorted(user_dir.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    else:
                        path.rmdir()
                user_dir.rmdir()

    def test_review_universe_replacement_requires_active_universe(self):
        subtitle_path = Path(__file__).with_name("_gui_no_universe_scope_test.srt")
        try:
            subtitle_path.write_text(
                "1\n00:00:01,000 --> 00:00:02,000\nWrod.\n",
                encoding="utf-8",
            )
            tool = SubtitleCleanupTool()
            tool.options["adjust_subtitle_line_count"] = False
            session = tool.start_spellcheck_review(
                [subtitle_path],
                subtitle_path.parent,
                DictionaryContext(language="american", base_words={"word"}),
            )

            with self.assertRaisesRegex(ValueError, "No Universe Dictionary"):
                tool.replace_review_with_scope(session, "word", "universe")

            self.assertEqual(session.prepared_blocks[0][0].text_lines, ["Wrod."])
            self.assertEqual(session.undo_actions, [])
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_session_edits_complete_cue_text_in_memory_and_undoes_it(self):
        subtitle_path = Path(__file__).with_name("_gui_cue_edit_undo_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nIdenti yourself!\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american",
                base_words={"hold", "it", "identify", "yourself"},
            )

            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )
            original_issue = session.current_issue
            finished = tool.replace_review_cue_text(
                session,
                "Hold it!\nIdentify yourself!",
            )
            edited_lines = list(session.prepared_blocks[0][0].text_lines)
            restored = tool.undo_review_action(session)

            self.assertEqual(original_issue.word, "Identi")
            self.assertIsNone(finished)
            self.assertEqual(edited_lines, ["Hold it!", "Identify yourself!"])
            self.assertEqual(restored.word, "Identi")
            self.assertEqual(
                session.prepared_blocks[0][0].timestamp,
                "00:00:01,000 --> 00:00:02,000",
            )
            self.assertEqual(
                session.prepared_blocks[0][0].text_lines,
                ["Identi yourself!"],
            )
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_gui_review_journal_restores_edits_ignores_cursor_and_undo(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_recovery_test.srt"
        journal_path = root / "_gui_review_state.json.gz"
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nWrod wrod.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nAnothr.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.gui_session_state_path = journal_path
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american", base_words={"word", "another"}
            )
            session = tool.start_spellcheck_review([subtitle_path], root, context)
            tool.ignore_review_occurrence(session)
            tool.replace_review_occurrence(session, "word")
            self.assertEqual(session.current_issue.word, "Anothr")

            tool.save_gui_review_session(session)
            restored = tool.load_gui_review_session()

            self.assertIsNotNone(restored)
            self.assertEqual(restored.current_issue.word, "Anothr")
            self.assertEqual(restored.ignored_occurrences, session.ignored_occurrences)
            self.assertEqual(
                restored.prepared_blocks[0][0].text_lines,
                ["Wrod word."],
            )
            self.assertEqual(len(restored.undo_actions), 2)
            previous = tool.undo_review_action(restored)
            self.assertEqual(previous.word, "wrod")
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)

    def test_gui_review_journal_restores_scoped_replacement_and_undo(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_scoped_recovery_test.srt"
        journal_path = root / "_gui_scoped_recovery_state.json.gz"
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nWrod now.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nWrod later.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.gui_session_state_path = journal_path
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american", base_words={"word", "now", "later"}
            )
            session = tool.start_spellcheck_review([subtitle_path], root, context)
            tool.replace_review_with_scope(session, "word", "session")
            tool.save_gui_review_session(session)

            with patch.object(tool, "load_dictionary_context", return_value=context):
                restored = tool.load_gui_review_session()

            self.assertEqual(restored.substitutions, {"wrod": "word"})
            self.assertEqual(restored.prepared_blocks[0][1].text_lines, ["word later."])
            previous = tool.undo_review_action(restored)
            self.assertEqual(previous.word, "Wrod")
            self.assertEqual(restored.substitutions, {})
            self.assertEqual(restored.prepared_blocks[0][1].text_lines, ["Wrod later."])
        finally:
            subtitle_path.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)

    def test_gui_review_journal_refuses_changed_source(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_recovery_drift_test.srt"
        journal_path = root / "_gui_review_drift_state.json.gz"
        try:
            subtitle_path.write_bytes(
                b"1\n00:00:01,000 --> 00:00:02,000\nWrod.\n"
            )
            tool = SubtitleCleanupTool()
            tool.gui_session_state_path = journal_path
            tool.options["adjust_subtitle_line_count"] = False
            session = tool.start_spellcheck_review(
                [subtitle_path], root, DictionaryContext(language="american")
            )
            tool.save_gui_review_session(session)
            subtitle_path.write_bytes(
                b"1\n00:00:01,000 --> 00:00:02,000\nExternal change.\n"
            )

            with self.assertRaisesRegex(RuntimeError, "changed since"):
                tool.load_gui_review_session()
        finally:
            subtitle_path.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)

    def test_gui_recovery_revalidates_stale_current_issue_against_current_dictionary(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_recovery_revalidate_test.srt"
        journal_path = root / "_gui_recovery_revalidate_state.json.gz"
        original = (
            "1\n00:00:01,000 --> 00:00:04,000\nDon’t go. Wrod.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.gui_session_state_path = journal_path
            tool.options["adjust_subtitle_line_count"] = False
            old_context = DictionaryContext(
                language="american", base_words={"go", "word"}
            )
            session = tool.start_spellcheck_review(
                [subtitle_path], root, old_context
            )
            self.assertEqual(session.current_issue.word, "Don’t")
            tool.save_gui_review_session(session)
            current_context = DictionaryContext(
                language="american", base_words={"don't", "go", "word"}
            )

            with patch.object(
                tool, "load_dictionary_context", return_value=current_context
            ):
                restored = tool.load_gui_review_session()

            self.assertIsNotNone(restored)
            self.assertEqual(restored.current_issue.word, "Wrod")
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)

    def test_review_dictionary_phrase_accepts_only_complete_phrase_and_undoes(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_dictionary_phrase_test.srt"
        dictionary_path = root / "american_words.txt"
        log_path = root / "_gui_dictionary_log.jsonl"
        try:
            dictionary_path.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)
            original = (
                "1\n00:00:01,000 --> 00:00:02,000\nkor mak bracelets.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nkor remains unknown.\n"
            ).encode("utf-8")
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.user_dir = root
            tool.session_log_path = log_path
            tool.options["adjust_subtitle_line_count"] = False
            context = DictionaryContext(
                language="american",
                base_words={"bracelets", "remains", "unknown"},
            )
            session = tool.start_spellcheck_review([subtitle_path], root, context)

            next_issue = tool.add_review_dictionary_entry(
                session,
                "kor mak",
                list_name="words",
                target="user",
            )

            self.assertEqual(next_issue.word, "kor")
            self.assertEqual(next_issue.subtitle_index, 1)
            self.assertEqual(dictionary_path.read_text(encoding="utf-8"), "kor mak\n")
            self.assertIn("kor mak", context.user_words)
            self.assertNotIn("kor", context.user_words)
            restored = tool.undo_review_action(session)
            self.assertEqual(restored.word, "kor")
            self.assertEqual(restored.subtitle_index, 0)
            self.assertEqual(dictionary_path.read_text(encoding="utf-8"), "")
            self.assertNotIn("kor mak", context.user_words)
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)
            dictionary_path.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)

    def test_review_name_phrase_applies_authoritative_casing_and_undoes(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_dictionary_name_phrase_test.srt"
        dictionary_path = root / "american_names.txt"
        log_path = root / "_gui_dictionary_log.jsonl"
        try:
            dictionary_path.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)
            original = (
                "1\n00:00:01,000 --> 00:00:02,000\nVala. Vala mal\nDoran.\n"
            ).encode("utf-8")
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.user_dir = root
            tool.session_log_path = log_path
            tool.options["adjust_subtitle_line_count"] = False
            context = DictionaryContext(
                language="american", base_words={"vala", "doran"}
            )
            session = tool.start_spellcheck_review([subtitle_path], root, context)

            finished = tool.add_review_dictionary_entry(
                session,
                "Vala Mal Doran",
                list_name="names",
                target="user",
            )

            self.assertIsNone(finished)
            self.assertEqual(
                session.prepared_blocks[0][0].text_lines,
                ["Vala. Vala Mal", "Doran."],
            )
            self.assertEqual(context.user_names["vala mal doran"], "Vala Mal Doran")
            self.assertTrue(tool.review_has_changes(session))
            restored = tool.undo_review_action(session)
            self.assertEqual(restored.word, "mal")
            self.assertEqual(
                session.prepared_blocks[0][0].text_lines,
                ["Vala. Vala mal", "Doran."],
            )
            self.assertNotIn("vala mal doran", context.user_names)
            self.assertEqual(dictionary_path.read_text(encoding="utf-8"), "")
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)
            dictionary_path.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)

    def test_review_dictionary_phrase_must_include_selected_word_and_exist_in_cue(self):
        subtitle_path = Path(__file__).with_name("_gui_dictionary_validation_test.srt")
        original = b"1\n00:00:01,000 --> 00:00:02,000\nVala mal Doran.\n"
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options["adjust_subtitle_line_count"] = False
            context = DictionaryContext(
                language="american", base_words={"vala", "doran"}
            )
            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )

            with self.assertRaisesRegex(ValueError, "selected word"):
                tool.add_review_dictionary_entry(
                    session, "Vala Doran", list_name="words", target="user"
                )
            with self.assertRaisesRegex(ValueError, "current subtitle"):
                tool.add_review_dictionary_entry(
                    session, "mal elsewhere", list_name="words", target="user"
                )

            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_dictionary_entry_can_target_active_universe(self):
        subtitle_path = Path(__file__).with_name("_gui_dictionary_universe_test.srt")
        original = b"1\n00:00:01,000 --> 00:00:02,000\nharriman reports.\n"
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options["adjust_subtitle_line_count"] = False
            tool.add_word_to_file = Mock(return_value=True)
            context = DictionaryContext(
                language="american",
                universe="Stargate",
                base_words={"reports"},
            )
            session = tool.start_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )

            finished = tool.add_review_dictionary_entry(
                session,
                "Harriman",
                list_name="names",
                target="universe",
            )

            self.assertIsNone(finished)
            expected_event = {
                "type": "dictionary_add",
                "target": "universe",
                "universe": "Stargate",
                "list": "names",
                "word": "Harriman",
            }
            tool.add_word_to_file.assert_called_once_with(
                tool.universe_dir / "Stargate" / "names.txt",
                "Harriman",
                expected_event,
            )
            self.assertEqual(context.universe_names["harriman"], "Harriman")
            self.assertEqual(
                session.prepared_blocks[0][0].text_lines,
                ["Harriman reports."],
            )
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_review_dictionary_add_rolls_back_if_advancing_scan_fails(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_dictionary_rollback_test.srt"
        dictionary_path = root / "american_words.txt"
        log_path = root / "_gui_dictionary_log.jsonl"
        try:
            dictionary_path.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)
            original = b"1\n00:00:01,000 --> 00:00:02,000\nwrod.\n"
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.user_dir = root
            tool.session_log_path = log_path
            tool.options["adjust_subtitle_line_count"] = False
            context = DictionaryContext(language="american")
            session = tool.start_spellcheck_review([subtitle_path], root, context)
            original_issue = session.current_issue

            with patch.object(
                tool, "_advance_spellcheck_review", side_effect=OSError("scan failed")
            ):
                with self.assertRaisesRegex(OSError, "scan failed"):
                    tool.add_review_dictionary_entry(
                        session,
                        "wrod",
                        list_name="words",
                        target="user",
                    )

            self.assertEqual(dictionary_path.read_text(encoding="utf-8"), "")
            self.assertNotIn("wrod", context.user_words)
            self.assertIs(session.current_issue, original_issue)
            self.assertEqual(session.undo_actions, [])
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)
            dictionary_path.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)

    def test_review_commit_creates_exact_backup_and_updates_saved_baseline(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_commit_backup_test.srt"
        backup_path = root / "backup_subtitles.zip"
        try:
            backup_path.unlink(missing_ok=True)
            original = (
                b"\xef\xbb\xbf1\r\n00:00:01,000 --> 00:00:02,000\r\n"
                b"i found Wrod.\r\n"
            )
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american", base_words={"i", "found", "word"}
            )
            session = tool.start_spellcheck_review(
                [subtitle_path], root, context
            )
            tool.replace_review_occurrence(session, "word")

            result = tool.commit_spellcheck_review(session, create_backups=True)

            self.assertEqual(result.changed_files, (subtitle_path,))
            self.assertEqual(result.backup_archives, (backup_path,))
            with zipfile.ZipFile(backup_path) as archive:
                self.assertEqual(archive.read(subtitle_path.name), original)
            expected = (
                b"\xef\xbb\xbf1\r\n00:00:01,000 --> 00:00:02,000\r\n"
                b"I found word.\r\n"
            )
            self.assertEqual(subtitle_path.read_bytes(), expected)
            self.assertEqual(session.source_bytes[0], expected)
            self.assertEqual(session.undo_actions, [])
            self.assertFalse(tool.review_has_changes(session))
        finally:
            subtitle_path.unlink(missing_ok=True)
            backup_path.unlink(missing_ok=True)

    def test_review_commit_refuses_external_source_drift_before_backup_or_write(self):
        root = Path(__file__).parent
        subtitle_path = root / "_gui_commit_drift_test.srt"
        backup_path = root / "backup_subtitles.zip"
        try:
            backup_path.unlink(missing_ok=True)
            original = b"1\n00:00:01,000 --> 00:00:02,000\nWrod.\n"
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options["adjust_subtitle_line_count"] = False
            context = DictionaryContext(language="american", base_words={"word"})
            session = tool.start_spellcheck_review([subtitle_path], root, context)
            tool.replace_review_occurrence(session, "word")
            external = original.replace(b"Wrod", b"External")
            subtitle_path.write_bytes(external)

            with self.assertRaisesRegex(RuntimeError, "changed outside"):
                tool.commit_spellcheck_review(session, create_backups=True)

            self.assertEqual(subtitle_path.read_bytes(), external)
            self.assertFalse(backup_path.exists())
            self.assertTrue(tool.review_has_changes(session))
        finally:
            subtitle_path.unlink(missing_ok=True)
            backup_path.unlink(missing_ok=True)

    def test_review_commit_rolls_back_earlier_file_when_later_write_fails(self):
        root = Path(__file__).parent
        first_path = root / "_gui_commit_rollback_one.srt"
        second_path = root / "_gui_commit_rollback_two.srt"
        try:
            first_original = b"1\n00:00:01,000 --> 00:00:02,000\ni first.\n"
            second_original = b"1\n00:00:03,000 --> 00:00:04,000\ni second.\n"
            first_path.write_bytes(first_original)
            second_path.write_bytes(second_original)
            tool = SubtitleCleanupTool()
            tool.options["adjust_subtitle_line_count"] = False
            context = DictionaryContext(
                language="american", base_words={"i", "first", "second"}
            )
            session = tool.start_spellcheck_review(
                [first_path, second_path], root, context
            )
            real_atomic_write = tool.atomic_write_bytes
            writes = []

            def fail_second_write(path, data):
                writes.append(path)
                if path == second_path and writes.count(second_path) == 1:
                    raise OSError("simulated disk failure")
                real_atomic_write(path, data)

            with patch.object(tool, "atomic_write_bytes", side_effect=fail_second_write):
                with self.assertRaisesRegex(OSError, "simulated disk failure"):
                    tool.commit_spellcheck_review(session, create_backups=False)

            self.assertEqual(first_path.read_bytes(), first_original)
            self.assertEqual(second_path.read_bytes(), second_original)
            self.assertTrue(tool.review_has_changes(session))
        finally:
            first_path.unlink(missing_ok=True)
            second_path.unlink(missing_ok=True)

    def test_gui_ignore_action_requires_this_time_scope(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.review_session = object()
        gui.current_issue = object()
        gui.pending_action = None
        gui.this_time_button = Mock()
        gui.this_session_button = Mock()
        gui.status_value = Mock()

        gui._choose_ignore()

        self.assertEqual(gui.pending_action, "ignore")
        gui.this_time_button.configure.assert_called_once_with(state="normal")
        gui.this_session_button.configure.assert_called_once_with(state="normal")
        gui.status_value.set.assert_called_once()
        self.assertIn("This time", gui.status_value.set.call_args.args[0])

    def test_gui_suggestion_action_enables_persistent_replacement_scopes(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.review_session = Mock(context=Mock(universe="Stargate SG-1"))
        gui.current_issue = Mock(suggestions=("word",))
        gui.pending_action = None
        gui.pending_replacement = None
        gui.this_time_button = Mock()
        gui.this_session_button = Mock()
        gui.this_universe_button = Mock()
        gui.always_button = Mock()
        gui.status_value = Mock()

        gui._choose_suggestion(0)

        self.assertEqual(gui.pending_action, "replacement")
        self.assertEqual(gui.pending_replacement, "word")
        gui.this_time_button.configure.assert_called_once_with(state="normal")
        gui.this_session_button.configure.assert_called_once_with(state="normal")
        gui.this_universe_button.configure.assert_called_once_with(state="normal")
        gui.always_button.configure.assert_called_once_with(state="normal")
        self.assertIn("word", gui.status_value.set.call_args.args[0])

    def test_gui_edit_action_makes_only_current_dialogue_editable(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.review_session = object()
        gui.current_issue = Mock(current_text="Identi yourself!")
        gui.pending_action = None
        gui.pending_replacement = None
        gui.editing_cue = False
        gui.current_box = Mock()
        gui.edit_button = Mock()
        gui.this_time_button = Mock()
        gui.this_session_button = Mock()
        gui.status_value = Mock()
        gui._disable_review_actions = Mock()

        gui._begin_or_cancel_cue_edit()

        self.assertTrue(gui.editing_cue)
        self.assertEqual(gui.pending_action, "cue_edit")
        gui.current_box.configure.assert_called_once_with(state="normal")
        gui.current_box.focus_set.assert_called_once_with()
        gui.edit_button.configure.assert_called_once_with(
            text="Cancel edit", state="normal"
        )
        gui.this_time_button.configure.assert_called_once_with(state="normal")
        gui.this_session_button.configure.assert_called_once_with(state="disabled")
        self.assertIn("dialogue", gui.status_value.set.call_args.args[0])

    def test_gui_save_choice_can_enable_persistent_backups(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui.tool.options = {"create_backup_subtitles_zip_before_editing": False}
        gui.messagebox = Mock()
        gui.messagebox.askyesnocancel.return_value = True

        create_backups = gui._choose_save_backup_behavior()

        self.assertTrue(create_backups)
        self.assertTrue(
            gui.tool.options["create_backup_subtitles_zip_before_editing"]
        )
        gui.tool.save_options.assert_called_once_with()

    def test_gui_save_dispatches_shared_review_commit(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        session = object()
        changed_path = Path("changed.srt")
        gui.review_session = session
        gui.current_issue = object()
        gui.prepare_thread = None
        gui.editing_cue = False
        gui.tool = Mock()
        gui.tool.review_changed_files.return_value = (changed_path,)
        gui.tool.options = {"create_backup_subtitles_zip_before_editing": True}
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = True
        gui.prepare_queue = None
        gui.save_button = Mock()
        gui.prepare_button = Mock()
        gui.pause_button = Mock()
        gui.stop_button = Mock()
        gui.status_value = Mock()
        gui._disable_review_actions = Mock()
        gui.root = Mock()

        gui._save_review_changes()
        gui.prepare_thread.join(timeout=2)

        gui.tool.commit_spellcheck_review.assert_called_once_with(
            session, create_backups=True
        )
        gui.root.after.assert_called_once_with(50, gui._poll_prepare_queue)

    def test_gui_startup_can_restore_a_valid_recovery_journal(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        issue = object()
        session = SimpleNamespace(
            target=Path("C:/Recovered"),
            context=SimpleNamespace(language="british", universe="Stargate"),
            recovery_paused=False,
            current_issue=issue,
            files=(Path("C:/Recovered/episode.srt"),),
        )
        recovery_path = Mock()
        recovery_path.exists.return_value = True
        gui.tool = Mock(gui_session_state_path=recovery_path)
        gui.tool.load_gui_review_session.return_value = session
        gui.messagebox = Mock()
        gui.messagebox.askyesnocancel.return_value = True
        gui.folder_value = Mock()
        gui.language_value = Mock()
        gui.universe_value = Mock()
        gui.stop_button = Mock()
        gui.status_value = Mock()
        gui._select_mode = Mock()
        gui._display_spellcheck_issue = Mock()
        gui._update_save_control = Mock()

        gui._offer_gui_recovery()

        self.assertIs(gui.review_session, session)
        self.assertIs(gui.current_issue, issue)
        gui.folder_value.set.assert_called_once_with("C:\\Recovered")
        gui.language_value.set.assert_called_once_with("British English")
        gui.universe_value.set.assert_called_once_with("Stargate")
        gui._select_mode.assert_called_once_with("universe")
        gui._display_spellcheck_issue.assert_called_once_with(issue)

    def test_gui_startup_can_discard_recovery_without_loading_it(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        recovery_path = Mock()
        recovery_path.exists.return_value = True
        gui.tool = Mock(gui_session_state_path=recovery_path)
        gui.messagebox = Mock()
        gui.messagebox.askyesnocancel.return_value = False

        gui._offer_gui_recovery()

        gui.tool.clear_gui_review_session.assert_called_once_with()
        gui.tool.load_gui_review_session.assert_not_called()

    def test_gui_dictionary_dialog_dispatches_shared_entry_operation(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        session = object()
        dialog = Mock()
        gui.review_session = session
        gui.current_issue = object()
        gui.prepare_thread = None
        gui.tool = Mock()
        gui.prepare_queue = None
        gui.pause_requested = threading.Event()
        gui.stop_requested = threading.Event()
        gui.prepare_button = Mock()
        gui.pause_button = Mock()
        gui.stop_button = Mock()
        gui.save_button = Mock()
        gui.status_value = Mock()
        gui._disable_review_actions = Mock()
        gui.root = Mock()

        gui._apply_dictionary_entry(
            "Vala Mal Doran", "names", "user", dialog
        )
        gui.prepare_thread.join(timeout=2)

        dialog.destroy.assert_called_once_with()
        gui.tool.add_review_dictionary_entry.assert_called_once()
        call = gui.tool.add_review_dictionary_entry.call_args
        self.assertIs(call.args[0], session)
        self.assertEqual(call.args[1], "Vala Mal Doran")
        self.assertEqual(call.kwargs["list_name"], "names")
        self.assertEqual(call.kwargs["target"], "user")
        gui.root.after.assert_called_once_with(50, gui._poll_prepare_queue)

    def test_review_session_pauses_and_safely_rebuilds_partial_preparation(self):
        subtitle_path = Path(__file__).with_name("_gui_pause_resume_test.srt")
        original = (
            "1\n00:00:01,000 --> 00:00:02,000\nKnown line.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nKnown wrod.\n"
        ).encode("utf-8")
        try:
            subtitle_path.write_bytes(original)
            tool = SubtitleCleanupTool()
            tool.options.update({
                "adjust_subtitle_line_count": False,
                "detect_dropped_speaker_breaks": False,
                "title_case_bracketed_sound_effects": False,
                "fix_mostly_uppercase_lines": False,
            })
            context = DictionaryContext(
                language="american", base_words={"known", "line", "word"}
            )
            session = tool.create_spellcheck_review(
                [subtitle_path], subtitle_path.parent, context
            )
            pause_requested = threading.Event()

            def pause_after_first_cue(*values):
                if values[0] == "Preparing" and values[3] == 1:
                    pause_requested.set()

            with patch.object(tool, "parse_srt", wraps=tool.parse_srt) as parse_srt:
                with self.assertRaises(SpellcheckReviewPaused):
                    tool.resume_spellcheck_review(
                        session,
                        progress_callback=pause_after_first_cue,
                        pause_requested=pause_requested.is_set,
                    )
                self.assertEqual(session.prepared_blocks, {})

                pause_requested.clear()
                issue = tool.resume_spellcheck_review(session)

            self.assertEqual(issue.word, "wrod")
            self.assertEqual(parse_srt.call_count, 2)
            self.assertEqual(subtitle_path.read_bytes(), original)
        finally:
            subtitle_path.unlink(missing_ok=True)

    def test_remembered_capitalization_choice_updates_persisted_gui_setting(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui.tool.options = {"capitalization_mode": "ask_always"}
        gui._saved_capitalization_mode = "ask_always"
        gui._temporary_capitalization_mode = False

        gui._apply_capitalization_choice("all_caps", remember=True)

        gui.tool.set_option_value.assert_called_once_with(
            "capitalization_mode", "all_caps"
        )
        self.assertEqual(gui._saved_capitalization_mode, "all_caps")
        self.assertFalse(gui._temporary_capitalization_mode)

    def test_unremembered_capitalization_choice_keeps_ask_always_setting(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.tool = Mock()
        gui.tool.options = {"capitalization_mode": "ask_always"}
        gui._saved_capitalization_mode = "ask_always"
        gui._temporary_capitalization_mode = False

        gui._apply_capitalization_choice("source", remember=False)

        gui.tool.set_option_value.assert_not_called()
        self.assertEqual(gui.tool.options["capitalization_mode"], "source")
        self.assertEqual(gui._saved_capitalization_mode, "ask_always")
        self.assertTrue(gui._temporary_capitalization_mode)

    def test_stopping_gui_scan_discards_only_in_memory_review_state(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.review_session = object()
        gui.current_issue = object()
        gui.pending_action = "ignore"
        gui.scan_paused = True
        gui.pause_requested = threading.Event()
        gui.stop_requested = threading.Event()
        gui.scan_button_text = Mock()
        gui.prepare_button = Mock()
        gui.pause_button = Mock()
        gui.stop_button = Mock()
        gui.status_value = Mock()
        gui._disable_review_actions = Mock()

        gui._stop_scan()

        self.assertIsNone(gui.review_session)
        self.assertIsNone(gui.current_issue)
        self.assertIsNone(gui.pending_action)
        self.assertFalse(gui.scan_paused)
        gui.scan_button_text.set.assert_called_once_with("Start scan")
        gui.pause_button.configure.assert_called_once_with(state="disabled", text="Pause scan")
        gui.stop_button.configure.assert_called_once_with(
            state="disabled", text="Stop scan"
        )
        gui._disable_review_actions.assert_called_once_with()

    def test_pause_button_has_no_stop_path_after_worker_exit(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.prepare_thread = Mock()
        gui.prepare_thread.is_alive.return_value = False
        gui.pause_requested = threading.Event()
        gui.pause_button = Mock()
        gui.status_value = Mock()
        gui._stop_scan = Mock()

        gui._request_pause()

        self.assertTrue(gui.pause_requested.is_set())
        gui.pause_button.configure.assert_called_once_with(
            state="disabled", text="Pausing…"
        )
        gui._stop_scan.assert_not_called()

    def test_stop_during_worker_requests_cancellation_before_clearing_state(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.prepare_thread = Mock()
        gui.prepare_thread.is_alive.return_value = True
        gui.prepare_queue = Mock()
        gui.pause_requested = threading.Event()
        gui.stop_requested = threading.Event()
        gui.pause_button = Mock()
        gui.stop_button = Mock()
        gui.status_value = Mock()
        gui._stop_scan = Mock()

        gui._request_stop()

        self.assertTrue(gui.pause_requested.is_set())
        self.assertTrue(gui.stop_requested.is_set())
        gui.pause_button.configure.assert_called_once_with(state="disabled")
        gui.stop_button.configure.assert_called_once_with(
            state="disabled", text="Stopping…"
        )
        gui._stop_scan.assert_not_called()

    def test_stop_does_not_discard_unsaved_review_without_confirmation(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        gui.review_session = object()
        gui.prepare_thread = None
        gui.prepare_queue = None
        gui.tool = Mock()
        gui.tool.review_has_changes.return_value = True
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = False
        gui._stop_scan = Mock()

        gui._request_stop()

        gui.messagebox.askyesno.assert_called_once()
        gui._stop_scan.assert_not_called()

    def test_gui_search_uses_exact_selected_line_and_keeps_review_state(self):
        gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(
            subtitle_gui.SubtitleSpellcheckGUI
        )
        block = SimpleNamespace(text_lines=["First wyrd.", "Second wyrd here."])
        issue = SimpleNamespace(
            file_number=1,
            subtitle_index=0,
            line_index=1,
            word="wyrd",
        )
        session = SimpleNamespace(prepared_blocks={0: [block]})
        gui.review_session = session
        gui.current_issue = issue
        gui.tool = Mock()
        gui.tool.search_subtitle_line_in_google.return_value = True
        gui.status_value = Mock()
        gui.messagebox = Mock()

        gui._search_current_line()

        gui.tool.search_subtitle_line_in_google.assert_called_once_with(
            block, "wyrd", line_index=1
        )
        self.assertIs(gui.review_session, session)
        self.assertIs(gui.current_issue, issue)
        gui.messagebox.showwarning.assert_not_called()
        self.assertIn("Opened Google search", gui.status_value.set.call_args.args[0])

    def test_shared_search_uses_requested_line_when_word_is_repeated(self):
        tool = SubtitleCleanupTool()
        block = SimpleNamespace(
            text_lines=["First wyrd should not be sent.", "<i>Second wyrd here.</i>"]
        )

        with patch("subtitle_cleanup.webbrowser.open", return_value=True) as open_browser:
            opened = tool.search_subtitle_line_in_google(
                block, "wyrd", line_index=1
            )

        self.assertTrue(opened)
        open_browser.assert_called_once_with(
            "https://www.google.com/search?q=Second+wyrd+here.", new=2
        )

    def test_gui_progress_does_not_move_backward_between_files(self):
        values = [
            subtitle_gui.scan_progress_percent("Preparing", 1, 2, 1, 2),
            subtitle_gui.scan_progress_percent("Spellchecking", 1, 2, 2, 2),
            subtitle_gui.scan_progress_percent("Preparing", 2, 2, 1, 2),
            subtitle_gui.scan_progress_percent("Spellchecking", 2, 2, 2, 2),
        ]

        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 100)


if __name__ == "__main__":
    unittest.main()
