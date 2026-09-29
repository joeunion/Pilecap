import { describe, expect, it } from "vitest";

import { LEXICON } from "@/copy/lexicon";
import { actsFor, bulkActsFor, footAct, pairActsFor, VERB_TABLE, type Road } from "@/screens/verbs";

/** A road declaring every record act, as a noun that adopted the whole family would. */
const ROAD: Road = {
    noun: "widget",
    seat: "record-acts",
    verbs: ["archive", "merge", "update", "duplicate", "move"],
    bulk: ["archive", "restore", "move"],
};

/** Rows shaped like a list answer: `allowed_acts` is the server's answer for the acting hat. */
const ADMIN = { allowed_acts: ["approve", "archive", "move", "update", "merge", "duplicate"] };
const MEMBER = { allowed_acts: [] as string[] };
const ARCHIVED = { allowed_acts: ["restore"] };

describe("the verb table transcribes the grammar's table, row for row", () => {
    it("holds the nine families in the table's order", () => {
        expect(VERB_TABLE.map((row) => row.verb)).toEqual([
            "update", "move", "duplicate", "merge", "archive", "restore", "import", "attach", "history",
        ]);
    });

    it("numbers the record acts 1 to 5 with archive last, and no other verb sits there", () => {
        const record = VERB_TABLE.filter((row) => row.order !== null);
        expect(record.map((row) => [row.verb, row.order])).toEqual([
            ["update", 1], ["move", 2], ["duplicate", 3], ["merge", 4], ["archive", 5],
        ]);
    });

    it("merge alone asks a confirm; import's preview is its second look; history has no act", () => {
        const press = Object.fromEntries(VERB_TABLE.map((row) => [row.verb, row.press]));
        expect(press).toEqual({
            update: "one", move: "one", duplicate: "one", merge: "confirm", archive: "one",
            restore: "one", import: "preview", attach: "one", history: "none",
        });
    });

    it("every family act is ghost weight: no family verb is ever primary", () => {
        expect(new Set(VERB_TABLE.map((row) => row.weight))).toEqual(new Set(["ghost"]));
    });

    it("every verb with an act has a busy form, and every verb has a refused label", () => {
        for (const row of VERB_TABLE) {
            if (row.press !== "none") expect(row.busy.length, row.verb).toBeGreaterThan(0);
            expect(row.refused.length, row.verb).toBeGreaterThan(0);
        }
    });

    it("the words are the table's", () => {
        const archive = VERB_TABLE.find((row) => row.verb === "archive");
        expect(archive).toMatchObject({
            pressed: ["Archive"], busy: ["Archiving…"], state: "Archived", refused: "Couldn't archive",
            wayBack: { verb: "restore", word: "Restore" },
        });
        expect(VERB_TABLE.find((row) => row.verb === "merge")?.wayBack).toBeNull();
        expect(VERB_TABLE.find((row) => row.verb === "update")?.wayBack?.word).toBe("Edit");
        expect(VERB_TABLE.find((row) => row.verb === "duplicate")?.wayBack?.word).toBe("Archive");
        expect(VERB_TABLE.find((row) => row.verb === "import")?.wayBack?.word).toBe("Archive");
        expect(VERB_TABLE.find((row) => row.verb === "restore")?.state).toBeNull();
    });

    it("every word is a lexicon row", () => {
        const lexicon = new Set<string>(LEXICON);
        for (const row of VERB_TABLE) {
            const words = [
                ...row.pressed,
                ...row.busy,
                row.state,
                row.foot,
                row.refused,
                row.wayBack?.word,
                ...Object.values(row.wayBackByKind ?? {}),
            ];
            for (const word of words) if (word !== null && word !== undefined) expect(lexicon, word).toContain(word);
        }
    });
});

describe("attach's way back is per kind", () => {
    it("a note and a file are archived; a tag is removed", () => {
        const attach = VERB_TABLE.find((row) => row.verb === "attach");
        expect(attach?.wayBack).toBeNull();
        expect(attach?.wayBackByKind).toEqual({ note: "Archive", file: "Archive", tag: "Remove tag" });
    });
});

describe("actsFor = the road ∩ the row's allowed_acts, in table order", () => {
    it("an admin row draws the road's verbs it allows, in table order, whatever order the road or the wire used", () => {
        expect(actsFor(ADMIN, ROAD).map((act) => act.verb)).toEqual(["update", "move", "duplicate", "merge", "archive"]);
    });

    it("a verb the row does not allow is absent, never drawn dead", () => {
        const acts = actsFor({ allowed_acts: ["archive", "update"] }, ROAD);
        expect(acts.map((act) => act.verb)).toEqual(["update", "archive"]);
    });

    it("a verb the road does not declare is absent even when the row allows it", () => {
        const road: Road = { ...ROAD, verbs: ["archive"] };
        expect(actsFor(ADMIN, road).map((act) => act.verb)).toEqual(["archive"]);
    });

    it("the noun's own acts are not family acts", () => {
        expect(actsFor(ADMIN, ROAD).map((act) => act.verb)).not.toContain("approve");
    });

    it("a member row draws no family act at all", () => {
        expect(actsFor(MEMBER, ROAD)).toEqual([]);
    });

    it("an archived row draws NO head act: its way back is the band's, never record-acts'", () => {
        const road: Road = { ...ROAD, verbs: [...ROAD.verbs, "restore"] };
        expect(actsFor(ARCHIVED, road)).toEqual([]);
    });

    it("placement ∩ allowed_acts: a row allowing restore AND archive draws Archive in record-acts and Restore only in the band and the cut row", () => {
        const road: Road = { noun: "widget", seat: "record-acts", verbs: ["archive", "restore"] };
        const row = { allowed_acts: ["restore", "archive"] };
        expect(actsFor(row, road).map((act) => act.verb)).toEqual(["archive"]);
        expect(actsFor(row, road, "band").map((act) => act.verb)).toEqual(["restore"]);
        expect(actsFor(row, road, "cut-row").map((act) => act.verb)).toEqual(["restore"]);
        // The server's answer for an archived row is `restore` alone, so its head acts are empty.
        expect(actsFor({ allowed_acts: ["restore"] }, road)).toEqual([]);
    });

    it("an archived row's Restore is drawn in the band and in the cut's row", () => {
        const road: Road = { ...ROAD, verbs: [...ROAD.verbs, "restore"] };
        expect(actsFor(ARCHIVED, road, "band").map((act) => act.verb)).toEqual(["restore"]);
        expect(actsFor(ARCHIVED, road, "cut-row").map((act) => act.verb)).toEqual(["restore"]);
        expect(actsFor(ARCHIVED, road, "band")[0]?.seat).toBe("band");
    });

    it("record-acts draws only edit, move, duplicate, merge and archive, whatever the row allows", () => {
        const road: Road = { ...ROAD, verbs: ["archive", "restore", "import", "history"] };
        const row = { allowed_acts: ["restore", "archive", "history", "import"] };
        expect(actsFor(row, road).map((act) => act.verb)).toEqual(["archive"]);
    });

    it("the band and the cut row draw restore only", () => {
        const road: Road = { ...ROAD, verbs: ["archive", "restore", "import", "move"] };
        const row = { allowed_acts: ["restore", "archive", "import", "move"] };
        expect(actsFor(row, road, "band").map((act) => act.verb)).toEqual(["restore"]);
        expect(actsFor(row, road, "cut-row").map((act) => act.verb)).toEqual(["restore"]);
    });

    it("a list-head road draws import only", () => {
        const road: Road = { noun: "widget", seat: "list-head", verbs: ["archive", "import", "move", "restore"] };
        const row = { allowed_acts: ["archive", "import", "move", "restore"] };
        expect(actsFor(row, road).map((act) => act.verb)).toEqual(["import"]);
    });

    it("a card-head road draws archive only", () => {
        const road: Road = { noun: "note", seat: "card-head", verbs: ["update", "archive", "move"] };
        expect(actsFor({ allowed_acts: ["update", "archive", "move"] }, road).map((act) => act.verb)).toEqual(["archive"]);
    });

    it("every verb's places are the grammar's", () => {
        const places = Object.fromEntries(VERB_TABLE.map((row) => [row.verb, row.places]));
        expect(places).toEqual({
            update: ["record-acts", "sheet-acts"],
            move: ["record-acts", "sheet-acts", "list-select"],
            duplicate: ["record-acts", "sheet-acts"],
            merge: ["record-acts", "sheet-acts", "list-select"],
            archive: ["record-acts", "sheet-acts", "card-head", "list-select"],
            restore: ["band", "cut-row", "list-select"],
            import: ["list-head"],
            attach: ["card-foot", "tag-row"],
            history: [],
        });
    });

    it("each act carries its words, the road's seat, ghost weight and the structure attributes", () => {
        const [archive] = actsFor({ allowed_acts: ["archive"] }, ROAD);
        expect(archive).toMatchObject({
            verb: "archive",
            label: "Archive",
            busy: "Archiving…",
            weight: "ghost",
            seat: "record-acts",
            attrs: { "data-act": "archive", "data-weight": "ghost" },
        });
    });

    it("history is never an act, even if a road and a row both name it", () => {
        const road: Road = { ...ROAD, verbs: ["history"] };
        expect(actsFor({ allowed_acts: ["history"] }, road)).toEqual([]);
    });
});

describe("bulkActsFor = the road's bulk verbs every checked row allows", () => {
    it("is the intersection over the selection, in table order", () => {
        const rows = [{ allowed_acts: ["archive", "move"] }, { allowed_acts: ["move", "archive", "update"] }];
        expect(bulkActsFor(rows, ROAD).map((act) => act.verb)).toEqual(["move", "archive"]);
    });

    it("one row that does not allow a verb takes it off the bar", () => {
        const rows = [{ allowed_acts: ["archive", "move"] }, { allowed_acts: ["move"] }];
        expect(bulkActsFor(rows, ROAD).map((act) => act.verb)).toEqual(["move"]);
    });

    it("an empty selection draws no bar act", () => {
        expect(bulkActsFor([], ROAD)).toEqual([]);
    });

    it("draws only the bulk verbs the table places in the selection bar", () => {
        const road: Road = { ...ROAD, bulk: ["archive", "restore", "move", "update", "import"] };
        const rows = [{ allowed_acts: ["archive", "restore", "move", "update", "import"] }];
        expect(bulkActsFor(rows, road).map((act) => act.verb)).toEqual(["move", "archive", "restore"]);
    });

    it("sits in the selection bar's seat", () => {
        expect(bulkActsFor([{ allowed_acts: ["archive"] }], ROAD)[0]?.seat).toBe("list-select");
    });
});

describe("pairActsFor = merge in the selection bar, at exactly two rows that both allow it", () => {
    const road: Road = { ...ROAD, verbs: [...ROAD.verbs, "merge"] };
    it("draws Merge at two rows that both allow it, in the bar's seat", () => {
        const acts = pairActsFor([{ allowed_acts: ["merge"] }, { allowed_acts: ["merge", "archive"] }], road);
        expect(acts.map((act) => [act.verb, act.seat, act.weight])).toEqual([["merge", "list-select", "ghost"]]);
    });

    it("draws nothing at one row, at three, when one row does not allow it, or when the road does not draw merge", () => {
        expect(pairActsFor([{ allowed_acts: ["merge"] }], road)).toEqual([]);
        expect(pairActsFor([{ allowed_acts: ["merge"] }, { allowed_acts: ["merge"] }, { allowed_acts: ["merge"] }], road)).toEqual([]);
        expect(pairActsFor([{ allowed_acts: ["merge"] }, { allowed_acts: [] }], road)).toEqual([]);
        expect(pairActsFor([{ allowed_acts: ["merge"] }, { allowed_acts: ["merge"] }], { ...ROAD, verbs: ["archive"] })).toEqual([]);
    });

    it("merge is never a bulk act, whatever the rows allow", () => {
        expect(bulkActsFor([{ allowed_acts: ["merge"] }, { allowed_acts: ["merge"] }], { ...road, bulk: ["merge"] })).toEqual([]);
    });
});

describe("footAct: the press at the foot of the sheet a verb opened", () => {
    it("is the table's foot word, the sheet's one primary, at the sheet's foot", () => {
        const save = footAct(ADMIN, ROAD, "update");
        expect(save).toMatchObject({ verb: "update", label: "Save", busy: "Saving…", weight: "primary", seat: "sheet-foot" });
        expect(save?.attrs).toEqual({ "data-act": "update", "data-weight": "primary" });
        expect(footAct(ADMIN, ROAD, "move")?.label).toBe("Move");
        expect(footAct(ADMIN, ROAD, "merge")?.label).toBe("Merge");
    });

    it("is absent for a verb that opens no sheet, one the road does not draw, or one the row does not allow", () => {
        expect(footAct(ADMIN, ROAD, "archive")).toBeNull();
        expect(footAct(ADMIN, ROAD, "duplicate")).toBeNull();
        expect(footAct(ADMIN, { ...ROAD, verbs: ["archive"] }, "update")).toBeNull();
        expect(footAct(MEMBER, ROAD, "update")).toBeNull();
    });
});
