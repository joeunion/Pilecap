# API editorial standard

<!-- The rules for every prose surface of the API contract: the overview
     guides in apps/core/api/docs.py and the contract half of every operation
     docstring. Builds on the owner's plain-language ruling (design-agreements.md)
     and the Stripe-shaped ruling; it never overrides either. The worked proof
     now ships as the authority: the Quickstart section of the OVERVIEW constant
     in apps/core/api/docs.py, pinned by apps/core/tests/test_contract_docs.py
     (the quickstart contract test names the first hour and the narrow token).
     The platform repo keeps the superseded draft as history. -->

**The reader** is a developer with an API key and a terminal, skimming for the
next command. They read prose only when a command surprises them. Every rule
below follows from that.

**The bar underneath** stands: plain language for a
developer who has never seen this codebase; the contract speaks to the caller
about the wire; no house idioms; a sentence a stranger with an API key cannot
act on goes below the divider. This standard adds economy on top of that bar.

## 1. The first-90-seconds test

A getting-started section puts a working command on the first screen — before
any rationale. If the first code block sits more than ~100 words in,
restructure: lead with the command, explain after it.

> **Before** (Quickstart today): the first `curl` arrives ~350 words in, behind
> sign-in, realm discovery, and four paragraphs of scope doctrine.
> **After** (rewrite): the mint call is the second thing on the page; the first
> `curl` is on the first screen.

## 2. Sentence economy — cut on sight

* **Throat-clearing.** A sentence that promises what the section will do
  repeats the heading. Cut the promise, keep the steps.
  > **Before:** "**Your first hour, in four steps.** At the end of it you have a
  > credential that does what your program needs and nothing else, and you have
  > read real data with it."
  > **After:** "Get a token, make a call, follow an id."
* **The second explanation of one idea.** Say it once, at the point of use;
  link everywhere else. Write-implies-read is currently explained three times
  before the reference begins (twice in Quickstart, again in Authentication).
* **Rationale longer than the rule.** One clause of *because* earns its keep; a
  paragraph of it moves to the concept guide or below the divider.
  > **Before:** "There is no default and leaving it out is refused: a token you
  > are about to paste into somebody else's software should be as narrow as the
  > work needs, and a default would quietly make it as wide as you are." (43 words)
  > **After:** "`scopes` has no default; omitting it is refused. Ask for the
  > narrowest set the job needs." (16 — the rationale survives as the imperative.)

## 3. Structure for scanning

* **Code first, prose second.** The command is the content; the paragraph under
  it handles the surprises.
* **One idea per paragraph.** A paragraph joining two facts about two different
  fields is two paragraphs, or a list.
* **Headings answer "can I skip this?"** Name the task ("Retrying a write
  safely"), never the theme ("Reliability").
* **Bold marks the sentence that changes what the reader types** — "the token
  is in this one response" — never tone.

## 4. What not to cut — the protected list

Economy cuts words, never facts a caller acts on:

* **Refusal meanings.** Every code an operation can answer, with what to do
  about it.
* **Exactness.** Paths, field names, header names, verbatim — never "the token
  endpoint" for `POST /api/v1/tokens/`.
* **The one warning that saves an hour.** "The token is shown once." "Hash the
  bytes you received." "A `404` is never proof that something does not exist."
  "A session write needs `X-CSRFToken`." These survive every cut, bold intact.
* **Copy-paste truth.** A command shown must run as shown.

The test for a borderline sentence: would deleting it cause a support ticket?
Then it stays.

## 5. Voice

* Imperative, second person, present tense: "Send the token on every request",
  never "The token should be sent".
* No marketing, no reassurance: *simply*, *just*, *easily*, *powerful* — delete.
* State a rule once; do not defend it. A defended rule reads as negotiable.

## 6. Length budgets

Prose words, code blocks excluded:

| Section type | Budget |
|---|---|
| Quickstart | 300 |
| Concept guide (auth, pagination, webhooks, agents) | 400 |
| Operation description, above the divider | 150 |
| Policy sections (changelog, versioning) | 250 |

Over budget is a finding, not a crime — the fix is moving rationale to one
linked guide or below the divider, never deleting a protected item to make
weight.

## 7. Mechanics for the editor

* Keep the pinned landmarks (`test_the_document_opens_with_the_overview`):
  `POST /tokens/`, `X-Org`, `Idempotency-Key`, `/mcp`, `/api/v1/`.
* Keep every heading at `##` — `/llms.txt` demotes them by one when embedding.
* Verify every path, field, header and scope name against the tree before it
  enters the text; write scope families against the ruled vocabulary
  (`org-structure` / `roles` / `invitations`, not the pre-split names).
* A factual error found while editing is reported to the PM to book, never
  silently patched into a draft nobody diffs.
