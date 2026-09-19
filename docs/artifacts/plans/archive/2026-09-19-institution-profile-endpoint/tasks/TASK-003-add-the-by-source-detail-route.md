# TASK-003: Add the by-source detail route

Depends on: TASK-002
Suggested commit: `feat(api): add GET /institutions/by-source/{kind}/{external_id}`

## Goal

The same detail payload is reachable by the stable natural key at
`GET /api/institutions/by-source/{kind}/{external_id}`, with identical body,
ETag, cache headers and error semantics to the id route, built by one shared
function.

## Files

- `src/yasli/routes/institutions.py` — extract
  `_detail_response(session, institution_row, if_none_match) -> Response`
  (coverage query and fold, `_locations_for`, serialise, ETag, 304) and
  `_institution_row(session, *where) -> Row | None` (the `_INSTITUTION_COLUMNS`
  SELECT with a caller-supplied WHERE); `get_institution` becomes a lookup by
  `Institution.id` plus a call to the builder; new handler
  `get_institution_by_source(kind: Kind = Path(...), external_id: str =
  Path(..., description="institutions.external_id"), session, if_none_match)`
  registered at `/institutions/by-source/{kind}/{external_id}` with
  `response_model=InstitutionDetail`. Module docstring lists the third public
  path.
- `tests/test_institutions.py` — by-source tests below.
- `tests/test_institutions_openapi.py` — path-parameter and schema assertions
  for the new path.
- `docs/ARCHITECTURE.md` — Public API table: reword the
  `GET /api/institutions` and `GET /api/institutions/{id}` rows for the
  enriched payloads and add a `GET /api/institutions/by-source/{kind}/{external_id}`
  row.

## Acceptance

- [ ] With the ДГ№13 fixture, `GET /api/institutions/by-source/kindergarten/46`
      returns 200 with body bytes and `ETag` identical to
      `GET /api/institutions/13`
- [ ] Unknown pair → 404 `{"error": "institution_not_found"}`; `kind=school`
      → 422; `POST` → 405
- [ ] `nursery/46` and `kindergarten/46` seeded side by side resolve to
      different institutions; `kindergarten/460` is a 404, not a prefix match
- [ ] `If-None-Match` equal to the current ETag → 304, empty body, `ETag`,
      `Cache-Control: public, max-age=3600, stale-while-revalidate=86400`,
      `Vary: Accept-Encoding`; a miss → 200 full body
- [ ] A raising session → 503 `{"status": "degraded", "error": "database unreachable"}`
      (copy the existing `_BrokenSession` test)
- [ ] The id route's behaviour is unchanged: every existing detail test still
      passes against the refactored handler
- [ ] OpenAPI: the path `/api/institutions/by-source/{kind}/{external_id}`
      declares exactly two required path parameters; `kind` resolves to the
      enum `{nursery, kindergarten, preschool}`; `external_id` is `string`;
      the 200 schema is the same `InstitutionDetail` reference the id route
      uses; the id route still declares only `institution_id` (integer,
      minimum 1)
- [ ] `docs/ARCHITECTURE.md` lists the route

Evidence: `pytest -v` for both modules; against the local database,
`curl -s -D /tmp/h1 -o /tmp/a.json localhost:8000/api/institutions/by-source/kindergarten/46`,
then the id route for the *same* institution, with the id taken from that
body rather than written down in advance (serials are reassigned when the
database is rebuilt):
`ID=$(python3 -c 'import json; print(json.load(open("/tmp/a.json"))["id"])')`
and `curl -s -D /tmp/h2 -o /tmp/b.json localhost:8000/api/institutions/$ID`,
then `cmp /tmp/a.json /tmp/b.json` silent and `grep -i etag /tmp/h1 /tmp/h2`
showing equal tags; `curl -s -o /dev/null -w '%{http_code}\n'
localhost:8000/api/institutions/by-source/school/46` printing `422` and
`…/by-source/kindergarten/999` printing `404`.

## Steps

### RED
- [ ] `test_by_source_matches_id_route_bytes_and_etag`,
      `test_by_source_unknown_pair_returns_404`,
      `test_by_source_invalid_kind_returns_422`,
      `test_by_source_distinguishes_kind_and_exact_external_id`,
      `test_by_source_method_not_allowed`, `test_by_source_if_none_match_returns_304`,
      `test_by_source_if_none_match_miss_returns_full_body`,
      `test_by_source_database_error_returns_503`
- [ ] OpenAPI: `test_institutions_by_source_declares_kind_and_external_id_path_params`,
      `test_institutions_by_source_returns_institution_detail_schema`

### GREEN
- [ ] Extract `_institution_row` and `_detail_response` first as a pure
      refactor — run the existing detail tests, they must stay green — then
      add the new handler on top
- [ ] Update `docs/ARCHITECTURE.md`

### REFACTOR
- [ ] `get_institution` should contain no serialisation code of its own
      afterwards; both handlers are lookup + builder

## Notes

FastAPI matches by path shape here, not registration order:
`{institution_id}` is a single segment, so the three-segment by-source path
can never be captured by it. The reverse case — `/api/institutions/by-source`
with nothing after it — does hit the id route and returns 422 because
`"by-source"` is not an integer. That is acceptable; note it in the handler
docstring rather than adding a route for it.

`Kind` is a `Literal`, so FastAPI validates it as an enum path parameter and
documents it as one — the same mechanism the `kind` query parameter on
`/api/match` already relies on, and the same `_enum_values` helper in the
OpenAPI tests reads it.

No `max_length` on `external_id` (DECISIONS.md #4): the column is 16
characters, but a longer value is "not found", not "malformed".
