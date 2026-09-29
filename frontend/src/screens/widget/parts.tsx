// golden: face begin
// patterns: §10, §16
// golden: face end
/**
 * EXAMPLE — the worked Widget face's shared parts: the card (patterns.md §10),
 * the state pill (§16), the fact line and the day. Token-only paint, no new
 * token, no primitive shipped: a product that fills `primitives/` replaces
 * these with its own and the screens above do not move.
 */

// golden: face begin
import type { ReactNode } from "react";

import type { components } from "@/api/generated/schema";
// golden: face end

// golden: face begin
/** The document's own shapes, used verbatim (fe-conventions §4, Law 3). */
export type Widget = components["schemas"]["WidgetOut"];
export type WidgetPage = components["schemas"]["PagedWidgetOut"];
/** The record's read: the row, and what its detail adds (the tags on it). */
export type WidgetDetail = components["schemas"]["WidgetDetailOut"];
// golden: face end
// golden: version begin
/** What a save sends: the fields, and the `version` the sheet read (required — a save that forgets it does not compile). */
export type WidgetPatch = components["schemas"]["WidgetPatch"];
// golden: version end
// golden: move begin
// golden: bulk begin
/** A node the hat may move the row to: the server's list, filtered to where this hat may move it. */
export type Destination = components["schemas"]["OrganizationOut"];
// golden: bulk end
// golden: move end
// golden: bulk begin
/** The batch's answer: one result per id, in the order the ids were sent. */
export type WidgetBulk = components["schemas"]["WidgetBulkOut"];
// golden: bulk end
// golden: attach begin
/** What attaches to the row, each the owner's own shape: a note, a file, a tag. */
export type Note = components["schemas"]["NoteOut"];
export type StoredFile = components["schemas"]["StoredFileOut"];
export type Tag = components["schemas"]["TagOut"];
// golden: attach end
// golden: merge begin
/** The merge's dry run: what moves to the survivor, per owner, in the owner's words. */
export type WidgetMergePreview = components["schemas"]["WidgetMergePreviewOut"];
// golden: merge end
// golden: history begin
/** One thing that happened to the row, and a page of them, newest first. */
export type HistoryEntry = components["schemas"]["HistoryEntryOut"];
export type HistoryPage = components["schemas"]["PagedHistoryEntryOut"];
// golden: history end

// golden: face begin
/**
 * A date is a day, never a timestamp (patterns.md §8 Words). Formatted in UTC
 * so the server's render and the client's agree.
 */
const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });

export function dayOf(iso: string): string {
    return DAY.format(new Date(iso));
}

/** §16: a state word after a name. Tinted, never filled; one neutral tone. */
export function Pill({ word }: { readonly word: string }) {
    return (
        <span
            data-pill=""
            data-tone="neutral"
            className="widget-pill"
            style={{
                fontSize: "var(--type-label)",
                letterSpacing: "var(--type-label-tracking)",
                fontWeight: 400,
                color: "var(--muted)",
            }}
        >
            {word}
        </span>
    );
}

/** §10: head (a title of four words or fewer), body, and no foot until a card has acts. */
export function Card({ title, busy, children }: { readonly title: string; readonly busy?: boolean; readonly children: ReactNode }) {
    return (
        <section
            aria-label={title}
            aria-busy={busy === true ? "true" : undefined}
            style={{
                background: "var(--surface-raised)",
                border: "1px solid var(--faint)",
                borderRadius: "var(--radius)",
                padding: "var(--space-3)",
            }}
        >
            <h2 style={{ fontSize: "var(--type-section)", margin: "0 0 var(--space-2)", color: "var(--ink)" }}>{title}</h2>
            {children}
        </section>
    );
}

/** A still shape at a line's height, for the `loading` state (§13): never a shimmer. */
export function StillLine({ tall }: { readonly tall?: boolean }) {
    return (
        <div
            style={{
                blockSize: tall === true ? "var(--act-min)" : "var(--type-title)",
                margin: "0 0 var(--space-2)",
                background: "var(--faint)",
                borderRadius: "var(--radius)",
            }}
        />
    );
}
// golden: face end
