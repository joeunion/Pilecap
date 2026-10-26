// golden: face begin
// patterns: §1, §5, §7, §8, §13, §14, §15, §16, §17, §20
"use client";
// golden: face end

/**
 * EXAMPLE — the worked Widget list: the list page head (patterns.md §5), the
 * control row (§7) and the list and its rows (§8), total over the four states —
 * loading (§13), empty (§14), refused (§15), ready. The archive road (§20)
 * draws the *Archived* chip at the control row's trail, and in the archived cut
 * one quiet *Restore* at each row's trail and no pill. The bulk road draws a
 * checkbox leading every row the family's bulk verbs could take, and while a
 * row is checked the selection bar takes the control row's seat; the batch's
 * answer is a band (§17), honest about each row. A product copies it for its
 * own noun.
 *
 * It renders and never fetches (fe-conventions §4, Law 4): the route hands it
 * a `SurfaceState` and the handlers it can take, so every state renders on
 * demand, without a network. An act with no handler is absent, never dead:
 * the chip needs `onShow`, *Show more* needs `more`, a row's *Restore* needs
 * `restore`, the checkboxes need `bulk`.
 *
 * TWO HONEST ABSENCES, both the book's own rulings: the head draws NO create
 * act and the empty state proposes NO door (a sentence alone, §14), because the
 * create face is not built yet and a door with no face behind it is a dead act;
 * and the head's lede is absent, because it names the scope and the list has no
 * one scope to name when the hat sees several branches. A THIRD, a design gap:
 * no page-level checkbox selects the loaded rows, because its accessible name
 * is not in the book's words yet.
 */

// golden: face begin
import { type ReactNode, useEffect, useRef } from "react";

import type { paths } from "@/api/generated/schema";
import { WIDGET_COPY as C, widgetStateWord } from "@pilecap/copy/widget";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { pathFor, STAFF_SURFACE } from "@pilecap/ui/routes";
import type { Refusal, SurfaceState } from "@pilecap/ui/state";
import { unhandledState } from "@pilecap/ui/state";
import { actsFor, VERB_TABLE } from "@pilecap/ui/verbs";
import { Pill } from "@pilecap/ui/pill";
import { StillLine } from "@pilecap/ui/still-line";
import { dayOf, onboardedOf, type Widget, type WidgetPage } from "@/screens/widget/parts";
import { ROAD } from "@/screens/widget/road";
import "@/screens/widget/widget-face.css";
// golden: face end
// golden: import begin
import { importingSentence } from "@pilecap/copy/widget";
import { importHeadAct } from "@pilecap/ui/verbs";
// golden: import end
// golden: bulk begin
import { type RefObject, useState } from "react";

import { bulkActsFor, footAct, type Verb } from "@pilecap/ui/verbs";

import { bulkSentence, moveManyTitle, selectedSentence, selectRowLabel } from "@pilecap/copy/widget";
import type { Destination, WidgetBulk } from "@/screens/widget/parts";
import { MoveSheet } from "@/screens/widget/widget-move";
// golden: bulk+merge begin
import { pairActsFor } from "@pilecap/ui/verbs";
import { type MergePairPress, MergePairSheet } from "@/screens/widget/widget-merge";
// golden: bulk+merge end
// golden: bulk end

// golden: face begin
/**
 * Which cut of the book the list shows: the wire's `show`, read from the
 * generated client verbatim (fe-conventions §4, Law 3), less `all`, which no
 * face draws. A cut the wire renames or drops stops compiling here.
 */
export type Cut = Exclude<NonNullable<NonNullable<paths["/api/v1/widgets/"]["get"]["parameters"]["query"]>["show"]>, "all">;

/** *Show more*: the route reads the next page (it owns the cursor); `busy` while it does. */
export type ShowMore = { readonly onShowMore: () => void; readonly busy: boolean };
// golden: face end

// golden: archive begin
/** A cut row's *Restore*: the press, the row at work, and the last refusal with the row it answers. */
export type RowRestore = {
    readonly onRestore: (id: string) => void;
    readonly busy?: string | null;
    readonly refused?: { readonly id: string; readonly refusal: Refusal } | null;
};
// golden: archive end

// golden: bulk begin
/**
 * The batch's answer as the face reads it: the wire's one result per id, in
 * the order the ids were sent, each refused item's body mapped to a `Refusal`
 * at the client seam like every other refusal (never parsed here).
 */
export type BulkAnswer = {
    readonly verb: Verb;
    readonly results: readonly {
        readonly id: string;
        readonly outcome: WidgetBulk["results"][number]["outcome"];
        readonly refusal: Refusal | null;
    }[];
};

/**
 * The bulk road: the one press over the checked rows, the verb at work, the
 * batch's last answer (one result per id) and a whole-batch refusal. The bar's
 * *Move* opens the move sheet; its `onMoveMany` is the batch with the node.
 */
export type BulkPress = {
    readonly onBulk: (verb: Verb, ids: readonly string[]) => void;
    readonly busy?: Verb | null;
    readonly answer?: BulkAnswer | null;
    readonly refused?: Refusal | null;
    /** Rows the route hands over checked (a link straight to a selection); the face holds the selection from there. */
    readonly selected?: readonly string[];
    readonly move?: {
        readonly destinations: SurfaceState<readonly Destination[]>;
        readonly onOpen?: () => void;
        readonly onMoveMany: (ids: readonly string[], organizationId: string) => Promise<boolean>;
    };
    // golden: bulk+merge begin
    /** The bar's Merge at exactly two checked rows: the pair's dry run and the merge. Without it, Merge is absent. */
    readonly merge?: MergePairPress & { readonly busy?: boolean; readonly refused?: Refusal | null };
    // golden: bulk+merge end
};
// golden: bulk end

// golden: face begin
export type WidgetListProps = {
    readonly state: SurfaceState<WidgetPage>;
    /** The cut the state was read under; the default cut spells no `show`. */
    readonly cut?: Cut;
    readonly more?: ShowMore;
    /** The socket feed's state word (`useEvents`' `board`), said as the page's `data-board`; absent, the page says none. */
    readonly board?: string;
    // golden: face end
    // golden: archive begin
    /** Presses the *Archived* chip: the route re-reads under the other cut. */
    readonly onShow?: (cut: Cut) => void;
    readonly restore?: RowRestore;
    // golden: archive end
    // golden: bulk begin
    readonly bulk?: BulkPress;
    // golden: bulk end
    // golden: import begin
    /**
     * The import road on the list: *Import* at the head (a door to the import
     * page) where the list's own answer offers `create`, and the band while a
     * run is in flight, polled from the run row by the route.
     */
    readonly imports?: { readonly importing?: { readonly fileName: string; readonly rows: number } | null };
    // golden: import end
    // golden: face begin
};

export function WidgetList(props: WidgetListProps) {
    const { state, cut = "live" } = props;
    const focus = useListLanding(props);
    /** The page's seats, each verb's block filling its own. */
    const seats: { controls: ReactNode; band: ReactNode; head: ReactNode } & { -readonly [K in keyof RowParts]: RowParts[K] } = {
        controls: null,
        lead: () => null,
        trail: () => null,
        band: null,
        head: null,
    };
    // golden: face end
    // golden: archive begin
    seats.controls = <Controls cut={cut} onShow={props.onShow} />;
    seats.trail = (widget, index) =>
        cut === "archived" ? <CutRowRestore widget={widget} restore={props.restore} focus={focus} index={index} /> : null;
    // golden: archive end
    // golden: bulk begin
    const selection = useSelection(props);
    if (selection.bar !== null) seats.controls = selection.bar;
    const trail = seats.trail;
    seats.lead = selection.lead;
    seats.trail = (widget, index) => (
        <>
            {trail(widget, index)}
            {selection.trail(widget)}
        </>
    );
    seats.band = selection.band;
    // golden: bulk end
    // golden: import begin
    const imported = importsHead(props);
    seats.head = imported.act;
    if (imported.band !== null) seats.band = imported.band;
    // golden: import end
    // golden: face begin
    const rows = { lead: seats.lead, trail: seats.trail };
    return (
        // The list is the page's width, not the measure: the measure caps prose, and rows are not prose (§8).
        <main className="widget-page" data-board={props.board}>
            <h1 className="widget-title">{C.title}</h1>
            {seats.head}
            {seats.controls}
            {seats.band}
            {body(state, cut, props.more, rows, focus)}
        </main>
    );
}

type Landing = ReturnType<typeof useListLanding>;
type RowParts = {
    readonly lead: (widget: Widget, index: number) => ReactNode;
    readonly trail: (widget: Widget, index: number) => ReactNode;
};

function body(state: SurfaceState<WidgetPage>, cut: Cut, more: ShowMore | undefined, rows: RowParts, focus: Landing) {
    switch (state.kind) {
        case "loading":
            return (
                <div aria-busy="true" aria-live="polite">
                    <p className="widget-reading">{C.loadingList}</p>
                    {[0, 1, 2].map((row) => (
                        <StillLine key={row} tall />
                    ))}
                </div>
            );
        case "empty":
            // §14: the sentence alone. In the live cut the door would be the
            // create act, and there is no create face; in the archived cut the
            // pressed chip is the way back, so there is nothing to propose.
            return (
                <p ref={focus.emptyLine} tabIndex={-1} className="widget-sentence">
                    {cut === "archived" ? C.nothingArchived : C.empty}
                </p>
            );
        case "error":
            return <ListRefusal refusal={state.refusal} />;
        case "ready": {
            const leads = state.data.items.map((widget, index) => rows.lead(widget, index));
            const classes = ["widget-rows", cut === "archived" ? "widget-cut" : "", leads.some((lead) => lead !== null) ? "widget-selectable" : ""];
            return (
                <>
                    <ul className={classes.filter((name) => name !== "").join(" ")}>
                        {state.data.items.map((widget, index) => (
                            <WidgetRow key={widget.id} widget={widget} cut={cut} focus={focus} index={index} lead={leads[index] ?? null} trail={rows.trail(widget, index)} />
                        ))}
                    </ul>
                    {/* §8: when the page has more and the route can read it, ONE act closes the list; no sentinel after the last row. */}
                    {state.data.has_more && more !== undefined ? (
                        <button
                            type="button"
                            className="widget-more"
                            data-weight="secondary"
                            aria-busy={more.busy ? "true" : undefined}
                            onClick={() => {
                                focus.showingMore(state.data.items.length);
                                more.onShowMore();
                            }}
                        >
                            {more.busy ? C.showingMoreAct : C.showMoreAct}
                        </button>
                    ) : null}
                </>
            );
        }
    }
    return unhandledState(state);
}

/**
 * The focus road on the list — focus lands where the next act is: after *Show more*,
 * focus lands on the first new row; after a cut row's *Restore*, on the nearest
 * remaining act — the next row's *Restore*, else the previous row's, else the
 * empty line. The landing is armed by the press and spent when the rows the
 * press asked for arrive.
 */
function useListLanding({ state, ...props }: WidgetListProps) {
    const landing = useRef<{ readonly kind: "more" | "restore"; readonly index: number; readonly id?: string } | null>(null);
    const rows = useRef(new Map<number, HTMLAnchorElement>());
    const restores = useRef(new Map<number, HTMLButtonElement>());
    const emptyLine = useRef<HTMLParagraphElement>(null);
    const items = state.kind === "ready" ? state.data.items : null;
    let refused: unknown = null;
    // golden: face end
    // golden: archive begin
    refused = props.restore?.refused ?? null;
    // golden: archive end
    // golden: face begin

    useEffect(() => {
        const armed = landing.current;
        if (armed === null) return;
        if (armed.kind === "restore" && state.kind === "empty") {
            landing.current = null;
            emptyLine.current?.focus();
            return;
        }
        if (items === null) return;
        if (armed.kind === "more" && items.length > armed.index) {
            landing.current = null;
            rows.current.get(armed.index)?.focus();
        }
        if (armed.kind === "restore" && !items.some((item) => item.id === armed.id)) {
            // The restored row left the cut: focus lands on the nearest remaining act —
            // the row now at its index (the next one), else the previous row; the empty
            // line takes it when the cut empties.
            landing.current = null;
            (restores.current.get(armed.index) ?? restores.current.get(armed.index - 1))?.focus();
        }
    }, [items, state.kind]);

    // A refusal leaves focus on the pressed act: the landing is forgotten.
    useEffect(() => {
        if (refused !== null) landing.current = null;
    }, [refused]);

    return {
        emptyLine,
        showingMore: (count: number) => {
            landing.current = { kind: "more", index: count };
        },
        restoring: (index: number, id: string) => {
            landing.current = { kind: "restore", index, id };
        },
        row: (index: number) => (el: HTMLAnchorElement | null) => {
            if (el === null) rows.current.delete(index);
            else rows.current.set(index, el);
        },
        restoreButton: (index: number) => (el: HTMLButtonElement | null) => {
            if (el === null) restores.current.delete(index);
            else restores.current.set(index, el);
        },
    };
}

/** One of the noun's own facts on a row: a field of the generated `Widget`, its label, and how its value reads. */
type Column = { readonly field: keyof Widget; readonly label: string; readonly reads: "day" | "word" };

/**
 * The noun's own facts a row shows, in the copy's order. Each key is a field of
 * the generated `Widget` — a column the wire drops stops compiling here.
 */
const COLUMNS: readonly Column[] = Object.entries<Omit<Column, "field">>(C.columns).map(([field, column]) => ({
    field: field as keyof typeof C.columns,
    ...column,
}));

/** A fact as a row says it — its label and its value — or nothing when the row has none. */
function factOf(value: unknown, label: string, reads: Column["reads"]): string {
    if (typeof value !== "string" || value === "") return "";
    return `${label} ${reads === "day" ? dayOf(value) : value}`;
}

/**
 * §8: the whole row is ONE pressable, the door to the record. The name block
 * first; the pill, when the row has departed its resting state, rides the
 * name's last word on a non-breaking space so it never sits alone on a line;
 * then one column per fact (the desk grid and the phone stack are the face
 * stylesheet's). In the archived cut the row wears no pill, and its one quiet
 * *Restore* sits at the trail, beside the door and never inside it. A row the
 * bulk verbs could take is led by its checkbox, beside the door too.
 */
function WidgetRow({
    widget,
    cut,
    focus,
    index,
    lead,
    trail,
}: {
    readonly widget: Widget;
    readonly cut: Cut;
    readonly focus: Landing;
    readonly index: number;
    readonly lead: ReactNode;
    readonly trail: ReactNode;
}) {
    const door = pathFor("widget-detail", { id: widget.id }, undefined, STAFF_SURFACE);
    const onboarded = onboardedOf(widget);
    const state = cut === "archived" || onboarded === undefined ? null : widgetStateWord(onboarded);
    const content = (
        <>
            <span className="widget-name">
                {state === null ? widget.name : <NameWithPill name={widget.name} word={state} />}
            </span>
            {COLUMNS.map(({ field, label, reads }) => (
                <span key={field} className="widget-fact">
                    {factOf(widget[field], label, reads)}
                </span>
            ))}
            <span className="widget-fact">
                {C.addedLabel} {dayOf(widget.created_at)}
            </span>
            <span className="widget-fact">
                {C.changedLabel} {dayOf(widget.updated_at)}
            </span>
        </>
    );
    return (
        <li>
            {lead}
            {door === null ? (
                <div className="widget-row">{content}</div>
            ) : (
                <a href={door} className="widget-row" ref={focus.row(index)}>
                    {content}
                </a>
            )}
            {trail}
        </li>
    );
}
/**
 * §8 · §16: the pill rides the name's last character on a non-breaking space,
 * the two held together (`.widget-pill-join`), so the pill wraps WITH the name
 * and is never alone on a line, and never splits: a name that wraps anywhere
 * (a long unbroken one) still carries its last character to the pill's line.
 */
function NameWithPill({ name, word }: { readonly name: string; readonly word: string }) {
    const characters = Array.from(name);
    const last = characters.pop() ?? "";
    return (
        <>
            {characters.join("")}
            <span className="widget-pill-join">
                {last}
                {"\u00a0"}
                <Pill word={word} className="widget-pill" />
            </span>
        </>
    );
}
// golden: face end

// golden: archive begin
/**
 * §7: the control row. Its one seat today is the cut: the *Archived* chip at
 * the trail, a native button with `aria-pressed`, unpressed in the default cut
 * and pressed under `?show=archived`, its word unchanged by the press. Drawn
 * for every hat that can read the list (a cut is a read), when the route can
 * take the press.
 */
function Controls({ cut, onShow }: { readonly cut: Cut; readonly onShow: ((cut: Cut) => void) | undefined }) {
    if (onShow === undefined) return null;
    const pressed = cut === "archived";
    return (
        <div className="widget-controls">
            <button
                type="button"
                className="widget-chip"
                aria-pressed={pressed ? "true" : "false"}
                onClick={() => onShow(pressed ? "live" : "archived")}
            >
                {C.archivedChipLabel}
            </button>
        </div>
    );
}

/**
 * A cut row's trail: its one quiet *Restore*, from the row's own answer, and
 * the refusal that answers it directly under the row, the row still drawn and
 * its *Restore* alive.
 */
function CutRowRestore({
    widget,
    restore,
    focus,
    index,
}: {
    readonly widget: Widget;
    readonly restore: RowRestore | undefined;
    readonly focus: Landing;
    readonly index: number;
}) {
    const acts = restore === undefined ? [] : actsFor({ allowed_acts: widget.allowed_acts ?? [] }, ROAD, "cut-row");
    const refused = restore?.refused?.id === widget.id ? restore.refused : null;
    const words = VERB_TABLE.find((row) => row.verb === "restore");
    return (
        <>
            {acts.map((act) => (
                <span key={act.verb} className="widget-trail">
                    <button
                        type="button"
                        className="widget-act"
                        ref={focus.restoreButton(index)}
                        {...act.attrs}
                        aria-busy={restore?.busy === widget.id ? "true" : undefined}
                        aria-label={`${act.label} ${widget.name}`}
                        onClick={() => {
                            focus.restoring(index, widget.id);
                            restore?.onRestore(widget.id);
                        }}
                    >
                        {restore?.busy === widget.id ? act.busy : act.label}
                    </button>
                </span>
            ))}
            {refused === null ? null : (
                <div className="widget-refusal-seat">
                    <RefusalPanel surface={STAFF_SURFACE} refusal={refused.refusal} seat="cut-row" refused={words?.refused} />
                </div>
            )}
        </>
    );
}
// golden: archive end

// golden: bulk begin
/**
 * THE BULK ROAD (patterns.md §7, §8, §17). The selection is the loaded rows
 * the face checked; it clears on a new cut or read. While a row is checked the
 * selection bar takes the control row's seat: *⟨n⟩ selected*, the bulk verbs
 * EVERY checked row allows (in table order, ghost), the × *Clear the
 * selection* at its trail. One press; the answer is per row: the band says
 * *Archived ⟨n⟩ widgets.* or *Archived ⟨n⟩ of ⟨m⟩ widgets.* with its one way
 * back, each refused row stays checked and carries its refusal under it, and
 * the bar now counts only them. Focus lands on the band's act, or on the first
 * refused row's checkbox.
 */
function useSelection(props: WidgetListProps) {
    const { bulk, state } = props;
    const rows = state.kind === "ready" ? state.data.items : [];
    const [checked, setChecked] = useState<ReadonlySet<string>>(() => new Set(bulk?.selected ?? []));
    const [sheet, setSheet] = useState(false);
    const [origins, setOrigins] = useState<ReadonlyMap<string, string>>(new Map());
    const [seen, setSeen] = useState<BulkAnswer | null>(null);
    const boxes = useRef(new Map<string, HTMLInputElement>());
    const wayBack = useRef<HTMLButtonElement>(null);
    const landing = useRef(false);
    const answer = bulk?.answer ?? null;

    // A new answer: the refused rows are the selection now (derived when it
    // lands, during render — never copied in by an effect).
    if (answer !== seen) {
        setSeen(answer);
        if (answer !== null) setChecked(new Set(answer.results.filter((item) => item.outcome === "refused").map((item) => item.id)));
    }

    // …and focus goes to the band's act, else to the first refused row's checkbox.
    useEffect(() => {
        if (!landing.current || answer === null) return;
        landing.current = false;
        const refusedFirst = answer.results.find((item) => item.outcome === "refused");
        if (wayBack.current !== null) wayBack.current.focus();
        else if (refusedFirst !== undefined) boxes.current.get(refusedFirst.id)?.focus();
    }, [answer]);

    const chosen = rows.filter((row) => checked.has(row.id));
    // The bar's seats, held in one object so a copy without merge (which fills two of them) binds nothing it never reassigns.
    const seated: { acts: ReturnType<typeof bulkActsFor>; pairSheet: ReactNode; openPair: () => void } = {
        acts: bulk === undefined ? [] : bulkActsFor(chosen.map((row) => ({ allowed_acts: row.allowed_acts ?? [] })), ROAD).filter((act) => act.verb !== "move" || bulk.move !== undefined),
        pairSheet: null,
        openPair: () => undefined,
    };
    // golden: bulk end
    // golden: bulk+merge begin
    // Merge joins the bar at EXACTLY two checked rows that both allow it, in table order among the bulk verbs.
    const [pairing, setPairing] = useState(false);
    const pair = bulk?.merge === undefined ? [] : pairActsFor(chosen.map((row) => ({ allowed_acts: row.allowed_acts ?? [] })), ROAD);
    const order = VERB_TABLE.map((row) => row.verb);
    seated.acts = [...seated.acts, ...pair].sort((x, y) => order.indexOf(x.verb) - order.indexOf(y.verb));
    seated.openPair = () => setPairing(true);
    const [one, two] = chosen;
    seated.pairSheet =
        pairing && bulk?.merge !== undefined && one !== undefined && two !== undefined && chosen.length === 2 ? (
            <MergePairSheet
                rows={[one, two]}
                road={ROAD}
                busy={bulk.merge.busy === true}
                refused={bulk.merge.refused ?? null}
                press={bulk.merge}
                onClose={(done) => {
                    setPairing(false);
                    if (done) setChecked(new Set());
                }}
            />
        ) : null;
    // golden: bulk+merge end
    // golden: bulk begin
    const press = (verb: Verb, ids: readonly string[]) => {
        landing.current = true;
        setOrigins(new Map(rows.filter((row) => ids.includes(row.id)).map((row) => [row.id, row.organization_id])));
        bulk?.onBulk(verb, ids);
    };
    /**
     * A batch that moves rows (the bar's *Move*, or the band's *Move them
     * back*): where the rows are NOW is what the next way back returns them
     * to, and the answer lands on the band's act — recorded at the press,
     * whichever act made it, so the band after an undo is the undo's.
     */
    const moving = (ids: readonly string[]) => {
        landing.current = true;
        setOrigins(new Map(rows.filter((row) => ids.includes(row.id)).map((row) => [row.id, row.organization_id])));
    };
    const moveBack = (ids: readonly string[], organizationId: string) => {
        moving(ids);
        void bulk?.move?.onMoveMany(ids, organizationId);
    };
    const toggle = (id: string) => {
        const next = new Set(checked);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setChecked(next);
    };

    const bar =
        bulk === undefined || chosen.length === 0 ? null : (
            <>
                <div data-seat="list-select" className="widget-select">
                    <span className="widget-count">{selectedSentence(chosen.length)}</span>
                    {seated.acts.map((act) => (
                        <button
                            key={act.verb}
                            type="button"
                            className="widget-act"
                            {...act.attrs}
                            aria-busy={bulk.busy === act.verb ? "true" : undefined}
                            onClick={() => {
                                if (act.verb === "move") {
                                    bulk.move?.onOpen?.();
                                    setSheet(true);
                                    return;
                                }
                                if (act.words.press === "confirm") return seated.openPair();
                                press(act.verb, chosen.map((row) => row.id));
                            }}
                        >
                            {bulk.busy === act.verb && act.words.foot === null ? act.busy : act.label}
                        </button>
                    ))}
                    <button type="button" className="widget-act widget-clear" aria-label={C.clearSelectionLabel} onClick={() => setChecked(new Set())}>
                        ×
                    </button>
                </div>
                {bulk.refused === null || bulk.refused === undefined ? null : (
                    <div className="widget-refusal-seat">
                        <RefusalPanel surface={STAFF_SURFACE} refusal={bulk.refused} seat="list-select" />
                    </div>
                )}
                {seated.pairSheet}
                {sheet && bulk.move !== undefined ? (
                    <BulkMoveSheet
                        rows={chosen}
                        bulk={bulk}
                        move={bulk.move}
                        onMoved={moving}
                        onClose={() => setSheet(false)}
                    />
                ) : null}
            </>
        );

    const band = answer === null ? null : <BulkBand answer={answer} origins={origins} wayBack={wayBack} press={press} moveBack={bulk?.move === undefined ? null : moveBack} />;

    return {
        bar,
        band,
        lead: (widget: Widget) => {
            const allowed = widget.allowed_acts ?? [];
            if (bulk === undefined || !(ROAD.bulk ?? []).some((verb) => allowed.includes(verb))) return null;
            return (
                <label className="widget-check">
                    <input
                        type="checkbox"
                        ref={(el) => {
                            if (el === null) boxes.current.delete(widget.id);
                            else boxes.current.set(widget.id, el);
                        }}
                        checked={checked.has(widget.id)}
                        aria-label={selectRowLabel(widget.name)}
                        onChange={() => toggle(widget.id)}
                    />
                </label>
            );
        },
        trail: (widget: Widget) => {
            const item = answer?.results.find((result) => result.id === widget.id && result.outcome === "refused");
            const refusal = item?.refusal ?? null;
            if (refusal === null) return null;
            const words = VERB_TABLE.find((row) => row.verb === answer?.verb);
            return (
                <div className="widget-refusal-seat">
                    <RefusalPanel
                        surface={STAFF_SURFACE}
                        refusal={refusal}
                        seat="list-select"
                        refused={words?.refused}
                    />
                </div>
            );
        },
    };
}

/** The bar's *Move*: the move sheet over the checked rows, *Move* in its foot, the batch with the node. */
function BulkMoveSheet({
    rows,
    bulk,
    move,
    onMoved,
    onClose,
}: {
    readonly rows: readonly Widget[];
    readonly bulk: BulkPress;
    readonly move: NonNullable<BulkPress["move"]>;
    readonly onMoved: (ids: readonly string[]) => void;
    readonly onClose: () => void;
}) {
    const act = footAct({ allowed_acts: rows.every((row) => (row.allowed_acts ?? []).includes("move")) ? ["move"] : [] }, ROAD, "move");
    if (act === null) return null;
    const ids = rows.map((row) => row.id);
    return (
        <MoveSheet
            title={moveManyTitle(rows.length)}
            currentId={null}
            move={act}
            busy={bulk.busy === "move"}
            refused={null}
            press={{
                destinations: move.destinations,
                onMove: async (organizationId) => {
                    onMoved(ids);
                    return move.onMoveMany(ids, organizationId);
                },
            }}
            onClose={onClose}
        />
    );
}

/**
 * §17: the batch's band, under the bar — the verb's state word and the count,
 * *n of m* when some were refused — and its one act, the way back over the
 * rows that were done: *Restore them* after an archive, *Move them back* after
 * a move whose rows all came from one node. A restore's band is the rows'
 * return, and needs no sentence (the verb table gives it no state word).
 */
function BulkBand({
    answer,
    origins,
    wayBack,
    press,
    moveBack,
}: {
    readonly answer: BulkAnswer;
    readonly origins: ReadonlyMap<string, string>;
    readonly wayBack: RefObject<HTMLButtonElement | null>;
    readonly press: (verb: Verb, ids: readonly string[]) => void;
    /** The move back, through the face — so its band and its next way back are the undo's. */
    readonly moveBack: ((ids: readonly string[], organizationId: string) => void) | null;
}) {
    const state = VERB_TABLE.find((row) => row.verb === answer.verb)?.state ?? null;
    if (state === null) return null;
    const done = answer.results.filter((item) => item.outcome !== "refused").map((item) => item.id);
    const from = new Set(done.map((id) => origins.get(id)));
    const [origin] = from;
    let back: { readonly word: string; readonly take: () => void } | null = null;
    if (answer.verb === "archive" && done.length > 0) back = { word: C.restoreThemAct, take: () => press("restore", done) };
    if (answer.verb === "move" && done.length > 0 && from.size === 1 && origin !== undefined && moveBack !== null) {
        back = { word: C.moveThemBackAct, take: () => moveBack(done, origin) };
    }
    return (
        <div data-band="bulk" className="widget-band">
            <p>{bulkSentence(state, done.length, answer.results.length)}</p>
            {back === null ? null : (
                <button type="button" className="widget-act" data-weight="ghost" ref={wayBack} onClick={back.take}>
                    {back.word}
                </button>
            )}
        </div>
    );
}
// golden: bulk end

// golden: import begin
/**
 * §5: the list head's *Import*, ghost, a door to the import page (`list-head`),
 * and §17: the band while a run is in flight — *Importing ⟨file⟩: ⟨n⟩ rows.*,
 * the file a link to the page.
 */
function importsHead(props: WidgetListProps): { readonly act: ReactNode; readonly band: ReactNode } {
    const listActs = props.state.kind === "ready" ? (props.state.data.allowed_acts ?? []) : [];
    const page = pathFor("djb_import-detail", {}, undefined, STAFF_SURFACE);
    const act = props.imports === undefined || page === null ? null : importHeadAct(ROAD, listActs);
    const run = props.imports?.importing ?? null;
    return {
        act:
            act === null || page === null ? null : (
                <div data-seat="list-head" className="widget-acts widget-list-head">
                    <a href={page} className="widget-act widget-door" {...act.attrs}>
                        {act.label}
                    </a>
                </div>
            ),
        band:
            run === null || page === null ? null : (
                <div data-band="importing" className="widget-band">
                    <p>
                        <a href={page}>{importingSentence(run.fileName, run.rows)}</a>
                    </p>
                </div>
            ),
    };
}
// golden: import end

// golden: face begin
function ListRefusal({ refusal }: { readonly refusal: Refusal }) {
    return (
        <RefusalPanel
            surface={STAFF_SURFACE}
            refusal={refusal}
        />
    );
}
// golden: face end
