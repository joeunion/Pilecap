// golden: history begin
// patterns: §10, §13, §14, §15
"use client";
// golden: history end

/**
 * EXAMPLE — the worked Widget's History card: what happened to this noun,
 * read-only (patterns.md §10, the card). A product
 * copies it for its own noun.
 *
 * The LAST card in the record page's main. Its rows run newest first, each
 * *⟨what⟩ · ⟨name⟩ · ⟨day⟩*: the verb's state word, or *Changed ⟨fields⟩* in
 * the reader's words (the schema's titles, never a key). *Show earlier*,
 * secondary, at the card's foot, reads the next page by cursor and lands on
 * the first new row. There is no revert act; restoring a version is an
 * ordinary Edit.
 *
 * ONE HONEST ABSENCE: *Use these values* (a row opening Edit prefilled) is not
 * drawn, because the trail keeps no values — the wire names which fields a
 * change was given, never what they were.
 *
 * It renders and never fetches: the route reads `…/history/` and hands the
 * card its state and, when there is more, the press that reads it.
 */

// golden: history begin
import { useEffect, useRef } from "react";

import { changedWhat, HISTORY_WORDS, WIDGET_COPY as C } from "@pilecap/copy/widget";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { STAFF_SURFACE } from "@pilecap/ui/routes";
import type { SurfaceState } from "@pilecap/ui/state";
import { unhandledState } from "@pilecap/ui/state";
import { VERB_TABLE } from "@pilecap/ui/verbs";
import { Card } from "@pilecap/ui/card";
import { StillLine } from "@pilecap/ui/still-line";
import { dayOf, type HistoryEntry, type HistoryPage } from "@/screens/widget/parts";

/** What the route hands the card: its read, and *Show earlier* when the page has more. */
export type HistoryPress = {
    readonly state: SurfaceState<HistoryPage>;
    readonly earlier?: { readonly onShowEarlier: () => void; readonly busy: boolean };
};

/**
 * ONE HISTORY ROW'S WHAT (patterns.md §10): a family verb's state word, read
 * off the verb table; else the noun's own word for its own verb; else
 * *Changed ⟨fields⟩*. The family's words are never spelled a second time.
 */
export function historyWhat(verb: string, changed: readonly string[]): string {
    return VERB_TABLE.find((row) => row.verb === verb)?.state ?? HISTORY_WORDS[verb] ?? changedWhat(changed);
}

/** One row: what, who (a name or no clause — never an address or an id), and the day. */
function rowWords(entry: HistoryEntry): string {
    const who = entry.actor?.name;
    const parts = [historyWhat(entry.verb, entry.changed_fields ?? [])];
    if (who !== null && who !== undefined && who.trim() !== "") parts.push(who);
    parts.push(dayOf(entry.at));
    return parts.join(" · ");
}

export function HistoryCard({ history }: { readonly history: HistoryPress }) {
    const { state, earlier } = history;
    const rows = useRef(new Map<number, HTMLLIElement>());
    const landing = useRef<number | null>(null);
    const count = state.kind === "ready" ? state.data.items.length : 0;

    // *Show earlier* lands on the first new row when the page it asked for arrives.
    useEffect(() => {
        const armed = landing.current;
        if (armed === null || count <= armed) return;
        landing.current = null;
        rows.current.get(armed)?.focus();
    }, [count]);

    switch (state.kind) {
        case "loading":
            return (
                <Card title={C.historyTitle} busy>
                    <p className="widget-quiet">{C.loadingHistory}</p>
                    <StillLine />
                    <StillLine />
                    <StillLine />
                </Card>
            );
        case "empty":
            return (
                <Card title={C.historyTitle}>
                    <p className="widget-quiet">{C.historyEmpty}</p>
                </Card>
            );
        case "error":
            return (
                <Card title={C.historyTitle}>
                    <RefusalPanel
                        surface={STAFF_SURFACE}
                        refusal={state.refusal}
                        seat="card-head"
                        refused={VERB_TABLE.find((row) => row.verb === "history")?.refused}
                    />
                </Card>
            );
        case "ready":
            return (
                <Card title={C.historyTitle}>
                    <ol className="widget-history">
                        {state.data.items.map((entry, index) => (
                            <li
                                key={`${entry.at}:${index}`}
                                tabIndex={-1}
                                ref={(el) => {
                                    if (el === null) rows.current.delete(index);
                                    else rows.current.set(index, el);
                                }}
                            >
                                {rowWords(entry)}
                            </li>
                        ))}
                    </ol>
                    {state.data.has_more && earlier !== undefined ? (
                        <button
                            type="button"
                            className="widget-more"
                            data-weight="secondary"
                            aria-busy={earlier.busy ? "true" : undefined}
                            onClick={() => {
                                landing.current = state.data.items.length;
                                earlier.onShowEarlier();
                            }}
                        >
                            {C.showEarlierAct}
                        </button>
                    ) : null}
                </Card>
            );
    }
    return unhandledState(state);
}
// golden: history end
