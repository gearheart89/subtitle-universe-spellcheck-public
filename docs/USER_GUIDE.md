# Subtitle Universe Spellcheck user guide

## Before the first scan

Run `python app/subtitle_cleanup.py` from a terminal. The tool requires Python
3.9 or later and uses only Python's standard library. It keeps writable
settings and dictionaries at the portable release root (the folder containing
`app`), so install it where your account can create files.

The development source also includes a cross-platform Tkinter launcher:

```console
python app/subtitle_gui.py
python app/subtitle_gui.py --cli
```

The first command opens the graphical spelling-review screen; `--cli` starts
the established command-line interface. The GUI finds and highlights genuine
unknowns, shows surrounding cues and suggestions, and supports **Ignore**
followed by **This time** to advance past one exact occurrence in memory or
**This session** to skip every later case-insensitive occurrence during that
GUI review. **Undo** reverses those ignores in last-in, first-out order and
returns to the affected occurrence, including after the review reaches the end.
None of these actions changes the subtitle file until Save changes is used.
The primary button changes between
**Start scan**, **Resume scan**, and **Restart scan** according to its effect.
**Search line** opens a Google search for the exact highlighted dialogue line;
it does not advance the scan or change the current review.
To use one of the displayed spelling suggestions, select it and then choose a
scope. **This time** changes only that exact occurrence. **This session** also
replaces later matches during the current review. **This universe** saves and
uses the substitution in the active Universe Dictionary, while **Always**
saves it in the selected language's User Dictionary. One **Undo** restores the
originating replacement, its later automatic replacements, and any saved
substitution rule. The subtitle file on disk remains unchanged until Save
changes is used.
To correct more than the selected word, choose **Edit / Substitute**. The
Current subtitle dialogue area becomes editable, while the timestamp remains a
separate locked label. Edit any of the cue's dialogue lines and choose **This
time** to apply the complete cue in memory. The action button changes to
**Cancel edit** while editing. Blank cues and blank lines are rejected because
they would make the SRT structure ambiguous. Applied cue edits can be undone
and are not yet written to disk.
Use **Pause scan** during background work to retain progress, or **Stop scan**
to discard only the GUI's in-memory review. They are separate buttons; Pause
never doubles as Stop. A displayed unknown is already a
natural pause while the program waits for your choice.

Official Windows Python installers and the frozen Windows release already
include the GUI support they need, so they do not run a Tkinter check. A source
launch on Linux or macOS checks Tkinter only when a GUI launch may be needed.
If it is missing, choose **Yes** to try the recognized operating-system package
manager, **No** to use CLI for this launch, or **Stop asking** to remember CLI
fallback in `dictionaries/options.ini`. Stop asking bypasses the normal
interface chooser while Tkinter remains absent. To retry later, open CLI
**Options → Install/check Tkinter GUI support**; that action appears only after
Stop asking was selected. An explicit `--cli` launch and an already saved CLI
launcher preference never require Tkinter. If the application cannot recognize
the package manager, it links to the official Python Tkinter documentation and
suggests `python -m tkinter` to verify a manual installation.

Root-level `SubtitleUniverseSpellcheck.pyw` chooses between the two interfaces.
On first use, enter `1` for GUI or `2` for CLI; invalid input is rejected. The
launcher records the choice beside itself as `launch gui.txt` or
`launch cli.txt`. Later launches continue with that mode after five seconds;
press Enter during the countdown to choose again. Deleting the marker also
restores the first-run question.

Windows `.pyw` startup has no console, so it shows equivalent GUI buttons and a
five-second Select again window. Choosing CLI opens a visible console. On macOS
or Linux, run `python3 SubtitleUniverseSpellcheck.pyw` in a terminal; GUI
detaches and CLI stays in that terminal. If GUI was selected on a console-only
Linux system, rerun the launcher, press Enter during the countdown, and select
CLI. A desktop's double-click behavior still depends on its `.pyw` association.
Startup errors without a console are shown in a dialog. Direct
`app/subtitle_gui.py` and `app/subtitle_gui.py --cli` commands remain available
for explicit launches and diagnostics.

For the portable Windows release, extract the complete folder before running
`SubtitleUniverseSpellcheck.exe`. Do not run the executable from inside the
ZIP. Windows may show an **Unknown publisher** warning because the executable
is intentionally unsigned. Compare the downloaded ZIP with the accompanying
SHA-256 file before extracting it. Double-clicking the executable opens the
GUI without keeping a console window open. To use the CLI from the same
package, open a terminal in the extracted folder and run
`SubtitleUniverseSpellcheck.exe --cli`.

The executable and application window use the same project quill icon. Source
packages retain the PNG/ICO pair under `assets`; keep that folder with the
application when moving or updating it.

Open **Options menu → File Discovery and Safety** and enable ZIP backups before
editing irreplaceable subtitles. Backups contain only `.srt` files and are
created before formatting or spellcheck changes begin.

When grouped backups exist for the selected folder, the GUI enables **Restore
backup…** in the scan area; the CLI lists **R. Restore subtitles from backup
ZIPs**. Restoration overwrites current subtitle files, so it requires typing
the exact confirmation `YES`. Archives are validated before any overwrite and
are retained afterward. The control stays disabled when no applicable archive
exists, while its tooltip explains why.

## Choosing a scan

The main menu offers three scan modes:

1. **Adjust formatting only** applies enabled deterministic cleanup rules and
   does not ask spelling questions.
2. **Standard spellcheck with formatting correction** loads one Base language
   and its always-active User dictionary.
3. **Spellcheck with optional Universe dictionary and formatting correction**
   additionally lets you select or create a project-specific dictionary, or
   continue without one. In the GUI, **Add a universe…** remains at the top of
   the Universe dropdown; choosing it creates and immediately selects a new
   dictionary. Longer dropdown lists scroll instead of expanding indefinitely.

Each new scan first searches recursively from the script folder. The summary
continues automatically after five seconds. Press Enter during the countdown
to choose another folder. In the folder browser, use a listed number to enter
a child folder, `U` to move up, `S` to select the displayed folder, `11` and
`33` for pagination, or type an absolute or relative path.

## Dictionary layers

- **Base** is the packaged read-only American or British English vocabulary.
- **User** stores personal words, names, canonical acronyms, and substitutions for one Base
  language and is loaded every time that language is selected.
- **Universe** is the narrowest layer: optional terminology for one show,
  franchise, game, book series, or other project.

Accepted words are case-insensitive. Names provide authoritative casing.
Explicit acronyms also provide authoritative casing and recognize simple
plural, possessive, and dotted variants (`MALPs`, `SGC's`, and `D.H.D.`).
When a proposed acronym matches an accepted word or authoritative name, the
program identifies the conflicting dictionaries and asks before adding it.
It performs the inverse check when adding a single-word word or name that
matches an acronym. User entries check every Universe that they could later be
combined with; Universe entries check only their own Universe plus applicable
Base and User data. `AM` and `PM` cannot be added as acronyms because their
context-sensitive time behavior is already built in.
Multiword entries are exact phrases: storing `Vala Mal Doran`, for example,
does not accept `Mal` everywhere by itself. Substitution inputs match without
regard to case and emit the stored replacement.

## Interactive spellcheck

For each unknown word, the program shows the current cue, two previous cues,
two following cues, and up to six suggestions. The selected word is highlighted
when the terminal supports color.

Actions are:

- `1`–`6`: use a displayed suggestion
- `7`: edit or substitute the selected word, a containing hyphenated term, or
  other exact text from the cue
- `8`: ignore
- `9`: add an accepted word, authoritative name, canonical acronym, accepted
  phrase, or authoritative name phrase
- `S`: search the subtitle line containing the selected word in Google
- `U`: undo the most recent supported action
- `0`: stop and preserve recovery state

Scopes are `1` for this occurrence, `2` for this session, `3` for the selected
Universe, and `4` for the always-loaded User dictionary. Only scopes valid for
the chosen action are accepted. Enter an action by itself for a guided scope
prompt, or combine them—for example, `81` means ignore this occurrence.

Google search removes subtitle markup, opens the line in your default browser,
and returns to the same spellcheck question without changing the subtitle.
This is an explicit online action: the selected dialogue line is sent to
Google only when you choose `S`.

In the GUI, spelling and formatting changes remain in memory until **Save
changes** is selected. The button is enabled only when prepared subtitle text
differs from the saved files. Saving confirms the affected file count, follows
the configured grouped-backup policy, refuses files changed outside the
review, preserves source encoding and newlines, and uses atomic writes. If a
later file cannot be written, earlier files from that save are restored. A
successful save starts a new Undo baseline; Stop, Restart, and closing the
window warn before discarding unsaved text.

The GUI's **Add word / name / acronym / phrase** action starts with the highlighted
unknown. Leave it unchanged for a single entry or expand it to an exact phrase
from the current cue, including a phrase split across subtitle lines. Choose
an accepted term, a name with authoritative casing, or a canonical acronym,
then explicitly choose
the User Dictionary or active Universe Dictionary. Phrase components are not
accepted separately. Dictionary additions are saved immediately; Undo removes
the entry again and restores any in-memory name-casing change.

## Formatting and common-error cleanup

In the GUI, choose **Formatting only**, select the folder and Base language,
then choose **Start scan**. The full formatting pipeline runs in memory and
reports file/cue progress. It can be paused, resumed, stopped, or recovered
after an interrupted shutdown. The completed screen reports how many files
have prepared changes and lists suspicious validation findings separately;
validation findings are never edited automatically. Choose **Save changes** to
use the normal confirmation, backup choice, source-drift protection, and atomic
write path. Until then, subtitle files remain unchanged.

The categorized Options menu controls acronym normalization, bracketed sound
effects, mostly-uppercase repair, line reflow, speaker-break preservation,
dropped-speaker detection, informal `-in'` recognition, and deterministic
common-error cleanup. The enabled-by-default lowercase-pronoun option changes
standalone `i` and `i'm`/`i'd`/`i'll`/`i've` to their capitalized forms while
protecting tags, `i.e.`, and web addresses. This shared rule runs in both CLI
scans and GUI preparation. The Common Error Cleanup screen includes examples for
music-symbol and punctuation mojibake, invisible characters, spacing, and
simple italic-tag repairs. Suspicious quote, bracket, tag, and repeated-
punctuation findings are reported but not edited.

The default **Ask always** capitalization preference prompts at each new scan
for **Source capitalization** (retain source case), **Subtitle-aware
capitalization** (the conservative behavior described above), or **All caps**.
Select **Remember my choice** in that prompt to replace Ask always with the
chosen mode. Without it, the choice lasts only for the active scan. Pausing,
resuming, or recovering that scan reuses its original choice without asking
again. All Caps is applied before spelling review and preserves subtitle markup;
capitalization-specific switches are disabled until another mode is selected.

Use `?` after an option number to see its detailed explanation.

In the GUI, select **Options** in the left pane. Choose one of the five
categories on the left; its settings appear in the main area. Boolean settings
use a pill switch on the left: red is off and green is on. Switch changes save
immediately. Numeric controls remain on the right; enter a positive whole
number and choose **Apply** or press Enter. Alternating white and light-gray
rows make individual settings easier to track. The blue `?` beside each setting
is aligned beneath the **Tooltips** heading and shows the same detailed
explanation used by the CLI. Common-cleanup examples remain shown beside their
labels. Values above 32 for the Universe display-name limit retain the layout
warning and require confirmation.

**Check for updates at startup** is under **Menus and Display** and applies to
both interfaces. On first launch, before any network access, the program asks
whether automatic startup checks are allowed and saves Yes or No; the same
option can change that answer later. The check is short and nonfatal when
offline. A newer stable release is never downloaded without confirmation. Windows executable launches
offer the matching Windows ZIP; all source launches offer the universal source
ZIP. The program verifies the required `.sha256` file and ZIP before publishing
both at the destination you select. You can then keep the verified ZIP or
approve automatic installation. Automatic installation stages the complete
new distribution outside the running folder, preserves portable dictionaries,
options, theme and recovery data, logs, launcher preference, and any subtitles
or backup archives beneath the application folder, then closes the old version.
An external helper exchanges the distribution, checks the new version, restarts
the same GUI or CLI interface, and rolls back if validation fails. The restarted
launcher removes temporary updater files; if Windows still has the helper
locked, cleanup is recorded and retried on the next launch. Git working copies
must be updated with Git rather than the automatic installer.

The original GUI color design is named **Ocean** and is the fresh-install
default. Select **Themes** under Settings to choose Ocean, the built-in **Dark**
palette, or **Custom**. Custom begins as a complete copy of Ocean. Every color
field explains which part of the interface it controls and accepts `#RGB` or
`#RRGGBB`; **Reset Custom to Ocean** and **Reset Custom to Dark** copy either
built-in palette into the form. Choose **Save theme**. If the saved selection
or active Custom colors differ from the running theme, the program offers to
restart immediately; choosing No leaves the theme saved for the next launch.
Retained review work is checkpointed before an accepted restart. The application
starts the replacement first and closes the current window only after the
operating system accepts that launch; if launching fails, the current window
stays open and explains that a manual reopen is required.
If you select another page after changing the theme or a Custom color without
saving, the program asks whether to save, discard, or cancel navigation.
Choosing save runs the same validation and restart prompt as **Save theme**.
Theme choices and Custom colors are stored in `dictionaries/gui_theme.json`.
Buttons, entries, dropdowns, lists, tables, headings, and scrollbars follow the
active application palette. Title bars, native file/folder dialogs, native
message boxes, and operating-system window borders retain the system theme.

## Recovery and undo

An interrupted spellcheck offers to resume, restart the saved folder while
keeping or discarding temporary choices, abandon it and begin a normal new
scan, or return to the menu. Flushing the session event log does not clear
recovery state.

Cross-file substitution undo verifies every affected cue before writing. If a
write fails, completed writes are compensated. If that compensation also
fails because storage is unavailable, the scan stops, retains the rule and
undo record, and marks affected files incomplete. Resume after storage is
available so those files can be scanned again.

## Session log maintenance

The session log supplies the history displayed by **Recent additions**. In the
CLI, choose `11` to flush it or enter `11?` first for an explanation. In the
GUI, choose **Flush session log** under Settings, review the maintenance screen,
then use its confirmation-protected button. Flushing removes recent-addition
history only: it does not delete words, names, acronyms, substitutions, or
interrupted-scan recovery state.

## Dictionary maintenance

The main menu provides User and Universe maintenance plus review screens for
recent additions. Universe maintenance supports creation, duplication,
renaming, deletion with typed confirmation, statistics, and direct editing of
words, names, acronyms, and substitutions. Acronyms are stored undotted as a
single letter/number token with authoritative casing. GUI Universe lists show a
vertical scrollbar only when their contents exceed the visible area. CLI
Universe lists are alphabetical and show ten entries per page; use `11` and
`33` to move between pages.

Dictionary entry rows alternate between light and very light gray. The
Substitutions view is one spreadsheet-style table with resizable Find and
Replace columns and one horizontal scrollbar that stays hidden when it is not
needed. Manually resized substitution columns retain their chosen widths, so
the scrollbar remains available when the columns extend beyond the window.
Selecting another Base/Universe or entry type restores a balanced,
window-fitting layout for the newly loaded view. A
trailing `…` indicates that a cell's complete text does not fit its
current width; editing the row still opens the complete stored value.

## Files created locally

Runtime files beneath `dictionaries/`, selected subtitle files, and generated
`backup_subtitles.zip` archives are intentionally excluded from Git. Do not
publish them with bug reports. A useful report includes the program version,
the relevant options, a small synthetic reproduction, and the displayed error.

## Updating a portable Windows installation

Close the program and extract the new release to a separate folder. To retain
personal data, copy these items from the old folder to the matching locations
in the new folder:

- `dictionaries/user`
- `dictionaries/universes`
- `dictionaries/options.ini`
- `dictionaries/gui_theme.json`

Copy `dictionaries/session_state.json` only when deliberately resuming an
interrupted scan against files that remain in the same locations. The session
log is optional. Do not copy the old `dictionaries/base` folder; each release
includes the correct SCOWL base dictionaries and attribution.

