# Packaged base dictionaries

`american_words.txt` and `british_words.txt` are generated from SCOWL
(Spell Checking Oriented Word Lists), release `2026.02.25`, Git tag
`rel-2026.02.25`, commit `7e99edab8e32f9f9ea2b15f249ca8d4d67237410`.

Source: <https://github.com/en-wl/wordlist/tree/rel-2026.02.25>

The SCOWL database was built in UTF-8 mode with:

```powershell
python -X utf8 combine.py create-db scowl.db
```

The source lists were extracted at SCOWL's recommended spellchecking size 60:

```powershell
# American English, default variants.
python -X utf8 -m libscowl --db scowl.db word-list 60 A 1 --deaccent

# British English, including -ise, Oxford -ize, and other accepted variants.
python -X utf8 -m libscowl --db scowl.db word-list 60 B,Z 5 --deaccent
```

The extracted entries were converted to lowercase, limited to the token forms
the application recognizes (`A-Z`, with at most one internal apostrophe),
deduplicated, and sorted. The packaged American list contains 107,876 entries;
the packaged British list contains 111,181 entries. `--deaccent` supplies the
ASCII forms expected by the application's current tokenizer.

These are immutable base vocabularies. User additions belong under
`dictionaries/user/`, and universe-specific terminology belongs under
`dictionaries/universes/`; neither location is tracked by Git.

SCOWL permits redistribution of generated word lists when its copyright and
permission notice are retained. The complete upstream notice is included in
`SCOWL-COPYRIGHT.txt`.
