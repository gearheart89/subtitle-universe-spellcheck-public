# Subtitle Universe Spellcheck

Subtitle Universe Spellcheck is a conservative, interactive cleanup and
spellcheck tool for `.srt` subtitle collections. It is designed for projects
with fictional names, acronyms, constructed-language terms, and recurring
transcription errors that do not belong in a general English dictionary.

The Version 1 release candidate is a single-file, standard-library-only Python
application. It supports American and British English base dictionaries,
personal dictionaries, optional project-specific “Universe” dictionaries,
deterministic formatting cleanup, interactive spelling decisions, persistent
substitutions, opt-in Google searches for a selected subtitle line, session
recovery, repeatable undo, and atomic subtitle writes.

## Requirements

- Python 3.9 or later
- Windows, macOS, or Linux terminal
- No third-party Python packages

## Run

```console
python subtitle_cleanup.py
```

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

Automatic spelling guesses are deliberately avoided. Unknown words are shown
with context and require an explicit user decision. Deterministic formatting
rules and substitutions can run automatically.

See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for the menu workflow, dictionary
scopes, backup behavior, spellcheck actions, and recovery guidance.

## Safety

- Work on copied subtitles until you are comfortable with your selected
  options and dictionaries.
- Enable ZIP backups before editing irreplaceable files.
- Formatting and substitutions can affect many cues at once; review a sample
  output before processing a large collection.
- Subtitle writes and newly created ZIP archives are published atomically.
- Encoding, BOM, predominant newline style, exact terminal newline sequence,
  cue indices, and timestamps are preserved as documented in `SPEC.md`.

No subtitle files, user dictionaries, Universe dictionaries, session state,
event logs, or backup archives are distributed by this repository.

## Test

```console
python -m unittest discover -s tests -v
```

The release candidate has 207 deterministic regression tests. It has also been
validated against synthetic end-to-end fixtures and a read-only 213-file,
149,058-cue corpus audit; that copyrighted corpus is not included.

## Documentation

- [User guide](docs/USER_GUIDE.md)
- [Product specification](SPEC.md)

## Licensing and dictionary attribution

The application source is available under the [MIT License](LICENSE).

The packaged American and British base vocabularies are generated from SCOWL
2026.02.25. Their source, generation choices, and required redistribution
notice are in [`dictionaries/base`](dictionaries/base/README.md).
