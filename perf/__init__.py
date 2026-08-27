"""The seeded-scale performance harness (ADR perf-1).

Measurement territory beside `quality/`, not an app: no `apps.py`, no models,
no migrations, and **excluded from the default suite** (`pyproject.toml` keeps
`testpaths = ["apps"]`; nothing here is collected unless `scripts/perf.sh`
names it). The three residents:

* `seed.py` — `ScaleSpec` (the fixture contract's declared volumes, the one
  place the code states them) and `seed_scale`, which builds the world through
  the models with `bulk_create` batches;
* `measure.py` — the four machine-invariant instruments (query counts, EXPLAIN
  plan shape, flat-under-doubling, cache-hit counts) and the refusal of any
  assertion phrased in seconds (wall-clock is recorded
  as observation, never gated);
* `conftest.py` — points pytest at the already-seeded `_perf` database instead
  of creating a `test_` one, marks everything here `perf`, and runs the
  wall-clock refusal over every collected measurement module.

Run it with `scripts/perf.sh`, never with bare pytest: the script provisions
the per-checkout `<derived-name>_perf` database, migrates it, re-seeds exactly
when the spec hash changes, and refuses any database whose name does not end
in `_perf`.
"""
