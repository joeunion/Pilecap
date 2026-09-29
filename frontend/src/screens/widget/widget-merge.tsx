// golden: merge begin
// patterns: §1, §13, §14, §15
"use client";
// golden: merge end

/**
 * EXAMPLE — the worked Widget's merge: two become one, asked twice (the Merge
 * road; patterns.md §1, the sheet and the confirm). A product copies it for
 * its own noun.
 *
 * *Merge* opens the CHOOSER, a sheet titled *Merge ⟨name⟩ into…*: a search
 * field and the rows of the same noun the server allows as survivors (a row
 * whose own answer offers `merge`, never this one). Picking one opens THE
 * CONFIRM — the one dialog primitive, its head the question *Merge ⟨loser⟩
 * into ⟨survivor⟩?*, its body the dry run's answer (what moves to the
 * survivor, in the owners' own words and counts), its foot ONE primary,
 * *Merge*, present once the dry run has answered. A refusal (`merge_blocked`)
 * sits inside the confirm, one line above its foot, *Merge* alive. Escape on
 * the confirm returns to the chooser. It is the one verb no press undoes, so
 * it is the one verb behind a confirm.
 *
 * ONE HONEST ABSENCE: the wire's dry run answers the re-point counts
 * (`repoints: [{title, left}]`) and no sentence, so the body composes one
 * from them; the survivor list is the list read with the search, narrowed to
 * the rows whose own `allowed_acts` offer `merge` — the server's answer per
 * row, read, never computed.
 *
 * It renders and never fetches: the route reads the candidates and the dry
 * run, and merges.
 */

// golden: merge begin
import { useEffect, useRef, useState } from "react";

import { WIDGET_COPY as C, mergeMovesSentence, mergeQuestion, mergeSheetTitle } from "@/copy/widget";
// golden: merge end
// golden: bulk+merge begin
import { mergePairTitle } from "@/copy/widget";
// golden: bulk+merge end
// golden: merge begin
import { Dialog } from "@/primitives/dialog";
import { RefusalPanel } from "@/screens/refusal-panel";
import type { Refusal, SurfaceState } from "@/screens/state";
import { type Act, footAct, type Road } from "@/screens/verbs";
import { StillLine, type Widget, type WidgetMergePreview } from "@/screens/widget/parts";

/** What the route hands the merge: the candidates it read, the dry run for the pick, and the merge. */
export type MergePress = {
    readonly candidates: SurfaceState<readonly Widget[]>;
    /** The chooser opened: the route reads the candidates now, and not before. */
    readonly onOpen?: () => void;
    /** The search changed: the route reads the list narrowed by it. */
    readonly onSearch?: (q: string) => void;
    /** A survivor was picked: the route reads the dry run for the pair. */
    readonly onPick: (into: Widget) => void;
    readonly preview: SurfaceState<WidgetMergePreview> | null;
    /** The merge, with both versions read; answers whether it merged. */
    readonly onMerge: (into: Widget) => Promise<boolean>;
    /** The survivor a refused merge was asked into, when the route opens the confirm again on it. */
    readonly chosen?: Widget | null;
};

export function MergeSheet({
    widget,
    road,
    busy,
    refused,
    press,
    onClose,
}: {
    readonly widget: Widget;
    readonly road: Road;
    readonly busy: boolean;
    readonly refused: Refusal | null;
    readonly press: MergePress;
    /** Called when the sheet goes down: `true` after the merge was answered, `false` when it was dismissed. */
    readonly onClose: (done: boolean) => void;
}) {
    const [into, setInto] = useState<Widget | null>(press.chosen ?? null);
    const merge = footAct({ allowed_acts: widget.allowed_acts ?? [] }, road, "merge");
    if (merge === null) return null;
    if (into === null) {
        return (
            <Chooser
                widget={widget}
                press={press}
                onPick={(survivor) => {
                    press.onPick(survivor);
                    setInto(survivor);
                }}
                onClose={() => onClose(false)}
            />
        );
    }
    return <Confirm widget={widget} into={into} merge={merge} busy={busy} refused={refused} press={press} onBack={() => setInto(null)} onClose={onClose} />;
}

// golden: bulk+merge begin
/** What the list hands the selection bar's Merge: the dry run for the pair as picked, and the merge. */
export type MergePairPress = {
    /** The survivor was picked: the route reads the dry run for (loser, survivor). */
    readonly onPick: (loser: Widget, into: Widget) => void;
    readonly preview: SurfaceState<WidgetMergePreview> | null;
    readonly onMerge: (loser: Widget, into: Widget) => Promise<boolean>;
    /**
     * The merge landed: the face goes to the survivor's record (the route
     * navigates there, and the record lands focus on its name). Without it the
     * list stays, the survivor on it.
     */
    readonly onMerged?: (into: Widget) => void;
};

/**
 * THE SELECTION BAR'S MERGE, at exactly two checked rows: the chooser opens
 * pre-filled with the two — *Merge ⟨a⟩ and ⟨b⟩ into…*, each one press, the
 * one pressed the survivor — and picking opens the SAME confirm, the other
 * row the one that goes. Escape on the confirm returns to the two.
 */
export function MergePairSheet({
    rows,
    road,
    busy,
    refused,
    press,
    onClose,
}: {
    readonly rows: readonly [Widget, Widget];
    readonly road: Road;
    readonly busy: boolean;
    readonly refused: Refusal | null;
    readonly press: MergePairPress;
    readonly onClose: (done: boolean) => void;
}) {
    const [into, setInto] = useState<Widget | null>(null);
    const first = useRef<HTMLButtonElement>(null);
    useEffect(() => {
        if (into === null) first.current?.focus();
    }, [into]);
    const [a, b] = rows;
    if (into === null) {
        return (
            <Dialog open title={mergePairTitle(a.name, b.name)} onDismiss={() => onClose(false)}>
                <ul className="widget-choices">
                    {rows.map((row, index) => (
                        <li key={row.id}>
                            <button
                                type="button"
                                className="widget-pick"
                                ref={index === 0 ? first : undefined}
                                onClick={() => {
                                    press.onPick(row === a ? b : a, row);
                                    setInto(row);
                                }}
                            >
                                {row.name}
                            </button>
                        </li>
                    ))}
                </ul>
            </Dialog>
        );
    }
    const loser = into === a ? b : a;
    const merge = footAct({ allowed_acts: loser.allowed_acts ?? [] }, road, "merge");
    if (merge === null) return null;
    return (
        <Confirm
            widget={loser}
            into={into}
            merge={merge}
            busy={busy}
            refused={refused}
            press={{
                candidates: { kind: "empty" },
                onPick: () => undefined,
                preview: press.preview,
                onMerge: async (survivor) => {
                    const merged = await press.onMerge(loser, survivor);
                    if (merged) press.onMerged?.(survivor);
                    return merged;
                },
            }}
            onBack={() => setInto(null)}
            onClose={onClose}
        />
    );
}
// golden: bulk+merge end

/** The chooser: the search and the survivors, by name; its empty says so. */
function Chooser({
    widget,
    press,
    onPick,
    onClose,
}: {
    readonly widget: Widget;
    readonly press: MergePress;
    readonly onPick: (survivor: Widget) => void;
    readonly onClose: () => void;
}) {
    const title = mergeSheetTitle(widget.name);
    const field = useRef<HTMLInputElement>(null);
    const [q, setQ] = useState("");
    const state = press.candidates;
    // Opening lands on the search, the chooser's first field.
    useEffect(() => {
        field.current?.focus();
    }, []);
    const survivors = state.kind === "ready" ? state.data.filter((row) => row.id !== widget.id && (row.allowed_acts ?? []).includes("merge")) : [];
    return (
        <Dialog open title={title} onDismiss={onClose}>
            <div className="widget-sheet">
                <input
                    ref={field}
                    type="search"
                    className="widget-search"
                    aria-label={title}
                    value={q}
                    onChange={(event) => {
                        setQ(event.target.value);
                        press.onSearch?.(event.target.value);
                    }}
                />
                {state.kind === "loading" ? (
                    <div aria-busy="true" aria-live="polite">
                        <p>{C.loadingList}</p>
                        <StillLine tall />
                        <StillLine tall />
                    </div>
                ) : null}
                {state.kind === "empty" || (state.kind === "ready" && survivors.length === 0) ? <p>{C.mergeNoneMatch}</p> : null}
                {state.kind === "error" ? <RefusalPanel refusal={state.refusal} words={{ label: C.errorLabel, remedies: C.remedies }} /> : null}
                {survivors.length === 0 ? null : (
                    <ul className="widget-choices">
                        {survivors.map((row) => (
                            <li key={row.id}>
                                <button type="button" className="widget-pick" onClick={() => onPick(row)}>
                                    {row.name}
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </Dialog>
    );
}

/** The confirm: the question, the dry run's answer, ONE primary *Merge*; a refusal above the foot. */
function Confirm({
    widget,
    into,
    merge,
    busy,
    refused,
    press,
    onBack,
    onClose,
}: {
    readonly widget: Widget;
    readonly into: Widget;
    readonly merge: Act;
    readonly busy: boolean;
    readonly refused: Refusal | null;
    readonly press: MergePress;
    readonly onBack: () => void;
    readonly onClose: (done: boolean) => void;
}) {
    const preview = press.preview;
    const answered = preview?.kind === "ready";
    return (
        <Dialog
            open
            focusTitle
            title={mergeQuestion(widget.name, into.name)}
            onDismiss={onBack}
            foot={
                !answered ? undefined : (
                    <button
                        type="button"
                        className="widget-act widget-primary"
                        {...merge.attrs}
                        aria-busy={busy ? "true" : undefined}
                        onClick={async () => {
                            if (await press.onMerge(into)) onClose(true);
                        }}
                    >
                        {busy ? merge.busy : merge.label}
                    </button>
                )
            }
        >
            <div className="widget-sheet">
                {preview === null || preview.kind === "loading" ? (
                    <div aria-busy="true" aria-live="polite">
                        <p>{C.loadingMerge}</p>
                        <StillLine />
                    </div>
                ) : null}
                {preview?.kind === "ready" ? <p>{mergeMovesSentence(preview.data.repoints, into.name)}</p> : null}
                {preview?.kind === "empty" ? <p>{mergeMovesSentence([], into.name)}</p> : null}
                {preview?.kind === "error" ? (
                    <RefusalPanel refusal={preview.refusal} words={{ label: merge.words.refused, remedies: C.remedies }} />
                ) : null}
                {refused === null ? null : (
                    <div className="widget-refusal-seat">
                        <RefusalPanel refusal={refused} seat="sheet-foot" words={{ label: merge.words.refused, remedies: C.remedies }} />
                    </div>
                )}
            </div>
        </Dialog>
    );
}
// golden: merge end
