# Decisions — institution-profile-endpoint

Date: 2026-09-16

## 1. ETag prefix stays `v1-`

### Options Considered

1. Keep `"v1-"` plus 16 hex characters of the body's sha256 — the prefix is an opaque namespace; the hash
   already changes because the body changes.
2. Bump to `"v2-…"` to signal that the response contract changed.

### Dependencies

`_etag` hashes the exact body bytes, so every payload's ETag changes the
moment a key is added. No client parses the prefix; the frontend sends it
back verbatim in `If-None-Match`. Existing tests assert `startswith('"v1-')`.

### Selected Option

Option 1.

### Rationale

A bump buys nothing a client can observe: cached `v1-` tags already miss
against the new bodies. It would only churn tests and the OpenSpec wording.
The prefix is reserved for a change where the *same* bytes must be treated as
a different resource, which this is not.

### Rejected Options

- Option 2 — signalling with no consumer; pure churn.

## 2. The list's `location` comes from a LEFT OUTER JOIN on the `main` row

### Options Considered

1. `select(...).outerjoin(InstitutionLocation, and_(kind == kind,
   external_id == external_id, role == 'main'))` in the existing list
   statement, keeping the `ORDER BY` untouched.
2. A second query fetching every `main` row, merged into the list in Python
   by `(kind, external_id)`.
3. Leave the list alone — rejected by the user on 2026-09-16 (they want the
   list to carry `location`).

### Dependencies

`uq_institution_locations_main` is a partial unique index on
`(kind, external_id) WHERE role = 'main'`, so the join can match at most one
row per institution and cannot multiply list rows. The `role = 'main'`
predicate must live in the `ON` clause: in a `WHERE` clause it would turn the
outer join into an inner one and drop institutions with no location row.

### Selected Option

Option 1.

### Rationale

One round trip, no Python merge, and the ordering clause — which two tests
pin — is not touched. The uniqueness argument is enforced by the database,
not assumed.

### Rejected Options

- Option 2 — two queries and a dict merge for no gain; the "can't multiply"
  guarantee is the same either way.
- Option 3 — user decision.

## 3. The empty-string storage sentinel becomes `null` at the API boundary

### Options Considered

1. Map `label == ""` and `address == ""` on branch rows to `null` in the
   response.
2. Pass `""` through as stored.

### Dependencies

`institution_locations` stores absent `label`/`address` as `""` only so the
UNIQUE tuple `(kind, external_id, role, label, address)` constrains — Postgres
treats NULLs as distinct. It is a storage convention, not a value. The epic
says: `null` where data is absent.

### Selected Option

Option 1.

### Rationale

The frontend should not need to know a database trick. `null` is what every
other absent field in the payload uses, and the epic's acceptance criterion
is phrased in terms of `null`.

### Rejected Options

- Option 2 — leaks a storage convention and makes "absent" look like an
  empty value.

## 4. `external_id` is validated by lookup, not by length

### Options Considered

1. `external_id: str = Path(...)` with no length constraint; anything that
   matches no row is a 404.
2. `Path(..., max_length=16)` to mirror the column width, returning 422 for
   longer values.

### Dependencies

`institutions.external_id` is `String(16)`. The frontend builds the path from
a committed manifest of real ids, so malformed values are a curiosity, not a
flow. The epic's criterion: unknown pair → 404, invalid `kind` → 422.

### Selected Option

Option 1.

### Rationale

A 17-character id is "no such institution", which is what 404 says. Length
is an implementation detail of the column, and a 422 would leak it into the
contract for no client benefit. `kind` is different: its value set is the
contract, so 422 is right there.

### Rejected Options

- Option 2 — encodes a column width into the public API.
