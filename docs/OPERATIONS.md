# Operations runbook

Operator-facing tasks beyond the weekly Railway cron set up in
[`DEPLOYMENT.md`](DEPLOYMENT.md). One-off maintenance, reference data
refreshes, post-mortem digging.

---

## ГРАО quarterly reference-data refresh

The ГД ГРАО (Главна Дирекция ГРАО) Address Classifier is the ground truth
for the **(street, building number, entrance) → район** mapping that
powers nursery + preschool routing in `/api/match`. The file is republished
per Bulgarian election cycle (roughly yearly, with off-cycle by-elections
occasionally minting a fresh release). The first iteration of the refresh
process is manual — automating the probe is a separate change.

### When to refresh

- After every Bulgarian election cycle ends, check for a new file.
- If `addresses_district_unstamped` in the weekly ingest summary climbs
  past ~2% of in-city addresses, the local `grao_addresses` table is
  probably stale — new construction is appearing.
- If a user reports a clearly mis-routed nursery or preschool in a known
  район, suspect a районна reassignment and refresh.

### Where to get the file

ГРАО publishes the file at `https://varna.bg/upload/<numeric-id>/kads-03-06.zip`.
The numeric id rotates each election. To find the current id:

1. Open <https://varna.bg/> in a browser and find the latest elections
   landing page (usually titled "Избори …" with the cycle date).
2. The page links to a ZIP archive named `kads-03-06.zip`. Right-click,
   copy link. The URL has the form
   `varna.bg/upload/<6-digit-id>/kads-03-06.zip`.
3. Download the ZIP (~700 KB).
4. Extract — the archive contains a single plaintext file (typically
   also named `kads-03-06.txt`). The file is windows-1251 encoded with
   CRLF line terminators.

If `varna.bg` is unreachable, the same file (and the cycle archive) is
mirrored on `https://www.grao.bg/` — search the elections / addresses
section. The two sources are byte-identical per cycle.

### Loading the file into the database

Once the plaintext file is on a machine that can reach the production
Postgres (Railway's "exec into deployment" shell works; or run locally
against a tunneled `DATABASE_URL`):

```bash
# 1. Verify the file decodes correctly.
file kads-03-06.txt
iconv -f windows-1251 -t utf-8 kads-03-06.txt | head -5

# 2. Load it. TRUNCATE grao_addresses + bulk INSERT inside one transaction.
python -m yasli.ingest.grao_loader /path/to/kads-03-06.txt

# Expected output:
# grao_loader done rows=<50000-100000> streets=<3000-6000> skipped=0
```

If the loader exits non-zero with `error: file is not valid windows-1251`,
the file got mangled by Git, an editor, or `unzip` (rare). Re-extract from
the ZIP. The loader does not write anything if decoding fails.

### Propagating district reassignments

After a reload, the `grao_addresses` table is current but
`addresses.district_code` and `institutions.district_code` (for KG/PG —
nurseries are API-sourced and untouched) still reflect the previous
ГРАО snapshot. Run the **non-gated** restamp to propagate:

```bash
python -m yasli.ingest restamp-districts

# Expected output:
# restamp-districts done addresses={primary:<N>,fallback1:<n>,fallback2:<n>} \
#   addresses_district_unstamped=<n> institutions={primary:<N>,fallback:<n>} \
#   institutions_district_unstamped=<n>
```

This command operates inside a single transaction. On any failure the
DB is rolled back to the previous stamp. Nurseries' `district_code` is
never touched — the kind filter excludes them from both the
catchment-majority and address-parse paths.

### Verification after refresh

Spot-check a known address against the new district stamp:

```sql
SELECT a.id, s.raw_name, a.number_int, a.district_code
FROM addresses a JOIN streets s ON s.id = a.street_id
WHERE s.search_norm LIKE '%vapcarov%' AND a.number_int = 7;
-- Expect district_code = '02' for ул. Н.Й. Вапцаров №7 (район Приморски).
```

Check the overall NULL rate:

```sql
SELECT
  COUNT(*) FILTER (WHERE district_code IS NULL)   AS no_district,
  COUNT(*) FILTER (WHERE settlement_code IS NULL) AS no_settlement,
  COUNT(*)                                        AS total
FROM addresses;
-- Expect no_settlement ≈ 0 (the settlement pass covers every Varna street).
-- no_district = village addresses (Каменар/Тополи/Звездица/Константиново/Казашко)
-- plus residual ГР.ВАРНА unmatched rows; aim for the city residual under 2%.
```

Then hit `/api/match` for a couple of addresses in different районs and
confirm the expected nurseries + preschools come back. Spot-check at
least one village address — it should return a `settlement_only`
envelope.

### Rollback

If a reload produces obviously wrong stamps (e.g. mass NULLs, wrong
codes), there is no "previous ГРАО" version in the DB. Two options:

1. **Re-extract the previous cycle's ZIP** (you should keep one per
   refresh as the rollback artifact) and reload it via the loader, then
   re-run `restamp-districts`.
2. **Truncate** `grao_addresses` and reset the stamps:
   ```sql
   TRUNCATE grao_addresses;
   UPDATE addresses    SET district_code = NULL, settlement_code = NULL;
   UPDATE institutions SET district_code = NULL WHERE kind <> 'nursery';
   ```
   The next weekly ingest will leave all KG/PG `district_code` columns
   at NULL until the next loader run; `/match` will return the
   `district_unknown` envelope for affected queries.

### What the weekly cron does automatically

`backend-ingest` runs both **gated** stamping passes after the snapshot
upsert phase:

1. `stamp_addresses_unmatched()` — only fills in addresses with
   `district_code IS NULL` (new construction the previous weekly run
   missed because ГРАО had nothing to join against).
2. `stamp_institutions_unmatched()` — only fills in KG/PG with
   `district_code IS NULL`. Nurseries are never touched by this pass.

The gated passes will NOT propagate ГРАО reassignments that affect
already-stamped rows. That is by design (the weekly pipeline must not
silently churn district stamps). Use `restamp-districts` for that.
