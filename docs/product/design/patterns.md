# The pattern book — one shape per element class, its ruling, its instrument

> **Holds:** the form every element-class entry takes, the one worked entry,
> the element classes a product fills in order, the floor the house rules hold
> every face to (the scales), the instrument index, and the mirror pass.
> **Must not hold:** a product's own entries, words, tones or signature — those
> go in the drawer beside this file, `patterns.local.md` (the product owns it,
> the template never ships it, so a fold never conflicts with it; house rule
> 60). **Status:** template-owned. A product reads it, cites it, and writes its
> own book in the drawer; it never edits this file.

**The rule, once: a pattern needs an instrument.** Every entry names the file
that measures it, and a ruling with no instrument is a wish that will be asked
again — two verifiers once passed a face that broke a written rule, because the
rule had no test to fail. **House rule 63 refuses an entry whose instrument file
does not exist**, in this book and in the drawer alike. Instruments land first
(red, with an owed list naming today's offending sites); then the entries that
cite them; then the faces.

**Every face declares what it draws.** Each module under
`frontend/src/screens/` and `frontend/src/components/` carries, in its header,
`// patterns: §<n>` for each section it draws (several allowed), and each one
resolves to an entry here or in the drawer; a module that draws nothing says
`// patterns: none — draws no face`, and the template's placeholder landing
says `// patterns: template placeholder — words owned`. House rule 63 reads the
declaration and refuses a face that has none, or names a section with no entry.
§26 and §27 are headings, not entries, so a face never declares them: every
face is held to the scales by rules 64–67 whatever it declares, and the mirror
pass is a verifier's walk, not a thing a face draws.

**A frontend brief cites an entry here by section** (`patterns.md §15`, or the
drawer's own numbering), never a review. Where two reviews name one thing, the
earlier review's element name stands and the later one is amended.

## The DESIGN stage comes before a product's first frontend rung

A product draws no face until its book exists. **Before the first rung that
touches `frontend/src/`, the loop runs a DESIGN stage** whose output is the
drawer's entries for every element class that rung will draw, each in the
six-part form below, each naming an instrument that exists (or landing it in
the same stage, red first). **The engineering lead's DECOMPOSE refuses a
frontend rung whose element class has no entry** — the rung is returned to
DESIGN, not built on a guess. The method is the product-manager skill's § The
loop (stage 2); the refusal is the lead's brief in its
`references/dispatch-briefs.md`.

## How an entry reads — six parts

| Part | What it decides | The test of a good line |
|---|---|---|
| **Shape** | the block, its parts, their seats, sizes and weights | a builder can draw it with no picture |
| **Words** | the label family, the sentence family, who speaks (*you* · *we*) | every word is the lexicon's, none composed on the screen |
| **Placement** | which surface, which seat, what it sits under or beside | one seat; a second seat is a second entry |
| **States** | empty · loading · refused · phone — each one line | no state says *see above* |
| **Ruling** | the agreement rows it rests on, by number — the sentences live in `design-agreements.md` — and one sentence saying what this entry supersedes or contradicts (*Supersedes: nothing.* is an answer) | a line with no ruling is a proposal, not an entry; nothing is silently contradicted |
| **Instrument** | the file that measures it, in backticks, and in brackets what it asserts | the file name, never "a test" — and the file exists (rule 63) |

Each part is a paragraph opening with its bold label at the start of a line
(`**Shape.**` … `**Instrument.**`). A section carrying any of the six labels is
an entry and owes all six; rule 63 reads exactly that grammar and nothing else.
The register on every entry, stated once: a word only where a shape cannot say
it · the same words at the desk and the phone (the desk adds columns, never
words) · no state is a different screen, only the same words in one column.

---

## The worked entry

The one entry written out in full, because it is one of the surfaces whose
words the template owns (`design-agreements.md` § 1, row 1). It is here to show
the form filled in; a product's entries follow it in the drawer. The floor
entries after it are the same form held to the classes a house rule measures.

### §15 · The refusal notice

**Shape.** One panel, `role="alert"`, drawn where the surface's content would
have been — the `error` branch of the surface's `SurfaceState`, never a layer
over it. Top to bottom: the label line (weight 600), the fact line, the code in
the mono face at the facts size, then the remedies under their heading, then at
most ONE act as a link. A left rule in the accent marks it; no fill, no icon.
The registry member and the transport member share the panel and differ only
in what they carry: the transport member has no remedies, because no response
existed for the server to put them in. One renderer draws every refusal in the
product: `frontend/src/screens/refusal-panel.tsx`.
**Words.** The label is the surface's own (*The server refused* · *Your access
here ended*), from its copy module. The fact, the code and every remedy are the
server's, verbatim — never rewritten, never summarised. A transport failure
carries this client's own two sentences (`frontend/src/copy/refusals.ts`) and
never a code the server did not say. No *please*, no *sorry*, no *try again*
unless a re-read is the remedy the server named.
**Placement.** In the surface's content seat, under the surface's head, in the
same column as the content it replaces. Never a toast, never a dialog, never
two panels for one event.
**States.** Empty: a refusal with no remedies draws no remedies heading. Loading:
not a state of this panel — the surface is `loading`, not refused. Refused: this
panel. Phone: the same panel and the same words in one column; the act stays a
link at least the act floor tall.
**Ruling.** `design-agreements.md` § 1 · 1 (the template styles only surfaces
whose words it owns) · § 1b · 4 (the standing remedy prints on every refusal and
on nothing else). Supersedes: nothing — the first entry of its class.
**Instrument.** `frontend/src/screens/welcome/welcome-screen.test.tsx` (the
`error` state renders the server's own fact, code and remedies, and nothing
renders the literal `undefined`) · `frontend/src/app/states/page.test.tsx` (the
close-frame members render the words their design gave them, and no registry
code is synthesised for a transport failure).

---

## The floor entries — the classes a house rule holds

Six classes whose floor is a house rule, so the template writes their entries
itself: the route table and the sheet because the scaffold draws them, and the
act vocabulary, loading, bands and words because every product's faces are held
to them from its first rung. Each says what the rule decides and no more — the
look is the product's. **A product's drawer entry for the same section
supersedes this one's Shape and Words and names it in its Ruling; it never
supersedes the Instrument**, because the rule reads every face whatever the
drawer says.

### §0 · The route table

**Shape.** One table, `frontend/src/screens/routes.ts`, one row per route the
app router draws: `path` · `job` (one sentence) · `primarySeat` (where the one
primary act sits, or `null`) · `operation` (the url name of the list or detail
operation the route draws, or `null`). `null` is an answer; an absent column is
not. It is data, never rendered.
**Words.** The job is one sentence about what the reader comes to do, in the
book's register; it is not copy and it is not a label.
**Placement.** The head of the book: a route is written here before its page
is drawn, and every surface that asks "which page draws this" — a nav, a
remedy's link — reads this table, never a list of its own.
**States.** Empty: a product with no pages has no rows, and the rule's floors
say so. Loading · refused · phone: not states of a table — a route's own states
are its screen's.
**Ruling.** `design-agreements.md` § 1 · 4 (one act per screen, the next move
already on it — the seat column is where it is written down). Supersedes:
nothing — the first entry of its class.
**Instrument.** `quality/runners/js_route_table.py` (house rule 71: every
`frontend/src/app/**/page.tsx` has a row, every row has a page, every row
carries the four columns, no path twice).

### §1 · The sheet

**Shape.** The one floating surface, drawn by
`frontend/src/primitives/dialog.tsx` and nothing else: a modal `<dialog>` whose
head carries the title and the ONE dismiss, a body that scrolls, and a foot of
acts only. No second dialog, no `role="dialog"` on a `div`, no sheet a module
draws for itself.
**Words.** The head's title is the sheet's subject, or its act as a question
(§2). The dismiss is the lexicon's *Close*, in the head. The foot's acts are
verbs from the lexicon; *Close*, *Cancel*, *Done* and *Dismiss* are never in a
foot — the way out is already in the head.
**Placement.** Over the surface that opened it, never replacing it; opened by
the surface's owner, which holds whether it is up.
**States.** Empty: a sheet with nothing to act on is not opened. Loading: the
body draws its content's still shapes (§13); the foot's acts stay pressable.
Refused: the refusal notice (§15) in the body, above the foot. Phone: the same
head, body and foot, full width.
**Ruling.** `design-agreements.md` § 1 · 4 (one act, the next move already on
it) · § 1 · 1 (the template draws only the shape; the look is the product's).
Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_one_dialog.py` (house rule 70: a
`<dialog>`, a dialog `role` or a `createElement("dialog")` outside the
primitive is red; a dismiss word in a dialog foot is red; the primitive exists)
· `frontend/src/primitives/dialog.test.tsx` (one head with one dismiss, a foot
holding only the acts it was handed, Escape asks the owner).

### §4 · The act vocabulary — nothing is disabled

**Shape.** An act is drawn or it is absent. Nothing carries a `disabled` or
`aria-disabled`, no props type offers the switch, and no stylesheet styles a
`:disabled` state.
**Words.** An act at work says its verb's progressive (*Saving…*) from the
lexicon and stays pressable; an act that cannot run yet says its verb and is
answered by the server's refusal.
**Placement.** In its surface's fixed seat (the route table's `primarySeat` for
the primary); the refusal that answers it sits under the act's row.
**States.** Empty: an act the role may not take is absent, never drawn dead.
Loading: the progressive, pressable. Refused: the act stays drawn and alive, the
refusal notice (§15) beside it. Phone: the same act, at least the act floor.
**Ruling.** `design-agreements.md` § 1 · 4 (the person's next move is already
on the screen) · § 1 · 6 (finished, not loud — a dead control says no without
saying why). Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_nothing_disabled.py` (house rule 68: no
`disabled` attribute, key, assignment or `setAttribute`, no `aria-disabled`, no
`:disabled` selector, and no `pointer-events: none` or `cursor: not-allowed` on a
pressable under `frontend/src/`).

### §13 · Loading

**Shape.** Still shapes at the content's heights, under `aria-busy`: the reader
sees what is coming. No spinner, no shimmer, no loader animation.
**Words.** At most one line naming what is being read, from the surface's copy
module (*Reading the session facts…*).
**Placement.** In the content seat the ready state will fill, never over it.
**States.** Empty · refused: not loading — the surface has answered. Loading:
this entry. Phone: the same shapes in one column.
**Ruling.** `design-agreements.md` § 1 · 6 (finished, not loud). Supersedes:
nothing — the first entry of its class.
**Instrument.** `quality/runners/js_no_toast_spinner.py` (house rule 69: no
identifier, import, class or `@keyframes` from the spinner and shimmer
families) · `frontend/src/screens/welcome/welcome-screen.test.tsx` (the
`loading` state is a designed render under `aria-busy`, not an absence).

### §17 · Bands — there are no toasts

**Shape.** An outcome is a full-width band under the surface's head, and it
stays until it is read or the surface moves on. There is no toast, no snackbar,
no notice on a timer.
**Words.** One sentence from the lexicon, finished and plain, and at most one
act.
**Placement.** Directly under the head, above the content it is about.
**States.** Empty: no outcome, no band. Loading: not a band's state. Refused: a
refusal is the notice (§15), never a band. Phone: the same band, full width.
**Ruling.** `design-agreements.md` § 1 · 6 (finished, not loud) · § 1b · 4 (the
standing remedy prints on refusals and on nothing else). Supersedes: nothing —
the first entry of its class.
**Instrument.** `quality/runners/js_no_toast_spinner.py` (house rule 69: no
identifier, import, class or `@keyframes` from the toast family).

### §21 · Words on a surface

**Shape.** Every label a face shows is a row of one lexicon,
`frontend/src/copy/lexicon.ts`; every string a copy module hands a reader is
free of machine tokens.
**Words.** One word per thing, everywhere: a label is spent from the lexicon
verbatim, and a rename is one lexicon line. No field name, key, slug or id in
reader text — the reader's words, and *you* for the reader.
**Placement.** Copy modules under `frontend/src/copy/`, one per surface or
noun; the lexicon beside them. Never a string inline in a face.
**States.** Every state's words are the same words at the desk and the phone;
a refused state speaks the server's sentence verbatim and the surface's label
from the lexicon.
**Ruling.** `design-agreements.md` § 1 · 7 (plain language on every face; the
product's internal vocabulary never reaches one). Supersedes: nothing — the
first entry of its class.
**Instrument.** `quality/runners/js_lexicon.py` (house rule 72: every label a
copy module writes is a lexicon row, and the lexicon has no row twice) ·
`quality/runners/js_machine_tokens.py` (house rule 73: no snake token, kebab
key or hex id in a copy string).

---

## The element classes — a product writes one entry each, in its drawer

A product fills these in its drawer in this order, in the form above. A class
it does not have stays a heading there with *not in this product, and why*, so
a number never shifts under a brief that cites it.

- **§0 · The route table** — every route's one job and where its primary act sits; the head of the book, before the furniture.
- **§1 · The sheet** — the one floating surface: head with the one dismiss, a scrolling body, a foot of acts only (never *Cancel · Close · Done* in a foot).
- **§2 · The confirm** — a sheet whose head is the act as a question and whose foot is one primary wearing the verb; when a confirm is owed and when it is not.
- **§3 · Choice** — one control per vocabulary shape; the shape decides the control, the screen never chooses.
- **§4 · The act vocabulary** — the weights, the fixed seats, one primary per surface; busy is the verb's progressive, disabled is never.
- **§5 · The list page head** — title, lede, one create act drawn only when the role may.
- **§6 · The record head** — crumb · name · at most one pill · lede · acts · the refusal seat.
- **§7 · The control row** — one row under the head, one seat per question, in a fixed order.
- **§8 · The list and the row** — one anatomy across nouns; the row is the door.
- **§9 · The record page grid** — head · main · rail, and the phone's one column.
- **§10 · The card** — head · body · foot acts; the primary only on the card that is the work.
- **§11 · The fact strip** — one bold fact about the acting scope above a list.
- **§12 · The integration row** — one row per integration, state pill, the switch only at the permission ceiling.
- **§13 · Loading** — still shapes at the content's heights; never a shimmer, never a spinner.
- **§14 · Empty states** — the sentence names the noun; the door proposes the next act.
- **§15 · Refusals** — the worked entry above; a product that draws more refusal faces adds them here.
- **§16 · Pills** — a tinted word, never a fill; the tone is the meaning.
- **§17 · Bands** — a full-width line under a head; there are no toasts.
- **§18 · The nav** — one route table drives every bar; a door the role may not use is absent, never disabled.
- **§19 · The scope chip** — narrowing a list to the acting node's subtree, in closed words.
- **§20 · Leaving the book** — every noun leaves one way; the hidden-by-default cut; one *Restore* per row.
- **§21 · Words on a surface** — no machine token in reader text; one word per thing; *you* always.
- **§22 · The narrowing surface** — search, a filters sheet, applied chips, a count line.
- **§23 · Search** — the box, the scope toggle, hits as rows, the miss that proposes one act.
- **§24 · The print and report acts** — prints the view as the reader sees it.
- **§25 · The admin sheet and the settings hub** — the sheet an admin row opens; the hub as a door list.
- **§26 · The scales** — the floor below; a product's drawer holds its values.
- **§27 · The mirror pass** — ten questions before a built face merges; the clause is at the foot of this book.

---

## §26 · The scales — the floor every face is held to

The values are a product's (its tokens in `frontend/src/tokens/`); the shape of
each ruling is fixed, and the house rules below hold every stylesheet and every
inline style under `frontend/src/` to it. **They red a product until it adopts
the floor**: a floor a product can ignore is the class a consumer already paid
for.

**Type roles.** Every size names a type role: a stylesheet or an inline style
never sets a `font-size`, a `letter-spacing` or a `font` shorthand outside a
`--type-*` token, and no role is a half pixel. A literal that fits no role is a
design finding, never a builder's rem. Both widths share the scale. (House
rule 64.)

**Spacing scale.** Every gap is on the scale: a `gap`, `padding` or `margin`
(and each of their sides) is `0`, `auto`, a keyword, or a `--space-*` token —
never a literal length. The geometry that is not spacing (the act floor, a
sheet's edge) is its own token, named. (House rule 65.)

**Motion ledger.** Every motion names a `--motion-*` token, and the tokens are
exactly the ledger — one row per moment that moves; a motion not on the ledger
is not built, and a builder who needs one stops. The ledger is the fenced block
below (and any a product adds in its drawer); the template moves nothing, so
its own block carries only the row's form. (House rule 66.)

```motion-ledger
# <moment> | --motion-<name> | <what moves> | <under reduced motion>
```

**Focus ring.** Every pressable wears one ring when the keyboard reaches it:
every pressable class, and every pressable element a stylesheet styles or a
screen renders, has a `:focus-visible` rule naming the `--focus-ring` token;
never a ring on mouse focus, never `outline: none` without the ring in its
place. (House rule 67.)

**The act floor.** Every pressable class consumes `--act-min` (44 px): its
target is at least that tall and that wide. This is the STATIC half — a class
that consumes the token; the measured box at the phone width needs a rendered
browser and is not a house rule here. Inline links inside a sentence are the
one named exception. (House rule 67.)

---

## The instruments, by file

The index every brief reads — the file column is copied into a brief's
territory line, the measures column into a criterion's instrument clause. One
row per instrument file; rule 63 holds every file named here to existing.

| pattern | instrument file | what it measures (the closed question) | its plant (what proves it fires) |
|---|---|---|---|
| every entry, every row here | `quality/pattern_book.py` | house rule 63: every entry is six parts and names an instrument file that exists; every row here names a file that exists | an entry naming a file this tree does not have — red |
| §15 | `frontend/src/screens/welcome/welcome-screen.test.tsx` | the `error` state renders the server's fact, code and remedies verbatim; nothing renders `undefined` | a panel rendering a sentence of its own — red |
| §15 | `frontend/src/app/states/page.test.tsx` | every close-frame state renders its design words; no registry code is synthesised for a transport failure | a synthesised registry code — red |
| every token | `quality/runners/js_token_consumer.py` | house rule 53: every token declared is read, and every token read is declared | a declared-unread token; a consumed-undeclared one — red |
| §26 type | `quality/runners/js_type_scale.py` | house rule 64: every `font-size`, `letter-spacing` and `font` names a `--type-*` role; no half pixel | a planted `font-size: 13.5px` — red |
| §26 space | `quality/runners/js_spacing_scale.py` | house rule 65: every gap, padding and margin is `0`, `auto` or a `--space-*` step | a planted `gap: 10px` — red |
| §26 motion | `quality/runners/js_motion_ledger.py` | house rule 66: every transition and animation names a `--motion-*` token; the token set equals the ledger | a planted `transition: 200ms`; a token off the ledger; a row with no token — red |
| §26 focus, act floor | `quality/runners/js_focus_ring.py` | house rule 67: every pressable has a `:focus-visible` rule naming `--focus-ring`; every pressable class consumes `--act-min` | a pressable class with no `:focus-visible` — red |
| §4 | `quality/runners/js_nothing_disabled.py` | house rule 68: nothing under `frontend/src/` disables a control — no `disabled` or `aria-disabled` attribute, key, assignment or `:disabled` selector | a planted `disabled` prop — red |
| §13, §17 | `quality/runners/js_no_toast_spinner.py` | house rule 69: no identifier, import, class or `@keyframes` from the toast, spinner or shimmer families | a planted `Spinner` import — red |
| §1 | `quality/runners/js_one_dialog.py` | house rule 70: only the primitive draws a dialog; no dismiss word in a dialog foot | a second `role="dialog"`; `Cancel` in a foot — red |
| §1 | `frontend/src/primitives/dialog.test.tsx` | one head with the one dismiss; the foot holds only the acts handed to it | a dismiss drawn in the foot — red |
| §0 | `quality/runners/js_route_table.py` | house rule 71: every page has a route-table row and every row a page, with path · job · primarySeat · operation | a page with no row — red |
| §21 | `quality/runners/js_lexicon.py` | house rule 72: every label a copy module writes is a lexicon row | an off-lexicon label — red |
| §21 | `quality/runners/js_machine_tokens.py` | house rule 73: no snake token, kebab key or hex id in a copy string | `invoice_id` in a copy string — red |

---

## §27 · The mirror pass — ten questions before a built face merges

**The rule.** A built face merges after the mirror pass, whose ten lines each
name their artifact; the tenth line is a sentence and an accessory, and a pass
with no accessory named is a pass that did not look. It is walked on the
rendered drive at the desk and the phone widths, by somebody who did not build
it, and it lives in three places: the builder's report (a standing criterion on
every frontend rung), the verifier's brief (the clause below), and every design
accept review.

**The clause — paste into every verifier brief on a frontend rung:**

> **The mirror pass.** Your report carries a section `## The mirror pass` with
> the ten lines below, each answered by its artifact — a file, a test id, a
> capture, a delta — never by a sentence alone. Walk it on the rendered drive
> at the desk and the phone widths. Where the builder's report already carries
> the section, re-read each artifact yourself; a line you cannot re-read is
> *not shown*, and a face with a line *not shown* does not merge. Line 10 is
> yours to answer even when the builder answered it: read the face for what you
> would have removed, and name it. Design judges the face; you judge that every
> line has its artifact.

```
## The mirror pass

1. The job — the route's row in the route table, quoted; the head shows its critical fact first (a capture at the desk).
2. One primary — the route census green on this branch (the test id and its run line).
3. The same words at the phone — the word census's delta equals the rung's declared ± (the two numbers).
4. Every size a role — the type-scale rule clean over the files the rung touched (the live-scan line).
5. Every gap on the scale — the spacing-scale rule, the same (the live-scan line).
6. Every motion on the ledger — the motion-ledger rule clean; no token added off the ledger (the line).
7. A ring on every pressable — the focus-ring rule clean; every pressable class the rung added consumes the act floor (the line).
8. Reduced motion walked — one capture at the phone with `prefers-reduced-motion` on, labelled.
9. The four states captured — one capture per authored state per touched route, each saying what in the seeded world produced it; the console transcript and the hydration assertion pasted.
10. The generic-default question, in one sentence — what here is what any product of this kind would draw, and what did we change — and the accessory removed, named: one element the built face had that the merged face does not, or *none, and why*.
```

**What the pass is not:** a design review (design's accept review carries the
section and adds its judgment; the verifier proves each line has its
artifact); a substitute for the rung's numbered criteria (they come first, the
pass is the last section of the report); or vacuous when nothing is removed —
*none, and why* is an answer, and the verifier still reads the face.
