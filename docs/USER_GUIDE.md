# Subtitle Universe Spellcheck user guide

## Before the first scan

Run `python subtitle_cleanup.py` from a terminal. The tool uses only Python's
standard library. It keeps writable settings and dictionaries beside the
script, so install it in a folder where your account can create files.

For the portable Windows release, extract the complete folder before running
`SubtitleUniverseSpellcheck.exe`. Do not run the executable from inside the
ZIP. Windows may show an **Unknown publisher** warning because the executable
is intentionally unsigned. Compare the downloaded ZIP with the accompanying
SHA-256 file before extracting it.

Open **Options menu → File Discovery and Safety** and enable ZIP backups before
editing irreplaceable subtitles. Backups contain only `.srt` files and are
created before formatting or spellcheck changes begin.

## Choosing a scan

The main menu offers three scan modes:

1. **Adjust formatting only** applies enabled deterministic cleanup rules and
   does not ask spelling questions.
2. **Standard spellcheck with formatting correction** loads one Base language
   and its always-active User dictionary.
3. **Spellcheck with optional Universe dictionary and formatting correction**
   additionally lets you select or create a project-specific dictionary, or
   continue without one.

Each new scan first searches recursively from the script folder. The summary
continues automatically after five seconds. Press Enter during the countdown
to choose another folder. In the folder browser, use a listed number to enter
a child folder, `U` to move up, `S` to select the displayed folder, `11` and
`33` for pagination, or type an absolute or relative path.

## Dictionary layers

- **Base** is the packaged read-only American or British English vocabulary.
- **User** stores personal words, names, and substitutions for one Base
  language and is loaded every time that language is selected.
- **Universe** is the narrowest layer: optional terminology for one show,
  franchise, game, book series, or other project.

Accepted words are case-insensitive. Names provide authoritative casing.
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
- `9`: add an accepted word, authoritative name, accepted phrase, or
  authoritative name phrase
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

## Formatting and common-error cleanup

The categorized Options menu controls acronym normalization, bracketed sound
effects, mostly-uppercase repair, line reflow, speaker-break preservation,
dropped-speaker detection, informal `-in'` recognition, and deterministic
common-error cleanup. The Common Error Cleanup screen includes examples for
music-symbol and punctuation mojibake, invisible characters, spacing, and
simple italic-tag repairs. Suspicious quote, bracket, tag, and repeated-
punctuation findings are reported but not edited.

Use `?` after an option number to see its detailed explanation.

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

## Dictionary maintenance

The main menu provides User and Universe maintenance plus review screens for
recent additions. Universe maintenance supports creation, duplication,
renaming, deletion with typed confirmation, statistics, and direct editing of
words, names, and substitutions. Universe lists are alphabetical and show ten
entries per page; use `11` and `33` to move between pages.

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

Copy `dictionaries/session_state.json` only when deliberately resuming an
interrupted scan against files that remain in the same locations. The session
log is optional. Do not copy the old `dictionaries/base` folder; each release
includes the correct SCOWL base dictionaries and attribution.

