#!/usr/bin/env python3
"""
Subtitle Cleanup and Interactive Spellcheck Tool
Initial implementation based on the Roadmap / Specification.

This is intentionally written as a single-file, standard-library-only script so it can
be dropped into a subtitle folder or a scripts folder and tested without extra setup.
"""
from __future__ import annotations

import configparser
import difflib
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
import time
import platform
import urllib.parse
import urllib.error
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

SCRIPT_VERSION = "1.1.0"
SCHEMA_VERSION = 1
PROJECT_URL = "https://github.com/gearheart89/subtitle-universe-spellcheck-public"
UPDATE_API_URL = "https://api.github.com/repos/gearheart89/subtitle-universe-spellcheck-public/releases/latest"
UPDATE_TIMEOUT_SECONDS = 4.0
UPDATE_METADATA_LIMIT = 2 * 1024 * 1024
UPDATE_CHECKSUM_LIMIT = 64 * 1024
UPDATE_ARCHIVE_LIMIT = 512 * 1024 * 1024
UPDATE_ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
SCOWL_URL = "https://github.com/en-wl/wordlist/tree/rel-2026.02.25"
SCOWL_CREDIT = (
    "American and British base dictionaries are generated from SCOWL 2026.02.25.\n"
    "Copyright 2000-2026 by Kevin Atkinson\n\n"
    "Permission to use, copy, modify, distribute, and sell any part of SCOWLv2, "
    "or word lists created from it, is hereby granted without fee, provided that "
    "the above copyright notice appears in all copies and that both the above "
    "copyright notice and this notice appear in supporting documentation. Kevin "
    "Atkinson makes no representations about the suitability of this database for "
    "any purpose. It is provided ‘as is’ without express or implied warranty."
)
SESSION_LOG_HELP = (
    "This clears dictionaries/session_log.jsonl and removes its history from "
    "the Recent additions screens. It does not remove dictionary entries.\n"
    "It also does not clear or abandon an interrupted spellcheck session, "
    "including CLI and GUI recovery."
)

BASE_LANGUAGE_CHOICES = {"1": "american", "2": "british"}
LOWERCASE_WORDS = {
    "and", "or", "but", "nor", "for", "so", "yet",
    "of", "with", "at", "by", "from", "in", "into",
    "to", "on", "onto", "off", "out", "over", "under",
    "the", "a", "an",
}
COMMON_ACRONYMS = {
    "AI", "ASAP", "CIA", "DC", "DNA", "DVD", "FBI", "GPS", "HD", "ID", "NASA",
    "OK", "PC", "TV", "UFO", "UK", "UN", "US", "USA", "USB", "VIP", "WiFi",
}
UNITED_STATES_CONTEXT_PATTERNS = [
    "US military", "US government", "US Air Force", "US Army", "US Navy", "US Marines",
    "US Marine Corps", "US forces", "US troops", "US base", "US command", "US intelligence",
    "US embassy", "US president", "US citizens", "the US", "to the US", "from the US",
    "in the US", "inside the US", "outside the US", "across the US", "throughout the US",
]
US_PRONOUN_PATTERNS = [
    "the two of us", "all of us", "both of us", "those of us", "one of us",
    "each of us", "some of us", "many of us", "most of us", "none of us",
    "any of us", "either of us", "neither of us", "just us", "with us",
    "told us", "asked us", "let us", "gave us", "send us", "show us",
]
ABBREVIATION_WORDS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "no",
    "capt", "cmdr", "col", "gen", "lt", "sgt", "adm",
}
COMMON_BASE_WORDS = """
a about above across act action actually add after again against age ago air all almost alone along already also always am among an and another answer any anyone anything are area around as ask at away back bad be because become been before began begin behind being believe best better between big bit black blue body book both bring brother brought but by call came can cannot car care carry case cause change child children city close cold come comes coming common company complete could country course cut day days dead deal did different do does dog done door down each early earth easy end enough even ever every everything example eye face fact fall family far father feel few field find fine fire first five follow food for form found four friend from front full gave get girl give given go goes going good got great group grow had half hand happen hard has have he head hear heard heart held help her here high him himself his hold home hope house how however I idea if important in inside interest into is it its itself job just keep kind knew know known large last late later law lay learn least leave left let life light like line little live long look looked lost lot love made make man many may me mean men might mind miss moment money more morning most mother move much must my name near need never new next night no not nothing now number of off often old on once one only open or order other our out over own part pass people person place point possible power present probably problem put question quick quite read real really reason right room run said same saw say says school see seem seen set several she should show side since small so some something soon sound still stop story study such sure take talk tell than that the their them then there these they thing think this those thought three through time to together told took toward try turn two under understand until up upon us use used very voice wait walk want was water way we well went were what when where whether which while white who whole why will with within without woman word work world would year years yes yet you your
"""

WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+|['’])?")
SRT_TIMESTAMP_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}")
HTML_TAG_RE = re.compile(r"<[^>]+>")
BRACKETED_RE = re.compile(r"\[([^\]]+)\]")
DOTTED_ACRONYM_RE = re.compile(r"(?<![A-Za-z])(?:[A-Za-z]\.){2,}[A-Za-z]?\.?(?![A-Za-z])")
DOTTED_FORM_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]{1,3}\.(?:[A-Za-z]\.)*[A-Za-z]\.?(?![A-Za-z])")


def preferred_acronym_casing(token: str, acronym_set: set) -> Optional[str]:
    """Return canonical casing for an acronym or its simple English inflection."""
    canonical = {value.casefold(): value for value in acronym_set}
    exact = canonical.get(token.casefold())
    if exact is not None:
        return exact

    possessive = re.fullmatch(r"(.+)(['’])[sS]", token)
    if possessive:
        base = canonical.get(possessive.group(1).casefold())
        if base is not None:
            return base + possessive.group(2) + "s"

    if len(token) > 1 and token[-1].casefold() == "s":
        base = canonical.get(token[:-1].casefold())
        if base is not None:
            return base + "s"
    return None

DEFAULT_OPTIONS: Dict[str, object] = {
    "check_for_updates_at_startup": False,
    "capitalization_mode": "ask_always",
    "scan_folders_recursively": True,
    "recognize_dropped_g_apostrophe_forms": True,
    "remove_periods_from_abbreviations": True,
    "convert_double_hyphen_and_three_dots_to_ellipsis": False,
    "title_case_bracketed_sound_effects": True,
    "fix_mostly_uppercase_lines": True,
    "capitalize_lowercase_pronoun_i": True,
    "adjust_subtitle_line_count": True,
    "preferred_max_visible_dialogue_lines": 2,
    "count_sound_effect_lines_toward_max": False,
    "preferred_max_chars_per_line": 40,
    "acceptable_max_chars_per_line": 55,
    "prefer_sentence_ending_line_breaks_when_reasonably_balanced": True,
    "preserve_speaker_clarity": True,
    "detect_dropped_speaker_breaks": True,
    "create_backup_subtitles_zip_before_editing": False,
    "repair_corrupted_music_symbols": True,
    "repair_common_mojibake_punctuation": True,
    "remove_safe_invisible_characters": True,
    "remove_duplicate_spaces": True,
    "fix_spaces_around_punctuation": True,
    "repair_unambiguous_italic_tag_errors": True,
    "report_suspicious_text": True,
    "maximum_universe_display_name_length": 24,
}

OPTION_LABELS = {
    "check_for_updates_at_startup": "Check for updates at startup",
    "capitalization_mode": "Capitalization preference",
    "scan_folders_recursively": "Scan folders recursively",
    "recognize_dropped_g_apostrophe_forms": "Recognize informal -in' forms when the -ing word is known",
    "remove_periods_from_abbreviations": "Remove periods from abbreviations",
    "convert_double_hyphen_and_three_dots_to_ellipsis": "Convert -- and ... to the ellipsis character",
    "title_case_bracketed_sound_effects": "Title-case bracketed sound effects",
    "fix_mostly_uppercase_lines": "Fix capitalization when a line is mostly uppercase",
    "capitalize_lowercase_pronoun_i": "Capitalize lowercase pronoun i and its contractions",
    "adjust_subtitle_line_count": "Adjust subtitle line count/length",
    "preferred_max_visible_dialogue_lines": "Preferred max visible dialogue lines per subtitle",
    "count_sound_effect_lines_toward_max": "Count sound-effect lines toward max visible line count",
    "preferred_max_chars_per_line": "Preferred max characters per line",
    "acceptable_max_chars_per_line": "Acceptable max characters per line",
    "prefer_sentence_ending_line_breaks_when_reasonably_balanced": "Prefer sentence-ending line breaks when reasonably balanced",
    "preserve_speaker_clarity": 'Preserve speaker clarity for "Name:" and "- " lines',
    "detect_dropped_speaker_breaks": "Detect dropped speaker breaks after punctuation",
    "create_backup_subtitles_zip_before_editing": "Create backup_subtitles.zip before editing",
    "repair_corrupted_music_symbols": "Repair corrupted music symbols",
    "repair_common_mojibake_punctuation": "Repair common mojibake punctuation",
    "remove_safe_invisible_characters": "Remove safe invisible characters",
    "remove_duplicate_spaces": "Remove duplicate spaces",
    "fix_spaces_around_punctuation": "Fix spaces around punctuation",
    "repair_unambiguous_italic_tag_errors": "Repair unambiguous italic-tag errors",
    "report_suspicious_text": "Report suspicious quotes, brackets, tags, and punctuation",
    "maximum_universe_display_name_length": "Maximum universe display name length",
}

OPTION_DESCRIPTIONS = {
    "check_for_updates_at_startup": "When enabled, launch performs a short, nonfatal check of the public GitHub release page. A newer version is never downloaded without permission, and Stage 1 never installs or replaces application files.",
    "capitalization_mode": "Ask always prompts at the start of each new scan but not when resuming one already in progress. Source capitalization preserves the capitalization in the subtitle. Subtitle-aware capitalization applies the tool's conservative pronoun, sound-effect, name, acronym, and mostly-uppercase repairs. All caps changes all visible subtitle text to uppercase while preserving markup tags.",
    "scan_folders_recursively": "When enabled, the selected folder and every child folder are scanned for .srt files. When disabled, only .srt files directly inside the selected folder are scanned.",
    "recognize_dropped_g_apostrophe_forms": "When enabled, informal dialogue forms ending in -in' or -in’ are accepted when adding g produces a known -ing word. For example, goin' is recognized only when going is in the active dictionaries.",
    "remove_periods_from_abbreviations": "Normalizes dotted acronyms such as M.A.L.P. -> MALP and S.G.C. -> SGC. Dotted U.S. and U.S.A. are treated as protected acronym forms before conservative us/US handling.",
    "convert_double_hyphen_and_three_dots_to_ellipsis": "When enabled, converts -- and runs of three or more periods to the single ellipsis character … before substitutions, capitalization repair, speaker-break detection, or line reflow.",
    "title_case_bracketed_sound_effects": "Changes bracketed sound effects such as [FOOTSTEPS APPROACHING] to [Footsteps Approaching]. Small connector words stay lowercase unless first or last.",
    "fix_mostly_uppercase_lines": "Repairs lines where more than 80% of letters are uppercase. Uses substitutions, names, known acronyms, dictionaries, connector words, and conservative fallback casing.",
    "capitalize_lowercase_pronoun_i": "Capitalizes standalone lowercase i and the common contractions i'm, i'd, i'll, and i've in ordinary dialogue. Subtitle tags, i.e., and web addresses are protected.",
    "adjust_subtitle_line_count": "Reflows normal dialogue toward the preferred line length and visible dialogue line count while preserving hard-break speaker/sound-effect lines.",
    "preferred_max_visible_dialogue_lines": "Target number of visible dialogue lines per subtitle cue. Hard-break speaker lines may exceed this target to preserve clarity.",
    "count_sound_effect_lines_toward_max": "When false, [Sound Effect] lines are excluded from the visible dialogue line count target.",
    "preferred_max_chars_per_line": "Target line length for normal subtitle reflow.",
    "acceptable_max_chars_per_line": "Maximum line length allowed when doing so avoids creating an extra visible line.",
    "prefer_sentence_ending_line_breaks_when_reasonably_balanced": "When practical, tries to place a line break after punctuation rather than splitting mid-phrase.",
    "preserve_speaker_clarity": "Lines beginning with Name: or - stay at the start of a new line, even when this exceeds preferred line count.",
    "detect_dropped_speaker_breaks": "Detects likely missing speaker breaks after punctuation, such as We go.Now?! or Ready?-Not yet.",
    "create_backup_subtitles_zip_before_editing": "Before options 1, 2, or 3 edit files, creates separate backup_subtitles.zip archives for the selected root and each immediate child folder that contains subtitle files. The root archive includes only .srt files directly in the root. Each child archive preserves paths below that child. Existing archives are assumed valid.",
    "repair_corrupted_music_symbols": "Repairs known encoding-damaged music symbols without guessing which dialogue is sung or adding new notes. Examples: â™ª -> ♪ and â™« -> ♫.",
    "repair_common_mojibake_punctuation": "Repairs known punctuation sequences produced when UTF-8 text was decoded with the wrong character encoding. Examples: â€™ -> ’, â€œ -> “, â€“ -> –, and â€” -> —.",
    "remove_safe_invisible_characters": "Removes zero-width spaces, stray byte-order marks, soft hyphens, and word joiners from subtitle text, and changes nonbreaking spaces to ordinary spaces. Potentially meaningful right-to-left controls are not removed.",
    "remove_duplicate_spaces": "Collapses repeated horizontal spaces in visible subtitle text while leaving spacing inside HTML-style tags unchanged. Example: Hello  world. -> Hello world.",
    "fix_spaces_around_punctuation": "Removes spaces before punctuation and inserts a missing space after commas, semicolons, and colons when followed by a letter. Examples: Hello ,world. -> Hello, world. and What ? -> What? Decimals, URLs, timestamps, ellipses, and tag contents are protected.",
    "repair_unambiguous_italic_tag_errors": "Repairs only simple, unambiguous italic-tag mistakes and removes empty or duplicate italic tags. Example: <i>Hello<i> -> <i>Hello</i>. More complicated malformed markup is reported rather than guessed.",
    "report_suspicious_text": "Reports unmatched quotes or brackets, unclosed italic tags, and runs of four or more question or exclamation marks. This validation option does not edit subtitle text.",
    "maximum_universe_display_name_length": "Controls visual truncation in universe menus/tables only. Internal universe folder names may be longer.",
}

OPTION_GROUPS = [
    (
        "File Discovery and Safety",
        ["scan_folders_recursively", "create_backup_subtitles_zip_before_editing"],
    ),
    (
        "Spelling and Text Cleanup",
        [
            "capitalization_mode",
            "recognize_dropped_g_apostrophe_forms",
            "remove_periods_from_abbreviations",
            "convert_double_hyphen_and_three_dots_to_ellipsis",
            "title_case_bracketed_sound_effects",
            "fix_mostly_uppercase_lines",
            "capitalize_lowercase_pronoun_i",
        ],
    ),
    (
        "Subtitle Layout and Dialogue",
        [
            "adjust_subtitle_line_count",
            "preferred_max_visible_dialogue_lines",
            "count_sound_effect_lines_toward_max",
            "preferred_max_chars_per_line",
            "acceptable_max_chars_per_line",
            "prefer_sentence_ending_line_breaks_when_reasonably_balanced",
            "preserve_speaker_clarity",
            "detect_dropped_speaker_breaks",
        ],
    ),
    (
        "Common Error Cleanup",
        [
            "repair_corrupted_music_symbols",
            "repair_common_mojibake_punctuation",
            "remove_safe_invisible_characters",
            "remove_duplicate_spaces",
            "fix_spaces_around_punctuation",
            "repair_unambiguous_italic_tag_errors",
            "report_suspicious_text",
        ],
    ),
    (
        "Menus and Display",
        ["check_for_updates_at_startup", "maximum_universe_display_name_length"],
    ),
]

CAPITALIZATION_MODES = {
    "ask_always": "Ask always",
    "source": "Source capitalization",
    "subtitle": "Subtitle-aware capitalization",
    "all_caps": "All caps",
}
CAPITALIZATION_SCAN_MODES = {
    key: label for key, label in CAPITALIZATION_MODES.items() if key != "ask_always"
}
CAPITALIZATION_DEPENDENT_OPTIONS = {
    "title_case_bracketed_sound_effects",
    "fix_mostly_uppercase_lines",
    "capitalize_lowercase_pronoun_i",
}

OPTION_INLINE_EXAMPLES = {
    "repair_corrupted_music_symbols": "[â™ª → ♪] [â™« → ♫]",
    "repair_common_mojibake_punctuation": "[â€™ → ’] [â€œ → “]",
    "remove_safe_invisible_characters": "[zero-width space → removed]",
    "remove_duplicate_spaces": "[Hello  world. → Hello world.]",
    "fix_spaces_around_punctuation": "[Hello ,world. → Hello, world.]",
    "repair_unambiguous_italic_tag_errors": "[<i>Hello<i> → <i>Hello</i>]",
    "report_suspicious_text": "[reports only—does not edit]",
    "capitalize_lowercase_pronoun_i": "[i told you → I told you] [i'm → I'm]",
}

MUSIC_SYMBOL_REPLACEMENTS = {
    "\u00e2\u2122\u00aa": "♪",
    "\u00e2\u2122\u00ab": "♫",
}

MOJIBAKE_PUNCTUATION_REPLACEMENTS = {
    "\u00e2\u20ac\u2122": "’",
    "\u00e2\u20ac\u02dc": "‘",
    "\u00e2\u20ac\u0153": "“",
    "\u00e2\u20ac\u009d": "”",
    "\u00e2\u20ac\ufffd": "”",
    "\u00e2\u20ac\u201c": "–",
    "\u00e2\u20ac\u201d": "—",
    "\u00e2\u20ac\u00a6": "…",
}

SAFE_INVISIBLE_TRANSLATION = str.maketrans({
    "\u200b": None,
    "\ufeff": None,
    "\u00ad": None,
    "\u2060": None,
    "\u00a0": " ",
})

BOOL_TRUE = {"yes", "y", "true", "t", "1", "on"}
BOOL_FALSE = {"no", "n", "false", "f", "0", "off"}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def application_root() -> Path:
    """Return the portable folder that owns runtime data and scan defaults."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    source_directory = Path(__file__).resolve().parent
    if source_directory.name.casefold() == "app":
        return source_directory.parent
    return source_directory


def application_entry_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def pause(message: str = "Press Enter to continue.") -> None:
    input(f"\n{message}")


class ConsoleProgressReporter:
    """Render one throttled, in-place progress line on an interactive console."""

    def __init__(self, stream=None, interval_seconds: float = 1.0) -> None:
        self.stream = sys.stdout if stream is None else stream
        self.interval_seconds = interval_seconds
        self.last_update: Optional[float] = None
        self.display_width = 0

    def update(
        self,
        phase: str,
        file_number: int,
        total_files: int,
        subtitle_number: int,
        total_subtitles: int,
        force: bool = False,
    ) -> None:
        if not hasattr(self.stream, "isatty") or not self.stream.isatty():
            return
        current_time = time.monotonic()
        if (
            not force
            and self.last_update is not None
            and current_time - self.last_update < self.interval_seconds
        ):
            return
        message = (
            f"{phase}: File {file_number} of {total_files} | "
            f"Subtitle {subtitle_number} of {total_subtitles}"
        )
        self.display_width = max(self.display_width, len(message))
        self.stream.write("\r" + message.ljust(self.display_width))
        self.stream.flush()
        self.last_update = current_time

    def clear(self) -> None:
        if not self.display_width:
            return
        self.stream.write("\r" + (" " * self.display_width) + "\r")
        self.stream.flush()
        self.display_width = 0


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_bool(value: str) -> Optional[bool]:
    lower = value.strip().lower()
    if lower in BOOL_TRUE:
        return True
    if lower in BOOL_FALSE:
        return False
    return None


def truncate_display(value: str, max_len: int) -> str:
    if max_len <= 0 or len(value) <= max_len:
        return value
    if max_len <= 3:
        return value[:max_len]
    return value[: max_len - 1] + "…"


SELECTED_WORD_COLOR = "\x1b[30;103m"
ANSI_RESET = "\x1b[0m"


def terminal_color_supported(stream=None) -> bool:
    """Enable ANSI color on a real Windows console and detect other terminals."""
    stream = sys.stdout if stream is None else stream
    if os.environ.get("NO_COLOR") is not None:
        return False
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not handle or not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_virtual_terminal_processing = 0x0004
        if mode.value & enable_virtual_terminal_processing:
            return True
        return bool(
            kernel32.SetConsoleMode(
                handle,
                mode.value | enable_virtual_terminal_processing,
            )
        )
    except Exception:
        # Color is optional; an unusual console host must never break review.
        return False


def highlight_selected_word(text: str, word: str, enabled: bool) -> str:
    if not enabled or not word:
        return text
    pattern = re.compile(
        rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])",
        flags=re.IGNORECASE,
    )
    parts = re.split(r"(<[^>]+>)", text)
    for index in range(0, len(parts), 2):
        highlighted, count = pattern.subn(
            lambda match: f"{SELECTED_WORD_COLOR}{match.group(0)}{ANSI_RESET}",
            parts[index],
            count=1,
        )
        parts[index] = highlighted
        if count:
            break
    return "".join(parts)


def containing_edit_term(lines: Sequence[str], word: str) -> str:
    """Return the first hyphenated/underscored term containing the selected word."""
    term_characters = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-–—")
    for line in lines:
        for match in WORD_RE.finditer(line):
            if match.group(0).casefold() != word.casefold():
                continue
            # Do not treat text inside an HTML-style subtitle tag as dialogue.
            if line.rfind("<", 0, match.start()) > line.rfind(">", 0, match.start()):
                continue
            start, end = match.span()
            while start > 0 and line[start - 1] in term_characters:
                start -= 1
            while end < len(line) and line[end] in term_characters:
                end += 1
            return line[start:end].strip("_-–—") or word
    return word


def sorted_unique(values: Iterable[str]) -> List[str]:
    cleaned = []
    seen = set()
    for value in values:
        item = value.strip()
        if not item:
            continue
        key = item.casefold()
        if key not in seen:
            cleaned.append(item)
            seen.add(key)
    return sorted(cleaned, key=lambda s: s.casefold())


def is_sound_effect_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped.startswith("[") and stripped.endswith("]"))


def is_speaker_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("-"):
        return True
    match = re.match(
        r"^[A-Z][A-Za-z0-9 ._'’\-]{0,40}:(?:\s+.*)?$",
        stripped,
    )
    if not match:
        return False
    label = stripped.split(":", 1)[0]
    # Periods are valid in labels such as ``P.A.`` and ``Dr. Fraiser``, but a
    # multi-letter word immediately followed by ``.Capital`` is concatenated
    # dialogue, not one long speaker name (``I'm sorry.Hammond:``).
    if re.search(r"[?!]|[A-Za-z]{2,}\.(?=[A-Z])", label):
        return False
    return True


def strip_html_tags(text: str) -> str:
    return HTML_TAG_RE.sub("", text)


def dictionary_key(text: str) -> str:
    """Return a case-insensitive key with typographic apostrophes unified."""
    return text.replace("’", "'").casefold()


def dictionary_set_contains(values: set, key: str) -> bool:
    """Support normalized loaded sets and in-memory contexts built by callers."""
    return key in values or key.replace("'", "’") in values


@dataclass
class SubtitleBlock:
    index: str
    timestamp: str
    text_lines: List[str]
    original_lines: List[str] = field(default_factory=list)
    has_index: bool = True
    has_timestamp: bool = True

    def to_srt(self) -> str:
        lines = []
        if self.has_index:
            lines.append(self.index)
        if self.has_timestamp:
            lines.append(self.timestamp)
        lines.extend(self.text_lines)
        return "\n".join(lines) + "\n"

    def render(self) -> str:
        return self.to_srt().rstrip()


@dataclass(frozen=True)
class SpellcheckIssuePreview:
    """Interface-neutral, read-only description of one spelling issue."""

    path: Path
    relative_file: str
    file_number: int
    total_files: int
    subtitle_index: int
    total_subtitles: int
    word: str
    line_index: int
    start: int
    end: int
    suggestions: Tuple[str, ...]
    previous_blocks: Tuple[str, ...]
    current_block: str
    current_text: str
    timestamp: str
    next_blocks: Tuple[str, ...]


@dataclass(frozen=True)
class SpellcheckReviewUndoAction:
    """One reversible mutation of a GUI review's in-memory state."""

    kind: str
    issue: SpellcheckIssuePreview
    before_text_lines: Tuple[str, ...] = ()
    dictionary_effect: Optional[dict] = None
    replacement_effect: Optional[dict] = None


@dataclass(frozen=True)
class SpellcheckReviewCommitResult:
    """Files written and backup archives retained by one GUI review commit."""

    changed_files: Tuple[Path, ...] = ()
    backup_archives: Tuple[Path, ...] = ()


@dataclass(frozen=True)
class SubtitleFileFormat:
    encoding: str = "utf-8"
    bom: bytes = b""
    newline: str = "\n"
    terminal_newlines: str = "\n"

    @property
    def trailing_newline(self) -> bool:
        return bool(self.terminal_newlines)


@dataclass
class DictionaryContext:
    language: str
    base_words: set = field(default_factory=set)
    user_words: set = field(default_factory=set)
    universe_words: set = field(default_factory=set)
    user_names: Dict[str, str] = field(default_factory=dict)
    universe_names: Dict[str, str] = field(default_factory=dict)
    user_acronyms: set = field(default_factory=set)
    universe_acronyms: set = field(default_factory=set)
    substitutions: Dict[str, str] = field(default_factory=dict)
    user_substitutions: Dict[str, str] = field(default_factory=dict)
    universe_substitutions: Dict[str, str] = field(default_factory=dict)
    acronym_set: set = field(default_factory=lambda: set(COMMON_ACRONYMS))
    universe: Optional[str] = None
    recognize_dropped_g_apostrophe_forms: bool = False

    @property
    def all_words(self) -> set:
        return {
            word
            for word in self.base_words | self.user_words | self.universe_words | set(LOWERCASE_WORDS)
            if not re.search(r"\s", word)
        }

    @property
    def name_map(self) -> Dict[str, str]:
        merged = {}
        merged.update(self.user_names)
        merged.update(self.universe_names)
        return merged

    @property
    def single_name_map(self) -> Dict[str, str]:
        return {
            key: preferred
            for key, preferred in self.name_map.items()
            if not re.search(r"\s", preferred)
        }

    @property
    def phrase_map(self) -> Dict[str, str]:
        phrases = {
            dictionary_key(phrase): phrase
            for phrase in self.user_words | self.universe_words
            if re.search(r"\s", phrase)
        }
        phrases.update({
            dictionary_key(preferred): preferred
            for preferred in self.name_map.values()
            if re.search(r"\s", preferred)
        })
        return phrases

    @property
    def explicit_acronyms(self) -> set:
        return self.user_acronyms | self.universe_acronyms

    def is_known_word(self, word: str, session_ignores: Optional[set] = None) -> bool:
        if not word:
            return True
        has_trailing_apostrophe = word.endswith(("'", "’"))
        clean = word.strip("'’")
        if not clean:
            return True
        lower = dictionary_key(clean)
        if session_ignores and dictionary_set_contains(session_ignores, lower):
            return True
        if (
            lower in LOWERCASE_WORDS
            or dictionary_set_contains(self.base_words, lower)
            or dictionary_set_contains(self.user_words, lower)
            or dictionary_set_contains(self.universe_words, lower)
        ):
            return True
        if (
            self.recognize_dropped_g_apostrophe_forms
            and has_trailing_apostrophe
            and len(lower) > 2
            and lower.endswith("in")
            and (
                dictionary_set_contains(self.base_words, f"{lower}g")
                or dictionary_set_contains(self.user_words, f"{lower}g")
                or dictionary_set_contains(self.universe_words, f"{lower}g")
            )
        ):
            return True
        single_names = self.single_name_map
        if lower in single_names or lower.replace("'", "’") in single_names:
            return True
        if preferred_acronym_casing(clean, self.acronym_set) is not None:
            return True
        # Possessive names: O'Neill's style words are tokenized as O'Neill, but handle simple s.
        names = self.name_map
        name_base = lower[:-1]
        if lower.endswith("s") and (
            name_base in names or name_base.replace("'", "’") in names
        ):
            return True
        return False

    def suggestions_for(self, word: str) -> List[str]:
        candidates = set(self.all_words)
        candidates.update(self.single_name_map.values())
        candidates.update(self.acronym_set)
        candidates = {c for c in candidates if c and abs(len(c) - len(word)) <= 4}
        # Sort first so equally ranked suggestions remain deterministic across
        # Python processes despite set hash randomization.
        ordered_candidates = sorted(candidates, key=lambda value: (value.casefold(), value))
        return difflib.get_close_matches(word, ordered_candidates, n=6, cutoff=0.68)


@dataclass
class SpellcheckReviewSession:
    """In-memory spelling review state shared by non-console interfaces."""

    files: Tuple[Path, ...]
    target: Path
    context: DictionaryContext
    options_snapshot: Dict[str, object] = field(default_factory=dict)
    mode: str = "spellcheck"
    prepared_blocks: Dict[int, List[SubtitleBlock]] = field(default_factory=dict)
    source_bytes: Dict[int, bytes] = field(default_factory=dict)
    ignored_occurrences: set = field(default_factory=set)
    ignored_words: set = field(default_factory=set)
    substitutions: Dict[str, str] = field(default_factory=dict)
    validation_findings: List[dict] = field(default_factory=list)
    undo_actions: List[SpellcheckReviewUndoAction] = field(default_factory=list)
    file_index: int = 0
    subtitle_index: int = 0
    current_issue: Optional[SpellcheckIssuePreview] = None
    recovery_paused: bool = False


class SpellcheckReviewPaused(Exception):
    """Signal a requested pause without treating it as a scan failure."""


class UpdateError(RuntimeError):
    """Raised when release metadata or a downloaded update is not trustworthy."""


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int
    digest: Optional[str] = None


@dataclass(frozen=True)
class ReleaseUpdate:
    version: str
    tag: str
    name: str
    page_url: str
    notes: str
    asset: ReleaseAsset
    checksum_asset: ReleaseAsset


def _version_parts(value: str) -> Tuple[Tuple[int, ...], Tuple[Tuple[int, object], ...]]:
    """Return comparable numeric and prerelease components for project versions."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:[-+](.+))?", value.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"Unsupported version: {value}")
    numeric = tuple(int(part) for part in match.group(1).split("."))
    suffix = match.group(2)
    if suffix is None:
        return numeric, ((2, ""),)
    tokens: List[Tuple[int, object]] = []
    for token in re.findall(r"[A-Za-z]+|\d+", suffix.casefold()):
        tokens.append((1, int(token)) if token.isdigit() else (0, token))
    return numeric, tuple(tokens)


def is_newer_version(candidate: str, current: str) -> bool:
    """Compare the stable GitHub release version with this runtime version."""
    candidate_numeric, candidate_suffix = _version_parts(candidate)
    current_numeric, current_suffix = _version_parts(current)
    width = max(len(candidate_numeric), len(current_numeric))
    candidate_numeric += (0,) * (width - len(candidate_numeric))
    current_numeric += (0,) * (width - len(current_numeric))
    if candidate_numeric != current_numeric:
        return candidate_numeric > current_numeric
    return candidate_suffix > current_suffix


def _validated_update_url(url: str, *, project_asset: bool = False) -> str:
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or hostname not in UPDATE_ALLOWED_HOSTS:
        raise UpdateError("The update service returned an untrusted download address.")
    if project_asset and (
        hostname != "github.com"
        or not parsed.path.casefold().startswith(
            "/gearheart89/subtitle-universe-spellcheck-public/releases/download/"
        )
    ):
        raise UpdateError("The update asset does not belong to the configured project.")
    return url


def _read_limited_response(response, limit: int, description: str) -> bytes:
    raw_length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if raw_length:
        try:
            if int(raw_length) > limit:
                raise UpdateError(f"The {description} exceeds the allowed size.")
        except ValueError as error:
            raise UpdateError(f"The {description} has an invalid size.") from error
    data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError(f"The {description} exceeds the allowed size.")
    return data


class SubtitleCleanupTool:
    def __init__(self) -> None:
        self.script_dir = application_root()
        self.dict_dir = self.script_dir / "dictionaries"
        self.base_dir = self.dict_dir / "base"
        self.user_dir = self.dict_dir / "user"
        self.universe_dir = self.dict_dir / "universes"
        self.options_path = self.dict_dir / "options.ini"
        self.session_state_path = self.dict_dir / "session_state.json"
        self.gui_session_state_path = self.dict_dir / "gui_session_state.json.gz"
        self.session_log_path = self.dict_dir / "session_log.jsonl"
        self.options: Dict[str, object] = dict(DEFAULT_OPTIONS)
        self.update_check_preference_confirmed = False
        self.undo_stack: List[dict] = []
        self.current_session_ignores: set = set()
        self.current_session_substitutions: Dict[str, str] = {}
        self.block_ignores: set = set()
        self.subtitle_file_formats: Dict[str, SubtitleFileFormat] = {}
        self.validation_findings: List[dict] = []
        self.ensure_folder_structure()
        self.load_options()

    # ------------------------------------------------------------------
    # Setup / options
    # ------------------------------------------------------------------
    def ensure_folder_structure(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.universe_dir.mkdir(parents=True, exist_ok=True)

        for language in ("american", "british"):
            base_words_path = self.base_dir / f"{language}_words.txt"
            if not base_words_path.exists():
                base_words_path.write_text("\n".join(sorted_unique(COMMON_BASE_WORDS.split())) + "\n", encoding="utf-8")
            for suffix in ("words", "names", "acronyms"):
                path = self.user_dir / f"{language}_{suffix}.txt"
                if not path.exists():
                    path.write_text("", encoding="utf-8")
            subs_path = self.user_dir / f"{language}_substitutions.tsv"
            if not subs_path.exists():
                subs_path.write_text("", encoding="utf-8")

        if not self.options_path.exists():
            self.save_options()

    def load_options(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(self.options_path, encoding="utf-8")
        self.update_check_preference_confirmed = parser.getboolean(
            "options", "update_check_preference_confirmed", fallback=False
        )
        loaded = dict(DEFAULT_OPTIONS)
        if parser.has_section("options"):
            for key, default in DEFAULT_OPTIONS.items():
                raw = parser.get("options", key, fallback=str(default))
                if isinstance(default, bool):
                    parsed = parse_bool(raw)
                    loaded[key] = default if parsed is None else parsed
                elif isinstance(default, int):
                    try:
                        value = int(raw)
                        loaded[key] = value if value > 0 else default
                    except ValueError:
                        loaded[key] = default
                else:
                    loaded[key] = (
                        raw
                        if key != "capitalization_mode" or raw in CAPITALIZATION_MODES
                        else str(default)
                    )
        self.options = loaded

    def save_options(self) -> None:
        parser = configparser.ConfigParser()
        parser["options"] = {key: str(value) for key, value in self.options.items()}
        parser["options"]["update_check_preference_confirmed"] = str(
            getattr(self, "update_check_preference_confirmed", False)
        )
        self.dict_dir.mkdir(parents=True, exist_ok=True)
        output = io.StringIO()
        parser.write(output)
        self.atomic_write_text(self.options_path, output.getvalue())

    def set_option_value(
        self,
        key: str,
        value: object,
        *,
        allow_long_universe_names: bool = False,
    ) -> None:
        """Validate and atomically persist one option without console prompts."""
        if key not in DEFAULT_OPTIONS:
            raise ValueError("That option is not recognized.")
        default = DEFAULT_OPTIONS[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError("This option must be true or false.")
        elif isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("This option must be a positive whole number.")
            if (
                key == "maximum_universe_display_name_length"
                and value > 32
                and not allow_long_universe_names
            ):
                raise ValueError(
                    "Universe names longer than 32 characters may break table layouts."
                )
        elif key == "capitalization_mode" and value not in CAPITALIZATION_MODES:
            raise ValueError("Choose a listed capitalization preference.")
        previous = self.options[key]
        previous_update_confirmation = getattr(
            self, "update_check_preference_confirmed", False
        )
        self.options[key] = value
        if key == "check_for_updates_at_startup":
            self.update_check_preference_confirmed = True
        try:
            self.save_options()
        except Exception:
            self.options[key] = previous
            self.update_check_preference_confirmed = previous_update_confirmation
            raise

    # ------------------------------------------------------------------
    # Stage 1 update discovery and verified ZIP download
    # ------------------------------------------------------------------
    def check_for_update(
        self,
        *,
        current_version: str = SCRIPT_VERSION,
        frozen: Optional[bool] = None,
        platform_name: Optional[str] = None,
        machine: Optional[str] = None,
        opener=urllib.request.urlopen,
        timeout: float = UPDATE_TIMEOUT_SECONDS,
    ) -> Optional[ReleaseUpdate]:
        """Return the matching newer release without downloading or installing it."""
        request = urllib.request.Request(
            UPDATE_API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"SubtitleUniverseSpellcheck/{current_version}",
            },
        )
        try:
            with opener(request, timeout=timeout) as response:
                _validated_update_url(response.geturl())
                raw_metadata = _read_limited_response(response, UPDATE_METADATA_LIMIT, "release metadata")
            metadata = json.loads(raw_metadata.decode("utf-8"))
        except UpdateError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.URLError) as error:
            raise UpdateError("The release information could not be checked.") from error
        if not isinstance(metadata, dict) or metadata.get("draft") or metadata.get("prerelease"):
            raise UpdateError("The update service returned invalid release information.")
        tag = str(metadata.get("tag_name", "")).strip()
        version = tag[1:] if tag.casefold().startswith("v") else tag
        try:
            newer = is_newer_version(version, current_version)
        except ValueError as error:
            raise UpdateError("The release uses an unsupported version number.") from error
        if not newer:
            return None

        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        runtime_platform = sys.platform if platform_name is None else platform_name
        if is_frozen and runtime_platform == "win32":
            runtime_machine = platform.machine() if machine is None else machine
            architecture_key = runtime_machine.casefold().replace("_", "-")
            architecture = {
                "amd64": "x64",
                "x86-64": "x64",
                "x64": "x64",
                "arm64": "arm64",
                "aarch64": "arm64",
                "x86": "x86",
                "i386": "x86",
                "i686": "x86",
            }.get(architecture_key, architecture_key)
            asset_name = f"SubtitleUniverseSpellcheck-{version}-windows-{architecture}.zip"
        else:
            asset_name = f"SubtitleUniverseSpellcheck-{version}-source.zip"
        checksum_name = asset_name + ".sha256"

        assets_by_name: Dict[str, ReleaseAsset] = {}
        assets = metadata.get("assets")
        if not isinstance(assets, list):
            raise UpdateError("The release does not contain a usable asset list.")
        for item in assets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            url = str(item.get("browser_download_url", ""))
            try:
                size = int(item.get("size", 0))
            except (TypeError, ValueError):
                continue
            if name in {asset_name, checksum_name}:
                _validated_update_url(url, project_asset=True)
                assets_by_name[name] = ReleaseAsset(name, url, size, item.get("digest"))
        if asset_name not in assets_by_name or checksum_name not in assets_by_name:
            raise UpdateError(f"Release {version} does not provide {asset_name} and its checksum.")
        asset = assets_by_name[asset_name]
        checksum_asset = assets_by_name[checksum_name]
        if asset.size < 1 or asset.size > UPDATE_ARCHIVE_LIMIT:
            raise UpdateError("The update archive has an invalid size.")
        if checksum_asset.size < 1 or checksum_asset.size > UPDATE_CHECKSUM_LIMIT:
            raise UpdateError("The update checksum has an invalid size.")
        return ReleaseUpdate(
            version,
            tag,
            str(metadata.get("name") or tag),
            _validated_update_url(str(metadata.get("html_url", ""))),
            str(metadata.get("body") or ""),
            asset,
            checksum_asset,
        )

    def download_update(
        self,
        update: ReleaseUpdate,
        destination: Path,
        *,
        opener=urllib.request.urlopen,
        timeout: float = UPDATE_TIMEOUT_SECONDS,
    ) -> Tuple[Path, Path]:
        """Download and verify an update ZIP without replacing application files."""
        destination = Path(destination)
        if destination.suffix.casefold() != ".zip":
            raise UpdateError("The update download must be saved as a ZIP file.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        archive_part = Path(str(destination) + ".part")
        checksum_path = Path(str(destination) + ".sha256")
        checksum_part = Path(str(checksum_path) + ".part")
        for temporary in (archive_part, checksum_part):
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        try:
            checksum_request = urllib.request.Request(
                _validated_update_url(update.checksum_asset.url, project_asset=True),
                headers={"User-Agent": f"SubtitleUniverseSpellcheck/{SCRIPT_VERSION}"},
            )
            with opener(checksum_request, timeout=timeout) as response:
                _validated_update_url(response.geturl())
                checksum_data = _read_limited_response(response, UPDATE_CHECKSUM_LIMIT, "checksum")
            checksum_match = re.search(rb"(?i)(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])", checksum_data)
            if checksum_match is None:
                raise UpdateError("The published checksum is invalid.")
            expected_digest = checksum_match.group(1).decode("ascii").casefold()
            if update.asset.digest:
                api_digest = str(update.asset.digest).casefold()
                if not api_digest.startswith("sha256:") or api_digest[7:] != expected_digest:
                    raise UpdateError("The published checksum conflicts with the release metadata.")

            archive_request = urllib.request.Request(
                _validated_update_url(update.asset.url, project_asset=True),
                headers={"User-Agent": f"SubtitleUniverseSpellcheck/{SCRIPT_VERSION}"},
            )
            digest = hashlib.sha256()
            total = 0
            with opener(archive_request, timeout=timeout) as response, archive_part.open("wb") as handle:
                _validated_update_url(response.geturl())
                raw_length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
                if raw_length and int(raw_length) > UPDATE_ARCHIVE_LIMIT:
                    raise UpdateError("The update archive exceeds the allowed size.")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > UPDATE_ARCHIVE_LIMIT:
                        raise UpdateError("The update archive exceeds the allowed size.")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if update.asset.size and total != update.asset.size:
                raise UpdateError("The downloaded archive size does not match the release metadata.")
            if digest.hexdigest().casefold() != expected_digest:
                raise UpdateError("The downloaded archive checksum does not match the published checksum.")
            try:
                with zipfile.ZipFile(archive_part, "r") as archive:
                    members = archive.infolist()
                    if not members:
                        raise UpdateError("The downloaded update ZIP is empty.")
                    for member in members:
                        path = PurePosixPath(member.filename.replace("\\", "/"))
                        if path.is_absolute() or ".." in path.parts:
                            raise UpdateError("The downloaded update ZIP contains an unsafe path.")
                    if archive.testzip() is not None:
                        raise UpdateError("The downloaded update ZIP is damaged.")
            except zipfile.BadZipFile as error:
                raise UpdateError("The downloaded update is not a valid ZIP file.") from error

            with checksum_part.open("w", encoding="ascii", newline="\n") as handle:
                handle.write(f"{expected_digest}  {destination.name}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(archive_part, destination)
            os.replace(checksum_part, checksum_path)
            return destination, checksum_path
        except UpdateError:
            raise
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise UpdateError("The update ZIP could not be downloaded and verified.") from error
        finally:
            for temporary in (archive_part, checksum_part):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def check_for_updates_cli(self) -> None:
        """Offer a verified ZIP download at CLI startup; failures remain nonfatal."""
        if not getattr(self, "update_check_preference_confirmed", False):
            print(
                "\nSubtitle Universe Spellcheck can check the public GitHub Releases "
                "page for newer versions when it starts. No network request has been "
                "made yet."
            )
            enabled = input("Allow automatic update checks at startup? [y/N]: ").strip().casefold() in {
                "y",
                "yes",
            }
            try:
                self.set_option_value("check_for_updates_at_startup", enabled)
            except OSError as error:
                print(f"The update-check preference could not be saved: {error}")
                return
        if not self.options.get("check_for_updates_at_startup", False):
            return
        try:
            update = self.check_for_update()
        except UpdateError:
            return
        if update is None:
            return
        print(f"\nVersion {update.version} is available: {update.name}")
        print(update.page_url)
        print("Stage 1 downloads a verified ZIP only; it does not install or replace files.")
        if input("Download this update ZIP now? [y/N]: ").strip().casefold() not in {"y", "yes"}:
            return
        default_directory = Path.home() / "Downloads"
        if not default_directory.is_dir():
            default_directory = self.script_dir
        default_path = default_directory / update.asset.name
        chosen = input(f"Save as [{default_path}]: ").strip()
        destination = Path(chosen).expanduser() if chosen else default_path
        try:
            archive_path, checksum_path = self.download_update(update, destination)
        except UpdateError as error:
            print(f"Update download failed: {error}")
            return
        print(f"Downloaded and verified: {archive_path}")
        print(f"Checksum: {checksum_path}")

    # ------------------------------------------------------------------
    # Logs / state
    # ------------------------------------------------------------------
    def log_event(self, event: dict) -> None:
        payload = {"timestamp": now_iso(), **event}
        self.session_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def load_session_state(self) -> dict:
        if not self.session_state_path.exists():
            return {}
        try:
            state = json.loads(self.session_state_path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save_session_state(self, state: dict) -> None:
        state["last_updated_at"] = now_iso()
        state["schema_version"] = SCHEMA_VERSION
        self.session_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.atomic_write_text(
            self.session_state_path,
            json.dumps(state, indent=2, ensure_ascii=False),
        )

    def clear_session_log(self) -> None:
        """Atomically clear history without touching dictionaries or recovery."""
        self.atomic_write_text(self.session_log_path, "")

    def show_flush_session_log_help(self) -> None:
        clear_screen()
        print("Flush session log — Help\n")
        print(SESSION_LOG_HELP)
        pause()

    def flush_session_log(self) -> None:
        clear_screen()
        print("Flush session log")
        print(SESSION_LOG_HELP)
        choice = input("Type FLUSH to confirm, or press Enter to go back: ").strip()
        if choice == "FLUSH":
            self.clear_session_log()
            print("Session log flushed.")
            pause()

    # ------------------------------------------------------------------
    # Main menu
    # ------------------------------------------------------------------
    def run(self) -> None:
        while True:
            clear_screen()
            print(f"Subtitle Cleanup Tool v{SCRIPT_VERSION}")
            print(f"Running file: {application_entry_path()}")
            print(f"Automatic scan root: {self.script_dir}")
            print()
            print("Subtitle Scan:")
            print("1. Adjust formatting only")
            print("2. Run standard spellcheck with formatting correction")
            print("3. Run spellcheck with optional universe dictionary and formatting correction")
            print("R. Restore subtitles from backup ZIPs")
            print("\nDictionary Maintenance:")
            print("4. Review recent dictionary additions")
            print("5. Review recent substitution additions")
            print("6. User dictionary maintenance")
            print("7. Universe dictionary maintenance and stats")
            print("8. Options menu")
            print("\nInfo/Maintenance:")
            print("9. What do Base, User, and Universe mean?")
            print("10. About this tool")
            print("11. Flush session log [enter 11? for help]")
            print("\n0. Exit")
            choice = input("\nEnter a menu option: ").strip()
            if choice == "1":
                self.run_formatting_only()
            elif choice == "2":
                self.run_spellcheck(use_universe=False)
            elif choice == "3":
                self.run_spellcheck(use_universe=True)
            elif choice.casefold() == "r":
                self.restore_subtitles_from_backup_cli()
            elif choice == "4":
                self.review_recent_dictionary_additions()
            elif choice == "5":
                self.review_recent_substitution_additions()
            elif choice == "6":
                self.user_dictionary_maintenance()
            elif choice == "7":
                self.universe_dictionary_menu()
            elif choice == "8":
                self.options_menu()
            elif choice == "9":
                self.show_dictionary_terms_screen()
            elif choice == "10":
                self.show_about_screen()
            elif choice == "11":
                self.flush_session_log()
            elif choice == "11?":
                self.show_flush_session_log_help()
            elif choice == "0":
                return
            else:
                print("Unexpected input. Please choose a listed option.")
                pause()

    def show_dictionary_terms_screen(self) -> None:
        clear_screen()
        print("What do Base, User, and Universe mean?\n")
        print("Base Dictionary")
        print("  Broad American or British English dictionary. It is read-only for this tool.")
        print("\nUser Dictionary")
        print("  Your personal always-loaded words, names, acronyms, and substitutions for the selected language.")
        print("\nUniverse Dictionary")
        print("  Optional project/franchise-specific words, names, acronyms, and substitutions. Despite sounding broad,")
        print("  Universe is the narrowest scope in this tool, as in a specific fictional/project universe.")
        pause()

    def show_about_screen(self) -> None:
        clear_screen()
        print(f"Subtitle Cleanup and Interactive Spellcheck Tool v{SCRIPT_VERSION}\n")
        print("This tool can recursively scan .srt subtitle files, adjust formatting, normalize dotted")
        print("acronyms, repair common encoding/spacing errors, title-case bracketed sound effects,")
        print("repair mostly-uppercase subtitle lines,")
        print("reflow subtitle line lengths, preserve speaker clarity, run an interactive spellcheck,")
        print("use Base/User/Universe dictionaries, maintain custom dictionaries and substitutions,")
        print("recover from interrupted spellcheck sessions, and review recent additions.")
        print("\nIt is designed to avoid unsafe automatic spelling guesses. Formatting rules and explicit")
        print("substitutions can be automatic; unknown spelling issues are presented interactively.")
        print("\nProject page")
        print(f"  {PROJECT_URL}")
        print("\nApplication source: MIT License")
        print("\nSCOWL dictionary credit")
        print(SCOWL_CREDIT)
        print("\nSCOWL 2026.02.25 source page")
        print(f"  {SCOWL_URL}")
        print("\nComplete bundled notice")
        print("  dictionaries/base/SCOWL-COPYRIGHT.txt")
        pause()

    # ------------------------------------------------------------------
    # Options menu
    # ------------------------------------------------------------------
    def options_menu(self) -> None:
        while True:
            clear_screen()
            print("Options\n")
            for index, (title, _) in enumerate(OPTION_GROUPS, start=1):
                print(f"{index}. {title}")
            print("\n0. Back to main menu")
            raw = input("\nCategory: ").strip()
            if raw == "0":
                self.save_options()
                return
            if not raw.isdigit() or not (1 <= int(raw) <= len(OPTION_GROUPS)):
                print("Unexpected input. Enter a listed category number.")
                pause()
                continue
            title, keys = OPTION_GROUPS[int(raw) - 1]
            self.option_group_menu(title, keys)

    def option_group_menu(self, title: str, keys: Sequence[str]) -> None:
        display_labels = [
            " ".join(
                value
                for value in (OPTION_LABELS[key], OPTION_INLINE_EXAMPLES.get(key, ""))
                if value
            )
            for key in keys
        ]
        label_width = max(40, max(len(label) for label in display_labels))
        while True:
            clear_screen()
            print(f"{title}\n")
            print(f"{'#':<2} {'Option':<{label_width}} | Current State")
            for index, (key, display_label) in enumerate(zip(keys, display_labels), start=1):
                print(f"{index:<2} {display_label:<{label_width}} | {self.options[key]}")
            print(f"\n{0:<2} Back to Options")
            print("\nEnter an option number to change it.")
            print("Enter an option number followed by ? for details and examples.")
            raw = input("\nOption: ").strip()
            if raw == "0":
                self.save_options()
                return
            show_help = raw.endswith("?")
            num_text = raw[:-1] if show_help else raw
            if not num_text.isdigit() or not (1 <= int(num_text) <= len(keys)):
                print("Unexpected input. Enter a listed option number, such as 1 or 1?.")
                pause()
                continue
            key = keys[int(num_text) - 1]
            if show_help:
                clear_screen()
                print(OPTION_LABELS[key])
                print("\n" + OPTION_DESCRIPTIONS.get(key, "No description available."))
                pause()
                continue
            self.change_option(key)

    def change_option(self, key: str) -> None:
        current = self.options[key]
        clear_screen()
        print(f"Change option: {OPTION_LABELS[key]}")
        print(f"Current value: {current}\n")
        if (
            self.options.get("capitalization_mode") == "all_caps"
            and key in CAPITALIZATION_DEPENDENT_OPTIONS
        ):
            print("This option is not available in All caps mode.")
            print("Change Capitalization preference first to adjust it.")
            pause()
            return
        if key == "capitalization_mode":
            for index, label in enumerate(CAPITALIZATION_MODES.values(), start=1):
                print(f"{index}. {label}")
            raw = input("\nChoice, or press Enter to cancel: ").strip()
            if not raw.isdigit() or not (1 <= int(raw) <= len(CAPITALIZATION_MODES)):
                if raw:
                    print("Choose a listed capitalization preference.")
                    pause()
                return
            self.set_option_value(key, tuple(CAPITALIZATION_MODES)[int(raw) - 1])
            return
        if isinstance(DEFAULT_OPTIONS[key], bool):
            value = input("Enter yes/no, true/false, y/n, t/f, or press Enter to cancel: ").strip()
            if not value:
                return
            parsed = parse_bool(value)
            if parsed is None:
                print("Please enter yes/no, true/false, y/n, or t/f.")
                pause()
                return
            self.options[key] = parsed
            self.save_options()
            return

        if isinstance(DEFAULT_OPTIONS[key], int):
            value = input("Enter a positive whole number, or press Enter to cancel: ").strip()
            if not value:
                return
            if not value.isdigit() or int(value) <= 0:
                print("Please enter a positive whole number.")
                pause()
                return
            number = int(value)
            if key == "maximum_universe_display_name_length" and number > 32:
                clear_screen()
                print("Universe names longer than 32 characters may break table layouts.")
                print("This tool was not designed around very long displayed universe names.\n")
                print("1. Go back and enter a shorter limit")
                print("2. I understand this may break layouts")
                confirm = input("\nChoice: ").strip()
                if confirm != "2":
                    return
            self.options[key] = number
            self.save_options()
            return

    # ------------------------------------------------------------------
    # Dictionary loading / saving
    # ------------------------------------------------------------------
    def choose_language(self) -> Optional[str]:
        clear_screen()
        print("Choose Base Dictionary language")
        print("1. American English")
        print("2. British English")
        print("0. Go back")
        choice = input("\nChoice: ").strip()
        if choice == "0":
            return None
        return BASE_LANGUAGE_CHOICES.get(choice)

    def load_dictionary_context(self, language: str, universe: Optional[str] = None) -> DictionaryContext:
        ctx = DictionaryContext(
            language=language,
            universe=universe,
            recognize_dropped_g_apostrophe_forms=bool(
                self.options["recognize_dropped_g_apostrophe_forms"]
            ),
        )
        ctx.base_words = self.load_word_set(self.base_dir / f"{language}_words.txt")
        ctx.user_words = self.load_word_set(self.user_dir / f"{language}_words.txt")
        ctx.user_names = self.load_name_map(self.user_dir / f"{language}_names.txt")
        ctx.user_acronyms = self.load_acronym_set(
            self.user_dir / f"{language}_acronyms.txt"
        )
        ctx.user_substitutions = self.load_substitutions(self.user_dir / f"{language}_substitutions.tsv")
        ctx.substitutions.update(ctx.user_substitutions)
        if universe:
            u_dir = self.universe_dir / universe
            ctx.universe_words = self.load_word_set(u_dir / "words.txt")
            ctx.universe_names = self.load_name_map(u_dir / "names.txt")
            ctx.universe_acronyms = self.load_acronym_set(u_dir / "acronyms.txt")
            ctx.universe_substitutions = self.load_substitutions(u_dir / "substitutions.tsv")
            ctx.substitutions.update(ctx.universe_substitutions)
        ctx.acronym_set.update(ctx.explicit_acronyms)
        ctx.acronym_set.update(self.derive_acronyms(ctx))
        return ctx

    def load_acronym_set(self, path: Path) -> set:
        if not path.exists():
            return set()
        return {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    def validate_acronym_entry(self, value: str) -> str:
        value = value.strip()
        if value.casefold() in {"am", "pm"}:
            raise ValueError(
                "AM and PM are already handled contextually as time expressions "
                "and cannot be added to an acronym dictionary."
            )
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", value):
            raise ValueError(
                "An acronym must be one undotted token containing only letters and numbers."
            )
        if len(value) < 2:
            raise ValueError("An acronym must contain at least two characters.")
        return value

    def acronym_word_conflicts(
        self,
        value: str,
        context: DictionaryContext,
    ) -> List[str]:
        """Return active word/name layers that also contain an acronym token."""
        key = dictionary_key(value)
        language_label = f"{context.language.title()} English"
        conflicts = []
        if key in context.base_words:
            conflicts.append(f"{language_label} Base Dictionary")
        if key in context.user_words or key in context.user_names:
            conflicts.append(f"{language_label} User Dictionary")
        if context.universe and (
            key in context.universe_words or key in context.universe_names
        ):
            conflicts.append(f"{context.universe} Universe Dictionary")
        return conflicts

    def acronym_word_conflicts_for_location(
        self,
        value: str,
        target: str,
        *,
        language: Optional[str] = None,
        universe: Optional[str] = None,
    ) -> List[str]:
        """Check word layers relevant to a maintenance destination."""
        if target == "user":
            if language not in {"american", "british"}:
                raise ValueError("Choose American or British English first.")
            contexts = [self.load_dictionary_context(language)]
            universe_names = self.list_universes()
        elif target == "universe" and universe:
            # A Universe may be paired with either Base language, so check both.
            contexts = [
                self.load_dictionary_context(active_language)
                for active_language in ("american", "british")
            ]
            universe_names = [universe]
        else:
            raise ValueError("Choose a dictionary destination first.")
        conflicts = []
        for context in contexts:
            for label in self.acronym_word_conflicts(value, context):
                if label not in conflicts:
                    conflicts.append(label)
        key = dictionary_key(value)
        for universe_name in universe_names:
            words = self.load_word_set(
                self.universe_dir / universe_name / "words.txt"
            )
            names = self.load_name_map(
                self.universe_dir / universe_name / "names.txt"
            )
            label = f"{universe_name} Universe Dictionary"
            if (key in words or key in names) and label not in conflicts:
                conflicts.append(label)
        return conflicts

    def word_acronym_conflicts(
        self,
        value: str,
        context: DictionaryContext,
    ) -> List[str]:
        """Return active acronym layers that also contain an accepted word."""
        key = dictionary_key(value)
        language_label = f"{context.language.title()} English"
        conflicts = []
        if any(dictionary_key(acronym) == key for acronym in COMMON_ACRONYMS):
            conflicts.append("Built-in common acronym handling")
        if any(dictionary_key(acronym) == key for acronym in context.user_acronyms):
            conflicts.append(f"{language_label} User Dictionary")
        if context.universe and any(
            dictionary_key(acronym) == key
            for acronym in context.universe_acronyms
        ):
            conflicts.append(f"{context.universe} Universe Dictionary")
        return conflicts

    def word_acronym_conflicts_for_location(
        self,
        value: str,
        target: str,
        *,
        language: Optional[str] = None,
        universe: Optional[str] = None,
    ) -> List[str]:
        """Check acronym layers relevant to a word-maintenance destination."""
        if target == "user":
            if language not in {"american", "british"}:
                raise ValueError("Choose American or British English first.")
            contexts = [self.load_dictionary_context(language)]
            universe_names = self.list_universes()
        elif target == "universe" and universe:
            contexts = [
                self.load_dictionary_context(active_language)
                for active_language in ("american", "british")
            ]
            universe_names = [universe]
        else:
            raise ValueError("Choose a dictionary destination first.")
        conflicts = []
        for context in contexts:
            for label in self.word_acronym_conflicts(value, context):
                if label not in conflicts:
                    conflicts.append(label)
        key = dictionary_key(value)
        for universe_name in universe_names:
            acronyms = self.load_acronym_set(
                self.universe_dir / universe_name / "acronyms.txt"
            )
            label = f"{universe_name} Universe Dictionary"
            if any(dictionary_key(acronym) == key for acronym in acronyms):
                if label not in conflicts:
                    conflicts.append(label)
        return conflicts

    def confirm_acronym_word_conflict(
        self,
        value: str,
        conflicts: Sequence[str],
    ) -> bool:
        """Ask the CLI user whether an acronym/word collision is intentional."""
        if not conflicts:
            return True
        print(
            f'Warning: "{value}" is already accepted as a word in '
            + ", ".join(conflicts)
            + "."
        )
        print(
            "Adding it as an acronym will make the stored acronym casing "
            "authoritative when that dictionary is active."
        )
        return input("Add this acronym anyway? [y/N]: ").strip().casefold() in {
            "y",
            "yes",
        }

    def confirm_word_acronym_conflict(
        self,
        value: str,
        conflicts: Sequence[str],
    ) -> bool:
        """Ask the CLI user whether a word/acronym collision is intentional."""
        if not conflicts:
            return True
        print(
            f'Warning: "{value}" is already handled as an acronym in '
            + ", ".join(conflicts)
            + "."
        )
        print(
            "Adding it as a word or name creates overlapping dictionary meanings; "
            "acronym casing remains authoritative when applicable."
        )
        return input("Add this dictionary entry anyway? [y/N]: ").strip().casefold() in {
            "y",
            "yes",
        }

    def derive_acronyms(self, ctx: DictionaryContext) -> set:
        acronyms = set()
        for value in list(ctx.substitutions.values()) + list(ctx.name_map.values()):
            cleaned = re.sub(r"[^A-Za-z0-9]", "", value)
            if len(cleaned) >= 2 and cleaned.upper() == cleaned:
                acronyms.add(cleaned)
        for word in ctx.base_words | ctx.user_words | ctx.universe_words:
            if len(word) >= 2 and word.upper() == word:
                acronyms.add(word)
        return acronyms

    def load_word_set(self, path: Path) -> set:
        if not path.exists():
            return set()
        return {
            dictionary_key(line.strip())
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    def load_name_map(self, path: Path) -> Dict[str, str]:
        if not path.exists():
            return {}
        result = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item:
                result[dictionary_key(item)] = item
        return result

    def load_substitutions(self, path: Path) -> Dict[str, str]:
        if not path.exists():
            return {}
        result = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or "\t" not in line:
                continue
            left, right = line.split("\t", 1)
            left = left.strip()
            right = right.strip()
            if left and right:
                result[left.casefold()] = right
        return result

    def save_word_list(self, path: Path, values: Iterable[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted_unique(values)
        self.atomic_write_text(path, "\n".join(ordered) + ("\n" if ordered else ""))

    def save_substitutions(self, path: Path, substitutions: Dict[str, str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for key, value in substitutions.items():
            key = key.strip()
            value = value.strip()
            if key and value:
                rows.append((key, value))
        rows.sort(key=lambda row: row[0].casefold())
        self.atomic_write_text(
            path, "".join(f"{left}\t{right}\n" for left, right in rows)
        )

    def add_word_to_file(self, path: Path, word: str, event: Optional[dict] = None) -> bool:
        word = word.strip()
        if not word:
            return False
        existing = []
        if path.exists():
            existing = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if dictionary_key(word) not in {dictionary_key(x) for x in existing}:
            existing.append(word.strip())
            self.save_word_list(path, existing)
            if event:
                self.log_event(event)
            return True
        return False

    def add_substitution_to_file(self, path: Path, source: str, replacement: str, event: Optional[dict] = None) -> None:
        substitutions = self.load_substitutions(path)
        substitutions[source.casefold()] = replacement
        self.save_substitutions(path, substitutions)
        if event:
            self.log_event(event)

    # ------------------------------------------------------------------
    # File scanning / backups
    # ------------------------------------------------------------------
    def prompt_target_folder(
        self,
        intro_lines: Optional[Sequence[str]] = None,
        start_folder: Optional[Path] = None,
    ) -> Optional[Path]:
        current = (start_folder or Path.cwd()).expanduser().resolve()
        if not current.exists() or not current.is_dir():
            current = self.script_dir.resolve()
        page = 0
        while True:
            try:
                folders = sorted(
                    (path for path in current.iterdir() if path.is_dir()),
                    key=lambda path: path.name.casefold(),
                )
                folder_error = None
            except OSError as exc:
                folders = []
                folder_error = str(exc)
            page_count = max(1, (len(folders) + 9) // 10)
            page = min(page, page_count - 1)
            page_folders = folders[page * 10 : (page + 1) * 10]

            clear_screen()
            if intro_lines:
                for line in intro_lines:
                    print(line)
                print()
            print(f"Choose a subtitle search location — Page {page + 1} of {page_count}")
            print(f"Current folder: {current}")
            print()
            if folder_error:
                print(f"Unable to list subfolders: {folder_error}")
            elif page_folders:
                for number, folder in enumerate(page_folders, start=1):
                    print(f"{number}. {folder.name}")
            else:
                print("No subfolders are available here.")
            print()
            print("S. Select this folder")
            print("U. Go up one level")
            if page > 0:
                print("11. Previous page")
            if page + 1 < page_count:
                print("33. Next page")
            print("0. Return to the main menu")
            print("You may also enter an absolute or relative folder path.")
            if self.options["scan_folders_recursively"]:
                print("Recursive scanning is ON; every folder below the selected root will be searched.")
            else:
                print("Recursive scanning is OFF; only .srt files directly in the selected root will be searched.")
            choice = input("\nChoice or folder path: ").strip().strip('"')
            lowered = choice.casefold()
            if choice == "0":
                return None
            if lowered == "11" and page > 0:
                page -= 1
                continue
            if lowered == "33" and page + 1 < page_count:
                page += 1
                continue
            if lowered == "u":
                current = current.parent.resolve()
                page = 0
                intro_lines = None
                continue
            if choice.isdigit() and 1 <= int(choice) <= len(page_folders):
                current = page_folders[int(choice) - 1].resolve()
                page = 0
                intro_lines = None
                continue
            if lowered == "s":
                resolved = current
            elif not choice:
                print("\nChoose a listed folder, S, U, a page control, a folder path, or 0.")
                pause()
                continue
            else:
                entered = Path(choice).expanduser()
                candidates = [entered]
                if not entered.is_absolute():
                    candidates = [current / entered, self.script_dir / entered, Path.cwd() / entered]

                resolved = None
                for candidate in candidates:
                    if candidate.exists() and candidate.is_dir():
                        resolved = candidate.resolve()
                        break
                if resolved is None:
                    print("\nThat folder does not exist or is not a folder.")
                    pause()
                    continue

            files = self.find_srt_files(resolved)
            if files:
                clear_screen()
                self.show_scan_summary(resolved, files)
                return resolved

            intro_lines = [
                "No .srt files were found in:",
                str(resolved),
                (
                    "All folders below that location were also checked."
                    if self.options["scan_folders_recursively"]
                    else "Only that folder was checked because recursive scanning is disabled."
                ),
                "Please choose another search location.",
            ]
            current = resolved
            page = 0

    def select_target_folder(self, action_label: str) -> Optional[Path]:
        default_root = self.script_dir
        clear_screen()
        print(f"Automatic subtitle scan — v{SCRIPT_VERSION}")
        print(f"Checking project root: {default_root}")
        print(
            "Recursive scanning: ON"
            if self.options["scan_folders_recursively"]
            else "Recursive scanning: OFF"
        )
        print()

        files = self.find_srt_files(default_root)
        if not files:
            return self.prompt_target_folder([
                "The automatic scan could not find any .srt files.",
                f"Checked: {default_root}",
                (
                    "All folders below the project root were also checked."
                    if self.options["scan_folders_recursively"]
                    else "Only the project root was checked because recursive scanning is disabled."
                ),
                "Please tell the script where to look.",
            ])

        self.show_scan_summary(default_root, files)
        print(f"\n{action_label} will proceed in 5 seconds.")
        print("Press Enter during the countdown to customize the search location.")
        if wait_for_enter_to_customize(5):
            return self.prompt_target_folder()
        return default_root

    def show_scan_summary(self, target_root: Path, files: Sequence[Path]) -> None:
        folder_names = self.scan_folder_names(target_root, files)
        print(f"This script found {len(files)} .srt files in these folders:")
        for name in folder_names[:5]:
            print(name)
        remaining = len(folder_names) - 5
        if remaining > 0:
            print(f"+{remaining} other folder{'s' if remaining != 1 else ''}")

    def scan_folder_names(self, target_root: Path, files: Sequence[Path]) -> List[str]:
        names = set()
        root_label = f"{target_root.name} (root)"
        for path in files:
            relative = path.relative_to(target_root)
            if len(relative.parts) == 1:
                names.add(root_label)
            else:
                names.add(relative.parts[0])
        return sorted(names, key=str.casefold)

    def find_srt_files(self, target_root: Path) -> List[Path]:
        files: List[Path] = []
        if self.options["scan_folders_recursively"]:
            for current_root, _dirs, filenames in os.walk(target_root):
                current_path = Path(current_root)
                for filename in filenames:
                    if Path(filename).suffix.casefold() == ".srt":
                        files.append(current_path / filename)
        else:
            try:
                files = [
                    path for path in target_root.iterdir()
                    if path.is_file() and path.suffix.casefold() == ".srt"
                ]
            except OSError:
                return []
        return sorted(files, key=lambda p: str(p.relative_to(target_root)).casefold())

    def backup_groups(self, target_root: Path, files: Sequence[Path]) -> Dict[Path, List[Path]]:
        groups: Dict[Path, List[Path]] = {}
        for subtitle_path in files:
            relative = subtitle_path.relative_to(target_root)
            if len(relative.parts) == 1:
                backup_root = target_root
            else:
                backup_root = target_root / relative.parts[0]
            groups.setdefault(backup_root, []).append(subtitle_path)
        return groups

    def find_backup_archives(self, target_root: Path) -> List[Path]:
        """Find only archives produced by the grouped subtitle-backup workflow."""
        if not target_root.exists() or not target_root.is_dir():
            return []
        candidates = [target_root / "backup_subtitles.zip"]
        try:
            candidates.extend(
                path / "backup_subtitles.zip"
                for path in target_root.iterdir()
                if path.is_dir()
            )
        except OSError:
            return []
        return sorted(
            (path for path in candidates if path.is_file()),
            key=lambda path: str(path).casefold(),
        )

    def restore_backup_archives(self, target_root: Path) -> Tuple[int, int]:
        """Validate, then atomically restore all subtitle files from grouped archives."""
        archives = self.find_backup_archives(target_root)
        if not archives:
            raise ValueError("No backup_subtitles.zip archives were found.")

        prepared: List[Tuple[Path, bytes]] = []
        destinations = set()
        for archive_path in archives:
            backup_root = archive_path.parent.resolve()
            try:
                with zipfile.ZipFile(archive_path, "r") as archive:
                    bad_entry = archive.testzip()
                    if bad_entry is not None:
                        raise ValueError(
                            f"Backup archive is damaged at {bad_entry}: {archive_path}"
                        )
                    entries = [item for item in archive.infolist() if not item.is_dir()]
                    if not entries:
                        raise ValueError(f"Backup archive contains no files: {archive_path}")
                    for item in entries:
                        relative = PurePosixPath(item.filename)
                        if (
                            relative.is_absolute()
                            or ".." in relative.parts
                            or any(":" in part for part in relative.parts)
                            or relative.suffix.casefold() != ".srt"
                        ):
                            raise ValueError(
                                f"Backup contains an unsafe path: {item.filename}"
                            )
                        destination = backup_root.joinpath(*relative.parts).resolve()
                        try:
                            destination.relative_to(backup_root)
                        except ValueError as error:
                            raise ValueError(
                                f"Backup contains an unsafe path: {item.filename}"
                            ) from error
                        key = str(destination).casefold()
                        if key in destinations:
                            raise ValueError(
                                f"Backup contains a duplicate subtitle path: {destination}"
                            )
                        destinations.add(key)
                        prepared.append((destination, archive.read(item)))
            except zipfile.BadZipFile as error:
                raise ValueError(f"Backup archive is not a valid ZIP: {archive_path}") from error

        originals = {
            path: path.read_bytes() if path.exists() else None for path, _data in prepared
        }
        written: List[Path] = []
        try:
            for path, data in prepared:
                path.parent.mkdir(parents=True, exist_ok=True)
                self.atomic_write_bytes(path, data)
                written.append(path)
        except Exception as error:
            rollback_error = None
            for path in reversed(written):
                try:
                    original = originals[path]
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        self.atomic_write_bytes(path, original)
                except Exception as candidate:
                    rollback_error = candidate
            if rollback_error is not None:
                raise RuntimeError(
                    "Restoration failed and at least one subtitle could not be rolled back."
                ) from error
            raise RuntimeError("Restoration failed; changed files were rolled back.") from error
        return len(archives), len(prepared)

    def restore_subtitles_from_backup_cli(self) -> None:
        clear_screen()
        target = self.select_target_folder("Restore subtitles from backup ZIPs")
        if not target:
            return
        archives = self.find_backup_archives(target)
        if not archives:
            print("No backup_subtitles.zip archives were found in the selected folder or its immediate child folders.")
            pause()
            return
        print(f"\nFound {len(archives)} backup archive(s).")
        print("This will overwrite current subtitle files and cannot be undone from within the tool.")
        confirmation = input("Type YES to restore, or press Enter to cancel: ").strip()
        if confirmation != "YES":
            print("Restore cancelled; no subtitle files were changed.")
            pause()
            return
        try:
            archive_count, file_count = self.restore_backup_archives(target)
        except (OSError, RuntimeError, ValueError) as error:
            print(f"Restore failed: {error}")
        else:
            print(f"Restored {file_count} subtitle file(s) from {archive_count} archive(s).")
            print("The backup archives were retained.")
        pause()

    def create_backup_archive(
        self, backup_root: Path, files: Sequence[Path]
    ) -> Tuple[Path, bool]:
        """Create one flushed grouped archive, or retain the existing archive."""
        backup_path = backup_root / "backup_subtitles.zip"
        if backup_path.exists():
            return backup_path, False
        temporary_path = backup_path.with_name(f".{backup_path.name}.tmp")
        try:
            temporary_path.unlink(missing_ok=True)
            with zipfile.ZipFile(
                temporary_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                for subtitle_path in sorted(
                    files,
                    key=lambda p: str(p.relative_to(backup_root)).casefold(),
                ):
                    zf.write(subtitle_path, subtitle_path.relative_to(backup_root))
            with temporary_path.open("r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, backup_path)
            return backup_path, True
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def create_backup_if_needed(self, target_root: Path, files: Sequence[Path]) -> bool:
        if not self.options["create_backup_subtitles_zip_before_editing"]:
            clear_screen()
            print("Subtitle backup creation is currently disabled.\n")
            print("1. Enable backups and create them before editing")
            print("2. Continue this run without a backup")
            print("0. Cancel and return without editing")
            choice = input("\nChoice: ").strip()
            if choice == "1":
                self.options["create_backup_subtitles_zip_before_editing"] = True
                self.save_options()
            elif choice == "2":
                print("Continuing without a subtitle backup.")
                return True
            else:
                print("Editing cancelled; no subtitle files were changed.")
                return False

        groups = self.backup_groups(target_root, files)
        print("\nPreparing subtitle backups:")
        all_succeeded = True
        for backup_root in sorted(groups, key=lambda p: str(p).casefold()):
            try:
                backup_path, created = self.create_backup_archive(
                    backup_root, groups[backup_root]
                )
                print(
                    f"- {'Created' if created else 'Existing backup retained'}: "
                    f"{backup_path}"
                )
            except (OSError, zipfile.BadZipFile) as exc:
                print(
                    f"- ERROR: Could not create "
                    f"{backup_root / 'backup_subtitles.zip'}: {exc}"
                )
                all_succeeded = False
        return all_succeeded

    # ------------------------------------------------------------------
    # SRT parsing/writing
    # ------------------------------------------------------------------
    def decode_subtitle_bytes(self, raw: bytes) -> Tuple[str, SubtitleFileFormat]:
        bom_encodings = (
            (b"\x00\x00\xfe\xff", "utf-32-be"),
            (b"\xff\xfe\x00\x00", "utf-32-le"),
            (b"\xef\xbb\xbf", "utf-8"),
            (b"\xfe\xff", "utf-16-be"),
            (b"\xff\xfe", "utf-16-le"),
        )
        bom = b""
        encoding = "utf-8"
        content = raw
        for marker, candidate in bom_encodings:
            if raw.startswith(marker):
                bom = marker
                encoding = candidate
                content = raw[len(marker):]
                break
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = raw.decode("cp1252")
                    encoding = "cp1252"
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                    encoding = "latin-1"
            else:
                encoding = "utf-8"
            newline = self.detect_subtitle_newline(text)
            return text, SubtitleFileFormat(
                encoding=encoding,
                newline=newline,
                terminal_newlines=self.subtitle_terminal_newlines(text),
            )

        text = content.decode(encoding)
        return text, SubtitleFileFormat(
            encoding=encoding,
            bom=bom,
            newline=self.detect_subtitle_newline(text),
            terminal_newlines=self.subtitle_terminal_newlines(text),
        )

    def subtitle_terminal_newlines(self, text: str) -> str:
        match = re.search(r"(?:\r\n|\r|\n)+\Z", text)
        return match.group(0) if match else ""

    def detect_subtitle_newline(self, text: str) -> str:
        crlf_count = text.count("\r\n")
        without_crlf = text.replace("\r\n", "")
        counts = {
            "\r\n": crlf_count,
            "\n": without_crlf.count("\n"),
            "\r": without_crlf.count("\r"),
        }
        if not any(counts.values()):
            return "\r\n" if os.name == "nt" else "\n"
        priorities = {"\r\n": 2, "\n": 1, "\r": 0}
        return max(counts, key=lambda value: (counts[value], priorities[value]))

    def parse_srt(
        self, path: Path, source_bytes: Optional[bytes] = None
    ) -> List[SubtitleBlock]:
        raw = path.read_bytes() if source_bytes is None else source_bytes
        text, file_format = self.decode_subtitle_bytes(raw)
        formats = getattr(self, "subtitle_file_formats", None)
        if formats is None:
            formats = {}
            self.subtitle_file_formats = formats
        formats[str(path)] = file_format
        text = normalize_newlines(text)
        content = text.rstrip("\n")
        raw_blocks = re.split(r"\n\s*\n", content) if content else []
        blocks = []
        for block_number, raw_block in enumerate(raw_blocks, start=1):
            lines = raw_block.split("\n")
            if len(lines) >= 2 and SRT_TIMESTAMP_RE.search(lines[1]):
                # Retain unusual but parseable padding exactly. Timestamp and
                # index text are metadata owned by the source subtitle; only
                # cue text is eligible for cleanup.
                index = lines[0]
                timestamp = lines[1]
                text_lines = lines[2:]
                has_index = True
                has_timestamp = True
            elif len(lines) >= 1 and SRT_TIMESTAMP_RE.search(lines[0]):
                index = str(block_number)
                timestamp = lines[0]
                text_lines = lines[1:]
                has_index = False
                has_timestamp = True
            else:
                # Tolerate malformed text-only blocks without inventing metadata.
                index = str(block_number)
                timestamp = ""
                text_lines = lines
                has_index = False
                has_timestamp = False
            blocks.append(SubtitleBlock(
                index=index,
                timestamp=timestamp,
                text_lines=text_lines,
                original_lines=lines,
                has_index=has_index,
                has_timestamp=has_timestamp,
            ))
        return blocks

    def encode_srt(self, path: Path, blocks: Sequence[SubtitleBlock]) -> bytes:
        """Render blocks using the source file's encoding and newline details."""
        formats = getattr(self, "subtitle_file_formats", {})
        default_newline = "\r\n" if os.name == "nt" else "\n"
        file_format = formats.get(str(path), SubtitleFileFormat(
            newline=default_newline,
            terminal_newlines=default_newline,
        ))
        output = "\n\n".join(block.to_srt().rstrip("\n") for block in blocks)
        output = output.replace("\n", file_format.newline)
        if output:
            output += file_format.terminal_newlines
        encoded = output.encode(file_format.encoding)
        return file_format.bom + encoded

    def write_srt(self, path: Path, blocks: Sequence[SubtitleBlock]) -> None:
        self.atomic_write_bytes(path, self.encode_srt(path, blocks))

    def atomic_write_bytes(self, path: Path, data: bytes) -> None:
        """Flush a complete sibling file before atomically replacing the target."""
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(6):
                try:
                    os.replace(temporary_path, path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.05 * (2 ** attempt))
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def atomic_write_text(self, path: Path, text: str) -> None:
        """Publish a complete UTF-8 text file without exposing a partial rewrite."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.atomic_write_bytes(path, text.encode("utf-8"))

    @staticmethod
    def _review_issue_payload(issue: Optional[SpellcheckIssuePreview]) -> Optional[dict]:
        if issue is None:
            return None
        return {
            "path": str(issue.path),
            "relative_file": issue.relative_file,
            "file_number": issue.file_number,
            "total_files": issue.total_files,
            "subtitle_index": issue.subtitle_index,
            "total_subtitles": issue.total_subtitles,
            "word": issue.word,
            "line_index": issue.line_index,
            "start": issue.start,
            "end": issue.end,
            "suggestions": list(issue.suggestions),
            "previous_blocks": list(issue.previous_blocks),
            "current_block": issue.current_block,
            "current_text": issue.current_text,
            "timestamp": issue.timestamp,
            "next_blocks": list(issue.next_blocks),
        }

    @staticmethod
    def _review_issue_from_payload(payload: Optional[dict]) -> Optional[SpellcheckIssuePreview]:
        if payload is None:
            return None
        return SpellcheckIssuePreview(
            path=Path(payload["path"]),
            relative_file=str(payload["relative_file"]),
            file_number=int(payload["file_number"]),
            total_files=int(payload["total_files"]),
            subtitle_index=int(payload["subtitle_index"]),
            total_subtitles=int(payload["total_subtitles"]),
            word=str(payload["word"]),
            line_index=int(payload["line_index"]),
            start=int(payload["start"]),
            end=int(payload["end"]),
            suggestions=tuple(payload.get("suggestions", ())),
            previous_blocks=tuple(payload.get("previous_blocks", ())),
            current_block=str(payload.get("current_block", "")),
            current_text=str(payload.get("current_text", "")),
            timestamp=str(payload.get("timestamp", "")),
            next_blocks=tuple(payload.get("next_blocks", ())),
        )

    @staticmethod
    def _review_block_payload(block: SubtitleBlock) -> dict:
        return {
            "index": block.index,
            "timestamp": block.timestamp,
            "text_lines": list(block.text_lines),
            "original_lines": list(block.original_lines),
            "has_index": block.has_index,
            "has_timestamp": block.has_timestamp,
        }

    @staticmethod
    def _review_block_from_payload(payload: dict) -> SubtitleBlock:
        return SubtitleBlock(
            index=str(payload["index"]),
            timestamp=str(payload["timestamp"]),
            text_lines=[str(value) for value in payload.get("text_lines", ())],
            original_lines=[str(value) for value in payload.get("original_lines", ())],
            has_index=bool(payload.get("has_index", True)),
            has_timestamp=bool(payload.get("has_timestamp", True)),
        )

    def save_gui_review_session(
        self, session: SpellcheckReviewSession, *, paused: bool = False
    ) -> None:
        """Atomically checkpoint a GUI review for crash or power-loss recovery."""
        prepared = {}
        source_hashes = {}
        for file_index, blocks in session.prepared_blocks.items():
            source = session.source_bytes.get(file_index)
            if source is None:
                raise RuntimeError("A prepared subtitle is missing its recovery baseline.")
            prepared[str(file_index)] = [
                self._review_block_payload(block) for block in blocks
            ]
            source_hashes[str(file_index)] = hashlib.sha256(source).hexdigest()
        undo = []
        for action in session.undo_actions:
            undo.append({
                "kind": action.kind,
                "issue": self._review_issue_payload(action.issue),
                "before_text_lines": list(action.before_text_lines),
                "dictionary_effect": action.dictionary_effect,
                "replacement_effect": action.replacement_effect,
            })
        payload = {
            "schema_version": 2,
            "saved_at": now_iso(),
            "target": str(session.target.resolve()),
            "files": [str(path.resolve()) for path in session.files],
            "language": session.context.language,
            "universe": session.context.universe,
            "mode": session.mode,
            "options_snapshot": session.options_snapshot,
            "prepared_blocks": prepared,
            "source_hashes": source_hashes,
            "ignored_occurrences": [list(value) for value in sorted(session.ignored_occurrences)],
            "ignored_words": sorted(session.ignored_words),
            "substitutions": session.substitutions,
            "validation_findings": session.validation_findings,
            "undo_actions": undo,
            "file_index": session.file_index,
            "subtitle_index": session.subtitle_index,
            "current_issue": self._review_issue_payload(session.current_issue),
            "paused": bool(paused),
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.atomic_write_bytes(self.gui_session_state_path, gzip.compress(encoded))

    def load_gui_review_session(self) -> Optional[SpellcheckReviewSession]:
        """Restore a checkpoint only while every prepared source is unchanged."""
        if not self.gui_session_state_path.exists():
            return None
        try:
            raw = gzip.decompress(self.gui_session_state_path.read_bytes())
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, EOFError, gzip.BadGzipFile, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError("The saved GUI recovery journal is unreadable.") from error
        if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2}:
            raise RuntimeError("The saved GUI recovery journal uses an unsupported format.")
        target = Path(payload["target"]).resolve()
        files = tuple(Path(value).resolve() for value in payload.get("files", ()))
        if not target.is_dir() or not files:
            raise RuntimeError("The saved GUI review folder is no longer available.")
        for path in files:
            try:
                path.relative_to(target)
            except ValueError as error:
                raise RuntimeError("The recovery journal contains a file outside its folder.") from error
            if not path.is_file():
                raise RuntimeError(f"A subtitle from the saved GUI review is missing: {path.name}")

        context = self.load_dictionary_context(
            str(payload["language"]), payload.get("universe")
        )
        self.apply_options_snapshot(payload.get("options_snapshot", {}))
        session = self.create_spellcheck_review(files, target, context)
        session.mode = str(payload.get("mode", "spellcheck"))
        if session.mode not in {"spellcheck", "formatting"}:
            raise RuntimeError("The recovery journal contains an invalid review mode.")
        prepared_payload = payload.get("prepared_blocks", {})
        source_hashes = payload.get("source_hashes", {})
        for index_text, blocks_payload in prepared_payload.items():
            file_index = int(index_text)
            if not 0 <= file_index < len(files):
                raise RuntimeError("The recovery journal contains an invalid file position.")
            source = files[file_index].read_bytes()
            if hashlib.sha256(source).hexdigest() != source_hashes.get(index_text):
                raise RuntimeError(
                    f"{files[file_index].name} changed since the GUI recovery journal was saved."
                )
            # Parsing registers the exact source encoding/newline metadata needed
            # by the shared commit path; checkpointed blocks retain prepared edits.
            self.parse_srt(files[file_index], source)
            session.source_bytes[file_index] = source
            session.prepared_blocks[file_index] = [
                self._review_block_from_payload(value) for value in blocks_payload
            ]
        session.ignored_occurrences = {
            tuple(value) for value in payload.get("ignored_occurrences", ())
        }
        session.ignored_words = set(payload.get("ignored_words", ()))
        session.substitutions = {
            str(key).casefold(): str(value)
            for key, value in payload.get("substitutions", {}).items()
        }
        session.validation_findings = [
            dict(value)
            for value in payload.get("validation_findings", ())
            if isinstance(value, dict)
        ]
        session.undo_actions = [
            SpellcheckReviewUndoAction(
                kind=str(value["kind"]),
                issue=self._review_issue_from_payload(value["issue"]),
                before_text_lines=tuple(value.get("before_text_lines", ())),
                dictionary_effect=value.get("dictionary_effect"),
                replacement_effect=value.get("replacement_effect"),
            )
            for value in payload.get("undo_actions", ())
        ]
        session.file_index = int(payload.get("file_index", 0))
        session.subtitle_index = int(payload.get("subtitle_index", 0))
        session.current_issue = self._review_issue_from_payload(payload.get("current_issue"))
        session.recovery_paused = bool(payload.get("paused", False))
        if (
            session.mode == "spellcheck"
            and session.current_issue is not None
            and not session.recovery_paused
        ):
            # A journal may have been created by an older version or before a
            # dictionary was updated. Rebuild the displayed issue using the
            # current shared lookup rules rather than trusting stale UI data.
            session.current_issue = None
            self._advance_spellcheck_review(session)
        return session

    def clear_gui_review_session(self) -> None:
        """Remove the recoverable GUI checkpoint after an explicit discard."""
        try:
            self.gui_session_state_path.unlink(missing_ok=True)
        except OSError as error:
            raise RuntimeError("The GUI recovery journal could not be removed.") from error

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------
    def require_capitalization_mode_cli(self) -> bool:
        """Resolve Ask always for one scan, optionally saving the selection."""
        self._capitalization_choice_remembered = False
        if self.options.get("capitalization_mode") in CAPITALIZATION_SCAN_MODES:
            return True
        clear_screen()
        print("Choose a capitalization preference before starting this scan.\n")
        for index, label in enumerate(CAPITALIZATION_SCAN_MODES.values(), start=1):
            print(f"{index}. {label}")
        print("0. Cancel")
        while True:
            raw = input("\nChoice: ").strip()
            if raw == "0":
                return False
            if raw.isdigit() and 1 <= int(raw) <= len(CAPITALIZATION_SCAN_MODES):
                mode = tuple(CAPITALIZATION_SCAN_MODES)[int(raw) - 1]
                remember = input("Remember this choice for future scans? [y/N]: ").strip()
                parsed = parse_bool(remember) if remember else False
                if parsed:
                    self.set_option_value("capitalization_mode", mode)
                    self._capitalization_choice_remembered = True
                else:
                    self.options["capitalization_mode"] = mode
                return True
            print("Choose one of the listed capitalization preferences.")

    def run_formatting_only(self) -> None:
        configured_options = dict(self.options)
        self._capitalization_choice_remembered = False
        try:
            self._run_formatting_only()
        finally:
            remembered = bool(
                getattr(self, "_capitalization_choice_remembered", False)
            )
            selected = self.options.get("capitalization_mode")
            self.options = configured_options
            if remembered:
                self.options["capitalization_mode"] = selected

    def _run_formatting_only(self) -> None:
        if not self.require_capitalization_mode_cli():
            return
        clear_screen()
        print("AUTO-SCAN DISPATCH ACTIVE: Option 1")
        print("Starting automatic subtitle discovery from the script folder...")
        target = self.select_target_folder("Formatting-only cleanup")
        if not target:
            return
        language = self.choose_language()
        if not language:
            return
        ctx = self.load_dictionary_context(language)
        files = self.find_srt_files(target)
        if not files:
            print("No .srt files found.")
            pause()
            return
        if not self.create_backup_if_needed(target, files):
            pause()
            return
        self.validation_findings = []
        changed_files = 0
        for path in files:
            changed = self.format_file(path, ctx, target=target)
            if changed:
                changed_files += 1
        print("\nFormatting-only run complete.")
        print(f"Files scanned: {len(files)}")
        print(f"Files changed: {changed_files}")
        self.review_validation_findings()
        pause()

    def format_file(
        self,
        path: Path,
        ctx: DictionaryContext,
        target: Optional[Path] = None,
    ) -> bool:
        blocks = self.parse_srt(path)
        changed = False
        for block in blocks:
            before = list(block.text_lines)
            block.text_lines = self.format_text_lines(block.text_lines, ctx)
            if block.text_lines != before:
                changed = True
        self.collect_file_validation_findings(path, target or path.parent, blocks)
        if changed:
            self.write_srt(path, blocks)
        return changed

    def format_text_lines(
        self,
        text_lines: List[str],
        ctx: DictionaryContext,
        defer_tracked_substitutions: bool = False,
    ) -> List[str]:
        lines = self.apply_common_error_cleanup(text_lines)
        # After deterministic common-error repair, normalize ellipses so later
        # formatting rules see the final punctuation form rather than treating
        # -- or ... as speaker-break clues.
        if self.options["convert_double_hyphen_and_three_dots_to_ellipsis"]:
            lines = [self.normalize_ellipsis_sequences(line) for line in lines]
        uppercase_source_flags = [self.is_mostly_uppercase_line(line) for line in lines]
        substitution_method = (
            self.apply_untracked_active_substitutions
            if defer_tracked_substitutions
            else self.apply_active_substitutions
        )
        lines = [substitution_method(line, ctx) for line in lines]
        capitalization_mode = self.options.get("capitalization_mode")
        if capitalization_mode not in CAPITALIZATION_SCAN_MODES:
            capitalization_mode = "subtitle"
        if capitalization_mode == "all_caps":
            lines = [self.transform_visible_text(line, str.upper) for line in lines]
        if (
            capitalization_mode == "subtitle"
            and self.options["capitalize_lowercase_pronoun_i"]
        ):
            lines = [self.capitalize_pronoun_i(line) for line in lines]
        if self.options["remove_periods_from_abbreviations"]:
            lines = [
                self.normalize_dotted_acronyms(
                    line,
                    ctx,
                    following_line=lines[index + 1] if index + 1 < len(lines) else None,
                )
                for index, line in enumerate(lines)
            ]
        if (
            capitalization_mode == "subtitle"
            and self.options["title_case_bracketed_sound_effects"]
        ):
            lines = [self.title_case_bracketed_sound_effects(line, ctx) for line in lines]
        if capitalization_mode == "subtitle" and self.options["fix_mostly_uppercase_lines"]:
            lines = self.repair_mostly_uppercase_lines(lines, ctx, uppercase_source_flags)
        if capitalization_mode == "subtitle":
            lines = self.restore_multiword_name_casing_in_lines(lines, ctx)
        if self.options["detect_dropped_speaker_breaks"]:
            lines = self.detect_dropped_speaker_breaks_in_lines(lines)
        if self.options["adjust_subtitle_line_count"]:
            lines = self.reflow_subtitle_lines(lines)
        if capitalization_mode == "subtitle":
            lines = [self.restore_explicit_acronym_casing(line, ctx) for line in lines]
        return lines

    def apply_common_error_cleanup(self, text_lines: Sequence[str]) -> List[str]:
        lines = list(text_lines)
        if self.options["repair_corrupted_music_symbols"]:
            lines = [
                self.transform_visible_text(
                    line,
                    lambda text: self.replace_known_sequences(
                        text,
                        MUSIC_SYMBOL_REPLACEMENTS,
                    ),
                )
                for line in lines
            ]
        if self.options["repair_common_mojibake_punctuation"]:
            lines = [
                self.transform_visible_text(
                    line,
                    lambda text: self.replace_known_sequences(
                        text,
                        MOJIBAKE_PUNCTUATION_REPLACEMENTS,
                    ),
                )
                for line in lines
            ]
        if self.options["remove_safe_invisible_characters"]:
            lines = [
                self.transform_visible_text(line, lambda text: text.translate(SAFE_INVISIBLE_TRANSLATION))
                for line in lines
            ]
        if self.options["repair_unambiguous_italic_tag_errors"]:
            lines = [self.repair_unambiguous_italic_tags(line) for line in lines]
        if self.options["remove_duplicate_spaces"]:
            lines = [
                self.transform_visible_text(line, lambda text: re.sub(r"[ \t]{2,}", " ", text))
                for line in lines
            ]
        if self.options["fix_spaces_around_punctuation"]:
            lines = [self.transform_visible_text(line, self.fix_punctuation_spacing) for line in lines]
        return lines

    def transform_visible_text(self, line: str, transform) -> str:
        parts = re.split(r"(<[^>]+>)", line)
        return "".join(
            part if HTML_TAG_RE.fullmatch(part) else transform(part)
            for part in parts
        )

    def capitalize_pronoun_i(self, line: str) -> str:
        """Repair lowercase English pronoun I without touching markup or URLs."""
        def repair_text(text: str) -> str:
            parts = re.split(r"((?:https?://|www\.)[^\s<]+)", text, flags=re.IGNORECASE)
            for index in range(0, len(parts), 2):
                part = parts[index]
                part = re.sub(
                    r"(?<![A-Za-z])i(['’])(?i:(m|d|ll|ve))(?![A-Za-z])",
                    lambda match: "I" + match.group(1) + match.group(2).lower(),
                    part,
                )
                parts[index] = re.sub(
                    r"(?<![A-Za-z])i(?![A-Za-z'’]|\.[eE]\.)",
                    "I",
                    part,
                )
            return "".join(parts)

        return self.transform_visible_text(line, repair_text)

    def replace_known_sequences(self, text: str, replacements: Dict[str, str]) -> str:
        for source, destination in replacements.items():
            text = text.replace(source, destination)
        return text

    def fix_punctuation_spacing(self, text: str) -> str:
        text = re.sub(r"[ \t]+([,?!;:])", r"\1", text)
        return re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", text)

    def repair_unambiguous_italic_tags(self, line: str) -> str:
        line = re.sub(r"(?i)<i>\s*</i>", "", line)
        line = re.sub(r"(?i)(?:<i>){2,}", "<i>", line)
        line = re.sub(r"(?i)(?:</i>){2,}", "</i>", line)
        line = re.sub(r"(?i)<i>([^<>]+)<i>(?=\s|$)", r"<i>\1</i>", line)
        return line

    def validate_common_error_text(self, text_lines: Sequence[str]) -> List[str]:
        text = "\n".join(text_lines)
        visible = strip_html_tags(text)
        findings = []
        if visible.count('"') % 2 or visible.count("“") != visible.count("”"):
            findings.append("Unmatched double quote")
        for opening, closing, label in (
            ("[", "]", "square bracket"),
            ("(", ")", "parenthesis"),
            ("{", "}", "curly bracket"),
        ):
            if visible.count(opening) != visible.count(closing):
                findings.append(f"Unmatched {label}")
        if len(re.findall(r"(?i)<i>", text)) != len(re.findall(r"(?i)</i>", text)):
            findings.append("Unclosed italic tag")
        if re.search(r"[!?]{4,}", visible):
            findings.append("Repeated punctuation")
        return findings

    def collect_file_validation_findings(
        self,
        path: Path,
        target: Path,
        blocks: Sequence[SubtitleBlock],
        findings: Optional[List[dict]] = None,
    ) -> None:
        if not self.options["report_suspicious_text"]:
            return
        if findings is None:
            findings = getattr(self, "validation_findings", None)
            if findings is None:
                findings = []
                self.validation_findings = findings
        try:
            relative_path = str(path.relative_to(target))
        except ValueError:
            relative_path = str(path)
        findings[:] = [item for item in findings if item.get("file") != relative_path]
        for position, block in enumerate(blocks, start=1):
            for issue in self.validate_common_error_text(block.text_lines):
                if issue == "Unmatched double quote":
                    continue
                findings.append({
                    "file": relative_path,
                    "subtitle": block.index if block.has_index else position,
                    "issue": issue,
                    "text": " / ".join(block.text_lines),
                })
        complete_text = "\n".join(
            "\n".join(block.text_lines)
            for block in blocks
        )
        visible = strip_html_tags(complete_text)
        if visible.count('"') % 2 or visible.count("“") != visible.count("”"):
            findings.append({
                "file": relative_path,
                "subtitle": "file",
                "issue": "Unmatched double quote",
                "text": "The complete file contains unbalanced quotation marks.",
            })

    def review_validation_findings(self) -> None:
        findings = getattr(self, "validation_findings", [])
        if not self.options["report_suspicious_text"]:
            return
        if not findings:
            print("Validation report: no suspicious text found.")
            return
        print(f"Validation report: {len(findings)} suspicious item(s) found.")
        print("These items were reported only; validation did not edit them.")
        for item in findings[:10]:
            print(
                f"- {item['file']} | Subtitle {item['subtitle']} | "
                f"{item['issue']}: {item['text']}"
            )
        if len(findings) > 10:
            print(f"- ...and {len(findings) - 10} more item(s).")

    def normalize_ellipsis_sequences(self, line: str) -> str:
        line = re.sub(r"\.{3,}", "…", line)
        line = re.sub(r"-{2,}", "…", line)
        return line

    def apply_substitutions(self, line: str, substitutions: Dict[str, str]) -> str:
        result = line
        # Longest first prevents a shorter substitution from damaging a longer one.
        for source_key, replacement in sorted(substitutions.items(), key=lambda kv: len(kv[0]), reverse=True):
            source = source_key
            if not source:
                continue
            escaped = re.escape(source)
            if re.fullmatch(r"[A-Za-z0-9_'’\-]+", source):
                pattern = re.compile(rf"(?<![A-Za-z0-9_'’\-]){escaped}(?![A-Za-z0-9_'’\-])", re.IGNORECASE)
            else:
                pattern = re.compile(escaped, re.IGNORECASE)
            result = pattern.sub(replacement, result)
        return result

    def apply_session_substitutions(self, line: str) -> str:
        return self.apply_substitutions(line, self.current_session_substitutions)

    def apply_active_substitutions(self, line: str, ctx: DictionaryContext) -> str:
        """Apply session substitutions before persistent dictionary substitutions."""
        return self.apply_substitutions(self.apply_session_substitutions(line), ctx.substitutions)

    def substitution_undo_action(
        self,
        source: str,
        replacement: str,
        effect_name: str,
    ) -> Optional[dict]:
        """Return the newest still-active undo action that owns a rule."""
        source_key = source.casefold()
        for action in reversed(self.undo_stack):
            if action.get("type") != "replace_word":
                continue
            effect = action.get(effect_name)
            if not isinstance(effect, dict):
                continue
            if effect.get("input", "").casefold() != source_key:
                continue
            if action.get("to") == replacement:
                return action
        return None

    def apply_untracked_active_substitutions(self, line: str, ctx: DictionaryContext) -> str:
        """Apply rules loaded before this run, deferring rules with undo owners."""
        session_rules = {
            source: replacement
            for source, replacement in self.current_session_substitutions.items()
            if self.substitution_undo_action(source, replacement, "session_substitution") is None
        }
        persistent_rules = {
            source: replacement
            for source, replacement in ctx.substitutions.items()
            if self.substitution_undo_action(source, replacement, "persistent_substitution") is None
        }
        return self.apply_substitutions(
            self.apply_substitutions(line, session_rules),
            persistent_rules,
        )

    def apply_active_substitutions_to_block(
        self,
        block: SubtitleBlock,
        ctx: DictionaryContext,
        rel_file: str,
        block_index: int,
    ) -> None:
        """Apply active rules and attach automatic changes to their undo action."""
        rule_groups = (
            (self.current_session_substitutions, "session_substitution"),
            (ctx.substitutions, "persistent_substitution"),
        )
        for substitutions, effect_name in rule_groups:
            for source, replacement in sorted(
                substitutions.items(), key=lambda item: len(item[0]), reverse=True
            ):
                action = self.substitution_undo_action(source, replacement, effect_name)
                if action is None:
                    # Pre-existing rules were already applied by the formatting
                    # pass and do not belong to an undoable action in this run.
                    continue
                changes = action.setdefault("propagated_changes", [])
                if any(
                    existing.get("file") == rel_file
                    and existing.get("subtitle_index") == block_index
                    for existing in changes
                ):
                    continue
                before = list(block.text_lines)
                after = [
                    self.apply_substitutions(line, {source: replacement})
                    for line in before
                ]
                if after == before:
                    continue
                block.text_lines = after
                change = {
                    "file": rel_file,
                    "subtitle_index": block_index,
                    "before_text_lines": before,
                    "after_text_lines": after,
                }
                changes.append(change)

    def normalize_dotted_acronyms(
        self,
        line: str,
        ctx: Optional[DictionaryContext] = None,
        following_line: Optional[str] = None,
    ) -> str:
        def repl(match: re.Match) -> str:
            text = match.group(0)
            letters = re.sub(r"[^A-Za-z]", "", text)
            if len(letters) < 2:
                return text
            candidate = letters.upper()
            acronym_set = ctx.acronym_set if ctx is not None else COMMON_ACRONYMS
            preferred = preferred_acronym_casing(candidate, acronym_set)
            if preferred is None and ctx is not None:
                preferred_name = ctx.name_map.get(dictionary_key(candidate))
                if preferred_name and preferred_name.isalpha() and preferred_name.isupper():
                    preferred = preferred_name
            if preferred is None:
                return text

            terminal_period = ""
            if text.endswith("."):
                is_plural = preferred.endswith("s") and preferred[:-1].casefold() in {
                    value.casefold() for value in acronym_set
                }
                remaining = line[match.end() :]
                at_sentence_end = bool(re.fullmatch(r"[\s\"'”’\)\]}]*", remaining))
                if at_sentence_end and following_line is not None:
                    next_letter = re.search(r"[A-Za-z]", strip_html_tags(following_line))
                    if next_letter and next_letter.group(0).islower():
                        at_sentence_end = False
                if is_plural or at_sentence_end:
                    terminal_period = "."
            return preferred + terminal_period
        return DOTTED_ACRONYM_RE.sub(repl, line)

    def authoritative_name_casing(
        self,
        token: str,
        ctx: DictionaryContext,
    ) -> Optional[str]:
        lower = dictionary_key(token)
        if lower in ctx.name_map:
            return ctx.name_map[lower]

        possessive = re.fullmatch(r"(.+)(['’])[sS]", token)
        if possessive and dictionary_key(possessive.group(1)) in ctx.name_map:
            return ctx.name_map[dictionary_key(possessive.group(1))] + possessive.group(2) + "s"

        for suffix in ("ing", "ed", "es", "s"):
            if lower.endswith(suffix) and lower[: -len(suffix)] in ctx.name_map:
                return ctx.name_map[lower[: -len(suffix)]] + suffix
        return None

    def restore_explicit_acronym_casing(
        self, line: str, ctx: DictionaryContext
    ) -> str:
        """Apply canonical casing from explicit User/Universe acronym lists."""
        explicit = ctx.explicit_acronyms
        if not explicit:
            return line

        def restore(text: str) -> str:
            def replace(match: re.Match) -> str:
                token = match.group(0)
                if token.casefold() == "us":
                    return token
                preferred = preferred_acronym_casing(token, explicit)
                return preferred if preferred is not None else token

            return WORD_RE.sub(replace, text)

        return self.transform_visible_text(line, restore)

    def restore_multiword_name_casing(
        self,
        text: str,
        ctx: DictionaryContext,
    ) -> str:
        return self.restore_multiword_name_casing_in_lines([text], ctx)[0]

    def restore_multiword_name_casing_in_lines(
        self,
        lines: Sequence[str],
        ctx: DictionaryContext,
    ) -> List[str]:
        result = "\n".join(lines)
        multiword_names = [value for value in ctx.name_map.values() if re.search(r"\s", value)]
        for preferred in sorted(multiword_names, key=len, reverse=True):
            preferred_tokens = [match.group(0) for match in WORD_RE.finditer(preferred)]
            if len(preferred_tokens) < 2:
                continue
            pattern = re.compile(
                r"(?<![A-Za-z0-9_'’\-])"
                + r"\s+".join(re.escape(token) for token in preferred_tokens)
                + r"(?![A-Za-z0-9_'’\-])",
                re.IGNORECASE,
            )

            def restore_match(match: re.Match) -> str:
                token_index = 0

                def restore_token(_token_match: re.Match) -> str:
                    nonlocal token_index
                    replacement = preferred_tokens[token_index]
                    token_index += 1
                    return replacement

                return WORD_RE.sub(restore_token, match.group(0))

            result = pattern.sub(restore_match, result)
        return result.split("\n")

    def title_case_bracketed_sound_effects(
        self,
        line: str,
        ctx: Optional[DictionaryContext] = None,
    ) -> str:
        def repl(match: re.Match) -> str:
            inner = match.group(1).strip()
            words = re.split(r"(\s+|[-/])", inner)
            word_positions = [i for i, part in enumerate(words) if re.search(r"[A-Za-z]", part)]
            first = word_positions[0] if word_positions else None
            last = word_positions[-1] if word_positions else None
            for i in word_positions:
                part = words[i]
                lower = part.casefold()
                authoritative = self.authoritative_name_casing(part, ctx) if ctx is not None else None
                if authoritative is not None:
                    words[i] = authoritative
                elif i not in (first, last) and lower in LOWERCASE_WORDS:
                    words[i] = lower
                elif (
                    part.upper() == part
                    and len(part) <= 4
                    and part.isalpha()
                    and part.upper() in (ctx.acronym_set if ctx is not None else COMMON_ACRONYMS)
                ):
                    words[i] = part.upper()
                else:
                    words[i] = part[:1].upper() + part[1:].lower()
            titled = "".join(words).strip()
            if ctx is not None:
                titled = self.restore_multiword_name_casing(titled, ctx)
            return "[" + titled + "]"
        return BRACKETED_RE.sub(repl, line)

    def detect_dropped_speaker_breaks_in_lines(self, lines: Sequence[str]) -> List[str]:
        """Detect lost speaker breaks using complete wrapped dialogue segments."""
        result: List[str] = []
        paragraph: List[str] = []

        def flush() -> None:
            nonlocal paragraph
            if not paragraph:
                return
            joined = " ".join(part.strip() for part in paragraph if part.strip())
            detected = self.detect_dropped_speaker_breaks(joined)
            if detected != [joined]:
                result.extend(detected)
            else:
                result.extend(paragraph)
            paragraph = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                flush()
                result.append(line)
                continue
            if is_sound_effect_line(line):
                flush()
                result.append(line)
                continue
            if is_speaker_line(line):
                flush()
                if stripped.endswith(":"):
                    result.append(line)
                else:
                    paragraph.append(line)
                continue
            paragraph.append(line)
        flush()
        return result

    def detect_dropped_speaker_breaks(self, line: str) -> List[str]:
        if "http://" in line or "https://" in line or "www." in line:
            return [line]
        if re.search(
            r"\b(?:[A-Za-z0-9-]+\.)+(?:com|org|net|edu|gov|mil|int|io|co|tv)\b",
            line,
            re.IGNORECASE,
        ):
            return [line]
        stripped = line.strip()
        if not stripped:
            return [line]
        parts = []
        start = 0
        i = 0
        while i < len(line) - 1:
            ch = line[i]
            nxt = line[i + 1]
            if ch in ".?!" and self.is_likely_dropped_break(line, i):
                split_at = i + 1
                parts.append(line[start:split_at].strip())
                if nxt == "-":
                    start = split_at + 1
                else:
                    start = split_at
                i = start
                continue
            i += 1
        if not parts:
            return [line]
        parts.append(line[start:].strip())
        cleaned = [p.strip(" -") for p in parts if p.strip(" -")]
        if len(cleaned) < 2:
            return [line]
        if stripped.startswith("-"):
            return ["- " + cleaned[0]] + ["- " + p for p in cleaned[1:]]
        if is_speaker_line(line):
            return [cleaned[0]] + ["- " + p for p in cleaned[1:]]
        return ["- " + p for p in cleaned]

    def is_likely_dropped_break(self, line: str, punct_index: int) -> bool:
        next_part = line[punct_index + 1 :]
        if not next_part:
            return False
        if next_part.startswith(" "):
            return False
        if len(next_part) >= 1 and next_part[0].isdigit():
            return False
        if next_part.startswith("."):
            return False
        if line[punct_index] == ".":
            if punct_index > 0 and line[punct_index - 1] == ".":
                return False
            if (
                punct_index > 0
                and line[punct_index - 1].isalpha()
                and re.match(r"[A-Za-z]\.", next_part)
            ):
                return False
            if re.search(r"[A-Za-z]{1,3}$", line[:punct_index]) and re.match(
                r"[A-Z](?:[.,:]|$)", next_part
            ):
                return False
        # Punctuation immediately followed by a closing quote/bracket is normally the
        # end of quoted dialogue, not a missing speaker break.  Being conservative here
        # is safer than splitting a quote into a fake second speaker line.
        if next_part[0] in "\"'”’)]}":
            return False
        before = line[:punct_index]
        token_match = re.search(r"([A-Za-z](?:[A-Za-z]|\.){0,8})$", before)
        token = token_match.group(1).casefold().rstrip(".") if token_match else ""
        if token in ABBREVIATION_WORDS:
            return False
        if re.search(r"(?:[A-Za-z]\.){2,}$", before + line[punct_index]):
            return False
        # Break if immediately followed by uppercase/new speaker, or hyphen plus text.
        return bool(re.match(r"-?[A-Z0-9'\"“‘]", next_part))

    def is_mostly_uppercase_line(self, line: str) -> bool:
        if is_sound_effect_line(line):
            return False
        visible_without_annotations = BRACKETED_RE.sub("", strip_html_tags(line))
        letters = [ch for ch in visible_without_annotations if ch.isalpha()]
        if not letters:
            return False
        return sum(1 for ch in letters if ch.isupper()) / len(letters) > 0.80

    def repair_mostly_uppercase_lines(
        self,
        lines: List[str],
        ctx: DictionaryContext,
        force_uppercase: Optional[Sequence[bool]] = None,
    ) -> List[str]:
        repaired_lines: List[str] = []
        sentence_start = True
        for index, line in enumerate(lines):
            if not line.strip():
                repaired_lines.append(line)
                sentence_start = True
                continue
            stripped_visible = strip_html_tags(line).lstrip()
            begins_quoted_phrase = bool(stripped_visible.startswith(("\"", "“", "‘")))
            initial_start = True if (is_speaker_line(line) or begins_quoted_phrase) else sentence_start
            repaired, sentence_start = self.repair_mostly_uppercase_line(
                line,
                ctx,
                initial_start_sentence=initial_start,
                force=bool(force_uppercase and index < len(force_uppercase) and force_uppercase[index]),
            )
            repaired_lines.append(repaired)
            if is_sound_effect_line(line) or (
                is_speaker_line(line) and line.strip().endswith(":")
            ):
                sentence_start = True
        return repaired_lines

    def repair_mostly_uppercase_line(
        self,
        line: str,
        ctx: DictionaryContext,
        initial_start_sentence: bool = True,
        force: bool = False,
    ) -> Tuple[str, bool]:
        if is_sound_effect_line(line):
            return line, True
        if not force and not self.is_mostly_uppercase_line(line):
            return line, self.line_ends_sentence(line)
        if force and not re.search(r"[A-Za-z]", BRACKETED_RE.sub("", strip_html_tags(line))):
            return line, self.line_ends_sentence(line)

        tokens = re.findall(
            r"<[^>]+>|\[[^\]]+\]|[A-Za-z]{1,3}\.(?:[A-Za-z]\.)*[A-Za-z]\.?(?![A-Za-z])|"
            r"[A-Za-z]+(?:['’][A-Za-z]+)?|\s+|.",
            line,
        )
        result: List[str] = []
        start_sentence = initial_start_sentence
        for token in tokens:
            if (
                HTML_TAG_RE.fullmatch(token)
                or BRACKETED_RE.fullmatch(token)
                or DOTTED_FORM_RE.fullmatch(token)
                or token.isspace()
                or not re.search(r"[A-Za-z]", token)
            ):
                result.append(token)
                if token in ".?!":
                    start_sentence = True
                continue
            lower = token.casefold()
            upper_clean = re.sub(r"[^A-Za-z0-9]", "", token).upper()
            authoritative = self.authoritative_name_casing(token, ctx)
            authoritative_acronym = preferred_acronym_casing(token, ctx.acronym_set)
            if authoritative is not None:
                fixed = authoritative
            elif authoritative_acronym is not None and token.casefold() != "us":
                fixed = authoritative_acronym
            elif lower == "i":
                fixed = "I"
            elif re.fullmatch(r"i['’](?:m|d|ll|ve)", lower):
                fixed = "I" + token[1:].lower()
            elif upper_clean == "US":
                fixed = "us"
            elif lower in LOWERCASE_WORDS and not start_sentence:
                fixed = lower
            else:
                fixed = lower.capitalize() if start_sentence else lower
            result.append(fixed)
            start_sentence = False
        repaired = "".join(result)
        repaired = self.restore_multiword_name_casing(repaired, ctx)
        repaired = self.apply_us_context_rules(repaired)
        repaired = re.sub(
            r"(?<![A-Za-z0-9])(\d{1,2}(?::\d{2})?\s*)(am|pm)(?![A-Za-z])",
            lambda match: match.group(1) + match.group(2).upper(),
            repaired,
            flags=re.IGNORECASE,
        )
        # The first word is capitalized only when this line truly begins a sentence.
        # A wrapped continuation line such as "A DENT..." must become "a dent...".
        if initial_start_sentence or is_speaker_line(line):
            repaired = re.sub(
                r"(^|[-]\s+)([a-z])",
                lambda m: m.group(1) + m.group(2).upper(),
                repaired,
                count=1,
            )
        return repaired, start_sentence

    @staticmethod
    def line_ends_sentence(line: str) -> bool:
        visible = strip_html_tags(line).strip()
        return bool(re.search(r"[.!?][\"'”’)]*\s*$", visible))

    def apply_us_context_rules(self, text: str) -> str:
        protected_spans: List[Tuple[int, int]] = []
        lower_text = text.casefold()
        for phrase in US_PRONOUN_PATTERNS:
            for match in re.finditer(re.escape(phrase.casefold()), lower_text):
                protected_spans.append(match.span())

        def overlaps_protected(start: int, end: int) -> bool:
            return any(not (end <= a or start >= b) for a, b in protected_spans)

        result = text
        # Apply longer patterns first.
        for pattern in sorted(UNITED_STATES_CONTEXT_PATTERNS, key=len, reverse=True):
            lower_pattern = pattern.replace("US", "us")
            regex = re.compile(r"(?<![A-Za-z])" + re.escape(lower_pattern) + r"(?![A-Za-z])", re.IGNORECASE)
            def repl(match: re.Match, pat: str = pattern) -> str:
                if overlaps_protected(match.start(), match.end()):
                    return match.group(0)
                replacement = pat
                # Preserve sentence-start The/To/From capitalization where natural.
                if match.group(0)[:1].isupper():
                    replacement = replacement[:1].upper() + replacement[1:]
                return replacement
            result = regex.sub(repl, result)
        return result

    def reflow_subtitle_lines(self, lines: List[str]) -> List[str]:
        preferred = int(self.options["preferred_max_chars_per_line"])
        acceptable = int(self.options["acceptable_max_chars_per_line"])
        max_lines = int(self.options["preferred_max_visible_dialogue_lines"])
        result: List[str] = []
        paragraph: List[str] = []

        def flush() -> None:
            nonlocal paragraph, result
            if not paragraph:
                return
            text = " ".join(part.strip() for part in paragraph if part.strip())
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                paragraph = []
                return
            result.extend(self.wrap_dialogue_text(text, preferred, acceptable, max_lines))
            paragraph = []

        for line in lines:
            if not line.strip():
                flush()
                continue
            if is_sound_effect_line(line):
                flush()
                result.append(line.strip())
            elif self.options["preserve_speaker_clarity"] and is_speaker_line(line):
                flush()
                result.extend(self.wrap_speaker_line(line.strip(), preferred, acceptable))
            else:
                paragraph.append(line)
        flush()
        return result

    def wrap_dialogue_text(self, text: str, preferred: int, acceptable: int, max_lines: int) -> List[str]:
        # A single line may exceed the preferred target up to the acceptable maximum
        # when doing so avoids creating another visible line.
        if len(text) <= acceptable:
            return [text]

        fallback = textwrap.wrap(
            text,
            width=preferred,
            break_long_words=False,
            break_on_hyphens=False,
        )

        if max_lines == 2 and len(text) <= acceptable * 2:
            balanced = self.best_two_line_wrap(text, acceptable)
            if balanced:
                return balanced

        if len(fallback) > max_lines and acceptable > preferred:
            wider = textwrap.wrap(
                text,
                width=acceptable,
                break_long_words=False,
                break_on_hyphens=False,
            )
            if len(wider) <= max_lines or len(wider) < len(fallback):
                fallback = wider
        return fallback

    def best_two_line_wrap(self, text: str, acceptable: int) -> Optional[List[str]]:
        candidates: List[Tuple[int, int, List[str], bool]] = []
        for match in re.finditer(r"\s+", text):
            left = text[: match.start()].strip()
            right = text[match.end() :].strip()
            if not left or not right:
                continue
            if len(left) > acceptable or len(right) > acceptable:
                continue
            imbalance = abs(len(left) - len(right))
            sentence_break = bool(re.search(r"[.!?][\"'”’)]*$", left))
            candidates.append((imbalance, max(len(left), len(right)), [left, right], sentence_break))
        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]))
        best = candidates[0]
        if self.options["prefer_sentence_ending_line_breaks_when_reasonably_balanced"]:
            sentence_candidates = [item for item in candidates if item[3]]
            if sentence_candidates:
                sentence_candidates.sort(key=lambda item: (item[0], item[1]))
                sentence_best = sentence_candidates[0]
                reasonable_limit = max(12, best[0] + 8)
                if sentence_best[0] <= reasonable_limit:
                    best = sentence_best
        return best[2]

    def try_sentence_break_wrap(self, text: str, preferred: int, acceptable: int, max_lines: int, fallback: List[str]) -> List[str]:
        if max_lines != 2:
            return fallback
        if len(text) <= preferred or len(text) > acceptable * 2:
            return fallback
        candidates = [m.end() for m in re.finditer(r"[.!?]\s+", text)]
        if not candidates:
            return fallback
        best = None
        best_score = 10**9
        for idx in candidates:
            left = text[:idx].strip()
            right = text[idx:].strip()
            if len(left) <= acceptable and len(right) <= acceptable:
                score = abs(len(left) - len(right))
                if score < best_score:
                    best = [left, right]
                    best_score = score
        return best if best else fallback

    def wrap_speaker_line(self, line: str, preferred: int, acceptable: int) -> List[str]:
        if len(line) <= acceptable:
            return [line]
        if line.startswith("-"):
            marker = "- "
            content = line[1:].strip()
        else:
            match = re.match(r"^([^:]{1,45}:\s+)(.*)$", line)
            if not match:
                return textwrap.wrap(line, width=acceptable, break_long_words=False, break_on_hyphens=False)
            marker, content = match.group(1), match.group(2)
        subsequent_indent = " " * len(marker)
        return textwrap.wrap(
            content,
            width=preferred,
            initial_indent=marker,
            subsequent_indent=subsequent_indent,
            break_long_words=False,
            break_on_hyphens=False,
        )

    # ------------------------------------------------------------------
    # Spellcheck
    # ------------------------------------------------------------------
    def run_spellcheck(self, use_universe: bool) -> None:
        # Recovery uses the options captured when the session began. Restore the
        # currently configured options when this run returns to the main menu.
        configured_options = dict(self.options)
        self._capitalization_choice_remembered = False
        try:
            self._run_spellcheck(use_universe)
        finally:
            remembered = bool(
                getattr(self, "_capitalization_choice_remembered", False)
            )
            selected = self.options.get("capitalization_mode")
            self.options = configured_options
            if remembered:
                self.options["capitalization_mode"] = selected

    def _run_spellcheck(self, use_universe: bool) -> None:
        state = self.load_session_state()
        resume_mode = None
        if state.get("session_active") and not state.get("scan_completed"):
            resume_mode = self.prompt_aborted_session()
            if resume_mode == "back":
                return
            if resume_mode == "new_scan":
                self.abandon_recovered_session(state)
                state = {}
                resume_mode = None
        if resume_mode in {"resume", "fresh_keep", "fresh_discard"}:
            recovered = self.configure_recovered_session(state, resume_mode)
            if recovered is None:
                print("The saved session does not contain a valid target folder.")
                pause()
                return
            target = recovered["target"]
            language = recovered["language"]
            universe = recovered["universe"]
            mode = recovered["mode"]
            start_file = recovered["start_file"]
            start_index = recovered["start_index"]
        else:
            if not self.require_capitalization_mode_cli():
                return
            action_label = (
                "Spellcheck with optional universe dictionary and formatting correction"
                if use_universe
                else "Standard spellcheck with formatting correction"
            )
            target = self.select_target_folder(action_label)
            if not target:
                return
            language = self.choose_language()
            if not language:
                return
            if use_universe:
                proceed, universe = self.choose_spellcheck_universe()
                if not proceed:
                    return
            else:
                universe = None
            mode = "spellcheck_with_universe" if universe else "spellcheck_standard"
            start_file = None
            start_index = 0
            self.current_session_ignores = set()
            self.current_session_substitutions = {}
            self.undo_stack = []
            self.block_ignores = set()

        if not target.exists() or not target.is_dir():
            print("The target folder from the saved session no longer exists.")
            pause()
            return
        files = self.find_srt_files(target)
        if not files:
            print("No .srt files found.")
            pause()
            return

        manifest = self.build_manifest(target, files)
        if resume_mode == "resume":
            differences = self.manifest_differences(state.get("file_manifest", []), manifest)
            if differences:
                recovery_choice = self.prompt_manifest_drift(differences)
                if recovery_choice == "back":
                    return
                resume_mode = "fresh_keep"
                self.configure_recovered_session(state, resume_mode)
                start_file = None
                start_index = 0

        if not self.create_backup_if_needed(target, files):
            pause()
            return

        ctx = self.load_dictionary_context(language, universe)
        self.validation_findings = []
        saved_completed = state.get("completed_files", [])
        completed_files = (
            {value for value in saved_completed if isinstance(value, str)}
            if resume_mode == "resume" and isinstance(saved_completed, list)
            else set()
        )
        session_state = {
            "session_active": True,
            "scan_completed": False,
            "mode": mode,
            "base_language": language,
            "universe": universe,
            "target_root": str(target),
            "recursive": bool(self.options["scan_folders_recursively"]),
            "started_at": state.get("started_at", now_iso()) if resume_mode == "resume" else now_iso(),
            "options_snapshot": self.options_snapshot(),
            "file_manifest": manifest,
            "completed_files": sorted(completed_files),
            "current_file": start_file,
            "current_subtitle_index": start_index,
            "current_word": None,
            "session_ignore_words": sorted(self.current_session_ignores),
            "session_substitutions": self.current_session_substitutions,
            "undo_stack": self.undo_stack,
        }
        self.save_session_state(session_state)
        self.log_event({"type": "spellcheck_started", "mode": mode, "target_root": str(target), "universe": universe})

        quit_requested = False
        files_scanned = 0
        files_changed = 0
        for file_number, path in enumerate(files, start=1):
            rel = str(path.relative_to(target))
            if rel in completed_files:
                continue
            file_start_index = start_index if start_file == rel else 0
            session_state["current_file"] = rel
            session_state["current_subtitle_index"] = file_start_index
            self.save_session_state(session_state)
            changed, quit_requested, last_index = self.spellcheck_file(
                path,
                target,
                ctx,
                file_start_index,
                session_state,
                file_number=file_number,
                total_files=len(files),
            )
            self.refresh_manifest_entry(session_state["file_manifest"], target, path)
            if quit_requested:
                session_state["current_file"] = rel
                session_state["current_subtitle_index"] = last_index
                session_state["session_ignore_words"] = sorted(self.current_session_ignores)
                session_state["session_substitutions"] = self.current_session_substitutions
                session_state["undo_stack"] = self.undo_stack
                self.save_session_state(session_state)
                print("Spellcheck stopped. Session state was saved for recovery.")
                self.review_validation_findings()
                pause()
                return
            completed_files.add(rel)
            session_state["completed_files"] = sorted(completed_files)
            session_state["current_file"] = None
            session_state["current_subtitle_index"] = 0
            session_state["current_word"] = None
            self.sync_session_choices(session_state)
            self.save_session_state(session_state)
            self.log_event({"type": "file_completed", "file": rel})
            files_scanned += 1
            if changed:
                files_changed += 1

        session_state["session_active"] = False
        session_state["scan_completed"] = True
        session_state["current_file"] = None
        session_state["current_subtitle_index"] = 0
        session_state["current_word"] = None
        session_state["session_ignore_words"] = []
        session_state["session_substitutions"] = {}
        session_state["undo_stack"] = []
        self.save_session_state(session_state)
        self.log_event({"type": "scan_completed", "files_scanned": files_scanned, "files_changed": files_changed})
        print("\nSpellcheck complete.")
        print(f"Files scanned this run: {files_scanned}")
        print(f"Files changed this run: {files_changed}")
        self.review_validation_findings()
        pause()

    def prompt_aborted_session(self) -> str:
        choices = {
            "1": "resume",
            "2": "fresh_keep",
            "3": "fresh_discard",
            "4": "new_scan",
            "5": "back",
        }
        while True:
            clear_screen()
            print("An earlier spellcheck session appears to have ended before completion.\n")
            print("1. Resume session")
            print("2. Restart the same folder and preserve session ignore/substitution choices")
            print("3. Restart the same folder and discard session ignore/substitution choices")
            print("4. Abandon saved session and start the normal new scan")
            print("5. Return to main menu")
            choice = input("\nChoice: ").strip()
            if choice in choices:
                return choices[choice]
            print("Please choose 1, 2, 3, 4, or 5.")
            pause()

    def abandon_recovered_session(self, state: dict) -> None:
        abandoned = dict(state)
        abandoned.update(
            {
                "session_active": False,
                "scan_completed": False,
                "session_abandoned": True,
                "current_file": None,
                "current_subtitle_index": 0,
                "current_word": None,
                "session_ignore_words": [],
                "session_substitutions": {},
                "undo_stack": [],
            }
        )
        self.save_session_state(abandoned)
        self.log_event(
            {
                "type": "spellcheck_abandoned",
                "target_root": state.get("target_root"),
            }
        )

    def configure_recovered_session(self, state: dict, resume_mode: str) -> Optional[dict]:
        raw_target = state.get("target_root")
        if not isinstance(raw_target, str) or not raw_target.strip():
            return None

        self.apply_saved_options(state)
        preserve_choices = resume_mode in {"resume", "fresh_keep"}
        saved_ignores = state.get("session_ignore_words", [])
        self.current_session_ignores = (
            {value.casefold() for value in saved_ignores if isinstance(value, str)}
            if preserve_choices and isinstance(saved_ignores, list)
            else set()
        )
        substitutions = state.get("session_substitutions", {})
        self.current_session_substitutions = (
            {
                key.casefold(): value
                for key, value in substitutions.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            if preserve_choices and isinstance(substitutions, dict)
            else {}
        )
        saved_undo = state.get("undo_stack", [])
        self.undo_stack = list(saved_undo) if resume_mode == "resume" and isinstance(saved_undo, list) else []
        self.block_ignores = set()
        if resume_mode == "resume":
            for action in self.undo_stack:
                if not isinstance(action, dict) or action.get("type") != "block_ignore":
                    continue
                rel_file = action.get("file")
                subtitle_index = action.get("subtitle_index")
                word = action.get("word")
                if isinstance(rel_file, str) and isinstance(subtitle_index, int) and isinstance(word, str):
                    self.block_ignores.add((rel_file, subtitle_index, word.casefold()))

        try:
            start_index = max(0, int(state.get("current_subtitle_index", 0) or 0))
        except (TypeError, ValueError):
            start_index = 0
        language = state.get("base_language")
        if language not in {"american", "british"}:
            language = "american"
        universe = state.get("universe")
        if not isinstance(universe, str) or not universe.strip():
            universe = None
        current_file = state.get("current_file")
        if not isinstance(current_file, str) or not current_file:
            current_file = None
        mode = state.get("mode")
        if mode not in {"spellcheck_standard", "spellcheck_with_universe"}:
            mode = "spellcheck_with_universe" if universe else "spellcheck_standard"
        return {
            "target": Path(raw_target.strip()),
            "language": language,
            "universe": universe,
            "mode": mode,
            "start_file": current_file if resume_mode == "resume" else None,
            "start_index": start_index if resume_mode == "resume" else 0,
        }

    def apply_saved_options(self, state: dict) -> None:
        self.apply_options_snapshot(state.get("options_snapshot", {}))
        recursive = state.get("recursive")
        if isinstance(recursive, bool):
            self.options["scan_folders_recursively"] = recursive

    def apply_options_snapshot(self, snapshot: object) -> None:
        """Apply a validated scan snapshot without persisting temporary choices."""
        if isinstance(snapshot, dict):
            for key, default in DEFAULT_OPTIONS.items():
                value = snapshot.get(key)
                if isinstance(default, bool) and isinstance(value, bool):
                    self.options[key] = value
                elif isinstance(default, int) and not isinstance(value, bool) and isinstance(value, int) and value > 0:
                    self.options[key] = value
                elif (
                    key == "capitalization_mode"
                    and isinstance(value, str)
                    and value in CAPITALIZATION_SCAN_MODES
                ):
                    self.options[key] = value

    def sync_session_choices(self, session_state: dict) -> None:
        session_state["session_ignore_words"] = sorted(self.current_session_ignores)
        session_state["session_substitutions"] = dict(self.current_session_substitutions)
        session_state["undo_stack"] = list(self.undo_stack)

    def options_snapshot(self) -> dict:
        return {key: self.options[key] for key in DEFAULT_OPTIONS}

    def build_manifest(self, target: Path, files: Sequence[Path]) -> List[dict]:
        manifest = []
        for path in files:
            stat = path.stat()
            manifest.append({
                "path": str(path.relative_to(target)),
                "size_bytes": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat(),
                "modified_time_ns": stat.st_mtime_ns,
            })
        return manifest

    def manifest_differences(self, saved_manifest: object, current_manifest: object) -> List[str]:
        if not isinstance(saved_manifest, list) or not isinstance(current_manifest, list):
            return ["The saved file manifest is invalid."]
        saved = {item.get("path"): item for item in saved_manifest if isinstance(item, dict) and isinstance(item.get("path"), str)}
        current = {item.get("path"): item for item in current_manifest if isinstance(item, dict) and isinstance(item.get("path"), str)}
        differences = []
        for path in sorted(saved.keys() - current.keys(), key=str.casefold):
            differences.append(f"Missing file: {path}")
        for path in sorted(current.keys() - saved.keys(), key=str.casefold):
            differences.append(f"New file: {path}")
        for path in sorted(saved.keys() & current.keys(), key=str.casefold):
            before = saved[path]
            after = current[path]
            if "modified_time_ns" in before and "modified_time_ns" in after:
                before_stamp = before.get("modified_time_ns")
                after_stamp = after.get("modified_time_ns")
            else:
                before_stamp = before.get("modified_time")
                after_stamp = after.get("modified_time")
            if before.get("size_bytes") != after.get("size_bytes") or before_stamp != after_stamp:
                differences.append(f"Changed file: {path}")
        return differences

    def prompt_manifest_drift(self, differences: Sequence[str]) -> str:
        while True:
            clear_screen()
            print("The subtitle files no longer match the saved session, so an exact resume is unsafe.\n")
            for message in differences[:10]:
                print(f"- {message}")
            if len(differences) > 10:
                print(f"- ...and {len(differences) - 10} more change(s)")
            print("\n1. Restart from the beginning and preserve session choices")
            print("2. Return to the main menu")
            choice = input("\nChoice: ").strip()
            if choice == "1":
                return "fresh_keep"
            if choice == "2":
                return "back"
            print("Please choose 1 or 2.")
            pause()

    def refresh_manifest_entry(self, manifest: List[dict], target: Path, path: Path) -> None:
        refreshed = self.build_manifest(target, [path])[0]
        for index, item in enumerate(manifest):
            if item.get("path") == refreshed["path"]:
                manifest[index] = refreshed
                return
        manifest.append(refreshed)

    def spellcheck_file(
        self,
        path: Path,
        target: Path,
        ctx: DictionaryContext,
        start_index: int,
        session_state: dict,
        file_number: int = 1,
        total_files: int = 1,
    ) -> Tuple[bool, bool, int]:
        blocks = self.parse_srt(path)
        original_text = [list(block.text_lines) for block in blocks]
        rel_file = str(path.relative_to(target))
        progress = ConsoleProgressReporter()
        # Formatting correction first, as required by spellcheck modes.
        for block_index, block in enumerate(blocks):
            progress.update(
                "Preparing",
                file_number,
                total_files,
                block_index + 1,
                len(blocks),
                force=block_index == 0,
            )
            # Rules created during this run are applied separately so their exact
            # automatic edits remain attributable to the action that owns them.
            block.text_lines = self.format_text_lines(
                block.text_lines,
                ctx,
                defer_tracked_substitutions=True,
            )
            self.apply_active_substitutions_to_block(
                block,
                ctx,
                rel_file,
                block_index,
            )

        for i in range(start_index, len(blocks)):
            progress.update(
                "Spellchecking",
                file_number,
                total_files,
                i + 1,
                len(blocks),
                force=i == start_index,
            )
            while True:
                session_state["current_subtitle_index"] = i
                self.save_session_state(session_state)
                # Substitutions can be added interactively after the initial
                # formatting pass. Reapply only active substitutions here so a
                # session/universe/always choice affects the rest of the run.
                self.apply_active_substitutions_to_block(
                    blocks[i],
                    ctx,
                    rel_file,
                    i,
                )
                unknown = self.find_first_unknown_word(blocks[i], ctx, rel_file, i)
                if not unknown:
                    break
                word = unknown["word"]
                session_state["current_word"] = word
                session_state["session_ignore_words"] = sorted(self.current_session_ignores)
                session_state["session_substitutions"] = self.current_session_substitutions
                session_state["undo_stack"] = self.undo_stack
                self.save_session_state(session_state)
                progress.clear()
                action_result = self.prompt_spellcheck_action(
                    path,
                    target,
                    blocks,
                    i,
                    word,
                    ctx,
                    file_number=file_number,
                    total_files=total_files,
                )
                if action_result == "quit":
                    self.collect_file_validation_findings(path, target, blocks)
                    self.write_srt(path, blocks)
                    progress.clear()
                    return blocks_changed(original_text, blocks), True, i
                if action_result == "undo":
                    self.perform_undo(
                        blocks,
                        ctx,
                        rel_file,
                        target=target,
                        session_state=session_state,
                    )
                    self.sync_session_choices(session_state)
                    self.save_session_state(session_state)
                    if session_state.get("undo_recovery_required"):
                        progress.clear()
                        return blocks_changed(original_text, blocks), True, i
                    continue
                self.sync_session_choices(session_state)
                self.save_session_state(session_state)
                # Re-scan current block after any action.
        changed = blocks_changed(original_text, blocks)
        self.collect_file_validation_findings(path, target, blocks)
        if changed:
            self.write_srt(path, blocks)
        progress.clear()
        return changed, False, len(blocks)

    def phrase_covered_token_indexes(
        self,
        visible_text: str,
        tokens: Sequence[dict],
        ctx: DictionaryContext,
    ) -> set:
        covered = set()
        phrase_tokens = []
        for phrase in ctx.phrase_map.values():
            values = [dictionary_key(match.group(0)) for match in WORD_RE.finditer(phrase)]
            if len(values) >= 2:
                phrase_tokens.append(values)
        phrase_tokens.sort(key=len, reverse=True)

        token_values = [dictionary_key(token["word"]) for token in tokens]
        for values in phrase_tokens:
            width = len(values)
            for start in range(0, len(tokens) - width + 1):
                if token_values[start : start + width] != values:
                    continue
                if all(
                    visible_text[tokens[index]["global_end"] : tokens[index + 1]["global_start"]].isspace()
                    for index in range(start, start + width - 1)
                ):
                    covered.update(range(start, start + width))
        return covered

    def find_first_unknown_word(
        self,
        block: SubtitleBlock,
        ctx: DictionaryContext,
        rel_file: str,
        block_index: int,
        *,
        exact_occurrence_ignores: Optional[set] = None,
        block_ignores: Optional[set] = None,
        session_ignores: Optional[set] = None,
    ) -> Optional[dict]:
        visible_lines = [strip_html_tags(line) for line in block.text_lines]
        visible_text = "\n".join(visible_lines)
        tokens = []
        offset = 0
        for line_idx, text in enumerate(visible_lines):
            for match in WORD_RE.finditer(text):
                tokens.append({
                    "word": match.group(0),
                    "line_index": line_idx,
                    "start": match.start(),
                    "end": match.end(),
                    "global_start": offset + match.start(),
                    "global_end": offset + match.end(),
                })
            offset += len(text) + 1

        phrase_covered = self.phrase_covered_token_indexes(visible_text, tokens, ctx)
        active_block_ignores = self.block_ignores if block_ignores is None else block_ignores
        active_session_ignores = (
            self.current_session_ignores
            if session_ignores is None
            else session_ignores
        )
        for token_index, token in enumerate(tokens):
            word = token["word"]
            lower = word.casefold()
            occurrence_key = (
                rel_file,
                block_index,
                token["line_index"],
                token["start"],
                token["end"],
                lower,
            )
            if exact_occurrence_ignores and occurrence_key in exact_occurrence_ignores:
                continue
            if (rel_file, block_index, lower) in active_block_ignores:
                continue
            if token_index in phrase_covered:
                continue
            if ctx.is_known_word(word, active_session_ignores):
                continue
            return {
                "word": word,
                "line_index": token["line_index"],
                "start": token["start"],
                "end": token["end"],
            }
        return None

    def start_spellcheck_review(
        self,
        files: Sequence[Path],
        target: Path,
        ctx: DictionaryContext,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
    ) -> SpellcheckReviewSession:
        """Create a write-free review session and locate its first issue."""
        session = self.create_spellcheck_review(files, target, ctx)
        self.resume_spellcheck_review(
            session, progress_callback=progress_callback
        )
        return session

    def review_changed_files(
        self, session: SpellcheckReviewSession
    ) -> Tuple[Path, ...]:
        """Return prepared files whose encoded contents differ from their baseline."""
        changed = []
        for file_index in sorted(session.prepared_blocks):
            if file_index not in session.source_bytes:
                raise RuntimeError("A prepared subtitle is missing its source baseline.")
            path = session.files[file_index]
            rendered = self.encode_srt(path, session.prepared_blocks[file_index])
            if rendered != session.source_bytes[file_index]:
                changed.append(path)
        return tuple(changed)

    def review_has_changes(self, session: Optional[SpellcheckReviewSession]) -> bool:
        """Report whether a GUI review contains text that has not been saved."""
        return bool(session is not None and self.review_changed_files(session))

    def commit_spellcheck_review(
        self,
        session: SpellcheckReviewSession,
        *,
        create_backups: bool,
    ) -> SpellcheckReviewCommitResult:
        """Atomically commit prepared review text after drift and backup checks."""
        changed_files = self.review_changed_files(session)
        if not changed_files:
            return SpellcheckReviewCommitResult()

        target = session.target.resolve()
        changed_payloads = []
        for path in changed_files:
            try:
                file_index = session.files.index(path)
            except ValueError as error:
                raise RuntimeError("A changed subtitle is not part of this review.") from error
            try:
                path.resolve().relative_to(target)
            except ValueError as error:
                raise RuntimeError(
                    f"Refusing to save a subtitle outside the review folder: {path}"
                ) from error
            baseline = session.source_bytes[file_index]
            try:
                current = path.read_bytes()
            except OSError as error:
                raise RuntimeError(f"Could not re-read {path.name} before saving: {error}") from error
            if current != baseline:
                raise RuntimeError(
                    f"{path.name} changed outside this review; no subtitle files were saved."
                )
            changed_payloads.append((file_index, path, baseline, self.encode_srt(
                path, session.prepared_blocks[file_index]
            )))

        backup_archives = []
        if create_backups:
            groups = self.backup_groups(session.target, session.files)
            for backup_root in sorted(groups, key=lambda value: str(value).casefold()):
                try:
                    backup_path, _created = self.create_backup_archive(
                        backup_root, groups[backup_root]
                    )
                except (OSError, zipfile.BadZipFile) as error:
                    raise RuntimeError(
                        f"Could not create {backup_root / 'backup_subtitles.zip'}; "
                        "no subtitle files were saved."
                    ) from error
                backup_archives.append(backup_path)

        written = []
        try:
            for payload in changed_payloads:
                _file_index, path, _baseline, rendered = payload
                self.atomic_write_bytes(path, rendered)
                written.append(payload)
        except Exception as write_error:
            rollback_errors = []
            for _file_index, path, baseline, _rendered in reversed(written):
                try:
                    self.atomic_write_bytes(path, baseline)
                except Exception as rollback_error:  # pragma: no cover - catastrophic disk failure
                    rollback_errors.append(f"{path.name}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(
                    "Saving failed and one or more earlier files could not be restored: "
                    + "; ".join(rollback_errors)
                ) from write_error
            raise

        for file_index, _path, _baseline, rendered in changed_payloads:
            session.source_bytes[file_index] = rendered
        session.undo_actions.clear()
        return SpellcheckReviewCommitResult(
            changed_files=changed_files,
            backup_archives=tuple(backup_archives),
        )

    def create_spellcheck_review(
        self,
        files: Sequence[Path],
        target: Path,
        ctx: DictionaryContext,
    ) -> SpellcheckReviewSession:
        """Create an unstarted review session for background interfaces."""
        return SpellcheckReviewSession(
            files=tuple(Path(path) for path in files),
            target=Path(target),
            context=ctx,
            options_snapshot=self.options_snapshot(),
        )

    def create_formatting_review(
        self,
        files: Sequence[Path],
        target: Path,
        ctx: DictionaryContext,
    ) -> SpellcheckReviewSession:
        """Create an unstarted write-free formatting review for the GUI."""
        return SpellcheckReviewSession(
            files=tuple(Path(path) for path in files),
            target=Path(target),
            context=ctx,
            options_snapshot=self.options_snapshot(),
            mode="formatting",
        )

    def resume_formatting_review(
        self,
        session: SpellcheckReviewSession,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> SpellcheckReviewSession:
        """Format every cue in memory, retaining an exact resumable cursor."""
        if session.mode != "formatting":
            raise ValueError("This review is not a Formatting-only review.")
        total_files = len(session.files)
        while session.file_index < total_files:
            file_index = session.file_index
            path = session.files[file_index]
            blocks = session.prepared_blocks.get(file_index)
            if blocks is None:
                source = path.read_bytes()
                session.source_bytes[file_index] = source
                blocks = self.parse_srt(path, source)
                session.prepared_blocks[file_index] = blocks
            total_subtitles = len(blocks)
            while session.subtitle_index < total_subtitles:
                if pause_requested is not None and pause_requested():
                    session.current_issue = None
                    raise SpellcheckReviewPaused()
                block_index = session.subtitle_index
                if progress_callback is not None:
                    progress_callback(
                        "Formatting",
                        file_index + 1,
                        total_files,
                        block_index + 1,
                        total_subtitles,
                    )
                block = blocks[block_index]
                block.text_lines = self.format_text_lines(
                    block.text_lines, session.context
                )
                session.subtitle_index += 1
            self.collect_file_validation_findings(
                path,
                session.target,
                blocks,
                findings=session.validation_findings,
            )
            session.file_index += 1
            session.subtitle_index = 0
        session.current_issue = None
        return session

    def resume_spellcheck_review(
        self,
        session: SpellcheckReviewSession,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Continue a paused write-free review session."""
        session.current_issue = None
        return self._advance_spellcheck_review(
            session,
            progress_callback=progress_callback,
            pause_requested=pause_requested,
        )

    def ignore_review_occurrence(
        self,
        session: SpellcheckReviewSession,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Ignore only the selected token position and advance in memory."""
        issue = session.current_issue
        if issue is None:
            return None
        session.ignored_occurrences.add((
            issue.relative_file,
            issue.subtitle_index,
            issue.line_index,
            issue.start,
            issue.end,
            issue.word.casefold(),
        ))
        session.undo_actions.append(SpellcheckReviewUndoAction("occurrence", issue))
        session.current_issue = None
        return self._advance_spellcheck_review(
            session,
            progress_callback=progress_callback,
            pause_requested=pause_requested,
        )

    def ignore_review_word_for_session(
        self,
        session: SpellcheckReviewSession,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Ignore every case-insensitive occurrence for this review only."""
        issue = session.current_issue
        if issue is None:
            return None
        session.ignored_words.add(issue.word.casefold())
        session.undo_actions.append(SpellcheckReviewUndoAction("session", issue))
        session.current_issue = None
        return self._advance_spellcheck_review(
            session,
            progress_callback=progress_callback,
            pause_requested=pause_requested,
        )

    def replace_review_occurrence(
        self,
        session: SpellcheckReviewSession,
        replacement: str,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Replace exactly the selected visible token in memory and advance."""
        return self.replace_review_with_scope(
            session,
            replacement,
            "occurrence",
            progress_callback=progress_callback,
            pause_requested=pause_requested,
        )

    def replace_review_with_scope(
        self,
        session: SpellcheckReviewSession,
        replacement: str,
        scope: str,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Replace the selected token and optionally retain a substitution rule."""
        issue = session.current_issue
        if issue is None:
            return None
        replacement = replacement.strip()
        if not replacement:
            raise ValueError("A replacement cannot be empty.")
        if scope not in {"occurrence", "session", "universe", "always"}:
            raise ValueError("Choose This time, This session, This universe, or Always.")
        if scope == "universe" and not session.context.universe:
            raise ValueError("No Universe Dictionary is active for this review.")
        if scope in {"universe", "always"} and not session.context.is_known_word(
            replacement, session.ignored_words
        ):
            raise ValueError(
                "A persistent replacement must already be present in the selected "
                "dictionary context. Add the replacement word first."
            )
        blocks = session.prepared_blocks.get(issue.file_number - 1)
        if blocks is None or not 0 <= issue.subtitle_index < len(blocks):
            raise RuntimeError("The selected subtitle is no longer available.")
        block = blocks[issue.subtitle_index]
        if not 0 <= issue.line_index < len(block.text_lines):
            raise RuntimeError("The selected subtitle line is no longer available.")
        line = block.text_lines[issue.line_index]
        visible_line = strip_html_tags(line)
        if visible_line[issue.start:issue.end].casefold() != issue.word.casefold():
            raise RuntimeError("The selected word has changed since it was displayed.")
        before_text_lines = tuple(block.text_lines)
        key = issue.word.casefold()
        effect = None
        if scope == "session":
            effect = {
                "scope": scope,
                "input": issue.word,
                "output": replacement,
                "previous_exists": key in session.substitutions,
                "previous_value": session.substitutions.get(key),
                "review_previous_exists": key in session.substitutions,
                "review_previous_value": session.substitutions.get(key),
                "propagated_changes": [],
            }
            session.substitutions[key] = replacement
            self.log_event({
                "type": "session_substitution",
                "from": issue.word,
                "to": replacement,
            })
        elif scope in {"universe", "always"}:
            context = session.context
            target = "universe" if scope == "universe" else "user"
            target_map = (
                context.universe_substitutions
                if target == "universe"
                else context.user_substitutions
            )
            effect = {
                "scope": scope,
                "target": target,
                "universe": context.universe if target == "universe" else None,
                "language": context.language,
                "input": issue.word,
                "output": replacement,
                "previous_exists": key in target_map,
                "previous_value": target_map.get(key),
                "review_previous_exists": key in session.substitutions,
                "review_previous_value": session.substitutions.get(key),
                "propagated_changes": [],
            }
            path = (
                self.universe_dir / context.universe / "substitutions.tsv"
                if target == "universe"
                else self.user_dir / f"{context.language}_substitutions.tsv"
            )
            event = {
                "type": "substitution_add",
                "target": target,
                "input": issue.word,
                "output": replacement,
            }
            if target == "universe":
                event["universe"] = context.universe
            else:
                event["base_language"] = context.language
            self.add_substitution_to_file(path, issue.word, replacement, event)
            target_map[key] = replacement
            context.substitutions[key] = replacement
            session.substitutions[key] = replacement
        block.text_lines[issue.line_index] = replace_visible_span(
            line,
            issue.start,
            issue.end,
            replacement,
        )
        session.undo_actions.append(SpellcheckReviewUndoAction(
            "replacement",
            issue,
            before_text_lines,
            replacement_effect=effect,
        ))
        self.log_event({
            "type": "replace_word",
            "scope": {"occurrence": 1, "session": 2, "universe": 3, "always": 4}[scope],
            "file": issue.relative_file,
            "subtitle_index": issue.subtitle_index,
            "from": issue.word,
            "to": replacement,
        })
        session.current_issue = None
        return self._advance_spellcheck_review(
            session,
            progress_callback=progress_callback,
            pause_requested=pause_requested,
        )

    def replace_review_cue_text(
        self,
        session: SpellcheckReviewSession,
        edited_text: str,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Replace the current cue's dialogue in memory without touching metadata."""
        issue = session.current_issue
        if issue is None:
            return None
        blocks = session.prepared_blocks.get(issue.file_number - 1)
        if blocks is None or not 0 <= issue.subtitle_index < len(blocks):
            raise RuntimeError("The selected subtitle is no longer available.")
        normalized = edited_text.replace("\r\n", "\n").replace("\r", "\n")
        edited_lines = normalized.split("\n")
        if not normalized.strip():
            raise ValueError("Subtitle dialogue cannot be empty.")
        if any(not line.strip() for line in edited_lines):
            raise ValueError("Subtitle dialogue cannot contain a blank line.")
        block = blocks[issue.subtitle_index]
        before_text_lines = tuple(block.text_lines)
        if tuple(edited_lines) == before_text_lines:
            return issue
        block.text_lines = edited_lines
        session.undo_actions.append(SpellcheckReviewUndoAction(
            "cue_edit",
            issue,
            before_text_lines,
        ))
        session.current_issue = None
        return self._advance_spellcheck_review(
            session,
            progress_callback=progress_callback,
            pause_requested=pause_requested,
        )

    def add_review_dictionary_entry(
        self,
        session: SpellcheckReviewSession,
        entry: str,
        *,
        list_name: str,
        target: str,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Persist one GUI word/name/acronym entry and advance the review."""
        issue = session.current_issue
        if issue is None:
            return None
        if list_name not in {"words", "names", "acronyms"}:
            raise ValueError("Choose an accepted word/phrase, name, or acronym.")
        if target not in {"user", "universe"}:
            raise ValueError("Choose either the User or Universe Dictionary.")
        if target == "universe" and not session.context.universe:
            raise ValueError("No Universe Dictionary is active for this review.")

        preferred = " ".join(entry.split())
        if not preferred:
            raise ValueError("Dictionary entry text cannot be empty.")
        entry_tokens = [match.group(0) for match in WORD_RE.finditer(preferred)]
        if not entry_tokens or issue.word.casefold() not in {
            token.casefold() for token in entry_tokens
        }:
            raise ValueError(
                f'The entry must include the selected word "{issue.word}".'
            )
        if list_name == "acronyms":
            preferred = self.validate_acronym_entry(preferred)
            entry_tokens = [preferred]

        blocks = session.prepared_blocks.get(issue.file_number - 1)
        if blocks is None or not 0 <= issue.subtitle_index < len(blocks):
            raise RuntimeError("The selected subtitle is no longer available.")
        block = blocks[issue.subtitle_index]
        if len(entry_tokens) == 1:
            if WORD_RE.fullmatch(preferred) is None:
                raise ValueError("A single-word entry cannot include punctuation or spaces.")
            if dictionary_key(preferred) != dictionary_key(issue.word):
                raise ValueError(
                    "A single-word dictionary entry may change casing only; use "
                    "Edit/Substitute to change its spelling."
                )
        elif not self.phrase_present_in_block(preferred, block):
            raise ValueError("That complete phrase was not found in the current subtitle.")
        if list_name == "names" and len(entry_tokens) == 1:
            if not 0 <= issue.line_index < len(block.text_lines):
                raise RuntimeError("The selected subtitle line is no longer available.")
            visible_line = strip_html_tags(block.text_lines[issue.line_index])
            if dictionary_key(visible_line[issue.start:issue.end]) != dictionary_key(issue.word):
                raise RuntimeError("The selected word has changed since it was displayed.")

        context = session.context
        filename = f"{list_name}.txt"
        if target == "universe":
            path = self.universe_dir / context.universe / filename
            event = {
                "type": "dictionary_add",
                "target": "universe",
                "universe": context.universe,
                "list": list_name,
                "word": preferred,
            }
            target_words = context.universe_words
            target_names = context.universe_names
            target_acronyms = context.universe_acronyms
        else:
            path = self.user_dir / f"{context.language}_{filename}"
            event = {
                "type": "dictionary_add",
                "target": "user",
                "base_language": context.language,
                "list": list_name,
                "word": preferred,
            }
            target_words = context.user_words
            target_names = context.user_names
            target_acronyms = context.user_acronyms

        if not self.add_word_to_file(path, preferred, event):
            raise ValueError("That entry is already present in the selected dictionary.")

        before_text_lines = tuple(block.text_lines)
        if list_name in {"names", "acronyms"}:
            if list_name == "acronyms":
                target_acronyms.add(preferred)
                context.acronym_set.add(preferred)
            else:
                target_names[dictionary_key(preferred)] = preferred
            if len(entry_tokens) > 1:
                block.text_lines = self.restore_multiword_name_casing_in_lines(
                    block.text_lines, context
                )
            else:
                line = block.text_lines[issue.line_index]
                block.text_lines[issue.line_index] = replace_visible_span(
                    line, issue.start, issue.end, preferred
                )
        else:
            target_words.add(dictionary_key(preferred))

        session.undo_actions.append(SpellcheckReviewUndoAction(
            "dictionary_add",
            issue,
            before_text_lines,
            event,
        ))
        session.current_issue = None
        try:
            return self._advance_spellcheck_review(
                session,
                progress_callback=progress_callback,
                pause_requested=pause_requested,
            )
        except SpellcheckReviewPaused:
            raise
        except Exception:
            session.undo_actions.pop()
            block.text_lines = list(before_text_lines)
            self.remove_logged_dictionary_add(event)
            self.remove_dictionary_entry_from_context(event, context)
            self.log_event({
                "type": "undo",
                "undo_type": "dictionary_add",
                "target": event.get("target"),
                "universe": event.get("universe"),
                "base_language": event.get("base_language"),
                "list": event.get("list"),
                "word": event.get("word"),
            })
            session.file_index = issue.file_number - 1
            session.subtitle_index = issue.subtitle_index
            session.current_issue = issue
            raise

    def undo_review_action(
        self,
        session: SpellcheckReviewSession,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Undo the latest GUI review action and return to its occurrence."""
        if not session.undo_actions:
            return session.current_issue
        action = session.undo_actions[-1]
        issue = action.issue
        if action.kind == "replacement" and action.replacement_effect:
            effect = action.replacement_effect
            scope = effect.get("scope")
            key = str(effect.get("input", "")).casefold()
            if scope in {"universe", "always"}:
                self.undo_persistent_substitution(effect, session.context)
                if effect.get("previous_exists"):
                    undo_event = {
                        "type": "substitution_edit",
                        "target": effect.get("target"),
                        "from_input": effect.get("input"),
                        "input": effect.get("input"),
                        "output": effect.get("previous_value"),
                    }
                else:
                    undo_event = {
                        "type": "substitution_remove",
                        "target": effect.get("target"),
                        "input": effect.get("input"),
                    }
                if effect.get("target") == "universe":
                    undo_event["universe"] = effect.get("universe")
                else:
                    undo_event["base_language"] = effect.get("language")
                self.log_event(undo_event)
            if effect.get("review_previous_exists", effect.get("previous_exists")):
                session.substitutions[key] = effect.get(
                    "review_previous_value", effect.get("previous_value")
                )
            else:
                session.substitutions.pop(key, None)
        session.undo_actions.pop()
        if action.kind == "occurrence":
            session.ignored_occurrences.discard((
                issue.relative_file,
                issue.subtitle_index,
                issue.line_index,
                issue.start,
                issue.end,
                issue.word.casefold(),
            ))
        elif action.kind == "session":
            session.ignored_words.discard(issue.word.casefold())
        elif action.kind in {"replacement", "cue_edit"}:
            blocks = session.prepared_blocks.get(issue.file_number - 1)
            if blocks is None or not 0 <= issue.subtitle_index < len(blocks):
                raise RuntimeError("The edited subtitle is no longer available.")
            if action.kind == "replacement" and action.replacement_effect:
                for change in reversed(
                    action.replacement_effect.get("propagated_changes", [])
                ):
                    changed_blocks = session.prepared_blocks.get(
                        int(change.get("file_index", -1))
                    )
                    changed_index = int(change.get("subtitle_index", -1))
                    if changed_blocks is None or not 0 <= changed_index < len(changed_blocks):
                        raise RuntimeError("A propagated subtitle edit is no longer available.")
                    changed_blocks[changed_index].text_lines = list(
                        change.get("before_text_lines", ())
                    )
            blocks[issue.subtitle_index].text_lines = list(action.before_text_lines)
        elif action.kind == "dictionary_add":
            effect = action.dictionary_effect
            if effect is None:
                raise RuntimeError("The dictionary addition cannot be identified for Undo.")
            blocks = session.prepared_blocks.get(issue.file_number - 1)
            if blocks is None or not 0 <= issue.subtitle_index < len(blocks):
                raise RuntimeError("The edited subtitle is no longer available.")
            blocks[issue.subtitle_index].text_lines = list(action.before_text_lines)
            self.remove_logged_dictionary_add(effect)
            self.remove_dictionary_entry_from_context(effect, session.context)
            self.log_event({
                "type": "undo",
                "undo_type": "dictionary_add",
                "target": effect.get("target"),
                "universe": effect.get("universe"),
                "base_language": effect.get("base_language"),
                "list": effect.get("list"),
                "word": effect.get("word"),
            })
        session.file_index = issue.file_number - 1
        session.subtitle_index = issue.subtitle_index
        session.current_issue = None
        return self._advance_spellcheck_review(
            session,
            progress_callback=progress_callback,
            pause_requested=pause_requested,
        )

    def undo_review_ignore(
        self,
        session: SpellcheckReviewSession,
        **kwargs,
    ) -> Optional[SpellcheckIssuePreview]:
        """Backward-compatible name for the generalized GUI review undo."""
        return self.undo_review_action(session, **kwargs)

    @staticmethod
    def _active_review_replacement_actions(
        session: SpellcheckReviewSession,
    ) -> List[SpellcheckReviewUndoAction]:
        """Return the newest active owner for each GUI-created substitution."""
        actions = []
        claimed = set()
        for action in reversed(session.undo_actions):
            effect = action.replacement_effect
            if action.kind != "replacement" or not effect:
                continue
            key = str(effect.get("input", "")).casefold()
            scope = effect.get("scope")
            if not key or scope == "occurrence" or key in claimed:
                continue
            expected = effect.get("output")
            current = session.substitutions.get(key)
            if current == expected:
                actions.append(action)
                claimed.add(key)
        actions.reverse()
        return actions

    def _format_review_text_lines(
        self,
        session: SpellcheckReviewSession,
        text_lines: Sequence[str],
    ) -> List[str]:
        """Format lines while deferring substitutions created during this review."""
        deferred = {}
        for key in session.substitutions:
            if key in session.context.substitutions:
                deferred[key] = session.context.substitutions.pop(key)
        try:
            return self.format_text_lines(
                list(text_lines),
                session.context,
                defer_tracked_substitutions=True,
            )
        finally:
            session.context.substitutions.update(deferred)

    def _apply_review_substitutions_to_block(
        self,
        session: SpellcheckReviewSession,
        block: SubtitleBlock,
        relative_file: str,
        block_index: int,
    ) -> None:
        """Apply GUI-created rules and attach every propagated edit to Undo."""
        owners = {
            str((action.replacement_effect or {}).get("input", "")).casefold(): action
            for action in self._active_review_replacement_actions(session)
        }
        for source, replacement in sorted(
            session.substitutions.items(), key=lambda item: len(item[0]), reverse=True
        ):
            action = owners.get(source.casefold())
            changes = (
                action.replacement_effect.setdefault("propagated_changes", [])
                if action is not None and action.replacement_effect is not None
                else None
            )
            if changes is not None and any(
                value.get("file") == relative_file
                and value.get("subtitle_index") == block_index
                for value in changes
            ):
                continue
            before = list(block.text_lines)
            after = [
                self.apply_substitutions(line, {source: replacement})
                for line in before
            ]
            if after == before:
                continue
            block.text_lines = after
            if changes is not None:
                changes.append({
                    "file": relative_file,
                    "file_index": session.file_index,
                    "subtitle_index": block_index,
                    "before_text_lines": before,
                    "after_text_lines": after,
                })

    def _advance_spellcheck_review(
        self,
        session: SpellcheckReviewSession,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        pause_requested: Optional[Callable[[], bool]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        total_files = len(session.files)
        while session.file_index < total_files:
            file_index = session.file_index
            path = session.files[file_index]
            try:
                relative_file = str(path.relative_to(session.target))
            except ValueError:
                relative_file = path.name

            blocks = session.prepared_blocks.get(file_index)
            if blocks is None:
                source_bytes = path.read_bytes()
                session.source_bytes[file_index] = source_bytes
                blocks = self.parse_srt(path, source_bytes)
                session.prepared_blocks[file_index] = blocks
                total_subtitles = len(blocks)
                for block_index, block in enumerate(blocks):
                    if pause_requested is not None and pause_requested():
                        session.prepared_blocks.pop(file_index, None)
                        session.source_bytes.pop(file_index, None)
                        session.current_issue = None
                        raise SpellcheckReviewPaused()
                    if progress_callback is not None:
                        progress_callback(
                            "Preparing",
                            file_index + 1,
                            total_files,
                            block_index + 1,
                            total_subtitles,
                        )
                    block.text_lines = self._format_review_text_lines(
                        session, block.text_lines
                    )

            total_subtitles = len(blocks)
            while session.subtitle_index < total_subtitles:
                if pause_requested is not None and pause_requested():
                    session.current_issue = None
                    raise SpellcheckReviewPaused()
                block_index = session.subtitle_index
                block = blocks[block_index]
                self._apply_review_substitutions_to_block(
                    session, block, relative_file, block_index
                )
                if progress_callback is not None:
                    progress_callback(
                        "Spellchecking",
                        file_index + 1,
                        total_files,
                        block_index + 1,
                        total_subtitles,
                    )
                unknown = self.find_first_unknown_word(
                    block,
                    session.context,
                    relative_file,
                    block_index,
                    exact_occurrence_ignores=session.ignored_occurrences,
                    block_ignores=set(),
                    session_ignores=session.ignored_words,
                )
                if unknown is None:
                    session.subtitle_index += 1
                    continue
                word = unknown["word"]
                session.current_issue = SpellcheckIssuePreview(
                    path=path,
                    relative_file=relative_file,
                    file_number=file_index + 1,
                    total_files=total_files,
                    subtitle_index=block_index,
                    total_subtitles=total_subtitles,
                    word=word,
                    line_index=unknown["line_index"],
                    start=unknown["start"],
                    end=unknown["end"],
                    suggestions=tuple(session.context.suggestions_for(word)),
                    previous_blocks=tuple(
                        item.render()
                        for item in blocks[max(0, block_index - 2):block_index]
                    ),
                    current_block=block.render(),
                    current_text="\n".join(block.text_lines),
                    timestamp=block.timestamp.strip(),
                    next_blocks=tuple(
                        item.render()
                        for item in blocks[block_index + 1:block_index + 3]
                    ),
                )
                return session.current_issue

            session.file_index += 1
            session.subtitle_index = 0

        session.current_issue = None
        return None

    def find_next_spellcheck_issue(
        self,
        files: Sequence[Path],
        target: Path,
        ctx: DictionaryContext,
        *,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
    ) -> Optional[SpellcheckIssuePreview]:
        """Prepare files in memory and return the first unknown without writing.

        This is the shared boundary used by the GUI preview. It follows the
        same formatting-before-spellcheck order as ``spellcheck_file`` while
        deliberately omitting session persistence, backup creation, logging,
        and disk writes.
        """
        return self.start_spellcheck_review(
            files,
            target,
            ctx,
            progress_callback=progress_callback,
        ).current_issue

    def prompt_spellcheck_action(
        self,
        path: Path,
        target: Path,
        blocks: List[SubtitleBlock],
        block_index: int,
        word: str,
        ctx: DictionaryContext,
        file_number: int = 1,
        total_files: int = 1,
    ) -> str:
        while True:
            clear_screen()
            rel = path.relative_to(target)
            suggestions = ctx.suggestions_for(word)
            print(
                f"Progress: File {file_number} of {total_files} | "
                f"Subtitle {block_index + 1} of {len(blocks)}"
            )
            print(f"File: {rel}\n")
            prev_blocks = blocks[max(0, block_index - 2): block_index]
            next_blocks = blocks[block_index + 1: block_index + 3]
            print("Previous subtitle blocks:")
            print("\n---\n".join(b.render() for b in prev_blocks) if prev_blocks else "(none)")
            print("\nCurrent subtitle block:")
            print(
                highlight_selected_word(
                    blocks[block_index].render(),
                    word,
                    terminal_color_supported(),
                )
            )
            print("\nNext subtitle blocks:")
            print("\n---\n".join(b.render() for b in next_blocks) if next_blocks else "(none)")
            print(f"\nI found the word \"{word}\".")
            print("Would you like to use any of these?\n")
            for i in range(1, 7):
                value = suggestions[i - 1] if i <= len(suggestions) else ""
                print(f"{i} - {value}" if value else f"{i} - (no suggestion)")
            print("_" * 58)
            action_lines = [
                "7 - Edit/Substitute",
                "8 - Ignore",
                "9 - Add word/name/acronym/phrase",
                "S - Search this subtitle line in Google",
                "U - Undo last action",
                "0 - Quit spellcheck",
            ]
            scope_lines = ["Scope:", "1 - This time", "2 - This session", ""]
            if ctx.universe:
                scope_lines.extend(["3 - This universe", "4 - Always"])
            else:
                scope_lines.extend(["", "4 - Always"])
            for action_line, scope_line in zip(action_lines, scope_lines):
                print(f"{action_line:<36}{scope_line}".rstrip())
            print("\nEnter an action alone to choose its scope next, or combine them (example: 81).")
            choice = input("\nChoice: ").strip()
            if choice.casefold() == "u":
                return "undo"
            if choice.casefold() == "s":
                self.search_subtitle_line_in_google(blocks[block_index], word)
                pause()
                continue
            if choice == "0":
                return "quit"
            parsed = self.parse_spellcheck_choice(choice, suggestions, ctx)
            if not parsed:
                print(self.spellcheck_choice_guidance(choice, suggestions, ctx))
                pause()
                continue
            action, scope = parsed
            if action in range(1, 7):
                replacement = suggestions[action - 1]
                self.apply_replacement_action(path, target, blocks, block_index, word, replacement, scope, ctx, action_name="suggestion")
                return "continue"
            if action == 7:
                edit_source = self.prompt_edit_source(blocks[block_index], word)
                if edit_source is None:
                    continue
                replacement = input(f"Enter replacement for \"{edit_source}\": ").strip()
                if not replacement:
                    print("No replacement entered.")
                    pause()
                    continue
                self.apply_replacement_action(path, target, blocks, block_index, edit_source, replacement, scope, ctx, action_name="edit_substitute")
                return "continue"
            if action == 8:
                if scope == 1:
                    rel = str(path.relative_to(target))
                    self.block_ignores.add((rel, block_index, word.casefold()))
                    self.undo_stack.append({"type": "block_ignore", "file": rel, "subtitle_index": block_index, "word": word})
                    self.log_event({"type": "block_ignore", "file": rel, "subtitle_index": block_index, "word": word})
                elif scope == 2:
                    self.current_session_ignores.add(word.casefold())
                    self.undo_stack.append({"type": "session_ignore", "word": word})
                    self.log_event({"type": "session_ignore", "word": word})
                return "continue"
            if action == 9:
                dictionary_entry = self.prompt_dictionary_entry(
                    word,
                    blocks[block_index],
                    ctx,
                    target="universe" if scope == 3 else "user",
                )
                if dictionary_entry is None:
                    continue
                list_name, preferred = dictionary_entry
                dictionary_action = self.apply_dictionary_add(
                    preferred,
                    scope,
                    ctx,
                    list_name=list_name,
                )
                if dictionary_action and list_name == "names":
                    before = list(blocks[block_index].text_lines)
                    if re.search(r"\s", preferred):
                        after = self.restore_multiword_name_casing_in_lines(before, ctx)
                    else:
                        after = replace_first_word_in_lines(before, word, preferred)
                    if after != before:
                        blocks[block_index].text_lines = after
                        dictionary_action.update(
                            {
                                "file": str(path.relative_to(target)),
                                "subtitle_index": block_index,
                                "before_text_lines": before,
                                "after_text_lines": after,
                            }
                        )
                return "continue"

    def search_subtitle_line_in_google(
        self,
        block: SubtitleBlock,
        selected_word: str,
        *,
        line_index: Optional[int] = None,
    ) -> bool:
        visible_lines = [strip_html_tags(line).strip() for line in block.text_lines]
        if line_index is not None and 0 <= line_index < len(visible_lines):
            search_text = visible_lines[line_index]
        else:
            search_text = next(
                (
                    line
                    for line in visible_lines
                    if any(
                        match.group(0).casefold() == selected_word.casefold()
                        for match in WORD_RE.finditer(line)
                    )
                ),
                " ".join(line for line in visible_lines if line),
            )
        search_text = " ".join(search_text.split())
        if not search_text:
            print("This subtitle line has no searchable text.")
            return False

        url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": search_text})
        try:
            opened = webbrowser.open(url, new=2)
        except Exception as exc:
            print(f"The program could not open a web browser: {exc}")
            return False
        if not opened:
            print("The program could not open a web browser.")
            return False
        print("Opened a Google search for this subtitle line in your default browser.")
        return True

    def prompt_edit_source(self, block: SubtitleBlock, word: str) -> Optional[str]:
        containing_term = containing_edit_term(block.text_lines, word)
        while True:
            print("\nWhat text should be replaced?")
            print(f'1 - Selected word: "{word}"')
            if containing_term.casefold() != word.casefold():
                print(f'2 - Containing term: "{containing_term}"')
            else:
                print("2 - (No larger containing term found)")
            print("3 - Enter different text from this subtitle")
            print("0 - Go back")
            choice = input("\nText choice: ").strip()
            if choice in {"", "1"}:
                return word
            if choice == "2" and containing_term.casefold() != word.casefold():
                return containing_term
            if choice == "3":
                source = input("Exact text to replace: ").strip()
                if source and any(
                    source.casefold() in line.casefold()
                    for line in block.text_lines
                ):
                    return source
                print("That text was not found in the current subtitle.")
                pause()
                continue
            if choice == "0":
                return None
            print("Please choose 1, 2, 3, or 0.")
            pause()

    def parse_spellcheck_choice(self, choice: str, suggestions: List[str], ctx: DictionaryContext) -> Optional[Tuple[int, int]]:
        if len(choice) == 2 and choice[0].isdigit() and choice[1].isdigit():
            action, scope = int(choice[0]), int(choice[1])
        elif choice.isdigit():
            action = int(choice)
            if action not in range(1, 10):
                return None
            if action in range(1, 7) and action > len(suggestions):
                return None
            scope = self.prompt_scope(action, ctx)
            if scope is None:
                return None
        else:
            return None
        if action not in range(1, 10):
            return None
        if action in range(1, 7) and action > len(suggestions):
            return None
        return (action, scope) if self.valid_action_scope(action, scope, ctx) else None

    def spellcheck_choice_guidance(self, choice: str, suggestions: List[str], ctx: DictionaryContext) -> str:
        if len(choice) == 2 and choice.isdigit():
            action, scope = int(choice[0]), int(choice[1])
            if action in range(1, 7) and action > len(suggestions):
                return f"Suggestion {action} is not available. Choose one of the displayed suggestions."
            if action == 8 and scope not in {1, 2}:
                return (
                    f"{choice} is not a valid choice. To ignore a word temporarily, use 81 or 82. "
                    "To accept it permanently, use 93 or 94 when those scopes are available."
                )
            if action == 9 and scope in {1, 2}:
                valid = "93 or 94" if ctx.universe else "94"
                return f"{choice} is not a valid choice. Add-to-dictionary requires {valid}."
        return "That is not a valid choice."

    def prompt_scope(self, action: int, ctx: DictionaryContext) -> Optional[int]:
        print("\nScope:")
        if action in range(1, 8):
            print("1 - This time")
            print("2 - This session")
            if ctx.universe:
                print("3 - This universe")
            print("4 - Always")
        elif action == 8:
            print("1 - This time")
            print("2 - This session")
        elif action == 9:
            if ctx.universe:
                print("3 - This universe")
            print("4 - Always")
        value = input("Scope choice: ").strip()
        return int(value) if value.isdigit() else None

    def phrase_present_in_block(self, phrase: str, block: SubtitleBlock) -> bool:
        phrase_tokens = [match.group(0) for match in WORD_RE.finditer(phrase)]
        if len(phrase_tokens) < 2:
            return False
        visible_text = "\n".join(strip_html_tags(line) for line in block.text_lines)
        pattern = re.compile(
            r"(?<![A-Za-z0-9_'’\-])"
            + r"\s+".join(re.escape(token) for token in phrase_tokens)
            + r"(?![A-Za-z0-9_'’\-])",
            re.IGNORECASE,
        )
        return bool(pattern.search(visible_text))

    def prompt_dictionary_entry(
        self,
        word: str,
        block: Optional[SubtitleBlock] = None,
        context: Optional[DictionaryContext] = None,
        target: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        while True:
            print(f'\nHow should "{word}" be stored?')
            print("1 - Accepted word")
            print("2 - Name with authoritative casing")
            if block is not None:
                print("3 - Accepted exact phrase from this subtitle")
                print("4 - Exact name phrase with authoritative casing")
                print("5 - Acronym with authoritative casing")
            else:
                print("3 - Acronym with authoritative casing")
            print("0 - Go back")
            choice = input("Dictionary entry type: ").strip()
            if choice == "0":
                return None
            if choice == "1":
                if context is not None:
                    conflicts = (
                        self.word_acronym_conflicts_for_location(
                            word,
                            target,
                            language=context.language if target == "user" else None,
                            universe=context.universe if target == "universe" else None,
                        )
                        if target in {"user", "universe"}
                        else self.word_acronym_conflicts(word, context)
                    )
                    if not self.confirm_word_acronym_conflict(word, conflicts):
                        continue
                return "words", word
            if choice == "2":
                preferred = input(f'Preferred name casing [{word}]: ').strip() or word
                if preferred.casefold() != word.casefold():
                    print(
                        "A name entry may change casing only. Use Edit/Substitute "
                        "when the spelling itself should change."
                    )
                    continue
                if context is not None:
                    conflicts = (
                        self.word_acronym_conflicts_for_location(
                            preferred,
                            target,
                            language=context.language if target == "user" else None,
                            universe=context.universe if target == "universe" else None,
                        )
                        if target in {"user", "universe"}
                        else self.word_acronym_conflicts(preferred, context)
                    )
                    if not self.confirm_word_acronym_conflict(preferred, conflicts):
                        continue
                return "names", preferred
            if choice == ("5" if block is not None else "3"):
                preferred = input(f'Canonical acronym casing [{word}]: ').strip() or word
                try:
                    preferred = self.validate_acronym_entry(preferred)
                except ValueError as error:
                    print(error)
                    continue
                if preferred.casefold() != word.casefold():
                    print(
                        "An acronym entry may change casing only. Use Edit/Substitute "
                        "when the spelling itself should change."
                    )
                    continue
                if context is not None:
                    conflicts = (
                        self.acronym_word_conflicts_for_location(
                            preferred,
                            target,
                            language=context.language if target == "user" else None,
                            universe=context.universe if target == "universe" else None,
                        )
                        if target in {"user", "universe"}
                        else self.acronym_word_conflicts(preferred, context)
                    )
                    if not self.confirm_acronym_word_conflict(preferred, conflicts):
                        continue
                return "acronyms", preferred
            if choice in {"3", "4"} and block is not None:
                phrase = input("Exact phrase from this subtitle: ").strip()
                phrase_words = [match.group(0).casefold() for match in WORD_RE.finditer(phrase)]
                if word.casefold() not in phrase_words:
                    print(f'The phrase must include the selected word "{word}".')
                    continue
                if not self.phrase_present_in_block(phrase, block):
                    print("That complete phrase was not found in the current subtitle.")
                    continue
                if choice == "3":
                    return "words", phrase
                preferred = input(f"Preferred phrase casing [{phrase}]: ").strip() or phrase
                if preferred.casefold() != phrase.casefold():
                    print(
                        "A name phrase may change casing only. Use Edit/Substitute "
                        "when the spelling itself should change."
                    )
                    continue
                return "names", preferred
            valid = "1, 2, 3, 4, 5, or 0" if block is not None else "1, 2, 3, or 0"
            print(f"Please choose {valid}.")

    def valid_action_scope(self, action: int, scope: int, ctx: DictionaryContext) -> bool:
        if action in range(1, 7) or action == 7:
            valid = {1, 2, 4}
            if ctx.universe:
                valid.add(3)
            return scope in valid
        if action == 8:
            return scope in {1, 2}
        if action == 9:
            valid = {4}
            if ctx.universe:
                valid.add(3)
            return scope in valid
        return False

    def apply_replacement_action(
        self,
        path: Path,
        target: Path,
        blocks: List[SubtitleBlock],
        block_index: int,
        word: str,
        replacement: str,
        scope: int,
        ctx: DictionaryContext,
        action_name: str,
    ) -> bool:
        dictionary_add_action = None
        if scope == 3 and ctx.universe:
            replacement_is_valid, dictionary_add_action = self.ensure_replacement_known_for_substitution(
                replacement,
                ctx,
                universe_scope=True,
            )
            if not replacement_is_valid:
                return False
        elif scope == 4:
            replacement_is_valid, dictionary_add_action = self.ensure_replacement_known_for_substitution(
                replacement,
                ctx,
                universe_scope=False,
            )
            if not replacement_is_valid:
                return False

        rel = str(path.relative_to(target))
        before = list(blocks[block_index].text_lines)
        blocks[block_index].text_lines = replace_first_word_in_lines(
            blocks[block_index].text_lines,
            word,
            replacement,
        )
        after = list(blocks[block_index].text_lines)
        undo_action = {
            "type": "replace_word",
            "file": rel,
            "subtitle_index": block_index,
            "from": word,
            "to": replacement,
            "before_text_lines": before,
            "after_text_lines": after,
        }
        if dictionary_add_action:
            undo_action["dictionary_add"] = dictionary_add_action
        self.log_event({"type": "replace_word", "scope": scope, "file": rel, "subtitle_index": block_index, "from": word, "to": replacement})
        if scope == 2:
            key = word.casefold()
            undo_action["session_substitution"] = {
                "input": word,
                "previous_exists": key in self.current_session_substitutions,
                "previous_value": self.current_session_substitutions.get(key),
            }
            self.current_session_substitutions[word.casefold()] = replacement
            self.log_event({"type": "session_substitution", "from": word, "to": replacement})
        elif scope == 3 and ctx.universe:
            key = word.casefold()
            undo_action["persistent_substitution"] = {
                "target": "universe",
                "universe": ctx.universe,
                "language": ctx.language,
                "input": word,
                "previous_exists": key in ctx.universe_substitutions,
                "previous_value": ctx.universe_substitutions.get(key),
            }
            path = self.universe_dir / ctx.universe / "substitutions.tsv"
            self.add_substitution_to_file(path, word, replacement, {
                "type": "substitution_add", "target": "universe", "universe": ctx.universe, "input": word, "output": replacement,
            })
            ctx.substitutions[word.casefold()] = replacement
            ctx.universe_substitutions[word.casefold()] = replacement
        elif scope == 4:
            key = word.casefold()
            undo_action["persistent_substitution"] = {
                "target": "user",
                "language": ctx.language,
                "input": word,
                "previous_exists": key in ctx.user_substitutions,
                "previous_value": ctx.user_substitutions.get(key),
            }
            path = self.user_dir / f"{ctx.language}_substitutions.tsv"
            self.add_substitution_to_file(path, word, replacement, {
                "type": "substitution_add", "target": "user", "input": word, "output": replacement,
            })
            ctx.substitutions[word.casefold()] = replacement
            ctx.user_substitutions[word.casefold()] = replacement

        self.undo_stack.append(undo_action)

        return True

    def ensure_replacement_known_for_substitution(
        self,
        replacement: str,
        ctx: DictionaryContext,
        universe_scope: bool,
    ) -> Tuple[bool, Optional[dict]]:
        if ctx.is_known_word(replacement, self.current_session_ignores):
            return True, None
        clear_screen()
        if universe_scope and ctx.universe:
            print("The replacement word is not in the loaded Universe Dictionary.")
            print("1. Add it to the Universe Dictionary and add the substitution")
            print("2. Go back")
            print("3. Add it to the User Dictionary and add the substitution")
            choice = input("\nChoice: ").strip()
            if choice == "1":
                target = "universe"
            elif choice == "3":
                target = "user"
            else:
                return False, None
        else:
            print("The replacement word is not in any loaded dictionary.")
            print("1. Add it to the User Dictionary and add the substitution")
            print("2. Go back")
            if ctx.universe:
                print("3. Add it to the Universe Dictionary and add the substitution")
            choice = input("\nChoice: ").strip()
            if choice == "1":
                target = "user"
            elif choice == "3" and ctx.universe:
                target = "universe"
            else:
                return False, None

        dictionary_entry = self.prompt_dictionary_entry(
            replacement, context=ctx, target=target
        )
        if dictionary_entry is None:
            return False, None
        list_name, preferred = dictionary_entry
        filename = f"{list_name}.txt"
        if target == "universe" and ctx.universe:
            path = self.universe_dir / ctx.universe / filename
            event = {
                "type": "dictionary_add",
                "target": "universe",
                "universe": ctx.universe,
                "list": list_name,
                "word": preferred,
            }
            target_words = ctx.universe_words
            target_names = ctx.universe_names
            target_acronyms = ctx.universe_acronyms
        else:
            path = self.user_dir / f"{ctx.language}_{filename}"
            event = {
                "type": "dictionary_add",
                "target": "user",
                "base_language": ctx.language,
                "list": list_name,
                "word": preferred,
            }
            target_words = ctx.user_words
            target_names = ctx.user_names
            target_acronyms = ctx.user_acronyms

        dictionary_add_action = event if self.add_word_to_file(path, preferred, event) else None
        if list_name == "names":
            target_names[dictionary_key(preferred)] = preferred
        elif list_name == "acronyms":
            target_acronyms.add(preferred)
            ctx.acronym_set.add(preferred)
        else:
            target_words.add(dictionary_key(preferred))
        return True, dictionary_add_action

    def apply_dictionary_add(
        self,
        word: str,
        scope: int,
        ctx: DictionaryContext,
        list_name: str = "words",
    ) -> Optional[dict]:
        if list_name not in {"words", "names", "acronyms"}:
            raise ValueError(f"Unsupported dictionary list: {list_name}")
        if list_name == "acronyms":
            word = self.validate_acronym_entry(word)
        filename = f"{list_name}.txt"
        if scope == 3 and ctx.universe:
            path = self.universe_dir / ctx.universe / filename
            event = {
                "type": "dictionary_add",
                "target": "universe",
                "universe": ctx.universe,
                "list": list_name,
                "word": word,
            }
            if not self.add_word_to_file(path, word, event):
                return None
            if list_name == "names":
                ctx.universe_names[dictionary_key(word)] = word
            elif list_name == "acronyms":
                ctx.universe_acronyms.add(word)
                ctx.acronym_set.add(word)
            else:
                ctx.universe_words.add(dictionary_key(word))
            self.undo_stack.append(event)
            return event
        elif scope == 4:
            path = self.user_dir / f"{ctx.language}_{filename}"
            event = {
                "type": "dictionary_add",
                "target": "user",
                "base_language": ctx.language,
                "list": list_name,
                "word": word,
            }
            if not self.add_word_to_file(path, word, event):
                return None
            if list_name == "names":
                ctx.user_names[dictionary_key(word)] = word
            elif list_name == "acronyms":
                ctx.user_acronyms.add(word)
                ctx.acronym_set.add(word)
            else:
                ctx.user_words.add(dictionary_key(word))
            self.undo_stack.append(event)
            return event
        return None

    def perform_undo(
        self,
        blocks: Optional[List[SubtitleBlock]] = None,
        ctx: Optional[DictionaryContext] = None,
        current_file: Optional[str] = None,
        target: Optional[Path] = None,
        session_state: Optional[dict] = None,
    ) -> bool:
        if not self.undo_stack:
            print("There is no action to undo.")
            pause()
            return False
        action = self.undo_stack[-1]
        typ = action.get("type")
        if typ == "replace_word":
            if blocks is not None and current_file is None:
                current_file = action.get("file")
            if not self.undo_replacement_changes(
                action,
                blocks,
                current_file,
                target,
                session_state,
            ):
                return False
        if typ == "dictionary_add" and action.get("before_text_lines") is not None:
            index = action.get("subtitle_index")
            if (
                blocks is None
                or not isinstance(index, int)
                or index < 0
                or index >= len(blocks)
                or blocks[index].text_lines != action.get("after_text_lines")
                or (current_file is not None and current_file != action.get("file"))
            ):
                print("The dictionary addition was not undone because its subtitle text has changed.")
                return False
        action = self.undo_stack.pop()
        if typ == "replace_word":
            session_effect = action.get("session_substitution")
            if session_effect:
                key = session_effect.get("input", "").casefold()
                if session_effect.get("previous_exists"):
                    self.current_session_substitutions[key] = session_effect.get("previous_value")
                else:
                    self.current_session_substitutions.pop(key, None)
            persistent_effect = action.get("persistent_substitution")
            if persistent_effect:
                self.undo_persistent_substitution(persistent_effect, ctx)
            dictionary_effect = action.get("dictionary_add")
            if dictionary_effect:
                self.remove_logged_dictionary_add(dictionary_effect)
                self.remove_dictionary_entry_from_context(dictionary_effect, ctx)
            self.log_event({
                "type": "undo",
                "undo_type": typ,
                "file": action.get("file"),
                "subtitle_index": action.get("subtitle_index"),
            })
            return True
        if typ == "session_ignore":
            self.current_session_ignores.discard(action.get("word", "").casefold())
        elif typ == "session_substitution":
            self.current_session_substitutions.pop(action.get("from", "").casefold(), None)
        elif typ == "block_ignore":
            self.block_ignores.discard((action.get("file"), action.get("subtitle_index"), action.get("word", "").casefold()))
        elif typ == "dictionary_add":
            if action.get("before_text_lines") is not None and blocks is not None:
                blocks[action["subtitle_index"]].text_lines = list(action["before_text_lines"])
            self.remove_logged_dictionary_add(action)
            self.remove_dictionary_entry_from_context(action, ctx)
        elif typ == "substitution_add":
            self.remove_logged_substitution_add(action)
        self.log_event({"type": "undo", "undo_type": typ})
        return True

    def remove_dictionary_entry_from_context(
        self,
        action: dict,
        ctx: Optional[DictionaryContext],
    ) -> None:
        if ctx is None:
            return
        key = dictionary_key(action.get("word", ""))
        is_user = action.get("target") == "user"
        if action.get("list") == "names":
            names = ctx.user_names if is_user else ctx.universe_names
            names.pop(key, None)
        elif action.get("list") == "acronyms":
            acronyms = ctx.user_acronyms if is_user else ctx.universe_acronyms
            for value in list(acronyms):
                if value.casefold() == key:
                    acronyms.discard(value)
            ctx.acronym_set = set(COMMON_ACRONYMS)
            ctx.acronym_set.update(ctx.explicit_acronyms)
            ctx.acronym_set.update(self.derive_acronyms(ctx))
        else:
            words = ctx.user_words if is_user else ctx.universe_words
            words.discard(key)

    def undo_replacement_changes(
        self,
        action: dict,
        blocks: Optional[List[SubtitleBlock]],
        current_file: Optional[str],
        target: Optional[Path],
        session_state: Optional[dict],
    ) -> bool:
        """Preflight and restore every exact text change owned by one action."""
        changes = [{
            "file": action.get("file"),
            "subtitle_index": action.get("subtitle_index"),
            "before_text_lines": action.get("before_text_lines"),
            "after_text_lines": action.get("after_text_lines"),
        }]
        changes.extend(action.get("propagated_changes", []))

        files_to_blocks: Dict[str, List[SubtitleBlock]] = {}
        for change in changes:
            rel_file = change.get("file")
            if not isinstance(rel_file, str):
                continue
            if current_file == rel_file and blocks is not None:
                files_to_blocks[rel_file] = blocks
                continue
            if rel_file in files_to_blocks:
                continue
            if target is None:
                print("The last replacement belongs to another file and cannot be safely undone without the session folder.")
                pause()
                return False
            target_root = target.resolve()
            path = (target_root / rel_file).resolve()
            try:
                path.relative_to(target_root)
            except ValueError:
                print("The saved undo action refers to a file outside the session folder.")
                pause()
                return False
            try:
                files_to_blocks[rel_file] = self.parse_srt(path)
            except OSError as exc:
                print(f"The replacement could not be undone because {rel_file} could not be read: {exc}")
                pause()
                return False

        # Refuse before changing anything if a file no longer has the exact text
        # produced by this action. This protects edits made outside the session.
        for change in changes:
            rel_file = change.get("file")
            idx = change.get("subtitle_index")
            expected = change.get("after_text_lines")
            file_blocks = files_to_blocks.get(rel_file)
            if (
                not isinstance(idx, int)
                or file_blocks is None
                or not 0 <= idx < len(file_blocks)
                or list(file_blocks[idx].text_lines) != list(expected or [])
            ):
                print(
                    "The replacement was not undone because a recorded subtitle "
                    "has changed since the automatic replacement."
                )
                pause()
                return False

        original_text_by_file = {
            rel_file: [list(block.text_lines) for block in file_blocks]
            for rel_file, file_blocks in files_to_blocks.items()
        }
        for change in reversed(changes):
            rel_file = change["file"]
            idx = change["subtitle_index"]
            files_to_blocks[rel_file][idx].text_lines = list(change.get("before_text_lines") or [])

        undone_text_by_file = {
            rel_file: [list(block.text_lines) for block in file_blocks]
            for rel_file, file_blocks in files_to_blocks.items()
        }

        written_files: List[str] = []
        if target is not None:
            for rel_file, file_blocks in files_to_blocks.items():
                if current_file == rel_file and blocks is file_blocks:
                    continue
                path = target / rel_file
                try:
                    self.write_srt(path, file_blocks)
                except (OSError, UnicodeError) as exc:
                    # Restore the in-memory state first, then compensate for each
                    # earlier file that this undo already committed to disk.
                    for restore_file, restore_lines in original_text_by_file.items():
                        for block, text_lines in zip(files_to_blocks[restore_file], restore_lines):
                            block.text_lines = list(text_lines)
                    rollback_errors = []
                    failed_rollback_files = []
                    for written_file in reversed(written_files):
                        rollback_path = target / written_file
                        try:
                            self.write_srt(rollback_path, files_to_blocks[written_file])
                            if session_state is not None and isinstance(session_state.get("file_manifest"), list):
                                self.refresh_manifest_entry(
                                    session_state["file_manifest"], target, rollback_path
                                )
                        except (OSError, UnicodeError) as rollback_exc:
                            rollback_errors.append(f"{written_file}: {rollback_exc}")
                            failed_rollback_files.append(written_file)
                            # Atomic subtitle writes leave the last successfully
                            # published bytes intact. This rollback failed, so
                            # the disk still contains the undo result rather than
                            # the rule-applied text restored above in memory.
                            for block, text_lines in zip(
                                files_to_blocks[written_file],
                                undone_text_by_file[written_file],
                            ):
                                block.text_lines = list(text_lines)
                    print(f"The replacement was not undone because {rel_file} could not be written: {exc}")
                    if rollback_errors:
                        print(
                            "WARNING: rollback also failed for "
                            + "; ".join(rollback_errors)
                        )
                        if session_state is not None:
                            completed = session_state.get("completed_files", [])
                            if isinstance(completed, list):
                                failed = set(failed_rollback_files)
                                session_state["completed_files"] = [
                                    value for value in completed if value not in failed
                                ]
                            session_state["undo_recovery_required"] = True
                            session_state["undo_recovery_files"] = sorted(
                                set(failed_rollback_files)
                            )
                        try:
                            self.log_event({
                                "type": "undo_rollback_failed",
                                "failed_write_file": rel_file,
                                "recovery_files": sorted(set(failed_rollback_files)),
                                "errors": rollback_errors,
                            })
                        except (OSError, UnicodeError):
                            # The subtitle target may share the unavailable
                            # storage with the event log. Recovery state remains
                            # the authoritative signal when it can be saved.
                            pass
                        print(
                            "Spellcheck must stop with the substitution and undo "
                            "record still active. Resume after storage is available; "
                            "the affected file will be scanned again."
                        )
                    if not (rollback_errors and session_state is not None):
                        pause()
                    return False
                written_files.append(rel_file)
                if session_state is not None and isinstance(session_state.get("file_manifest"), list):
                    self.refresh_manifest_entry(session_state["file_manifest"], target, path)
        return True

    def undo_persistent_substitution(self, effect: dict, ctx: Optional[DictionaryContext]) -> None:
        source = effect.get("input", "")
        if not source:
            return
        target = effect.get("target")
        if target == "user":
            path = self.user_dir / f"{effect.get('language', 'american')}_substitutions.tsv"
        elif target == "universe" and effect.get("universe"):
            path = self.universe_dir / effect["universe"] / "substitutions.tsv"
        else:
            return

        if effect.get("previous_exists"):
            previous = effect.get("previous_value")
            if previous:
                self.add_substitution_to_file(path, source, previous)
        else:
            substitutions = self.load_substitutions(path)
            substitutions.pop(source.casefold(), None)
            self.save_substitutions(path, substitutions)

        if ctx:
            key = source.casefold()
            target_map = ctx.user_substitutions if target == "user" else ctx.universe_substitutions
            if effect.get("previous_exists"):
                target_map[key] = effect.get("previous_value")
            else:
                target_map.pop(key, None)
            # Universe substitutions override User substitutions. Rebuild the
            # effective value so undoing one layer cannot hide the other.
            if key in ctx.universe_substitutions:
                ctx.substitutions[key] = ctx.universe_substitutions[key]
            elif key in ctx.user_substitutions:
                ctx.substitutions[key] = ctx.user_substitutions[key]
            else:
                ctx.substitutions.pop(key, None)

    def remove_logged_dictionary_add(self, action: dict) -> None:
        word = action.get("word", "")
        if not word:
            return
        for path in self.dictionary_paths_for_event(action):
            self.remove_entries_from_file(path, [word])

    def remove_logged_substitution_add(self, action: dict) -> None:
        source = action.get("input", "")
        if not source:
            return
        for path in self.substitution_paths_for_event(action):
            subs = self.load_substitutions(path)
            subs.pop(source.casefold(), None)
            self.save_substitutions(path, subs)

    # ------------------------------------------------------------------
    # Recent additions review
    # ------------------------------------------------------------------
    def read_log_events(self) -> List[dict]:
        if not self.session_log_path.exists():
            return []
        events = []
        try:
            lines = self.session_log_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    def normalized_dictionary_entry(
        self,
        target: object,
        universe: object,
        language: object,
        list_name: object,
        word: object,
    ) -> Optional[dict]:
        if not isinstance(word, str) or not word.strip():
            return None
        normalized_list = (
            list_name if list_name in {"words", "names", "acronyms"} else "words"
        )
        if target == "user":
            result = {
                "type": "dictionary_add",
                "target": "user",
                "list": normalized_list,
                "word": word.strip(),
            }
            if language in {"american", "british"}:
                result["base_language"] = language
            return result
        if target == "universe" and isinstance(universe, str) and universe:
            return {
                "type": "dictionary_add",
                "target": "universe",
                "universe": universe,
                "list": normalized_list,
                "word": word.strip(),
            }
        return None

    def dictionary_entry_key(self, entry: dict) -> tuple:
        location = (
            entry.get("base_language", "")
            if entry.get("target") == "user"
            else str(entry.get("universe", "")).casefold()
        )
        return (
            entry.get("target"),
            location,
            self.dictionary_list_name(entry),
            str(entry.get("word", "")).casefold(),
        )

    def pop_matching_dictionary_entries(
        self,
        active: Dict[tuple, dict],
        word: object,
        target: object,
        list_name: object,
        universe: object = None,
        language: object = None,
    ) -> List[dict]:
        if not isinstance(word, str):
            return []
        word_key = word.casefold()
        normalized_list = (
            list_name if list_name in {"words", "names", "acronyms"} else None
        )
        removed = []
        for key, entry in list(active.items()):
            if entry.get("target") != target:
                continue
            if normalized_list is not None and self.dictionary_list_name(entry) != normalized_list:
                continue
            if str(entry.get("word", "")).casefold() != word_key:
                continue
            if target == "user" and language in {"american", "british"}:
                if entry.get("base_language") != language:
                    continue
            if target == "universe" and isinstance(universe, str):
                if str(entry.get("universe", "")).casefold() != universe.casefold():
                    continue
            removed.append(active.pop(key))
        return removed

    def reduce_recent_dictionary_events(self, events: Sequence[dict]) -> List[dict]:
        active: Dict[tuple, dict] = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "dictionary_add":
                entry = self.normalized_dictionary_entry(
                    event.get("target"),
                    event.get("universe"),
                    event.get("base_language"),
                    event.get("list"),
                    event.get("word"),
                )
                if entry:
                    active[self.dictionary_entry_key(entry)] = entry
            elif event_type == "dictionary_edit":
                removed = self.pop_matching_dictionary_entries(
                    active,
                    event.get("from"),
                    event.get("target"),
                    event.get("list"),
                    event.get("universe"),
                    event.get("base_language"),
                )
                locations = removed or [self.normalized_dictionary_entry(
                    event.get("target"),
                    event.get("universe"),
                    event.get("base_language"),
                    event.get("list"),
                    event.get("to"),
                )]
                for location in locations:
                    if not location:
                        continue
                    entry = dict(location)
                    entry["word"] = str(event.get("to", "")).strip()
                    if entry["word"]:
                        active[self.dictionary_entry_key(entry)] = entry
            elif event_type == "dictionary_move":
                removed = self.pop_matching_dictionary_entries(
                    active,
                    event.get("word"),
                    event.get("from_target"),
                    event.get("list"),
                    event.get("from_universe"),
                    event.get("from_base_language"),
                )
                entry = self.normalized_dictionary_entry(
                    event.get("to_target"),
                    event.get("to_universe"),
                    event.get("to_base_language") or (
                        event.get("base_language") if event.get("to_target") == "user" else None
                    ),
                    event.get("list") or (removed[0].get("list") if removed else None),
                    event.get("word"),
                )
                if entry:
                    active[self.dictionary_entry_key(entry)] = entry
            elif event_type == "dictionary_remove":
                self.pop_matching_dictionary_entries(
                    active,
                    event.get("word"),
                    event.get("target"),
                    event.get("list"),
                    event.get("universe"),
                    event.get("base_language"),
                )
            elif event_type == "universe_rename":
                old_name, new_name = event.get("from"), event.get("to")
                if not isinstance(old_name, str) or not isinstance(new_name, str):
                    continue
                for key, entry in list(active.items()):
                    if (
                        entry.get("target") == "universe"
                        and str(entry.get("universe", "")).casefold() == old_name.casefold()
                    ):
                        active.pop(key)
                        renamed = dict(entry)
                        renamed["universe"] = new_name
                        active[self.dictionary_entry_key(renamed)] = renamed
            elif event_type == "universe_delete":
                universe = event.get("universe")
                if not isinstance(universe, str):
                    continue
                for key, entry in list(active.items()):
                    if (
                        entry.get("target") == "universe"
                        and str(entry.get("universe", "")).casefold() == universe.casefold()
                    ):
                        active.pop(key)
        return sorted(
            active.values(),
            key=lambda entry: (
                str(entry.get("word", "")).casefold(),
                str(entry.get("target", "")),
                str(entry.get("base_language") or entry.get("universe") or "").casefold(),
                self.dictionary_list_name(entry),
            ),
        )

    def normalized_substitution_entry(
        self,
        target: object,
        universe: object,
        language: object,
        source: object,
        output: object,
    ) -> Optional[dict]:
        if not isinstance(source, str) or not source.strip():
            return None
        if not isinstance(output, str) or not output.strip():
            return None
        if target == "user":
            result = {
                "type": "substitution_add",
                "target": "user",
                "input": source.strip(),
                "output": output.strip(),
            }
            if language in {"american", "british"}:
                result["base_language"] = language
            return result
        if target == "universe" and isinstance(universe, str) and universe:
            return {
                "type": "substitution_add",
                "target": "universe",
                "universe": universe,
                "input": source.strip(),
                "output": output.strip(),
            }
        return None

    def substitution_entry_key(self, entry: dict) -> tuple:
        location = (
            entry.get("base_language", "")
            if entry.get("target") == "user"
            else str(entry.get("universe", "")).casefold()
        )
        return (
            entry.get("target"),
            location,
            str(entry.get("input", "")).casefold(),
        )

    def pop_matching_substitution_entries(
        self,
        active: Dict[tuple, dict],
        source: object,
        target: object,
        universe: object = None,
        language: object = None,
    ) -> List[dict]:
        if not isinstance(source, str):
            return []
        source_key = source.casefold()
        removed = []
        for key, entry in list(active.items()):
            if entry.get("target") != target:
                continue
            if str(entry.get("input", "")).casefold() != source_key:
                continue
            if target == "user" and language in {"american", "british"}:
                if entry.get("base_language") != language:
                    continue
            if target == "universe" and isinstance(universe, str):
                if str(entry.get("universe", "")).casefold() != universe.casefold():
                    continue
            removed.append(active.pop(key))
        return removed

    def reduce_recent_substitution_events(self, events: Sequence[dict]) -> List[dict]:
        active: Dict[tuple, dict] = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "substitution_add":
                entry = self.normalized_substitution_entry(
                    event.get("target"), event.get("universe"), event.get("base_language"),
                    event.get("input"), event.get("output"),
                )
                if entry:
                    active[self.substitution_entry_key(entry)] = entry
            elif event_type == "substitution_edit":
                removed = self.pop_matching_substitution_entries(
                    active,
                    event.get("from_input") or event.get("input"),
                    event.get("target"),
                    event.get("universe"),
                    event.get("base_language"),
                )
                locations = removed or [self.normalized_substitution_entry(
                    event.get("target"), event.get("universe"), event.get("base_language"),
                    event.get("input"), event.get("output"),
                )]
                for location in locations:
                    if not location:
                        continue
                    entry = dict(location)
                    entry["input"] = str(event.get("input", "")).strip()
                    entry["output"] = str(event.get("output", "")).strip()
                    if entry["input"] and entry["output"]:
                        active[self.substitution_entry_key(entry)] = entry
            elif event_type == "substitution_move":
                self.pop_matching_substitution_entries(
                    active,
                    event.get("input"),
                    event.get("from_target"),
                    event.get("from_universe"),
                    event.get("from_base_language"),
                )
                entry = self.normalized_substitution_entry(
                    event.get("to_target"),
                    event.get("to_universe"),
                    event.get("to_base_language") or (
                        event.get("base_language") if event.get("to_target") == "user" else None
                    ),
                    event.get("input"),
                    event.get("output"),
                )
                if entry:
                    active[self.substitution_entry_key(entry)] = entry
            elif event_type == "substitution_remove":
                self.pop_matching_substitution_entries(
                    active,
                    event.get("input"),
                    event.get("target"),
                    event.get("universe"),
                    event.get("base_language"),
                )
            elif event_type == "universe_rename":
                old_name, new_name = event.get("from"), event.get("to")
                if not isinstance(old_name, str) or not isinstance(new_name, str):
                    continue
                for key, entry in list(active.items()):
                    if (
                        entry.get("target") == "universe"
                        and str(entry.get("universe", "")).casefold() == old_name.casefold()
                    ):
                        active.pop(key)
                        renamed = dict(entry)
                        renamed["universe"] = new_name
                        active[self.substitution_entry_key(renamed)] = renamed
            elif event_type == "universe_delete":
                universe = event.get("universe")
                if not isinstance(universe, str):
                    continue
                for key, entry in list(active.items()):
                    if (
                        entry.get("target") == "universe"
                        and str(entry.get("universe", "")).casefold() == universe.casefold()
                    ):
                        active.pop(key)
        return sorted(
            active.values(),
            key=lambda entry: (
                str(entry.get("input", "")).casefold(),
                str(entry.get("target", "")),
                str(entry.get("base_language") or entry.get("universe") or "").casefold(),
            ),
        )

    def recent_dictionary_entries(self) -> List[dict]:
        candidates = self.reduce_recent_dictionary_events(self.read_log_events())
        results: Dict[tuple, dict] = {}
        word_cache: Dict[Path, set] = {}
        name_cache: Dict[Path, Dict[str, str]] = {}
        acronym_cache: Dict[Path, Dict[str, str]] = {}
        for candidate in candidates:
            word_key = candidate["word"].casefold()
            for path in self.dictionary_paths_for_event(candidate):
                current = dict(candidate)
                if candidate["list"] == "names":
                    if path not in name_cache:
                        name_cache[path] = self.load_name_map(path)
                    names = name_cache[path]
                    if word_key not in names:
                        continue
                    current["word"] = names[word_key]
                elif candidate["list"] == "acronyms":
                    if path not in acronym_cache:
                        acronym_cache[path] = {
                            value.casefold(): value
                            for value in self.load_acronym_set(path)
                        }
                    acronyms = acronym_cache[path]
                    if word_key not in acronyms:
                        continue
                    current["word"] = acronyms[word_key]
                else:
                    if path not in word_cache:
                        word_cache[path] = self.load_word_set(path)
                    words = word_cache[path]
                    if word_key not in words:
                        continue
                if current["target"] == "user":
                    language = self.user_language_for_path(path)
                    if language:
                        current["base_language"] = language
                results[self.dictionary_entry_key(current)] = current
        return sorted(results.values(), key=lambda entry: entry["word"].casefold())

    def recent_substitution_entries(self) -> List[dict]:
        candidates = self.reduce_recent_substitution_events(self.read_log_events())
        results: Dict[tuple, dict] = {}
        cache: Dict[Path, Dict[str, str]] = {}
        for candidate in candidates:
            source_key = candidate["input"].casefold()
            for path in self.substitution_paths_for_event(candidate):
                if path not in cache:
                    cache[path] = self.load_substitutions(path)
                substitutions = cache[path]
                if source_key not in substitutions:
                    continue
                current = dict(candidate)
                current["output"] = substitutions[source_key]
                if current["target"] == "user":
                    language = self.user_language_for_path(path)
                    if language:
                        current["base_language"] = language
                results[self.substitution_entry_key(current)] = current
        return sorted(results.values(), key=lambda entry: entry["input"].casefold())

    def recent_location_label(self, event: dict) -> str:
        if event.get("target") == "user":
            language = event.get("base_language")
            labels = {
                "american": "American English",
                "british": "British English",
            }
            return f"User ({labels.get(language, str(language).title())})" if language else "User Dictionary"
        return str(event.get("universe") or "Universe")

    def review_recent_dictionary_additions(self) -> None:
        while True:
            entries = self.recent_dictionary_entries()
            clear_screen()
            print("Recent Dictionary Additions\n")
            if not entries:
                print("No recent dictionary additions found in the session log.")
                pause()
                return
            print(f"{'Index#':<7} {'Dictionary':<24} {'Type':<7} Entry")
            for i, event in enumerate(entries, start=1):
                label = self.recent_location_label(event)
                label = truncate_display(label, int(self.options["maximum_universe_display_name_length"]))
                entry_type = {
                    "names": "Name",
                    "acronyms": "Acronym",
                }.get(event.get("list"), "Word")
                print(f"{i:<7} {label:<24} {entry_type:<7} {event.get('word', '')}")
            choice = input("\nEnter 0 to go back, or an index number to edit: ").strip()
            if choice == "0":
                return
            if choice.isdigit() and 1 <= int(choice) <= len(entries):
                self.edit_dictionary_entry_from_event(entries[int(choice) - 1])
            else:
                print("Unexpected input.")
                pause()

    def edit_dictionary_entry_from_event(self, event: dict) -> None:
        while True:
            clear_screen()
            word = event.get("word", "")
            target = event.get("target")
            print(f"Selected word: {word}")
            print(f"Location: {'User Dictionary' if target == 'user' else event.get('universe', 'Universe')}\n")
            print("1. Modify word")
            if target == "user":
                print("2. Move from User Dictionary to a universe dictionary")
                print("3. Delete word")
            else:
                print("2. Move from this universe dictionary to User Dictionary")
                print("3. Move to a different universe dictionary")
                print("4. Delete word")
            print("0. Go back")
            choice = input("\nChoice: ").strip()
            if choice == "0":
                return
            if choice == "1":
                new_word = input("New word: ").strip()
                if new_word:
                    try:
                        changed = self.modify_dictionary_word(event, new_word)
                    except ValueError as error:
                        pause(f"{error} Press Enter to continue.")
                        continue
                    if changed:
                        event["word"] = new_word
                        pause("Word modified. Press Enter to continue.")
            elif target == "user" and choice == "2":
                universe = self.choose_universe()
                if universe and self.confirm_move(word, universe):
                    self.move_dictionary_word(event, "universe", universe)
                    return
            elif target == "user" and choice == "3":
                self.delete_dictionary_word(event)
                return
            elif target != "user" and choice == "2":
                if self.move_dictionary_word(event, "user", None):
                    return
            elif target != "user" and choice == "3":
                universe = self.choose_universe()
                if universe and self.confirm_move(word, universe):
                    self.move_dictionary_word(event, "universe", universe)
                    return
            elif target != "user" and choice == "4":
                self.delete_dictionary_word(event)
                return

    def confirm_move(self, word: str, universe: str) -> bool:
        clear_screen()
        print(f'You have chosen to move "{word}" to the "{universe}" universe dictionary.')
        print("Is this correct?\n")
        print("1. Yes, move it")
        print("2. No, go back")
        return input("\nChoice: ").strip() == "1"

    def modify_dictionary_word(self, event: dict, new_word: str) -> bool:
        old_word = event.get("word", "")
        list_name = self.dictionary_list_name(event)
        target = event.get("target")
        language = event.get("base_language")
        universe = event.get("universe")
        if list_name == "acronyms":
            new_word = self.validate_acronym_entry(new_word)
            if not self.confirm_acronym_word_conflict(
                new_word,
                self.acronym_word_conflicts_for_location(
                    new_word,
                    target,
                    language=language,
                    universe=universe,
                ),
            ):
                return False
        elif list_name in {"words", "names"} and not re.search(r"\s", new_word):
            if not self.confirm_word_acronym_conflict(
                new_word,
                self.word_acronym_conflicts_for_location(
                    new_word,
                    target,
                    language=language,
                    universe=universe,
                ),
            ):
                return False
        changed_paths = []
        for path in self.dictionary_paths_for_event(event):
            missing = self.remove_entries_from_file(path, [old_word])
            if not missing:
                self.add_word_to_file(path, new_word)
                changed_paths.append(path)
        if changed_paths:
            payload = {
                "type": "dictionary_edit",
                "from": old_word,
                "to": new_word,
                "target": event.get("target"),
                "universe": event.get("universe"),
                "list": self.dictionary_list_name(event),
            }
            if event.get("base_language") in {"american", "british"}:
                payload["base_language"] = event["base_language"]
            self.log_event(payload)
        return bool(changed_paths)

    def move_dictionary_word(self, event: dict, target: str, universe: Optional[str]) -> bool:
        language = None
        if target == "user":
            # Ask language so we do not add to the wrong User Dictionary.
            language = self.choose_language()
            if not language:
                return False
        word = str(event.get("word", ""))
        list_name = self.dictionary_list_name(event)
        if list_name == "acronyms":
            word = self.validate_acronym_entry(word)
            if not self.confirm_acronym_word_conflict(
                word,
                self.acronym_word_conflicts_for_location(
                    word,
                    target,
                    language=language,
                    universe=universe,
                ),
            ):
                return False
        elif list_name in {"words", "names"} and not re.search(r"\s", word):
            if not self.confirm_word_acronym_conflict(
                word,
                self.word_acronym_conflicts_for_location(
                    word,
                    target,
                    language=language,
                    universe=universe,
                ),
            ):
                return False
        return self.move_dictionary_word_to(event, target, universe, language=language)

    def move_dictionary_word_to(
        self,
        event: dict,
        target: str,
        universe: Optional[str],
        *,
        language: Optional[str] = None,
    ) -> bool:
        """Move a recent word/name to an explicit non-interactive destination."""
        word = event.get("word", "")
        list_name = self.dictionary_list_name(event)
        if list_name == "acronyms":
            word = self.validate_acronym_entry(str(word))
        filename = f"{list_name}.txt"
        if target == "user" and language in {"american", "british"}:
            destination = self.user_dir / f"{language}_{list_name}.txt"
        elif target == "universe" and universe:
            destination = self.universe_dir / universe / filename
            language = None
        else:
            return False
        if destination in self.dictionary_paths_for_event(event):
            return False
        self.add_word_to_file(destination, word)
        self.delete_dictionary_word(event, log=False)
        payload = {
            "type": "dictionary_move",
            "word": word,
            "list": list_name,
            "from_target": event.get("target"),
            "from_universe": event.get("universe"),
            "from_base_language": event.get("base_language"),
            "to_target": target,
            "to_universe": universe,
            "to_base_language": language,
        }
        if language:
            payload["base_language"] = language
        self.log_event(payload)
        return True

    def delete_dictionary_word(self, event: dict, log: bool = True) -> None:
        word = event.get("word", "")
        for path in self.dictionary_paths_for_event(event):
            self.remove_entries_from_file(path, [word])
        if log:
            payload = {
                "type": "dictionary_remove",
                "word": word,
                "target": event.get("target"),
                "universe": event.get("universe"),
                "list": self.dictionary_list_name(event),
            }
            if event.get("base_language") in {"american", "british"}:
                payload["base_language"] = event["base_language"]
            self.log_event(payload)

    def dictionary_list_name(self, event: dict) -> str:
        value = event.get("list")
        return value if value in {"words", "names", "acronyms"} else "words"

    def dictionary_paths_for_event(self, event: dict) -> List[Path]:
        list_name = self.dictionary_list_name(event)
        if event.get("target") == "user":
            language = event.get("base_language")
            if language in {"american", "british"}:
                return [self.user_dir / f"{language}_{list_name}.txt"]
            # Older log entries did not identify a language. Retain best-effort
            # compatibility while keeping words and names in their own files.
            return [
                self.user_dir / f"{language}_{list_name}.txt"
                for language in ("american", "british")
            ]
        universe = event.get("universe")
        if event.get("target") == "universe" and isinstance(universe, str) and universe:
            return [self.universe_dir / universe / f"{list_name}.txt"]
        return []

    def review_recent_substitution_additions(self) -> None:
        while True:
            entries = self.recent_substitution_entries()
            clear_screen()
            print("Recent Substitution Additions\n")
            if not entries:
                print("No recent substitution additions found in the session log.")
                pause()
                return
            print(f"{'Index#':<7} {'Dictionary':<24} {'Input':<24} Output")
            for i, event in enumerate(entries, start=1):
                label = self.recent_location_label(event)
                label = truncate_display(label, int(self.options["maximum_universe_display_name_length"]))
                print(f"{i:<7} {label:<24} {event.get('input', ''):<24} {event.get('output', '')}")
            choice = input("\nEnter 0 to go back, or an index number to edit: ").strip()
            if choice == "0":
                return
            if choice.isdigit() and 1 <= int(choice) <= len(entries):
                self.edit_substitution_entry_from_event(entries[int(choice) - 1])
            else:
                print("Unexpected input.")
                pause()

    def edit_substitution_entry_from_event(self, event: dict) -> None:
        while True:
            clear_screen()
            print(f"Selected substitution: {event.get('input', '')} -> {event.get('output', '')}\n")
            print("1. Modify substitution")
            if event.get("target") != "user":
                print("2. Move substitution to User Dictionary")
                print("3. Move substitution to a different Universe Dictionary")
            else:
                print("2. Move substitution to a Universe Dictionary")
            print("4. Delete substitution")
            print("0. Go back")
            choice = input("\nChoice: ").strip()
            if choice == "0":
                return
            if choice == "1":
                source = input("New input: ").strip() or event.get("input", "")
                output = input("New output: ").strip() or event.get("output", "")
                if self.modify_substitution(event, source, output):
                    event["input"], event["output"] = source, output
                    pause("Substitution modified. Press Enter to continue.")
            elif choice == "2":
                if event.get("target") == "user":
                    universe = self.choose_universe()
                    if universe and self.confirm_move(event.get("input", ""), universe):
                        self.move_substitution(event, "universe", universe)
                        return
                else:
                    if self.move_substitution(event, "user", None):
                        return
            elif choice == "3" and event.get("target") != "user":
                universe = self.choose_universe()
                if universe and self.confirm_move(event.get("input", ""), universe):
                    self.move_substitution(event, "universe", universe)
                    return
            elif choice == "4":
                self.delete_substitution(event)
                return

    def substitution_paths_for_event(self, event: dict) -> List[Path]:
        if event.get("target") == "user":
            language = event.get("base_language") or event.get("language")
            if language in {"american", "british"}:
                return [self.user_dir / f"{language}_substitutions.tsv"]
            return [
                self.user_dir / f"{language}_substitutions.tsv"
                for language in ("american", "british")
            ]
        universe = event.get("universe")
        if event.get("target") == "universe" and isinstance(universe, str) and universe:
            return [self.universe_dir / universe / "substitutions.tsv"]
        return []

    def substitution_file_for_event(self, event: dict) -> Optional[Path]:
        paths = self.substitution_paths_for_event(event)
        return paths[0] if len(paths) == 1 else None

    def modify_substitution(self, event: dict, source: str, output: str) -> bool:
        target = event.get("target")
        if target == "user":
            language = event.get("base_language")
            if language not in {"american", "british"}:
                language = self.choose_language()
            if not language:
                return False
            path = self.user_dir / f"{language}_substitutions.tsv"
        elif event.get("universe"):
            path = self.universe_dir / event["universe"] / "substitutions.tsv"
            language = None
        else:
            return False
        self.delete_substitution(event, log=False)
        self.add_substitution_to_file(path, source, output)
        payload = {"type": "substitution_edit", "from_input": event.get("input"), "from_output": event.get("output"), "input": source, "output": output, "target": target, "universe": event.get("universe")}
        if language:
            payload["base_language"] = language
        self.log_event(payload)
        return True

    def move_substitution(self, event: dict, target: str, universe: Optional[str]) -> bool:
        language = None
        if target == "user":
            language = self.choose_language()
            if not language:
                return False
        return self.move_substitution_to(event, target, universe, language=language)

    def move_substitution_to(
        self,
        event: dict,
        target: str,
        universe: Optional[str],
        *,
        language: Optional[str] = None,
    ) -> bool:
        """Move a recent substitution to an explicit GUI/CLI destination."""
        source, output = event.get("input", ""), event.get("output", "")
        if target == "user" and language in {"american", "british"}:
            path = self.user_dir / f"{language}_substitutions.tsv"
        elif target == "universe" and universe:
            path = self.universe_dir / universe / "substitutions.tsv"
            language = None
        else:
            return False
        if path in self.substitution_paths_for_event(event):
            return False
        self.add_substitution_to_file(path, source, output)
        self.delete_substitution(event, log=False)
        payload = {"type": "substitution_move", "input": source, "output": output, "from_target": event.get("target"), "from_universe": event.get("universe"), "from_base_language": event.get("base_language") or event.get("language"), "to_target": target, "to_universe": universe, "to_base_language": language}
        if language:
            payload["base_language"] = language
        self.log_event(payload)
        return True

    def delete_substitution(self, event: dict, log: bool = True) -> None:
        source = event.get("input", "")
        if not source:
            return
        for path in self.substitution_paths_for_event(event):
            subs = self.load_substitutions(path)
            subs.pop(source.casefold(), None)
            self.save_substitutions(path, subs)
        if log:
            payload = {"type": "substitution_remove", "input": source, "output": event.get("output"), "target": event.get("target"), "universe": event.get("universe")}
            language = event.get("base_language") or event.get("language")
            if language in {"american", "british"}:
                payload["base_language"] = language
            self.log_event(payload)

    # ------------------------------------------------------------------
    # User dictionary maintenance
    # ------------------------------------------------------------------
    def user_dictionary_maintenance(self) -> None:
        language = self.choose_language()
        if not language:
            return
        while True:
            clear_screen()
            print(f"User Dictionary Maintenance ({language.title()} English)\n")
            print("1. User words")
            print("2. User names")
            print("3. User acronyms")
            print("4. User substitutions")
            print("0. Go back")
            choice = input("\nChoice: ").strip()
            if choice == "0":
                return
            if choice == "1":
                self.maintain_word_or_name_file(self.user_dir / f"{language}_words.txt", "user", "words")
            elif choice == "2":
                self.maintain_word_or_name_file(self.user_dir / f"{language}_names.txt", "user", "names")
            elif choice == "3":
                self.maintain_word_or_name_file(self.user_dir / f"{language}_acronyms.txt", "user", "acronyms")
            elif choice == "4":
                self.maintain_substitution_file(self.user_dir / f"{language}_substitutions.tsv", "user", None)

    def maintain_word_or_name_file(self, path: Path, target: str, list_name: str, universe: Optional[str] = None) -> None:
        while True:
            clear_screen()
            print(f"Maintain {list_name}")
            print(f"File: {path}\n")
            print("1. Add entries")
            print("2. Remove entries")
            print("0. Go back")
            choice = input("\nChoice: ").strip()
            if choice == "0":
                return
            if choice == "1":
                additions = self.prompt_entries_for_addition(list_name)
                if additions is None:
                    continue
                entries, redirected_names = additions
                if list_name in {"words", "names", "acronyms"}:
                    approved_entries = []
                    try:
                        language = (
                            self.user_language_for_path(path)
                            if target == "user"
                            else None
                        )
                        for entry in entries:
                            if list_name == "acronyms":
                                entry = self.validate_acronym_entry(entry)
                                conflicts = self.acronym_word_conflicts_for_location(
                                    entry,
                                    target,
                                    language=language,
                                    universe=universe,
                                )
                                confirmed = self.confirm_acronym_word_conflict(
                                    entry, conflicts
                                )
                            elif re.search(r"\s", entry):
                                confirmed = True
                            else:
                                conflicts = self.word_acronym_conflicts_for_location(
                                    entry,
                                    target,
                                    language=language,
                                    universe=universe,
                                )
                                confirmed = self.confirm_word_acronym_conflict(
                                    entry, conflicts
                                )
                            if confirmed:
                                approved_entries.append(entry)
                    except ValueError as error:
                        pause(f"{error} Press Enter to continue.")
                        continue
                    entries = approved_entries
                added = self.add_word_or_name_entries(
                    path, target, list_name, universe, entries
                )
                if redirected_names:
                    names_path = self.corresponding_names_path(path)
                    added.extend(
                        self.add_word_or_name_entries(
                            names_path, target, "names", universe, redirected_names
                        )
                    )
                pause(f"Added {len(added)} new entr{'y' if len(added) == 1 else 'ies'}. Press Enter to continue.")
            elif choice == "2":
                entries = self.prompt_entries_for_removal()
                missing = self.remove_entries_from_file(path, entries)
                for entry in entries:
                    if entry not in missing:
                        event = {"type": "dictionary_remove", "target": target, "universe": universe, "list": list_name, "word": entry}
                        language = self.user_language_for_path(path) if target == "user" else None
                        if language:
                            event["base_language"] = language
                        self.log_event(event)
                if missing:
                    print("Could not find:")
                    for item in missing:
                        print(f"- {item}")
                pause()

    def prompt_entries_for_addition(self, list_name: str) -> Optional[Tuple[List[str], List[str]]]:
        raw = input("Enter one entry or a list of entries: ").strip()
        if not raw:
            return ([], [])
        entries = self.prompt_entry_list(raw)
        if entries is None:
            return None
        final_entries = []
        redirected_names = []
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            if re.search(r"\s", entry) and list_name == "words":
                while True:
                    print(f'\n"{entry}" contains a space.')
                    print("1. Add it as an accepted exact phrase")
                    print("2. Add it as an authoritative name phrase instead")
                    print("3. Edit this entry")
                    print("4. Remove this entry from the additions")
                    print("0. Go back")
                    choice = input("Choice: ").strip()
                    if choice == "1":
                        final_entries.append(entry)
                        break
                    if choice == "2":
                        redirected_names.append(entry)
                        break
                    if choice == "3":
                        entry = input("Edited entry: ").strip()
                        if not entry:
                            break
                        if not re.search(r"\s", entry):
                            final_entries.append(entry)
                            break
                        continue
                    if choice == "4":
                        break
                    if choice == "0":
                        return None
                    print("Please choose 0, 1, 2, 3, or 4.")
            else:
                final_entries.append(entry)
        return sorted_unique(final_entries), sorted_unique(redirected_names)

    def prompt_entries_for_removal(self) -> List[str]:
        raw = input("Enter one entry or a list of entries to remove: ").strip()
        if not raw:
            return []
        entries = self.prompt_entry_list(raw)
        return [] if entries is None else entries

    def prompt_entry_list(self, raw: str) -> Optional[List[str]]:
        detected_separator = next((sep for sep in (",", ";", "|", "\t") if sep in raw), None)
        if len(raw) <= 15 and detected_separator is None:
            return [raw.strip()]
        print("\nThis looks like it may be more than one entry.")
        print("1. One entry")
        print("2. A list of entries")
        print("0. Go back")
        while True:
            choice = input("Choice: ").strip()
            if choice == "0":
                return None
            if choice == "1":
                return [raw.strip()]
            if choice == "2":
                prompt = (
                    f"Enter the separator, or press Enter to use {detected_separator!r}: "
                    if detected_separator
                    else "Enter the separator, such as comma: "
                )
                separator = input(prompt)
                if not separator:
                    separator = detected_separator
                if separator:
                    return sorted_unique(part.strip() for part in raw.split(separator))
                print("A separator is required for a list.")
                continue
            print("Please choose 0, 1, or 2.")

    def user_language_for_path(self, path: Path) -> Optional[str]:
        name = path.name.casefold()
        for language in ("american", "british"):
            if name.startswith(f"{language}_"):
                return language
        return None

    def corresponding_names_path(self, path: Path) -> Path:
        if path.name.casefold() == "words.txt":
            return path.with_name("names.txt")
        if path.name.casefold().endswith("_words.txt"):
            return path.with_name(path.name[:-len("words.txt")] + "names.txt")
        return path.with_name("names.txt")

    def add_word_or_name_entries(
        self,
        path: Path,
        target: str,
        list_name: str,
        universe: Optional[str],
        entries: Sequence[str],
    ) -> List[str]:
        existing = (
            [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if path.exists()
            else []
        )
        existing_keys = {dictionary_key(entry) for entry in existing}
        added = []
        for entry in sorted_unique(entries):
            if list_name == "acronyms":
                entry = self.validate_acronym_entry(entry)
            if dictionary_key(entry) in existing_keys:
                continue
            existing.append(entry)
            existing_keys.add(dictionary_key(entry))
            added.append(entry)
            event = {
                "type": "dictionary_add",
                "target": target,
                "universe": universe,
                "list": list_name,
                "word": entry,
            }
            language = self.user_language_for_path(path) if target == "user" else None
            if language:
                event["base_language"] = language
            self.log_event(event)
        if added:
            self.save_word_list(path, existing)
        return added

    def remove_entries_from_file(self, path: Path, entries: Sequence[str]) -> List[str]:
        existing = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
        remove_keys = {dictionary_key(entry) for entry in entries}
        found_keys = {
            dictionary_key(entry)
            for entry in existing
            if dictionary_key(entry) in remove_keys
        }
        remaining = [entry for entry in existing if dictionary_key(entry) not in remove_keys]
        self.save_word_list(path, remaining)
        return [entry for entry in entries if dictionary_key(entry) not in found_keys]

    def replace_maintenance_dictionary_entry(
        self,
        path: Path,
        target: str,
        list_name: str,
        universe: Optional[str],
        old_entry: str,
        new_entry: str,
    ) -> bool:
        """Replace one word/name with one atomic list publication."""
        old_entry = old_entry.strip()
        new_entry = new_entry.strip()
        if not old_entry or not new_entry or list_name not in {"words", "names", "acronyms"}:
            return False
        if list_name == "acronyms":
            new_entry = self.validate_acronym_entry(new_entry)
        existing = (
            [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if path.exists()
            else []
        )
        old_key = dictionary_key(old_entry)
        new_key = dictionary_key(new_entry)
        match_indexes = [
            index for index, value in enumerate(existing)
            if dictionary_key(value) == old_key
        ]
        if not match_indexes:
            return False
        if any(
            dictionary_key(value) == new_key and index not in match_indexes
            for index, value in enumerate(existing)
        ):
            raise ValueError("That replacement entry already exists in this dictionary.")
        existing[match_indexes[0]] = new_entry
        for index in reversed(match_indexes[1:]):
            existing.pop(index)
        self.save_word_list(path, existing)
        payload = {
            "type": "dictionary_edit",
            "from": old_entry,
            "to": new_entry,
            "target": target,
            "universe": universe,
            "list": list_name,
        }
        language = self.user_language_for_path(path) if target == "user" else None
        if language:
            payload["base_language"] = language
        self.log_event(payload)
        return True

    def replace_maintenance_substitution(
        self,
        path: Path,
        target: str,
        universe: Optional[str],
        old_source: str,
        new_source: str,
        new_output: str,
    ) -> bool:
        """Replace one substitution through one atomic map publication."""
        old_source = old_source.strip()
        new_source = new_source.strip()
        new_output = new_output.strip()
        if not old_source or not new_source or not new_output:
            return False
        substitutions = self.load_substitutions(path)
        old_key = old_source.casefold()
        new_key = new_source.casefold()
        if old_key not in substitutions:
            return False
        old_output = substitutions[old_key]
        if new_key != old_key and new_key in substitutions:
            raise ValueError("That substitution input already exists in this dictionary.")
        substitutions.pop(old_key)
        substitutions[new_key] = new_output
        self.save_substitutions(path, substitutions)
        payload = {
            "type": "substitution_edit",
            "from_input": old_source,
            "from_output": old_output,
            "input": new_source,
            "output": new_output,
            "target": target,
            "universe": universe,
        }
        language = self.user_language_for_path(path) if target == "user" else None
        if language:
            payload["base_language"] = language
        self.log_event(payload)
        return True

    def maintain_substitution_file(self, path: Path, target: str, universe: Optional[str]) -> None:
        while True:
            clear_screen()
            print("Maintain substitutions")
            print(f"File: {path}\n")
            print("1. Add substitution")
            print("2. Remove substitution by input")
            print("0. Go back")
            choice = input("\nChoice: ").strip()
            if choice == "0":
                return
            if choice == "1":
                source = input("Input text: ").strip()
                output = input("Output text: ").strip()
                if source and output:
                    added = self.set_maintenance_substitution(path, target, universe, source, output)
                    message = "added" if added else "updated"
                    pause(f"Substitution {message}. Press Enter to continue.")
            elif choice == "2":
                source = input("Input text to remove: ").strip()
                subs = self.load_substitutions(path)
                if source.casefold() in subs:
                    output = subs.pop(source.casefold())
                    self.save_substitutions(path, subs)
                    event = {"type": "substitution_remove", "target": target, "universe": universe, "input": source, "output": output}
                    language = self.user_language_for_path(path) if target == "user" else None
                    if language:
                        event["base_language"] = language
                    self.log_event(event)
                    pause("Substitution removed. Press Enter to continue.")
                else:
                    pause(f'Could not find "{source}". Press Enter to continue.')

    def set_maintenance_substitution(
        self,
        path: Path,
        target: str,
        universe: Optional[str],
        source: str,
        output: str,
    ) -> bool:
        source = source.strip()
        output = output.strip()
        if not source or not output:
            return False
        substitutions = self.load_substitutions(path)
        key = source.casefold()
        previous = substitutions.get(key)
        substitutions[key] = output
        self.save_substitutions(path, substitutions)
        event = {
            "type": "substitution_add" if previous is None else "substitution_edit",
            "target": target,
            "universe": universe,
            "input": source,
            "output": output,
        }
        if previous is not None:
            event["from_output"] = previous
        language = self.user_language_for_path(path) if target == "user" else None
        if language:
            event["base_language"] = language
        self.log_event(event)
        return previous is None

    # ------------------------------------------------------------------
    # Universe dictionary maintenance
    # ------------------------------------------------------------------
    def universe_dictionary_menu(self) -> None:
        while True:
            clear_screen()
            print("Universe Dictionary Maintenance and Stats")
            print("1. Create universe dictionary")
            print("2. Duplicate universe dictionary with new name")
            print("3. Rename universe dictionary")
            print("4. Delete universe dictionary")
            print("5. Universe dictionary stats")
            print("6. Maintain a universe dictionary")
            print("0. Back")
            choice = input("\nChoice: ").strip()
            if choice == "0":
                return
            if choice == "1":
                self.create_universe_dictionary()
            elif choice == "2":
                self.duplicate_universe_dictionary()
            elif choice == "3":
                self.rename_universe_dictionary()
            elif choice == "4":
                self.delete_universe_dictionary()
            elif choice == "5":
                self.show_universe_stats()
            elif choice == "6":
                self.maintain_universe_dictionary()

    def list_universes(self) -> List[str]:
        if not self.universe_dir.exists():
            return []
        return sorted(
            [
                path.name
                for path in self.universe_dir.iterdir()
                if path.is_dir() and not path.name.startswith(".__universe_")
            ],
            key=str.casefold,
        )

    def universe_name_error(self, name: str) -> Optional[str]:
        if not isinstance(name, str) or not name:
            return "Universe name cannot be empty."
        if name != name.strip():
            return "Universe name cannot begin or end with whitespace."
        if name in {".", ".."}:
            return "Universe name cannot be . or ..."
        if name.startswith(".__universe_"):
            return "That universe-name prefix is reserved for safe file operations."
        if len(name) > 200:
            return "Universe name must be 200 characters or fewer."
        if any(ord(character) < 32 for character in name):
            return "Universe name cannot contain control characters."
        invalid = '<>:"/\\|?*'
        if any(character in invalid for character in name):
            return f"Universe name cannot contain any of these characters: {invalid}"
        if name.endswith(".") or name.endswith(" "):
            return "Universe name cannot end with a period or space."
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved.update(f"COM{index}" for index in range(1, 10))
        reserved.update(f"LPT{index}" for index in range(1, 10))
        if name.split(".", 1)[0].upper() in reserved:
            return "That name is reserved by Windows."
        return None

    def universe_name_exists(self, name: str, exclude: Optional[str] = None) -> bool:
        key = name.casefold()
        return any(
            existing.casefold() == key
            and not (exclude is not None and existing == exclude)
            for existing in self.list_universes()
        )

    def create_universe_files(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=False)
        try:
            for filename in ("words.txt", "names.txt", "acronyms.txt", "substitutions.tsv"):
                (path / filename).write_text("", encoding="utf-8")
        except Exception:
            shutil.rmtree(path, ignore_errors=True)
            raise

    def ensure_universe_files(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        for filename in ("words.txt", "names.txt", "acronyms.txt", "substitutions.tsv"):
            file_path = path / filename
            if not file_path.exists():
                file_path.write_text("", encoding="utf-8")

    def copy_universe_files(self, source: Path, destination: Path) -> None:
        staging = destination.with_name(f".__universe_copy_{os.getpid()}")
        if staging.exists():
            raise FileExistsError(f"Temporary universe copy path already exists: {staging}")
        try:
            shutil.copytree(source, staging)
            self.ensure_universe_files(staging)
            staging.rename(destination)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

    def active_session_uses_universe(self, universe: str) -> bool:
        state = self.load_session_state()
        saved_universe = state.get("universe")
        return bool(
            state.get("session_active")
            and not state.get("scan_completed")
            and isinstance(saved_universe, str)
            and saved_universe.casefold() == universe.casefold()
        )

    def update_active_session_universe(self, old_name: str, new_name: str) -> bool:
        state = self.load_session_state()
        saved_universe = state.get("universe")
        if not (
            state.get("session_active")
            and not state.get("scan_completed")
            and isinstance(saved_universe, str)
            and saved_universe.casefold() == old_name.casefold()
        ):
            return False
        state["universe"] = new_name
        self.save_session_state(state)
        return True

    def choose_universe(self) -> Optional[str]:
        proceed, universe = self.choose_universe_from_pages()
        return universe if proceed else None

    def choose_spellcheck_universe(self) -> Tuple[bool, Optional[str]]:
        return self.choose_universe_from_pages(allow_create=True, allow_none=True)

    def choose_universe_from_pages(
        self,
        allow_create: bool = False,
        allow_none: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        page = 0
        while True:
            universes = sorted(self.list_universes(), key=str.casefold)
            if not universes and not allow_create and not allow_none:
                clear_screen()
                print("Choose Universe Dictionary")
                print("No universe dictionaries exist yet.")
                pause()
                return False, None
            page_count = max(1, (len(universes) + 9) // 10)
            page = min(page, page_count - 1)
            page_universes = universes[page * 10 : (page + 1) * 10]
            clear_screen()
            print(f"Choose Universe Dictionary — Page {page + 1} of {page_count}")
            if universes:
                max_len = int(self.options["maximum_universe_display_name_length"])
                for i, name in enumerate(page_universes, start=1):
                    print(f"{i}. {truncate_display(name, max_len)}")
            else:
                print("No universe dictionaries exist yet.")
            print()
            print()
            if allow_create:
                print("C. Create a new universe dictionary")
            if allow_none:
                print("N. Continue without a universe dictionary")
            if page > 0:
                print("11. Previous page")
            if page + 1 < page_count:
                print("33. Next page")
            print("0. Go back")
            choice = input("\nChoice: ").strip().casefold()
            if choice == "0":
                return False, None
            if choice == "11" and page > 0:
                page -= 1
                continue
            if choice == "33" and page + 1 < page_count:
                page += 1
                continue
            if allow_none and choice == "n":
                return True, None
            if allow_create and choice == "c":
                self.create_universe_dictionary()
                continue
            if choice.isdigit() and 1 <= int(choice) <= len(page_universes):
                return True, page_universes[int(choice) - 1]
            choices = ["a listed universe"]
            if allow_create:
                choices.append("C")
            if allow_none:
                choices.append("N")
            choices.append("a displayed page control")
            choices.append("0")
            print(f"Please choose {', '.join(choices)}.")
            pause()

    def create_universe_dictionary(self) -> bool:
        clear_screen()
        name = input("Universe name: ")
        if not name:
            return False
        try:
            self.create_universe_named(name)
        except ValueError as error:
            pause(f"{error} Press Enter to continue.")
            return False
        print(f'\nSuccessfully created universe dictionary files for "{name}":')
        print("- words.txt")
        print("- names.txt")
        print("- acronyms.txt")
        print("- substitutions.tsv")
        pause()
        return True

    def create_universe_named(self, name: str) -> bool:
        """Create a validated Universe Dictionary without interactive prompts."""
        error = self.universe_name_error(name)
        if error:
            raise ValueError(error)
        if self.universe_name_exists(name):
            raise ValueError("That universe already exists.")
        self.create_universe_files(self.universe_dir / name)
        self.log_event({"type": "universe_create", "universe": name})
        return True

    def duplicate_universe_dictionary(self) -> bool:
        source = self.choose_universe()
        if not source:
            return False
        clear_screen()
        new_name = input("New universe name: ")
        if not new_name:
            return False
        try:
            self.duplicate_universe_named(source, new_name)
        except ValueError as error:
            pause(f"{error} Press Enter to continue.")
            return False
        pause(f'Duplicated "{source}" to "{new_name}". Press Enter to continue.')
        return True

    def duplicate_universe_named(self, source: str, new_name: str) -> bool:
        """Copy one Universe Dictionary to a validated new name."""
        source_error = self.universe_name_error(source)
        if source_error:
            raise ValueError(source_error)
        error = self.universe_name_error(new_name)
        if error:
            raise ValueError(error)
        if self.universe_name_exists(new_name):
            raise ValueError("A universe with that name already exists.")
        self.copy_universe_files(
            self.universe_dir / source,
            self.universe_dir / new_name,
        )
        self.log_event({"type": "universe_duplicate", "from": source, "to": new_name})
        return True

    def rename_universe_dictionary(self) -> bool:
        source = self.choose_universe()
        if not source:
            return False
        clear_screen()
        new_name = input("New universe name: ")
        if not new_name:
            return False
        try:
            self.rename_universe_named(source, new_name)
        except (RuntimeError, ValueError) as error:
            pause(f"{error} Press Enter to continue.")
            return False
        pause(f'Renamed "{source}" to "{new_name}". Press Enter to continue.')
        return True

    def rename_universe_named(self, source: str, new_name: str) -> bool:
        """Rename a Universe Dictionary without interactive prompts."""
        source_error = self.universe_name_error(source)
        if source_error:
            raise ValueError(source_error)
        error = self.universe_name_error(new_name)
        if error:
            raise ValueError(error)
        if source == new_name:
            raise ValueError("The universe already has that name.")
        if self.universe_name_exists(new_name, exclude=source):
            raise ValueError("A universe with that name already exists.")
        src = self.universe_dir / source
        dst = self.universe_dir / new_name
        if source.casefold() == new_name.casefold():
            temporary = self.universe_dir / f".__universe_rename_{os.getpid()}"
            if temporary.exists():
                raise RuntimeError("A temporary rename path is already in use.")
            src.rename(temporary)
            try:
                temporary.rename(dst)
            except Exception:
                temporary.rename(src)
                raise
        else:
            src.rename(dst)
        self.ensure_universe_files(dst)
        self.update_active_session_universe(source, new_name)
        self.log_event({"type": "universe_rename", "from": source, "to": new_name})
        return True

    def delete_universe_dictionary(self) -> bool:
        universe = self.choose_universe()
        if not universe:
            return False
        if self.active_session_uses_universe(universe):
            pause(
                "That universe is referenced by an interrupted spellcheck session. "
                "Resume or restart that session before deleting it. Press Enter to continue."
            )
            return False
        clear_screen()
        print(f'You are about to delete the universe dictionary "{universe}".')
        confirm = input("Type DELETE to confirm deletion: ").strip()
        if confirm != "DELETE":
            return False
        self.delete_universe_named(universe)
        pause("Universe dictionary deleted. Press Enter to continue.")
        return True

    def delete_universe_named(self, universe: str) -> bool:
        """Delete one named Universe Dictionary after recovery-state checks."""
        error = self.universe_name_error(universe)
        if error:
            raise ValueError(error)
        if self.active_session_uses_universe(universe):
            raise RuntimeError(
                "That universe is referenced by an interrupted spellcheck session. "
                "Resume or restart that session before deleting it."
            )
        shutil.rmtree(self.universe_dir / universe)
        self.log_event({"type": "universe_delete", "universe": universe})
        return True

    def universe_statistics(self, universe: str) -> dict:
        path = self.universe_dir / universe
        return {
            "words": len(self.load_word_set(path / "words.txt")),
            "names": len(self.load_name_map(path / "names.txt")),
            "acronyms": len(self.load_acronym_set(path / "acronyms.txt")),
            "substitutions": len(self.load_substitutions(path / "substitutions.tsv")),
        }

    def show_universe_stats(self) -> None:
        clear_screen()
        print("Universe Dictionary Stats\n")
        print(f"{'Name':<28} {'Custom Words':>12} {'Names':>8} {'Acronyms':>10} {'Substitution Pairings':>22}")
        max_len = int(self.options["maximum_universe_display_name_length"])
        universes = self.list_universes()
        if not universes:
            print("(No universe dictionaries exist.)")
        for name in universes:
            stats = self.universe_statistics(name)
            print(f"{truncate_display(name, max_len):<28} {stats['words']:>12} {stats['names']:>8} {stats['acronyms']:>10} {stats['substitutions']:>22}")
        pause()

    def maintain_universe_dictionary(self) -> None:
        universe = self.choose_universe()
        if not universe:
            return
        path = self.universe_dir / universe
        self.ensure_universe_files(path)
        while True:
            clear_screen()
            print(f"Maintain Universe Dictionary: {universe}\n")
            print("1. Universe words")
            print("2. Universe names")
            print("3. Universe acronyms")
            print("4. Universe substitutions")
            print("0. Go back")
            choice = input("\nChoice: ").strip()
            if choice == "0":
                return
            if choice == "1":
                self.maintain_word_or_name_file(path / "words.txt", "universe", "words", universe)
            elif choice == "2":
                self.maintain_word_or_name_file(path / "names.txt", "universe", "names", universe)
            elif choice == "3":
                self.maintain_word_or_name_file(path / "acronyms.txt", "universe", "acronyms", universe)
            elif choice == "4":
                self.maintain_substitution_file(path / "substitutions.tsv", "universe", universe)



def wait_for_enter_to_customize(timeout_seconds: int) -> bool:
    """Return True when Enter is pressed before the timeout expires."""
    deadline = time.monotonic() + timeout_seconds
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            time.sleep(timeout_seconds)
            return False
        while time.monotonic() < deadline:
            remaining = max(0, int(deadline - time.monotonic() + 0.999))
            print(f"\rContinuing in {remaining} second{'s' if remaining != 1 else ''}... ", end="", flush=True)
            end_of_tick = min(deadline, time.monotonic() + 0.1)
            while time.monotonic() < end_of_tick:
                if msvcrt.kbhit():
                    char = msvcrt.getwch()
                    if char == "\x03":
                        raise KeyboardInterrupt
                    if char in {"\r", "\n"}:
                        print()
                        return True
                    if char in {"\x00", "\xe0"} and msvcrt.kbhit():
                        msvcrt.getwch()
                time.sleep(0.02)
        print("\rContinuing now.                 ")
        return False

    try:
        import select
        while time.monotonic() < deadline:
            remaining = max(0, int(deadline - time.monotonic() + 0.999))
            print(f"\rContinuing in {remaining} second{'s' if remaining != 1 else ''}... ", end="", flush=True)
            wait_time = min(0.2, max(0.0, deadline - time.monotonic()))
            readable, _, _ = select.select([sys.stdin], [], [], wait_time)
            if readable:
                sys.stdin.readline()
                print()
                return True
        print("\rContinuing now.                 ")
        return False
    except (OSError, ValueError):
        time.sleep(max(0.0, deadline - time.monotonic()))
        print()
        return False

def replace_first_word(line: str, source_word: str, replacement: str) -> str:
    # Match the token boundaries used by WORD_RE. Hyphens separate tokens, so
    # a selected component of a malformed form such as re-assed can be edited.
    pattern = re.compile(
        rf"(?<![A-Za-z'’]){re.escape(source_word)}(?![A-Za-z'’])",
        re.IGNORECASE,
    )
    return pattern.sub(replacement, line, count=1)


def replace_visible_span(text: str, start: int, end: int, replacement: str) -> str:
    """Replace a span measured after HTML-style subtitle tags are removed."""
    visible_raw_indexes = []
    tag_matches = iter(HTML_TAG_RE.finditer(text))
    tag = next(tag_matches, None)
    raw_index = 0
    while raw_index < len(text):
        if tag is not None and raw_index == tag.start():
            raw_index = tag.end()
            tag = next(tag_matches, None)
            continue
        visible_raw_indexes.append(raw_index)
        raw_index += 1
    if not 0 <= start < end <= len(visible_raw_indexes):
        raise ValueError("The visible replacement span is outside the subtitle line.")
    raw_start = visible_raw_indexes[start]
    raw_end = visible_raw_indexes[end - 1] + 1
    return text[:raw_start] + replacement + text[raw_end:]


def replace_first_word_in_lines(lines: Sequence[str], source_word: str, replacement: str) -> List[str]:
    """Replace exactly one occurrence across a subtitle block."""
    result = list(lines)
    for index, line in enumerate(result):
        replaced = replace_first_word(line, source_word, replacement)
        if replaced != line:
            result[index] = replaced
            break
    return result


def blocks_changed(original_text: List[List[str]], blocks: Sequence[SubtitleBlock]) -> bool:
    if len(original_text) != len(blocks):
        return True
    return any(before != block.text_lines for before, block in zip(original_text, blocks))


def count_nonblank_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def main() -> None:
    try:
        tool = SubtitleCleanupTool()
        tool.check_for_updates_cli()
        tool.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
