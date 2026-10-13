# Subtitle Universe Spellcheck Specification

## 1. Purpose

Subtitle Universe Spellcheck is a menu-driven, standard-library Python tool for safely cleaning and interactively spellchecking `.srt` subtitle collections. It is designed for shows and fictional settings containing invented terminology, inconsistent source spellings, unusual names, apostrophes, and acronyms.

The tool may automatically apply deterministic formatting rules and explicitly configured substitutions. It must not broadly guess spelling corrections. Unknown words must be presented to the user through an interactive review workflow.

## 2. Dictionary model

The tool uses three dictionary layers:

- **Base dictionary:** immutable American or British English vocabulary. Exactly one base language is active.
- **User dictionary:** personal words, names, and substitutions that are always loaded for the selected base language.
- **Universe dictionary:** optional words, names, and substitutions for one specific show, franchise, or project. At most one universe is active during a run.

Dictionary precedence and casing authority are:

1. Active session substitutions.
2. Universe and user substitutions.
3. Universe and user name lists, preserving their stored case.
4. Known acronyms.
5. Universe and user word lists.
6. Base vocabulary.
7. Conservative sentence-casing fallback.

Internal apostrophes, including straight and curly forms, are part of a word token.
Known-token checks use direct membership in the active base, user, and universe
sets; scanning must not rebuild their combined vocabulary for every token.

## 3. Repository and runtime layout

```text
subtitle_cleanup.py
SPEC.md
STATUS.md
docs/
    FINDINGS.md
tests/
dictionaries/                  # base assets tracked; writable runtime data ignored
    options.ini
    session_state.json
    session_log.jsonl
    base/
        american_words.txt
        british_words.txt
    user/
        american_words.txt
        american_names.txt
        american_substitutions.tsv
        british_words.txt
        british_names.txt
        british_substitutions.tsv
    universes/
        <Universe Name>/
            words.txt
            names.txt
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

Word and name files contain one entry per line. Substitution files contain `input<TAB>output`. Substitution input matching is case-insensitive; output is emitted exactly as stored. Lists are sorted after maintenance operations, with substitutions sorted by input.

Multiword entries are exact, phrase-scoped dictionary entries. Multiword names
provide authoritative casing for the complete phrase; multiword words accept
the complete phrase without imposing name casing. A component is not accepted
outside the complete phrase unless it also has its own single-word entry.
Phrase matching is case-insensitive, requires whitespace rather than intervening
punctuation, and may cross a subtitle line wrap within one cue. Simple plural
and possessive forms of known acronyms retain the acronym's canonical casing,
for example `MALPs`, `GDOs`, and `SGC's`.

The application remains a single-file, standard-library-only Python program unless a later design decision explicitly changes that constraint.

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
11. Flush session log

0. Exit
```

Menus clear the console before rendering and provide a way to return without making changes. Help screens explain the dictionary layers, supported cleanup operations, session recovery, and the conservative correction policy.

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
submenus. They include:

| Option | Default |
| --- | ---: |
| Scan folders recursively | `true` |
| Recognize informal `-in'` forms when the `-ing` word is known | `true` |
| Remove periods from abbreviations | `true` |
| Convert `--` and `...` to `…` | `false` |
| Title-case bracketed sound effects | `true` |
| Fix capitalization when a line is mostly uppercase | `true` |
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

When informal dropped-`g` recognition is enabled, a token ending in straight
or curly apostrophe after `-in` is accepted only if adding `g` produces a word
in the active dictionaries. Thus `goin'` and `goin’` are recognized when
`going` is known; unrelated apostrophe fragments remain unknown.

Universe display limits affect menus only. Longer internal names are permitted, but values above 32 require a layout warning and explicit acknowledgement.

## 6. Discovery and target selection

For main-menu actions 1 through 3, the tool first scans from the script folder using the configured recursive behavior.

When subtitles are found, it reports the count and up to five top-level folders, then starts a five-second countdown. Pressing Enter during the countdown opens a custom-location prompt. When no subtitles are found, it explains the searched location and prompts immediately.

The custom-location prompt is a folder browser beginning at the process's
current working directory. It lists immediate child folders alphabetically,
ten per page. `1` through `10` enter a folder on the current page, `U` goes up
one level, `S` selects the displayed folder, `11` and `33` navigate pages when
available, and `0` returns to the main menu. The user may type an absolute or
relative folder path instead of browsing; relative paths are resolved from the
displayed folder first while retaining script-folder and process-folder
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
4. Optional dotted-acronym normalization.
5. Optional bracketed sound-effect title casing.
6. Optional mostly-uppercase repair.
7. Optional dropped-speaker-break detection.
8. Optional subtitle reflow.

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

### 9.2 Dotted acronyms

Known dotted acronyms are normalized to their preferred undotted casing, for example `M.A.L.P.` to `MALP`, `S.G.C.` to `SGC`, and `D.H.D.` to `DHD`.

Simple plural and possessive suffixes are retained. A period serving as true
sentence punctuation is also retained, so sentence-final `G.D.O.s.` becomes
`GDOs.` rather than `GDOs`.

### 9.3 Bracketed sound effects

Bracketed sound effects are title-cased, retaining lowercase connector words except at the beginning or end. Example: `[SOUND OF A DOOR OPENING]` becomes `[Sound of a Door Opening]`.

### 9.4 Mostly-uppercase repair

Lines with more than 80 percent uppercase letters are conservatively sentence-cased using the dictionary precedence rules. Stored names and acronyms retain authoritative casing.

The uppercase determination is taken from the source line before configured
substitutions introduce canonical mixed-case output. A correction such as
`TEALD` to `Teal'c` must not prevent the rest of an originally uppercase line
from being repaired.

### 9.5 Ambiguous `us` and `US`

Mixed-case lowercase `us` remains unchanged. During all-caps repair, a bare `US` defaults to the pronoun `us` unless a strong United States context is detected. Pronoun patterns override country patterns.

Protected country contexts include `US military`, `US government`, service branches, `US forces`, `US embassy`, and prepositional forms such as `in the US`, `to the US`, and `from the US`. Pronoun forms include `the two of us`, `all of us`, `both of us`, `one of us`, `just us`, `with us`, and verb-object phrases such as `told us`.

Ambiguous cases prefer lowercase `us`. Dotted `U.S.` and `U.S.A.` are protected and normalized according to the abbreviation option.

### 9.6 Dropped speaker breaks

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

### 9.7 Line reflow

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
- `9` Add word, name, or exact phrase to a dictionary.
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
| Add word/name/phrase 9 | 3 when available, 4 |

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
authoritative name, an accepted exact phrase, or an authoritative exact name
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

Session state is written through a sibling temporary file and atomically
replaced. A transient Windows permission error during replacement is retried
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

User maintenance first selects American or British English, then words, names, or substitutions. Addition/removal accepts one value or a delimited list. Whitespace is trimmed. Multiword entries may be stored as accepted exact phrases, redirected to authoritative name phrases, edited, or omitted.

Universe maintenance supports create, duplicate, rename, delete with typed `DELETE` confirmation, statistics, and direct word/name/substitution maintenance. Every universe contains `words.txt`, `names.txt`, and `substitutions.tsv`.

## 13. Version 1 acceptance criteria

Version 1 is complete when all of the following are implemented and tested:

- Folder structure creation and persistent options.
- Menus and help screens.
- Automatic and custom recursive discovery.
- Grouped ZIP backups.
- Lossless SRT structure handling.
- Formatting-only pipeline and all rules in Section 9.
- Base, user, and universe dictionary loading.
- Substitution loading and application.
- Interactive prompt, valid scope matrix, and invalid-scope guidance.
- Session ignores, substitutions, recovery, and basic repeatable undo.
- User and universe maintenance.
- Recent addition review screens.
- Session log flushing.

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
single-file, standard-library-only application runtime. A Windows executable
must be built and smoke-tested on Windows. Upgrades preserve personal data by
copying `dictionaries/user`, `dictionaries/universes`, and optionally
`dictionaries/options.ini` into a newly extracted release while the program is
closed. The base dictionary folder is replaced by each release.

## 15. Deferred ideas

- Richer undo throughout all maintenance screens.
- Improved acronym and HTML/italic handling.
- Dry-run reports and line-by-line previews.
- Detailed statistics and exportable reports.
- Configurable capitalization exceptions.
- Malformed timing-block diagnostics.
