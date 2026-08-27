# Agreements — taste and identity, spent once

> **Holds:** every taste and refusal ruling the owner has made — what the
> product looks like and what it refuses to do — each dated, each naming what
> now enforces it (a token, a rule with a canary, precedent). Read before
> asking the owner anything about how the product looks or what it will not
> do; most questions are already answered here.
> **Must not hold:** the order of work (**that lives in `queue.md`**), a
> backlog of design ideas, or an unsettled question posed as a ruling.
> **Status:** skeleton. Opens the day the owner makes the first ruling.

## The problem this file solves

Everything else in this repository is verifiable by machine: correctness has
the suite, standards have house rules with canaries. **Taste is the only thing
with no canary**, which is why it is the one stage of the loop that stops for a
human, and why it threatens to become the bottleneck. The fix is not to ask
faster; it is to **stop asking the same question twice**:

1. settle the identity once, as a single decision;
2. write every ruling down here, including the ones already made;
3. convert a ruling into a token or a rule with a canary wherever it can be.

> **If it is settled here, the PM applies it and does not ask. If a cycle needs
> a decision that is not settled here, that — and only that — goes to the
> owner, and the answer comes back as a new line in this file.**

For a backend-only product "taste" is the API's register: naming, error
bodies, what a resource refuses. The same discipline applies.

## 1 · Already settled

| # | Settled | When | Now enforced by |
|---|---|---|---|

## 1b · What the product refuses to do

| # | Refusal | When | Now enforced by |
|---|---|---|---|

## 2 · The identity, as buildable values

*(Tokens, not adjectives: hex, px, weights, ms. For an API: the error body
shape, the pagination envelope, the naming rule.)*

## 3 · Open — awaiting the owner

*(Each with the cycle that needs it. Empty most of the time, by construction.)*

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — one marked ruling; delete when the first real one lands
>
> ## Ruling (Alex, 2026-03-04): a refusal names what to do next, or it is not
> ## a refusal
>
> **Asked because** the orders door answered `422 {"detail": "Not Found"}` for
> a customer that did not exist, and the clerk's next action was unknowable
> from the body. Two rungs had each invented their own wording.
>
> **The ruling, in the owner's words:** *"If we say no, we say what would have
> worked. Every time. I never want to read a body and have to guess."*
>
> **What it means, as buildable values:** every refusal body carries
> `code` (from the closed registry in `core.exceptions`), `message` in plain
> language addressed to the caller, and `remedy` — a sentence naming the next
> legal action. No door invents a fourth key.
>
> **Now enforced by:** house rule 47 (`quality/rules.yaml`) — a refusal code
> a route can answer is declared in its `@refuses(...)` set and registered in
> `core.exceptions`, with a canary that fires on an unregistered code. The
> `remedy` requirement rides the same registry entry.
>
> That is the shape of every entry: what was asked and why, the owner's own
> words, the ruling as values a builder can type, and the mechanism that
> means nobody has to remember it. **A ruling with no "now enforced by" is a
> ruling that will be asked again.**
