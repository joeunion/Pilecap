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

**A face's stories are its population.** The four required exports are the
floor, in order (`REQUIRED_STORY_EXPORTS`); a module may export more only when
each extra is named for a state or shape an entry the module DECLARES names
(a `HasMore` for §8's *Show more*; a `LongName` for §8's wrap; a `Resting` for
§16's resting state). The face census reads such extras as the population for
that entry's clauses and the mirror pass captures them beside the four; an
extra no declared entry names is red, so a module declaring no entry keeps the
rule that a fifth export is as wrong as three.

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

## The floor entries — the classes a house rule holds, and the worked face's classes

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
draws for itself. The noun-verb family's two sheets are this one. **Edit's**
(the Edit road, versioned): the noun's fields, each its word over its control,
holding the `version` it read, and *Save* the foot's one primary — a save that
lost a race is refused, and the sheet stays up with the server's sentence one
line above the foot and one act, *Reload*; there is no field-level merge and
no silent last-write-wins. **Move's** (the Move road): one question per axis
the noun's move door accepts — the destinations the server lists for this hat
(`?can=<noun>.move`), by name, the current one marked and never chosen — it
is drawn with a visible mark and `aria-current`, and offers no choice at all —
and *Move* the foot's one primary, drawn once a node other than the current
one is chosen (a move to where the row already is moves nothing, so it is
never a press); after the answer the sheet closes. **Merge's** (the Merge
road, asked twice): *Merge* opens the CHOOSER, a sheet titled *Merge ⟨name⟩
into…* — a search, and the rows of the same noun the server allows as
survivors (a row whose own answer offers merge), by name, each one press, no
foot; picking one opens **the confirm** — this same primitive, its head the
question *Merge ⟨loser⟩ into ⟨survivor⟩?*, its body the dry run's answer
(what moves to the survivor, in the owners' words and counts), its foot ONE
primary, *Merge*, drawn once the dry run has answered; Escape returns to the
chooser. After the merge the face stands on the survivor; the loser's address
wears the merged band (§17). Merge is the one verb no press undoes, so it is
the one verb behind a confirm: a sheet that collects an argument is not a
confirm (§2): its foot's primary is the one press, and a verb the same face
undoes in one press is never behind a dialog.
**Words.** The head's title is the sheet's subject, or its act as a question
(§2). The dismiss is the lexicon's *Close*, in the head. The foot's acts are
verbs from the lexicon; *Close*, *Cancel*, *Done* and *Dismiss* are never in a
foot — the way out is already in the head. Edit's: the noun's name as the
title; the fields' words are the generated schema's property titles (never a
key); *Save* · *Saving…* · *Couldn't save* · *Reload*; the in-place ask
*Discard your changes?* · *Keep editing* · *Discard* (the sheet's own words,
in its body). Move's: *Move ⟨name⟩* (*Move ⟨n⟩ ⟨nouns⟩* over a selection) ·
*Moving…* · *Couldn't move* · *No other place to move this.* Merge's: *Merge
⟨name⟩ into…* · the question · *Merge* · *Merging…* · *Couldn't merge* ·
*No other ⟨nouns⟩ match.* Modify and Update are red as labels on a noun that
edits; Transfer, Reassign and Relocate on a noun that moves; Combine, Dedupe
and Consolidate on a noun that merges (house rule 79).
**Placement.** Over the surface that opened it, never replacing it; opened by
the surface's owner, which holds whether it is up.
**States.** Empty: a sheet with nothing to act on is not opened; Move's with
no destination says *No other place to move this.* and its foot draws no
*Move*. Loading: the body draws its content's still shapes (§13); the foot's
acts stay pressable. Refused: the refusal notice (§15) in the body, one line
above the foot, the sheet open and the pressed act alive — for a lost race
(`stale_version`, whose remedy is a re-read) with its one act *Reload*, which
on a dirty form first asks *Discard your changes?* in place with *Keep
editing* focused, and then lands on the first field the re-read changed;
`move_blocked` with its remedies and no act; `merge_blocked` inside the
confirm, above its foot, *Merge* alive. Merge's chooser with no survivor says
*No other ⟨nouns⟩ match.*; its confirm draws the dry run's still line and no
*Merge* until the dry run answers. Phone: the same head, body and foot, full
width. Focus: an act that opens a sheet lands on its first field (Move's: its
first choice; Merge's chooser: its search); the confirm opens on its question,
*Merge* the next act; the sheet going down lands back on the act that opened
it, or — after a move or a merge — on the record's name.
**Ruling.** `design-agreements.md` § 1 · 4 (one act, the next move already on
it) · § 1 · 1 (the template draws only the shape; the look is the product's)
· the verb family's V-1–V-4, V-6 and V-8 (the Edit, Move and Merge roads).
Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_one_dialog.py` (house rule 70: a
`<dialog>`, a dialog `role` or a `createElement("dialog")` outside the
primitive is red; a dismiss word in a dialog foot is red; the primitive exists)
· `frontend/src/primitives/dialog.test.tsx` (one head with one dismiss, a foot
holding only the acts it was handed, Escape asks the owner) ·
`quality/runners/js_verb_acts.py` (house rule 78: a verb the same face undoes
in one press is never inside the dialog primitive, and merge's press is only
there) · `quality/runners/js_verb_road.py` (house rule 77: a face draws Edit
and Move only where its wire serves the door) ·
`frontend/src/screens/verb-face-census.test.tsx` (the lost race's story: the
sheet's one primary alive, the refusal above its foot, a re-read beside it;
Move's refused story in the sheet; merge's refused story inside the confirm,
its head the question, ONE primary *Merge*) ·
`frontend/src/screens/verb-focus.test.tsx` (the first field; *Reload* to the
first changed field; the dirty ask on *Keep editing*; back to the opener; the
chooser's search, the confirm's question, Escape back to the chooser, the
survivor's name) · `frontend/src/screens/widget/widget-record.test.tsx` (the
current node marked with no radio; the chooser's survivors the rows offering
merge; the confirm's words).

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
pressable under `frontend/src/`) · `quality/runners/js_verb_table.py`
(house rule 80: `frontend/src/screens/verbs.ts` equals the verb table below,
row for row — order, press, weight and the five forms' presence) ·
`frontend/src/screens/verbs.test.ts` (the table's acts are constructed, never
remembered: `actsFor` intersects the road with the row's answer in table
order, a busy form for every verb with an act).

**The verb table** — the noun-verb family's one grammar, the table every noun
face's acts are constructed from (`frontend/src/screens/verbs.ts` transcribes
it row for row, and rule 80 holds the two equal). One row per verb, in the
order a face draws them: the pressed word(s), the busy form(s) on the same
button, the state word a band or pill shows, the refusal notice's first line,
the way back, how it is pressed (`one` · `confirm`, merge alone · `preview`,
import's second look · `none`), its place in `record-acts` (*Archive* last),
and its weight — no family verb is ever primary. `—` is an answer; several
words are separated by ` · `. A product that renames a verb renames it once in
its lexicon and writes its WHOLE table, in this form, in its drawer's own
`verb-table` block, which then stands for this one.

```verb-table
# verb | pressed | busy | state | refused | way back | press | order | weight
update | Edit | Saving… | — | Couldn't save | Edit | one | 1 | ghost
move | Move | Moving… | Moved | Couldn't move | Move again | one | 2 | ghost
duplicate | Duplicate | Duplicating… | Duplicated | Couldn't duplicate | Archive | one | 3 | ghost
merge | Merge | Merging… | Merged | Couldn't merge | — | confirm | 4 | ghost
archive | Archive | Archiving… | Archived | Couldn't archive | Restore | one | 5 | ghost
restore | Restore | Restoring… | — | Couldn't restore | Archive | one | — | ghost
import | Import | Checking… · Importing… | Imported | Couldn't import | Archive | preview | — | ghost
attach | Add a note · Add a file · Add a tag | Adding… | — | Couldn't add | Archive · Remove tag | one | — | ghost
history | — | — | — | Couldn't load the history | — | none | — | ghost
```

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
act. The noun-verb family's: the archived record's (§20); a record moved out
of the hat's sight, *Moved to ⟨node⟩.*, with no act; a batch's, *Archived ⟨n⟩
⟨nouns⟩.* — *Archived ⟨n⟩ of ⟨m⟩ ⟨nouns⟩.* when the server refused some —
with its one way back over the rows that were done, *Restore them* (after a
move, *Moved ⟨n⟩ ⟨nouns⟩.* and *Move them back* when they all came from one
node). The copy's, *Duplicated from ⟨source⟩.*, the source a live door, until
the next navigation, with no act. The merged row's, *Merged into ⟨survivor⟩ on
⟨day⟩.*, the survivor a live door where a page draws it, with no act — a merge
has no way back. The list's while an import runs, *Importing ⟨file⟩: ⟨n⟩
rows.*, its words a door to the import page; the import page's, *Imported ⟨n⟩
⟨nouns⟩ on ⟨day⟩.* with the list a door, and *This file was imported on
⟨day⟩.* for the same file again. Never a partial that reads as a success.
**Placement.** Directly under the head, above the content it is about (a
batch's, under the list's control row).
**States.** Empty: no outcome, no band. Loading: not a band's state. Refused: a
refusal is the notice (§15), never a band. Phone: the same band, full width.
**Ruling.** `design-agreements.md` § 1 · 6 (finished, not loud) · § 1b · 4 (the
standing remedy prints on refusals and on nothing else) · the verb family's
V-5. Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_no_toast_spinner.py` (house rule 69: no
identifier, import, class or `@keyframes` from the toast family) ·
`frontend/src/screens/verb-face-census.test.tsx` (the moved-away band with zero
primary and no act; a batch's band saying *n of m*; the merged band naming the
survivor, with no act and no primary) ·
`frontend/src/screens/verb-focus.test.tsx` (a batch lands on the band's act).

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

### §5 · The list page head

**Shape.** One head over every list route, drawn in all four states, top to
bottom: the title (`h1`, `--type-title`, the noun's plural), the lede (one fact
about the acting scope — its name, `--muted`, `--type-facts`), and at the trail
of the title line at most ONE act, the create act, drawn only when the page's
answer says this hat may create here — the client never derives it, and a
permission key spelled in a screen is red. No second act in the head: the
import act (the verb family's `list-head` seat) sits after the create act and
is the family's, not a second one of this class. What follows the head, in this
order and only when the face has it: the band (§17), the fact strip (§11), the
control row (§7), the list (§8). **The import act** (the Import road) is *Import*,
ghost, a door to the noun's import page, drawn where the list's own answer
offers `create` (an import applies the noun's own create, row by row). **The
import page** is the list's own page with this head (its title *Import
⟨nouns⟩*, the crumb to the list) and ONE body read from the run row, which the
route polls — the work is the server's workflow: *choose* (the file field, the
columns the file carries, *Import* the page's one primary) → *checking*
(*Checking ⟨file⟩…*, still) → *previewed* (the counts line *⟨a⟩ new · ⟨b⟩
changed · ⟨c⟩ unchanged · ⟨d⟩ refused*, each refused row by its number with the
server's sentence, then ONE primary *Import ⟨n⟩ ⟨nouns⟩*, n what the apply will
write, absent when it would write nothing — the preview is the import's second
look, not a confirm) → *importing* (the same button, *Importing…*, alive) →
*imported* (the band, §17). The same file again lands on its run: *This file was
imported on ⟨day⟩.*
**Words.** The title is the noun's plural, a lexicon row; the lede is a name,
never a slug, a count or an instruction; the create act is the create verb and
the noun's singular (*Add a ⟨noun⟩*), one lexicon row per noun. The head says
nothing about the session and nothing that is not true in all four states.
Import's: *Import* · *Checking…* · *Importing…* · *Imported* · *Couldn't import*;
the counts line; *Import ⟨n⟩ ⟨nouns⟩*; *Nothing to import in ⟨file⟩.*; Upload ·
Load · Bulk add are not its words (*Add a file* on the Files card is not an
import).
**Placement.** The head of the list route, above everything; the route table's
`primarySeat` for the list route names the create act's seat or is `null`.
**States.** Empty: the same head; when the empty's door (§14) is the create
act, the head does not draw it too — one act, one seat. Loading: the same
head, the create act drawn if the page's answer is already known, else absent.
Refused: the same head over the notice (§15). Phone: title, lede and act in
one column, the act at least `--act-min` tall and full width. The import page:
empty is *choose* (no run yet), and a file with no rows says *Nothing to import
in ⟨file⟩.* with no primary; loading, *checking* and *importing* are still
states, never spinners; a file refused whole (`import_invalid`) is the notice
under the head, *Couldn't import* first, the file field and *Import* alive;
previewed lands focus on the counts line, the primary the next stop.
**Ruling.** `design-agreements.md` § 1 · 4 (one act per screen, the next move
already on it) · § 1 · 6 (finished, not loud) · § 1 · 7 (plain language; the
scope by its name) · the verb family's V-1, V-3–V-5 (the Import road).
Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_route_table.py` (house rule 71: the list
route has a row, and its `primarySeat` says where the create act sits or that
there is none) · `quality/runners/js_nothing_disabled.py` (house rule 68: a
create act the hat may not take is absent, never dead) ·
`quality/runners/js_lexicon.py` (house rule 72: the title and the act are
lexicon rows) · `frontend/src/screens/verb-face-census.test.tsx` (the import
preview's ONE primary carrying its count; the whole-file refusal under the
head) · `frontend/src/screens/verb-focus.test.tsx` (previewed to the counts
line) · `frontend/src/screens/widget/widget-import.test.tsx` (every state of
the import page, its words, the apply's busy word on the same button).
Declared gap: no instrument yet refuses a second act in the head
or a head drawn in fewer than four states; the rendered census the verb family
owes (its face census over every noun's stories) is where that count lands.

### §6 · The record head

**Shape.** One head over every record route, top to bottom: the crumb (one
link to the list route, wearing the list's title, at least `--act-min` tall —
the word unchanged, the target grown; not a second exception to the floor),
the name (`h1`,
`--type-title`, wraps and never clips, `tabIndex={-1}` so a way back can land
focus on it), at most ONE pill after the name (§16 — the noun's standing
state, only when it has one), the lede (one fact — the scope the record lives
in, by name), the acts row (`data-seat="record-acts"`: the noun's own acts
first, then the family verbs as `allowed_acts` answers them for this row, in
the order and at the weight the face's one verb table declares — this entry
does not repeat that table), and the refusal seat directly under the acts row.
At most one primary in the head, and it is the noun's own; no family verb is
ever primary. An act the row's `allowed_acts` does not name is absent.
**Duplicate** (the Duplicate road) is one press — no naming dialog, no
confirm: the server makes the copy and the face stands on the copy's page
under the band *Duplicated from ⟨source⟩.* (§17), the copy an ordinary live
noun whose way back is its own *Archive*. **Merge** opens its chooser (§1).
**The tag row** (attach) sits directly under the lede: each tag its word and
its × (*Remove tag ⟨name⟩* — a tag coming off is not a noun leaving the book;
a tag is a word, never a pill, and has no colour), then *Add a tag*, ghost,
which opens the chooser in place — the existing tags matching what is typed,
each one press, and *Add* for the typed word. Who may attach is the owners'
answer (any reader of the row, for a note or a tag), never computed here. A
record that is archived or merged keeps its tags and offers no act on them.
**Words.** The crumb is the list's title, the same lexicon row; the name is
the record's, verbatim; the pill's word is the lexicon's; every act is its
verb as pressed, its progressive while at work. No *Back*, no *Actions*.
Duplicate's: *Duplicate* · *Duplicating…* · *Couldn't duplicate*; Copy and
Clone are red as its label (house rule 79). The tag row's: *Add a tag* ·
*Add* · *Adding…* · *Couldn't add* · *Remove tag ⟨name⟩*.
**Placement.** The head of the record route, full width above the grid (§9);
the route table's `primarySeat` for the record route is `record-acts` or
`null`.
**States.** Empty: not a state of a head — a record that does not exist is the
not-found notice (§15) in the content seat, under a head carrying the crumb
alone. Loading: crumb drawn, a still shape at the name's height, no acts.
Refused: the notice (§15) in the refusal seat, the pressed act still drawn and
alive (a refused *Duplicate* there, *Couldn't duplicate* first); the tag row's
refusal directly under the row. Phone: one column; the acts wrap in the same
order, each at least `--act-min`; the tags wrap; the crumb stays. Focus:
*Duplicate* lands on the copy's name; a record reached by the list bar's
*Merge* lands on its name; a tag added through the chooser lands on its own ×,
the new tag's one act.
**Ruling.** `design-agreements.md` § 1 · 4 (one act per screen) · § 1 · 6
(finished, not loud — an absent act, never a dead one) · § 1 · 7 (a name,
never a slug) · the verb family's V-1–V-3, V-5, V-6 and V-8 (the Duplicate
and Merge roads, attach's tag row). Supersedes: nothing — the first entry of
its class.
**Instrument.** `quality/runners/js_route_table.py` (house rule 71: the record
route has a row and a `primarySeat`) · `quality/runners/js_nothing_disabled.py`
(house rule 68: no act in the head is disabled) ·
`quality/runners/js_focus_ring.py` (house rule 67: every act in the row wears
the ring and consumes the act floor) ·
`frontend/src/screens/welcome/welcome-screen.test.tsx` (the refusal seat's
panel renders the server's fact, code and remedies, never a sentence of its
own) · `frontend/src/screens/verb-face-census.test.tsx` (the family's acts in
the seat in table order, *Duplicate* third and *Merge* fourth, ghost; attach's
acts only in a card's foot or the tag row) ·
`frontend/src/screens/verb-focus.test.tsx` (*Duplicate* to the copy's name).
Declared gap: the order crumb · name · pill · lede · acts, the one-pill
and one-primary counts and the family acts' order are rendered questions no
runner asks yet; they are the verb family's face census, owed.

### §7 · The control row

**Shape.** Exactly one row under the list head (and under the fact strip
§11 when there is one), above the rows (§8): one seat per question the list
can be asked, in a fixed order — the search box (§23) · the scope chip (§19) ·
the narrowings (§22's applied chips, one per applied value) · at the trail the cut chips, of which the *Archived* chip (§20) is one, exclusive of the others — drawn whenever the list can be asked `?show=`, for every hat that can read the list (a cut is a read, and no read is role-gated), unpressed in the default cut, which spells no `show`, and pressed under `?show=archived`, its word unchanged by the press.
Every seat is a query-string fact (`?q=` · `?tag=` · `?show=`): the URL is the
row's state, so a remedy carrying a query lands on the cut it names. A chip is
a native `button` with `aria-pressed`, a word only, no fill, no glyph, at least
`--act-min`; a seat with no question is absent, and a list that can be asked
nothing draws no row. While one or more rows are checked, the bulk road's
selection bar takes this row's seat (`list-select`) and gives it back when the
selection clears: *⟨n⟩ selected* · the bulk verbs EVERY checked row allows, in
the verb table's order, ghost · the × *Clear the selection* at its trail — one
press; the answer is per row (the band, §17). At EXACTLY two checked rows that
both allow merge, the bar also offers *Merge*, in the verb table's order among
the bulk verbs: it opens the merge chooser pre-filled with the two — *Merge ⟨a⟩
and ⟨b⟩ into…*, the row pressed the survivor — then the one confirm (§1); the
merge lands on the survivor's record, focus on its name. Merge is never a bulk
verb: a batch is one press per row. Nothing else sits in the row: no create
act, no count, no sort menu.
**Words.** A chip's word is a lexicon row (*Archived*); a search box's label
is the lexicon's; a narrowing shows the value's name, never its key. No
*Filter*, *Filters*, *Options* as a chip; a filters sheet is §22's. The bar's:
*⟨n⟩ selected*; *Clear the selection* (the ×'s accessible name); the verbs'
own words; no *Bulk* word on a face.
**Placement.** The list route only, between the head (§5) and the rows (§8);
never on a record page, never inside a card or a sheet.
**States.** Empty: the row stays — a narrowed list's empty (§14) names the
chip that narrowed it, and pressing the chip again is the way back. Loading:
the row drawn, every chip pressable (a narrowing is a re-read). Refused: the
row stands over the notice (§15); a whole batch refused (forbidden, too many)
is one notice under the bar, the selection kept. Phone: one row wrapping to
two lines at most, the search box first, the chips after it in the same
order; the bar is one row whose count and × never wrap away from its acts —
the count never breaks, and the acts give up padding before the count gives
up its line.
**Ruling.** `design-agreements.md` § 1 · 4 (one act, the way back on the
screen — a pressed chip is its own way back) · § 1 · 6 (finished, not loud —
absent, never dead) · § 1 · 7 (a value's name, never its key) · ruled
2026-09-29 (the two-row bar): at exactly two checked rows that both allow
merge, the bar offers *Merge*, and the row pressed in its chooser survives.
Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_nothing_disabled.py` (house rule 68: no
chip is disabled) · `quality/runners/js_focus_ring.py` (house rule 67: every
chip wears the ring and consumes the act floor) ·
`quality/runners/js_lexicon.py` (house rule 72: a chip's word is a lexicon
row) · `quality/runners/js_no_toast_spinner.py` (house rule 69: a narrowing
re-read shows still rows, never a spinner) · `quality/runners/js_verb_road.py`
(house rule 77: the bar's verbs are the bulk door's, both ways) ·
`frontend/src/screens/verb-face-census.test.tsx` (the bar in the control row's
seat, its verbs the intersection in table order, ghost) ·
`frontend/src/screens/verbs.test.ts` (the bulk intersection). Declared gap:
"exactly one row" and the seat order are rendered questions no runner asks;
the verb family's face census (the archived cut's story) is where they land.

### §8 · The list and the row

**Shape.** One anatomy for every noun: a list (`ul`, no bullets) of rows, no
table. Each row is ONE pressable — a link to the record route wrapping the
whole row, one focus ring, at least `--act-min` tall — with the name first
(weight 600), at most one pill after it (§16), then the noun's facts as the
row's remaining columns (`--type-facts`, `--muted`). At the desk the row is a
grid — the name block first (`minmax(0, 1fr)`, the name wrapping inside it,
never clipped), then one column per fact aligned across rows; the list is the
page's width, not `--measure` (the measure caps prose, and rows are not
prose). The pill rides the name's last word, joined by a non-breaking space,
so it wraps with that word and is never alone on a line. The phone stacks: the
name block, then the facts under it, the same words. The lead of
the row is reserved for the selection checkbox the bulk road draws when the
row allows a bulk verb; nothing else sits before the name. In the live list a
row holds no button. When the page has more, one act, *Show more*, closes the
list in its foot — SECONDARY weight (the sibling paging act *Show earlier* is
secondary too; ghost is the family's departures, primary is spent), a native
`button` left-aligned to the name column at the desk and full width at the
phone, never sticky, never fired by scroll (nothing runs without a press); its
busy form *Showing more…* stays alive on the same button; the rows arrive
under the last row and focus lands on the first new one. There is no sentinel
after the last row. The bulk road's checkbox leads a row whose answer allows
at least one of the noun's bulk verbs (a native checkbox named *Select
⟨name⟩*, beside the door and never inside it) and is absent on any other row;
after a batch some rows were refused in, each refused row stays checked and
carries its refusal and its remedy's door directly under it. The landing
after a cut row's *Restore* is the NEAREST REMAINING ACT: the next row's
*Restore*, else the previous row's *Restore*, else the empty line.
**Words.** The name verbatim; each fact's label from the noun's copy module,
one lexicon row each; a date is a day; a person is a name; a scope is a name.
No slug, email, id or key in a row.
**Placement.** Under the list head and its rows (§5); the row's door is the
record route from the route table, never a path composed in the screen.
**States.** Empty: the empty state (§14) in the list's seat. Loading: three
still rows at the row's height under `aria-busy` (§13). Refused: the notice
(§15) in the list's seat. Phone: one column — the name block, then the facts
stacked under it — the pressable row unchanged. The archived cut (§20): rows
absent by default; under `?show=archived` the same rows with no pill and one
quiet *Restore* button at the trail — the one row that holds a second pressable,
beside the door and never inside it.
**Ruling.** `design-agreements.md` § 1 · 4 (the next move already on the
screen — the row is it) · § 1 · 7 (no internal vocabulary on a face).
Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_focus_ring.py` (house rule 67: the row's
pressable has its `:focus-visible` rule naming `--focus-ring` and consumes
`--act-min`) · `quality/runners/js_machine_tokens.py` (house rule 73: no slug,
id or key in a fact's label) · `quality/runners/js_no_toast_spinner.py` (house
rule 69: the loading rows are still shapes) ·
`quality/runners/js_nothing_disabled.py` (house rule 68: no dead row, no dead
*Restore*, no disabled checkbox) · `frontend/src/screens/verb-face-census.test.tsx`
(a batch some rows were refused in: *n of m*, the refused rows checked with
their refusal under them) · `frontend/src/screens/verb-focus.test.tsx` (*Show
more* to the first new row; a cut row's *Restore* to the nearest remaining
act; a batch to the band's act, else the first refused row's checkbox).
Declared gap: "the whole row is the one pressable", name-first and the column
order are rendered questions; the verb family's face census is where they
land.

### §9 · The record page grid

**Shape.** Three regions: the head (§6) full width; under it two columns at
the desk — main, at most `--measure` wide, and the rail beside it, `gap:
var(--space-4)`. Main holds the work: the *About* card first (what the thing is,
its description and, as the noun grows, its own fields), then the noun's lists,
then the attachment cards, then History last. The rail holds the standing facts
— the details card first (who owns it, where it lives, when it was made and last
changed) and any reference card. Never in the rail: an act (acts live in the
head), the work, a list of the noun's rows, a band. Every region is cards (§10)
or a list (§8); nothing is painted on the page itself.
**Words.** None of its own — a grid has no words.
**Placement.** The record route's body, under the head; the band (§17), when
there is one, sits between the head and the grid, full width.
**States.** Empty: not a state of a grid — each card says its own. Loading:
each card's still shapes in place. Refused: the notice (§15) in the head's
seat or a card's; the grid stands. Phone: one column — the head, main's cards
in their order, then the rail's cards; the same words.
**Ruling.** `design-agreements.md` § 1 · 4 (one act per screen — the head
holds it, the grid holds none) · § 1 · 1 (the template draws the shape; the
split is the product's). Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_spacing_scale.py` (house rule 65: the
grid's gap is a `--space-*` step) · `quality/runners/js_type_scale.py` (house
rule 64: nothing in a region sets a size off the roles). Declared gap: which
region a card sits in and the phone's one column are rendered layout — the one
class the family design declares out (a browser engine); a reviewer reads them
on the mirror pass (§27, line 9's captures).

### §10 · The card

**Shape.** A bordered block (`--surface-raised`, `1px solid var(--faint)`,
`--radius`, padding `--space-3`), in three parts: the head — a title (`h2`,
`--type-section`, four words or fewer), an optional lede (a fact), a state
pill only when the card carries a state, and at the trail the seat
`data-seat="card-head"` the family's archive act takes on a card noun; the body
— facts as label · value lines, or rows (§8); the foot — acts only, native
buttons left to right, first the act that is the card's work. The primary
weight appears only on the card that is the work of the page, and the route
table's `primarySeat` names that seat; every other card's acts are secondary
or ghost. A card never holds a card. **The History card** (the noun-verb
family's read of what happened to the noun) is the LAST card in main, on the
record page only: rows newest first, each *⟨what⟩ · ⟨name⟩ · ⟨day⟩* — the
verb's state word, or *Changed ⟨field⟩, ⟨field⟩ and ⟨field⟩* in the fields'
words (the generated schema's titles, never a key) — the name dropped when
the trail has none; *Show earlier*, secondary, at its foot, reads the page
before by cursor. It is read-only: no revert act, no raw diff; restoring a
version is an ordinary Edit. **The Notes and Files cards** (attach) sit in
main before History, Notes first: Notes' rows *⟨body⟩ · ⟨day⟩*, newest first;
Files' rows *⟨file name⟩ · ⟨day⟩*, each carrying *Archive* at its trail where
the file's own answer offers it (the `card-head` act of a card noun). Each
card's foot holds its attach act — *Add a note*, *Add a file* — ghost, which
opens an inline field in the card whose own primary is *Add*; one inline field
open at a time, so a face never shows two primaries. Who may add is the
owners' answer: a note on any row the reader can see, a file where the files
list offers `create`; with no answer the act is absent. On an archived or
merged row the cards stay and offer no act.
**Words.** The title is a lexicon row (*About* · *Details* · *History* ·
*Notes* · *Files* — *About* names the work's seat, *Details* the standing facts,
the same pair on every noun's page); the fact labels are the noun's copy
module's; the acts are verbs. History's: *History*; *Show earlier*; *No
history yet.*; *Couldn't load the history*; Activity · Log · Audit · Timeline
are red as its title (house rule 79). Attach's: *Notes* · *Files*; *Add a
note* · *Add a file* · *Add* · *Adding…* · *Couldn't add*; *No notes yet.* ·
*No files yet.*; Comment · Attachment · Label are not its words.
**Placement.** In main or the rail of the record grid (§9), never in a list
head or a sheet; a card's refusal seat is inside it, under its head.
**States.** Empty: the card's empty line (§14) in the body with the add act in
the foot when the role may (History's: *No history yet.*, no door). Loading:
still shapes at the body's heights under `aria-busy`, the title drawn
(History's: three still rows). Refused: the notice (§15) inside the card under
its head, the acts alive (an add refused: *Couldn't add* inside the card,
above its foot, the add act alive). Phone: full width, in main's order, the
foot's acts wrapping. *Show earlier* lands on the first new row; an add act
lands on its field, and the add on the new row.
**Ruling.** `design-agreements.md` § 1 · 4 (one primary, on the work) ·
§ 1 · 6 (finished, not loud) · the verb family's V-1–V-3, V-5, V-6 and V-8
(the History card, attach's cards). Supersedes: nothing — the first entry of
its class; the attach acts at a card's foot are ghost, the verb table's
weight for every family verb (house rule 80 holds the table), not the
*secondary* the attach road's first draft named.
**Instrument.** `quality/runners/js_type_scale.py` (house rule 64: the title
is `--type-section`) · `quality/runners/js_focus_ring.py` (house rule 67: the
foot's buttons wear the ring and the floor) · `quality/runners/js_lexicon.py`
(house rule 72: the title is a lexicon row) ·
`quality/runners/js_verb_words.py` (house rule 79: one word per verb, and
History's title never a synonym) · `frontend/src/screens/verb-face-census.test.tsx`
(≤ 1 primary per story; the History card last in main with no family act in
it; its refusal inside it, under its head; attach's refused story inside its
card, *Couldn't add* first) · `frontend/src/screens/verb-focus.test.tsx`
(*Show earlier* to the first new row; *Add a note* to its field, the add to
the new row). Declared gap: acts-only in the foot has
no runner.

### §14 · Empty states

**Shape.** The `empty` branch of `SurfaceState`, in the seat the ready state
would fill: one sentence, then at most one act — the door. The sentence names
the noun (*No ⟨nouns⟩ yet.*); a narrowed list's sentence names what narrowed
it (*Nothing archived.* · *Nothing for "⟨q⟩".*); a card's names its noun (*No
notes yet.*); an absent fact is not an empty — a label · value line with no
value is not drawn, and a card with no fact left says what is missing (*No
description yet.*, the reader's word for the field, never the wire key's
stem); a record's empty is not a claim about the record (that is the server's `not_found`, §15) — it says *Nothing to show here.*, and its door to the list is the crumb the head carries in every state (§6): the seat under the sentence draws no second link to the same page, so there the sentence stands alone (one door to one page, drawn once — the rule §5 applies when the head yields its create act to the empty's door). The door proposes the next act, in the imperative: the create act only when the page's answer says the hat may create; a widening act when a cut emptied the list; none when there is nothing to propose or when the head already draws it, and then the sentence stands alone. Never an illustration, never a glyph, never a spinner, never a
second sentence.
**Words.** The sentence family above, one row per noun; the door's label is the act's lexicon row. A door is never a page's name — a noun's plural is the title's and the crumb's word (§5, §6), and a door under a sentence wears a verb. No *sorry*, no *yet!*, no *get started*.
**Placement.** The content seat of the list (§8) or the body of the card
(§10); never a page of its own, never a dialog.
**States.** Empty: this entry. Loading: not empty — the surface has not
answered (§13). Refused: not empty — the notice (§15); an empty is the
server's answer, a refusal is its refusal. Phone: the same sentence and the
same door in one column, the door at least `--act-min` tall.
**Ruling.** `design-agreements.md` § 1 · 4 (the person's next move is already
on the screen) · § 1 · 6 (finished, not loud — it states the fact and names
the next act). Supersedes: nothing — the first entry of its class.
**Instrument.** `frontend/src/screens/welcome/welcome-screen.test.tsx` (the
`empty` state proposes the next act rather than reporting emptiness) ·
`quality/runners/js_no_toast_spinner.py` (house rule 69: no spinner where the
answer is) · `quality/runners/js_lexicon.py` (house rule 72: the door's label
is a lexicon row) · `quality/runners/js_nothing_disabled.py` (house rule 68: a
door the hat may not use is absent, never dead) · `frontend/src/screens/widget/widget-record.test.tsx` (the record's empty holds exactly one link to the list route — the crumb — and no act). Declared gap: no instrument
reads the sentence family or refuses an illustration; the test that does is a
word census over every noun's `Empty` story, owed with the verb family's face
census.

### §16 · Pills

**Shape.** A pill is a state word: one inline `span` after a name, the word
alone at `--type-label` with `--type-label-tracking`, tinted by its tone and
never filled — no background, no border, no glyph, no dot. The tone IS the
meaning: a product declares its tones as tokens in its drawer, one per
meaning, and the pill carries `data-tone="<meaning>"` as structure; the
template's worked face knows one tone, neutral (`--muted`). At most one pill
per name — after the record's name in its head (§6), after a row's name in a
list (§8), after a reference's name on another noun's face. A pill is never
pressable (a pressable word is a chip, §7), never a count, never a tag (§2.9's
tag row), never a verb. A row in the archived cut wears no pill (§20); the
archived record's own head wears none — its band says it; only a REFERENCE to
an archived noun wears *Archived*.
**Words.** The word is the lexicon's, mapped from the wire's state in the
noun's copy module — the one wire→word map — so a wire key never reaches a
pill. The verb family's state words (*Archived* · *Moved* · *Merged* ·
*Duplicated*) are its own; a noun's standing states are its copy module's, one
lexicon row each. Sentence case; one word or two, never a sentence.
**Placement.** Inline, directly after the name it qualifies, in the same line;
never in a head's acts row, never in a band, never in a card's foot.
**States.** Empty: no state, no pill — a row in its RESTING state wears
none: every noun has one resting state (the one most rows are in and the
reader assumes), the pill is the departure, and the copy module's wire→word
map carries the resting state as no word (the product names it there).
Loading: no pill on a still shape. Refused: not a pill's state. Phone: the
same word after the same name; it wraps with the name, never alone on a line
above it.
**Ruling.** `design-agreements.md` § 1 · 6 (finished, not loud — a word,
never a fill) · § 1 · 7 (plain language; the wire's key never reaches a face)
· § 1 · 5 (one colour restrained by default — a tone is a token, not a fill).
Supersedes: nothing — the first entry of its class.
**Instrument.** `quality/runners/js_machine_tokens.py` (house rule 73: no wire
key in the map's words) · `quality/runners/js_lexicon.py` (house rule 72: a
pill's word keyed as a label is a lexicon row) ·
`quality/runners/js_type_scale.py` (house rule 64: the pill's size and tracking
are the label role's tokens) · `quality/runners/js_nothing_disabled.py` (house
rule 68: a pill is not a control, so nothing about it is disabled). Declared
gap: "one pill per name, after it, never a fill" is a rendered question; the
verb family's face census (the reference story) and the tone-token set-equality
a product's drawer owes are where it lands.
### §20 · Leaving the book

**Shape.** Every noun leaves one way: *Archive*, ghost, LAST in
`record-acts` (or leading `sheet-acts` for a page-less noun, or at the trail
of `card-head` for a card noun), drawn only when the row's `allowed_acts`
names it. One press: no sheet, no reason, no confirm — the way back is one
press too. **The list** hides archived rows by default; one chip, *Archived*,
at the control row's trail (`?show=archived`, exclusive of the other cuts)
shows them, each row with one quiet *Restore* at its trail and no pill. **The
record** stays reachable, read-only: a band (§17) under the head — *Archived
⟨day⟩ by ⟨name⟩.* with its one act, *Restore*, quiet; the acts row not drawn (a seat holding no act is absent, never an empty element — §7), every card's act gone, zero primary. A reference elsewhere keeps the name, wears the
*Archived* pill (§16) and lands on the face. Nothing is purged from the face.
This section is the archive road's home: the verb family's archive entry lands
here as amendments to these six parts, never as a second entry beside them.
**Words.** Archive · Archiving… · Archived · Couldn't archive; Restore ·
Restoring… · Couldn't restore; *Archived* (chip and pill); *Nothing archived.*; the band sentence — *Archived ⟨day⟩ by ⟨name⟩.* when the wire names the archiver, *Archived ⟨day⟩.* when `archived_by` or its `name` is null (a person is a name or no clause — never an address, an id, or a word for an absence); ⟨day⟩ is the face's one day form (§8). The sentence is the noun's copy module's, composed from the wire's two fields; it is not a lexicon row (rule 72 reads labels). Delete · Remove · Trash · Retire · Deactivate · Discard ·
Hide · Unarchive · Recover are red on a noun that carries the road.
**Placement.** The act in its one seat; the chip in the control row (§7); the
row's *Restore* at its trail (§8); the band under the head (§17).
**States.** Loading: the cut's still rows, the chip pressed. Empty cut:
*Nothing archived.*, no door (§14). Refused: `archive_blocked` in the head's refusal seat (§15), every blocker's remedy a live link, *Archive* still alive; `restore_blocked` under the band — and, in the cut, directly under the row whose *Restore* was pressed, the row still drawn and its *Restore* alive (the seat under the act's row, V-4). Phone: the band's act stacks under its
sentence, full width; the row's *Restore* at least `--act-min`.
**Ruling.** `design-agreements.md` § 1 · 4 (one act, the way back on the
screen) · § 1 · 6 (finished, not loud — no confirm on a reversible act) ·
§ 1b · 4 (the standing remedy prints on refusals and nothing else) · the verb
family's V-1–V-6 and V-8, numbered in § 1 at their fold. Supersedes: nothing —
the first entry of its class.
**Instrument.** `quality/runners/js_nothing_disabled.py` (house rule 68:
*Archive* and *Restore* are drawn or absent, never dead) ·
`quality/runners/js_no_toast_spinner.py` (house rule 69: the outcome is a
band, never a toast) · `quality/runners/js_route_table.py` (house rule 71: the
list route's `operation` column is what a blocker's `route:` remedy resolves
through) · `frontend/src/screens/welcome/welcome-screen.test.tsx` (the notice
renders every blocker's remedy verbatim) · `quality/runners/js_verb_road.py`
(house rule 77: every noun face's road equals the verb doors its wire serves,
both ways — *Archive* and *Restore* drawn where the wire serves them, and
nowhere else) · `quality/runners/js_verb_acts.py` (house rule 78: a family act
is constructed from the verb table, never spelled — *Archive* never in a
confirm, no object-less ask, no seat reordered by a stylesheet) ·
`quality/runners/js_verb_words.py` (house rule 79: one word per verb — Delete,
Remove and the rest red in the copy of a noun that archives) ·
`frontend/src/screens/verb-face-census.test.tsx` (every noun's `Archived`
story: zero primary, no head acts, no pill, the way back drawn; *Archive* last,
ghost, in the admin story; zero family acts in the member story) ·
`frontend/src/screens/verb-focus.test.tsx` (*Archive* to the band's *Restore*;
*Restore* to the record's name; a cut row's *Restore* to the nearest remaining
act) · `frontend/src/screens/remedy-door.test.ts` (a `route:` remedy is a live
link or an unlinked label, never a broken one).

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

**Stylesheets.** A face's own stylesheet is the pattern: one per face
directory, beside its screens, imported only by the screens in that directory
(a route imports `tokens.css` and nothing else; a sheet two directories want is
a component asking to exist, and moves to `components/` with it). Tokens only —
every colour, size, gap, ring and radius is a `var(--…)` or a scale keyword; it
DECLARES no token (`frontend/src/tokens/` is the one declaring layer); every
selector is rooted in the face's own class prefix, derived from the directory's
name — no element selector, no `*`, `:root` or `body`, and no bare `[data-…]`
rule (`data-seat` and `data-act` are the grammar, never a paint hook). Why a
place for face rules must exist: rule 67 asks every pressable class for a rule
of its own, and a phone stack is a media query — neither can be inline; and
neither the tokens layer (a declaring file growing a noun's selectors is the
template shipping taste) nor the primitives (a primitive knows no noun) can be
that place. Rejected: one shared `styles.css` (the collision file every
parallel face rung edits); CSS-in-JS everywhere. Owed instruments: a token
declared outside `frontend/src/tokens/`; a face-sheet selector whose first
compound is not the face's prefix; a face sheet imported from outside its
directory.

**The phone.** One breakpoint: `40rem`. Every width media query under
`frontend/src/` is `(width <= 40rem)` or its complement, in `rem`, and no
other number — the book has two widths, the desk and the phone, and a third is
a third set of captures on every mirror pass; `40rem` is the smallest width at
which the record grid's main (`--measure`) plus its gap (`--space-4`) and a
rail can stand side by side, so the number and §9's stack are one fact. A token
cannot live in a media query, so the value is declared here and repeated
verbatim. A product may not add a second breakpoint by default; one that must
records the value in its drawer's §26 with its reason, and the instrument reads
the drawer's value as the one other allowed number. Rejected: `px` (breaks when
the root font scales); a `matchMedia` reader of a CSS variable (a runtime
reader for a static fact); per-face container queries (per-face phones). Owed
instrument: every `@media` width condition equals this value or the drawer's;
a planted `(max-width: 600px)` is the canary.

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
| §20, §1, §5, §6, §7, §10 | `quality/runners/js_verb_road.py` | house rule 77: every noun face's road equals the verb doors its wire serves, both ways — import where an importer takes the noun, attach where its detail answers `tags`; the bar's verbs are the bulk door's | a road missing its noun's door; a road naming `merge`, `import` or `attach` with no door — red |
| §20, §1, §26 | `quality/runners/js_verb_acts.py` | house rule 78: no hand-spelled `data-act`, no object-less ask, no one-press verb in a dialog and merge only there, no reordered seat, every width query the one breakpoint | a hand `data-act="archive"`; *Archive* in a confirm; `(max-width: 600px)` — red |
| §20, §10 | `quality/runners/js_verb_words.py` | house rule 79: one word per verb in the copy of a noun whose wire carries it | *Delete* in the copy of a noun that archives — red |
| §4 | `quality/runners/js_verb_table.py` | house rule 80: the code's verb table equals the book's, row for row | archive ruled before merge; a verb with no busy form — red |
| §1, §5, §6, §7, §10, §17, §20 | `frontend/src/screens/verb-face-census.test.tsx` | per noun road: the stories each verb owes; the acts in their seat in table order, ghost; ≤ 1 primary; the member draws none; each state and refusal in its seat; merge asked in the confirm; the import preview's one counted primary; attach's acts only at a card's foot or the tag row | a road declaring a verb whose stories are absent — red |
| §1, §5, §6, §8, §10, §20 | `frontend/src/screens/verb-focus.test.tsx` | the focus road, as `document.activeElement` after each press | a landing cut from a face — red |
| §5 | `frontend/src/screens/widget/widget-import.test.tsx` | the worked import page: every state drawn from the run row, its words, one primary, the apply's busy word on the same button | a preview drawing a second primary — red |
| §1, §6, §10 | `frontend/src/screens/widget/widget-record.test.tsx` | the worked record: the move sheet's current node marked and never a choice; the merge chooser and confirm; the copy's band; the attach cards and the tag row | the current node offered as a radio — red |
| §4, §7 | `frontend/src/screens/verbs.test.ts` | `actsFor` and the bulk intersection in table order; a busy form for every verb; the foot's one press | a verb with no busy form — red |
| §15, §20 | `frontend/src/screens/remedy-door.test.ts` | a `route:` remedy is a live link where a page draws the operation, else its label unlinked | an unknown url name drawn as a link — red |

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
