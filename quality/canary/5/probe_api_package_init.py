"""The probe app's `api/` package marker, so the plant is a real package.

Empty of routes on purpose: the routes are in `routes.py` beside it, which is
the shape `apps/core/api/` actually has. If the check only looked at an
`__init__.py` it would still miss the file the routes are in.
"""
