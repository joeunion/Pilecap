// patterns: none — draws no face
/**
 * THE VERB TABLE — the noun-verb family's one declaration on the client.
 *
 * Every noun face draws its family acts (edit, move, duplicate, merge, archive,
 * and the rest) from THIS table, through `actsFor`, and never by hand: the
 * order, the press, the weight and the words are constructed here, not
 * remembered on each face. The table transcribes the design grammar's verb
 * table row for row; a change to one is a change to both.
 *
 * WHO SEES AN ACT IS THE SERVER'S ANSWER. An act is drawn iff its verb is in
 * the row's `allowed_acts`, the server's policy evaluated for the acting hat
 * against that row. The client reads it and never computes it, and it never
 * asks object-less ("may I archive widgets?"): an act the row does not allow is
 * absent, never drawn dead.
 *
 * THE WORDS ARE LEXICON ROWS (`@/copy/lexicon`), typed as such, so a word that
 * is not a row does not compile. A product renames a verb once, in the lexicon,
 * product-wide.
 *
 * Pure: no markup, no fetch. A face spreads `act.attrs` onto its button.
 */

import type { LexiconWord } from "@/copy/lexicon";

/** The five seats a family act may sit in. A sixth is a book entry, not a builder's choice. */
export const SEATS = ["record-acts", "sheet-acts", "card-head", "list-select", "list-head"] as const;
export type Seat = (typeof SEATS)[number];

/** What attach adds, and so what its way back is per kind. */
export type AttachKind = "note" | "file" | "tag";

export type Verb = "update" | "move" | "duplicate" | "merge" | "archive" | "restore" | "import" | "attach" | "history";

/** How an act is pressed: once; through the one confirm (merge only); through a preview (import); or not an act. */
export type Press = "one" | "confirm" | "preview" | "none";

/**
 * Every place a family act may be drawn: the five seats, plus the way back's
 * two homes (the archived face's band and the archived cut's row, which are
 * not seats of their own), attach's two (a card's foot, the tag row), and the
 * foot of the sheet an act opened (Edit's *Save*, Move's *Move*): the press
 * that answers the sheet's question, and the seat its refusal sits above.
 */
export type Place = Seat | "band" | "cut-row" | "card-foot" | "tag-row" | "sheet-foot";

export type VerbRow = {
    readonly verb: Verb;
    /** The act's label(s). Attach has three; history has none. */
    readonly pressed: readonly LexiconWord[];
    /** The word on the foot's primary when the act opens a sheet or the confirm; `null` when it opens none. */
    readonly foot: LexiconWord | null;
    /** The busy form(s): the same button, alive, saying the progressive. */
    readonly busy: readonly LexiconWord[];
    /** The state word a band or pill shows; `null` where the table says none. */
    readonly state: LexiconWord | null;
    /** The refusal notice's first line. */
    readonly refused: LexiconWord;
    /** The act that undoes it, and its word; `null` where there is none, or where it differs per kind. */
    readonly wayBack: { readonly verb: Verb; readonly word: LexiconWord } | null;
    /**
     * Attach's way back, per kind: a note and a file are archived; a tag has no
     * archive door, so it is removed (*Remove tag*, whose accessible name
     * appends the tag's name).
     */
    readonly wayBackByKind?: Readonly<Record<AttachKind, LexiconWord>>;
    readonly press: Press;
    /** Position in `record-acts` (archive is last); `null` for a verb that never sits there. */
    readonly order: number | null;
    /** The places this verb's act may be drawn; an act is never drawn anywhere else. History has none. */
    readonly places: readonly Place[];
    /** No family verb is ever primary: the one primary on a surface is the noun's own. */
    readonly weight: "ghost";
};

export const VERB_TABLE: readonly VerbRow[] = [
    {
        verb: "update",
        pressed: ["Edit"],
        foot: "Save",
        busy: ["Saving…"],
        state: null,
        refused: "Couldn't save",
        wayBack: { verb: "update", word: "Edit" },
        press: "one",
        order: 1,
        places: ["record-acts", "sheet-acts"],
        weight: "ghost",
    },
    {
        verb: "move",
        pressed: ["Move"],
        foot: "Move",
        busy: ["Moving…"],
        state: "Moved",
        refused: "Couldn't move",
        wayBack: { verb: "move", word: "Move again" },
        press: "one",
        order: 2,
        places: ["record-acts", "sheet-acts", "list-select"],
        weight: "ghost",
    },
    {
        verb: "duplicate",
        pressed: ["Duplicate"],
        foot: null,
        busy: ["Duplicating…"],
        state: "Duplicated",
        refused: "Couldn't duplicate",
        wayBack: { verb: "archive", word: "Archive" },
        press: "one",
        order: 3,
        places: ["record-acts", "sheet-acts"],
        weight: "ghost",
    },
    {
        verb: "merge",
        pressed: ["Merge"],
        foot: "Merge",
        busy: ["Merging…"],
        state: "Merged",
        refused: "Couldn't merge",
        wayBack: null,
        press: "confirm",
        order: 4,
        // The selection bar only at EXACTLY two checked rows (`pairActsFor`): merge is no bulk verb.
        places: ["record-acts", "sheet-acts", "list-select"],
        weight: "ghost",
    },
    {
        verb: "archive",
        pressed: ["Archive"],
        foot: null,
        busy: ["Archiving…"],
        state: "Archived",
        refused: "Couldn't archive",
        wayBack: { verb: "restore", word: "Restore" },
        press: "one",
        order: 5,
        places: ["record-acts", "sheet-acts", "card-head", "list-select"],
        weight: "ghost",
    },
    {
        verb: "restore",
        pressed: ["Restore"],
        foot: null,
        busy: ["Restoring…"],
        state: null,
        refused: "Couldn't restore",
        wayBack: { verb: "archive", word: "Archive" },
        press: "one",
        order: null,
        places: ["band", "cut-row", "list-select"],
        weight: "ghost",
    },
    {
        verb: "import",
        pressed: ["Import"],
        // The preview's primary names the count it will write ("Import ⟨n⟩
        // ⟨nouns⟩"), composed from the noun's words at run time, so no row here.
        foot: null,
        busy: ["Checking…", "Importing…"],
        state: "Imported",
        refused: "Couldn't import",
        wayBack: { verb: "archive", word: "Archive" },
        press: "preview",
        order: null,
        places: ["list-head"],
        weight: "ghost",
    },
    {
        verb: "attach",
        pressed: ["Add a note", "Add a file", "Add a tag"],
        foot: null,
        busy: ["Adding…"],
        state: null,
        refused: "Couldn't add",
        wayBack: null,
        wayBackByKind: { note: "Archive", file: "Archive", tag: "Remove tag" },
        press: "one",
        order: null,
        places: ["card-foot", "tag-row"],
        weight: "ghost",
    },
    {
        verb: "history",
        pressed: [],
        foot: null,
        busy: [],
        state: null,
        refused: "Couldn't load the history",
        wayBack: null,
        press: "none",
        order: null,
        places: [],
        weight: "ghost",
    },
];

/** What a noun face declares once: the seat its acts sit in and the verbs it draws. */
export type Road = {
    readonly noun: string;
    readonly seat: Seat;
    readonly verbs: readonly Verb[];
    readonly bulk?: readonly Verb[];
};

/** Anything carrying the server's per-row answer. It may name the noun's own acts too; those are not family acts. */
export type ActsSubject = { readonly allowed_acts: readonly string[] };

export type Act = {
    readonly verb: Verb;
    readonly label: LexiconWord;
    readonly busy: LexiconWord;
    readonly weight: "ghost" | "primary";
    readonly seat: Place;
    readonly words: VerbRow;
    readonly attrs: { readonly "data-act": Verb; readonly "data-weight": "ghost" | "primary" };
};

function toAct(row: VerbRow, seat: Place): Act | null {
    const label = row.pressed[0];
    const busy = row.busy[0];
    if (row.press === "none" || label === undefined || busy === undefined) return null;
    return {
        verb: row.verb,
        label,
        busy,
        weight: row.weight,
        seat,
        words: row,
        attrs: { "data-act": row.verb, "data-weight": row.weight },
    };
}

function drawn(verbs: readonly Verb[], allowed: (verb: Verb) => boolean, seat: Place): Act[] {
    const acts: Act[] = [];
    for (const row of VERB_TABLE) {
        if (!row.places.includes(seat) || !verbs.includes(row.verb) || !allowed(row.verb)) continue;
        const act = toAct(row, seat);
        if (act !== null) acts.push(act);
    }
    return acts;
}

/**
 * The acts drawn at one place for this row: the road's verbs whose table
 * places include it, that the row allows, in table order. The place is the
 * road's seat unless the face is drawing the way back (`band`, `cut-row`) or an
 * attach place. So an archived row (whose answer is `restore`) draws nothing in
 * `record-acts` and its *Restore* in the band.
 */
export function actsFor(row: ActsSubject, road: Road, place: Place = road.seat): Act[] {
    return drawn(road.verbs, (verb) => row.allowed_acts.includes(verb), place);
}

/** The road's bulk verbs that EVERY checked row allows, in table order, for the selection bar. */
export function bulkActsFor(rows: readonly ActsSubject[], road: Road): Act[] {
    if (rows.length === 0) return [];
    // A batch is one press per row: a verb asked through the confirm (merge) is never a bulk act.
    const onePress = (road.bulk ?? []).filter((verb) => VERB_TABLE.find((row) => row.verb === verb)?.press === "one");
    return drawn(onePress, (verb) => rows.every((row) => row.allowed_acts.includes(verb)), "list-select");
}

/**
 * The selection bar's PAIR acts — merge, at exactly two checked rows that both
 * allow it, where the road draws merge. Merge is no bulk verb (no batch takes
 * it: it is the one confirm's), so it is not in `bulkActsFor`; the bar draws
 * these beside the bulk acts, in table order.
 */
export function pairActsFor(rows: readonly ActsSubject[], road: Road): Act[] {
    if (rows.length !== 2) return [];
    return drawn(
        road.verbs.filter((verb) => verb === "merge"),
        (verb) => rows.every((row) => row.allowed_acts.includes(verb)),
        "list-select",
    );
}

/**
 * The press at the foot of the sheet a verb opened — Edit's *Save*, Move's
 * *Move* — or `null` when the road does not draw the verb, the table gives it
 * no foot word, or the row does not allow it. A sheet that collects an
 * argument is not a confirm: its foot's ONE primary is the one press (the
 * book's §1, the sheet), and it is the sheet's primary, never the page's —
 * the family's acts on the page stay ghost.
 */
export function footAct(row: ActsSubject, road: Road, verb: Verb): Act | null {
    const words = VERB_TABLE.find((candidate) => candidate.verb === verb);
    const busy = words?.busy[0];
    if (words === undefined || words.foot === null || busy === undefined) return null;
    if (!road.verbs.includes(verb) || !row.allowed_acts.includes(verb)) return null;
    return {
        verb,
        label: words.foot,
        busy,
        weight: "primary",
        seat: "sheet-foot",
        words,
        attrs: { "data-act": verb, "data-weight": "primary" },
    };
}

/**
 * Attach's act for one kind — *Add a note* and *Add a file* at a card's foot,
 * *Add a tag* in the tag row — or `null` when the road does not draw attach.
 * The answer to WHO may attach is the owner's, not the row's: a note and a tag
 * may be put on any row the reader can see (the owners' policy), so reading
 * the row is the answer; a file asks its own list's `create`, which the route
 * reads and hands over. A face draws the act only where the route handed its
 * press, and never on an archived or merged row.
 */
export function attachAct(road: Road, kind: AttachKind): Act | null {
    const words = VERB_TABLE.find((row) => row.verb === "attach");
    if (words === undefined || !road.verbs.includes("attach")) return null;
    const label = words.pressed[["note", "file", "tag"].indexOf(kind)];
    const busy = words.busy[0];
    if (label === undefined || busy === undefined) return null;
    return {
        verb: "attach",
        label,
        busy,
        weight: words.weight,
        seat: kind === "tag" ? "tag-row" : "card-foot",
        words,
        attrs: { "data-act": "attach", "data-weight": words.weight },
    };
}

/**
 * The import page's two presses, the page's one act at a time: STAGE (*Import*
 * on the chosen file, busy *Checking…*) and APPLY (its label the count it will
 * write — composed by the face from the noun's words — busy *Importing…*).
 * Both primary: the import page's one act. `null` when the road does not draw
 * import. Who may import is the list's `create` answer — an import applies the
 * noun's own create, row by row — which the route reads and hands over.
 */
export function importActs(road: Road): { readonly stage: Act; readonly apply: Act } | null {
    const words = VERB_TABLE.find((row) => row.verb === "import");
    const label = words?.pressed[0];
    const [checking, importing] = words?.busy ?? [];
    if (words === undefined || label === undefined || checking === undefined || importing === undefined || !road.verbs.includes("import")) return null;
    const act = (busy: LexiconWord): Act => ({
        verb: "import",
        label,
        busy,
        weight: "primary",
        seat: "list-head",
        words,
        attrs: { "data-act": "import", "data-weight": "primary" },
    });
    return { stage: act(checking), apply: act(importing) };
}

/**
 * The list head's *Import*, ghost, after the create act: drawn iff the road
 * draws import and the list's own answer offers `create` (an import is the
 * noun's create, row by row). `null` otherwise.
 */
export function importHeadAct(road: Road, listActs: readonly string[]): Act | null {
    if (!listActs.includes("create")) return null;
    return actsFor({ allowed_acts: ["import"] }, road, "list-head")[0] ?? null;
}
