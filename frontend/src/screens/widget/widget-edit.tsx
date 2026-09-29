// golden: version begin
// patterns: §1, §15
"use client";
// golden: version end

/**
 * EXAMPLE — the worked Widget's edit sheet: the Edit road, versioned (the
 * book's Edit road; patterns.md §1, the sheet). A product copies it for
 * its own noun.
 *
 * The sheet holds the `version` it read, and *Save* sends it: a save that lost
 * a race is refused `stale_version`, and the refusal sits one line above the
 * foot with its one act, *Reload*, while *Save* stays alive. *Reload* re-reads
 * the record — first asking, in place, *Discard your changes?* when the form
 * is dirty (*Keep editing* first and focused) — and lands on the first field
 * the re-read changed. There is no field-level merge and no silent
 * last-write-wins.
 *
 * It renders and never fetches: the route saves and re-reads, and hands back
 * the row, the press at work and the last refusal. The sheet is the one
 * dialog primitive's; its foot carries *Save* and nothing else.
 */

// golden: version begin
import { useEffect, useRef, useState } from "react";

import { DIALOG_COPY as D } from "@/copy/dialog";
import { WIDGET_COPY as C, WIDGET_FIELD_WORDS as F } from "@/copy/widget";
import { Dialog } from "@/primitives/dialog";
import { RefusalPanel } from "@/screens/refusal-panel";
import type { Refusal } from "@/screens/state";
import type { Act } from "@/screens/verbs";
import type { Widget, WidgetPatch } from "@/screens/widget/parts";

/** What the route hands the sheet: the save (answering whether it was saved) and the re-read. */
export type EditPress = {
    readonly onSave: (patch: WidgetPatch) => Promise<boolean>;
    readonly onReread: () => void;
};

type Values = { readonly name: string; readonly notes: string };
type Field = keyof Values;

const FIELDS: readonly Field[] = ["name", "notes"];

function valuesOf(widget: Widget): Values {
    return { name: widget.name, notes: widget.notes };
}

/** The Patch body: `version` always (the sheet's read), and only the fields the draft changed. */
function patchOf(read: Widget, draft: Values): WidgetPatch {
    return {
        version: read.version,
        ...(draft.name === read.name ? {} : { name: draft.name }),
        ...(draft.notes === read.notes ? {} : { notes: draft.notes }),
    };
}

/** A `self:reread` remedy is the one refusal a re-read answers: its one act is *Reload*. */
function rereadAnswers(refusal: Refusal | null): boolean {
    return refusal?.kind === "registry" && (refusal.refusal.remedies ?? []).some((remedy) => remedy.destination === "self:reread");
}

export function EditSheet({
    widget,
    save,
    busy,
    refused,
    press,
    onClose,
}: {
    readonly widget: Widget;
    readonly save: Act;
    readonly busy: boolean;
    readonly refused: Refusal | null;
    readonly press: EditPress;
    /** Called when the sheet goes down: `true` after its press was answered, `false` when it was dismissed. */
    readonly onClose: (done: boolean) => void;
}) {
    const [read, setRead] = useState(widget);
    const [draft, setDraft] = useState<Values>(() => valuesOf(widget));
    const [asking, setAsking] = useState<"reload" | "close" | null>(null);
    const [reloading, setReloading] = useState(false);
    const [landing, setLanding] = useState<{ readonly field: Field; readonly n: number }>({ field: "name", n: 0 });
    const nameField = useRef<HTMLInputElement>(null);
    const notesField = useRef<HTMLTextAreaElement>(null);
    const keep = useRef<HTMLButtonElement>(null);
    const dirty = FIELDS.some((field) => draft[field] !== read[field]);

    // A re-read the sheet asked for has landed (the row's version moved): the
    // draft becomes the row, and focus goes to the first field the re-read
    // changed from what the sheet had read. Derived from the new props during
    // render, never copied in by an effect.
    if (reloading && widget.version !== read.version) {
        const changed = FIELDS.find((field) => widget[field] !== read[field]) ?? "name";
        setRead(widget);
        setDraft(valuesOf(widget));
        setReloading(false);
        setLanding({ field: changed, n: landing.n + 1 });
    }

    // Opening lands on the first field; a reload, on the first field it changed.
    useEffect(() => {
        (landing.field === "name" ? nameField : notesField).current?.focus();
    }, [landing]);

    // The dirty ask lands on *Keep editing*.
    useEffect(() => {
        if (asking !== null) keep.current?.focus();
    }, [asking]);

    const reload = () => {
        setAsking(null);
        setReloading(true);
        press.onReread();
    };


    return (
        <Dialog
            open
            title={read.name}
            onDismiss={() => (dirty ? setAsking("close") : onClose(false))}
            foot={
                <button
                    type="button"
                    className="widget-act widget-primary"
                    {...save.attrs}
                    aria-busy={busy ? "true" : undefined}
                    onClick={async () => {
                        if (await press.onSave(patchOf(read, draft))) onClose(true);
                    }}
                >
                    {busy ? save.busy : save.label}
                </button>
            }
        >
            <div className="widget-sheet">
                <label className="widget-field">
                    <span>{F.name}</span>
                    <input type="text" ref={nameField} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
                </label>
                <label className="widget-field">
                    <span>{F.notes}</span>
                    <textarea rows={4} ref={notesField} value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} />
                </label>
                {refused === null ? null : (
                    <div className="widget-refusal-seat">
                        <RefusalPanel refusal={refused} seat="sheet-foot" words={{ label: save.words.refused, remedies: C.remedies }} />
                        {rereadAnswers(refused) && asking === null ? (
                            <button
                                type="button"
                                className="widget-act"
                                data-weight="secondary"
                                onClick={() => (dirty ? setAsking("reload") : reload())}
                            >
                                {C.reloadAct}
                            </button>
                        ) : null}
                    </div>
                )}
                {asking === null ? null : (
                    <div className="widget-ask">
                        <p>{D.discardQuestion}</p>
                        <button type="button" className="widget-act" data-weight="secondary" ref={keep} onClick={() => setAsking(null)}>
                            {D.keepEditingAct}
                        </button>
                        <button
                            type="button"
                            className="widget-act"
                            data-weight="secondary"
                            onClick={() => (asking === "close" ? onClose(false) : reload())}
                        >
                            {D.discardAct}
                        </button>
                    </div>
                )}
            </div>
        </Dialog>
    );
}
// golden: version end
