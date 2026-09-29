// golden: move begin
// golden: bulk begin
// patterns: §1, §13, §14, §15
"use client";
// golden: bulk end
// golden: move end

/**
 * EXAMPLE — the worked Widget's move sheet: the Move road (the design
 * book's Move road; patterns.md §1, the sheet). A product copies it for its own
 * noun. The selection bar's *Move* opens the same sheet over the checked rows.
 *
 * The sheet asks one question per axis the noun's move door accepts: the node
 * (the destinations the server lists for this hat, shown by name, the current
 * one marked). Its foot holds one primary, *Move*; after the answer the sheet
 * closes. A move the server refuses (`move_blocked`) sits one line above the
 * foot, the sheet open and *Move* alive. A sheet that collects an argument is
 * not a confirm: *Move* in its foot is the one press.
 *
 * ONE HONEST ABSENCE: the door also takes an owner, and the sheet does not ask
 * for one — the template's user has no name to show a reader, and a chooser of
 * addresses is a machine token on a face. A product whose people have names
 * adds the second question here.
 *
 * It renders and never fetches: the route reads the destinations
 * (`GET /organizations/?can=<noun>.move`, never a per-noun read) and moves.
 */

// golden: move begin
// golden: bulk begin
import { useEffect, useId, useRef, useState } from "react";

import { WIDGET_COPY as C } from "@/copy/widget";
import { Dialog } from "@/primitives/dialog";
import { RefusalPanel } from "@/screens/refusal-panel";
import type { Refusal, SurfaceState } from "@/screens/state";
import type { Act } from "@/screens/verbs";
import { type Destination, StillLine } from "@/screens/widget/parts";

/** What the route hands the sheet: the destinations it read, and the move (answering whether it moved). */
export type MovePress = {
    readonly destinations: SurfaceState<readonly Destination[]>;
    readonly onMove: (organizationId: string) => Promise<boolean>;
    /** The sheet opened: the route reads the destinations now, and not before. */
    readonly onOpen?: () => void;
    /** The node a refused move was sent to, when the route opens the sheet again on it. */
    readonly chosen?: string | null;
};

export function MoveSheet({
    title,
    currentId,
    move,
    busy,
    refused,
    press,
    onClose,
}: {
    readonly title: string;
    /** The node the row sits at now (one row), or `null` over a selection. */
    readonly currentId: string | null;
    readonly move: Act;
    readonly busy: boolean;
    readonly refused: Refusal | null;
    readonly press: MovePress;
    /** Called when the sheet goes down: `true` after its press was answered, `false` when it was dismissed. */
    readonly onClose: (done: boolean) => void;
}) {
    // THE CURRENT NODE IS MARKED, NEVER CHOSEN: a move to where the row already
    // is moves nothing, so the current node is drawn marked and offers no
    // radio, the sheet opens with no choice, and its foot's *Move* is drawn
    // only once another node is chosen — absent, never dead, and never a press
    // that sends the current node.
    const [chosen, setChosen] = useState<string | null>(press.chosen ?? null);
    const moving = chosen !== null && chosen !== currentId ? chosen : null;
    const first = useRef<HTMLInputElement>(null);
    const name = useId();
    const state = press.destinations;
    const firstChoice = state.kind === "ready" ? (state.data.find((node) => node.id !== currentId)?.id ?? null) : null;

    // Opening lands on the first chooser, once the destinations are read.
    const ready = state.kind === "ready";
    useEffect(() => {
        if (ready) first.current?.focus();
    }, [ready]);

    return (
        <Dialog
            open
            title={title}
            onDismiss={() => onClose(false)}
            foot={
                moving === null ? undefined : (
                    <button
                        type="button"
                        className="widget-act widget-primary"
                        {...move.attrs}
                        aria-busy={busy ? "true" : undefined}
                        onClick={async () => {
                            if (await press.onMove(moving)) onClose(true);
                        }}
                    >
                        {busy ? move.busy : move.label}
                    </button>
                )
            }
        >
            <div className="widget-sheet">
                {state.kind === "loading" ? (
                    <div aria-busy="true" aria-live="polite">
                        <p>{C.loadingDestinations}</p>
                        <StillLine tall />
                        <StillLine tall />
                    </div>
                ) : null}
                {state.kind === "empty" ? <p>{C.moveNowhere}</p> : null}
                {state.kind === "error" ? (
                    <RefusalPanel refusal={state.refusal} words={{ label: move.words.refused, remedies: C.remedies }} />
                ) : null}
                {state.kind === "ready" ? (
                    <fieldset className="widget-choices" aria-label={title}>
                        {state.data.map((node) =>
                            node.id === currentId ? (
                                // The current node is marked and never a choice: it is where the
                                // row is, so it carries no radio, only the mark (the face
                                // stylesheet's) and `aria-current` for a reader that cannot see it.
                                <p key={node.id} className="widget-choice widget-current" aria-current="true">
                                    {node.name}
                                </p>
                            ) : (
                                <label key={node.id} className="widget-choice">
                                    <input
                                        type="radio"
                                        name={name}
                                        ref={node.id === firstChoice ? first : undefined}
                                        checked={chosen === node.id}
                                        onChange={() => setChosen(node.id)}
                                    />
                                    <span>{node.name}</span>
                                </label>
                            ),
                        )}
                    </fieldset>
                ) : null}
                {refused === null ? null : (
                    <div className="widget-refusal-seat">
                        <RefusalPanel refusal={refused} seat="sheet-foot" words={{ label: move.words.refused, remedies: C.remedies }} />
                    </div>
                )}
            </div>
        </Dialog>
    );
}
// golden: bulk end
// golden: move end
