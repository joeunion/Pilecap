/**
 * THE VERB FACE CENSUS — the noun-verb family's rendered questions, asked of
 * every noun face's stories (patterns.md §6, §7, §8, §20; the design grammar's
 * seats, order, weight and states).
 *
 * THE POPULATION IS DERIVED, NEVER LISTED: every `screens/<noun>/road.ts` in the
 * tree, and every `*.stories.tsx` beside it. A road that declares a verb owes
 * the stories that verb's road draws, and each story is asked the closed
 * questions below. A road declaring no verb owes nothing, and says so.
 *
 * The questions are over the rendered DOM (jsdom), so they read order, count
 * and presence; the box a person presses and where a phone wraps it are the
 * rendered drive's (the mirror pass), and this file does not claim them.
 */

import { cleanup, render } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { remedyDoor } from "@pilecap/ui/remedy-door";
import { pathFor, STAFF_SURFACE } from "@pilecap/ui/routes";
import { VERB_TABLE, type Place, type Road, type Verb } from "@pilecap/ui/verbs";

afterEach(cleanup);

/**
 * jsdom draws a <dialog> but implements neither showModal() nor close(); the
 * family's sheet stories open one as they render, so both are stood in for
 * here, around this file alone.
 */
const DIALOG = HTMLDialogElement.prototype;
const NATIVE = { showModal: DIALOG.showModal, close: DIALOG.close };
beforeAll(() => {
    DIALOG.showModal = function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
    };
    DIALOG.close = function (this: HTMLDialogElement) {
        this.removeAttribute("open");
    };
});
afterAll(() => {
    DIALOG.showModal = NATIVE.showModal;
    DIALOG.close = NATIVE.close;
});

/**
 * Vite's own module census (`import.meta.glob`), typed here because this tree
 * does not name `vite/client`: the runner transforms the literal call, so the
 * population is whatever files exist, read at collection time.
 */
declare global {
    interface ImportMeta {
        glob<T>(pattern: string, options: { readonly eager: true }): Record<string, T>;
    }
}

type StoryModule = Readonly<Record<string, unknown>>;

const ROADS = import.meta.glob<{ ROAD: Road }>("./*/road.ts", { eager: true });
const STORY_MODULES = import.meta.glob<StoryModule>("./*/*.stories.tsx", { eager: true });

/** The story a verb's STATE is drawn in: the face after the verb has happened. */
const STATE_STORY: Readonly<Partial<Record<Verb, string>>> = {
    archive: "Archived",
    restore: "Archived",
    move: "Moved",
    merge: "Merged",
    import: "ImportPreviewed",
    update: "Stale",
};

/**
 * Where a verb's refusal sits: under the act's row, so at the place the act is
 * drawn — for a verb that opens a sheet, one line above the sheet's foot, where
 * its press is (merge's is the confirm's foot); for the History card, inside
 * the card under its head; for attach, inside its card or under the tag row;
 * for import, under the import page's head, where its act sits.
 */
const REFUSAL_PLACES: Readonly<Partial<Record<Verb, readonly Place[]>>> = {
    restore: ["band", "cut-row"],
    update: ["sheet-foot"],
    move: ["sheet-foot"],
    merge: ["sheet-foot"],
    attach: ["card-foot", "tag-row"],
    import: ["list-head"],
    history: ["card-head"],
};

/** The stories a road's bulk verbs owe: the bar in the control row's seat, and a batch some rows were refused in. */
const BULK_STORIES = ["Selected", "BulkPartial"] as const;

const FAMILY = new Set<string>(VERB_TABLE.map((row) => row.verb));

function refusedStory(verb: Verb): string {
    return `Refused${verb.charAt(0).toUpperCase()}${verb.slice(1)}`;
}

function nounOf(path: string): string {
    return path.split("/")[1] ?? "";
}

function storiesOf(noun: string, name: string): [string, ComponentType][] {
    return Object.entries(STORY_MODULES)
        .filter(([path, module]) => nounOf(path) === noun && typeof module[name] === "function")
        .map(([path, module]) => [path, module[name] as ComponentType]);
}

function familyActs(root: ParentNode): Element[] {
    return Array.from(root.querySelectorAll("[data-act]")).filter((el) => FAMILY.has(el.getAttribute("data-act") ?? ""));
}

const roads = Object.entries(ROADS).map(([path, module]) => ({ noun: nounOf(path), road: module.ROAD }));

describe("the census's population", () => {
    it("finds every road in the tree, and every road's noun has stories beside it", () => {
        expect(roads.length).toBeGreaterThan(0);
        for (const { noun } of roads) {
            expect(Object.keys(STORY_MODULES).some((path) => nounOf(path) === noun), noun).toBe(true);
        }
    });
});

describe.each(roads)("the $noun face's road", ({ noun, road }) => {
    // A road owes the stories of what it declares: its single verbs' (the two
    // hats, each verb's refusal and state) and its bulk verbs' (the bar and a
    // batch some rows were refused in). A road declaring neither owes nothing.
    const required = [
        ...(road.verbs.length === 0
            ? []
            : [
                  "PopulatedAdmin",
                  "PopulatedMember",
                  ...road.verbs.map(refusedStory),
                  ...road.verbs.flatMap((verb) => (STATE_STORY[verb] === undefined ? [] : [STATE_STORY[verb]])),
                  ...(road.verbs.includes("history") ? ["History"] : []),
              ]),
        ...((road.bulk ?? []).length === 0 ? [] : BULK_STORIES),
    ];

    it.each([...new Set(required)])("owes the %s story, in one of the noun's story modules", (name) => {
        expect(storiesOf(noun, name).map(([path]) => path), `${noun} owes ${name}`).not.toEqual([]);
    });

    it("the admin story draws the road's acts in its seat, in table order, the leaving act last, all ghost", () => {
        if (road.verbs.length === 0) return;
        const expected = VERB_TABLE.filter((row) => row.places.includes(road.seat) && road.verbs.includes(row.verb)).map((row) => row.verb);
        for (const [path, Story] of storiesOf(noun, "PopulatedAdmin")) {
            const { container, unmount } = render(<Story />);
            if (expected.length === 0) {
                // A road whose verbs sit nowhere in its seat (History is a card, not an act): no seat is drawn.
                expect(container.querySelector(`[data-seat="${road.seat}"]`), path).toBeNull();
                unmount();
                continue;
            }
            const seat = container.querySelector(`[data-seat="${road.seat}"]`);
            expect(seat, path).not.toBeNull();
            const acts = familyActs(seat as Element);
            expect(acts.map((act) => act.getAttribute("data-act")), path).toEqual(expected);
            if (expected.includes("archive")) expect(acts.at(-1)?.getAttribute("data-act"), path).toBe("archive");
            for (const act of acts) {
                expect(act.getAttribute("data-weight"), path).toBe("ghost");
                expect(act.tagName, path).toBe("BUTTON");
            }
            expect(container.querySelectorAll('[data-weight="primary"]').length, path).toBeLessThanOrEqual(1);
            unmount();
        }
    });

    it("the member story renders zero family acts", () => {
        if (road.verbs.length === 0) return;
        for (const [path, Story] of storiesOf(noun, "PopulatedMember")) {
            const { container, unmount } = render(<Story />);
            expect(familyActs(container), path).toEqual([]);
            unmount();
        }
    });

    it.each(road.verbs.filter((verb) => VERB_TABLE.find((row) => row.verb === verb)?.press !== "none"))(
        "the refused story for %s: one alert under the act's row, the verb's refused label first, live doors, the act alive",
        (verb) => {
            const words = VERB_TABLE.find((row) => row.verb === verb);
            const places = REFUSAL_PLACES[verb] ?? [road.seat];
            for (const [path, Story] of storiesOf(noun, refusedStory(verb))) {
                const { container, unmount } = render(<Story />);
                const alerts = container.querySelectorAll('[role="alert"]');
                expect(alerts, path).toHaveLength(1);
                const alert = alerts[0] as HTMLElement;
                expect(places, path).toContain(alert.getAttribute("data-seat"));
                expect(alert.querySelector("p")?.textContent, path).toBe(words?.refused);
                expect(alert.textContent ?? "", path).not.toMatch(/try again/i);
                const doors = Array.from(alert.querySelectorAll("[data-destination]"));
                expect(doors.length, path).toBeGreaterThan(0);
                for (const door of doors) {
                    const answer = remedyDoor({ label: door.textContent ?? "", destination: door.getAttribute("data-destination") ?? "" }, undefined, STAFF_SURFACE);
                    expect(door.tagName, `${path}: ${door.getAttribute("data-destination")}`).toBe(answer.kind === "link" ? "A" : "SPAN");
                    if (answer.kind === "link") expect(door.getAttribute("href")).toBe(answer.href);
                }
                // The pressed act stays drawn and alive (no `disabled` exists in this tree to check).
                expect(container.querySelectorAll(`button[data-act="${verb}"]`).length, path).toBeGreaterThan(0);
                unmount();
            }
        },
    );

    it("the refused story for history: one alert inside the History card, under its head, the card's refused label first", () => {
        if (!road.verbs.includes("history")) return;
        const words = VERB_TABLE.find((row) => row.verb === "history");
        for (const [path, Story] of storiesOf(noun, refusedStory("history"))) {
            const { container, unmount } = render(<Story />);
            const alerts = container.querySelectorAll('[role="alert"]');
            expect(alerts, path).toHaveLength(1);
            const alert = alerts[0] as HTMLElement;
            expect(alert.getAttribute("data-seat"), path).toBe("card-head");
            expect(alert.closest("section")?.querySelector("h2")?.textContent, path).toBe(words?.pressed[0] ?? "History");
            expect(alert.querySelector("p")?.textContent, path).toBe(words?.refused);
            unmount();
        }
    });

    it("the History card is the last card in main, read-only: no family act inside it", () => {
        if (!road.verbs.includes("history")) return;
        for (const [path, Story] of storiesOf(noun, "History")) {
            const { container, unmount } = render(<Story />);
            const cards = Array.from(container.querySelectorAll("main section[aria-label]")).filter((card) => card.closest("aside") === null);
            const last = cards.at(-1);
            expect(last?.getAttribute("aria-label"), path).toBe("History");
            expect(familyActs(last as Element), path).toEqual([]);
            expect(last?.querySelectorAll("li").length, path).toBeGreaterThan(0);
            unmount();
        }
    });

    it("the stale state: the sheet's one primary alive, the lost race above its foot, and a re-read offered beside it", () => {
        if (!road.verbs.includes("update")) return;
        for (const [path, Story] of storiesOf(noun, STATE_STORY.update ?? "Stale")) {
            const { container, unmount } = render(<Story />);
            const sheet = container.querySelector("dialog[open]");
            expect(sheet, path).not.toBeNull();
            const primaries = container.querySelectorAll('[data-weight="primary"]');
            expect(primaries, path).toHaveLength(1);
            expect(primaries[0]?.getAttribute("data-act"), path).toBe("update");
            const alert = sheet?.querySelector('[role="alert"][data-seat="sheet-foot"]');
            expect(alert, path).not.toBeNull();
            expect(alert?.querySelector('[data-destination="self:reread"]'), path).not.toBeNull();
            expect(alert?.parentElement?.querySelectorAll('button[data-weight="secondary"]').length, path).toBe(1);
            unmount();
        }
    });

    it("the merged state: the band naming the survivor — a live door where a page draws the noun's detail — zero primary, no head acts, no pill, no act at all", () => {
        if (!road.verbs.includes("merge")) return;
        // A live door only where the route table has a page drawing the detail; else the name alone, never a broken link.
        const detailPage = pathFor(`${noun}-detail`, { id: "x" }, undefined, STAFF_SURFACE);
        for (const [path, Story] of storiesOf(noun, STATE_STORY.merge ?? "Merged")) {
            const { container, unmount } = render(<Story />);
            const band = container.querySelector('[data-band="merged"]');
            expect(band, path).not.toBeNull();
            if (detailPage === null) expect(band?.querySelector("a"), path).toBeNull();
            else expect(band?.querySelector("a[href]"), path).not.toBeNull();
            expect(container.querySelectorAll('[data-weight="primary"]'), path).toHaveLength(0);
            expect(container.querySelector('[data-seat="record-acts"]'), path).toBeNull();
            expect(container.querySelector('[data-band="archived"]'), path).toBeNull();
            expect(container.querySelectorAll("[data-pill]"), path).toHaveLength(0);
            expect(familyActs(container), path).toEqual([]);
            unmount();
        }
    });

    it("merge is asked twice: the refused story's alert sits inside the confirm, whose head is the question and whose foot holds ONE primary, Merge", () => {
        if (!road.verbs.includes("merge")) return;
        for (const [path, Story] of storiesOf(noun, refusedStory("merge"))) {
            const { container, unmount } = render(<Story />);
            const confirm = container.querySelector("dialog[open]");
            expect(confirm, path).not.toBeNull();
            expect(confirm?.querySelector("h2")?.textContent ?? "", path).toMatch(/\?$/);
            expect(confirm?.querySelector('[role="alert"][data-seat="sheet-foot"]'), path).not.toBeNull();
            const primaries = container.querySelectorAll('[data-weight="primary"]');
            expect(primaries, path).toHaveLength(1);
            expect(primaries[0]?.getAttribute("data-act"), path).toBe("merge");
            expect(primaries[0]?.closest("footer")?.closest("dialog"), path).toBe(confirm);
            unmount();
        }
    });

    it("attach's acts sit only at a card's foot or in the tag row, ghost, never in the road's seat, in every story", () => {
        if (!road.verbs.includes("attach")) return;
        for (const [path, module] of Object.entries(STORY_MODULES).filter(([candidate]) => nounOf(candidate) === noun)) {
            for (const [name, Story] of Object.entries(module)) {
                if (typeof Story !== "function" || !/^[A-Z][a-z]/.test(name)) continue;
                const Component = Story as ComponentType;
                const { container, unmount } = render(<Component />);
                for (const act of Array.from(container.querySelectorAll('[data-act="attach"]'))) {
                    const inCard = act.closest("section[aria-label]") !== null;
                    const inTags = act.closest("[data-tags]") !== null;
                    expect(inCard || inTags, `${path} ${name}`).toBe(true);
                    expect(act.closest(`[data-seat="${road.seat}"]`), `${path} ${name}`).toBeNull();
                    expect(act.getAttribute("data-weight"), `${path} ${name}`).toBe("ghost");
                }
                unmount();
            }
        }
    });

    it("import's preview is its second look: ONE primary, the import act, its label carrying the count it will write", () => {
        if (!road.verbs.includes("import")) return;
        for (const [path, Story] of storiesOf(noun, STATE_STORY.import ?? "ImportPreviewed")) {
            const { container, unmount } = render(<Story />);
            const primaries = container.querySelectorAll('[data-weight="primary"]');
            expect(primaries, path).toHaveLength(1);
            expect(primaries[0]?.getAttribute("data-act"), path).toBe("import");
            expect(primaries[0]?.textContent ?? "", path).toMatch(/\d/);
            expect(container.querySelector("dialog"), path).toBeNull();
            unmount();
        }
    });

    it("the moved-away state: the band, zero primary, no head acts, no pill", () => {
        if (!road.verbs.includes("move")) return;
        for (const [path, Story] of storiesOf(noun, STATE_STORY.move ?? "Moved")) {
            const { container, unmount } = render(<Story />);
            expect(container.querySelector('[data-band="moved"]'), path).not.toBeNull();
            expect(container.querySelectorAll('[data-weight="primary"]'), path).toHaveLength(0);
            expect(container.querySelector('[data-seat="record-acts"]'), path).toBeNull();
            expect(container.querySelectorAll("[data-pill]"), path).toHaveLength(0);
            expect(familyActs(container), path).toEqual([]);
            unmount();
        }
    });

    it("the selection bar takes the control row's seat: the count, the bulk verbs every checked row allows, ghost, in table order", () => {
        const bulk = road.bulk ?? [];
        if (bulk.length === 0) return;
        const order = VERB_TABLE.map((row) => row.verb);
        for (const [path, Story] of storiesOf(noun, "Selected")) {
            const { container, unmount } = render(<Story />);
            const bar = container.querySelector('[data-seat="list-select"]');
            expect(bar, path).not.toBeNull();
            const acts = familyActs(bar as Element);
            expect(acts.length, path).toBeGreaterThan(0);
            const verbs = acts.map((act) => act.getAttribute("data-act") ?? "");
            expect(verbs, path).toEqual([...verbs].sort((a, b) => order.indexOf(a as Verb) - order.indexOf(b as Verb)));
            const checked = container.querySelectorAll('input[type="checkbox"]:checked').length;
            // At exactly two checked rows the road's merge joins the bulk verbs (the pair act, the one confirm's).
            const offered = [...bulk, ...(checked === 2 && road.verbs.includes("merge") ? ["merge"] : [])];
            for (const act of acts) {
                expect(offered, path).toContain(act.getAttribute("data-act"));
                expect(act.getAttribute("data-weight"), path).toBe("ghost");
            }
            expect(bar?.textContent ?? "", path).toContain(String(checked));
            expect(container.querySelectorAll('[data-weight="primary"]').length, path).toBeLessThanOrEqual(1);
            unmount();
        }
    });

    it("the bulk-partial state: the band says n of m, and every refused row stays checked with its refusal under it", () => {
        if ((road.bulk ?? []).length === 0) return;
        for (const [path, Story] of storiesOf(noun, "BulkPartial")) {
            const { container, unmount } = render(<Story />);
            const band = container.querySelector('[data-band="bulk"]');
            expect(band?.textContent ?? "", path).toMatch(/\d+ of \d+/);
            const alerts = Array.from(container.querySelectorAll('[role="alert"][data-seat="list-select"]'));
            expect(alerts.length, path).toBeGreaterThan(0);
            for (const alert of alerts) {
                const row = alert.closest("li");
                expect(row?.querySelector('input[type="checkbox"]:checked'), path).not.toBeNull();
            }
            const checked = container.querySelectorAll('input[type="checkbox"]:checked').length;
            expect(checked, path).toBe(alerts.length);
            expect(container.querySelector('[data-seat="list-select"]')?.textContent ?? "", path).toContain(String(checked));
            expect(container.querySelectorAll('[data-weight="primary"]'), path).toHaveLength(0);
            unmount();
        }
    });

    it("the archived state: zero primary, no head acts, no pill, and the way back drawn", () => {
        if (!road.verbs.includes("archive")) return;
        for (const [path, Story] of storiesOf(noun, "Archived")) {
            const { container, unmount } = render(<Story />);
            expect(container.querySelectorAll('[data-weight="primary"]'), path).toHaveLength(0);
            expect(container.querySelector('[data-seat="record-acts"]'), path).toBeNull();
            expect(container.querySelectorAll("[data-pill]"), path).toHaveLength(0);
            expect(container.querySelectorAll('button[data-act="restore"]').length, path).toBeGreaterThan(0);
            expect(familyActs(container).every((act) => act.getAttribute("data-act") === "restore"), path).toBe(true);
            unmount();
        }
    });

    it("a page that has more draws exactly one Show more, secondary", () => {
        for (const [path, Story] of storiesOf(noun, "HasMore")) {
            const { container, unmount } = render(<Story />);
            const more = container.querySelectorAll('button[data-weight="secondary"]');
            expect(more, path).toHaveLength(1);
            expect(more[0]?.textContent, path).toBe("Show more");
            unmount();
        }
    });

    it("no story draws more than one primary", () => {
        for (const [path, module] of Object.entries(STORY_MODULES).filter(([candidate]) => nounOf(candidate) === noun)) {
            for (const [name, Story] of Object.entries(module)) {
                // A story is a PascalCase component; fixtures are UPPER_CASE, helpers camelCase.
                if (typeof Story !== "function" || !/^[A-Z][a-z]/.test(name)) continue;
                const Component = Story as ComponentType;
                const { container, unmount } = render(<Component />);
                expect(container.querySelectorAll('[data-weight="primary"]').length, `${path} ${name}`).toBeLessThanOrEqual(1);
                unmount();
            }
        }
    });
});
