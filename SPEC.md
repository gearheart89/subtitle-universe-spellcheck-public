# Subtitle Universe Spellcheck Specification

## 1. Purpose

Subtitle Universe Spellcheck is a menu-driven, standard-library Python tool for safely cleaning and interactively spellchecking `.srt` subtitle collections. It is designed for shows and fictional settings containing invented terminology, inconsistent source spellings, unusual names, apostrophes, and acronyms.

The tool may automatically apply deterministic formatting rules and explicitly configured substitutions. It must not broadly guess spelling corrections. Unknown words must be presented to the user through an interactive review workflow.

## 2. Dictionary model

The tool uses three dictionary layers:

- **Base dictionary:** immutable American or British English vocabulary. Exactly one base language is active.
- **User dictionary:** personal words, names, acronyms, and substitutions that are always loaded for the selected base language.
- **Universe dictionary:** optional words, names, acronyms, and substitutions for one specific show, franchise, or project. At most one universe is active during a run.

Dictionary precedence and casing authority are:

1. Active session substitutions.
2. Universe and user substitutions.
3. Universe and user name lists, preserving their stored case.
4. User and Universe acronym lists, preserving their stored canonical case, followed by compatible derived/common acronyms.
5. Universe and user word lists.
6. Base vocabulary.
7. Conservative sentence-casing fallback.

Internal apostrophes, including straight and curly forms, are part of a word token.
Straight `'` and typographic `’` apostrophes have the same dictionary identity,
so `don't` and `Don’t` match without rewriting the subtitle's punctuation.
Known-token checks use direct membership in the active base, user, and universe
sets; scanning must not rebuild their combined vocabulary for every token.

## 3. Repository and runtime layout

```text
app/
    subtitle_cleanup.py
    subtitle_gui.py
assets/
    subtitle-universe-quill.png
    subtitle-universe-quill.ico
SubtitleUniverseSpellcheck.pyw
tools/
    build_multiplatform_release.py
    build_windows.ps1
SPEC.md
STATUS.md
docs/
    FINDINGS.md
tests/
dictionaries/                  # base assets tracked; writable runtime data ignored
    options.ini
    gui_theme.json
    session_state.json
    session_log.jsonl
    base/
        american_words.txt
        british_words.txt
    user/
        american_words.txt
        american_names.txt
        american_acronyms.txt
        american_substitutions.tsv
        british_words.txt
        british_names.txt
        british_acronyms.txt
        british_substitutions.tsv
    universes/
        <Universe Name>/
            words.txt
            names.txt
            acronyms.txt
            substitutions.tsv
```

The packaged American and British base vocabularies are generated from the
pinned SCOWL 2026.02.25 release at its recommended spellchecking size 60. The
American list uses spelling category `A` and default variants. The inclusive
British list uses categories `B,Z` through variant level 5 so both standard
`-ise` and Oxford `-ize` forms are accepted. Generated entries are deaccented
to match the Version 1 ASCII tokenizer, lowercased, restricted to supported
single-word token forms, deduplicated, and sorted. The source, generation
parameters, and required redistribution notice are stored beside the lists.

Word, name, and acronym files contain one entry per line. Acronyms are stored as one undotted alphanumeric token in authoritative casing. Their simple plural and possessive forms are recognized, and a recognized dotted spelling is normalized to the stored casing. Substitution files contain `input<TAB>output`. Substitution input matching is case-insensitive; output is emitted exactly as stored. Lists are sorted after maintenance operations, with substitutions sorted by input.

Before adding a single-token acronym, the application checks for the same
case-insensitive spelling in relevant accepted-word and authoritative-name
lists and requires confirmation when a collision exists. A Universe acronym
checks both Base/User language pairs plus only its own Universe; a User acronym
checks its selected Base/User language plus every Universe because that User
dictionary can be combined with any of them. Adding a single-token word or
name performs the inverse check against relevant built-in, User, and Universe
acronyms with the same scope rules. These collisions are advisory because some
are intentional. `AM` and `PM` are the exception: their contextual time
handling is built in, so explicit acronym entries for either spelling are
rejected with an explanation.

Multiword entries are exact, phrase-scoped dictionary entries. Multiword names
provide authoritative casing for the complete phrase; multiword words accept
the complete phrase without imposing name casing. A component is not accepted
outside the complete phrase unless it also has its own single-word entry.
Phrase matching is case-insensitive, requires whitespace rather than intervening
punctuation, and may cross a subtitle line wrap within one cue. Simple plural
and possessive forms of known acronyms retain the acronym's canonical casing,
for example `MALPs`, `GDOs`, and `SGC's`.

The application remains standard-library-only. The tested subtitle engine and
command-line interface remain in `app/subtitle_cleanup.py`. The approved graphical
interface is a thin Tkinter launcher in `app/subtitle_gui.py`; it must call the
same engine rather than duplicate spelling, formatting, dictionary, backup, or
write-safety behavior.

GUI colors are resolved through an internal theme registry. The original visual
design is the built-in `Ocean` baseline and fresh-install default. `Dark` is a
second immutable built-in palette. Settings exposes a Themes workspace where
the user selects Ocean, Dark, or Custom; the saved choice applies on the next
application start. Custom begins as a complete Ocean copy and exposes every
existing semantic color role as a validated `#RGB` or `#RRGGBB` input with a
plain-language description. It can be reset to either Ocean or Dark before
saving. After an actual selected-theme or active-Custom color change is saved,
the GUI offers to restart immediately; an unchanged save does not prompt. The
cross-platform restart supports source, `.pyw`, and frozen executable launches,
checkpoints retained review state, launches the replacement, and closes the old
Tk instance only after that launch succeeds. The choice
and complete Custom palette are atomically persisted in ignored portable file
`dictionaries/gui_theme.json`. Theme editing must not create extra color roles,
and widget code must not contain theme-specific branches.
Leaving Themes with an unsaved theme selection or Custom color edit prompts to
save, discard, or cancel navigation. Saving through that prompt uses the same
validation and restart offer as the explicit Save theme button; a failed save
or Cancel keeps the Themes workspace open.
Options, dictionary-maintenance, and Recent Additions alternating rows must use
the same `row_white` and `row_light` palette entries rather than independent
literals.

Boolean option switches must not communicate state through red and green alone.
Their moving knob contains a theme-controlled check mark when enabled and an ×
when disabled, retaining color as a secondary cue while supporting users with
red/green color-vision deficiencies.

Large titles must reuse the background color of their containing surface.
Page-level titles use `surface`; titles inside cards use `card`. This prevents a
label-sized rectangle around card titles without adding another Custom-theme
color choice.

Application-owned ttk controls use one palette-driven style layer rendered by
the cross-platform `clam` engine when available. The layer covers buttons,
entries, comboboxes and their popdown lists, Treeviews and headings, vertical
and horizontal scrollbars, separators, frames, and labels. Classic Tk listboxes
receive equivalent palette options through one helper. Theme limitations are
restricted to operating-system-owned title bars, window borders, native
file/folder dialogs, and native message boxes; those intentionally follow the
host operating system.

Returning to Formatting Only, Standard Spellcheck, or Universe Spellcheck from
any maintenance workspace must replace the maintenance status-bar message with
the current scan state. An idle scan identifies the selected mode and prompts
for Start scan; a retained review reports whether it is paused, awaiting an
action, or ready to save instead of presenting stale maintenance text.

The scan workspace must remain usable on smaller displays. Its readable content
width protects complete action and scope-button labels and its natural height
protects the bottom controls. When the window viewport is smaller than either
dimension, theme-neutral horizontal and/or vertical scrollbars appear around
the scan workspace; each scrollbar hides again when its overflow is removed.
The application minimum remains small enough for compact monitors rather than
forcing the full workspace width or height onto the physical display.

## 3.1 Graphical launcher

Running `app/subtitle_gui.py` without arguments opens the Tkinter interface on
Windows, macOS, or Linux. Running it with `--cli` starts the established
command-line interface. Directly running `app/subtitle_cleanup.py` also continues
to start the command-line interface.

Root-level `SubtitleUniverseSpellcheck.pyw` is the portable interface chooser.
On first use it requires an explicit `1` for GUI or `2` for CLI and writes
exactly one human-readable marker beside itself: `launch gui.txt` or
`launch cli.txt`. Later launches announce the saved choice and provide a
five-second opportunity to press Enter and choose again before continuing.
Changing the choice atomically creates the new marker and removes the old one;
deleting the marker manually restores first-run selection. Both markers are
ignored runtime data and are absent from release archives.

Tkinter availability is preflighted only for non-frozen source launches on
Linux and macOS when the GUI may be used. Windows source launches do not run
the check because official Windows Python installers bundle Tcl/Tk; frozen
builds do not run it because the release build controls its bundled runtime.
Explicit CLI launches and a retained CLI launcher choice likewise do not
require Tkinter. When a relevant source interpreter cannot import both
`tkinter` and `_tkinter`, a terminal prompt accepts Yes, No, or Stop asking.
Yes invokes only a recognized operating-system package manager and verifies
the import afterward. No starts the CLI for that launch without saving a
choice. Stop asking atomically records suppression in
`dictionaries/options.ini`, bypasses the interface chooser, and starts the CLI
on subsequent launches while Tkinter remains absent. Suppression is cleared
automatically when support is detected or successfully installed. Only while
suppression is active, CLI Options exposes an Install/check Tkinter GUI support
action. Failure or an unknown package manager leaves the CLI usable and does
not modify application files itself. Unknown-manager guidance links to the
official Python Tkinter documentation and provides `python -m tkinter` as the
post-installation verification command.

When a terminal is available, selection and the five-second override use text
prompts. A Windows `.pyw` process has no console, so it provides the equivalent
small Tk chooser/countdown; choosing CLI starts `app/subtitle_gui.py --cli` in
a new console window. On macOS and Linux, choosing GUI from a terminal starts a
detached child with standard streams closed, while choosing CLI remains in the
current terminal. The detached GUI child bypasses the chooser to prevent a
second prompt. This makes an accidental GUI selection on a console-only host
recoverable on the next terminal launch. Startup failures without a console
are presented in an error dialog. Desktop double-click association remains an
operating-system/user configuration rather than an application guarantee.

The Version 1 GUI and CLI have feature parity for scanning, formatting,
spellcheck decisions and scopes, dictionary maintenance, recent additions,
options, themes, About information, session-log maintenance, recovery, and
guarded backup restoration. Future GUI behavior must remain visibly disabled
or identify itself as not yet connected until it uses the shared engine and is
covered by regression tests; interface code must not duplicate formatting,
dictionary, backup, recovery, or write-safety rules. Formatting Only selects a
folder and Base language, discovers `.srt` files using the configured
recursive option, and runs the complete production formatter in memory on a
worker thread. It reports file/cue progress, supports Pause, Resume, Stop, and
Restart, summarizes changed files, and displays every report-only validation
finding without modifying it. Save changes uses the same confirmation, backup,
external-drift check, encoding preservation, atomic writes, and rollback path
as spellcheck review. Formatting progress, prepared blocks, validation
findings, and unsaved changes are included in GUI crash recovery.

The spellcheck review screen prepares cues in memory using the production
formatting order and displays genuine unknowns with up to six
production suggestions, two preceding cues, two following cues, and exact
selected-occurrence highlighting. Preparation and advancement run outside the
Tk event thread and report progress. The GUI supports Ignore followed by This
time or This session, retaining already prepared cues and treating repeated
copies of a word in one cue as separate occurrences. Session-scope ignores are
case-insensitive and last only for that GUI review. The GUI atomically
checkpoints prepared cues, its current position, occurrence/session ignores,
and Undo history to an ignored compressed recovery journal after each stable
review state. On the next launch, the user may recover or discard that journal.
Recovery is refused if a prepared source file no longer matches its recorded
baseline. A restored current issue is revalidated with the running version's
dictionary rules and advances automatically if it is no longer unknown. The
journal does not write any subtitle; Undo reverses GUI occurrence
and session ignores in last-in,
first-out order and returns the review to the affected occurrence, including
after the scan has otherwise reached its end.
Displayed suggestions are selectable GUI actions. Choosing one enables This
time, This session, Always, and This universe when a Universe Dictionary is
active. This time replaces only the highlighted occurrence. This session
retains a case-insensitive substitution for the remainder of the review.
This universe and Always atomically persist the same rule to the active
Universe or selected-language User substitutions file. Scoped rules propagate
through later prepared cues and files. Their originating and propagated edits
form one repeatable GUI Undo action; persistent Undo also restores the prior
dictionary rule. The recovery journal retains active review substitutions,
their propagated edits, and Undo metadata. Replacement respects HTML-style
subtitle tags and remains in memory until Save changes writes subtitle files.
Edit/Substitute turns the dialogue area of the Current subtitle panel into an
editable field while displaying the cue timestamp separately as read-only
metadata. The button becomes Cancel edit while editing. This time replaces the
complete prepared cue text, may change its line wrapping, advances the review,
and records the prior complete text in the repeatable GUI Undo history. Empty
dialogue and internal blank lines are rejected because they would produce an
invalid or structurally ambiguous SRT cue. This action also remains in memory
and does not alter the source subtitle.
Search line opens an explicit Google search for the exact highlighted dialogue
line using the shared markup-stripping behavior and leaves the review state
unchanged.
Save changes becomes available only when prepared subtitle bytes differ from
the session's saved baseline. It reports the number of affected files, asks
for confirmation, and, when the backup option is disabled, offers to enable
backups, save once without a backup, or cancel. Before writing, the shared
engine verifies that every affected source still matches the bytes originally
prepared. It then creates or retains the normal grouped ZIP archives and uses
the same encoding-preserving atomic subtitle writes as the CLI. A failed later
write rolls back any earlier files written by that save. A successful save
establishes a new baseline and clears the pre-save GUI Undo history. Stop,
Restart, and window close require confirmation before discarding unsaved text.
The primary scan control identifies whether it will Start, Resume, or Restart
the scan. Active background spelling work can be paused and resumed without
discarding completed preparation or occurrence ignores. Stopping explicitly
clears only the GUI's in-memory review state. A scan waiting at an unknown is
already paused for user review. Pause and Stop are separate, permanently
labeled controls; the Pause control has no code path that clears a session.

The GUI displays the Base choices as `American English` and `British English`
while retaining the stable `american` and `british` keys in dictionary paths,
saved review state, and engine calls. A light-blue question-mark help icon is
shown beside the scan language selector, User Dictionary Base-language list,
and the move form's Base-language choice. Its hover tooltip explains that
American uses forms such as `color` and `center`, British uses `colour` and
`centre`, and the British dictionary accepts both standard `-ise` and Oxford
British `-ize` forms such as `organise`/`organize`. The language selector
remains enabled for Formatting Only because formatting loads language-specific
user substitutions and names and uses dictionary context for casing behavior.
When Standard spellcheck disables the Universe selector, a light-blue help
icon beside it directs users who need a Universe Dictionary to choose Universe
spellcheck in the left pane; the icon is hidden in other scan modes. Selecting
Universe spellcheck exposes `Add a universe…` as the permanently first item in
the scan selector, followed by `No universe` and the alphabetized Universe
names. Choosing the action uses the same validated creation operation as
maintenance and immediately selects a successfully created Universe; cancelling
or failing restores the prior selection. The selector's popdown is capped and
scrolls rather than growing indefinitely. The Universe-maintenance list likewise
remains bounded and shows its vertical scrollbar only while its entries exceed
the visible area.
Selecting
User Dictionary or Universe Dictionary replaces the scan workspace in the main window with dictionary
maintenance; it does not open a secondary window. User maintenance presents
the two Base languages in its left column. Words/phrases, authoritative names,
canonical acronyms, and substitutions are separate entry types. Universe maintenance presents an
alphabetized Universe list in its left column with Add, Copy, Rename, and
Delete controls. The entry area switches among words/phrases, authoritative
names, acronyms, and substitutions. Words, names, and acronyms use one entry column. Substitutions
use separate `Find word / phrase` and `Replace with` columns. Entry controls
support adding, editing, moving, and removing entries. Moving uses the same
destination picker as Recent Additions. Content rewrites are atomic,
and an edit is published as one replacement rather than a separate delete and
add. Universe lifecycle operations use the same validated engine methods as
the command-line menus. Selecting Recent Additions replaces the scan workspace
with a current-state review reconstructed from the append-only session log and
verified against the dictionary files on disk. The review switches between
words/names/acronyms and substitutions, identifies the exact User language or Universe
location, and supports refresh, edit, move, and remove. Edits use the same
single-publication atomic operations as dictionary maintenance. The move form
first selects User Dictionary or Universe Dictionary with radio buttons, then
populates its dropdown with only Base languages or Universes for that type.
It excludes the entry's current location. The command-line recent-addition
screens remain available and share the same reconstruction and mutation logic.
Recent Additions and dictionary-maintenance entry tables use native extended
selection: Ctrl toggles individual rows and Shift selects a contiguous range.
Move applies one chosen destination to every selected entry, and Remove uses
one batch confirmation before removing every selected entry. Edit remains a
single-entry operation; invoking it with multiple rows selected displays an
explanation and makes no changes.

Dictionary and Universe-name entry forms are horizontally resizable and use
larger padded fields. A substitution is entered in one form containing both
Find and Replace fields; Enter advances from Find to Replace and submits from
Replace. These forms open centered over the current main-window bounds rather
than at a fixed screen corner, including when the main window has moved. The
substitution table is one spreadsheet-style two-column table separated by a
single draggable column boundary and a matching faint-gray rule through the
table body. One automatically hidden horizontal scrollbar serves the table.
The substitution columns do not auto-stretch after a manual divider drag, so
their chosen widths and any resulting horizontal overflow remain in effect
while that dictionary view stays active. Selecting another Base/Universe or
switching the dictionary entry type resets the columns to fit the window.
Cell text that does not fit its current column is display-truncated with a
trailing ellipsis while the complete underlying value remains available to
Edit, Move, and Remove operations.
Dictionary-maintenance and Recent Additions tables alternate light and very
light gray rows to make wide entries easier to track. The sidebar separates its heading groups with thin
light-blue rules. The application owns one quill artwork in cross-platform PNG
and Windows multi-resolution ICO forms. Every application-owned Tk root loads
and retains the PNG as its window icon; missing or unreadable artwork is
nonfatal. On Windows the process receives a stable application identity before
Tk starts, and PyInstaller embeds the ICO into the main executable so Explorer,
shortcuts, the title bar, and taskbar use the same project identity rather than
Python or PyInstaller defaults.

An About item appears beneath Options. Its main-window view shows the running
version, the public GitHub project link, the MIT source-license identification,
the SCOWL version and primary copyright/permission notice, a clickable link to
the exact bundled SCOWL release tag, and the path of the complete bundled SCOWL
notice. CLI menu item `10. About this tool` prints the same version, project
URL, MIT identification, SCOWL attribution, exact release URL, and bundled
notice path. Both interfaces obtain these values from shared engine constants.

Selecting Options replaces the scan workspace with a main-window settings
workspace. Its left column contains the same five categories as the CLI; the
right column shows every option in that category with its current value,
inline example when available, and a light-blue help icon exposing the shared
description. Boolean changes validate and save immediately. Positive-integer
changes save through Apply or Enter. The Universe display-length warning and
explicit confirmation above 32 characters are retained. GUI and CLI settings
use the same in-memory values and atomically published `options.ini` file.

The completed GUI must retain the CLI's backup prompts, recovery behavior,
scope semantics, undo guarantees, format preservation, and conservative
correction policy. Long-running preparation and scanning must run without
freezing the window and report bounded progress updates.

Add word / name / acronym / phrase opens an editable dictionary-entry dialog initialized
with the selected unknown. The user may retain that single word or expand it
to an exact phrase present in the current cue, choose accepted term versus
authoritative name casing, and explicitly choose the User Dictionary or active
Universe Dictionary. A phrase must include the selected unknown and match the
cue using whitespace-only token separation, including across a subtitle line
wrap. Adding a phrase never accepts its individual components elsewhere.
Dictionary additions are persisted immediately and appear in the recent-entry
log. Authoritative names recase the selected occurrence or complete phrase in
the prepared cue; that subtitle change remains in memory until Save changes.
GUI Undo removes the added dictionary entry, updates the active context, and
restores any name-casing change.

## 4. Main menu

```text
Subtitle Cleanup Tool

Subtitle Scan:
1. Adjust formatting only
2. Run standard spellcheck with formatting correction
3. Run spellcheck with optional universe dictionary and formatting correction

Dictionary Maintenance:
4. Review recent dictionary additions
5. Review recent substitution additions
6. User dictionary maintenance
7. Universe dictionary maintenance and stats
8. Options menu

Info/Maintenance:
9. What do Base, User, and Universe mean?
10. About this tool
11. Flush session log [enter 11? for help]

0. Exit
```

Menus clear the console before rendering and provide a way to return without making changes. Help screens explain the dictionary layers, supported cleanup operations, session recovery, and the conservative correction policy.

Entering `11?` from the CLI main menu explains that flushing the append-only
session log removes the history shown by Recent additions but does not delete
dictionary entries or clear interrupted-session recovery. Selecting `11`
retains the typed `FLUSH` confirmation before the log is atomically emptied.
The GUI exposes the same operation as **Flush session log** beneath Settings.
Its main-window maintenance view presents the same scope explanation and an
irreversible-action confirmation before using the shared engine operation.

The universe-capable spellcheck path lists existing universe dictionaries and
also offers to create a new universe, continue without a universe dictionary,
or return to the main menu. After creation, the refreshed list is shown so the
new universe can be selected for the run. Universe-selection lists in both
spellcheck and maintenance workflows are sorted alphabetically and display ten
entries per page. `0` returns, `11` opens the previous page when available,
and `33` opens the next page when available; `1` through `10` select an entry
on the current page. Two blank lines visually separate the universe entries
from creation, no-universe, pagination, and back controls.

## 5. Options

Options are stored in `dictionaries/options.ini`, take effect immediately, and
are organized into File Discovery and Safety, Spelling and Text Cleanup,
Subtitle Layout and Dialogue, Common Error Cleanup, and Menus and Display
submenus. Options and writable word, name, and substitution dictionaries are
published through flushed sibling temporary files and atomic replacement so an
interrupted rewrite cannot expose a partially written final file. They include:

The same file contains internal confirmation/suppression state that is not a
normal scan option. In particular, the optional POSIX Tkinter Stop-asking flag
controls the conditional CLI recovery action described in Section 3.1 and is
not shown as a regular GUI option.

| Option | Default |
| --- | ---: |
| Scan folders recursively | `true` |
| Capitalization preference | `Ask always` |
| Recognize informal `-in'` forms when the `-ing` word is known | `true` |
| Remove periods from abbreviations | `true` |
| Convert `--` and `...` to `…` | `false` |
| Title-case bracketed sound effects | `true` |
| Fix capitalization when a line is mostly uppercase | `true` |
| Capitalize lowercase pronoun `i` and its contractions | `true` |
| Adjust subtitle line count and length | `true` |
| Preferred maximum visible dialogue lines | `2` |
| Count sound-effect lines toward the visible-line limit | `false` |
| Preferred maximum characters per line | `40` |
| Acceptable maximum characters per line | `55` |
| Prefer balanced sentence-ending line breaks | `true` |
| Preserve speaker clarity for `Name:` and `- ` lines | `true` |
| Detect dropped speaker breaks after punctuation | `true` |
| Create `backup_subtitles.zip` before editing | `false` |
| Repair corrupted music symbols | `true` |
| Repair common mojibake punctuation | `true` |
| Remove safe invisible characters | `true` |
| Remove duplicate spaces | `true` |
| Fix spaces around punctuation | `true` |
| Repair unambiguous italic-tag errors | `true` |
| Report suspicious quotes, brackets, tags, and punctuation | `true` |
| Maximum displayed universe-name length | `24` |

Boolean entry accepts `yes/y/true/t/1/on` and `no/n/false/f/0/off`, case-insensitively. Numeric options accept positive whole numbers. Entering `<option>?` displays examples and guidance. Common-error options also show short before-and-after examples directly in their submenu.

The GUI presents these same groups in its Options workspace. Boolean settings
use compact left-aligned pill switches with a red disabled state and green
enabled state, and save immediately. Numeric fields remain right-aligned and
save through Apply or the Enter key. Setting rows alternate white and light
gray to support visual tracking. Every row reserves the same fixed-width right
zone: its blue question-mark help icon occupies one fixed position beneath a
`Tooltips` heading, while numeric controls use the remaining space without
influencing that position. The icons display the descriptions above.

Capitalization preference offers Ask always, Source capitalization, Subtitle-aware
capitalization, and All caps. Ask always requests one of the three concrete modes
at each new scan and offers a Remember my choice checkbox; an unchecked choice is
limited to that scan. Resuming or recovering an in-progress scan reuses its
checkpointed effective choice without asking again. Source capitalization retains source letter case;
Subtitle-aware capitalization enables the conservative capitalization rules in
Section 9; All caps uppercases visible subtitle text while preserving markup.
In All caps mode, capitalization rules that can no longer affect output are
disabled in the GUI and their tooltip explains how to change the mode.

When informal dropped-`g` recognition is enabled, a token ending in straight
or curly apostrophe after `-in` is accepted only if adding `g` produces a word
in the active dictionaries. Thus `goin'` and `goin’` are recognized when
`going` is known; unrelated apostrophe fragments remain unknown.

Universe display limits affect menus only. Longer internal names are permitted, but values above 32 require a layout warning and explicit acknowledgement.

## 6. Discovery and target selection

For main-menu actions 1 through 3, the tool first scans from the portable
application root (the parent of `app` for source runs, or the executable folder
for a frozen build) using the configured recursive behavior.

When subtitles are found, it reports the count and up to five top-level folders, then starts a five-second countdown. Pressing Enter during the countdown opens a custom-location prompt. When no subtitles are found, it explains the searched location and prompts immediately.

The custom-location prompt is a folder browser beginning at the process's
current working directory. It lists immediate child folders alphabetically,
ten per page. `1` through `10` enter a folder on the current page, `U` goes up
one level, `S` selects the displayed folder, `11` and `33` navigate pages when
available, and `0` returns to the main menu. The user may type an absolute or
relative folder path instead of browsing; relative paths are resolved from the
displayed folder first while retaining application-root and process-folder
fallbacks for compatibility.

Scanning is case-insensitive for the `.srt` extension. With recursive mode disabled, only `.srt` files directly inside the target root are included.

## 7. Backup behavior

When backups are enabled, backups are created before any edit by actions 1 through 3. Backups include only `.srt` files and preserve relative directory relationships.

Backup grouping is:

- Root-level `.srt` files go into `<target>/backup_subtitles.zip` without child-folder content.
- Every immediate child folder containing subtitles gets its own `<child>/backup_subtitles.zip`, containing all subtitles below that child and preserving paths relative to the child.
- An existing archive is assumed valid and is not replaced.
- Individual `.bak` files are not created.
- A new archive is built and flushed as a sibling temporary file, then atomically moved into place. Failed or incomplete temporary archives are removed and editing does not begin.

If backup creation is disabled when an editing action begins, the user is offered a safe choice to enable it, continue without a backup, or cancel.

The scan area also exposes restoration when at least one grouped
`backup_subtitles.zip` exists in the selected root or an immediate child.
Otherwise the action is disabled and its tooltip identifies the missing
prerequisite. Restoration validates all archives, CRCs, `.srt` entries, and
destinations before writing; rejects absolute, traversal, duplicate, and
non-subtitle entries; then atomically restores every entry. A write failure
rolls back files already restored where possible. The action requires the user
to type the exact confirmation `YES`, overwrites current subtitle files, and
retains the ZIP archives. The CLI provides the same operation from the Subtitle
Scan menu.

## 8. SRT parsing and writing

The parser preserves cue index, timestamp, text lines, and blank-line separation. Only subtitle text is modified. Timestamp values are never rewritten by Version 1.

Files are decoded as UTF-8 first, with explicit support for UTF-8/UTF-16/UTF-32 byte-order marks and a Windows-1252 or Latin-1 fallback for legacy files. When a subtitle is rewritten, its detected encoding, byte-order mark, predominant CRLF/LF/CR newline style, and exact terminal newline sequence are preserved. An edit that cannot be represented in the source encoding fails before the file is opened for writing.

Cue blocks that omit a numeric index retain that omission. Malformed text-only blocks are preserved as text rather than being assigned fabricated timestamps. HTML-style subtitle tags remain part of the stored text and are excluded from spellcheck word detection.

Unusual but parseable whitespace on source index and timestamp lines is retained
exactly rather than normalized. Timestamp recognition may tolerate that padding,
but Version 1 never trims or otherwise rewrites the stored metadata line.

Subtitle output is fully encoded and flushed to a sibling temporary file before an atomic filesystem replacement. A failure before replacement leaves the existing subtitle untouched and removes the temporary file where possible.

## 9. Formatting pipeline

Formatting runs in this order:

1. Configured deterministic common-error cleanup.
2. Optional ellipsis normalization.
3. Configured substitutions.
4. Selected capitalization mode, including All caps when selected.
5. Optional lowercase pronoun `i` capitalization in Subtitle-aware mode.
6. Optional dotted-acronym normalization.
7. Optional bracketed sound-effect title casing in Subtitle-aware mode.
8. Optional mostly-uppercase repair in Subtitle-aware mode.
9. Optional dropped-speaker-break detection.
10. Optional subtitle reflow.
11. Authoritative name/acronym casing restoration in Subtitle-aware mode.

Capitalization is applied during the formatting pass before interactive
spelling prompts are displayed. Source mode bypasses automatic casing repairs;
All caps changes only visible text and does not uppercase tag markup.

Formatting-only changes do not require individual session-log events.

### 9.0 Common-error cleanup and validation

Common-error cleanup uses individually configurable, deterministic rules. It
may repair known corrupted music symbols (`â™ª` to `♪`, `â™«` to `♫`), known
mojibake punctuation (`â€™` to `’`, `â€œ` to `“`), safe invisible characters,
duplicate visible spaces, unambiguous punctuation spacing, and simple malformed
italic tags such as `<i>Hello<i>` to `<i>Hello</i>`. HTML-style tag contents,
decimals, URLs, timestamps, ellipses, and potentially meaningful
right-to-left controls are protected. The tool repairs existing music symbols
but never infers singing or adds new notes.

The validation option reports suspicious quotation/bracket balance, unclosed
italic tags, and runs of four or more question or exclamation marks without
editing them. Straight and curly quotation balance is evaluated across the
complete subtitle file rather than per cue so quotations spanning multiple
cues do not flood the report with false positives. Reports show at most ten
items in the completion summary and state explicitly that validation did not
edit them.

### 9.1 Ellipsis normalization

When enabled, runs of `...` and `--` become `…` before other rules. This is disabled by default because a double hyphen may represent interruption rather than an ellipsis.

### 9.2 Lowercase pronoun `i`

When enabled, standalone lowercase `i` becomes `I` in ordinary dialogue, and
the common straight- or curly-apostrophe contractions `i'm`, `i'd`, `i'll`,
and `i've` become `I'm`, `I'd`, `I'll`, and `I've`. The rule operates on
visible subtitle text after configured substitutions, does not alter tag
markup, and protects `i.e.` and web addresses. It is a shared formatting rule:
command-line formatting/spellcheck runs and GUI in-memory preparation call the
same implementation.

### 9.3 Dotted acronyms

Known dotted acronyms are normalized to their preferred undotted casing, for example `M.A.L.P.` to `MALP`, `S.G.C.` to `SGC`, and `D.H.D.` to `DHD`.

Simple plural and possessive suffixes are retained. A period serving as true
sentence punctuation is also retained, so sentence-final `G.D.O.s.` becomes
`GDOs.` rather than `GDOs`.

### 9.4 Bracketed sound effects

Bracketed sound effects are title-cased, retaining lowercase connector words except at the beginning or end. Example: `[SOUND OF A DOOR OPENING]` becomes `[Sound of a Door Opening]`.

### 9.5 Mostly-uppercase repair

Lines with more than 80 percent uppercase letters are conservatively sentence-cased using the dictionary precedence rules. Stored names and acronyms retain authoritative casing.

The uppercase determination is taken from the source line before configured
substitutions introduce canonical mixed-case output. A correction such as
`TEALD` to `Teal'c` must not prevent the rest of an originally uppercase line
from being repaired.

### 9.6 Ambiguous `us` and `US`

Mixed-case lowercase `us` remains unchanged. During all-caps repair, a bare `US` defaults to the pronoun `us` unless a strong United States context is detected. Pronoun patterns override country patterns.

Protected country contexts include `US military`, `US government`, service branches, `US forces`, `US embassy`, and prepositional forms such as `in the US`, `to the US`, and `from the US`. Pronoun forms include `the two of us`, `all of us`, `both of us`, `one of us`, `just us`, `with us`, and verb-object phrases such as `told us`.

Ambiguous cases prefer lowercase `us`. Dotted `U.S.` and `U.S.A.` are protected and normalized according to the abbreviation option.

### 9.7 Dropped speaker breaks

Probable merged speakers after `.`, `?`, or `!`, optionally followed by a hyphen, are split into two `- ` dialogue lines. The detector must not fire inside abbreviations, decimals, acronyms, URLs, or before closing quotation marks.

Example:

```text
We have to go.Now?!
```

becomes:

```text
- We have to go.
- Now?!
```

### 9.8 Line reflow

Normal dialogue aims for 40 characters per line, may extend to 55 to avoid unnecessary lines, and aims for two visible dialogue lines. For text requiring two lines, the split should be balanced rather than greedily filling the first line.

Hard-break lines beginning with `Name:`, `- `, or a bracketed sound effect remain separate. Sound-effect lines may be excluded from the visible-line limit. Quoted sentence endings must not be mistaken for speaker breaks.

## 10. Interactive spellcheck

Automatic replacements are limited to deterministic formatting, loaded substitutions, and session substitutions chosen by the user.

While a file is being prepared or spellchecked in an interactive terminal, a
single in-place status line shows `File x of y | Subtitle a of b`. It appears
immediately at each phase transition and refreshes no more than once per
second. The line is cleared before an interactive question, where the same
position is shown as a static `Progress:` header. Redirected output omits the
in-place status display.

For each unknown word, the interface shows:

- File name.
- The complete current cue with its timestamp.
- Two preceding and two following cues.
- The unknown word.
- Up to six suggestions.

The active unknown word is displayed with a contrasting foreground and
background color in the current cue. On Windows the program enables virtual-
terminal processing so this works in both Command Prompt and PowerShell. If
the console cannot display color, output is redirected, or the `NO_COLOR`
environment variable is present, the same prompt is rendered as plain text.

Actions are:

- Suggestions 1-6.
- `7` Edit or substitute.
- `8` Ignore.
- `9` Add word, name, acronym, or exact phrase to a dictionary.
- `S` Search the current subtitle line in Google.
- `U` Undo.
- `0` Quit spellcheck.

Scopes are:

- `1` This occurrence.
- `2` This session.
- `3` This universe, only when a universe is loaded.
- `4` Always, meaning the selected language's user dictionary.

Valid combinations:

| Action | Valid scopes |
| --- | --- |
| Suggestion 1-6 | 1, 2, 3 when available, 4 |
| Edit or substitute 7 | 1, 2, 3 when available, 4 |
| Ignore 8 | 1, 2 |
| Add word/name/acronym/phrase 9 | 3 when available, 4 |

Two-character shortcuts such as `71`, `82`, and `94` are accepted. Invalid combinations explain the permitted alternatives. After an action, the current cue is rescanned so multiple issues can be handled.

The Google search action has no scope and does not change subtitle or
dictionary state. It removes subtitle markup and opens the dialogue line
containing the selected unknown word in the system's default browser. For a
multi-line cue, other lines are not included. Choosing this action sends that
line to Google; no online search occurs automatically. Browser-launch failure
is reported and returns the user to the same spellcheck prompt.

The action menu displays one independent `Scope:` list in a right-hand column
beside the Edit, Ignore, Add, Undo, and Quit choices. Entering an action alone,
such as `8`, still opens the action-specific scope prompt; entering a valid
combined shortcut, such as `81`, applies it directly.

Edit/Substitute asks what source text to replace before requesting the new
text. The choices are the selected unknown word, a larger containing
hyphenated term when present, or exact custom text from the current subtitle.
For example, when `assed` is selected inside `re-assed`, choosing the
containing term permits `re-assed` to become `reassessed` without retaining an
extra `re-`. Session and persistent substitutions use the chosen source text,
and undo restores the complete original cue.

Adding to a dictionary asks whether the entry is an accepted word, an
authoritative name, an acronym with authoritative casing, an accepted exact phrase, or an authoritative exact name
phrase. Phrase choices require exact text present in the current cue and must
include the selected unknown word. Names retain user-confirmed authoritative
casing and recase the current occurrence immediately, including phrases split
across subtitle display lines. The dictionary addition and current-cue casing
change are one undoable action. A name entry may change casing but not spelling;
spelling changes use Edit/Substitute. When an unknown persistent replacement
must also be added to a dictionary, the word-or-name classification remains
available.

Permanent or universe substitutions whose output is unknown require the user to add the output to an appropriate dictionary or go back.

Undo is repeatable and covers replacements, session choices, dictionary/name additions, and substitution additions where practical. A cross-file replacement undo preflights all affected cues. If a later file cannot be written, earlier files written by that undo are restored and the undo action and substitution rule remain active. If that compensating restoration also fails, the scan stops without claiming success, keeps the substitution and undo record active, marks each disk-divergent file incomplete, and preserves recoverable session state. Resuming after storage is available rescans those files and reapplies the still-active rule.

## 11. Session recovery and log

Recoverable state is stored in `dictionaries/session_state.json`; append-only history is stored as JSONL in `dictionaries/session_log.jsonl`. Missing files mean no aborted session.

Session state is fully flushed through a sibling temporary file and atomically
replaced. Append-only log events are flushed before their write completes. A
transient Windows permission error during replacement is retried
with short bounded delays so an indexer or security scanner cannot terminate
an otherwise recoverable spellcheck run.

The state schema records:

- Schema version, active/completed flags, mode, base language, and universe.
- Target root, recursive setting, start/update times, and option snapshot.
- Ordered file manifest with relative path, size, and modification time.
- Fully completed files.
- Current file, cue index, and unknown word.
- Session ignores and substitutions.
- Undo stack where practical.

A file enters `completed_files` only after it has been fully scanned and successfully written. On unsafe partial recovery, the current file may restart while preserving session choices.

An interrupted run offers:

1. Resume.
2. Restart the same target folder while preserving session choices.
3. Restart the same target folder and discard session choices.
4. Abandon the saved session and start the normal new-target scan.
5. Return to the main menu.

Abandoning a saved session clears its transient ignore, substitution, progress,
and undo data but does not modify dictionaries or subtitle files. Flushing the
JSONL session log does not clear or abandon an interrupted session because
recovery state is stored separately in `session_state.json`.

The normal new-target scan is the same sequence used on a fresh installation:
it automatically scans the project root using the configured recursive option,
shows the discovered subtitle folders, and gives the user five seconds to press
Enter. If Enter is pressed, the existing folder picker opens; the folder chosen
there becomes the root of the same configured recursive scan.

Successful completion marks the session inactive and complete, clears transient session data, and logs `scan_completed`.

The JSONL log records session lifecycle, file/cue progress needed for recovery, dictionary/name/substitution additions or removals, moves and edits, session choices, and undoable actions. Formatting-only changes are excluded.

## 12. Dictionary review and maintenance

Recent dictionary and substitution screens combine user and universe additions from the session log. Entries are alphabetized and may be modified, moved, or deleted. Moving into a universe requires a confirmation naming both the entry and target universe.

User maintenance first selects American or British English, then words, names, acronyms, or substitutions. Addition/removal accepts one value or a delimited list. Whitespace is trimmed. Multiword entries may be stored as accepted exact phrases, redirected to authoritative name phrases, edited, or omitted. Acronym entries are restricted to one undotted alphanumeric token and preserve canonical casing.

Universe maintenance supports create, duplicate, rename, delete with typed `DELETE` confirmation, statistics, and direct word/name/acronym/substitution maintenance. Every universe contains `words.txt`, `names.txt`, `acronyms.txt`, and `substitutions.tsv`.

## 13. Version 1 acceptance criteria

Version 1 is complete when all of the following are implemented and tested:

- Folder structure creation and persistent options.
- Menus and help screens.
- Automatic and custom recursive discovery.
- Grouped ZIP backup creation and typed-confirmation restoration.
- Lossless SRT structure handling.
- Formatting-only pipeline and all rules in Section 9.
- Source, Subtitle-aware, All caps, and Ask always capitalization behavior,
  including remembered and recovered effective scan choices.
- Base, user, and universe dictionary loading.
- Substitution loading and application.
- Interactive prompt, valid scope matrix, and invalid-scope guidance.
- Session ignores, substitutions, recovery, and basic repeatable undo.
- User and universe maintenance.
- Recent addition review screens.
- Session log flushing.
- GUI and CLI feature parity through the shared engine, with platform-appropriate
  launch behavior and no duplicated subtitle-processing rules.
- Ocean, Dark, and persisted editable Custom GUI themes.
- Allowlisted Windows and universal-source release archives, matching SHA-256
  files, required public documentation/notices, and no writable user data.

## 14. Portable Windows distribution

The supported Windows binary is an unsigned PyInstaller one-folder build. The
folder uses the executable's parent as its application root so writable User
and Universe dictionaries, options, recovery state, logs, backups, and the
default scan root remain portable beside the executable rather than inside a
temporary bundle directory.

The release ZIP contains the executable and its runtime components, the full
American and British SCOWL base dictionaries, SCOWL provenance and required
notice, the MIT license, README, and user guide. It must not contain subtitle
files, User or Universe dictionaries, options, recovery state, logs, or backup
archives. Applicable Python and build-tool redistribution notices are included
with the runtime. The ZIP is accompanied by a SHA-256 checksum file and release
notes that disclose the executable is unsigned and may display an Unknown
publisher warning.

PyInstaller is pinned as a build-only dependency and does not change the
standard-library-only application runtime. The frozen build uses
`app/subtitle_gui.py` as its entry point: the Windows executable launches the
GUI by default and accepts `--cli` to start the command-line interface. Its
console subsystem supports the CLI; normal frozen GUI startup releases that
console immediately. Source runs and non-Windows platforms do not use this
console-release behavior. A Windows executable must be built and smoke-tested
on Windows. The builder must fail before archiving if the executable does not
report the source version, any required public file or redistribution notice is
missing, or a known writable runtime-data path is present. Upgrades preserve personal data by
copying `dictionaries/user`, `dictionaries/universes`, and optionally
`dictionaries/options.ini` into a newly extracted release while the program is
closed. The base dictionary folder is replaced by each release.

The Windows build must fail early when either tracked quill asset is missing,
pass the multi-resolution ICO through PyInstaller's `--icon` option, copy both
assets into the distribution, and include them in the required-file audit. The
universal source archive includes the same PNG and ICO through its explicit
allowlist.

## 14.1 Multi-platform source distribution

The universal source ZIP runs on Windows, macOS, and Linux with Python 3.9 or
later and Tkinter. It contains only the `app` runtime scripts, immutable base
dictionaries and SCOWL notice, quill application assets, README, user guide,
and MIT license. An explicit
allowlist excludes development documents (`SPEC.md`, `STATUS.md`, and findings),
tests, build tooling, subtitles, User and Universe dictionaries, options, theme
preferences, recovery state, logs, backups, and prior artifacts. The release is
accompanied by a SHA-256 checksum.

Windows is the maintainer's hardware-tested platform. macOS and Linux are
intended and covered by automated platform-routing tests, but remain explicitly
unverified on physical systems because the maintainer does not own that
hardware. Release documentation must preserve this distinction and must not
claim physical validation that has not occurred.

The source scripts derive writable data and the default scan root from the
portable release root above `app`, preserving the same data layout as the
Windows executable. `tools/build_multiplatform_release.py` must run using only
the standard library on any supported host. It must reopen the generated ZIP,
CRC-check its members, and compare them with the exact versioned allowlist
before publishing the checksum. The Windows-only PyInstaller build
remains in `tools/build_windows.ps1`, and its ZIP also includes the public
README.

## 14.2 Update progression

Update support is deliberately staged so notification and verified download do
not prematurely gain authority to replace an installation.

### Stage 1 — check and verified ZIP download

When **Check for updates at startup** is enabled, GUI and CLI launches make a
short-timeout request to the public GitHub Releases API. The request itself is
the connectivity test; the application must not depend on ping or a separate
third-party connectivity service. Offline, rate-limited, malformed, or other
failed checks are nonfatal and must not delay access to subtitle work beyond the
bounded timeout.

The fresh-install state is unconfirmed and must not access the network. Before
the first check, each interface asks whether automatic startup checks are
allowed, persists Yes or No locally, and exposes the resulting switch under
**Menus and Display**. Declining performs no request and must remain respected
until the user changes the option. The consent prompt must explicitly state
that no network request has yet occurred.

The shared engine compares the running semantic version with the newest
published stable release. A newer release is reported through an interface-
appropriate prompt. No download occurs without explicit consent. A frozen
Windows executable offers the matching Windows architecture ZIP; every source
launch, including source running on Windows, offers the universal source ZIP.
Asset selection is restricted to the configured public repository and the
project's versioned filename patterns.

The user chooses where to save the ZIP. The matching `.sha256` release asset is
mandatory, downloaded through the same shared service, and saved beside it.
The ZIP is streamed to a sibling temporary file, subject to size limits, and
published atomically only after its SHA-256 matches the checksum asset and any
GitHub-provided digest. Cancellation or failure leaves the installed program
and personal data untouched and removes partial downloads. Stage 1 does not
extract, install, replace, restart, or delete application files.

### Stage 2 — verified guided installation (superseded)

The planned guided-only installer was intentionally skipped when Stage 3 was
implemented. The verified ZIP remains available for users who prefer manual
installation, and the automatic path performs the same validation and data-
preservation work transactionally.

### Stage 3 — transactional self-update

After a separately confirmed verified download, both interfaces may offer
automatic installation. The engine must revalidate the local ZIP/checksum,
reject unsafe paths and links, extract one complete distribution outside the
installation, and refuse automatic replacement of a Git working copy. Source
packages copy the standard-library helper script outside the installation;
Windows packages include a separately frozen helper executable.

The external helper waits for the running application to exit, renames the old
complete installation to a rollback location, moves the staged distribution
into the original path, restores User and Universe dictionaries, options,
theme settings, CLI/GUI recovery, logs, launcher preference, and subtitle or
backup files stored beneath the portable application folder, and invokes the
new runtime's version check. Only then may it restart the same GUI or CLI
interface. Failed exchange or validation must restore and restart the prior
version; permission failures must not leave a partial installation.

The restarted launcher receives a narrowly validated cleanup path for the
external helper directory. It attempts removal only when the path is an
expected updater sibling of the installation. If Windows still locks the
helper, startup remains successful, a small pending-cleanup record is retained
under `dictionaries`, and a later launch retries. Staging directories and stale
rollback copies are cleanup debris after a validated restart, not grounds to
undo an otherwise successful update.

### `v1.1.1` publishing checklist

Before publishing the Stage 3 updater release from `main`:

1. Exercise a genuinely newer, temporary normal GitHub release from both an
   extracted source installation and the frozen Windows package. Verify public
   download/checksum selection, distribution exchange, health validation,
   same-interface restart, exact portable-data preservation, and removal of
   staging, rollback, and helper paths; then remove the temporary release/tag.
2. Change the internal version and release-facing references from the temporary
   identifier to stable `1.1.1`.
3. Run Python compilation and the complete deterministic regression suite.
4. Merge the validated development state into `main` and tag that exact commit
   `v1.1.1`.
5. Build fresh universal-source and Windows x64 archives from the exact tagged
   commit; never rename or reuse temporary-test artifacts.
6. Verify both SHA-256 files, archive allowlists, required notices, and absence
   of subtitles or writable personal/runtime data.
7. Smoke-test the extracted source GUI/CLI, frozen GUI/CLI, formatting
   preparation, and exact-byte backup restoration.
8. Publish only the matching archives/checksums with the unsigned-Windows and
   physically-untested macOS/Linux disclosures.
9. Merge or fast-forward the tagged release state back into `development`;
   future features remain on `development`, and hotfixes made on `main` must be
   returned there.

## 15. Deferred ideas

- Richer undo throughout all maintenance screens.
- Improved acronym and HTML/italic handling.
- Dry-run reports and line-by-line previews.
- Detailed statistics and exportable reports.
- Configurable capitalization exceptions.
- Malformed timing-block diagnostics.
