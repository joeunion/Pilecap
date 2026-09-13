# Journey · sign in → `/welcome`

**The one journey this template ships.** It is the auth landing made real: the
smallest surface that is a genuine client of the REST door, and the standing
subject that keeps every frontend rule proven in anger rather than declared.

A product deletes this file when it has journeys of its own. The **shape** is
what ships: a journey names its steps, its states, and what makes each state
non-vacuous — never a list of screens.

## The steps

| # | Step | Where it happens | What proves it |
|---|---|---|---|
| 1 | A person signs in | Django, `/accounts/login/` — the entrance chain, styled by `templates/account/base_entrance.html` | the entrance family's own tests |
| 2 | They land on `/welcome` | `LOGIN_REDIRECT_URL` | the Django landing's test |
| 3 | This client renders the same session facts | `frontend/src/app/welcome/page.tsx` | the state walk below |

**Step 3 is the parity claim, and it is the whole point:** the server-rendered
landing and this page answer the same question from the same tenancy
machinery — one through a template, one through the generated client — so a
disagreement between them is a finding rather than a mystery.

## The states, and what makes each one non-vacuous

`/welcome` reads one operation: `GET /api/v1/organizations/`, the organizations
the actor's *resolved* hat can see. The hat travels as `X-Org`; the server
revalidates it on every request. This page never decides it.

| State | What produces it | Seedable? |
|---|---|---|
| `loading` | the read is in flight | yes — with the backend paused |
| `empty` | the door answered with `items: []` | **no** — see below |
| `error` (registry) | a hat the session does not hold → `addressing_header_not_honoured`, rendered in the server's own words | yes — `/welcome?org=<a hat you do not hold>` |
| `error` (transport) | no response at all — the origin is down or the connection aborts | yes — stop the backend |
| `ready` | the tree the hat can see | yes — any signed-in session |

**`empty` is authored and is not reachable against a seeded world on this
operation, and that is recorded rather than papered over.** A signed-in
session's organization list always contains the organization it is acting as,
so there is no world in which the door answers `items: []` here. The state is
still authored — totality is the law, and the day this page reads an operation
that *can* answer empty, the branch is already designed — and it is
photographed from its story instead. A state proven only by a story says so.

## The acceptance ledger

| date | who | what was walked | verdict |
|---|---|---|---|
| — | — | — | *(a product's own rows go here; the template ships none)* |

**Rows are added by whoever walks the journey, and never by whoever built it.**
The template ships the format and no verdicts: a look accepted here would be
this template's taste in a product's ledger.
