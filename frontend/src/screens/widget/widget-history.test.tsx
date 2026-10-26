import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { HISTORY_WORDS } from "@pilecap/copy/widget";
import { VERB_TABLE } from "@pilecap/ui/verbs";
import { historyWhat } from "@/screens/widget/widget-history";

/**
 * THE WIRE'S VERBS, read from the document of record: the history entry's
 * `verb` enum, when the document publishes one. `undefined` while it does not —
 * and the pin below is then skipped with its reason, never passed.
 */
function wireVerbs(): readonly string[] | undefined {
    const document = JSON.parse(readFileSync(resolve(process.cwd(), "openapi.json"), "utf8")) as {
        readonly components: { readonly schemas: Readonly<Record<string, { readonly properties?: Readonly<Record<string, { readonly enum?: readonly string[] }>> }>> };
    };
    return document.components.schemas.HistoryEntryOut?.properties?.verb?.enum;
}

const WIRE = wireVerbs();
const FAMILY = new Set<string>(VERB_TABLE.map((row) => row.verb));

describe("the History card's words are the wire's", () => {
    it("a family verb with a state word in the verb table wears that word, read off the table", () => {
        for (const row of VERB_TABLE) {
            if (row.state !== null) expect(historyWhat(row.verb, []), row.verb).toBe(row.state);
        }
    });

    it("the noun's own words never re-spell a family verb the table already words", () => {
        for (const verb of Object.keys(HISTORY_WORDS)) {
            const row = VERB_TABLE.find((candidate) => candidate.verb === verb);
            expect(row?.state ?? null, verb).toBeNull();
        }
    });

    // Pinned against the document's `HistoryEntryOut.verb` enum. The document
    // does not publish one yet, so the pin is skipped with this reason; the day it
    // does, the pin runs with nothing else changed.
    it.skipIf(WIRE === undefined)("every key of the noun's words is a verb the wire's trail can say, and every family verb on the wire has a word", () => {
        const wire = new Set(WIRE ?? []);
        for (const verb of Object.keys(HISTORY_WORDS)) expect(wire, verb).toContain(verb);
        // The edit is the one family verb whose word is the sentence of what it changed (*Changed ⟨fields⟩*).
        for (const verb of wire) {
            if (FAMILY.has(verb) && verb !== "update") expect(historyWhat(verb, []), verb).not.toBe("Changed");
        }
    });
});
