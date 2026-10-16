#!/usr/bin/env python3
"""Cross-platform Tkinter launcher for Subtitle Universe Spellcheck.

The graphical interface is intentionally a thin client over the established
``subtitle_cleanup`` engine. Review work is checkpointed for recovery, while
subtitle changes stay outside source files until the explicit Save action.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

try:
    from .subtitle_cleanup import (
        DEFAULT_OPTIONS,
        CAPITALIZATION_DEPENDENT_OPTIONS,
        CAPITALIZATION_MODES,
        CAPITALIZATION_SCAN_MODES,
        OPTION_DESCRIPTIONS,
        OPTION_GROUPS,
        OPTION_INLINE_EXAMPLES,
        OPTION_LABELS,
        PROJECT_URL,
        ReleaseUpdate,
        SCOWL_CREDIT,
        SCOWL_URL,
        SESSION_LOG_HELP,
        SCRIPT_VERSION,
        SpellcheckIssuePreview,
        SpellcheckReviewPaused,
        SpellcheckReviewSession,
        SubtitleCleanupTool,
        UpdateError,
        application_root,
        count_nonblank_lines,
        install_tkinter_support,
        main as run_cli,
        tkinter_is_available,
        tkinter_preflight_required,
        wait_for_enter_to_customize,
    )
except ImportError:  # Direct execution: python app/subtitle_gui.py
    from subtitle_cleanup import (
        DEFAULT_OPTIONS,
        CAPITALIZATION_DEPENDENT_OPTIONS,
        CAPITALIZATION_MODES,
        CAPITALIZATION_SCAN_MODES,
        OPTION_DESCRIPTIONS,
        OPTION_GROUPS,
        OPTION_INLINE_EXAMPLES,
        OPTION_LABELS,
        PROJECT_URL,
        ReleaseUpdate,
        SCOWL_CREDIT,
        SCOWL_URL,
        SESSION_LOG_HELP,
        SCRIPT_VERSION,
        SpellcheckIssuePreview,
        SpellcheckReviewPaused,
        SpellcheckReviewSession,
        SubtitleCleanupTool,
        UpdateError,
        application_root,
        count_nonblank_lines,
        install_tkinter_support,
        main as run_cli,
        tkinter_is_available,
        tkinter_preflight_required,
        wait_for_enter_to_customize,
    )


LANGUAGE_DISPLAY_NAMES = {
    "american": "American English",
    "british": "British English",
}

ADD_UNIVERSE_LABEL = "Add a universe…"

DETACHED_GUI_ENVIRONMENT_VARIABLE = "SUBTITLE_UNIVERSE_GUI_DETACHED"
LAUNCH_GUI_MARKER = "launch gui.txt"
LAUNCH_CLI_MARKER = "launch cli.txt"
LAUNCH_MODE_CHANGE_SECONDS = 5
WINDOWS_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
UPDATE_CLEANUP_MARKER = Path("dictionaries/pending_update_cleanup.json")


def load_portable_launch_mode(application_root: Path) -> Optional[str]:
    """Read the mutually exclusive portable launcher marker files."""
    gui_exists = (application_root / LAUNCH_GUI_MARKER).is_file()
    cli_exists = (application_root / LAUNCH_CLI_MARKER).is_file()
    if gui_exists == cli_exists:
        return None
    return "gui" if gui_exists else "cli"


def save_portable_launch_mode(application_root: Path, mode: str) -> None:
    """Atomically publish one human-readable launch marker beside the wrapper."""
    if mode not in {"gui", "cli"}:
        raise ValueError(f"Unsupported launch mode: {mode}")
    selected_name = LAUNCH_GUI_MARKER if mode == "gui" else LAUNCH_CLI_MARKER
    other_name = LAUNCH_CLI_MARKER if mode == "gui" else LAUNCH_GUI_MARKER
    selected_path = application_root / selected_name
    temporary_path = selected_path.with_name(selected_path.name + ".tmp")
    temporary_path.write_text(
        "Subtitle Universe Spellcheck portable launch preference.\n"
        f"Saved mode: {mode.upper()}\n"
        "Delete this file to restore the first-run launcher choice.\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, selected_path)
    (application_root / other_name).unlink(missing_ok=True)


def console_is_interactive(stdin=None, stdout=None) -> bool:
    """Return whether the wrapper can safely display prompts and read input."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    try:
        return bool(stdin and stdout and stdin.isatty() and stdout.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def prompt_console_launch_mode(*, input_func=input, output_stream=None) -> str:
    """Require an explicit valid GUI/CLI choice in a terminal."""
    output_stream = output_stream if output_stream is not None else sys.stdout
    while True:
        print("\nChoose how Subtitle Universe Spellcheck should start:", file=output_stream)
        print("1. Graphical interface (GUI)", file=output_stream)
        print("2. Command-line interface (CLI)", file=output_stream)
        choice = input_func("\nChoice: ").strip()
        if choice == "1":
            return "gui"
        if choice == "2":
            return "cli"
        print("Enter 1 or 2.", file=output_stream)


def prompt_gui_launch_mode(
    saved_mode: Optional[str], timeout_seconds: int = LAUNCH_MODE_CHANGE_SECONDS
) -> Optional[str]:
    """Provide the `.pyw` equivalent of the terminal launch-mode prompt."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Subtitle Universe Spellcheck")
    apply_application_window_icon(root, image_factory=tk.PhotoImage)
    root.resizable(False, False)
    result: dict[str, Optional[str]] = {"mode": None}
    pending_after: dict[str, Optional[str]] = {"id": None}
    panel = ttk.Frame(root, padding=20)
    panel.pack(fill="both", expand=True)

    def finish(mode: str) -> None:
        after_id = pending_after["id"]
        if after_id is not None:
            root.after_cancel(after_id)
            pending_after["id"] = None
        result["mode"] = mode
        root.destroy()

    def show_choices(_event=None) -> None:
        after_id = pending_after["id"]
        if after_id is not None:
            root.after_cancel(after_id)
            pending_after["id"] = None
        for child in panel.winfo_children():
            child.destroy()
        ttk.Label(
            panel,
            text="Choose how the application should start:",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Button(
            panel,
            text="1 — Graphical interface (GUI)",
            command=lambda: finish("gui"),
        ).pack(fill="x", pady=4)
        ttk.Button(
            panel,
            text="2 — Command-line interface (CLI)",
            command=lambda: finish("cli"),
        ).pack(fill="x", pady=4)
        root.bind("1", lambda _event: finish("gui"))
        root.bind("2", lambda _event: finish("cli"))

    if saved_mode is None:
        show_choices()
    else:
        display_name = "GUI" if saved_mode == "gui" else "CLI"
        ttk.Label(
            panel,
            text=(
                f"Saved launch mode: {display_name}\n\n"
                f"Starting in {timeout_seconds} seconds. Press Enter or choose "
                "Select again to change it."
            ),
            justify="left",
        ).pack(anchor="w", pady=(0, 12))
        choose_again = ttk.Button(panel, text="Select again", command=show_choices)
        choose_again.pack(fill="x")
        choose_again.focus_set()
        root.bind("<Return>", show_choices)
        pending_after["id"] = root.after(
            max(0, timeout_seconds) * 1000,
            lambda: finish(saved_mode),
        )

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.update_idletasks()
    width = root.winfo_reqwidth()
    height = root.winfo_reqheight()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"+{x}+{y}")
    root.mainloop()
    return result["mode"]


def choose_portable_launch_mode(
    application_root: Path,
    *,
    has_console: Optional[bool] = None,
    input_func=input,
    output_stream=None,
    wait_for_change: Callable[[int], bool] = wait_for_enter_to_customize,
    gui_selector: Callable[[Optional[str], int], Optional[str]] = prompt_gui_launch_mode,
) -> Optional[str]:
    """Choose, persist, or reuse the root `.pyw` launch mode."""
    saved_mode = load_portable_launch_mode(application_root)
    has_console = console_is_interactive() if has_console is None else has_console
    if has_console:
        output_stream = output_stream if output_stream is not None else sys.stdout
        if saved_mode is not None:
            print(
                f"Saved launch mode: {saved_mode.upper()}.\n"
                "Press Enter during the countdown to select GUI or CLI again.",
                file=output_stream,
            )
            if not wait_for_change(LAUNCH_MODE_CHANGE_SECONDS):
                return saved_mode
        selected_mode = prompt_console_launch_mode(
            input_func=input_func,
            output_stream=output_stream,
        )
    else:
        selected_mode = gui_selector(saved_mode, LAUNCH_MODE_CHANGE_SECONDS)
        if selected_mode is None:
            return None
    save_portable_launch_mode(application_root, selected_mode)
    return selected_mode


def should_detach_gui_launcher(
    platform_name: Optional[str] = None,
    environment: Optional[dict[str, str]] = None,
) -> bool:
    """Return whether the .pyw wrapper should spawn a console-free child."""
    platform_name = platform_name if platform_name is not None else sys.platform
    environment = environment if environment is not None else os.environ
    return (
        platform_name != "win32"
        and environment.get(DETACHED_GUI_ENVIRONMENT_VARIABLE) != "1"
    )


def ensure_tkinter_for_gui(
    tool,
    *,
    platform_name: Optional[str] = None,
    frozen: Optional[bool] = None,
    has_console: Optional[bool] = None,
    force_prompt: bool = False,
    input_func=input,
    output_stream=None,
    availability_checker: Callable[[], bool] = tkinter_is_available,
    installer: Callable[..., bool] = install_tkinter_support,
) -> bool:
    """Offer a recoverable CLI path when optional POSIX Tkinter is absent."""
    current_platform = platform_name if platform_name is not None else sys.platform
    if not tkinter_preflight_required(
        platform_name=current_platform,
        frozen=frozen,
    ):
        return True
    output_stream = output_stream if output_stream is not None else sys.stdout
    available = availability_checker()
    if available:
        if getattr(tool, "suppress_tkinter_startup_prompt", False):
            tool.set_tkinter_startup_prompt_suppressed(False)
        return True

    if getattr(tool, "suppress_tkinter_startup_prompt", False) and not force_prompt:
        print(
            "Tkinter GUI support is not installed and its startup question is "
            "disabled. Starting the command-line interface.",
            file=output_stream,
        )
        return False

    has_console = console_is_interactive() if has_console is None else has_console
    if not has_console:
        print(
            "Tkinter GUI support is not installed. Start this launcher from a "
            "terminal to install it; the command-line interface will be used now.",
            file=output_stream,
        )
        return False

    print(
        "\nTkinter GUI support is not installed for this Python interpreter.\n"
        "It is required only for the graphical interface; the command-line "
        "interface remains available.\n",
        file=output_stream,
    )
    while True:
        try:
            answer = input_func(
                "Install Tkinter now? (Y)es, (N)o, or (S)top asking: "
            ).strip().casefold()
        except (EOFError, OSError):
            answer = "n"
        if answer in {"y", "yes", "n", "no", "s", "stop"}:
            break
        print("Enter Y, N, or S.", file=output_stream)

    if answer in {"s", "stop"}:
        tool.set_tkinter_startup_prompt_suppressed(True)
        print(
            "The startup question has been disabled. Starting the command-line "
            "interface. You can retry installation from CLI Options.",
            file=output_stream,
        )
        return False
    if answer in {"n", "no"}:
        print("Starting the command-line interface for this launch.", file=output_stream)
        return False

    if not installer(platform_name=current_platform, output_stream=output_stream):
        return False
    if not availability_checker():
        print(
            "The package manager completed, but this Python interpreter still "
            "cannot import Tkinter. Starting the command-line interface.",
            file=output_stream,
        )
        return False
    if getattr(tool, "suppress_tkinter_startup_prompt", False):
        tool.set_tkinter_startup_prompt_suppressed(False)
    print("Tkinter GUI support is ready.", file=output_stream)
    return True

RECENT_ADDITION_CATEGORIES = ("Words, names, and acronyms", "Substitutions")
RECENT_ADDITION_CATEGORY_WIDTH = (
    max(len(value) for value in RECENT_ADDITION_CATEGORIES) + 2
)

DEFAULT_THEME_NAME = "Ocean"
ACTIVE_THEME_NAME = DEFAULT_THEME_NAME
CUSTOM_THEME_NAME = "Custom"
DARK_THEME_NAME = "Dark"
OCEAN_THEME = {
    "nav": "#0b315c",
    "nav_active": "#174f83",
    "nav_text": "#f5f8fc",
    "nav_rule": "#8fb4d6",
    "surface": "#f4f7fa",
    "card": "#ffffff",
    "border": "#d3dde7",
    "text": "#132c49",
    "option_text": "#102f50",
    "edit_text": "#1d2733",
    "muted": "#64788e",
    "help": "#5d9dcc",
    "accent": "#118ba0",
    "accent_dark": "#087488",
    "selection": "#ffd37a",
    "success": "#218c5a",
    "toggle_off": "#b84a4a",
    "toggle_on": "#2f8f5b",
    "toggle_knob": "#ffffff",
    "toggle_symbol": "#132c49",
    "row_white": "#ffffff",
    "row_light": "#f2f3f5",
    "cue": "#f8fafc",
    "cue_selected": "#fffaf0",
    "context": "#f7f9fc",
    "status": "#e9eff4",
    "tooltip": "#f4f8fc",
    "progress_trough": "#dbe4eb",
    "link": "#075fa6",
    "column_rule": "#b7bcc3",
}
DARK_THEME = {
    "nav": "#08131f",
    "nav_active": "#1e5a78",
    "nav_text": "#f4f7fb",
    "nav_rule": "#5b8fb1",
    "surface": "#151a21",
    "card": "#1e252d",
    "border": "#3a4652",
    "text": "#e8eef5",
    "option_text": "#e8eef5",
    "edit_text": "#171b21",
    "muted": "#aab7c4",
    "help": "#66b6e8",
    "accent": "#21a6b8",
    "accent_dark": "#16889a",
    "selection": "#e3ad49",
    "success": "#37a873",
    "toggle_off": "#b34c55",
    "toggle_on": "#319a69",
    "toggle_knob": "#f4f7fb",
    "toggle_symbol": "#151a21",
    "row_white": "#242c35",
    "row_light": "#2b3540",
    "cue": "#242c35",
    "cue_selected": "#332d22",
    "context": "#242c35",
    "status": "#202832",
    "tooltip": "#26313c",
    "progress_trough": "#343f4b",
    "link": "#70b7ff",
    "column_rule": "#65717d",
}
BUILTIN_THEMES = {
    DEFAULT_THEME_NAME: OCEAN_THEME,
    DARK_THEME_NAME: DARK_THEME,
}
THEME_COLOR_FIELDS = (
    ("surface", "Window background", "Main workspace background behind cards and page headings."),
    ("card", "Panel background", "Background for cards, forms, tables, and card-contained headings."),
    ("text", "Primary text", "Main text and heading color throughout the application."),
    ("muted", "Secondary text", "Supporting descriptions, timestamps, and less prominent information."),
    ("border", "Borders", "Borders around fields, cards, buttons, and other controls."),
    ("nav", "Sidebar background", "Background of the navigation area on the left."),
    ("nav_active", "Selected navigation", "Selected sidebar item and active control highlight."),
    ("nav_text", "Sidebar text", "Text shown in the sidebar and on accent-colored controls."),
    ("nav_rule", "Sidebar separators", "Section headings and horizontal divider lines in the sidebar."),
    ("option_text", "Option text", "Labels used for individual settings on the Options screen."),
    ("edit_text", "Editable text", "Text entered in editable subtitle and maintenance fields."),
    ("help", "Help icons", "Question-mark icons and other contextual-help accents."),
    ("accent", "Primary accent", "Primary action buttons and prominent interactive accents."),
    ("accent_dark", "Pressed accent", "Border and pressed state for primary action buttons."),
    ("selection", "Current issue highlight", "Highlight around the current subtitle and selected spelling issue."),
    ("success", "Progress indicator", "Completed portion of scan progress bars."),
    ("toggle_off", "Switch off track", "Track color for disabled boolean settings; the × remains a non-color cue."),
    ("toggle_on", "Switch on track", "Track color for enabled boolean settings; the ✓ remains a non-color cue."),
    ("toggle_knob", "Switch knob", "Moving circular knob used by boolean setting switches."),
    ("toggle_symbol", "Switch symbol", "Check-mark and × color inside the switch knob."),
    ("row_white", "Alternating row A", "First alternating color used in Options and dictionary tables."),
    ("row_light", "Alternating row B", "Second alternating color used in Options and dictionary tables."),
    ("cue", "Subtitle card", "Background of previous and next subtitle cards."),
    ("cue_selected", "Current subtitle card", "Background of the subtitle currently being reviewed."),
    ("context", "Dictionary context", "Background of Base, Universe, and dictionary-statistic cards."),
    ("status", "Status bar", "Background of the status message along the bottom of the window."),
    ("tooltip", "Tooltip background", "Background of hover help popups."),
    ("progress_trough", "Progress track", "Unfilled portion of scan progress bars."),
    ("link", "Link text", "Clickable web-link color on the About screen."),
    ("column_rule", "Table divider", "Divider between Find and Replace columns in substitution tables."),
)
OPTION_TOOLTIP_HEADING = "Tooltips"
OPTION_SWITCH_COLUMN = 0
OPTION_TOOLTIP_COLUMN = 2
OPTION_NUMERIC_CONTROL_COLUMN = 3
OPTION_SWITCH_COLUMN_WIDTH = 70
OPTION_TOOLTIP_COLUMN_WIDTH = 74
OPTION_NUMERIC_CONTROL_COLUMN_WIDTH = 230
OPTION_RIGHT_ZONE_WIDTH = (
    OPTION_TOOLTIP_COLUMN_WIDTH + OPTION_NUMERIC_CONTROL_COLUMN_WIDTH
)
WINDOW_INITIAL_WIDTH = 1480
WINDOW_INITIAL_HEIGHT = 900
WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 600
NAVIGATION_WIDTH = 238
REVIEW_PANEL_MIN_WIDTH = 700
CONTEXT_PANEL_MIN_WIDTH = 260


def _valid_theme_color(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in (4, 7)
        and value.startswith("#")
        and all(character in "0123456789abcdefABCDEF" for character in value[1:])
    )


def resolve_theme(
    name: str = DEFAULT_THEME_NAME,
    custom_colors: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Return a validated palette without exposing theme choice in the UI yet."""
    if name == CUSTOM_THEME_NAME:
        palette = dict(BUILTIN_THEMES[DEFAULT_THEME_NAME])
        overrides = custom_colors or {}
        unknown = sorted(set(overrides) - set(palette))
        if unknown:
            raise ValueError(f"Unknown theme color key: {unknown[0]}")
        palette.update(overrides)
    else:
        if name not in BUILTIN_THEMES:
            raise ValueError(f"Unknown theme: {name}")
        if custom_colors:
            raise ValueError("Custom colors require the Custom theme")
        palette = dict(BUILTIN_THEMES[name])
    invalid = [key for key, value in palette.items() if not _valid_theme_color(value)]
    if invalid:
        raise ValueError(f"Invalid theme color for {invalid[0]}: {palette[invalid[0]]}")
    return palette


def load_theme_preferences(path: Path) -> tuple[str, dict[str, str]]:
    """Load a portable GUI theme choice, falling back safely to Ocean."""
    selected = DEFAULT_THEME_NAME
    custom = dict(OCEAN_THEME)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return selected, custom
    if isinstance(raw, dict):
        candidate = raw.get("selected")
        if candidate in (*BUILTIN_THEMES, CUSTOM_THEME_NAME):
            selected = candidate
        overrides = raw.get("custom")
        if isinstance(overrides, dict):
            for key in OCEAN_THEME:
                value = overrides.get(key)
                if _valid_theme_color(value):
                    custom[key] = value
    return selected, custom


def theme_preferences_text(selected: str, custom: dict[str, str]) -> str:
    """Validate and serialize the portable GUI theme preference file."""
    if selected not in (*BUILTIN_THEMES, CUSTOM_THEME_NAME):
        raise ValueError("Choose Ocean, Dark, or Custom.")
    resolved_custom = resolve_theme(CUSTOM_THEME_NAME, custom)
    return json.dumps(
        {"selected": selected, "custom": resolved_custom},
        indent=2,
        sort_keys=True,
    ) + "\n"


def theme_seed(name: str) -> dict[str, str]:
    """Return an isolated built-in palette suitable for resetting Custom."""
    if name not in BUILTIN_THEMES:
        raise ValueError("Custom can be reset only from Ocean or Dark.")
    return dict(BUILTIN_THEMES[name])


def theme_change_requires_restart(
    active_name: str,
    active_palette: dict[str, str],
    selected_name: str,
    custom_palette: dict[str, str],
) -> bool:
    """Report whether saved theme data differs from the running palette."""
    desired = resolve_theme(
        selected_name,
        custom_palette if selected_name == CUSTOM_THEME_NAME else None,
    )
    return selected_name != active_name or desired != active_palette


def restart_current_process(
    *,
    executable: Optional[str] = None,
    argv: Optional[Sequence[str]] = None,
    frozen: Optional[bool] = None,
    process_launcher=None,
) -> None:
    """Launch a replacement Python or frozen GUI process."""
    executable = executable or sys.executable
    arguments = list(sys.argv if argv is None else argv)
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    command = [executable, *arguments[1:]] if frozen else [executable, *arguments]
    (process_launcher or subprocess.Popen)(command, close_fds=True)


def dictionary_row_colors(
    palette: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    colors = palette or BUILTIN_THEMES[DEFAULT_THEME_NAME]
    return {
        "dictionary_even": colors["row_light"],
        "dictionary_odd": colors["row_white"],
    }


def option_row_color(
    index: int, palette: Optional[dict[str, str]] = None
) -> str:
    """Return the alternating background used by option setting rows."""
    colors = palette or BUILTIN_THEMES[DEFAULT_THEME_NAME]
    row_colors = (colors["row_white"], colors["row_light"])
    return row_colors[index % len(row_colors)]


def option_toggle_color(
    enabled: bool, palette: Optional[dict[str, str]] = None
) -> str:
    """Return the pill color for a disabled or enabled option."""
    colors = palette or BUILTIN_THEMES[DEFAULT_THEME_NAME]
    return colors["toggle_on" if enabled else "toggle_off"]


def option_toggle_symbol(enabled: bool) -> str:
    """Return a non-color cue for a toggle's current state."""
    return "✓" if enabled else "×"


def preferred_ttk_theme(theme_names: Sequence[str]) -> Optional[str]:
    """Choose a cross-platform ttk engine that honors application colors."""
    available = tuple(theme_names)
    for preferred in ("clam", "alt", "default"):
        if preferred in available:
            return preferred
    return available[0] if available else None


def ttk_style_layer(
    palette: dict[str, str],
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, list[tuple[str, str]]]]]:
    """Build palette-driven ttk configurations and state mappings."""
    configurations = {
        "TFrame": {"background": palette["card"]},
        "TLabel": {
            "background": palette["card"],
            "foreground": palette["text"],
        },
        "CardTitle.TLabel": {
            "background": palette["card"],
            "foreground": palette["text"],
            "font": ("Segoe UI", 18, "bold"),
        },
        "TButton": {
            "background": palette["row_light"],
            "foreground": palette["text"],
            "bordercolor": palette["border"],
            "darkcolor": palette["border"],
            "lightcolor": palette["border"],
            "focuscolor": palette["accent"],
            "padding": (10, 6),
        },
        "TEntry": {
            "fieldbackground": palette["card"],
            "background": palette["card"],
            "foreground": palette["text"],
            "insertcolor": palette["text"],
            "bordercolor": palette["border"],
            "lightcolor": palette["border"],
            "darkcolor": palette["border"],
        },
        "TCombobox": {
            "fieldbackground": palette["card"],
            "background": palette["row_light"],
            "foreground": palette["text"],
            "arrowcolor": palette["text"],
            "bordercolor": palette["border"],
            "lightcolor": palette["border"],
            "darkcolor": palette["border"],
        },
        "Treeview": {
            "background": palette["card"],
            "fieldbackground": palette["card"],
            "foreground": palette["text"],
            "bordercolor": palette["border"],
            "lightcolor": palette["border"],
            "darkcolor": palette["border"],
            "rowheight": 24,
        },
        "Treeview.Heading": {
            "background": palette["row_light"],
            "foreground": palette["text"],
            "bordercolor": palette["border"],
            "lightcolor": palette["border"],
            "darkcolor": palette["border"],
            "relief": "flat",
        },
        "Vertical.TScrollbar": {
            "background": palette["row_light"],
            "troughcolor": palette["card"],
            "arrowcolor": palette["text"],
            "bordercolor": palette["border"],
        },
        "Horizontal.TScrollbar": {
            "background": palette["row_light"],
            "troughcolor": palette["card"],
            "arrowcolor": palette["text"],
            "bordercolor": palette["border"],
        },
        "TSeparator": {"background": palette["border"]},
    }
    mappings = {
        "TButton": {
            "background": [
                ("disabled", palette["surface"]),
                ("pressed", palette["accent_dark"]),
                ("active", palette["nav_active"]),
            ],
            "foreground": [
                ("disabled", palette["muted"]),
                ("pressed", palette["nav_text"]),
                ("active", palette["nav_text"]),
            ],
        },
        "TEntry": {
            "fieldbackground": [("disabled", palette["surface"])],
            "foreground": [("disabled", palette["muted"])],
            "bordercolor": [("focus", palette["accent"])],
        },
        "TCombobox": {
            "fieldbackground": [
                ("disabled", palette["surface"]),
                ("readonly", palette["card"]),
            ],
            "foreground": [("disabled", palette["muted"])],
            "selectbackground": [("readonly", palette["card"])],
            "selectforeground": [("readonly", palette["text"])],
            "bordercolor": [("focus", palette["accent"])],
        },
        "Treeview": {
            "background": [("selected", palette["nav_active"])],
            "foreground": [("selected", palette["nav_text"])],
        },
        "Treeview.Heading": {
            "background": [("active", palette["nav_active"])],
            "foreground": [("active", palette["nav_text"])],
        },
        "Vertical.TScrollbar": {
            "background": [("active", palette["nav_active"])],
        },
        "Horizontal.TScrollbar": {
            "background": [("active", palette["nav_active"])],
        },
    }
    return configurations, mappings


def listbox_theme_options(palette: dict[str, str]) -> dict[str, object]:
    """Return palette-backed options for classic Tk listboxes."""
    return {
        "background": palette["card"],
        "foreground": palette["text"],
        "selectbackground": palette["nav_active"],
        "selectforeground": palette["nav_text"],
        "disabledforeground": palette["muted"],
        "highlightbackground": palette["border"],
        "highlightcolor": palette["accent"],
        "highlightthickness": 1,
        "selectborderwidth": 0,
    }


class OptionToggle:
    """Small keyboard-accessible pill switch backed by a Tk canvas."""

    WIDTH = 56
    HEIGHT = 28

    def __init__(
        self,
        tk,
        parent,
        value: bool,
        command,
        background: str,
        palette: Optional[dict[str, str]] = None,
        enabled: bool = True,
    ):
        self.value = bool(value)
        self.command = command
        self.palette = palette or BUILTIN_THEMES[DEFAULT_THEME_NAME]
        self.enabled = enabled
        self.canvas = tk.Canvas(
            parent,
            width=self.WIDTH,
            height=self.HEIGHT,
            background=background,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=background,
            highlightcolor=self.palette["help"],
            cursor="hand2" if enabled else "arrow",
            takefocus=enabled,
        )
        self.canvas.bind("<Button-1>", self._toggle)
        self.canvas.bind("<space>", self._toggle)
        self.canvas.bind("<Return>", self._toggle)
        self._draw()

    def grid(self, **kwargs) -> None:
        self.canvas.grid(**kwargs)

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = bool(value)
        self._draw()

    def _toggle(self, _event=None):
        if not self.enabled:
            return "break"
        self.set(not self.value)
        if self.command is not None:
            self.command(self)
        return "break"

    def _draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        fill = (
            option_toggle_color(self.value, self.palette)
            if getattr(self, "enabled", True)
            else self.palette["muted"]
        )
        top, bottom = 4, self.HEIGHT - 4
        radius = (bottom - top) // 2
        left, right = 2, self.WIDTH - 2
        canvas.create_oval(left, top, left + radius * 2, bottom, fill=fill, outline=fill)
        canvas.create_rectangle(
            left + radius,
            top,
            right - radius,
            bottom,
            fill=fill,
            outline=fill,
        )
        canvas.create_oval(right - radius * 2, top, right, bottom, fill=fill, outline=fill)
        knob_left = right - radius * 2 + 2 if self.value else left + 2
        canvas.create_oval(
            knob_left,
            top + 2,
            knob_left + (radius * 2) - 4,
            bottom - 2,
            fill=self.palette["toggle_knob"],
            outline=self.palette["toggle_knob"],
        )
        canvas.create_text(
            knob_left + radius - 2,
            (top + bottom) // 2,
            text=option_toggle_symbol(self.value),
            fill=self.palette["toggle_symbol"],
            font=("TkDefaultFont", 9, "bold"),
        )


def elide_cell_text(value: str, pixel_width: int, measure: Callable[[str], int]) -> str:
    """Fit a display value within a cell and mark clipped text with an ellipsis."""
    value = str(value)
    available = max(int(pixel_width) - 12, 0)
    if measure(value) <= available:
        return value
    ellipsis = "…"
    if measure(ellipsis) > available:
        return ""
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = value[:middle].rstrip() + ellipsis
        if measure(candidate) <= available:
            low = middle
        else:
            high = middle - 1
    return value[:low].rstrip() + ellipsis


def dictionary_row_tag(index: int) -> str:
    return "dictionary_even" if index % 2 == 0 else "dictionary_odd"


def dictionary_column_should_stretch(kind: str) -> bool:
    """Substitution columns retain user-selected widths like a spreadsheet."""
    return kind != "substitutions"


def initial_dictionary_column_widths(
    kind: str, viewport_width: int
) -> tuple[int, Optional[int]]:
    """Return window-fitting widths when a dictionary view is newly loaded."""
    minimum = 360 if kind == "substitutions" else 300
    usable = max(int(viewport_width) - 6, minimum)
    if kind == "substitutions":
        first = usable // 2
        return first, usable - first
    return usable, None


def horizontal_scroll_needed(first, last) -> bool:
    try:
        return float(first) > 0.0001 or float(last) < 0.9999
    except (TypeError, ValueError):
        return False


def option_tooltip_position() -> dict[str, object]:
    """Return the fixed position used by every Options tooltip marker."""
    return {
        "x": OPTION_TOOLTIP_COLUMN_WIDTH // 2,
        "rely": 0.5,
        "anchor": "center",
    }


def update_auto_hiding_scrollbar(scrollbar, first, last) -> None:
    scrollbar.set(first, last)
    if horizontal_scroll_needed(first, last):
        scrollbar.grid()
    else:
        scrollbar.grid_remove()


def universe_selector_values(universes: Sequence[str]) -> tuple[str, ...]:
    return (
        ADD_UNIVERSE_LABEL,
        "No universe",
        *sorted(universes, key=str.casefold),
    )


BASE_LANGUAGE_HELP = (
    "American English uses US spellings such as color and center.\n\n"
    "British English uses spellings such as colour and centre. It accepts both "
    "standard British -ise and Oxford British -ize forms, such as organise / "
    "organize and realise / realize."
)

STANDARD_UNIVERSE_HELP = (
    "Standard spellcheck does not load a Universe Dictionary. Select Universe "
    "spellcheck in the left pane if you want to enable Universe selection."
)

ACRONYM_HELP = (
    "Acronyms use authoritative casing. If the same spelling is already a word or name, "
    "the program will warn before adding it as an acronym.\n\n"
    "AM and PM are already handled contextually in time expressions and cannot "
    "be added to an acronym dictionary."
)

WINDOWS_APP_ID = "gearheart89.SubtitleUniverseSpellcheck"
APPLICATION_ICON_RELATIVE_PATH = Path("assets/subtitle-universe-quill.png")


def configure_windows_app_identity(
    *, platform: Optional[str] = None, setter=None
) -> bool:
    """Give Windows a stable app identity so the taskbar uses the window icon."""
    active_platform = platform or sys.platform
    if active_platform != "win32":
        return False
    try:
        if setter is None:
            import ctypes

            setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        return False
    return True


def apply_application_window_icon(
    window,
    *,
    icon_path: Optional[Path] = None,
    image_factory=None,
) -> bool:
    """Apply and retain the project-owned cross-platform quill window icon."""
    path = Path(icon_path or (application_root() / APPLICATION_ICON_RELATIVE_PATH))
    if not path.is_file():
        return False
    try:
        if image_factory is None:
            import tkinter as tk

            image_factory = tk.PhotoImage
        image = image_factory(file=os.fspath(path))
        window.iconphoto(True, image)
        window._subtitle_universe_icon = image
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def centered_child_position(
    parent_bounds: tuple[int, int, int, int],
    child_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> tuple[int, int]:
    """Return a parent-centered child position kept within the visible screen."""
    parent_x, parent_y, parent_width, parent_height = parent_bounds
    child_width, child_height = child_size
    screen_width, screen_height = screen_size
    x = parent_x + ((parent_width - child_width) // 2)
    y = parent_y + ((parent_height - child_height) // 2)
    # Clamp on the primary screen. Preserve relative centering for windows on
    # secondary monitors, whose coordinates can sit outside this screen size.
    if 0 <= parent_x < screen_width and 0 <= parent_y < screen_height:
        x = max(0, min(x, max(0, screen_width - child_width)))
        y = max(0, min(y, max(0, screen_height - child_height)))
    return x, y


def recent_destination_options(
    event: dict, universes: Sequence[str]
) -> list[tuple[str, str, Optional[str], Optional[str]]]:
    """Return GUI move destinations, excluding the entry's current location."""
    options = []
    current_target = event.get("target")
    current_language = event.get("base_language")
    for language in ("american", "british"):
        if current_target == "user" and current_language == language:
            continue
        options.append(
            (
                f"User — {language_display_name(language)}",
                "user",
                None,
                language,
            )
        )
    current_universe = str(event.get("universe") or "").casefold()
    for universe in sorted(universes, key=str.casefold):
        if current_target == "universe" and universe.casefold() == current_universe:
            continue
        options.append((f"Universe — {universe}", "universe", universe, None))
    return options


def recent_destination_groups(
    event_or_events, universes: Sequence[str]
) -> dict[str, list[tuple[str, str, Optional[str], Optional[str]]]]:
    """Group valid move destinations for the GUI's target-first picker."""
    events = (
        [event_or_events]
        if isinstance(event_or_events, dict)
        else list(event_or_events)
    )
    groups: dict[
        str, list[tuple[str, str, Optional[str], Optional[str]]]
    ] = {"user": [], "universe": []}
    if not events:
        return groups
    for _label, target, universe, language in recent_destination_options({}, universes):
        is_current = any(
            (
                target == "user"
                and event.get("target") == "user"
                and event.get("base_language") == language
            )
            or (
                target == "universe"
                and event.get("target") == "universe"
                and str(event.get("universe") or "").casefold()
                == str(universe or "").casefold()
            )
            for event in events
        )
        if is_current:
            continue
        display = language_display_name(language) if language else str(universe)
        groups[target].append((display, target, universe, language))
    return groups


def table_selection_entries(selection: Sequence[str], entries: Sequence):
    """Resolve all selected Treeview row identifiers to their backing entries."""
    return [entries[int(item)] for item in selection]


def language_display_name(value: str) -> str:
    return LANGUAGE_DISPLAY_NAMES.get(value.casefold(), value)


def language_key(value: str) -> str:
    folded = value.casefold()
    for key, label in LANGUAGE_DISPLAY_NAMES.items():
        if folded in {key, label.casefold()}:
            return key
    return "american"


@dataclass(frozen=True)
class ScanPreview:
    file_count: int
    cue_count: int
    file_name: str
    previous_text: str
    current_text: str
    next_text: str
    timestamp: str


def build_scan_preview(
    files: Sequence[Path], tool: Optional[SubtitleCleanupTool] = None
) -> ScanPreview:
    """Return a read-only preview of the first subtitle file and cues."""
    if not files:
        return ScanPreview(0, 0, "", "", "", "", "")
    active_tool = tool or SubtitleCleanupTool()
    first_path = Path(files[0])
    blocks = active_tool.parse_srt(first_path)
    current = blocks[0] if blocks else None
    following = blocks[1] if len(blocks) > 1 else None
    return ScanPreview(
        file_count=len(files),
        cue_count=len(blocks),
        file_name=first_path.name,
        previous_text="No previous subtitle.",
        current_text="\n".join(current.text_lines) if current else "No subtitle text.",
        next_text="\n".join(following.text_lines) if following else "No next subtitle.",
        timestamp=current.timestamp.strip() if current else "",
    )


def scan_progress_percent(
    phase: str,
    file_number: int,
    total_files: int,
    subtitle_number: int,
    total_subtitles: int,
) -> int:
    """Map per-file preparation/spellcheck passes to monotonic percent."""
    safe_total_files = max(1, total_files)
    completed_file_fraction = (max(1, file_number) - 1) / safe_total_files
    cue_fraction = min(1.0, subtitle_number / max(1, total_subtitles))
    if phase == "Formatting":
        phase_fraction = cue_fraction
    else:
        phase_fraction = (
            cue_fraction * 0.5
            if phase == "Preparing"
            else 0.5 + (cue_fraction * 0.5)
        )
    return round(
        min(1.0, completed_file_fraction + phase_fraction / safe_total_files) * 100
    )


class SubtitleSpellcheckGUI:
    """Native Tkinter shell backed by :class:`SubtitleCleanupTool`."""

    COLORS = resolve_theme()

    def __init__(
        self,
        tool: Optional[SubtitleCleanupTool] = None,
        *,
        theme_name: Optional[str] = None,
        custom_theme: Optional[dict[str, str]] = None,
    ) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog, messagebox, ttk
        except ImportError as error:  # pragma: no cover - platform installation issue
            raise RuntimeError(
                "Tkinter is not installed. On Debian/Ubuntu install python3-tk; "
                "on Fedora install python3-tkinter."
            ) from error

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.tool = tool or SubtitleCleanupTool()
        self.theme_settings_path = self.tool.dict_dir / "gui_theme.json"
        saved_theme_name, saved_custom_theme = load_theme_preferences(
            self.theme_settings_path
        )
        self.theme_name = theme_name or saved_theme_name
        self.saved_custom_theme = dict(custom_theme or saved_custom_theme)
        self.COLORS = resolve_theme(
            self.theme_name,
            self.saved_custom_theme if self.theme_name == CUSTOM_THEME_NAME else None,
        )
        self.active_theme_name = self.theme_name
        self.active_theme_palette = dict(self.COLORS)
        configure_windows_app_identity()
        self.root = tk.Tk()
        self.root.title(f"Subtitle Universe Spellcheck {SCRIPT_VERSION}")
        apply_application_window_icon(self.root, image_factory=tk.PhotoImage)
        self.root.geometry(f"{WINDOW_INITIAL_WIDTH}x{WINDOW_INITIAL_HEIGHT}")
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.root.configure(background=self.COLORS["surface"])

        self.scan_mode = tk.StringVar(value="universe")
        self.folder_value = tk.StringVar(value=str(self.tool.script_dir))
        self.language_value = tk.StringVar(value=language_display_name("american"))
        self.universe_value = tk.StringVar(value="No universe")
        self._selected_universe = "No universe"
        self.file_progress = tk.StringVar(value="File 0 of 0")
        self.cue_progress = tk.StringVar(value="Subtitle 0 of 0")
        self.progress_percent = tk.StringVar(value="0%")
        self.scan_button_text = tk.StringVar(value="Start scan")
        self.restore_backup_tooltip = tk.StringVar(
            value="Choose a subtitle folder to look for backup_subtitles.zip archives."
        )
        self.file_label = tk.StringVar(value="Choose a folder, then prepare a scan.")
        self.review_title = tk.StringVar(value="Scan preparation")
        self.current_timestamp = tk.StringVar(value="")
        self.previous_card_title = tk.StringVar(value="Previous subtitle")
        self.current_card_title = tk.StringVar(value="Current subtitle")
        self.next_card_title = tk.StringVar(value="Next subtitle")
        self.status_value = tk.StringVar(
            value="Ready • Read-only preparation • No subtitle files changed"
        )
        self.base_context = tk.StringVar(value="American English")
        self.universe_context = tk.StringVar(value="None")
        self.universe_words = tk.StringVar(value="0")
        self.universe_names = tk.StringVar(value="0")
        self.universe_acronyms = tk.StringVar(value="0")
        self.universe_substitutions = tk.StringVar(value="0")
        self.nav_buttons = {}
        self.active_navigation_key: Optional[str] = None
        self.theme_draft_is_dirty: Optional[Callable[[], bool]] = None
        self.save_theme_draft: Optional[Callable[[], bool]] = None
        self.suggestion_buttons = []
        self.prepare_queue = None
        self.prepare_thread = None
        self.update_queue = queue.Queue()
        self.update_thread = None
        self.update_installing = False
        self.review_session: Optional[SpellcheckReviewSession] = None
        self.current_issue: Optional[SpellcheckIssuePreview] = None
        self.pending_action: Optional[str] = None
        self.pending_replacement: Optional[str] = None
        self.editing_cue = False
        self.scan_paused = False
        self._saved_capitalization_mode = self.tool.options.get(
            "capitalization_mode", "ask_always"
        )
        self._temporary_capitalization_mode = False
        self.pause_requested = threading.Event()
        self.stop_requested = threading.Event()

        self._configure_styles()
        self._build_window()
        self.folder_value.trace_add(
            "write", lambda *_args: self.root.after_idle(self._refresh_backup_restore_control)
        )
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)
        self._refresh_universes()
        self._select_mode("universe")
        self._refresh_backup_restore_control()
        self.root.after(0, self._complete_startup)

    def _configure_styles(self) -> None:
        ttk = self.ttk
        style = ttk.Style(self.root)
        theme_engine = preferred_ttk_theme(style.theme_names())
        if theme_engine is not None:
            style.theme_use(theme_engine)
        configurations, mappings = ttk_style_layer(self.COLORS)
        for style_name, options in configurations.items():
            style.configure(style_name, **options)
        for style_name, options in mappings.items():
            style.map(style_name, **options)
        popdown = listbox_theme_options(self.COLORS)
        for option_name in (
            "background",
            "foreground",
            "selectbackground",
            "selectforeground",
        ):
            self.root.option_add(
                f"*TCombobox*Listbox.{option_name}",
                popdown[option_name],
            )
        style.configure("App.TFrame", background=self.COLORS["surface"])
        style.configure("Card.TFrame", background=self.COLORS["card"])
        style.configure(
            "Title.TLabel",
            background=self.COLORS["surface"],
            foreground=self.COLORS["text"],
            font=("Segoe UI", 18, "bold"),
        )
        style.configure(
            "Heading.TLabel",
            background=self.COLORS["card"],
            foreground=self.COLORS["text"],
            font=("Segoe UI", 11, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background=self.COLORS["card"],
            foreground=self.COLORS["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel",
            background=self.COLORS["card"],
            foreground=self.COLORS["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Help.TLabel",
            background=self.COLORS["card"],
            foreground=self.COLORS["help"],
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Accent.TButton",
            background=self.COLORS["accent"],
            foreground=self.COLORS["nav_text"],
            bordercolor=self.COLORS["accent_dark"],
            lightcolor=self.COLORS["accent_dark"],
            darkcolor=self.COLORS["accent_dark"],
            font=("Segoe UI", 10, "bold"),
            padding=(14, 9),
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", self.COLORS["surface"]),
                ("pressed", self.COLORS["accent_dark"]),
                ("active", self.COLORS["nav_active"]),
            ],
            foreground=[
                ("disabled", self.COLORS["muted"]),
                ("!disabled", self.COLORS["nav_text"]),
            ],
        )
        style.configure("Tool.TButton", font=("Segoe UI", 9), padding=(10, 7))
        style.configure("Large.TEntry", padding=(9, 8), font=("Segoe UI", 11))
        style.configure(
            "App.Horizontal.TProgressbar",
            troughcolor=self.COLORS["progress_trough"],
            background=self.COLORS["success"],
        )

    def _build_window(self) -> None:
        tk, ttk = self.tk, self.ttk
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        nav = tk.Frame(self.root, bg=self.COLORS["nav"], width=NAVIGATION_WIDTH)
        nav.grid(row=0, column=0, sticky="nsew")
        nav.grid_propagate(False)
        tk.Label(
            nav,
            text="Subtitle Universe\nSpellcheck",
            bg=self.COLORS["nav"],
            fg="white",
            font=("Segoe UI", 15, "bold"),
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=22, pady=(22, 18))

        self._nav_heading(nav, "SUBTITLE SCAN")
        self._nav_button(nav, "formatting", "Formatting only")
        self._nav_button(nav, "standard", "Standard spellcheck")
        self._nav_button(nav, "universe", "Universe spellcheck")
        self._nav_heading(nav, "DICTIONARIES")
        self._nav_button(
            nav,
            "user_dictionary",
            "User dictionary",
            command=lambda: self._open_dictionary_maintenance("user"),
        )
        self._nav_button(
            nav,
            "universe_dictionary",
            "Universe dictionary",
            command=lambda: self._open_dictionary_maintenance("universe"),
        )
        self._nav_button(
            nav, "recent", "Recent additions", command=self._show_recent_additions
        )
        self._nav_heading(nav, "SETTINGS")
        self._nav_button(nav, "options", "Options", command=self._show_options)
        self._nav_button(nav, "themes", "Themes", command=self._show_themes)
        self._nav_button(nav, "about", "About", command=self._show_about)
        self._nav_button(
            nav,
            "session_log",
            "Flush session log",
            command=self._show_session_log_maintenance,
        )

        content = ttk.Frame(self.root, style="App.TFrame", padding=18)
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self.scan_view = ttk.Frame(content, style="App.TFrame")
        self.scan_view.grid(row=0, column=0, sticky="nsew")
        self.scan_view.columnconfigure(0, weight=1)
        self.scan_view.rowconfigure(0, weight=1)
        self.scan_canvas = tk.Canvas(
            self.scan_view,
            background=self.COLORS["surface"],
            borderwidth=0,
            highlightthickness=0,
        )
        self.scan_canvas.grid(row=0, column=0, sticky="nsew")
        self.scan_horizontal_scrollbar = ttk.Scrollbar(
            self.scan_view,
            orient="horizontal",
            command=self.scan_canvas.xview,
        )
        self.scan_vertical_scrollbar = ttk.Scrollbar(
            self.scan_view,
            orient="vertical",
            command=self.scan_canvas.yview,
        )
        self.scan_canvas.configure(
            xscrollcommand=self.scan_horizontal_scrollbar.set,
            yscrollcommand=self.scan_vertical_scrollbar.set,
        )

        self.scan_workspace = ttk.Frame(self.scan_canvas, style="App.TFrame")
        self.scan_workspace.columnconfigure(0, weight=1)
        self.scan_workspace.rowconfigure(2, weight=1)
        self.scan_window_id = self.scan_canvas.create_window(
            (0, 0), window=self.scan_workspace, anchor="nw"
        )
        self._build_toolbar(self.scan_workspace)
        self._build_progress(self.scan_workspace)

        workspace = ttk.Frame(self.scan_workspace, style="App.TFrame")
        workspace.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        workspace.columnconfigure(0, weight=1, minsize=REVIEW_PANEL_MIN_WIDTH)
        workspace.columnconfigure(1, minsize=CONTEXT_PANEL_MIN_WIDTH)
        workspace.rowconfigure(0, weight=1)
        self._build_review_panel(workspace)
        self._build_context_panel(workspace)
        self.scan_workspace.bind("<Configure>", self._update_scan_scrollbars)
        self.scan_canvas.bind("<Configure>", self._update_scan_scrollbars)
        self.root.after_idle(self._update_scan_scrollbars)

        self.maintenance_workspace = ttk.Frame(content, style="App.TFrame")
        self.maintenance_workspace.grid(row=0, column=0, sticky="nsew")
        self.maintenance_workspace.grid_remove()
        self._build_status_bar(content, row=1)

    def _update_scan_scrollbars(self, _event=None) -> None:
        """Keep scan controls readable and expose overflow only when needed."""
        viewport_width = max(1, self.scan_canvas.winfo_width())
        viewport_height = max(1, self.scan_canvas.winfo_height())
        requested_width = max(
            self.scan_workspace.winfo_reqwidth(),
            REVIEW_PANEL_MIN_WIDTH + CONTEXT_PANEL_MIN_WIDTH + 12,
        )
        requested_height = self.scan_workspace.winfo_reqheight()
        content_width = max(viewport_width, requested_width)
        content_height = max(viewport_height, requested_height)
        self.scan_canvas.itemconfigure(
            self.scan_window_id,
            width=content_width,
            height=content_height,
        )
        self.scan_canvas.configure(
            scrollregion=(0, 0, content_width, content_height)
        )
        if requested_width > viewport_width:
            self.scan_horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        else:
            self.scan_horizontal_scrollbar.grid_remove()
            self.scan_canvas.xview_moveto(0)
        if requested_height > viewport_height:
            self.scan_vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.scan_vertical_scrollbar.grid_remove()
            self.scan_canvas.yview_moveto(0)

    def _nav_heading(self, parent, text: str) -> None:
        self.tk.Frame(parent, bg=self.COLORS["nav_rule"], height=1).pack(
            fill="x", padx=0, pady=(4, 0)
        )
        self.tk.Label(
            parent,
            text=text,
            bg=self.COLORS["nav"],
            fg=self.COLORS["nav_rule"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(17, 6))

    def _nav_button(
        self, parent, key: str, label: str, planned: bool = False, command=None
    ) -> None:
        callback = command or (
            (lambda selected_label=label: self._show_planned_feature(selected_label))
            if planned
            else (lambda selected_key=key: self._select_mode(selected_key))
        )
        def guarded_callback() -> None:
            if self._confirm_theme_navigation(key):
                callback()

        button = self.tk.Button(
            parent,
            text=label,
            command=guarded_callback,
            bg=self.COLORS["nav"],
            fg=self.COLORS["nav_text"],
            activebackground=self.COLORS["nav_active"],
            activeforeground=self.COLORS["nav_text"],
            relief="flat",
            bd=0,
            font=("Segoe UI", 10),
            anchor="w",
            padx=22,
            pady=10,
            cursor="hand2",
        )
        button.pack(fill="x")
        self.nav_buttons[key] = button

    def _attach_tooltip(self, widget, text) -> None:
        """Attach a delayed hover tooltip without adding runtime dependencies."""
        state = {"after": None, "window": None}

        def hide(_event=None):
            if state["after"] is not None:
                widget.after_cancel(state["after"])
                state["after"] = None
            if state["window"] is not None:
                state["window"].destroy()
                state["window"] = None

        def show():
            state["after"] = None
            if state["window"] is not None:
                return
            window = self.tk.Toplevel(widget)
            window.wm_overrideredirect(True)
            window.wm_geometry(
                f"+{widget.winfo_rootx() + 18}+{widget.winfo_rooty() + 22}"
            )
            tooltip_text = text.get() if hasattr(text, "get") else (
                text() if callable(text) else text
            )
            self.tk.Label(
                window,
                text=tooltip_text,
                justify="left",
                wraplength=390,
                bg=self.COLORS["tooltip"],
                fg=self.COLORS["text"],
                relief="solid",
                borderwidth=1,
                padx=10,
                pady=8,
                font=("Segoe UI", 9),
            ).pack()
            state["window"] = window

        def schedule(_event=None):
            hide()
            state["after"] = widget.after(350, show)

        widget.bind("<Enter>", schedule, add="+")
        widget.bind("<Leave>", hide, add="+")
        widget.bind("<ButtonPress>", hide, add="+")
        widget._subtitle_tooltip_state = state

    def _help_icon(self, parent, text: str):
        icon = self.ttk.Label(
            parent,
            text="?",
            style="Help.TLabel",
            cursor="question_arrow",
        )
        self._attach_tooltip(icon, text)
        return icon

    def _language_help_icon(self, parent):
        return self._help_icon(parent, BASE_LANGUAGE_HELP)

    def _build_toolbar(self, parent) -> None:
        ttk = self.ttk
        toolbar = ttk.Frame(parent, style="Card.TFrame", padding=14)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        toolbar.columnconfigure(5, weight=1)

        ttk.Label(toolbar, text="Folder", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(toolbar, textvariable=self.folder_value).grid(
            row=0, column=1, sticky="ew", padx=(8, 6)
        )
        ttk.Button(toolbar, text="Browse…", command=self._browse_folder).grid(
            row=0, column=2, padx=(0, 16)
        )
        language_heading = ttk.Frame(toolbar, style="Card.TFrame")
        language_heading.grid(row=0, column=3)
        ttk.Label(
            language_heading, text="Language", style="Heading.TLabel"
        ).pack(side="left")
        self._language_help_icon(language_heading).pack(side="left", padx=(5, 0))
        language = ttk.Combobox(
            toolbar,
            textvariable=self.language_value,
            values=tuple(LANGUAGE_DISPLAY_NAMES.values()),
            state="readonly",
            width=17,
        )
        language.grid(row=0, column=4, padx=(8, 16))
        language.bind("<<ComboboxSelected>>", lambda _event: self._refresh_context())
        universe_heading = ttk.Frame(toolbar, style="Card.TFrame")
        universe_heading.grid(row=0, column=5, sticky="e")
        ttk.Label(
            universe_heading, text="Universe", style="Heading.TLabel"
        ).pack(side="left")
        self.universe_help_icon = self._help_icon(
            universe_heading, STANDARD_UNIVERSE_HELP
        )
        self.universe_help_icon.pack_forget()
        self.universe_combo = ttk.Combobox(
            toolbar,
            textvariable=self.universe_value,
            state="readonly",
            width=24,
        )
        self.universe_combo.grid(row=0, column=6, padx=(8, 12))
        self.universe_combo.bind(
            "<<ComboboxSelected>>", self._on_universe_selected
        )
        self.prepare_button = ttk.Button(
            toolbar,
            textvariable=self.scan_button_text,
            style="Accent.TButton",
            command=self._start_or_resume_scan,
        )
        self.prepare_button.grid(row=1, column=5, sticky="e", pady=(10, 0))
        self.pause_button = ttk.Button(
            toolbar,
            text="Pause scan",
            command=self._request_pause,
            state="disabled",
        )
        self.pause_button.grid(row=1, column=6, padx=(8, 0), pady=(10, 0))
        self.stop_button = ttk.Button(
            toolbar,
            text="Stop scan",
            command=self._request_stop,
            state="disabled",
        )
        self.stop_button.grid(row=1, column=7, padx=(8, 0), pady=(10, 0))
        self.save_button = ttk.Button(
            toolbar,
            text="Save changes",
            command=self._save_review_changes,
            state="disabled",
        )
        self.save_button.grid(row=1, column=4, sticky="e", pady=(10, 0))
        self.restore_backup_button = ttk.Button(
            toolbar,
            text="Restore backup…",
            command=self._restore_subtitles_from_backup,
            state="disabled",
        )
        self.restore_backup_button.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        self._attach_tooltip(
            self.restore_backup_button, self.restore_backup_tooltip
        )

    def _build_progress(self, parent) -> None:
        ttk = self.ttk
        progress = ttk.Frame(parent, style="Card.TFrame", padding=(16, 10))
        progress.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        progress.columnconfigure(2, weight=1)
        ttk.Label(progress, textvariable=self.file_progress, style="Body.TLabel").grid(row=0, column=0)
        ttk.Label(progress, textvariable=self.cue_progress, style="Body.TLabel").grid(
            row=0, column=1, padx=(28, 18)
        )
        self.progress = ttk.Progressbar(
            progress, mode="determinate", maximum=100, style="App.Horizontal.TProgressbar"
        )
        self.progress.grid(row=0, column=2, sticky="ew")
        ttk.Label(progress, textvariable=self.progress_percent, style="Body.TLabel").grid(
            row=0, column=3, padx=(12, 0)
        )

    def _build_review_panel(self, parent) -> None:
        ttk = self.ttk
        panel = ttk.Frame(parent, style="Card.TFrame", padding=20)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        panel.columnconfigure(0, weight=1)
        ttk.Label(
            panel, textvariable=self.review_title, style="CardTitle.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(panel, textvariable=self.file_label, style="Body.TLabel").grid(
            row=1, column=0, sticky="w", pady=(3, 14)
        )

        self.previous_box = self._cue_card(panel, 2, self.previous_card_title)
        self.current_box = self._cue_card(
            panel, 3, self.current_card_title, selected=True
        )
        self.next_box = self._cue_card(panel, 4, self.next_card_title)

        ttk.Label(panel, text="Suggestions", style="Heading.TLabel").grid(
            row=5, column=0, sticky="w", pady=(16, 8)
        )
        suggestions = ttk.Frame(panel, style="Card.TFrame")
        suggestions.grid(row=6, column=0, sticky="ew")
        for index in range(6):
            suggestions.columnconfigure(index, weight=1)
            button = ttk.Button(
                suggestions,
                text="—",
                state="disabled",
                command=lambda suggestion_index=index: self._choose_suggestion(
                    suggestion_index
                ),
            )
            button.grid(
                row=0, column=index, sticky="ew", padx=(0 if index == 0 else 4, 0)
            )
            self.suggestion_buttons.append(button)

        ttk.Label(panel, text="Actions", style="Heading.TLabel").grid(
            row=7, column=0, sticky="w", pady=(16, 8)
        )
        actions = ttk.Frame(panel, style="Card.TFrame")
        actions.grid(row=8, column=0, sticky="ew")
        action_labels = (
            "Edit / Substitute", "Ignore", "Add word / name / acronym / phrase", "Search line", "Undo"
        )
        self.action_buttons = {}
        for column, label in enumerate(action_labels):
            button = ttk.Button(actions, text=label, state="disabled")
            if label == "Edit / Substitute":
                button.configure(command=self._begin_or_cancel_cue_edit)
                self.edit_button = button
            elif label == "Ignore":
                button.configure(command=self._choose_ignore)
                self.ignore_button = button
            elif label == "Add word / name / acronym / phrase":
                button.configure(command=self._open_dictionary_dialog)
                self.add_dictionary_button = button
            elif label == "Search line":
                button.configure(command=self._search_current_line)
                self.search_button = button
            elif label == "Undo":
                button.configure(command=self._undo_last_action)
                self.undo_button = button
            button.grid(
                row=0, column=column, padx=(0 if column == 0 else 5, 0), sticky="ew"
            )
            self.action_buttons[label] = button
            actions.columnconfigure(column, weight=1)

        ttk.Label(panel, text="Apply to", style="Heading.TLabel").grid(
            row=9, column=0, sticky="w", pady=(16, 8)
        )
        scopes = ttk.Frame(panel, style="Card.TFrame")
        scopes.grid(row=10, column=0, sticky="ew")
        self.scope_buttons = {}
        for column, label in enumerate(("This time", "This session", "This universe", "Always")):
            button = ttk.Button(scopes, text=label, state="disabled", width=17)
            if label == "This time":
                button.configure(command=self._apply_this_time)
                self.this_time_button = button
            elif label == "This session":
                button.configure(command=self._apply_this_session)
                self.this_session_button = button
            elif label == "This universe":
                button.configure(
                    command=lambda: self._apply_replacement_scope("universe")
                )
                self.this_universe_button = button
            elif label == "Always":
                button.configure(
                    command=lambda: self._apply_replacement_scope("always")
                )
                self.always_button = button
            button.grid(
                row=0,
                column=column,
                padx=(0 if column == 0 else 5, 0),
                sticky="ew",
            )
            scopes.columnconfigure(column, weight=1)
            self.scope_buttons[label] = button

    def _cue_card(self, parent, row: int, title: str, selected: bool = False):
        frame = self.tk.Frame(
            parent,
            bg=self.COLORS["cue_selected"] if selected else self.COLORS["cue"],
            highlightbackground=self.COLORS["selection"] if selected else self.COLORS["border"],
            highlightthickness=2 if selected else 1,
            padx=12,
            pady=9,
        )
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)
        self.tk.Label(
            frame,
            textvariable=title,
            bg=frame["bg"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 9, "bold"),
            width=18,
            anchor="w",
        ).grid(row=0, column=0, sticky="nw")
        text_row = 0
        if selected:
            self.tk.Label(
                frame,
                textvariable=self.current_timestamp,
                bg=frame["bg"],
                fg=self.COLORS["muted"],
                font=("Segoe UI", 10),
                anchor="w",
            ).grid(row=0, column=1, sticky="ew", pady=(0, 3))
            text_row = 1
        text_widget = self.tk.Text(
            frame,
            bg=frame["bg"],
            fg=self.COLORS["text"],
            font=("Segoe UI", 12 if selected else 10),
            wrap="word",
            height=3 if selected else 2,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=0,
            pady=0,
        )
        text_widget.insert("1.0", "—")
        text_widget.configure(state="disabled")
        text_widget.grid(row=text_row, column=1, sticky="ew")
        return text_widget

    def _build_context_panel(self, parent) -> None:
        ttk = self.ttk
        panel = ttk.Frame(parent, style="Card.TFrame", padding=16)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="Dictionary context", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        self._context_value(panel, 1, "Base", self.base_context)
        self._context_value(panel, 2, "Universe", self.universe_context)
        ttk.Label(panel, text="Universe contents", style="Heading.TLabel").grid(
            row=3, column=0, sticky="w", pady=(18, 8)
        )
        self._stat_row(panel, 4, "Words", self.universe_words)
        self._stat_row(panel, 5, "Names", self.universe_names)
        self._stat_row(panel, 6, "Acronyms", self.universe_acronyms)
        self._stat_row(panel, 7, "Substitutions", self.universe_substitutions)
        ttk.Separator(panel).grid(row=8, column=0, sticky="ew", pady=18)
        ttk.Label(
            panel,
            text=(
                "The GUI prepares subtitles in memory. Suggestions support all "
                "applicable replacement scopes; complete cue edits support This "
                "time. Ignore supports This time or This session. Formatting Only "
                "runs the complete formatter and reports validation findings. "
                "Save changes uses drift checks, grouped backups, and atomic writes."
            ),
            style="Muted.TLabel",
            wraplength=230,
            justify="left",
        ).grid(row=9, column=0, sticky="nw")

    def _context_value(self, parent, row: int, label: str, variable) -> None:
        card = self.tk.Frame(parent, bg=self.COLORS["context"], padx=10, pady=8)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        self.tk.Label(
            card, text=label, bg=self.COLORS["context"], fg=self.COLORS["muted"], font=("Segoe UI", 8, "bold")
        ).pack(anchor="w")
        self.tk.Label(
            card, textvariable=variable, bg=self.COLORS["context"], fg=self.COLORS["text"], font=("Segoe UI", 10)
        ).pack(anchor="w")

    def _stat_row(self, parent, row: int, label: str, variable) -> None:
        frame = self.tk.Frame(parent, bg=self.COLORS["context"], padx=10, pady=7)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 1))
        frame.columnconfigure(0, weight=1)
        self.tk.Label(frame, text=label, bg=self.COLORS["context"], fg=self.COLORS["text"]).grid(row=0, column=0, sticky="w")
        self.tk.Label(
            frame, textvariable=variable, bg=self.COLORS["context"], fg=self.COLORS["text"], font=("Segoe UI", 9, "bold")
        ).grid(row=0, column=1, sticky="e")

    def _build_status_bar(self, parent, row: int = 3) -> None:
        bar = self.tk.Frame(parent, bg=self.COLORS["status"], padx=10, pady=7)
        bar.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        self.tk.Label(
            bar,
            textvariable=self.status_value,
            bg=self.COLORS["status"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x")

    def _select_mode(self, mode: str) -> None:
        self.maintenance_workspace.grid_remove()
        self.scan_view.grid()
        self.scan_mode.set(mode)
        self._activate_navigation(mode)
        universe_enabled = mode == "universe"
        self.universe_combo.configure(state="readonly" if universe_enabled else "disabled")
        if hasattr(self, "universe_help_icon"):
            if mode == "standard":
                self.universe_help_icon.pack(side="left", padx=(5, 0))
            else:
                self.universe_help_icon.pack_forget()
        if not universe_enabled:
            self.universe_value.set("No universe")
            self._selected_universe = "No universe"
        self._refresh_context()
        self._restore_scan_status(mode)

    def _restore_scan_status(self, mode: str) -> None:
        """Replace maintenance-view text with the current scan-view state."""
        session = getattr(self, "review_session", None)
        if session is None:
            labels = {
                "formatting": "Formatting Only",
                "standard": "Standard Spellcheck",
                "universe": "Universe Spellcheck",
            }
            label = labels.get(mode, "Subtitle Scan")
            self.status_value.set(
                f"{label} • Choose Start scan • No subtitle files changed"
            )
            return
        if getattr(self, "scan_paused", False):
            self.status_value.set("Scan paused • Choose Resume scan to continue")
        elif getattr(self, "current_issue", None) is not None:
            self.status_value.set("Review restored • Choose an action to continue")
        else:
            self.status_value.set(
                "Scan review restored • Save prepared changes or start a new scan"
            )

    def _activate_navigation(self, active_key: str) -> None:
        self.active_navigation_key = active_key
        for key, button in self.nav_buttons.items():
            button.configure(
                bg=self.COLORS["nav_active"] if key == active_key else self.COLORS["nav"]
            )

    def _browse_folder(self) -> None:
        chosen = self.filedialog.askdirectory(
            title="Choose a subtitle folder",
            initialdir=self.folder_value.get() or str(self.tool.script_dir),
            mustexist=True,
        )
        if chosen:
            self.folder_value.set(chosen)
            self.status_value.set("Folder selected • Choose Start scan to inspect it")

    def _refresh_backup_restore_control(self) -> None:
        button = getattr(self, "restore_backup_button", None)
        if button is None:
            return
        if self.prepare_thread is not None or self.review_session is not None:
            button.configure(state="disabled")
            self.restore_backup_tooltip.set(
                "Stop or finish the current scan before restoring subtitle backups."
            )
            return
        raw = self.folder_value.get().strip()
        folder = Path(raw).expanduser() if raw else None
        if folder is None or not folder.exists() or not folder.is_dir():
            button.configure(state="disabled")
            self.restore_backup_tooltip.set(
                "Choose an existing subtitle folder before restoring a backup."
            )
            return
        archives = self.tool.find_backup_archives(folder)
        if not archives:
            button.configure(state="disabled")
            self.restore_backup_tooltip.set(
                "No backup_subtitles.zip was found in this folder or an immediate child folder. Backups can be enabled in Options → File Discovery and Safety."
            )
            return
        button.configure(state="normal")
        self.restore_backup_tooltip.set(
            f"Restore subtitles from {len(archives)} backup archive(s). Current subtitle files will be overwritten."
        )

    def _restore_subtitles_from_backup(self) -> None:
        if self.prepare_thread is not None or self.review_session is not None:
            self._refresh_backup_restore_control()
            return
        folder = Path(self.folder_value.get().strip()).expanduser()
        archives = self.tool.find_backup_archives(folder)
        if not archives:
            self._refresh_backup_restore_control()
            return
        confirmation = self._prompt_typed_confirmation(
            "Restore subtitle backups?",
            f"This will overwrite current subtitle files using {len(archives)} backup archive(s).\n\n"
            "The change cannot be undone from within the tool. The ZIP archives will be retained.\n\n"
            "Type YES to restore.",
        )
        if not confirmation:
            return
        try:
            archive_count, file_count = self.tool.restore_backup_archives(folder)
            self.tool.clear_gui_review_session()
        except (OSError, RuntimeError, ValueError) as error:
            self.messagebox.showerror("Could not restore subtitles", str(error))
            self.status_value.set("Backup restore failed")
            return
        self.messagebox.showinfo(
            "Subtitles restored",
            f"Restored {file_count} subtitle file(s) from {archive_count} archive(s).\n\nThe backup archives were retained.",
        )
        self.status_value.set(
            f"Restored {file_count} subtitle file(s) • Backup archives retained"
        )
        self._refresh_backup_restore_control()

    def _refresh_universes(self) -> None:
        values = universe_selector_values(self.tool.list_universes())
        self.universe_combo.configure(values=values)
        selected = self.universe_value.get()
        if selected == ADD_UNIVERSE_LABEL:
            selected = getattr(self, "_selected_universe", "No universe")
        if selected not in values[1:]:
            selected = "No universe"
        self.universe_value.set(selected)
        self._selected_universe = selected
        self._refresh_context()

    def _on_universe_selected(self, _event=None) -> None:
        selected = self.universe_value.get()
        if selected == ADD_UNIVERSE_LABEL:
            self._create_universe_from_scan_selector()
            return
        self._selected_universe = selected
        self._refresh_context()

    def _create_universe_from_scan_selector(self) -> Optional[str]:
        previous = getattr(self, "_selected_universe", "No universe")
        response = self._prompt_text_fields(
            "New Universe Dictionary", (("Universe name", ""),)
        )
        if response is None:
            self.universe_value.set(previous)
            return None
        name = response[0]
        try:
            self.tool.create_universe_named(name)
        except (OSError, RuntimeError, UnicodeError, ValueError) as error:
            self.universe_value.set(previous)
            self.messagebox.showerror("Could not create universe", str(error))
            return None
        self._refresh_universes()
        self.universe_value.set(name)
        self._selected_universe = name
        self._refresh_context()
        self.status_value.set(f'Created and selected Universe Dictionary “{name}”')
        return name

    def _refresh_context(self) -> None:
        language = language_key(self.language_value.get())
        self.base_context.set("American English" if language == "american" else "British English")
        universe = self.universe_value.get()
        if self.scan_mode.get() != "universe" or universe == "No universe":
            self.universe_context.set("None")
            self.universe_words.set("0")
            self.universe_names.set("0")
            self.universe_acronyms.set("0")
            self.universe_substitutions.set("0")
            return
        self.universe_context.set(universe)
        universe_path = self.tool.universe_dir / universe
        self.universe_words.set(str(count_nonblank_lines(universe_path / "words.txt")))
        self.universe_names.set(str(count_nonblank_lines(universe_path / "names.txt")))
        self.universe_acronyms.set(
            str(count_nonblank_lines(universe_path / "acronyms.txt"))
        )
        self.universe_substitutions.set(
            str(count_nonblank_lines(universe_path / "substitutions.tsv"))
        )

    def _start_or_resume_scan(self) -> None:
        if self.scan_paused and self.review_session is not None:
            self._resume_scan()
        else:
            self._prepare_scan()

    def _apply_capitalization_choice(self, mode: str, *, remember: bool) -> None:
        """Apply one scan choice and persist it only when explicitly requested."""
        if mode not in CAPITALIZATION_SCAN_MODES:
            raise ValueError("Choose one of the capitalization preferences.")
        if remember:
            self.tool.set_option_value("capitalization_mode", mode)
            self._saved_capitalization_mode = mode
            self._temporary_capitalization_mode = False
        else:
            self.tool.options["capitalization_mode"] = mode
            self._temporary_capitalization_mode = True

    def _require_capitalization_mode(self) -> bool:
        if self.tool.options.get("capitalization_mode") in CAPITALIZATION_SCAN_MODES:
            return True
        dialog = self.tk.Toplevel(self.root)
        dialog.title("Capitalization preference required")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(True, False)
        result = {"saved": False}
        selected = self.tk.StringVar(value="")
        remember = self.tk.BooleanVar(value=False)
        body = self.ttk.Frame(dialog, style="Card.TFrame", padding=18)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        self.ttk.Label(
            body,
            text="Choose how subtitle capitalization should be handled before starting the scan.",
            style="Body.TLabel",
            wraplength=520,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        combo = self.ttk.Combobox(
            body,
            textvariable=selected,
            values=tuple(CAPITALIZATION_SCAN_MODES.values()),
            state="readonly",
            width=31,
        )
        combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 16))

        def save(_event=None):
            label = selected.get()
            mode = next(
                (key for key, candidate in CAPITALIZATION_SCAN_MODES.items() if candidate == label),
                None,
            )
            if mode is None:
                self.messagebox.showwarning(
                    "Selection required",
                    "Choose one of the capitalization preferences.",
                    parent=dialog,
                )
                return "break"
            try:
                self._apply_capitalization_choice(mode, remember=remember.get())
            except (OSError, RuntimeError, ValueError) as error:
                self.messagebox.showerror("Could not save option", str(error), parent=dialog)
                return "break"
            result["saved"] = True
            dialog.destroy()
            return "break"

        self.ttk.Checkbutton(
            body,
            text="Remember my choice",
            variable=remember,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 16))
        self.ttk.Button(body, text="Cancel", command=dialog.destroy).grid(
            row=3, column=0, sticky="e", padx=(0, 8)
        )
        self.ttk.Button(body, text="Continue", command=save).grid(
            row=3, column=1, sticky="e"
        )
        combo.bind("<<ComboboxSelected>>", lambda _event: None)
        dialog.bind("<Return>", save)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._center_child_window(dialog)
        combo.focus_set()
        self.root.wait_window(dialog)
        return result["saved"]

    def _prepare_scan(self) -> None:
        raw_folder = self.folder_value.get().strip()
        folder = Path(raw_folder).expanduser() if raw_folder else None
        if folder is None or not folder.exists() or not folder.is_dir():
            self.messagebox.showerror("Folder not found", "Choose an existing subtitle folder.")
            return
        if not self._confirm_discard_unsaved_review("start a new scan"):
            return
        if getattr(self, "_temporary_capitalization_mode", False):
            self.tool.options["capitalization_mode"] = getattr(
                self,
                "_saved_capitalization_mode",
                self.tool.options.get("capitalization_mode", "ask_always"),
            )
            self._temporary_capitalization_mode = False
        if not self._require_capitalization_mode():
            return
        try:
            self.tool.clear_gui_review_session()
        except RuntimeError as error:
            self.messagebox.showerror("Could not start a new scan", str(error))
            return
        mode = self.scan_mode.get()
        language = language_key(self.language_value.get())
        selected_universe = self.universe_value.get()
        universe = (
            selected_universe
            if mode == "universe" and selected_universe != "No universe"
            else None
        )
        self.pause_requested.clear()
        self.stop_requested.clear()
        self.scan_paused = False
        self._set_scan_running(can_pause=True)
        self._disable_review_actions()
        self.save_button.configure(state="disabled")
        self.review_session = None
        self.current_issue = None
        self.pending_action = None
        self.pending_replacement = None
        self.editing_cue = False
        self.current_box.configure(state="disabled")
        self.progress["value"] = 0
        self.progress_percent.set("0%")
        self.status_value.set("Preparing read-only scan preview…")
        self.prepare_queue = queue.Queue()

        def worker() -> None:
            session = None
            try:
                files = self.tool.find_srt_files(folder)
                if not files:
                    self.prepare_queue.put(("empty", None))
                    return
                if mode == "formatting":
                    context = self.tool.load_dictionary_context(language)
                    session = self.tool.create_formatting_review(
                        files, folder, context
                    )
                    self.tool.resume_formatting_review(
                        session,
                        progress_callback=lambda *values: self.prepare_queue.put(
                            ("progress", values)
                        ),
                        pause_requested=self.pause_requested.is_set,
                    )
                    self.prepare_queue.put(
                        ("stopped", None)
                        if self.stop_requested.is_set()
                        else ("formatting_session", session)
                    )
                    return
                context = self.tool.load_dictionary_context(language, universe)
                session = self.tool.create_spellcheck_review(
                    files,
                    folder,
                    context,
                )
                self.tool.resume_spellcheck_review(
                    session,
                    progress_callback=lambda *values: self.prepare_queue.put(
                        ("progress", values)
                    ),
                    pause_requested=self.pause_requested.is_set,
                )
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("session", session)
                )
            except SpellcheckReviewPaused:
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("paused", session)
                )
            except Exception as error:  # Report worker failures on the GUI thread.
                self.prepare_queue.put(("error", error))

        self.prepare_thread = threading.Thread(target=worker, daemon=True)
        self.prepare_thread.start()
        self.root.after(50, self._poll_prepare_queue)

    def _poll_prepare_queue(self) -> None:
        completed = False
        while self.prepare_queue is not None:
            try:
                event, payload = self.prepare_queue.get_nowait()
            except queue.Empty:
                break
            if self.stop_requested.is_set() and event != "error":
                self._stop_scan()
                completed = True
                break
            if event == "progress":
                self._display_progress(*payload)
            elif event == "preview":
                self._display_basic_preview(payload)
                completed = True
            elif event == "session":
                self.review_session = payload
                self.scan_paused = False
                issue = payload.current_issue
                if issue is None:
                    self._display_no_unknowns(len(payload.files))
                else:
                    self._display_spellcheck_issue(issue)
                self._checkpoint_review()
                completed = True
            elif event == "formatting_session":
                self.review_session = payload
                self.scan_paused = False
                self._display_formatting_review(payload)
                self._checkpoint_review()
                completed = True
            elif event == "review_advanced":
                issue = payload
                if issue is None:
                    file_count = len(self.review_session.files) if self.review_session else 0
                    self._display_no_unknowns(file_count)
                else:
                    self._display_spellcheck_issue(issue)
                self._checkpoint_review()
                completed = True
            elif event == "review_saved":
                self._display_review_saved(payload)
                self._checkpoint_review()
                completed = True
            elif event == "dictionary_advanced":
                issue, entry, target = payload
                if issue is None:
                    self._display_no_unknowns(
                        len(self.review_session.files) if self.review_session else 0
                    )
                else:
                    self._display_spellcheck_issue(issue)
                destination = "Universe" if target == "universe" else "User"
                self.status_value.set(
                    f'Added “{entry}” to the {destination} Dictionary • Undo available'
                )
                self._checkpoint_review()
                completed = True
            elif event == "save_error":
                self.messagebox.showerror("Could not save changes", str(payload))
                if self.current_issue is not None:
                    self._display_spellcheck_issue(self.current_issue)
                else:
                    self._display_no_unknowns(
                        len(self.review_session.files) if self.review_session else 0
                    )
                self.status_value.set(
                    "Save failed • In-memory review retained • Check the error and try again"
                )
                completed = True
            elif event == "dictionary_error":
                self.messagebox.showerror("Could not add dictionary entry", str(payload))
                if self.current_issue is not None:
                    self._display_spellcheck_issue(self.current_issue)
                self.status_value.set("Dictionary entry was not added • Review unchanged")
                completed = True
            elif event == "paused":
                self.review_session = payload
                self.current_issue = None
                self.scan_paused = True
                self.scan_button_text.set("Resume scan")
                self.pause_button.configure(state="disabled", text="Pause scan")
                self.stop_button.configure(state="normal", text="Stop scan")
                self.status_value.set(
                    "Scan paused • Prepared work is checkpointed • No subtitle files changed"
                )
                self._checkpoint_review(paused=True)
                completed = True
            elif event == "stopped":
                self._stop_scan()
                completed = True
            elif event == "empty":
                self._display_empty_scan()
                completed = True
            elif event == "error":
                self.messagebox.showerror("Could not prepare scan", str(payload))
                self.status_value.set("Scan preparation failed • No files changed")
                self.scan_button_text.set("Start scan")
                self.pause_button.configure(state="disabled", text="Pause scan")
                self.stop_button.configure(state="disabled", text="Stop scan")
                completed = True

        if completed:
            self.prepare_button.configure(state="normal")
            self.prepare_queue = None
            self.prepare_thread = None
            self._update_save_control()
            self._refresh_backup_restore_control()
            return
        if self.prepare_thread is not None and self.prepare_thread.is_alive():
            self.root.after(50, self._poll_prepare_queue)
        else:
            self.prepare_button.configure(state="normal")
            self.prepare_queue = None
            self.prepare_thread = None

    def _display_progress(
        self,
        phase: str,
        file_number: int,
        total_files: int,
        subtitle_number: int,
        total_subtitles: int,
    ) -> None:
        self.file_progress.set(f"File {file_number} of {total_files}")
        self.cue_progress.set(f"Subtitle {subtitle_number} of {total_subtitles}")
        percent = scan_progress_percent(
            phase,
            file_number,
            total_files,
            subtitle_number,
            total_subtitles,
        )
        self.progress["value"] = percent
        self.progress_percent.set(f"{percent}%")
        self.status_value.set(
            "Formatting subtitles in memory…"
            if phase == "Formatting"
            else f"{phase} read-only review…"
        )

    def _display_basic_preview(self, preview: ScanPreview) -> None:
        self._set_review_card_titles()
        self.scan_button_text.set("Start scan")
        self.pause_button.configure(state="disabled", text="Pause scan")
        self.stop_button.configure(state="disabled", text="Stop scan")
        self.file_progress.set(f"File 1 of {preview.file_count}")
        self.cue_progress.set(f"Subtitle 1 of {preview.cue_count}")
        percent = 100 if preview.file_count == 1 and preview.cue_count <= 1 else 0
        self.progress["value"] = percent
        self.progress_percent.set(f"{percent}%")
        self.review_title.set("Formatting preview")
        self.file_label.set(preview.file_name)
        self._set_cue_text(self.previous_box, preview.previous_text)
        self.current_timestamp.set(preview.timestamp)
        self._set_cue_text(self.current_box, preview.current_text)
        self._set_cue_text(self.next_box, preview.next_text)
        self._set_suggestions(())
        self._refresh_context()
        recursive = "recursive" if self.tool.options["scan_folders_recursively"] else "current folder only"
        self.status_value.set(
            f"Prepared read-only preview • {preview.file_count} file(s) • {recursive} • No files changed"
        )

    def _display_formatting_review(self, session: SpellcheckReviewSession) -> None:
        """Present a completed in-memory formatting pass and its validation report."""
        self.current_issue = None
        self.pending_action = None
        self.pending_replacement = None
        self.editing_cue = False
        self.scan_paused = False
        self._disable_review_actions()
        self._set_review_card_titles(
            "Formatting summary", "Prepared changes", "Validation report"
        )
        self.next_box.configure(height=8)
        changed_count = len(self.tool.review_changed_files(session))
        finding_count = len(session.validation_findings)
        self.scan_button_text.set("Restart scan")
        self.pause_button.configure(state="disabled", text="Pause scan")
        self.stop_button.configure(state="normal", text="Stop scan")
        self.file_progress.set(f"File {len(session.files)} of {len(session.files)}")
        total_cues = sum(len(blocks) for blocks in session.prepared_blocks.values())
        self.cue_progress.set(f"Subtitles scanned: {total_cues}")
        self.progress["value"] = 100
        self.progress_percent.set("100%")
        self.review_title.set("Formatting review complete")
        self.file_label.set(f"Scanned {len(session.files)} subtitle file(s) in memory")
        self.current_timestamp.set("")
        self._set_cue_text(
            self.previous_box,
            f"Files scanned: {len(session.files)}\nFiles with prepared changes: {changed_count}",
        )
        self._set_cue_text(
            self.current_box,
            "Formatting corrections are prepared in memory.\n"
            + (
                "Choose Save changes to write them safely."
                if changed_count
                else "No subtitle text changed."
            ),
        )
        if session.validation_findings:
            report_lines = []
            for finding in session.validation_findings:
                report_lines.append(
                    f"{finding.get('file')} | Subtitle {finding.get('subtitle')} | "
                    f"{finding.get('issue')}: {finding.get('text')}"
                )
            validation_text = (
                f"Validation report: {finding_count} suspicious item(s) found.\n"
                "These are reported only and were not edited.\n\n"
                + "\n".join(report_lines)
            )
        else:
            validation_text = "Validation report: no suspicious items found."
        self._set_cue_text(self.next_box, validation_text)
        self._set_suggestions(())
        self._refresh_context()
        self.status_value.set(
            f"Formatting complete in memory • {changed_count} file(s) changed • "
            f"{finding_count} validation finding(s) • "
            + ("Save changes when ready" if changed_count else "No save required")
        )
        self._update_save_control()

    def _display_spellcheck_issue(self, issue: SpellcheckIssuePreview) -> None:
        self._set_review_card_titles()
        self.current_issue = issue
        self.pending_action = None
        self.pending_replacement = None
        self.editing_cue = False
        self.scan_paused = False
        self.scan_button_text.set("Restart scan")
        self.pause_button.configure(state="disabled", text="Pause scan")
        self.stop_button.configure(state="normal", text="Stop scan")
        self.review_title.set(f'Review spelling issue: “{issue.word}”')
        self.file_label.set(issue.relative_file)
        self.file_progress.set(f"File {issue.file_number} of {issue.total_files}")
        self.cue_progress.set(
            f"Subtitle {issue.subtitle_index + 1} of {issue.total_subtitles}"
        )
        percent = scan_progress_percent(
            "Spellchecking",
            issue.file_number,
            issue.total_files,
            issue.subtitle_index + 1,
            issue.total_subtitles,
        )
        self.progress["value"] = percent
        self.progress_percent.set(f"{percent}%")
        previous = "\n\n—\n\n".join(issue.previous_blocks) or "No previous subtitle."
        following = "\n\n—\n\n".join(issue.next_blocks) or "No next subtitle."
        self._set_cue_text(self.previous_box, previous)
        self.current_timestamp.set(issue.timestamp)
        self.edit_button.configure(text="Edit / Substitute", state="normal")
        display_line = issue.line_index + 1
        self._set_cue_text(
            self.current_box,
            issue.current_text,
            highlight=issue.word,
            highlight_position=(display_line, issue.start, issue.end),
        )
        self._set_cue_text(self.next_box, following)
        self._set_suggestions(issue.suggestions)
        self.ignore_button.configure(state="normal")
        self.add_dictionary_button.configure(state="normal")
        self.search_button.configure(state="normal")
        self.undo_button.configure(
            state="normal"
            if self.review_session is not None and self.review_session.undo_actions
            else "disabled"
        )
        self.this_time_button.configure(state="disabled")
        self.this_session_button.configure(state="disabled")
        self.this_universe_button.configure(state="disabled")
        self.always_button.configure(state="disabled")
        self._refresh_context()
        self.status_value.set(
            "Unknown found • Choose a suggestion or action, then choose its scope"
        )
        self._update_save_control()

    def _display_no_unknowns(self, file_count: int) -> None:
        self._set_review_card_titles()
        self.current_issue = None
        self.pending_action = None
        self.pending_replacement = None
        self.editing_cue = False
        self._disable_review_actions()
        self.scan_paused = False
        has_undo = self.review_session is not None and bool(
            self.review_session.undo_actions
        )
        self.scan_button_text.set("Restart scan" if has_undo else "Start scan")
        self.pause_button.configure(state="disabled", text="Pause scan")
        self.stop_button.configure(
            state="normal" if has_undo else "disabled", text="Stop scan"
        )
        if has_undo:
            self.undo_button.configure(state="normal")
        self.review_title.set("No spelling issues found")
        self.file_label.set(f"Scanned {file_count} subtitle file(s) in memory")
        self.current_timestamp.set("")
        self.progress["value"] = 100
        self.progress_percent.set("100%")
        self._set_cue_text(self.previous_box, "—")
        self._set_cue_text(self.current_box, "Every visible word was recognized.")
        self._set_cue_text(self.next_box, "—")
        self._set_suggestions(())
        self.status_value.set(
            "Review complete in memory • Undo is available • Save changes when ready"
            if has_undo
            else "Review complete • No unsaved changes"
        )
        self._update_save_control()

    def _display_empty_scan(self) -> None:
        self._set_review_card_titles()
        self.review_session = None
        self.current_issue = None
        self.pending_action = None
        self.pending_replacement = None
        self.editing_cue = False
        self._disable_review_actions()
        self.current_timestamp.set("")
        self._set_cue_text(self.previous_box, "—")
        self._set_cue_text(self.current_box, "No subtitle files found.")
        self._set_cue_text(self.next_box, "—")
        self.scan_button_text.set("Start scan")
        self.pause_button.configure(state="disabled", text="Pause scan")
        self.stop_button.configure(state="disabled", text="Stop scan")
        self.messagebox.showinfo(
            "No subtitles found",
            "No .srt files were found using the current recursive-scan option.",
        )
        self.file_progress.set("File 0 of 0")
        self.cue_progress.set("Subtitle 0 of 0")
        self.progress["value"] = 0
        self.progress_percent.set("0%")
        self.status_value.set("No subtitle files found • No files changed")

    def _set_cue_text(
        self,
        widget,
        text: str,
        highlight: Optional[str] = None,
        highlight_position: Optional[tuple[int, int, int]] = None,
    ) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text or "—")
        widget.tag_remove("selected_word", "1.0", "end")
        if highlight:
            if highlight_position is not None:
                line_number, start_column, end_column = highlight_position
                start = f"{line_number}.{start_column}"
                end = f"{line_number}.{end_column}"
            else:
                start = widget.search(highlight, "1.0", stopindex="end", nocase=True)
                end = f"{start}+{len(highlight)}c" if start else ""
            if start:
                widget.tag_add("selected_word", start, end)
                widget.tag_configure(
                    "selected_word",
                    background=self.COLORS["selection"],
                    foreground=self.COLORS["edit_text"],
                )
        widget.configure(state="disabled")

    def _set_review_card_titles(
        self,
        previous: str = "Previous subtitle",
        current: str = "Current subtitle",
        following: str = "Next subtitle",
    ) -> None:
        """Switch the shared review cards between cue and summary meanings."""
        self.previous_card_title.set(previous)
        self.current_card_title.set(current)
        self.next_card_title.set(following)
        self.previous_box.configure(height=2)
        self.current_box.configure(height=3)
        self.next_box.configure(height=2)

    def _set_suggestions(self, suggestions: Sequence[str]) -> None:
        for index, button in enumerate(self.suggestion_buttons):
            available = index < len(suggestions)
            button.configure(
                text=suggestions[index] if available else "—",
                state="normal" if available else "disabled",
            )

    def _disable_review_actions(self) -> None:
        for button in getattr(self, "suggestion_buttons", ()):
            button.configure(state="disabled")
        if hasattr(self, "edit_button"):
            self.edit_button.configure(state="disabled")
        if hasattr(self, "ignore_button"):
            self.ignore_button.configure(state="disabled")
        if hasattr(self, "add_dictionary_button"):
            self.add_dictionary_button.configure(state="disabled")
        if hasattr(self, "search_button"):
            self.search_button.configure(state="disabled")
        if hasattr(self, "undo_button"):
            self.undo_button.configure(state="disabled")
        if hasattr(self, "this_time_button"):
            self.this_time_button.configure(state="disabled")
        if hasattr(self, "this_session_button"):
            self.this_session_button.configure(state="disabled")
        if hasattr(self, "this_universe_button"):
            self.this_universe_button.configure(state="disabled")
        if hasattr(self, "always_button"):
            self.always_button.configure(state="disabled")

    def _update_save_control(self) -> None:
        if not hasattr(self, "save_button"):
            return
        enabled = False
        if (
            self.review_session is not None
            and self.prepare_thread is None
            and not self.editing_cue
        ):
            try:
                enabled = self.tool.review_has_changes(self.review_session)
            except (OSError, RuntimeError, UnicodeError):
                enabled = False
        self.save_button.configure(state="normal" if enabled else "disabled")

    def _choose_save_backup_behavior(self) -> Optional[bool]:
        if self.tool.options["create_backup_subtitles_zip_before_editing"]:
            return True
        choice = self.messagebox.askyesnocancel(
            "Backups are disabled",
            "Subtitle backup creation is currently disabled.\n\n"
            "Yes: enable backups and save\n"
            "No: save this time without a backup\n"
            "Cancel: return without saving",
        )
        if choice is None:
            return None
        if choice:
            self.tool.options["create_backup_subtitles_zip_before_editing"] = True
            self.tool.save_options()
            return True
        return False

    def _save_review_changes(self) -> None:
        session = self.review_session
        if session is None or self.prepare_thread is not None or self.editing_cue:
            return
        try:
            changed_files = self.tool.review_changed_files(session)
        except (OSError, RuntimeError, UnicodeError) as error:
            self.messagebox.showerror("Cannot save review", str(error))
            return
        if not changed_files:
            self.status_value.set("There are no unsaved subtitle changes")
            self._update_save_control()
            return
        if not self.messagebox.askyesno(
            "Save reviewed changes",
            f"Save prepared changes to {len(changed_files)} subtitle file(s)?\n\n"
            "A successful save establishes a new baseline and clears the current "
            "Undo history.",
        ):
            return
        create_backups = self._choose_save_backup_behavior()
        if create_backups is None:
            return

        self._disable_review_actions()
        self.save_button.configure(state="disabled")
        self.prepare_button.configure(state="disabled")
        self.pause_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.status_value.set("Saving reviewed changes safely…")
        self.prepare_queue = queue.Queue()

        def worker() -> None:
            try:
                result = self.tool.commit_spellcheck_review(
                    session, create_backups=create_backups
                )
                self.prepare_queue.put(("review_saved", result))
            except Exception as error:
                self.prepare_queue.put(("save_error", error))

        self.prepare_thread = threading.Thread(target=worker, daemon=True)
        self.prepare_thread.start()
        self.root.after(50, self._poll_prepare_queue)

    def _display_review_saved(self, result) -> None:
        count = len(result.changed_files)
        self.pending_action = None
        self.pending_replacement = None
        self.undo_button.configure(state="disabled")
        self.stop_button.configure(state="normal", text="Stop scan")
        if (
            self.review_session is not None
            and getattr(self.review_session, "mode", "spellcheck") == "formatting"
        ):
            self._display_formatting_review(self.review_session)
        elif self.current_issue is not None:
            self._display_spellcheck_issue(self.current_issue)
        else:
            self._display_no_unknowns(
                len(self.review_session.files) if self.review_session else 0
            )
        backup_text = (
            f" • {len(result.backup_archives)} backup archive(s) retained"
            if result.backup_archives
            else " • Saved without a backup by request"
        )
        self.status_value.set(
            f"Saved {count} subtitle file(s){backup_text} • Undo baseline reset"
        )

    def _open_dictionary_dialog(self) -> None:
        session = self.review_session
        issue = self.current_issue
        if session is None or issue is None or self.prepare_thread is not None:
            return

        tk, ttk = self.tk, self.ttk
        dialog = tk.Toplevel(self.root)
        dialog.title("Add dictionary entry")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text=f'Add “{issue.word}” to a dictionary',
            style="Heading.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            frame,
            text=(
                "Keep the highlighted word for a single entry, or expand it to an "
                "exact phrase from the current subtitle. Phrase components remain "
                "unknown when used separately."
            ),
            wraplength=500,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 14))

        entry_value = tk.StringVar(value=issue.word)
        list_value = tk.StringVar(value="words")
        default_target = "universe" if session.context.universe else "user"
        target_value = tk.StringVar(value=default_target)

        ttk.Label(frame, text="Entry text").grid(row=2, column=0, sticky="w")
        entry = ttk.Entry(frame, textvariable=entry_value, width=58)
        entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 14))

        ttk.Label(frame, text="Entry type").grid(row=4, column=0, sticky="w")
        ttk.Radiobutton(
            frame,
            text="Accepted word or exact phrase",
            variable=list_value,
            value="words",
        ).grid(row=5, column=0, sticky="w", pady=(4, 0))
        ttk.Radiobutton(
            frame,
            text="Name or exact name phrase (entry casing is authoritative)",
            variable=list_value,
            value="names",
        ).grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(
            frame,
            text="Acronym (canonical casing is authoritative)",
            variable=list_value,
            value="acronyms",
        ).grid(row=7, column=0, columnspan=2, sticky="w")

        ttk.Label(frame, text="Dictionary").grid(
            row=8, column=0, sticky="w", pady=(14, 0)
        )
        ttk.Radiobutton(
            frame,
            text=f"User Dictionary ({session.context.language.title()} English)",
            variable=target_value,
            value="user",
        ).grid(row=9, column=0, sticky="w", pady=(4, 0))
        if session.context.universe:
            ttk.Radiobutton(
                frame,
                text=f"Universe Dictionary ({session.context.universe})",
                variable=target_value,
                value="universe",
            ).grid(row=10, column=0, columnspan=2, sticky="w")

        controls = ttk.Frame(frame)
        controls.grid(row=11, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(controls, text="Cancel", command=dialog.destroy).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(
            controls,
            text="Add entry",
            style="Accent.TButton",
            command=lambda: self._apply_dictionary_entry(
                entry_value.get(), list_value.get(), target_value.get(), dialog
            ),
        ).grid(row=0, column=1)

        entry.focus_set()
        entry.selection_range(0, "end")
        dialog.bind(
            "<Return>",
            lambda _event: self._apply_dictionary_entry(
                entry_value.get(), list_value.get(), target_value.get(), dialog
            ),
        )
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()

    def _apply_dictionary_entry(
        self,
        entry: str,
        list_name: str,
        target: str,
        dialog,
    ) -> None:
        session = self.review_session
        if session is None or self.current_issue is None or self.prepare_thread is not None:
            return
        entry = " ".join(entry.split())
        if not entry:
            self.messagebox.showwarning(
                "Dictionary entry required", "Enter a word, name, or exact phrase."
            )
            return
        if list_name == "acronyms":
            try:
                if not self._confirm_acronym_addition(
                    entry,
                    target=target,
                    language=(
                        session.context.language if target == "user" else None
                    ),
                    universe=(
                        session.context.universe if target == "universe" else None
                    ),
                ):
                    return
            except ValueError as error:
                self.messagebox.showerror("Could not add acronym", str(error))
                return
        elif list_name in {"words", "names"} and not any(
            character.isspace() for character in entry
        ):
            if not self._confirm_word_addition(
                entry,
                target=target,
                language=(session.context.language if target == "user" else None),
                universe=(
                    session.context.universe if target == "universe" else None
                ),
            ):
                return
        dialog.destroy()
        self._disable_review_actions()
        self.save_button.configure(state="disabled")
        self.prepare_button.configure(state="disabled")
        self.pause_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.pause_requested.clear()
        self.stop_requested.clear()
        self.status_value.set(f'Adding “{entry}” to the dictionary…')
        self.prepare_queue = queue.Queue()

        def worker() -> None:
            try:
                issue = self.tool.add_review_dictionary_entry(
                    session,
                    entry,
                    list_name=list_name,
                    target=target,
                    progress_callback=lambda *values: self.prepare_queue.put(
                        ("progress", values)
                    ),
                    pause_requested=self.pause_requested.is_set,
                )
                self.prepare_queue.put(
                    ("dictionary_advanced", (issue, entry, target))
                )
            except SpellcheckReviewPaused:
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("paused", session)
                )
            except Exception as error:
                self.prepare_queue.put(("dictionary_error", error))

        self.prepare_thread = threading.Thread(target=worker, daemon=True)
        self.prepare_thread.start()
        self.root.after(50, self._poll_prepare_queue)

    def _confirm_acronym_addition(
        self,
        value: str,
        *,
        context=None,
        target: Optional[str] = None,
        language: Optional[str] = None,
        universe: Optional[str] = None,
    ) -> bool:
        """Validate an acronym and confirm any collision with a word list."""
        value = self.tool.validate_acronym_entry(value)
        if context is not None:
            conflicts = self.tool.acronym_word_conflicts(value, context)
        else:
            conflicts = self.tool.acronym_word_conflicts_for_location(
                value,
                target,
                language=language,
                universe=universe,
            )
        if not conflicts:
            return True
        message = (
            f'“{value}” is already accepted as a word in:\n\n'
            + "\n".join(f"• {label}" for label in conflicts)
            + "\n\nAdding it as an acronym will make this casing authoritative "
            "when that dictionary is active. Add it anyway?"
        )
        return bool(self.messagebox.askyesno(
            "Acronym matches an existing word",
            message,
            parent=getattr(self, "root", None),
        ))

    def _confirm_word_addition(
        self,
        value: str,
        *,
        context=None,
        target: Optional[str] = None,
        language: Optional[str] = None,
        universe: Optional[str] = None,
    ) -> bool:
        """Confirm a word whose spelling overlaps a relevant acronym."""
        if context is not None:
            conflicts = self.tool.word_acronym_conflicts(value, context)
        else:
            conflicts = self.tool.word_acronym_conflicts_for_location(
                value,
                target,
                language=language,
                universe=universe,
            )
        if not conflicts:
            return True
        message = (
            f'“{value}” is already handled as an acronym in:\n\n'
            + "\n".join(f"• {label}" for label in conflicts)
            + "\n\nAdding it as a word or name creates overlapping dictionary meanings. "
            "Acronym casing will remain authoritative when applicable. Add it anyway?"
        )
        return bool(self.messagebox.askyesno(
            "Word or name matches an existing acronym",
            message,
            parent=getattr(self, "root", None),
        ))

    def _search_current_line(self) -> None:
        session = self.review_session
        issue = self.current_issue
        if session is None or issue is None:
            return
        blocks = session.prepared_blocks.get(issue.file_number - 1)
        if blocks is None or not 0 <= issue.subtitle_index < len(blocks):
            self.messagebox.showwarning(
                "Search unavailable",
                "The selected subtitle is no longer available in this review.",
            )
            return
        opened = self.tool.search_subtitle_line_in_google(
            blocks[issue.subtitle_index],
            issue.word,
            line_index=issue.line_index,
        )
        if opened:
            self.status_value.set(
                "Opened Google search for the selected subtitle line • Review unchanged"
            )
        else:
            self.messagebox.showwarning(
                "Could not open browser",
                "The program could not open the Google search in your default browser.",
            )
            self.status_value.set("Browser did not open • Review unchanged")

    def _choose_ignore(self) -> None:
        if self.review_session is None or self.current_issue is None:
            return
        self.pending_action = "ignore"
        self.pending_replacement = None
        self.this_time_button.configure(state="normal")
        self.this_session_button.configure(state="normal")
        if hasattr(self, "this_universe_button"):
            self.this_universe_button.configure(state="disabled")
        if hasattr(self, "always_button"):
            self.always_button.configure(state="disabled")
        self.status_value.set(
            "Ignore selected • Choose This time or This session"
        )

    def _begin_or_cancel_cue_edit(self) -> None:
        issue = self.current_issue
        if self.review_session is None or issue is None:
            return
        if self.editing_cue:
            self._display_spellcheck_issue(issue)
            self.status_value.set("Cue edit cancelled • Review unchanged")
            return
        self._disable_review_actions()
        self.editing_cue = True
        self.pending_action = "cue_edit"
        self.pending_replacement = None
        self.current_box.configure(state="normal")
        self.current_box.tag_remove("selected_word", "1.0", "end")
        self.current_box.focus_set()
        self.edit_button.configure(text="Cancel edit", state="normal")
        self.this_time_button.configure(state="normal")
        self.this_session_button.configure(state="disabled")
        if hasattr(self, "this_universe_button"):
            self.this_universe_button.configure(state="disabled")
        if hasattr(self, "always_button"):
            self.always_button.configure(state="disabled")
        self.status_value.set(
            "Edit the dialogue text above, then choose This time • Timestamp is locked"
        )

    def _choose_suggestion(self, suggestion_index: int) -> None:
        issue = self.current_issue
        if (
            self.review_session is None
            or issue is None
            or not 0 <= suggestion_index < len(issue.suggestions)
        ):
            return
        self.pending_action = "replacement"
        self.pending_replacement = issue.suggestions[suggestion_index]
        self.this_time_button.configure(state="normal")
        self.this_session_button.configure(state="normal")
        self.this_universe_button.configure(
            state="normal" if self.review_session.context.universe else "disabled"
        )
        self.always_button.configure(state="normal")
        self.status_value.set(
            f'Replace “{issue.word}” with “{self.pending_replacement}” • '
            "Choose a replacement scope"
        )

    def _undo_last_action(self) -> None:
        session = self.review_session
        if (
            session is None
            or not session.undo_actions
            or self.prepare_thread is not None
        ):
            return
        self.pending_action = None
        self.pending_replacement = None
        self.editing_cue = False
        self._disable_review_actions()
        self.pause_requested.clear()
        self.stop_requested.clear()
        self._set_scan_running(can_pause=True)
        self.status_value.set("Undoing the last review action and returning to that word…")
        self.prepare_queue = queue.Queue()

        def worker() -> None:
            try:
                issue = self.tool.undo_review_action(
                    session,
                    progress_callback=lambda *values: self.prepare_queue.put(
                        ("progress", values)
                    ),
                    pause_requested=self.pause_requested.is_set,
                )
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("review_advanced", issue)
                )
            except SpellcheckReviewPaused:
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("paused", session)
                )
            except Exception as error:
                self.prepare_queue.put(("error", error))

        self.prepare_thread = threading.Thread(target=worker, daemon=True)
        self.prepare_thread.start()
        self.root.after(50, self._poll_prepare_queue)

    def _apply_this_time(self) -> None:
        if self.pending_action == "cue_edit":
            self._apply_cue_edit()
        elif self.pending_action == "replacement":
            self._apply_replacement_scope("occurrence")
        else:
            self._apply_ignore_scope(session_wide=False)

    def _apply_this_session(self) -> None:
        if self.pending_action == "replacement":
            self._apply_replacement_scope("session")
        else:
            self._apply_ignore_scope(session_wide=True)

    def _apply_cue_edit(self) -> None:
        session = self.review_session
        if (
            self.pending_action != "cue_edit"
            or session is None
            or self.current_issue is None
            or self.prepare_thread is not None
        ):
            return
        edited_text = self.current_box.get("1.0", "end-1c")
        normalized = edited_text.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip() or any(
            not line.strip() for line in normalized.split("\n")
        ):
            self.messagebox.showwarning(
                "Cannot apply cue edit",
                "Subtitle dialogue cannot be empty or contain a blank line.",
            )
            return
        self.editing_cue = False
        self.edit_button.configure(text="Edit / Substitute")
        self.current_box.configure(state="disabled")
        self._disable_review_actions()
        self.pause_requested.clear()
        self.stop_requested.clear()
        self._set_scan_running(can_pause=True)
        self.status_value.set("Applying the edited cue in memory…")
        self.prepare_queue = queue.Queue()

        def worker() -> None:
            try:
                issue = self.tool.replace_review_cue_text(
                    session,
                    normalized,
                    progress_callback=lambda *values: self.prepare_queue.put(
                        ("progress", values)
                    ),
                    pause_requested=self.pause_requested.is_set,
                )
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("review_advanced", issue)
                )
            except SpellcheckReviewPaused:
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("paused", session)
                )
            except Exception as error:
                self.prepare_queue.put(("error", error))

        self.prepare_thread = threading.Thread(target=worker, daemon=True)
        self.prepare_thread.start()
        self.root.after(50, self._poll_prepare_queue)

    def _apply_replacement_scope(self, scope: str = "occurrence") -> None:
        session = self.review_session
        replacement = self.pending_replacement
        if (
            self.pending_action != "replacement"
            or session is None
            or self.current_issue is None
            or replacement is None
            or self.prepare_thread is not None
        ):
            return
        self._disable_review_actions()
        self.pause_requested.clear()
        self.stop_requested.clear()
        self._set_scan_running(can_pause=True)
        scope_labels = {
            "occurrence": "this occurrence",
            "session": "this review session",
            "universe": "this universe",
            "always": "the user dictionary",
        }
        self.status_value.set(
            f'Replacing for {scope_labels[scope]} with “{replacement}”…'
        )
        self.prepare_queue = queue.Queue()

        def worker() -> None:
            try:
                issue = self.tool.replace_review_with_scope(
                    session,
                    replacement,
                    scope,
                    progress_callback=lambda *values: self.prepare_queue.put(
                        ("progress", values)
                    ),
                    pause_requested=self.pause_requested.is_set,
                )
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("review_advanced", issue)
                )
            except SpellcheckReviewPaused:
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("paused", session)
                )
            except Exception as error:
                self.prepare_queue.put(("error", error))

        self.prepare_thread = threading.Thread(target=worker, daemon=True)
        self.prepare_thread.start()
        self.root.after(50, self._poll_prepare_queue)

    def _apply_ignore_scope(self, *, session_wide: bool) -> None:
        if (
            self.pending_action != "ignore"
            or self.review_session is None
            or self.current_issue is None
            or self.prepare_thread is not None
        ):
            return
        self.ignore_button.configure(state="disabled")
        self.undo_button.configure(state="disabled")
        self.this_time_button.configure(state="disabled")
        self.this_session_button.configure(state="disabled")
        self.pause_requested.clear()
        self.stop_requested.clear()
        self._set_scan_running(can_pause=True)
        scope_text = "this word for the session" if session_wide else "this occurrence"
        self.status_value.set(f"Ignoring {scope_text} and finding the next unknown…")
        self.prepare_queue = queue.Queue()

        def worker() -> None:
            try:
                ignore_operation = (
                    self.tool.ignore_review_word_for_session
                    if session_wide
                    else self.tool.ignore_review_occurrence
                )
                issue = ignore_operation(
                    self.review_session,
                    progress_callback=lambda *values: self.prepare_queue.put(
                        ("progress", values)
                    ),
                    pause_requested=self.pause_requested.is_set,
                )
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("review_advanced", issue)
                )
            except SpellcheckReviewPaused:
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("paused", self.review_session)
                )
            except Exception as error:
                self.prepare_queue.put(("error", error))

        self.prepare_thread = threading.Thread(target=worker, daemon=True)
        self.prepare_thread.start()
        self.root.after(50, self._poll_prepare_queue)

    def _set_scan_running(self, *, can_pause: bool) -> None:
        self.scan_button_text.set("Scanning…")
        self.prepare_button.configure(state="disabled")
        self.pause_button.configure(
            state="normal" if can_pause else "disabled", text="Pause scan"
        )
        self.stop_button.configure(state="normal", text="Stop scan")
        if hasattr(self, "save_button"):
            self.save_button.configure(state="disabled")
        if hasattr(self, "restore_backup_button"):
            self.restore_backup_button.configure(state="disabled")
            self.restore_backup_tooltip.set(
                "Stop or finish the current scan before restoring subtitle backups."
            )

    def _request_pause(self) -> None:
        # This control has exactly one meaning.  It deliberately never calls
        # the stop path, even if the worker exits before Tk processes its
        # queued completion message.
        self.pause_requested.set()
        self.pause_button.configure(state="disabled", text="Pausing…")
        self.status_value.set("Pause requested • Finishing the current scan step…")

    def _request_stop(self) -> None:
        if not self._confirm_discard_unsaved_review("stop this scan"):
            return
        worker_pending = self.prepare_queue is not None or (
            self.prepare_thread is not None and self.prepare_thread.is_alive()
        )
        if worker_pending:
            self.stop_requested.set()
            self.pause_requested.set()
            self.pause_button.configure(state="disabled")
            self.stop_button.configure(state="disabled", text="Stopping…")
            self.status_value.set("Stopping scan safely…")
            return
        self._stop_scan()

    def _resume_scan(self) -> None:
        if self.review_session is None or self.prepare_thread is not None:
            return
        self.pause_requested.clear()
        self.stop_requested.clear()
        self.scan_paused = False
        self._set_scan_running(can_pause=True)
        self.status_value.set("Resuming scan from retained in-memory work…")
        self.prepare_queue = queue.Queue()

        def worker() -> None:
            try:
                if getattr(self.review_session, "mode", "spellcheck") == "formatting":
                    self.tool.resume_formatting_review(
                        self.review_session,
                        progress_callback=lambda *values: self.prepare_queue.put(
                            ("progress", values)
                        ),
                        pause_requested=self.pause_requested.is_set,
                    )
                    event = ("formatting_session", self.review_session)
                else:
                    issue = self.tool.resume_spellcheck_review(
                        self.review_session,
                        progress_callback=lambda *values: self.prepare_queue.put(
                            ("progress", values)
                        ),
                        pause_requested=self.pause_requested.is_set,
                    )
                    event = ("review_advanced", issue)
                self.prepare_queue.put(
                    ("stopped", None) if self.stop_requested.is_set() else event
                )
            except SpellcheckReviewPaused:
                self.prepare_queue.put(
                    ("stopped", None)
                    if self.stop_requested.is_set()
                    else ("paused", self.review_session)
                )
            except Exception as error:
                self.prepare_queue.put(("error", error))

        self.prepare_thread = threading.Thread(target=worker, daemon=True)
        self.prepare_thread.start()
        self.root.after(50, self._poll_prepare_queue)

    def _stop_scan(self) -> None:
        tool = getattr(self, "tool", None)
        if tool is not None and hasattr(tool, "clear_gui_review_session"):
            try:
                tool.clear_gui_review_session()
            except RuntimeError as error:
                self.messagebox.showerror("Could not discard recovery state", str(error))
                return
        self.pause_requested.clear()
        self.stop_requested.clear()
        self.review_session = None
        self.current_issue = None
        self.pending_action = None
        self.pending_replacement = None
        self.editing_cue = False
        self.scan_paused = False
        if tool is not None:
            tool.options["capitalization_mode"] = getattr(
                self,
                "_saved_capitalization_mode",
                tool.options.get("capitalization_mode", "ask_always"),
            )
        self._temporary_capitalization_mode = False
        self.scan_button_text.set("Start scan")
        self.prepare_button.configure(state="normal")
        self.pause_button.configure(state="disabled", text="Pause scan")
        self.stop_button.configure(state="disabled", text="Stop scan")
        if hasattr(self, "save_button"):
            self.save_button.configure(state="disabled")
        self._disable_review_actions()
        if hasattr(self, "review_title"):
            self._set_review_card_titles()
            self.review_title.set("Scan stopped")
            self.file_label.set("Choose Start scan when you are ready.")
            self.current_timestamp.set("")
            self.file_progress.set("File 0 of 0")
            self.cue_progress.set("Subtitle 0 of 0")
            self.progress["value"] = 0
            self.progress_percent.set("0%")
            self._set_cue_text(self.previous_box, "—")
            self._set_cue_text(self.current_box, "No active scan.")
            self._set_cue_text(self.next_box, "—")
            self._set_suggestions(())
        self._refresh_backup_restore_control()
        self.status_value.set("Scan stopped • In-memory review cleared")

    def _checkpoint_review(self, *, paused: bool = False) -> bool:
        session = getattr(self, "review_session", None)
        if session is None:
            return True
        try:
            self.tool.save_gui_review_session(session, paused=paused)
            return True
        except (OSError, RuntimeError, UnicodeError) as error:
            self.messagebox.showwarning(
                "Recovery checkpoint failed",
                "The review remains open, but its latest state could not be saved "
                f"for crash recovery.\n\n{error}",
            )
            return False

    def _begin_update_check(self) -> None:
        """Check GitHub off the UI thread and silently tolerate offline startup."""
        if self.update_thread is not None or not self.tool.options.get(
            "check_for_updates_at_startup", False
        ):
            return

        def worker() -> None:
            try:
                update = self.tool.check_for_update()
            except UpdateError as error:
                self.update_queue.put(("check_error", error))
            else:
                self.update_queue.put(("available", update))

        self.update_thread = threading.Thread(target=worker, daemon=True)
        self.update_thread.start()
        self.root.after(100, self._poll_update_queue)

    def _complete_startup(self) -> None:
        """Finish recovery handling before any optional update prompt can appear."""
        self._offer_gui_recovery()
        if not self.tool.update_check_preference_confirmed:
            enabled = self.messagebox.askyesno(
                "Automatic update checks",
                "Would you like Subtitle Universe Spellcheck to check the public "
                "GitHub Releases page for updates when it starts?\n\n"
                "No network request has been made. You can change this later under "
                "Options → Menus and Display.",
                parent=self.root,
            )
            try:
                self.tool.set_option_value("check_for_updates_at_startup", enabled)
            except OSError as error:
                self.messagebox.showwarning(
                    "Preference not saved",
                    "The update-check preference could not be saved, so no update "
                    f"check will be made.\n\n{error}",
                    parent=self.root,
                )
                return
        if self.tool.options.get("check_for_updates_at_startup", False):
            self.root.after(750, self._begin_update_check)

    def _poll_update_queue(self) -> None:
        try:
            event, payload = self.update_queue.get_nowait()
        except queue.Empty:
            if self.update_thread is not None and self.update_thread.is_alive():
                self.root.after(100, self._poll_update_queue)
            else:
                self.update_thread = None
            return
        self.update_thread = None
        if event == "available" and payload is not None:
            self._offer_update_download(payload)
        elif event == "downloaded":
            update, archive_path, checksum_path = payload
            self.status_value.set(f"Update downloaded • {archive_path.name}")
            install_now = self.messagebox.askyesno(
                "Update downloaded",
                "The verified update ZIP was downloaded. No application files have "
                "been replaced yet.\n\n"
                f"ZIP: {archive_path}\nChecksum: {checksum_path}\n\n"
                "Install it now? The application will close, replace the complete "
                "distribution, validate the new version, and restart. Personal "
                "dictionaries, settings, recovery data, logs, subtitles, and backups "
                "will be retained.",
            )
            if install_now:
                self._start_update_installation(update, archive_path)
        elif event == "download_error":
            self.status_value.set("Update download failed • Existing files unchanged")
            self.messagebox.showerror("Update download failed", str(payload))
        elif event == "install_error":
            self.update_installing = False
            self.status_value.set("Update installation not started • Existing files unchanged")
            self.messagebox.showerror("Update installation could not start", str(payload))
        elif event == "install_started":
            self.status_value.set("Updater ready • Closing this version")
            self.root.after(100, self.root.destroy)

    def _offer_update_download(self, update: ReleaseUpdate) -> None:
        if not self.messagebox.askyesno(
            "Update available",
            f"Subtitle Universe Spellcheck {update.version} is available.\n\n"
            f"{update.name}\n{update.page_url}\n\n"
            "Would you like to download the verified ZIP now? After verification you "
            "can either keep the ZIP for manual installation or install it "
            "automatically with rollback protection.",
        ):
            return
        default_directory = Path.home() / "Downloads"
        if not default_directory.is_dir():
            default_directory = self.tool.script_dir
        chosen = self.filedialog.asksaveasfilename(
            title="Save verified update ZIP",
            initialdir=str(default_directory),
            initialfile=update.asset.name,
            defaultextension=".zip",
            filetypes=(("ZIP archives", "*.zip"), ("All files", "*.*")),
        )
        if chosen:
            self._start_update_download(update, Path(chosen))

    def _start_update_download(self, update: ReleaseUpdate, destination: Path) -> None:
        self.status_value.set(f"Downloading update • {update.asset.name}")

        def worker() -> None:
            try:
                result = self.tool.download_update(update, destination)
            except UpdateError as error:
                self.update_queue.put(("download_error", error))
            else:
                archive_path, checksum_path = result
                self.update_queue.put(
                    ("downloaded", (update, archive_path, checksum_path))
                )

        self.update_thread = threading.Thread(target=worker, daemon=True)
        self.update_thread.start()
        self.root.after(100, self._poll_update_queue)

    def _start_update_installation(self, update: ReleaseUpdate, archive_path: Path) -> None:
        if self.prepare_thread is not None and self.prepare_thread.is_alive():
            self.messagebox.showwarning(
                "Finish the current scan step",
                "Wait for the current scan operation to finish, then restart the "
                "application to install the downloaded update.",
                parent=self.root,
            )
            return
        if self.review_session is not None and not self._checkpoint_review(paused=True):
            return
        self.update_installing = True
        self.status_value.set(f"Preparing update • {update.version}")

        def worker() -> None:
            try:
                prepared = self.tool.prepare_update_installation(
                    update,
                    archive_path,
                    interface="gui",
                )
                self.tool.launch_prepared_update(prepared)
            except (OSError, RuntimeError, UpdateError, ValueError, zipfile.BadZipFile) as error:
                self.update_queue.put(("install_error", error))
            else:
                self.update_queue.put(("install_started", prepared))

        self.update_thread = threading.Thread(target=worker, daemon=True)
        self.update_thread.start()
        self.root.after(100, self._poll_update_queue)

    def _offer_gui_recovery(self) -> None:
        path = self.tool.gui_session_state_path
        if not path.exists():
            return
        choice = self.messagebox.askyesnocancel(
            "Recover interrupted GUI review?",
            "A GUI spellcheck review from an earlier run is available.\n\n"
            "Yes: recover it\n"
            "No: discard it and start fresh\n"
            "Cancel: leave it available without opening it",
        )
        if choice is None:
            return
        if not choice:
            try:
                self.tool.clear_gui_review_session()
            except RuntimeError as error:
                self.messagebox.showerror("Could not discard recovery state", str(error))
            return
        configured_capitalization = self.tool.options.get("capitalization_mode")
        try:
            session = self.tool.load_gui_review_session()
        except (OSError, RuntimeError, UnicodeError) as error:
            self.messagebox.showerror(
                "Could not recover GUI review",
                f"The saved review was left intact.\n\n{error}",
            )
            return
        if session is None:
            return
        recovered_capitalization = self.tool.options.get("capitalization_mode")
        self._temporary_capitalization_mode = (
            recovered_capitalization in CAPITALIZATION_SCAN_MODES
            and recovered_capitalization != configured_capitalization
        ) or configured_capitalization == "ask_always"
        self.review_session = session
        self.current_issue = session.current_issue
        self.folder_value.set(str(session.target))
        self.language_value.set(language_display_name(session.context.language))
        self.universe_value.set(session.context.universe or "No universe")
        if getattr(session, "mode", "spellcheck") == "formatting":
            self._select_mode("formatting")
        else:
            self._select_mode("universe" if session.context.universe else "standard")
        self.scan_paused = session.recovery_paused
        self.stop_button.configure(state="normal", text="Stop scan")
        if session.recovery_paused:
            self.scan_button_text.set("Resume scan")
            self.pause_button.configure(state="disabled", text="Pause scan")
            self.status_value.set("Recovered paused review • Choose Resume scan")
        elif getattr(session, "mode", "spellcheck") == "formatting":
            self._display_formatting_review(session)
            self.status_value.set(
                "Recovered completed Formatting-only review • Save prepared changes when ready"
            )
        elif session.current_issue is not None:
            self._display_spellcheck_issue(session.current_issue)
            self.status_value.set("Recovered interrupted review • No subtitle files changed")
        else:
            self._display_no_unknowns(len(session.files))
            self.status_value.set("Recovered completed review • Save any prepared changes")
        self._update_save_control()
        self._checkpoint_review(paused=session.recovery_paused)
        self._refresh_backup_restore_control()

    def _confirm_discard_unsaved_review(self, action: str) -> bool:
        session = getattr(self, "review_session", None)
        if session is None:
            return True
        has_changes = bool(getattr(self, "editing_cue", False))
        if not has_changes:
            try:
                has_changes = self.tool.review_has_changes(session)
            except (OSError, RuntimeError, UnicodeError):
                has_changes = True
        if not has_changes:
            return True
        return bool(self.messagebox.askyesno(
            "Discard unsaved changes?",
            f"This review contains subtitle changes that have not been saved.\n\n"
            f"Do you want to discard them and {action}?",
        ))

    def _open_project_page(self) -> None:
        try:
            opened = webbrowser.open(PROJECT_URL, new=2)
        except (OSError, RuntimeError) as error:
            self.messagebox.showerror("Could not open GitHub", str(error))
            return
        if not opened:
            self.messagebox.showerror(
                "Could not open GitHub",
                f"No browser accepted this address:\n\n{PROJECT_URL}",
            )
            return
        self.status_value.set("Opened the public GitHub project page")

    def _open_scowl_page(self) -> None:
        try:
            opened = webbrowser.open(SCOWL_URL, new=2)
        except (OSError, RuntimeError) as error:
            self.messagebox.showerror("Could not open SCOWL page", str(error))
            return
        if not opened:
            self.messagebox.showerror(
                "Could not open SCOWL page",
                f"No browser accepted this address:\n\n{SCOWL_URL}",
            )
            return
        self.status_value.set("Opened the SCOWL 2026.02.25 source page")

    def _clear_theme_draft_tracking(self) -> None:
        self.theme_draft_is_dirty = None
        self.save_theme_draft = None

    def _confirm_theme_navigation(self, destination_key: str) -> bool:
        """Protect unsaved theme edits before leaving the Themes workspace."""
        if getattr(self, "active_navigation_key", None) != "themes":
            return True
        if destination_key == "themes":
            return False
        dirty_check = getattr(self, "theme_draft_is_dirty", None)
        if dirty_check is None or not dirty_check():
            self._clear_theme_draft_tracking()
            return True
        answer = self.messagebox.askyesnocancel(
            "Save theme changes?",
            "The Themes page contains changes that have not been saved.\n\n"
            "Choose Yes to save them, No to discard them, or Cancel to stay "
            "on the Themes page.",
        )
        if answer is None:
            return False
        if answer:
            save_draft = getattr(self, "save_theme_draft", None)
            if save_draft is None or not save_draft():
                return False
        self._clear_theme_draft_tracking()
        return True

    def _show_options(self) -> None:
        """Show the categorized, immediately persisted GUI Options workspace."""
        if self.prepare_thread is not None:
            self.messagebox.showinfo(
                "Scan in progress",
                "Pause or finish the active scan before opening Options.",
            )
            return
        tk, ttk = self.tk, self.ttk
        self.scan_view.grid_remove()
        self.maintenance_workspace.grid()
        self._activate_navigation("options")
        for child in self.maintenance_workspace.winfo_children():
            child.destroy()
        self.maintenance_workspace.columnconfigure(0, weight=1)
        self.maintenance_workspace.rowconfigure(1, weight=1)
        ttk.Label(
            self.maintenance_workspace,
            text="Options",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))
        body = ttk.Frame(self.maintenance_workspace, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, minsize=255)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        category_card = ttk.Frame(body, style="Card.TFrame", padding=16)
        category_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        category_card.columnconfigure(0, weight=1)
        category_card.rowconfigure(1, weight=1)
        ttk.Label(
            category_card, text="Categories", style="Heading.TLabel"
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        category_list = tk.Listbox(
            category_card,
            exportselection=False,
            activestyle="none",
            font=("Segoe UI", 10),
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
        )
        category_list.configure(**listbox_theme_options(self.COLORS))
        category_list.grid(row=1, column=0, sticky="nsew")
        for title, _keys in OPTION_GROUPS:
            category_list.insert("end", title)

        self.options_detail_frame = ttk.Frame(
            body, style="Card.TFrame", padding=18
        )
        self.options_detail_frame.grid(row=0, column=1, sticky="nsew")
        self.options_detail_frame.columnconfigure(0, weight=1)

        def show_selected(_event=None):
            selection = category_list.curselection()
            if not selection:
                return
            title, keys = OPTION_GROUPS[int(selection[0])]
            self._render_option_group(title, keys)

        category_list.bind("<<ListboxSelect>>", show_selected)
        category_list.selection_set(0)
        category_list.activate(0)
        show_selected()
        self.status_value.set(
            "Options save immediately • Changes apply to new scans and future formatting steps"
        )

    def _render_option_group(self, title: str, keys: Sequence[str]) -> None:
        """Render one option category without replacing the surrounding workspace."""
        ttk = self.ttk
        frame = self.options_detail_frame
        for child in frame.winfo_children():
            child.destroy()
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 5)
        )
        ttk.Label(
            frame,
            text="Changes are validated and saved immediately.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        column_header = self.tk.Frame(
            frame,
            background=self.COLORS["card"],
            padx=12,
        )
        column_header.grid(row=2, column=0, sticky="ew", pady=(0, 3))
        column_header.columnconfigure(0, weight=1)
        header_right_zone = self.tk.Frame(
            column_header,
            background=self.COLORS["card"],
            width=OPTION_RIGHT_ZONE_WIDTH,
            height=20,
        )
        header_right_zone.grid(row=0, column=1, sticky="e")
        header_right_zone.grid_propagate(False)
        self.tk.Label(
            header_right_zone,
            text=OPTION_TOOLTIP_HEADING,
            background=self.COLORS["card"],
            foreground=self.COLORS["help"],
            font=("Segoe UI", 8, "bold"),
        ).place(**option_tooltip_position())

        for row_number, key in enumerate(keys, start=3):
            background = option_row_color(row_number - 3, self.COLORS)
            card = self.tk.Frame(
                frame,
                background=background,
                padx=12,
                pady=9,
                borderwidth=0,
            )
            card.grid(row=row_number, column=0, sticky="ew", pady=(0, 3))
            card.columnconfigure(
                OPTION_SWITCH_COLUMN, minsize=OPTION_SWITCH_COLUMN_WIDTH
            )
            card.columnconfigure(1, weight=1)
            right_zone = self.tk.Frame(
                card,
                background=background,
                width=OPTION_RIGHT_ZONE_WIDTH,
                height=32,
            )
            right_zone.grid(row=0, column=2, sticky="e")
            right_zone.grid_propagate(False)
            label_text = OPTION_LABELS[key]
            example = OPTION_INLINE_EXAMPLES.get(key)
            if example:
                label_text = f"{label_text}  {example}"
            unavailable_in_all_caps = (
                self.tool.options.get("capitalization_mode") == "all_caps"
                and key in CAPITALIZATION_DEPENDENT_OPTIONS
            )
            label = self.tk.Label(
                card,
                text=label_text,
                background=background,
                foreground=(
                    self.COLORS["muted"]
                    if unavailable_in_all_caps
                    else self.COLORS["option_text"]
                ),
                font=("Segoe UI", 10),
                wraplength=660,
                justify="left",
            )
            help_icon = self.tk.Label(
                right_zone,
                text="?",
                background=background,
                foreground=self.COLORS["help"],
                font=("Segoe UI", 9, "bold"),
                cursor="question_arrow",
                padx=3,
            )
            help_text = (
                "Not available in All caps mode. Go to Options → Spelling and Text Cleanup and change Capitalization preference to adjust this setting."
                if unavailable_in_all_caps
                else OPTION_DESCRIPTIONS[key]
            )
            self._attach_tooltip(help_icon, help_text)
            help_icon.place(**option_tooltip_position())

            current = self.tool.options[key]
            if key == "capitalization_mode":
                label.grid(
                    row=0,
                    column=OPTION_SWITCH_COLUMN,
                    columnspan=2,
                    sticky="w",
                    padx=(0, 8),
                )
                display_value = CAPITALIZATION_MODES.get(str(current), "Select…")
                variable = self.tk.StringVar(value=display_value)
                controls = self.tk.Frame(right_zone, background=background)
                controls.place(relx=1.0, rely=0.5, anchor="e")
                combo = ttk.Combobox(
                    controls,
                    textvariable=variable,
                    values=tuple(CAPITALIZATION_MODES.values()),
                    state="readonly",
                    width=22,
                )
                combo.pack(side="left")
                combo.bind(
                    "<<ComboboxSelected>>",
                    lambda _event, value=variable, group_title=title, group_keys=keys: self._save_gui_capitalization_option(
                        value, group_title, group_keys
                    ),
                )
            elif isinstance(DEFAULT_OPTIONS[key], bool):
                label.grid(row=0, column=1, sticky="w", padx=(0, 8))
                control = OptionToggle(
                    self.tk,
                    card,
                    bool(current),
                    command=lambda value, option_key=key: self._save_gui_boolean_option(
                        option_key, value
                    ),
                    background=background,
                    palette=self.COLORS,
                    enabled=not unavailable_in_all_caps,
                )
                control.grid(row=0, column=OPTION_SWITCH_COLUMN, sticky="w")
            else:
                label.grid(
                    row=0,
                    column=OPTION_SWITCH_COLUMN,
                    columnspan=2,
                    sticky="w",
                    padx=(0, 8),
                )
                variable = self.tk.StringVar(value=str(current))
                controls = self.tk.Frame(right_zone, background=background)
                controls.place(relx=1.0, rely=0.5, anchor="e")
                entry = ttk.Entry(
                    controls,
                    textvariable=variable,
                    width=8,
                    justify="right",
                )
                entry.pack(side="left")
                ttk.Button(
                    controls,
                    text="Apply",
                    command=lambda option_key=key, value=variable: self._save_gui_integer_option(
                        option_key, value
                    ),
                ).pack(side="left", padx=(6, 0))
                entry.bind(
                    "<Return>",
                    lambda _event, option_key=key, value=variable: self._save_gui_integer_option(
                        option_key, value
                    ),
                )

    def _save_gui_capitalization_option(
        self, variable, group_title: str, group_keys: Sequence[str]
    ) -> None:
        selected = str(variable.get())
        mode = next(
            (key for key, label in CAPITALIZATION_MODES.items() if label == selected),
            None,
        )
        try:
            self.tool.set_option_value("capitalization_mode", mode)
        except (OSError, RuntimeError, ValueError) as error:
            variable.set(
                CAPITALIZATION_MODES.get(
                    str(self.tool.options.get("capitalization_mode", "")), "Select…"
                )
            )
            self.messagebox.showerror("Could not save option", str(error))
            return
        self.status_value.set(f"Saved option: {CAPITALIZATION_MODES[mode]}")
        self._saved_capitalization_mode = mode
        self._temporary_capitalization_mode = False
        self._render_option_group(group_title, group_keys)

    def _save_gui_boolean_option(self, key: str, variable) -> None:
        previous = bool(self.tool.options[key])
        try:
            self.tool.set_option_value(key, bool(variable.get()))
        except (OSError, RuntimeError, ValueError) as error:
            variable.set(previous)
            self.messagebox.showerror("Could not save option", str(error))
            self.status_value.set("Option was not changed")
            return
        self.status_value.set(f"Saved option: {OPTION_LABELS[key]}")

    def _save_gui_integer_option(self, key: str, variable) -> None:
        raw = str(variable.get()).strip()
        previous = int(self.tool.options[key])
        if not raw.isdigit() or int(raw) <= 0:
            variable.set(str(previous))
            self.messagebox.showwarning(
                "Invalid option value", "Enter a positive whole number."
            )
            return
        value = int(raw)
        allow_long = False
        if key == "maximum_universe_display_name_length" and value > 32:
            allow_long = bool(self.messagebox.askyesno(
                "Long Universe display names",
                "Universe names longer than 32 characters may break table layouts.\n\n"
                "Save this display limit anyway?",
            ))
            if not allow_long:
                variable.set(str(previous))
                return
        try:
            self.tool.set_option_value(
                key,
                value,
                allow_long_universe_names=allow_long,
            )
        except (OSError, RuntimeError, ValueError) as error:
            variable.set(str(previous))
            self.messagebox.showerror("Could not save option", str(error))
            self.status_value.set("Option was not changed")
            return
        variable.set(str(value))
        self.status_value.set(f"Saved option: {OPTION_LABELS[key]}")

    def _save_theme_preferences(
        self, selected: str, custom: dict[str, str]
    ) -> None:
        text = theme_preferences_text(selected, custom)
        self.tool.atomic_write_text(self.theme_settings_path, text)
        self.saved_custom_theme = resolve_theme(CUSTOM_THEME_NAME, custom)

    def _restart_for_theme_change(self) -> None:
        session = getattr(self, "review_session", None)
        if getattr(self, "editing_cue", False):
            if not self._confirm_discard_unsaved_review("restart the application"):
                return
        if session is not None and not self._checkpoint_review(
            paused=getattr(self, "scan_paused", False)
        ):
            if not self._confirm_discard_unsaved_review("restart the application"):
                return
        try:
            restart_current_process()
        except (OSError, RuntimeError, ValueError) as error:
            self.messagebox.showerror(
                "Could not restart",
                f"The theme was saved, but the application could not restart.\n\n{error}",
            )
            self.status_value.set(
                "Theme saved • Close and reopen the application to apply it"
            )
            return
        self.root.destroy()

    def _show_themes(self) -> None:
        if self.prepare_thread is not None:
            self.messagebox.showinfo(
                "Scan in progress",
                "Pause or finish the active scan before opening Themes.",
            )
            return
        tk, ttk = self.tk, self.ttk
        self.scan_view.grid_remove()
        self.maintenance_workspace.grid()
        self._activate_navigation("themes")
        for child in self.maintenance_workspace.winfo_children():
            child.destroy()
        self.maintenance_workspace.columnconfigure(0, weight=1)
        self.maintenance_workspace.rowconfigure(1, weight=0)
        self.maintenance_workspace.rowconfigure(2, weight=1)
        ttk.Label(
            self.maintenance_workspace,
            text="Themes",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        selector = ttk.Frame(
            self.maintenance_workspace, style="Card.TFrame", padding=18
        )
        selector.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        selector.columnconfigure(1, weight=1)
        ttk.Label(selector, text="Theme", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        selected_theme = tk.StringVar(value=self.theme_name)
        theme_combo = ttk.Combobox(
            selector,
            textvariable=selected_theme,
            values=(DEFAULT_THEME_NAME, DARK_THEME_NAME, CUSTOM_THEME_NAME),
            state="readonly",
            width=16,
        )
        theme_combo.grid(row=0, column=1, sticky="w")
        theme_description = tk.StringVar()
        ttk.Label(
            selector,
            textvariable=theme_description,
            style="Muted.TLabel",
            wraplength=850,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))

        editor_card = ttk.Frame(
            self.maintenance_workspace, style="Card.TFrame", padding=16
        )
        editor_card.grid(row=2, column=0, sticky="nsew")
        editor_card.columnconfigure(0, weight=1)
        editor_card.rowconfigure(2, weight=1)
        ttk.Label(editor_card, text="Custom colors", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            editor_card,
            text=(
                "Custom begins as a complete copy of Ocean. Enter colors as "
                "#RGB or #RRGGBB. Saving Custom validates every field; it does "
                "not add new color roles to the theme. Use either reset button "
                "as a new starting point."
            ),
            style="Muted.TLabel",
            wraplength=920,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        color_canvas = tk.Canvas(
            editor_card,
            background=self.COLORS["card"],
            borderwidth=0,
            highlightthickness=0,
        )
        color_scrollbar = ttk.Scrollbar(
            editor_card, orient="vertical", command=color_canvas.yview
        )
        color_canvas.configure(yscrollcommand=color_scrollbar.set)
        color_canvas.grid(row=2, column=0, sticky="nsew")
        color_scrollbar.grid(row=2, column=1, sticky="ns")
        color_rows = tk.Frame(color_canvas, background=self.COLORS["card"])
        color_rows.columnconfigure(1, weight=1)
        color_window = color_canvas.create_window(
            (0, 0), window=color_rows, anchor="nw"
        )
        custom_values = {
            key: tk.StringVar(value=self.saved_custom_theme.get(key, OCEAN_THEME[key]))
            for key in OCEAN_THEME
        }
        for row_number, (key, label, description) in enumerate(THEME_COLOR_FIELDS):
            background = option_row_color(row_number, self.COLORS)
            row = tk.Frame(color_rows, background=background, padx=12, pady=8)
            row.grid(row=row_number, column=0, columnspan=2, sticky="ew")
            row.columnconfigure(1, weight=1)
            tk.Label(
                row,
                text=label,
                background=background,
                foreground=self.COLORS["option_text"],
                font=("Segoe UI", 9, "bold"),
                width=23,
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=(0, 12))
            tk.Label(
                row,
                text=description,
                background=background,
                foreground=self.COLORS["muted"],
                font=("Segoe UI", 9),
                anchor="w",
                justify="left",
                wraplength=620,
            ).grid(row=0, column=1, sticky="ew", padx=(0, 12))
            entry = ttk.Entry(
                row,
                textvariable=custom_values[key],
                width=11,
                justify="center",
            )
            entry.grid(row=0, column=2, sticky="e")

        def update_color_scrollregion(_event=None) -> None:
            color_canvas.configure(scrollregion=color_canvas.bbox("all"))

        def fit_color_rows(event) -> None:
            color_canvas.itemconfigure(color_window, width=max(1, event.width))

        color_rows.bind("<Configure>", update_color_scrollregion)
        color_canvas.bind("<Configure>", fit_color_rows)

        controls = ttk.Frame(selector, style="Card.TFrame")
        controls.grid(
            row=2, column=0, columnspan=3, sticky="e", pady=(12, 0)
        )

        def reset_custom(source: str) -> None:
            for key, value in theme_seed(source).items():
                custom_values[key].set(value)
            self.status_value.set(
                f"Custom theme reset to {source} values • Choose Save theme to keep it"
            )

        def save_theme() -> bool:
            selected = selected_theme.get()
            custom = {key: value.get().strip() for key, value in custom_values.items()}
            try:
                restart_needed = theme_change_requires_restart(
                    self.active_theme_name,
                    self.active_theme_palette,
                    selected,
                    custom,
                )
                self._save_theme_preferences(selected, custom)
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                self.messagebox.showerror("Could not save theme", str(error))
                self.status_value.set("Theme was not changed")
                return False
            self.theme_name = selected
            if restart_needed and self.messagebox.askyesno(
                "Restart to apply theme?",
                f"{selected} was saved successfully.\n\n"
                "Restart the application now to apply the change?",
            ):
                self._restart_for_theme_change()
                # A successful restart destroys this Tk instance. If launch failed,
                # remain on Themes so the status and error message stay visible.
                return False
            self.status_value.set(
                f"Saved theme: {selected}"
                + (
                    " • Restart the application to apply it"
                    if restart_needed
                    else " • The running theme already matches"
                )
            )
            return True

        reset_ocean_button = ttk.Button(
            controls,
            text="Reset Custom to Ocean",
            command=lambda: reset_custom(DEFAULT_THEME_NAME),
        )
        reset_ocean_button.pack(side="left", padx=(0, 8))
        reset_dark_button = ttk.Button(
            controls,
            text="Reset Custom to Dark",
            command=lambda: reset_custom(DARK_THEME_NAME),
        )
        reset_dark_button.pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Save theme", command=save_theme).pack(side="left")

        descriptions = {
            DEFAULT_THEME_NAME: (
                "Ocean is the original light theme and the default for fresh installs."
            ),
            DARK_THEME_NAME: (
                "Dark uses the same interface roles with lower-light backgrounds and controls."
            ),
            CUSTOM_THEME_NAME: (
                "Custom uses the saved colors below. It starts from Ocean and can be reset from Ocean or Dark."
            ),
        }

        def selection_changed(_event=None) -> None:
            selected = selected_theme.get()
            theme_description.set(
                descriptions.get(selected, "Choose Ocean, Dark, or Custom.")
                + " Saved changes apply after restarting the application."
            )
            if selected == CUSTOM_THEME_NAME:
                editor_card.grid()
                reset_ocean_button.configure(state="normal")
                reset_dark_button.configure(state="normal")
            else:
                editor_card.grid_remove()
                reset_ocean_button.configure(state="disabled")
                reset_dark_button.configure(state="disabled")

        theme_combo.bind("<<ComboboxSelected>>", selection_changed)
        selection_changed()

        def theme_draft_is_dirty() -> bool:
            if selected_theme.get() != self.theme_name:
                return True
            return any(
                custom_values[key].get().strip() != self.saved_custom_theme[key]
                for key in OCEAN_THEME
            )

        self.theme_draft_is_dirty = theme_draft_is_dirty
        self.save_theme_draft = save_theme
        self.status_value.set(
            "Themes • Choose a built-in theme or edit and save Custom colors"
        )

    def _show_about(self) -> None:
        if self.prepare_thread is not None:
            self.messagebox.showinfo(
                "Scan in progress", "Pause or finish the active scan before opening About."
            )
            return
        tk, ttk = self.tk, self.ttk
        self.scan_view.grid_remove()
        self.maintenance_workspace.grid()
        self._activate_navigation("about")
        for child in self.maintenance_workspace.winfo_children():
            child.destroy()
        self.maintenance_workspace.columnconfigure(0, weight=1)
        self.maintenance_workspace.rowconfigure(1, weight=1)
        ttk.Label(
            self.maintenance_workspace,
            text="About Subtitle Universe Spellcheck",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))
        card = ttk.Frame(self.maintenance_workspace, style="Card.TFrame", padding=24)
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        ttk.Label(
            card,
            text=f"Version {SCRIPT_VERSION}",
            style="Heading.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            card,
            text=(
                "A conservative, cross-platform subtitle cleanup and spellcheck tool "
                "with Base, User, and Universe dictionaries."
            ),
            style="Body.TLabel",
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(10, 18))
        ttk.Label(card, text="Project page", style="Heading.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        link = tk.Label(
            card,
            text=PROJECT_URL,
            bg=self.COLORS["card"],
            fg=self.COLORS["link"],
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
            anchor="w",
        )
        link.grid(row=3, column=0, sticky="w", pady=(5, 18))
        link.bind("<Button-1>", lambda _event: self._open_project_page())
        ttk.Label(card, text="SCOWL dictionary credit", style="Heading.TLabel").grid(
            row=4, column=0, sticky="w"
        )
        ttk.Label(
            card,
            text=(
                f"{SCOWL_CREDIT}\n\n"
                "The complete required notice is distributed as "
                "dictionaries/base/SCOWL-COPYRIGHT.txt."
            ),
            style="Body.TLabel",
            wraplength=820,
            justify="left",
        ).grid(row=5, column=0, sticky="nw", pady=(6, 18))
        scowl_link = tk.Label(
            card,
            text="View the SCOWL 2026.02.25 source page",
            bg=self.COLORS["card"],
            fg=self.COLORS["link"],
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
            anchor="w",
        )
        scowl_link.grid(row=6, column=0, sticky="w", pady=(0, 18))
        scowl_link.bind("<Button-1>", lambda _event: self._open_scowl_page())
        ttk.Label(
            card,
            text="Application source: MIT License",
            style="Muted.TLabel",
        ).grid(row=7, column=0, sticky="w")
        self.status_value.set("About • Version, project link, and dictionary credit")

    def _show_session_log_maintenance(self) -> None:
        if self.prepare_thread is not None:
            self.messagebox.showinfo(
                "Scan in progress",
                "Pause or finish the active scan before opening Session Log Maintenance.",
            )
            return
        ttk = self.ttk
        self.scan_view.grid_remove()
        self.maintenance_workspace.grid()
        self._activate_navigation("session_log")
        for child in self.maintenance_workspace.winfo_children():
            child.destroy()
        self.maintenance_workspace.columnconfigure(0, weight=1)
        self.maintenance_workspace.rowconfigure(1, weight=1)
        ttk.Label(
            self.maintenance_workspace,
            text="Session Log Maintenance",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))
        card = ttk.Frame(
            self.maintenance_workspace,
            style="Card.TFrame",
            padding=24,
        )
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        ttk.Label(
            card,
            text="Flush session log",
            style="Heading.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            card,
            text=SESSION_LOG_HELP,
            style="Body.TLabel",
            wraplength=780,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(10, 18))
        ttk.Label(
            card,
            text=(
                "Use this only when you no longer need the history shown by "
                "Recent additions. This action cannot be undone."
            ),
            style="Muted.TLabel",
            wraplength=780,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(0, 18))
        ttk.Button(
            card,
            text="Flush session log",
            command=self._flush_session_log_from_gui,
        ).grid(row=3, column=0, sticky="w")
        self.status_value.set(
            "Session Log Maintenance • Dictionary entries and recovery remain unchanged"
        )

    def _flush_session_log_from_gui(self) -> None:
        confirmed = self.messagebox.askyesno(
            "Flush session log?",
            "Clear the history used by Recent additions?\n\n"
            "Dictionary entries and interrupted-scan recovery will not be removed. "
            "This action cannot be undone.",
        )
        if not confirmed:
            return
        try:
            self.tool.clear_session_log()
        except (OSError, RuntimeError) as error:
            self.messagebox.showerror("Could not flush session log", str(error))
            self.status_value.set("Session log was not changed")
            return
        self.messagebox.showinfo(
            "Session log flushed",
            "Recent-addition history was cleared. Dictionary entries and recovery "
            "state were not changed.",
        )
        self.status_value.set("Session log flushed • Dictionary entries remain unchanged")

    def _center_child_window(self, window) -> None:
        self.root.update_idletasks()
        window.update_idletasks()
        position = centered_child_position(
            (
                self.root.winfo_rootx(),
                self.root.winfo_rooty(),
                self.root.winfo_width(),
                self.root.winfo_height(),
            ),
            (window.winfo_width(), window.winfo_height()),
            (window.winfo_screenwidth(), window.winfo_screenheight()),
        )
        window.geometry(f"+{position[0]}+{position[1]}")

    def _prompt_typed_confirmation(self, title: str, message: str) -> bool:
        dialog = self.tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(True, False)
        result = {"confirmed": False}
        value = self.tk.StringVar()
        body = self.ttk.Frame(dialog, style="Card.TFrame", padding=18)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        self.ttk.Label(
            body, text=message, style="Body.TLabel", wraplength=520, justify="left"
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        entry = self.ttk.Entry(body, textvariable=value, width=32)
        entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 16))

        def confirm(_event=None):
            if value.get() != "YES":
                self.messagebox.showwarning(
                    "Confirmation required",
                    "Type YES in uppercase to confirm the restore.",
                    parent=dialog,
                )
                entry.focus_set()
                return "break"
            result["confirmed"] = True
            dialog.destroy()
            return "break"

        self.ttk.Button(body, text="Cancel", command=dialog.destroy).grid(
            row=2, column=0, sticky="e", padx=(0, 8)
        )
        self.ttk.Button(body, text="Restore", command=confirm).grid(
            row=2, column=1, sticky="e"
        )
        entry.bind("<Return>", confirm)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._center_child_window(dialog)
        entry.focus_set()
        self.root.wait_window(dialog)
        return result["confirmed"]

    def _prompt_text_fields(
        self,
        title: str,
        fields: Sequence[tuple[str, str]],
    ) -> Optional[tuple[str, ...]]:
        """Show a responsive entry form; Enter advances fields, then submits."""
        tk, ttk = self.tk, self.ttk
        window = tk.Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        window.geometry(f"700x{180 + (len(fields) * 58)}")
        window.minsize(520, 165 + (len(fields) * 48))
        window.resizable(True, True)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        frame = ttk.Frame(window, padding=22)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        values = []
        entries = []
        result = None

        for row, (label, initial) in enumerate(fields):
            ttk.Label(frame, text=label, style="Heading.TLabel").grid(
                row=row * 2, column=0, sticky="w", pady=(0 if row == 0 else 12, 5)
            )
            value = tk.StringVar(value=initial)
            entry = ttk.Entry(
                frame, textvariable=value, style="Large.TEntry", font=("Segoe UI", 11)
            )
            entry.grid(row=(row * 2) + 1, column=0, sticky="ew")
            values.append(value)
            entries.append(entry)

        controls = ttk.Frame(frame)
        controls.grid(row=len(fields) * 2, column=0, sticky="e", pady=(18, 0))

        def cancel(_event=None):
            window.destroy()

        def submit(_event=None):
            nonlocal result
            result = tuple(value.get() for value in values)
            window.destroy()
            return "break"

        ttk.Button(controls, text="Cancel", command=cancel).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(controls, text="Save", command=submit).pack(side="left")
        for index, entry in enumerate(entries):
            if index + 1 < len(entries):
                entry.bind(
                    "<Return>",
                    lambda _event, next_entry=entries[index + 1]: (
                        next_entry.focus_set(),
                        next_entry.icursor("end"),
                        "break",
                    )[-1],
                )
            else:
                entry.bind("<Return>", submit)
        window.bind("<Escape>", cancel)
        window.protocol("WM_DELETE_WINDOW", cancel)
        self._center_child_window(window)
        window.grab_set()
        entries[0].focus_set()
        entries[0].selection_range(0, "end")
        self.root.wait_window(window)
        return result

    def _prompt_maintenance_values(
        self,
        kind: str,
        *,
        title: str,
        entry: str = "",
        output: str = "",
    ) -> Optional[tuple[str, str]]:
        fields = (
            (("Find word or phrase", entry), ("Replace with", output))
            if kind == "substitutions"
            else (("Word, name, or exact phrase", entry),)
        )
        response = self._prompt_text_fields(title, fields)
        if response is None:
            return None
        return response[0], response[1] if len(response) > 1 else ""

    def _maintenance_path(
        self, target: str, kind: str, universe: Optional[str]
    ) -> Path:
        filename = (
            f"{kind}.txt"
            if kind in {"words", "names", "acronyms"}
            else "substitutions.tsv"
        )
        if target == "user":
            language = language_key(self.language_value.get())
            return self.tool.user_dir / f"{language}_{filename}"
        if target == "universe" and universe:
            return self.tool.universe_dir / universe / filename
        raise ValueError("Choose a Universe Dictionary before maintaining it.")

    def _maintenance_event(
        self,
        target: str,
        kind: str,
        universe: Optional[str],
        *,
        entry: str = "",
        output: str = "",
        language: Optional[str] = None,
    ) -> dict:
        event = {"target": target, "universe": universe}
        if target == "user":
            event["base_language"] = language or language_key(
                self.language_value.get()
            )
        if kind == "substitutions":
            event.update({"input": entry, "output": output})
        else:
            event.update({"list": kind, "word": entry})
        return event

    def _load_maintenance_entries(
        self, target: str, kind: str, universe: Optional[str]
    ) -> list:
        path = self._maintenance_path(target, kind, universe)
        if kind == "substitutions":
            return list(self.tool.load_substitutions(path).items())
        if not path.exists():
            return []
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _add_maintenance_entry(
        self,
        target: str,
        kind: str,
        universe: Optional[str],
        entry: str,
        output: Optional[str] = None,
    ) -> bool:
        entry = entry.strip()
        if not entry:
            return False
        path = self._maintenance_path(target, kind, universe)
        if kind == "substitutions":
            if output is None or not output.strip():
                return False
            self.tool.set_maintenance_substitution(
                path, target, universe, entry, output.strip()
            )
            return True
        if kind == "acronyms" and not self._confirm_acronym_addition(
            entry,
            target=target,
            language=(
                language_key(self.language_value.get())
                if target == "user"
                else None
            ),
            universe=universe,
        ):
            return False
        if (
            kind in {"words", "names"}
            and not any(character.isspace() for character in entry)
            and not self._confirm_word_addition(
                entry,
                target=target,
                language=(
                    language_key(self.language_value.get())
                    if target == "user"
                    else None
                ),
                universe=universe,
            )
        ):
            return False
        return bool(self.tool.add_word_or_name_entries(
            path, target, kind, universe, [entry]
        ))

    def _edit_maintenance_entry(
        self,
        target: str,
        kind: str,
        universe: Optional[str],
        old_entry: str,
        new_entry: str,
        old_output: str = "",
        new_output: str = "",
    ) -> bool:
        new_entry = new_entry.strip()
        if not new_entry:
            return False
        path = self._maintenance_path(target, kind, universe)
        if kind == "acronyms" and not self._confirm_acronym_addition(
            new_entry,
            target=target,
            language=(
                language_key(self.language_value.get())
                if target == "user"
                else None
            ),
            universe=universe,
        ):
            return False
        if (
            kind in {"words", "names"}
            and not any(character.isspace() for character in new_entry)
            and not self._confirm_word_addition(
                new_entry,
                target=target,
                language=(
                    language_key(self.language_value.get())
                    if target == "user"
                    else None
                ),
                universe=universe,
            )
        ):
            return False
        if kind == "substitutions":
            if not new_output.strip():
                return False
            return bool(self.tool.replace_maintenance_substitution(
                path,
                target,
                universe,
                old_entry,
                new_entry,
                new_output.strip(),
            ))
        return bool(self.tool.replace_maintenance_dictionary_entry(
            path,
            target,
            kind,
            universe,
            old_entry,
            new_entry,
        ))

    def _remove_maintenance_entry(
        self,
        target: str,
        kind: str,
        universe: Optional[str],
        entry: str,
        output: str = "",
    ) -> None:
        event = self._maintenance_event(
            target, kind, universe, entry=entry, output=output
        )
        if kind == "substitutions":
            self.tool.delete_substitution(event)
        else:
            self.tool.delete_dictionary_word(event)

    def _move_maintenance_entry(
        self,
        target: str,
        kind: str,
        universe: Optional[str],
        entry: str,
        output: str = "",
        *,
        source_language: Optional[str] = None,
        destination_target: str,
        destination_universe: Optional[str] = None,
        destination_language: Optional[str] = None,
    ) -> bool:
        event = self._maintenance_event(
            target,
            kind,
            universe,
            entry=entry,
            output=output,
            language=source_language,
        )
        if kind == "substitutions":
            return self.tool.move_substitution_to(
                event,
                destination_target,
                destination_universe,
                language=destination_language,
            )
        if kind == "acronyms" and not self._confirm_acronym_addition(
            entry,
            target=destination_target,
            language=destination_language,
            universe=destination_universe,
        ):
            return False
        if (
            kind in {"words", "names"}
            and not any(character.isspace() for character in entry)
            and not self._confirm_word_addition(
                entry,
                target=destination_target,
                language=destination_language,
                universe=destination_universe,
            )
        ):
            return False
        return self.tool.move_dictionary_word_to(
            event,
            destination_target,
            destination_universe,
            language=destination_language,
        )

    def _single_selected_entry(self, entries: Sequence):
        """Return one editable selection or explain why batch edit is unavailable."""
        if len(entries) != 1:
            self.messagebox.showinfo(
                "Select one entry",
                "Edit works with one entry at a time. Move and Remove support multiple selections.",
            )
            return None
        return entries[0]

    def _prompt_recent_destination(
        self, event_or_events
    ) -> Optional[tuple[str, Optional[str], Optional[str]]]:
        events = (
            [event_or_events]
            if isinstance(event_or_events, dict)
            else list(event_or_events)
        )
        groups = recent_destination_groups(events, self.tool.list_universes())
        if not any(groups.values()):
            self.messagebox.showinfo(
                "No other dictionaries",
                "Create another Universe Dictionary before moving this entry.",
            )
            return None
        tk, ttk = self.tk, self.ttk
        window = tk.Toplevel(self.root)
        window.title("Move dictionary entry")
        window.transient(self.root)
        window.geometry("700x300")
        window.minsize(520, 280)
        window.resizable(True, False)
        window.columnconfigure(0, weight=1)
        frame = ttk.Frame(window, padding=22)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="Dictionary type", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        current_targets = {event.get("target") for event in events}
        current_target = next(iter(current_targets)) if len(current_targets) == 1 else None
        preferred_target = "universe" if current_target == "user" else "user"
        if not groups[preferred_target]:
            preferred_target = "user" if groups["user"] else "universe"
        selected_target = tk.StringVar(value=preferred_target)
        radio_frame = ttk.Frame(frame)
        radio_frame.grid(row=1, column=0, sticky="w", pady=(0, 14))
        ttk.Radiobutton(
            radio_frame,
            text="User Dictionary",
            variable=selected_target,
            value="user",
            state="normal" if groups["user"] else "disabled",
        ).pack(side="left", padx=(0, 24))
        ttk.Radiobutton(
            radio_frame,
            text="Universe Dictionary",
            variable=selected_target,
            value="universe",
            state="normal" if groups["universe"] else "disabled",
        ).pack(side="left")
        destination_label = tk.StringVar(value="")
        destination_heading = ttk.Frame(frame, style="Card.TFrame")
        destination_heading.grid(row=2, column=0, sticky="w", pady=(0, 6))
        ttk.Label(
            destination_heading,
            textvariable=destination_label,
            style="Heading.TLabel",
        ).pack(side="left")
        language_help = self._language_help_icon(destination_heading)
        language_help.pack(side="left", padx=(5, 0))
        selected = tk.StringVar(value="")
        choices = ttk.Combobox(
            frame,
            textvariable=selected,
            state="readonly",
            font=("Segoe UI", 11),
        )
        choices.grid(row=3, column=0, sticky="ew")
        controls = ttk.Frame(frame)
        controls.grid(row=4, column=0, sticky="e", pady=(18, 0))
        result = None

        def cancel(_event=None):
            window.destroy()

        def submit(_event=None):
            nonlocal result
            options = groups[selected_target.get()]
            result = next(
                (
                    (target, universe, language)
                    for label, target, universe, language in options
                    if label == selected.get()
                ),
                None,
            )
            window.destroy()
            return "break"

        def refresh_choices(*_args):
            target_name = selected_target.get()
            options = groups[target_name]
            destination_label.set(
                "Base language" if target_name == "user" else "Universe"
            )
            if target_name == "user":
                language_help.pack(side="left", padx=(5, 0))
            else:
                language_help.pack_forget()
            values = tuple(option[0] for option in options)
            choices.configure(
                values=values,
                state="readonly" if values else "disabled",
            )
            selected.set(values[0] if values else "")
            move_button.configure(state="normal" if values else "disabled")

        ttk.Button(controls, text="Cancel", command=cancel).pack(
            side="left", padx=(0, 8)
        )
        move_button = ttk.Button(controls, text="Move", command=submit)
        move_button.pack(side="left")
        selected_target.trace_add("write", refresh_choices)
        choices.bind("<Return>", submit)
        window.bind("<Escape>", cancel)
        window.protocol("WM_DELETE_WINDOW", cancel)
        refresh_choices()
        self._center_child_window(window)
        window.grab_set()
        choices.focus_set()
        self.root.wait_window(window)
        return result

    def _show_recent_additions(self) -> None:
        if self.prepare_thread is not None:
            self.messagebox.showinfo(
                "Scan in progress",
                "Pause or finish the active scan before reviewing recent additions.",
            )
            return
        tk, ttk = self.tk, self.ttk
        self.scan_view.grid_remove()
        self.maintenance_workspace.grid()
        self._activate_navigation("recent")
        for child in self.maintenance_workspace.winfo_children():
            child.destroy()
        self.maintenance_workspace.columnconfigure(0, weight=1)
        self.maintenance_workspace.rowconfigure(1, weight=1)
        ttk.Label(
            self.maintenance_workspace,
            text="Recent Additions",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))
        panel = ttk.Frame(self.maintenance_workspace, style="Card.TFrame", padding=18)
        panel.grid(row=1, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        header = ttk.Frame(panel, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Current entries reconstructed from the session log and verified on disk",
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        category = tk.StringVar(value=RECENT_ADDITION_CATEGORIES[0])
        category_combo = ttk.Combobox(
            header,
            textvariable=category,
            values=RECENT_ADDITION_CATEGORIES,
            state="readonly",
            width=RECENT_ADDITION_CATEGORY_WIDTH,
        )
        category_combo.grid(row=0, column=1, sticky="e")

        help_text = tk.StringVar(value="Double-click an entry to edit it.")
        ttk.Label(panel, textvariable=help_text, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 6)
        )
        table = ttk.Treeview(
            panel,
            columns=("entry", "entry_type", "replacement", "location"),
            show="headings",
            selectmode="extended",
        )
        table.heading("entry", text="Entry")
        table.heading("entry_type", text="Type")
        table.heading("replacement", text="Replace with")
        table.heading("location", text="Dictionary")
        table.column("entry", width=360, minwidth=220, stretch=True)
        table.column("entry_type", width=120, minwidth=90, stretch=False)
        table.column("replacement", width=360, minwidth=220, stretch=True)
        table.column("location", width=230, minwidth=160, stretch=True)
        for tag, color in dictionary_row_colors(self.COLORS).items():
            table.tag_configure(tag, background=color)
        table.grid(row=2, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(panel, orient="vertical", command=table.yview)
        vertical.grid(row=2, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(panel, orient="horizontal", command=table.xview)
        horizontal.grid(row=3, column=0, sticky="ew")
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        table_status = tk.StringVar(value="")
        ttk.Label(panel, textvariable=table_status, style="Muted.TLabel").grid(
            row=4, column=0, sticky="w", pady=(8, 0)
        )
        controls = ttk.Frame(panel, style="Card.TFrame")
        controls.grid(row=5, column=0, sticky="e", pady=(12, 0))
        current_entries = []

        def substitutions_selected() -> bool:
            return category.get() == "Substitutions"

        def refresh(*_args) -> None:
            nonlocal current_entries
            for item in table.get_children():
                table.delete(item)
            try:
                current_entries = (
                    self.tool.recent_substitution_entries()
                    if substitutions_selected()
                    else self.tool.recent_dictionary_entries()
                )
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                self.messagebox.showerror("Could not read recent additions", str(error))
                current_entries = []
            if substitutions_selected():
                table.configure(displaycolumns=("entry", "replacement", "location"))
                table.heading("entry", text="Find word / phrase")
                help_text.set(
                    "Recent substitutions • Use Ctrl or Shift to select multiple entries."
                )
            else:
                table.configure(displaycolumns=("entry", "entry_type", "location"))
                table.heading("entry", text="Word, name, acronym, or exact phrase")
                help_text.set(
                    "Recent words, names, and acronyms • Use Ctrl or Shift to select multiple entries."
                )
            for index, event in enumerate(current_entries):
                if substitutions_selected():
                    values = (
                        event.get("input", ""),
                        "",
                        event.get("output", ""),
                        self.tool.recent_location_label(event),
                    )
                else:
                    values = (
                        event.get("word", ""),
                        {"names": "Name", "acronyms": "Acronym"}.get(
                            event.get("list"), "Word"
                        ),
                        "",
                        self.tool.recent_location_label(event),
                    )
                table.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=values,
                    tags=(dictionary_row_tag(index),),
                )
            count = len(current_entries)
            table_status.set(
                f"{count} verified recent entr{'y' if count == 1 else 'ies'}"
                if count
                else "No current recent additions in this category"
            )

        def selected_events() -> list[dict]:
            selection = table.selection()
            if not selection:
                self.messagebox.showinfo("Select an entry", "Select an entry first.")
                return []
            return table_selection_entries(selection, current_entries)

        def selected_event() -> Optional[dict]:
            events = selected_events()
            if not events:
                return None
            return self._single_selected_entry(events)

        def edit_entry() -> None:
            event = selected_event()
            if event is None:
                return
            kind = "substitutions" if substitutions_selected() else self.tool.dictionary_list_name(event)
            old_entry = event.get("input", "") if substitutions_selected() else event.get("word", "")
            old_output = event.get("output", "") if substitutions_selected() else ""
            values = self._prompt_maintenance_values(
                kind,
                title="Edit recent substitution" if substitutions_selected() else "Edit recent entry",
                entry=old_entry,
                output=old_output,
            )
            if values is None:
                return
            new_entry, new_output = values
            paths = (
                self.tool.substitution_paths_for_event(event)
                if substitutions_selected()
                else self.tool.dictionary_paths_for_event(event)
            )
            if len(paths) != 1:
                self.messagebox.showerror(
                    "Cannot identify dictionary",
                    "This legacy log entry does not identify one exact dictionary file.",
                )
                return
            if not substitutions_selected():
                if kind == "acronyms" and not self._confirm_acronym_addition(
                    new_entry,
                    target=event.get("target"),
                    language=event.get("base_language"),
                    universe=event.get("universe"),
                ):
                    return
                if (
                    kind in {"words", "names"}
                    and not any(character.isspace() for character in new_entry)
                    and not self._confirm_word_addition(
                        new_entry,
                        target=event.get("target"),
                        language=event.get("base_language"),
                        universe=event.get("universe"),
                    )
                ):
                    return
            try:
                if substitutions_selected():
                    changed = self.tool.replace_maintenance_substitution(
                        paths[0],
                        event.get("target"),
                        event.get("universe"),
                        old_entry,
                        new_entry,
                        new_output,
                    )
                else:
                    changed = self.tool.replace_maintenance_dictionary_entry(
                        paths[0],
                        event.get("target"),
                        self.tool.dictionary_list_name(event),
                        event.get("universe"),
                        old_entry,
                        new_entry,
                    )
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                self.messagebox.showerror("Could not edit recent addition", str(error))
                return
            refresh()
            self._refresh_context()
            self.status_value.set(
                "Recent addition updated" if changed else "No recent addition changed"
            )

        def move_entry() -> None:
            events = selected_events()
            if not events:
                return
            destination = self._prompt_recent_destination(events)
            if destination is None:
                return
            target_name, universe, language = destination
            moved_count = 0
            try:
                for event in events:
                    event_kind = self.tool.dictionary_list_name(event)
                    event_entry = str(event.get("word", ""))
                    if not substitutions_selected():
                        if event_kind == "acronyms" and not self._confirm_acronym_addition(
                            event_entry,
                            target=target_name,
                            language=language,
                            universe=universe,
                        ):
                            continue
                        if (
                            event_kind in {"words", "names"}
                            and not any(character.isspace() for character in event_entry)
                            and not self._confirm_word_addition(
                                event_entry,
                                target=target_name,
                                language=language,
                                universe=universe,
                            )
                        ):
                            continue
                    moved = (
                        self.tool.move_substitution_to(
                            event, target_name, universe, language=language
                        )
                        if substitutions_selected()
                        else self.tool.move_dictionary_word_to(
                            event, target_name, universe, language=language
                        )
                    )
                    moved_count += int(moved)
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                refresh()
                self._refresh_context()
                self.messagebox.showerror("Could not move recent addition", str(error))
                return
            refresh()
            self._refresh_context()
            self.status_value.set(
                f"{moved_count} recent entr{'y' if moved_count == 1 else 'ies'} moved"
            )

        def remove_entry() -> None:
            events = selected_events()
            if not events:
                return
            if len(events) == 1:
                event = events[0]
                display = (
                    event.get("input")
                    if substitutions_selected()
                    else event.get("word")
                )
                prompt = (
                    f'Remove “{display}” from '
                    f"{self.tool.recent_location_label(event)}?"
                )
            else:
                prompt = f"Remove all {len(events)} selected recent additions?"
            if not self.messagebox.askyesno(
                "Remove recent addition?",
                prompt,
                icon="warning",
                parent=self.root,
            ):
                return
            try:
                for event in events:
                    if substitutions_selected():
                        self.tool.delete_substitution(event)
                    else:
                        self.tool.delete_dictionary_word(event)
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                refresh()
                self._refresh_context()
                self.messagebox.showerror("Could not remove recent addition", str(error))
                return
            refresh()
            self._refresh_context()
            count = len(events)
            self.status_value.set(
                f"{count} recent entr{'y' if count == 1 else 'ies'} removed"
            )

        ttk.Button(controls, text="Refresh", command=refresh).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(controls, text="Edit", command=edit_entry).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(controls, text="Move", command=move_entry).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(controls, text="Remove", command=remove_entry).pack(side="left")
        category_combo.bind("<<ComboboxSelected>>", refresh)
        table.bind("<Double-1>", lambda _event: edit_entry())
        refresh()
        self.status_value.set("Recent additions • Verified against current dictionary files")

    def _open_dictionary_maintenance(self, target: str) -> None:
        if self.prepare_thread is not None:
            self.messagebox.showinfo(
                "Scan in progress",
                "Pause or finish the active scan before opening dictionary maintenance.",
            )
            return

        tk, ttk = self.tk, self.ttk
        self.scan_view.grid_remove()
        self.maintenance_workspace.grid()
        self._activate_navigation(f"{target}_dictionary")
        for child in self.maintenance_workspace.winfo_children():
            child.destroy()
        self.maintenance_workspace.columnconfigure(0, weight=1)
        self.maintenance_workspace.rowconfigure(1, weight=1)

        title = (
            "User Dictionary Maintenance"
            if target == "user"
            else "Universe Dictionary Maintenance"
        )
        ttk.Label(
            self.maintenance_workspace, text=title, style="Title.TLabel"
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        body = ttk.Frame(self.maintenance_workspace, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, minsize=260)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        selector = ttk.Frame(body, style="Card.TFrame", padding=16)
        selector.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        selector.columnconfigure(0, weight=1)
        selector.rowconfigure(1, weight=1)
        selector_title = "Base language" if target == "user" else "Universes"
        selector_heading = ttk.Frame(selector, style="Card.TFrame")
        selector_heading.grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Label(
            selector_heading, text=selector_title, style="Heading.TLabel"
        ).pack(side="left")
        if target == "user":
            self._language_help_icon(selector_heading).pack(
                side="left", padx=(5, 0)
            )
        scope_list = tk.Listbox(
            selector,
            font=("Segoe UI", 10),
            activestyle="none",
            selectmode="browse",
            exportselection=False,
        )
        scope_list.configure(**listbox_theme_options(self.COLORS))
        scope_list.grid(row=1, column=0, sticky="nsew")
        scope_scroll = ttk.Scrollbar(
            selector, orient="vertical", command=scope_list.yview
        )
        scope_scroll.grid(row=1, column=1, sticky="ns")
        scope_scroll.grid_remove()
        scope_list.configure(
            yscrollcommand=lambda first, last: update_auto_hiding_scrollbar(
                scope_scroll, first, last
            )
        )

        selector_controls = ttk.Frame(selector, style="Card.TFrame")
        selector_controls.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for column in range(2):
            selector_controls.columnconfigure(column, weight=1)

        entries_panel = ttk.Frame(body, style="Card.TFrame", padding=16)
        entries_panel.grid(row=0, column=1, sticky="nsew")
        entries_panel.columnconfigure(0, weight=1)
        entries_panel.rowconfigure(2, weight=1)
        heading = ttk.Frame(entries_panel, style="Card.TFrame")
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="Dictionary entries", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        kind_value = tk.StringVar(value="Words / phrases")
        kind_combo = ttk.Combobox(
            heading,
            textvariable=kind_value,
            values=("Words / phrases", "Names", "Acronyms", "Substitutions"),
            state="readonly",
            width=20,
        )
        kind_combo.grid(row=0, column=1, sticky="e")
        acronym_help_icon = self._help_icon(heading, ACRONYM_HELP)
        acronym_help_icon.grid(row=0, column=2, sticky="e", padx=(6, 0))
        acronym_help_icon.grid_remove()

        column_help = tk.StringVar(value="Double-click an entry to edit it.")
        ttk.Label(
            entries_panel, textvariable=column_help, style="Muted.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))
        normal_table_frame = ttk.Frame(entries_panel, style="Card.TFrame")
        normal_table_frame.grid(row=2, column=0, sticky="nsew")
        normal_table_frame.columnconfigure(0, weight=1)
        normal_table_frame.rowconfigure(0, weight=1)
        entry_table = ttk.Treeview(
            normal_table_frame,
            columns=("entry", "replacement"),
            show="headings",
            selectmode="extended",
        )
        entry_table.heading("entry", text="Word / phrase")
        entry_table.heading("replacement", text="Replace with")
        entry_table.column("entry", minwidth=260, width=420, stretch=True)
        entry_table.column("replacement", minwidth=260, width=420, stretch=True)
        entry_table.grid(row=0, column=0, sticky="nsew")
        for tag, color in dictionary_row_colors(self.COLORS).items():
            entry_table.tag_configure(tag, background=color)
        table_scroll = ttk.Scrollbar(
            normal_table_frame, orient="vertical", command=entry_table.yview
        )
        table_scroll.grid(row=0, column=1, sticky="ns")
        table_xscroll = ttk.Scrollbar(
            normal_table_frame, orient="horizontal", command=entry_table.xview
        )
        table_xscroll.grid(row=1, column=0, sticky="ew")
        table_xscroll.grid_remove()
        column_rule = tk.Frame(
            entry_table,
            bg=self.COLORS["column_rule"],
            width=1,
        )

        def set_table_xscroll(first, last) -> None:
            table_xscroll.set(first, last)
            if horizontal_scroll_needed(first, last):
                table_xscroll.grid()
            else:
                table_xscroll.grid_remove()

        entry_table.configure(
            yscrollcommand=table_scroll.set,
            xscrollcommand=set_table_xscroll,
        )

        entry_status = tk.StringVar(value="")
        ttk.Label(
            entries_panel, textvariable=entry_status, style="Muted.TLabel"
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))
        entry_controls = ttk.Frame(entries_panel, style="Card.TFrame")
        entry_controls.grid(row=5, column=0, sticky="e", pady=(12, 0))
        current_entries = []
        displayed_kind = {"value": None}
        tree_font = ttk.Style(self.root).lookup("Treeview", "font") or "TkDefaultFont"

        def measure_cell_text(value: str) -> int:
            return int(self.root.tk.call("font", "measure", tree_font, value))

        def selected_scope() -> Optional[str]:
            selection = scope_list.curselection()
            if not selection:
                return None
            value = scope_list.get(selection[0])
            return language_key(value) if target == "user" else value

        def selected_kind() -> str:
            label = kind_value.get()
            return {
                "Words / phrases": "words",
                "Names": "names",
                "Acronyms": "acronyms",
                "Substitutions": "substitutions",
            }[label]

        def update_substitution_view() -> None:
            if selected_kind() != "substitutions":
                column_rule.place_forget()
                return
            first_width = int(entry_table.column("entry", "width"))
            replacement_width = int(entry_table.column("replacement", "width"))
            for index, value in enumerate(current_entries):
                find_value, replacement = value
                entry_table.item(
                    str(index),
                    values=(
                        elide_cell_text(
                            find_value, first_width, measure_cell_text
                        ),
                        elide_cell_text(
                            replacement, replacement_width, measure_cell_text
                        ),
                    ),
                )
            heading_height = 24
            children = entry_table.get_children()
            if children:
                bounds = entry_table.bbox(children[0], "entry")
                if bounds:
                    heading_height = bounds[1]
            total_width = max(first_width + replacement_width, 1)
            horizontal_offset = round(entry_table.xview()[0] * total_width)
            rule_x = first_width - horizontal_offset
            if 0 < rule_x < entry_table.winfo_width():
                column_rule.place(
                    x=rule_x,
                    y=heading_height,
                    width=1,
                    relheight=1.0,
                    height=-heading_height,
                )
                column_rule.lift()
            else:
                column_rule.place_forget()

        def resize_entry_columns(_event=None) -> None:
            kind = selected_kind()
            if kind != "substitutions":
                first_width, _replacement_width = initial_dictionary_column_widths(
                    kind, entry_table.winfo_width()
                )
                entry_table.column(
                    "entry",
                    width=first_width,
                    minwidth=260,
                    stretch=dictionary_column_should_stretch(kind),
                )
                column_rule.place_forget()
            elif displayed_kind["value"] != "substitutions":
                first_width, replacement_width = initial_dictionary_column_widths(
                    kind, entry_table.winfo_width()
                )
                entry_table.column(
                    "entry",
                    width=first_width,
                    minwidth=180,
                    stretch=dictionary_column_should_stretch(kind),
                )
                entry_table.column(
                    "replacement",
                    width=replacement_width,
                    minwidth=180,
                    stretch=dictionary_column_should_stretch(kind),
                )
            displayed_kind["value"] = kind
            self.root.after_idle(update_substitution_view)

        def refresh_entries(*_args, reset_columns: bool = False) -> None:
            nonlocal current_entries
            scope = selected_scope()
            kind = selected_kind()
            if reset_columns:
                displayed_kind["value"] = None
            substitutions = kind == "substitutions"
            if target == "user" and kind == "acronyms":
                acronym_help_icon.grid()
            else:
                acronym_help_icon.grid_remove()
            if target == "user" and scope:
                self.language_value.set(language_display_name(scope))
                self._refresh_context()
            universe = scope if target == "universe" else None
            for item in entry_table.get_children():
                entry_table.delete(item)
            current_entries = []
            if scope is None:
                entry_status.set(
                    "Create or select a Universe Dictionary to maintain its entries."
                )
                return
            try:
                current_entries = self._load_maintenance_entries(
                    target, kind, universe
                )
            except (OSError, ValueError, UnicodeError) as error:
                self.messagebox.showerror("Could not load dictionary", str(error))
                return
            entry_table.configure(
                displaycolumns=("entry", "replacement")
                if substitutions
                else ("entry",)
            )
            entry_table.heading(
                "entry",
                text=(
                    "Find word / phrase"
                    if substitutions
                    else (
                        "Name / exact phrase"
                        if kind == "names"
                        else ("Canonical acronym" if kind == "acronyms" else "Word / phrase")
                    )
                ),
            )
            entry_table.heading("replacement", text="Replace with")
            column_help.set(
                "Use Ctrl or Shift to select multiple entries; drag the column divider to resize. An ellipsis marks clipped text."
                if substitutions
                else "Double-click to edit; use Ctrl or Shift to select multiple entries."
            )
            for index, value in enumerate(current_entries):
                tag = (dictionary_row_tag(index),)
                values = value if substitutions else (value, "")
                entry_table.insert(
                    "", "end", iid=str(index), values=values, tags=tag
                )
            self.root.after_idle(resize_entry_columns)
            count = len(current_entries)
            entry_status.set(f"{count} entr{'y' if count == 1 else 'ies'}")

        def reload_scopes(preferred: Optional[str] = None) -> None:
            scope_list.delete(0, "end")
            values = (
                list(LANGUAGE_DISPLAY_NAMES.values())
                if target == "user"
                else self.tool.list_universes()
            )
            for value in values:
                scope_list.insert("end", value)
            if not values:
                refresh_entries(reset_columns=True)
                return
            current = preferred
            if target == "user" and current:
                current = language_display_name(current)
            if current not in values:
                current = values[0]
            index = values.index(current)
            scope_list.selection_set(index)
            scope_list.activate(index)
            scope_list.see(index)
            refresh_entries(reset_columns=True)

        def selected_entries() -> list:
            selection = entry_table.selection()
            if not selection:
                self.messagebox.showinfo("Select an entry", "Select an entry first.")
                return []
            return table_selection_entries(selection, current_entries)

        def selected_entry():
            values = selected_entries()
            if not values:
                return None
            return self._single_selected_entry(values)

        def add_entry() -> None:
            scope = selected_scope()
            if scope is None:
                self.messagebox.showinfo(
                    "Select a universe", "Create or select a Universe Dictionary first."
                )
                return
            kind = selected_kind()
            values = self._prompt_maintenance_values(
                kind,
                title="Add substitution" if kind == "substitutions" else "Add entry",
            )
            if values is None:
                return
            entry, output = values
            try:
                changed = self._add_maintenance_entry(
                    target,
                    kind,
                    scope if target == "universe" else None,
                    entry,
                    output,
                )
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                self.messagebox.showerror("Could not add entry", str(error))
                return
            refresh_entries()
            self._refresh_context()
            self.status_value.set(
                "Dictionary entry added"
                if changed
                else "Entry already exists or was empty"
            )

        def edit_entry() -> None:
            value = selected_entry()
            if value is None:
                return
            scope = selected_scope()
            kind = selected_kind()
            old_entry, old_output = value if kind == "substitutions" else (value, "")
            values = self._prompt_maintenance_values(
                kind,
                title="Edit substitution" if kind == "substitutions" else "Edit entry",
                entry=old_entry,
                output=old_output,
            )
            if values is None:
                return
            new_entry, new_output = values
            try:
                changed = self._edit_maintenance_entry(
                    target,
                    kind,
                    scope if target == "universe" else None,
                    old_entry,
                    new_entry,
                    old_output,
                    new_output,
                )
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                self.messagebox.showerror("Could not edit entry", str(error))
                return
            refresh_entries()
            self._refresh_context()
            self.status_value.set(
                "Dictionary entry updated" if changed else "No dictionary change made"
            )

        def remove_entry() -> None:
            values = selected_entries()
            if not values:
                return
            scope = selected_scope()
            kind = selected_kind()
            if len(values) == 1:
                entry = values[0][0] if kind == "substitutions" else values[0]
                prompt = f'Remove “{entry}” from this dictionary?'
            else:
                prompt = f"Remove all {len(values)} selected entries from this dictionary?"
            if not self.messagebox.askyesno(
                "Remove entry",
                prompt,
                parent=self.root,
            ):
                return
            try:
                for value in values:
                    entry, output = (
                        value if kind == "substitutions" else (value, "")
                    )
                    self._remove_maintenance_entry(
                        target,
                        kind,
                        scope if target == "universe" else None,
                        entry,
                        output,
                    )
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                refresh_entries()
                self._refresh_context()
                self.messagebox.showerror("Could not remove entry", str(error))
                return
            refresh_entries()
            self._refresh_context()
            count = len(values)
            self.status_value.set(
                f"{count} dictionary entr{'y' if count == 1 else 'ies'} removed"
            )

        def move_entry() -> None:
            values = selected_entries()
            if not values:
                return
            scope = selected_scope()
            if scope is None:
                return
            kind = selected_kind()
            events = []
            for value in values:
                entry, output = value if kind == "substitutions" else (value, "")
                events.append(self._maintenance_event(
                    target,
                    kind,
                    scope if target == "universe" else None,
                    entry=entry,
                    output=output,
                    language=scope if target == "user" else None,
                ))
            destination = self._prompt_recent_destination(events)
            if destination is None:
                return
            destination_target, destination_universe, destination_language = (
                destination
            )
            moved_count = 0
            try:
                for value in values:
                    entry, output = (
                        value if kind == "substitutions" else (value, "")
                    )
                    moved = self._move_maintenance_entry(
                        target,
                        kind,
                        scope if target == "universe" else None,
                        entry,
                        output,
                        source_language=scope if target == "user" else None,
                        destination_target=destination_target,
                        destination_universe=destination_universe,
                        destination_language=destination_language,
                    )
                    moved_count += int(moved)
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                refresh_entries()
                self._refresh_context()
                self.messagebox.showerror("Could not move entry", str(error))
                return
            refresh_entries()
            self._refresh_context()
            self.status_value.set(
                f"{moved_count} dictionary entr{'y' if moved_count == 1 else 'ies'} moved"
            )

        ttk.Button(entry_controls, text="Add", command=add_entry).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(entry_controls, text="Edit", command=edit_entry).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(entry_controls, text="Move", command=move_entry).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(entry_controls, text="Remove", command=remove_entry).pack(
            side="left"
        )

        def current_universe() -> Optional[str]:
            return selected_scope() if target == "universe" else None

        def block_active_review(universe: str) -> bool:
            session = self.review_session
            in_use = bool(
                session is not None
                and session.context.universe
                and session.context.universe.casefold() == universe.casefold()
            )
            if in_use:
                self.messagebox.showerror(
                    "Universe is in use",
                    "Stop the current GUI review before renaming or deleting its "
                    "Universe Dictionary.",
                )
            return in_use

        def create_universe() -> None:
            name = self._create_universe_from_scan_selector()
            if name is None:
                return
            reload_scopes(name)

        def copy_universe() -> None:
            source = current_universe()
            if source is None:
                self.messagebox.showinfo("Select a universe", "Select a universe first.")
                return
            response = self._prompt_text_fields(
                "Copy Universe Dictionary",
                (("Name for the copy", f"{source} Copy"),),
            )
            if response is None:
                return
            new_name = response[0]
            try:
                self.tool.duplicate_universe_named(source, new_name)
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                self.messagebox.showerror("Could not copy universe", str(error))
                return
            self._refresh_universes()
            reload_scopes(new_name)
            self.status_value.set(f'Copied “{source}” to “{new_name}”')

        def rename_universe() -> None:
            source = current_universe()
            if source is None:
                self.messagebox.showinfo("Select a universe", "Select a universe first.")
                return
            if block_active_review(source):
                return
            response = self._prompt_text_fields(
                "Rename Universe Dictionary", (("New universe name", source),)
            )
            if response is None:
                return
            new_name = response[0]
            try:
                self.tool.rename_universe_named(source, new_name)
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                self.messagebox.showerror("Could not rename universe", str(error))
                return
            if self.universe_value.get() == source:
                self.universe_value.set(new_name)
            self._refresh_universes()
            reload_scopes(new_name)
            self.status_value.set(f'Renamed “{source}” to “{new_name}”')

        def delete_universe() -> None:
            universe = current_universe()
            if universe is None:
                self.messagebox.showinfo("Select a universe", "Select a universe first.")
                return
            if block_active_review(universe):
                return
            if not self.messagebox.askyesno(
                "Delete Universe Dictionary?",
                f'Delete “{universe}” and all of its dictionary entries?\n\n'
                "This cannot be undone.",
                icon="warning",
                parent=self.root,
            ):
                return
            try:
                self.tool.delete_universe_named(universe)
            except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                self.messagebox.showerror("Could not delete universe", str(error))
                return
            if self.universe_value.get() == universe:
                self.universe_value.set("No universe")
            self._refresh_universes()
            reload_scopes()
            self.status_value.set(f'Deleted Universe Dictionary “{universe}”')

        if target == "universe":
            ttk.Button(
                selector_controls, text="Add", command=create_universe
            ).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
            ttk.Button(
                selector_controls, text="Copy", command=copy_universe
            ).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))
            ttk.Button(
                selector_controls, text="Rename", command=rename_universe
            ).grid(row=1, column=0, sticky="ew", padx=(0, 4))
            ttk.Button(
                selector_controls, text="Delete", command=delete_universe
            ).grid(row=1, column=1, sticky="ew", padx=(4, 0))

        scope_list.bind(
            "<<ListboxSelect>>",
            lambda event: refresh_entries(event, reset_columns=True),
        )
        kind_combo.bind(
            "<<ComboboxSelected>>",
            lambda event: refresh_entries(event, reset_columns=True),
        )
        entry_table.bind("<Double-1>", lambda _event: edit_entry())
        entry_table.bind("<Configure>", resize_entry_columns)
        entry_table.bind(
            "<B1-Motion>", lambda _event: self.root.after_idle(update_substitution_view)
        )
        entry_table.bind(
            "<ButtonRelease-1>",
            lambda _event: self.root.after_idle(update_substitution_view),
        )

        def scroll_entry_table(*args) -> None:
            entry_table.xview(*args)
            self.root.after_idle(update_substitution_view)

        table_xscroll.configure(command=scroll_entry_table)
        preferred = (
            language_key(self.language_value.get())
            if target == "user"
            else self.universe_value.get()
        )
        if preferred == "No universe":
            preferred = None
        reload_scopes(preferred)
        self.status_value.set(f"{title} • Changes save immediately")

    def _close_window(self) -> None:
        if getattr(self, "update_installing", False):
            self.messagebox.showinfo(
                "Update preparation in progress",
                "Please wait while the verified update is prepared. The application "
                "will close automatically only after the external updater is ready.",
                parent=self.root,
            )
            return
        if not self._confirm_theme_navigation("close"):
            return
        session = getattr(self, "review_session", None)
        if getattr(self, "editing_cue", False):
            if not self._confirm_discard_unsaved_review("close the program"):
                return
        if session is not None and not self._checkpoint_review(paused=self.scan_paused):
            if not self._confirm_discard_unsaved_review("close the program"):
                return
        self.root.destroy()

    def _show_planned_feature(self, feature: str) -> None:
        self.messagebox.showinfo(
            feature,
            f"{feature} will be connected to the shared engine in a later GUI increment.\n\n"
            "The command-line interface remains fully available with --cli.",
        )

    def run(self) -> None:
        self.root.mainloop()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle_gui.py",
        description="Graphical and command-line launcher for Subtitle Universe Spellcheck.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="run the existing command-line interface instead of the GUI",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the application version and exit",
    )
    parser.add_argument(
        "--update-cleanup",
        type=Path,
        help=argparse.SUPPRESS,
    )
    return parser


def complete_update_cleanup(
    requested_path: Optional[Path] = None,
    *,
    root: Optional[Path] = None,
    remover: Callable[..., object] = shutil.rmtree,
    sleeper: Callable[[float], None] = time.sleep,
    attempts: int = 30,
) -> bool:
    """Remove an exited external updater, retaining a safe retry marker on failure."""
    installation = (root or application_root()).resolve()
    marker = installation / UPDATE_CLEANUP_MARKER
    cleanup_path = Path(requested_path).resolve() if requested_path else None
    if cleanup_path is None and marker.is_file():
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
            cleanup_path = Path(saved["path"]).resolve()
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            try:
                marker.unlink()
            except OSError:
                pass
            return False
    if cleanup_path is None:
        return True

    valid = (
        cleanup_path.parent == installation.parent
        and cleanup_path.name.startswith(".subtitle-universe-update-helper-")
        and cleanup_path != installation
    )
    if not valid:
        return False
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary_marker = marker.with_suffix(marker.suffix + ".tmp")
    try:
        temporary_marker.write_text(
            json.dumps({"schema": 1, "path": str(cleanup_path)}), encoding="utf-8"
        )
        os.replace(temporary_marker, marker)
    except OSError:
        return False

    for attempt in range(max(1, attempts)):
        try:
            if cleanup_path.exists():
                remover(cleanup_path)
            marker.unlink(missing_ok=True)
            return True
        except OSError:
            if attempt + 1 < max(1, attempts):
                sleeper(0.1)
    return False


def detach_frozen_gui_console(
    *,
    platform_name: Optional[str] = None,
    frozen: Optional[bool] = None,
    free_console: Optional[Callable[[], object]] = None,
) -> bool:
    """Hide the console owned by a frozen Windows GUI launch.

    The Windows package deliberately uses the console subsystem so the same
    executable can provide a real ``--cli`` mode.  A normal GUI launch releases
    that console immediately; source launches and non-Windows platforms are
    left untouched.
    """
    current_platform = platform_name if platform_name is not None else sys.platform
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if current_platform != "win32" or not is_frozen:
        return False
    try:
        if free_console is None:
            import ctypes

            free_console = ctypes.windll.kernel32.FreeConsole
        return bool(free_console())
    except (AttributeError, OSError):
        return False


def launch_application(
    argv: Optional[Sequence[str]] = None,
    *,
    gui_factory: Optional[Callable[[], SubtitleSpellcheckGUI]] = None,
    cli_runner: Optional[Callable[[], None]] = None,
    console_detacher: Optional[Callable[[], object]] = None,
    tool_factory: Callable[[], SubtitleCleanupTool] = SubtitleCleanupTool,
    tkinter_guard: Callable[..., bool] = ensure_tkinter_for_gui,
    platform_name: Optional[str] = None,
    frozen: Optional[bool] = None,
    has_console: Optional[bool] = None,
) -> int:
    arguments = build_argument_parser().parse_args(list(argv) if argv is not None else None)
    complete_update_cleanup(arguments.update_cleanup)
    if arguments.version:
        print(f"Subtitle Universe Spellcheck {SCRIPT_VERSION}")
        return 0
    if arguments.cli:
        (cli_runner or run_cli)()
        return 0
    current_platform = platform_name if platform_name is not None else sys.platform
    if tkinter_preflight_required(platform_name=current_platform, frozen=frozen):
        tool = tool_factory()
        if not tkinter_guard(
            tool,
            platform_name=current_platform,
            frozen=frozen,
            has_console=has_console,
        ):
            (cli_runner or run_cli)()
            return 0
    (console_detacher or detach_frozen_gui_console)()
    (gui_factory or SubtitleSpellcheckGUI)().run()
    return 0


def show_startup_error(message: str) -> None:
    """Display a GUI-visible startup error for the console-free launcher."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    apply_application_window_icon(root, image_factory=tk.PhotoImage)
    root.withdraw()
    try:
        messagebox.showerror("Subtitle Universe Spellcheck", message, parent=root)
    finally:
        root.destroy()


def launch_gui_only(
    *,
    gui_factory: Optional[Callable[[], SubtitleSpellcheckGUI]] = None,
    error_reporter: Optional[Callable[[str], None]] = None,
) -> int:
    """Launch only the GUI and turn hidden-console failures into a dialog."""
    try:
        return launch_application([], gui_factory=gui_factory)
    except Exception as error:  # The .pyw launcher has no console for a traceback.
        reporter = error_reporter or show_startup_error
        reporter(f"The graphical interface could not start.\n\n{error}")
        return 1


def launch_detached_gui_only(
    script_path: Path,
    *,
    executable: Optional[str] = None,
    environment: Optional[dict[str, str]] = None,
    process_launcher: Callable[..., object] = subprocess.Popen,
    error_reporter: Optional[Callable[[str], None]] = None,
) -> int:
    """Relaunch the source GUI independently of a POSIX terminal."""
    child_environment = dict(environment if environment is not None else os.environ)
    child_environment[DETACHED_GUI_ENVIRONMENT_VARIABLE] = "1"
    command = [executable or sys.executable, os.fspath(script_path)]
    try:
        process_launcher(
            command,
            env=child_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as error:
        reporter = error_reporter or show_startup_error
        reporter(f"The graphical interface could not start.\n\n{error}")
        return 1
    return 0


def launch_cli_in_new_console(
    script_path: Path,
    *,
    executable: Optional[str] = None,
    process_launcher: Callable[..., object] = subprocess.Popen,
    error_reporter: Optional[Callable[[str], None]] = None,
) -> int:
    """Start the source CLI visibly when a Windows `.pyw` has no console."""
    python_executable = Path(executable or sys.executable)
    if python_executable.name.lower() == "pythonw.exe":
        python_executable = python_executable.with_name("python.exe")
    command = [
        os.fspath(python_executable),
        os.fspath(script_path.parent / "app" / "subtitle_gui.py"),
        "--cli",
    ]
    try:
        process_launcher(
            command,
            creationflags=WINDOWS_NEW_CONSOLE,
            close_fds=True,
        )
    except Exception as error:
        reporter = error_reporter or show_startup_error
        reporter(f"The command-line interface could not start.\n\n{error}")
        return 1
    return 0


def launch_portable_wrapper(
    script_path: Path,
    *,
    tool_factory: Callable[[], SubtitleCleanupTool] = SubtitleCleanupTool,
    platform_name: Optional[str] = None,
    frozen: Optional[bool] = None,
) -> int:
    """Route the root `.pyw` through its recoverable portable preference."""
    environment = os.environ
    if environment.get(DETACHED_GUI_ENVIRONMENT_VARIABLE) == "1":
        return launch_gui_only()

    has_console = console_is_interactive()
    current_platform = platform_name if platform_name is not None else sys.platform
    needs_tkinter_check = tkinter_preflight_required(
        platform_name=current_platform,
        frozen=frozen,
    )
    saved_mode = load_portable_launch_mode(script_path.parent)
    if needs_tkinter_check and saved_mode != "cli":
        tool = tool_factory()
        if not ensure_tkinter_for_gui(
            tool,
            platform_name=current_platform,
            frozen=frozen,
            has_console=has_console,
        ):
            return launch_application(["--cli"])
    try:
        mode = choose_portable_launch_mode(
            script_path.parent,
            has_console=has_console,
        )
    except (EOFError, OSError, RuntimeError, UnicodeError, ValueError) as error:
        message = f"The launch preference could not be saved or read.\n\n{error}"
        if has_console:
            print(message, file=sys.stderr)
        else:
            show_startup_error(message)
        return 1
    if mode is None:
        return 0
    if mode == "gui":
        if needs_tkinter_check and saved_mode == "cli":
            tool = tool_factory()
            if not ensure_tkinter_for_gui(
                tool,
                platform_name=current_platform,
                frozen=frozen,
                has_console=has_console,
            ):
                return launch_application(["--cli"])
        if should_detach_gui_launcher(environment=environment):
            return launch_detached_gui_only(script_path, environment=environment)
        return launch_gui_only()
    if has_console:
        return launch_application(["--cli"])
    if sys.platform == "win32":
        return launch_cli_in_new_console(script_path)
    show_startup_error(
        "The CLI needs a terminal. Run this command from one:\n\n"
        "python3 app/subtitle_gui.py --cli"
    )
    return 1


def main() -> int:
    try:
        return launch_application()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
