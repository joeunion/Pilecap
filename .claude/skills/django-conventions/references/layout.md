# Registering an app, settings and dependencies

The long form of `django-conventions` §1.

### Registering an app

```python
# apps/<orders>/apps.py — the whole registration; nothing else is edited
class OrdersConfig(AppConfig):
    name = "apps.orders"
    depends_on = ("core", "accounts", "events")   # what this app may import; rule 7 reads it
```

- **`INSTALLED_APPS` is derived from `apps/*/apps.py`** — every package under
  `apps/` with an `AppConfig` is installed, in dependency order. Creating the
  package *is* registering it.
- An `AppConfig` declares `depends_on`: the app labels it may import from.
  `core` depends on nothing; a domain app names `core`, `accounts` and the spine
  apps it uses (`events` to `emit`, `workflows` to start a run). A sideways
  import between two domain apps is refused unless the lead has recorded it.
- **Never edit `config/` or `pyproject.toml` to register anything** — not
  `INSTALLED_APPS`, not a router, not a worker list, not an import-linter
  contract. Every one of those is read from the app. (Ruled after an
  alignment review found registration was hand-listed;
  `config/settings/discovery.py` derives `INSTALLED_APPS` today.)
- Settings come from the environment; a new variable lands in `.env.example`
  with a safe local default in the same commit. `DJANGO_SETTINGS_MODULE`:
  `config.settings.local` for `manage.py`, `.test` for pytest, `.production`
  for `check --deploy`.
- Dependencies live in `pyproject.toml` via `uv add` / `uv sync` / `uv run …`;
  never `pip install`, never `requirements.txt`.
