# TASK-001: Load the ГРАО KADS file from a committed zip

Depends on: None
Suggested commit: `feat(ingest): load the ГРАО KADS file from a committed zip`

## Goal

Commit the ГРАО KADS archive into the repo and let `grao_loader` read it directly,
so district data is never again missing locally just because nobody could obtain
the file.

## Files

- `data/grao/kads-03-06.zip` — new. Copied from `initial/data/grao/kads-03-06.zip`
  (92 KB), the archive as published at `varna.bg/upload/<id>/kads-03-06.zip`.
- `data/grao/README.md` — new. Provenance: the source URL it came from, the
  election cycle it belongs to, and a pointer to the refresh runbook in
  `docs/OPERATIONS.md`. Mirrors `data/varna_municipality.README.md`.
- `src/yasli/ingest/grao_loader.py` — `parse_file()` branches on suffix: a `.zip`
  is opened with `zipfile`, its single member read, and the same bytes handed to
  the existing windows-1251 decode. Add `DEFAULT_ARCHIVE` (resolved off the package,
  not the process CWD — mirror `institution_locations_loader.DEFAULT_CSV`) and make
  the CLI's positional `path` optional with that default.
- `tests/test_grao_loader.py` — new cases below.

## Acceptance

- [ ] `parse_file()` yields identical rows for the `.zip` and for the `.txt`
      extracted from it
- [ ] `python -m yasli.ingest.grao_loader` with no argument loads the committed
      archive and reports `rows=47579 streets=2071`
- [ ] A zip holding zero members, or more than one, fails with a clear message and
      the existing exit code 3 — not a `zipfile` traceback
- [ ] A `.txt` path still works exactly as before; every pre-existing test passes
      untouched
- [ ] `УЛ.Н.Й.ВАПЦАРОВ` number 7 parses with `district_code='02'` from the committed
      archive

Evidence: the `grao_loader done rows=… streets=…` summary line from a real run
against the committed zip, plus pytest output for the new cases.

## Steps

### RED
- [ ] Add a test that `parse_file()` over a zip fixture and over its extracted text
      produce equal row lists
- [ ] Add tests for the empty-archive and multi-member-archive error paths
- [ ] Add a test that the CLI's default path resolves to the committed archive and
      that the archive exists on disk (a data test, like
      `tests/test_institution_locations_data.py`)

### GREEN
- [ ] Copy the archive into `data/grao/` and write its README
- [ ] Add the zip branch, `DEFAULT_ARCHIVE`, and the optional CLI positional

### REFACTOR
- [ ] Keep the decode/parse path single — the zip branch must only produce bytes,
      never a second parsing route

## Notes

Do not commit the extracted `.txt`. `docs/OPERATIONS.md` already warns that the
plaintext gets mangled by Git, editors and `unzip`; the archive is the artifact of
record and the loader reads it in memory.

Resolve the default path off the installed package (`Path(__file__).parents[…]`),
not `Path("data/…")` — `just be-test` and `just be-seed` run from different
working directories.
