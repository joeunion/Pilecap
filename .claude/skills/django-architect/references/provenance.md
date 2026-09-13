# Provenance — how to read a snippet here

The long form of `django-architect`'s preamble.

Every rule below is stated as **statement · why · enforced · wrong → right**.
"Enforced" names the house rule id the gate runs, or says *criterion* (you
write it into the rung) or *review* (the lead checks it before returning
criteria; nothing automatic catches it yet). **Every module this file marks
`[main]` or `[A7a]` is on main today** — `core.service`, `core.authz`,
`core.audit`, `core.context`, `core.exceptions`, `core.actor`, `core.log`,
`core.observability`, and `selectors.py` / `policies.py` / `events.py` per app
all exist. The two markers now mean only *which shape a snippet shows*:
`[A7a]` is the contract's form, which is what the code does; `[main]` beside an
older snippet is kept where it names a real file, and where the snippet itself
predates the contract it says so. **Read the module, not this file** — the
markers are provenance, and the tree is the authority.
