// golden: face begin
"use client";
// golden: face end

/**
 * EXAMPLE — the worked Widget list's stories: the four `REQUIRED_STORY_EXPORTS`
 * (`Ready` is the populated case), then the extras the list's declared entries
 * name — §8's `HasMore` and `LongName`; §20's archived cut (`Archived`,
 * `ArchivedLoading`, `NothingArchived`, `RefusedRestore`); the bulk road's
 * selection bar in the control row's seat (§7: `Selected`, `RefusedBulk`) and
 * its band (§17: `BulkPartial`). Fixtures are typed against the generated
 * shape (fe-conventions §6.7), and every refusal is the registry's own, fact
 * and remedies verbatim.
 *
 * EVERY STORY IS PRESSABLE. The walk draws each story through `ListWalk`, a
 * stand-in for the route that answers from the fixtures below after a short
 * wait: the chip re-reads the other cut, *Show more* reads the next page, a
 * cut row's *Restore* takes the row out of the cut, the bar's verbs answer per
 * row. It is the fixtures' server, not the product's, and it lives here,
 * beside the fixtures, and nowhere a route could import it for real.
 */

// golden: face begin
import { createContext, useState } from "react";

import type { Refusal, SurfaceState, WireRefusal } from "@pilecap/ui/state";
import type { Widget, WidgetPage } from "@/screens/widget/parts";
import { type Cut, WidgetList, type WidgetListProps } from "@/screens/widget/widget-list";
// golden: face end
// golden: move begin
// golden: bulk begin
import type { Destination } from "@/screens/widget/parts";
// golden: bulk end
// golden: move end
// golden: bulk begin
import type { Verb } from "@pilecap/ui/verbs";
import type { BulkAnswer } from "@/screens/widget/widget-list";
// golden: bulk end
// golden: bulk+merge begin
import { useContext } from "react";

import { pathFor, STAFF_SURFACE } from "@pilecap/ui/routes";
// golden: bulk+merge end

// golden: face begin
/**
 * How the walk goes to another page: the walk page hands its router down
 * (`app/example/widgets/walk-navigation.tsx`); a unit test hands nothing, and
 * a press that would navigate goes nowhere.
 */
export const walkNavigation = createContext<(href: string) => void>(() => undefined);
// golden: face end

// golden: face begin
const TENANT = "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f00";
const BRANCH = "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21";
const OWNER = "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f30";
// golden: face end
// golden: archive begin
// golden: bulk begin
const ARCHIVER = "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f31";
// golden: bulk end
// golden: archive end
// golden: archive begin
const POLICY = "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f51";
// golden: archive end

// golden: face begin
/** How long the fixtures' server takes to answer, so the busy forms can be seen on the walk. */
export const LATENCY_MS = 600;

/** The server's answer for an administrator of the row's organization, and for a member of it. */
export const ADMIN_ACTS = ["update", "move", "duplicate", "merge", "archive"];
export const MEMBER_ACTS: string[] = [];

function widget(id: string, name: string, notes: string, onboarded: string | null, created: string, updated: string): Widget {
    /** The worked row whole; a noun that serves fewer fields takes the ones it names. */
    const row = {
        id,
        name,
        notes,
        owner_id: OWNER,
        owner_email: "dana@example.com",
        owner_name: null,
        tenant_id: TENANT,
        organization_id: BRANCH,
        organization_slug: "northern-branch",
        organization_name: "Northern branch",
        version: 1790411040000000,
        created_at: created,
        updated_at: updated,
        onboarded_at: onboarded,
        policy_id: null,
        external_ref: "",
        status: "draft",
        allowed_acts: ADMIN_ACTS,
        archived_at: null,
        archived_by: null,
    };
    return row;
}

// golden: face end
// golden: archive begin
// golden: bulk begin
/**
 * A widget as the archive answers it: `archived_at` set, `archived_by` naming
 * the archiver's id and — on the template, whose user has no name column —
 * `name: null`, and `allowed_acts` offering only `restore`.
 */
export function archivedOf(row: Widget, at = "2026-09-27T11:20:00.000Z", name: string | null = null): Widget {
    return { ...row, archived_at: at, archived_by: { id: ARCHIVER, name }, allowed_acts: ["restore"] };
}

/** A widget as the restore answers it: back in the book, both archive fields null, the live acts back. */
export function restoredOf(row: Widget): Widget {
    return { ...row, archived_at: null, archived_by: null, allowed_acts: ADMIN_ACTS };
}

// golden: bulk end
// golden: archive end

// golden: face begin
/** The onboarded widget, with notes: the record's populated case too. */
export const BENCH: Widget = widget(
    "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f41",
    "Bench press #4",
    "Needs the heavy-duty mount.",
    "2026-09-02T10:00:00.000Z",
    "2026-08-23T09:30:00.000Z",
    "2026-09-02T10:00:00.000Z",
);

/** Onboarding (the departure), with notes: the record's populated case. */
export const ROWING: Widget = widget(
    "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f42",
    "Rowing machine",
    "Belt replaced in August.",
    null,
    "2026-08-24T14:05:00.000Z",
    "2026-09-20T08:15:00.000Z",
);

/** Three rows: one onboarded, two onboarding (one with no notes and a long name). */
const WIDGETS: readonly Widget[] = [
    BENCH,
    ROWING,
    widget(
        "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f43",
        "Squat rack with a very long name that has to wrap on a phone",
        "",
        null,
        "2026-09-26T16:45:00.000Z",
        "2026-09-26T16:45:00.000Z",
    ),
];

const PAGE: WidgetPage = { items: [...WIDGETS], has_more: false, next_cursor: null, count: null, allowed_acts: ["create"] };

/** The page after the first: what *Show more* reads. */
export const NEXT_PAGE: WidgetPage = {
    ...PAGE,
    items: [
        widget("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f45", "Cable crossover", "", null, "2026-08-12T09:00:00.000Z", "2026-08-12T09:00:00.000Z"),
        widget(
            "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f46",
            "Leg press",
            "Seat pad on order.",
            "2026-08-20T10:00:00.000Z",
            "2026-08-10T15:30:00.000Z",
            "2026-08-20T10:00:00.000Z",
        ),
    ],
};

// golden: face end

// golden: archive begin
/** Archived, and back when restored. */
const TREADMILL: Widget = archivedOf(
    widget("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f47", "Treadmill", "Motor replaced.", "2026-07-01T10:00:00.000Z", "2026-06-20T08:00:00.000Z", "2026-09-27T11:20:00.000Z"),
);

/** Archived, and held there: it names a policy that is archived too. */
export const SPIN_BIKE: Widget = archivedOf(
    Object.assign(widget("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f48", "Spin bike", "", null, "2026-06-11T12:00:00.000Z", "2026-09-25T17:40:00.000Z"), { policy_id: POLICY }),
    "2026-09-25T17:40:00.000Z",
);

/** The archived cut: two archived widgets, each offering only `restore`. */
export const ARCHIVED_PAGE: WidgetPage = { ...PAGE, items: [TREADMILL, SPIN_BIKE] };

// golden: archive end

// golden: face begin
/** The registry's own refusal: what the door answers a hat that may not list here. */
const FORBIDDEN: WireRefusal = {
    code: "forbidden",
    detail: "You are who you say you are, and this is still not yours to do here. The row exists and you can see it; the action is what was refused.",
    remedies: [
        { label: "Check the role your membership gives you here", destination: "self:membership" },
        { label: "Ask somebody who administers this organization", destination: "header:X-Org" },
    ],
};

// golden: face end

// golden: archive begin
/**
 * What the widget's restore answers when the policy it names is archived:
 * `restore_blocked`, its blocker's label and door verbatim
 * (`apps/example/restore_blockers.py`). The door is the policy's restore, which
 * no page draws, so it renders as its label, unlinked.
 */
export const RESTORE_BLOCKED: WireRefusal = {
    code: "restore_blocked",
    detail: "This cannot be restored until what it depends on is put right.",
    remedies: [{ label: "Restore the policy this widget names first", destination: `route:widget_policy-restore?policy_id=${POLICY}` }],
};

function readCut(cut: Cut): SurfaceState<WidgetPage> {
    return { kind: "ready", data: cut === "archived" ? ARCHIVED_PAGE : PAGE };
}

/** The fixtures' restore: the second archived widget names an archived policy and is held; any other comes back. */
function restoreAnswer(id: string): Refusal | null {
    return id === SPIN_BIKE.id ? { kind: "registry", refusal: RESTORE_BLOCKED } : null;
}
// golden: archive end

// golden: move begin
// golden: bulk begin
/** Where this hat may move a widget: the server's list for `?can=widget.move`, the row's own node first. */
export const DESTINATIONS: readonly Destination[] = [
    { id: BRANCH, name: "Northern branch", slug: "northern-branch", parent_id: TENANT, path: "0001.0001", depth: 2, created_at: "2026-06-01T09:00:00.000Z", updated_at: "2026-06-01T09:00:00.000Z" },
    { id: "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f22", name: "Southern branch", slug: "southern-branch", parent_id: TENANT, path: "0001.0002", depth: 2, created_at: "2026-06-01T09:00:00.000Z", updated_at: "2026-06-01T09:00:00.000Z" },
    { id: "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f23", name: "Eastern depot", slug: "eastern-depot", parent_id: TENANT, path: "0001.0003", depth: 2, created_at: "2026-06-01T09:00:00.000Z", updated_at: "2026-06-01T09:00:00.000Z" },
];
// golden: bulk end
// golden: move end

// golden: bulk begin
/**
 * What one row of a batch answers when the server holds it: the single
 * archive's `archive_blocked`, its blocker's label and door verbatim.
 */
export const HELD: WireRefusal = {
    code: "archive_blocked",
    detail: "This cannot be archived while something still depends on it.",
    remedies: [
        {
            label: "Archive the widgets that name this policy, or give them another, first",
            destination: "route:widget-list?policy=0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f51",
        },
    ],
};

/** The whole batch refused: the hat may not take this verb over these rows at all. */
const BATCH_FORBIDDEN: WireRefusal = {
    code: "forbidden",
    detail: "You are who you say you are, and this is still not yours to do here. The row exists and you can see it; the action is what was refused.",
    remedies: [{ label: "Ask somebody who administers this organization", destination: "header:X-Org" }],
};

/** The widget the fixtures' server holds on an archive: the one with the long name, whose policy is still needed. */
const HELD_ID = "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f43";

/** A batch's answer over `ids`, each held one refused with `HELD`. */
function batch(verb: Verb, ids: readonly string[]): BulkAnswer {
    return {
        verb,
        results: ids.map((id) =>
            verb === "archive" && id === HELD_ID
                ? { id, outcome: "refused" as const, refusal: { kind: "registry" as const, refusal: HELD } }
                : { id, outcome: "done" as const, refusal: null },
        ),
    };
}
// golden: bulk end

// golden: face begin
type WalkProps = {
    readonly initial: SurfaceState<WidgetPage>;
    readonly cut?: Cut;
    // golden: face end
    // golden: archive begin
    readonly refused?: { readonly id: string; readonly refusal: Refusal } | null;
    // golden: archive end
    // golden: bulk begin
    readonly selected?: readonly string[];
    readonly answer?: BulkAnswer | null;
    readonly batchRefused?: WireRefusal;
    // golden: bulk end
    // golden: face begin
};

/** The stand-in route: holds the state of its reads and answers every press from the fixtures. */
function ListWalk(props: WalkProps) {
    const { initial } = props;
    const [cut, setCut] = useState<Cut>(props.cut ?? "live");
    const [state, setState] = useState(initial);
    const [moreBusy, setMoreBusy] = useState(false);
    let press: Partial<WidgetListProps> = {
        more: {
            busy: moreBusy,
            onShowMore: () => {
                setMoreBusy(true);
                setTimeout(() => {
                    setMoreBusy(false);
                    setState((now) =>
                        now.kind === "ready" ? { kind: "ready", data: { ...NEXT_PAGE, items: [...now.data.items, ...NEXT_PAGE.items] } } : now,
                    );
                }, LATENCY_MS);
            },
        },
    };
    // golden: face end
    // golden: archive begin
    const [rowBusy, setRowBusy] = useState<string | null>(null);
    const [refused, setRefused] = useState(props.refused ?? null);
    press = {
        ...press,
        onShow: (next) => {
            setCut(next);
            setRefused(null);
            setState({ kind: "loading" });
            setTimeout(() => setState(readCut(next)), LATENCY_MS);
        },
        restore: {
            busy: rowBusy,
            refused,
            onRestore: (id) => {
                setRowBusy(id);
                setTimeout(() => {
                    setRowBusy(null);
                    const refusal = restoreAnswer(id);
                    if (refusal !== null) {
                        setRefused({ id, refusal });
                        return;
                    }
                    setRefused(null);
                    setState((now) => {
                        if (now.kind !== "ready") return now;
                        const items = now.data.items.filter((row) => row.id !== id);
                        return items.length === 0 ? { kind: "empty" } : { kind: "ready", data: { ...now.data, items } };
                    });
                }, LATENCY_MS);
            },
        },
    };
    // golden: archive end
    // golden: bulk begin
    const [bulkBusy, setBulkBusy] = useState<Verb | null>(null);
    // golden: bulk end
    // golden: bulk+merge begin
    const [pairBusy, setPairBusy] = useState(false);
    const navigate = useContext(walkNavigation);
    // golden: bulk+merge end
    // golden: bulk begin
    const [answer, setAnswer] = useState<BulkAnswer | null>(props.answer ?? null);
    const [gone, setGone] = useState<ReadonlyMap<string, Widget>>(new Map());
    const batchRefused = props.batchRefused;
    /** The page after a batch: the rows it took out of this cut leave, the rows it brought back return, moved rows move. */
    const settle = (out: BulkAnswer, node: Destination | null) => {
        const done = new Set(out.results.filter((item) => item.outcome !== "refused").map((item) => item.id));
        setState((now) => {
            if (now.kind !== "ready") return now;
            const leaving = out.verb === "archive" || out.verb === "restore";
            const kept = now.data.items.filter((row) => !(leaving && done.has(row.id)));
            const back = out.verb === "restore" && cut === "live" ? [...gone.values()].filter((row) => done.has(row.id)).map(restoredOf) : [];
            const items = [...back, ...kept].map((row) =>
                out.verb === "move" && node !== null && done.has(row.id) ? { ...row, organization_id: node.id, organization_name: node.name } : row,
            );
            if (out.verb === "archive") setGone(new Map(now.data.items.filter((row) => done.has(row.id)).map((row) => [row.id, row])));
            return items.length === 0 ? { kind: "empty" } : { kind: "ready", data: { ...now.data, items } };
        });
        setAnswer(out);
    };
    press = {
        ...press,
        bulk: {
            busy: bulkBusy,
            answer,
            ...(props.selected === undefined ? {} : { selected: props.selected }),
            ...(batchRefused === undefined ? {} : { refused: { kind: "registry" as const, refusal: batchRefused } }),
            onBulk: (verb, ids) => {
                setBulkBusy(verb);
                setTimeout(() => {
                    setBulkBusy(null);
                    settle(batch(verb, ids), null);
                }, LATENCY_MS);
            },
            // golden: bulk end
            // golden: bulk+merge begin
            merge: {
                busy: pairBusy,
                // The survivor's record: the dev walk's record page, standing on the arrival,
                // through the router the walk page hands down (none in a unit test).
                onMerged: (into) => navigate(`${pathFor("widget-detail", { id: into.id }, undefined, STAFF_SURFACE) ?? ""}?story=ArrivedAfterMerge`),
                onPick: () => undefined,
                preview: { kind: "ready", data: { loser_id: BENCH.id, into_id: ROWING.id, repoints: [{ title: "Notes", left: 2 }] } },
                onMerge: (loser) => {
                    setPairBusy(true);
                    return new Promise((resolve) =>
                        setTimeout(() => {
                            setPairBusy(false);
                            setState((now) => (now.kind === "ready" ? { kind: "ready", data: { ...now.data, items: now.data.items.filter((row) => row.id !== loser.id) } } : now));
                            resolve(true);
                        }, LATENCY_MS),
                    );
                },
            },
            // golden: bulk+merge end
            // golden: bulk begin
            move: {
                destinations: { kind: "ready", data: DESTINATIONS },
                onMoveMany: (ids, organizationId) => {
                    setBulkBusy("move");
                    return new Promise((resolve) =>
                        setTimeout(() => {
                            setBulkBusy(null);
                            settle(batch("move", ids), DESTINATIONS.find((node) => node.id === organizationId) ?? null);
                            resolve(true);
                        }, LATENCY_MS),
                    );
                },
            },
        },
    };
    // golden: bulk end
    // golden: face begin

    return <WidgetList state={state} cut={cut} {...press} />;
}

function story(initial: SurfaceState<WidgetPage>, cut: Cut = "live") {
    return function Story() {
        return <ListWalk initial={initial} cut={cut} />;
    };
}

export const Loading = story({ kind: "loading" });
// No act: the create face is not built, so the sentence stands alone (§14).
export const Empty = story({ kind: "empty" });
export const Error = story({ kind: "error", refusal: { kind: "registry", refusal: FORBIDDEN } });
export const Ready = story({ kind: "ready", data: PAGE });

/** §8: the page has more, so *Show more* closes the list and reads the next page when pressed. */
export const HasMore = story({
    kind: "ready",
    data: { ...PAGE, has_more: true, next_cursor: "eyJrIjpbIjIwMjYtMDktMjZUMTY6NDU6MDBaIl0sInYiOjF9.p3Qb1w" },
});

/** §8: a 200-character name with no break in it, which must wrap inside the row. */
export const LONG_NAME = "Widget" + "x".repeat(194);
export const LongName = story({
    kind: "ready",
    data: {
        ...PAGE,
        items: [widget("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f44", LONG_NAME, "", null, "2026-09-27T08:00:00.000Z", "2026-09-27T08:00:00.000Z")],
    },
});

// golden: face end

// golden: archive begin
/** §20: the archived cut, the chip pressed; every row's one *Restore* at its trail, no pill. */
export const Archived = story({ kind: "ready", data: ARCHIVED_PAGE }, "archived");

/** §20: the cut being read — the chip pressed over still rows. */
export const ArchivedLoading = story({ kind: "loading" }, "archived");

/** §20: the cut is empty — *Nothing archived.*, no door; pressing the chip again is the way back. */
export const NothingArchived = story({ kind: "empty" }, "archived");

/** §20: `restore_blocked` from a cut row sits directly under that row, the row still drawn and its *Restore* alive. */
export function RefusedRestore() {
    return (
        <ListWalk
            initial={{ kind: "ready", data: ARCHIVED_PAGE }}
            cut="archived"
            refused={{ id: SPIN_BIKE.id, refusal: { kind: "registry", refusal: RESTORE_BLOCKED } }}
        />
    );
}
RefusedRestore.door = "widget-restore";
// golden: archive end

// golden: bulk begin
/**
 * §7: two rows checked — the selection bar in the control row's seat: the
 * count, the verbs both allow (and, at exactly two, *Merge*, which opens the
 * chooser pre-filled with the two, then the one confirm), the ×.
 */
export function Selected() {
    return <ListWalk initial={{ kind: "ready", data: PAGE }} selected={[BENCH.id, ROWING.id]} />;
}

/** §7 · §15: the whole batch refused — one notice under the bar, the selection kept. */
export function RefusedBulk() {
    return <ListWalk initial={{ kind: "ready", data: PAGE }} selected={[BENCH.id, ROWING.id]} batchRefused={BATCH_FORBIDDEN} />;
}
RefusedBulk.door = "widget-bulk";

/**
 * §17: three archived, one held — the band *Archived 2 of 3 widgets.* and its
 * *Restore them*; the held row stays, checked, its refusal under it, and the
 * bar counts only it.
 */
export function BulkPartial() {
    const held = PAGE.items.filter((row) => row.id === HELD_ID);
    return (
        <ListWalk
            initial={{ kind: "ready", data: { ...PAGE, items: held } }}
            answer={batch("archive", PAGE.items.map((row) => row.id))}
        />
    );
}
// A batch's per-row refusal (`BulkRefusalOut`) is the row's own act's answer, never the bulk door's.
BulkPartial.door = "widget-archive";
// golden: bulk end

// golden: import begin
/**
 * §5 · §17: the import road on the list — *Import* at the head (the list
 * offers `create`), a door to the import page, and the band while a run is in
 * flight, its file a link to the page.
 */
export function ImportInFlight() {
    return <WidgetList state={{ kind: "ready", data: PAGE }} imports={{ importing: { fileName: "widgets.csv", rows: 5 } }} />;
}
// golden: import end
