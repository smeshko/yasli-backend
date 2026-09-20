# `kads-03-06.zip`

The ГД ГРАО (Главна Дирекция ГРАО) Address Classifier for Varna — the
ground truth for the **(street, building number, entrance) → район**
mapping that powers nursery and preschool routing in `/api/match`.

`yasli.ingest.grao_loader` reads this archive directly (it is
`DEFAULT_ARCHIVE`, the CLI's default path), decoding the single member in
memory. `python -m yasli.seed` loads it as its ГРАО step, which is why
district data is present on a fresh local database without anyone having to
find the file first.

| | |
| --- | --- |
| Source | `https://varna.bg/upload/<6-digit-id>/kads-03-06.zip`, published by ГД ГРАО via Община Варна |
| Election cycle | 2026-02 (archive member dated 2026-02-25) |
| Member | a single `kads-03-06.txt`, 700,748 bytes, windows-1251, CRLF |
| Parses to | 47,579 rows across 2,071 streets, райони `01`–`05` |
| SHA-256 | `32279ee1566f4ab03cf080ebba2e28d1ec25f24fff8d98ce3a5f461d5c118dd2` |

## Why the zip and not the extracted text

The archive is what ГРАО publishes, and it is a seventh of the bytes (92 KB
against 688 KB). It is also the form least likely to be corrupted in
transit: `docs/OPERATIONS.md` warns that the windows-1251 plaintext gets
mangled by Git, editors and `unzip`, and a mangled file is exactly what the
loader's `error: file is not valid windows-1251` exit code 3 exists to
catch. Committing the archive removes that failure mode rather than
documenting it.

The loader's zip branch only produces bytes — the same decode and the same
state machine handle both suffixes, so a `.txt` path still behaves exactly
as it did.

## Refreshing

The numeric id in the URL rotates each election cycle, so there is no
stable link to automate against. The full procedure — when to refresh, how
to find the current id, how to load it and how to propagate районни
reassignments afterwards — is `docs/OPERATIONS.md` § "ГРАО quarterly
reference-data refresh". To refresh the committed copy: download the new
archive, drop it in here under the same name, and run
`uv run pytest tests/test_grao_loader.py` — the committed-data tests pin the
row and street counts and the ВАПЦАРОВ №7 → район `02` case, so a truncated
or wrong-cycle download fails rather than seeds quietly.
