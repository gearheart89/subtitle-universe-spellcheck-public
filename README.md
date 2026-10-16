# Subtitle Universe Spellcheck

Subtitle Universe Spellcheck is a conservative, interactive `.srt` cleanup and
spellcheck application with graphical and command-line interfaces. It is
designed for subtitle collections containing fictional names, acronyms,
constructed-language terms, and recurring transcription errors that do not
belong in a general English dictionary. Both interfaces use the same tested
engine and safety boundaries.

Version 1 capabilities include:

- Deterministic formatting and common-error cleanup with validation reports.
- Interactive American or British English spellcheck with User and optional
  project-specific Universe dictionaries for words, names, acronyms, exact
  phrases, and persistent substitutions.
- Occurrence, session, Universe, and always-active User replacement scopes,
  plus dictionary and recent-addition maintenance.
- Explicit capitalization modes, opt-in Google searches for a selected
  subtitle line, repeatable undo, and crash/power-loss recovery.
- Grouped ZIP backups, confirmation-protected restoration, external-change
  detection, format-preserving atomic subtitle writes, and rollback safeguards.
- Ocean, Dark, and editable Custom GUI themes; the command-line interface
  retains the same core scan, formatting, dictionary, and recovery behavior.

The application runtime uses only Python's standard library. The tested engine
and command-line interface remain in one file, with a thin Tkinter GUI that
calls the same engine rather than duplicating subtitle behavior.

The shared formatter includes an enabled-by-default correction for standalone
lowercase pronoun `i` and `i'm`/`i'd`/`i'll`/`i've`. CLI scans and GUI scan
preparation use the same tag-, abbreviation-, and URL-aware implementation.

## Requirements

- Python 3.9 or later with Tkinter
- Windows, macOS, or Linux
- No third-party Python packages

Some Linux distributions package Tkinter separately as `python3-tk` or
`python3-tkinter`. Windows is the currently hardware-tested platform. macOS and
Linux are expected to work and have automated cross-platform coverage, but have
not yet been validated on physical systems by the project.

## Run

```console
python app/subtitle_cleanup.py
```

Both interfaces are available directly from source:

```console
python app/subtitle_gui.py
python app/subtitle_gui.py --cli
```

The root `SubtitleUniverseSpellcheck.pyw` is a portable interface chooser. On
its first launch, select `1` for the GUI or `2` for the CLI; it will keep asking
until one of those choices is entered. The choice creates either
`launch gui.txt` or `launch cli.txt` beside the launcher. On later launches it
shows the saved mode and gives you five seconds to press Enter and choose
again. You can also delete the marker file to restore the first-run choice.

Windows `.pyw` launches have no text console, so they show the equivalent small
choice window; choosing CLI opens a real console. On macOS or Linux, run
`python3 SubtitleUniverseSpellcheck.pyw` from a terminal. A saved GUI choice is
detached from that terminal, while CLI remains attached. This override window
means a mistaken GUI choice on console-only Linux is recoverable: run the
launcher again, press Enter during the countdown, and choose CLI. Desktop
double-click handling for `.pyw` files depends on the local file association.
The published `1.0.0-rc3` Windows executable remains the earlier command-line
release. Current Windows builds open the GUI by default; run
`SubtitleUniverseSpellcheck.exe --cli` from a terminal to use the same package's
command-line interface.

Windows users may instead download the unsigned portable ZIP from the GitHub
Release. Extract the complete `SubtitleUniverseSpellcheck` folder and run
`SubtitleUniverseSpellcheck.exe`. Windows may display an **Unknown publisher**
warning because the executable is not code signed. Verify the ZIP against its
published SHA-256 file before extracting it.

On first run, the program creates ignored writable data beneath
`dictionaries/user` and `dictionaries/universes`, plus local option, session,
and event-log files. These files are not part of the repository.

The program initially searches recursively from its own folder. It displays a
summary and waits five seconds; press Enter during that countdown to choose a
different folder with the built-in folder browser or a typed path.

## Main workflows

- Formatting-only cleanup
- Standard spellcheck using Base and User dictionaries
- Spellcheck with an optional Universe dictionary
- User and Universe dictionary maintenance
- Review of recent dictionary and substitution additions
- Categorized options and common-error cleanup
- Interrupted-session recovery

## Update checks

On first launch, before making any network request, both the GUI and CLI ask
whether automatic update checks may run at startup. The answer is saved in the
portable options file and can be changed later under **Menus and Display**. If
enabled, the program makes one short, nonfatal request to this project's public
GitHub Releases page. Offline use remains supported: a failed check is ignored
and never prevents access to subtitle work.

When a newer stable release is available, the program asks before downloading
anything and lets you choose the destination. A frozen Windows executable
offers the matching Windows-architecture ZIP. Source launches on Windows,
macOS, or Linux offer the universal source ZIP. The matching `.sha256` file is
required, and the ZIP is published at the chosen location only after its hash
and ZIP structure are verified. This first-stage updater only downloads the
ZIP and checksum; it does not extract, install, replace, restart, or remove any
application or personal-data files.

Automatic spelling guesses are deliberately avoided. Unknown words are shown
with context and require an explicit user decision. Deterministic formatting
rules and substitutions can run automatically.

See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for the menu workflow, dictionary
scopes, backup behavior, spellcheck actions, and recovery guidance.

## Safety

- Work on copied subtitles until you are comfortable with your selected
  options and dictionaries.
- Enable ZIP backups before editing irreplaceable files.
- Restoring a grouped backup overwrites current subtitles and requires the exact typed confirmation `YES`.
- Formatting and substitutions can affect many cues at once; review a sample
  output before processing a large collection.
- Subtitle writes and newly created ZIP archives are published atomically.
- Encoding, BOM, predominant newline style, exact terminal newline sequence,
  cue indices, and timestamps are preserved as documented in `SPEC.md`.

No subtitle files, user dictionaries, Universe dictionaries, session state,
event logs, or backup archives are distributed by this repository.

When upgrading a portable Windows copy, preserve
`dictionaries/user`, `dictionaries/universes`,
`dictionaries/options.ini`, and `dictionaries/gui_theme.json`. Copy them into the same locations in the newly
extracted folder while the program is closed. You may also copy the single
`launch gui.txt` or `launch cli.txt` marker to preserve the root launcher choice;
otherwise the new copy asks again. The packaged
`dictionaries/base` folder belongs to the release and should be replaced by
the new version.

## Test

```console
python -m unittest discover -s tests -v
```

The current development tree has hundreds of deterministic regression tests.
The exact current baseline is recorded in `STATUS.md` to avoid duplicating a
fast-changing count here. It has also been validated against synthetic
end-to-end fixtures and a read-only 213-file, 149,058-cue corpus audit; that
copyrighted corpus is not included.

## Documentation

- [User guide](docs/USER_GUIDE.md)
- [Product specification](https://github.com/gearheart89/subtitle-universe-spellcheck-public/blob/main/SPEC.md) (repository development document)

## Building the multi-platform source release

The universal source archive requires Python 3.9 or later with Tkinter on the
destination computer. Build it on Windows, macOS, or Linux with:

```console
python tools/build_multiplatform_release.py
```

The ZIP and matching SHA-256 file are written beneath `artifacts`. The builder
uses an explicit public-file allowlist: it includes the three runtime launchers,
README, user guide, license, and immutable SCOWL base dictionaries, but excludes
`SPEC.md`, `STATUS.md`, findings, tests, build tools, subtitles, and writable
dictionary/session data. Before publishing the checksum, it reopens the ZIP,
CRC-checks every member, and verifies the archive against that exact allowlist.

## Rebuilding the Windows package

The Windows executable is a PyInstaller one-folder build. PyInstaller is a
build dependency only; the resulting application does not require Python.

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\tools\build_windows.ps1 -PythonExecutable .\.venv-build\Scripts\python.exe
```

The script creates an unsigned ZIP and matching SHA-256 file beneath
`artifacts`. It copies only the immutable base dictionaries, public
documentation, and applicable runtime redistribution notices—never local User
or Universe dictionaries, subtitle files, session state, logs, or backups. The
single executable opens the GUI by default and retains a console when invoked
with `--cli`; its normal frozen GUI startup releases the otherwise unnecessary
console window. Before creating the ZIP, the script verifies the executable's
reported version, all required public files/notices, and the absence of known
writable runtime-data paths.

## Licensing and dictionary attribution

The application source is available under the [MIT License](LICENSE).

The packaged American and British base vocabularies are generated from
[SCOWL 2026.02.25](https://github.com/en-wl/wordlist/tree/rel-2026.02.25).
Their source, generation choices, and required redistribution
notice are in [`dictionaries/base`](dictionaries/base/README.md).
