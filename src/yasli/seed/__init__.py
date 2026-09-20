"""`python -m yasli.seed` — one command to a production-like local database.

A developer with a clone of this repo and an empty Postgres runs the seed
and ends up with a database that answers the same questions production
answers, without holding a single R2 credential. The data it loads is
committed: ``data/grao/kads-03-06.zip``, ``data/seed/snapshot.json.gz``,
``data/seed/legacy_institutions.json`` and
``data/institution_locations.csv``.

The orchestration lives in :mod:`yasli.seed.runner`; the CLI in
``yasli.seed.__main__``. Each step is a thin call into the loader that
already owns it — the seed holds ordering and reporting, never loading
logic.
"""

from __future__ import annotations
