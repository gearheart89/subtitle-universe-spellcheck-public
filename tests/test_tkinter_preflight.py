import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import subtitle_gui
from app.subtitle_cleanup import (
    TKINTER_DOCS_URL,
    SubtitleCleanupTool,
    install_tkinter_support,
    tkinter_install_command,
    tkinter_preflight_required,
)


class TkinterPreflightTests(unittest.TestCase):
    def test_preflight_is_limited_to_nonfrozen_linux_and_macos_source_runs(self):
        self.assertTrue(tkinter_preflight_required(platform_name="linux", frozen=False))
        self.assertTrue(tkinter_preflight_required(platform_name="darwin", frozen=False))
        self.assertFalse(tkinter_preflight_required(platform_name="win32", frozen=False))
        self.assertFalse(tkinter_preflight_required(platform_name="linux", frozen=True))
        self.assertFalse(tkinter_preflight_required(platform_name="darwin", frozen=True))

    def test_linux_and_macos_install_commands_use_recognized_package_managers(self):
        available = {
            "apt-get": "/usr/bin/apt-get",
            "sudo": "/usr/bin/sudo",
        }
        linux = tkinter_install_command(
            platform_name="linux",
            which=lambda name: available.get(name),
            is_root=False,
        )
        self.assertEqual(
            linux,
            ["/usr/bin/sudo", "/usr/bin/apt-get", "install", "-y", "python3-tk"],
        )

        macos = tkinter_install_command(
            platform_name="darwin",
            which=lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
            python_version=(3, 13),
        )
        self.assertEqual(
            macos,
            ["/opt/homebrew/bin/brew", "install", "python-tk@3.13"],
        )

    def test_unknown_package_manager_prints_official_manual_guidance(self):
        output = io.StringIO()
        with patch(
            "app.subtitle_cleanup.tkinter_install_command", return_value=None
        ):
            installed = install_tkinter_support(
                platform_name="linux",
                output_stream=output,
            )

        self.assertFalse(installed)
        rendered = output.getvalue()
        self.assertIn(TKINTER_DOCS_URL, rendered)
        self.assertIn("python -m tkinter", rendered)
        self.assertIn("operating system's package manager", rendered)

    def test_stop_asking_persists_and_routes_directly_to_cli(self):
        tool = SimpleNamespace(
            suppress_tkinter_startup_prompt=False,
            set_tkinter_startup_prompt_suppressed=Mock(),
        )
        output = io.StringIO()

        can_launch_gui = subtitle_gui.ensure_tkinter_for_gui(
            tool,
            platform_name="linux",
            frozen=False,
            has_console=True,
            input_func=Mock(return_value="s"),
            output_stream=output,
            availability_checker=Mock(return_value=False),
            installer=Mock(),
        )

        self.assertFalse(can_launch_gui)
        tool.set_tkinter_startup_prompt_suppressed.assert_called_once_with(True)
        self.assertIn("command-line interface", output.getvalue())

    def test_declining_is_only_for_the_current_launch(self):
        tool = SimpleNamespace(
            suppress_tkinter_startup_prompt=False,
            set_tkinter_startup_prompt_suppressed=Mock(),
        )

        can_launch_gui = subtitle_gui.ensure_tkinter_for_gui(
            tool,
            platform_name="darwin",
            frozen=False,
            has_console=True,
            input_func=Mock(return_value="n"),
            output_stream=io.StringIO(),
            availability_checker=Mock(return_value=False),
            installer=Mock(),
        )

        self.assertFalse(can_launch_gui)
        tool.set_tkinter_startup_prompt_suppressed.assert_not_called()

    def test_successful_install_continues_to_gui_and_clears_suppression(self):
        tool = SimpleNamespace(
            suppress_tkinter_startup_prompt=True,
            set_tkinter_startup_prompt_suppressed=Mock(),
        )
        availability = Mock(side_effect=[False, True])

        can_launch_gui = subtitle_gui.ensure_tkinter_for_gui(
            tool,
            platform_name="linux",
            frozen=False,
            has_console=True,
            force_prompt=True,
            input_func=Mock(return_value="y"),
            output_stream=io.StringIO(),
            availability_checker=availability,
            installer=Mock(return_value=True),
        )

        self.assertTrue(can_launch_gui)
        tool.set_tkinter_startup_prompt_suppressed.assert_called_once_with(False)

    def test_saved_suppression_bypasses_both_prompt_and_interface_chooser(self):
        cli_launcher = Mock(return_value=0)
        chooser = Mock()
        tool = SimpleNamespace(suppress_tkinter_startup_prompt=True)

        with (
            patch.object(subtitle_gui, "console_is_interactive", return_value=True),
            patch.object(subtitle_gui, "choose_portable_launch_mode", chooser),
            patch.object(subtitle_gui, "launch_application", cli_launcher),
            patch.object(
                subtitle_gui,
                "ensure_tkinter_for_gui",
                return_value=False,
            ) as preflight,
        ):
            result = subtitle_gui.launch_portable_wrapper(
                Path("/opt/subtitle/SubtitleUniverseSpellcheck.pyw"),
                tool_factory=Mock(return_value=tool),
                platform_name="linux",
                frozen=False,
            )

        self.assertEqual(result, 0)
        preflight.assert_called_once()
        chooser.assert_not_called()
        cli_launcher.assert_called_once_with(["--cli"])

    def test_saved_cli_mode_does_not_require_tkinter(self):
        cli_launcher = Mock(return_value=0)
        preflight = Mock()
        with (
            patch.object(subtitle_gui, "console_is_interactive", return_value=True),
            patch.object(subtitle_gui, "load_portable_launch_mode", return_value="cli"),
            patch.object(subtitle_gui, "choose_portable_launch_mode", return_value="cli"),
            patch.object(subtitle_gui, "ensure_tkinter_for_gui", preflight),
            patch.object(subtitle_gui, "launch_application", cli_launcher),
        ):
            result = subtitle_gui.launch_portable_wrapper(
                Path("/opt/subtitle/SubtitleUniverseSpellcheck.pyw"),
                platform_name="linux",
                frozen=False,
            )

        self.assertEqual(result, 0)
        preflight.assert_not_called()
        cli_launcher.assert_called_once_with(["--cli"])

    def test_direct_posix_gui_launch_falls_back_to_cli_when_preflight_declines(self):
        gui_factory = Mock()
        cli_runner = Mock()
        tool = SimpleNamespace(suppress_tkinter_startup_prompt=False)
        guard = Mock(return_value=False)

        result = subtitle_gui.launch_application(
            [],
            gui_factory=gui_factory,
            cli_runner=cli_runner,
            tool_factory=Mock(return_value=tool),
            tkinter_guard=guard,
            platform_name="linux",
            frozen=False,
            has_console=True,
        )

        self.assertEqual(result, 0)
        guard.assert_called_once()
        cli_runner.assert_called_once_with()
        gui_factory.assert_not_called()

    def test_windows_and_frozen_gui_launches_do_not_construct_preflight_state(self):
        for platform_name, frozen in (("win32", False), ("linux", True)):
            with self.subTest(platform_name=platform_name, frozen=frozen):
                gui = Mock()
                tool_factory = Mock()
                guard = Mock()
                result = subtitle_gui.launch_application(
                    [],
                    gui_factory=Mock(return_value=gui),
                    tool_factory=tool_factory,
                    tkinter_guard=guard,
                    platform_name=platform_name,
                    frozen=frozen,
                )
                self.assertEqual(result, 0)
                gui.run.assert_called_once_with()
                tool_factory.assert_not_called()
                guard.assert_not_called()

    def test_suppression_setting_round_trips_without_becoming_a_normal_option(self):
        root = Path(__file__).with_name("_tkinter_preflight_state")
        options_path = root / "dictionaries" / "options.ini"
        try:
            tool = SubtitleCleanupTool()
            tool.dict_dir = root / "dictionaries"
            tool.options_path = options_path
            tool.set_tkinter_startup_prompt_suppressed(True)

            restored = SubtitleCleanupTool.__new__(SubtitleCleanupTool)
            restored.options_path = tool.options_path
            restored.options = {}
            restored.update_check_preference_confirmed = False
            restored.suppress_tkinter_startup_prompt = False
            restored.load_options()

            self.assertTrue(restored.suppress_tkinter_startup_prompt)
            self.assertNotIn("suppress_tkinter_startup_prompt", restored.options)
        finally:
            options_path.unlink(missing_ok=True)
            if options_path.parent.exists():
                options_path.parent.rmdir()
            if root.exists():
                root.rmdir()


if __name__ == "__main__":
    unittest.main()
