# ADR roads-1

- **ADR roads-1 (one road per job, declared where it lives) · 2026-09-29** ·
  **context:** the consolidation survey found a third of its findings to be
  two roads to one job, and the platform had no way to say which road was the
  road: `django-conventions` described shapes in prose that drifted from the
  code, the noun-verb family had a road table for its verbs and nothing for
  the other jobs, and a product cloning the template re-implemented refusal
  bodies, could-not-look banners and discovery walks because nothing in the
  tree told it not to · **decision:** a road declares itself once, in code,
  where it lives — `@road("<job>", example="<path>::<symbol>")` (or `ROAD =
  road(...)` for a module) in importable Python, `# road: <job> — <contract>
  · example: <path>::<symbol>` directly above a shell function or in a
  script's header window — and the job vocabulary is DERIVED from those
  markers by one static census (`quality/roads.py`), which serves the door
  (`manage.py roads`, `roads <job>`, `roads --json` — an instrument: exit 0
  printed, 2 could-not-look), house rule 84 (a second marker for one job is
  refused unless valved `rule-84` with its reason and printed as `kept`;
  copied shapes are ratchet classes, down-only), the fold
  (`divergence_census.sh --against <ref>`'s roads class reads the markers as
  text on both sides, the awk a pinned mirror of the census) and the loop
  (the lead's brief cites the roads a rung reuses; the verifier diffs `roads
  --json`); the contract is the road's own docstring line, never a second
  literal; a road is unconditional — a marker under an `if`, `try` or `with`,
  or inside a function, is refused; a grammar's road is its READER, never the
  data; the word *road*
  generalises the family's own (`core.verbs.Road`); a job is never spelled by
  its medium · **rejected:** a hand-maintained roads table in `docs/` or
  `rules.yaml` (the prose-drift class, and ADR platform-partition-1's
  forbidden shape — a central file a product must edit); an `AppConfig.roads`
  attribute or a `ready()` registry call (a table one file away from the
  road, and unreachable for shell); a comment marker everywhere, Python
  included (a docstring satisfies it, and it cannot tell whether the marked
  name exists); a Django system check `djb.E084` (it cannot see a shell or
  `quality/` road, and the Django leg's findings have no valve); a
  live-registry-only census, `REGISTRY` as the truth (the fold reads a release
  it has not imported and `--fast` boots no Django); namespaced product keys
  such as `acme.refuse` (a collision that can never happen is a message that
  can never be sent); the shape counts in `quality/budgets.yaml` (a ninth home
  for "a recorded number", and a copy is a finding, not a measurement); a
  second `Road` class for the census record (two meanings under one name — the
  record is `Marker`); renaming `verbs.Road` (the verb table's own change, not
  this one) · **consequences:** `apps/core` grows `roads.py` (the marker,
  standard library only) and the `roads` command; `quality/` grows `roads.py`
  (the census), rule 84, the `sh` scope kind and rule 84's canaries and
  negatives; `divergence_census.sh` grows one collision class and one remedy;
  each kept road carries its marker in the file that owns it; every later
  consolidation registers its kept road by moving or adding ONE marker and
  reports its progress as a rule-84 class falling · trigger to revisit:
  (a) the gate's orchestration moves a shell road to Python — the marker moves
  with the mechanism in one commit and the job key, the rule, the fold class
  and the ratchet are unchanged; if that commit is impossible (a road two media
  share for a while), the OLD carrier is valved `rule-84: superseded by <new
  path> — until <dated trigger>` and counted, and this ADR is reopened only if
  a job needs two live roads for longer than that window; (b) a third carrier
  is needed (TypeScript, YAML-as-road) — the census's `Marker` gains a
  `carrier` value and nothing else; (c) the vocabulary outgrows one screen —
  then, and not before, `roads` groups by a `group=` field on the marker; (d)
  a product asks for a synonym census — the belt this decision declines
  becomes a rule.
