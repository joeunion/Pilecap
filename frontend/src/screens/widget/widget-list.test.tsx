import { act, fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { useState } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, expectTypeOf, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { WIDGET_COPY as C } from "@pilecap/copy/widget";
import { REQUIRED_STORY_EXPORTS } from "@pilecap/ui/state";
import { type BulkAnswer, type Cut, WidgetList } from "@/screens/widget/widget-list";
import * as stories from "@/screens/widget/widget-list.stories";
import {
    ARCHIVED_PAGE,
    Archived,
    ArchivedLoading,
    BENCH,
    ImportInFlight,
    Empty,
    Error as Refused,
    HasMore,
    LATENCY_MS,
    Loading,
    LONG_NAME,
    LongName,
    BulkPartial,
    NothingArchived,
    Ready,
    RefusedBulk,
    RefusedRestore,
    ROWING,
    Selected,
    SPIN_BIKE,
    DESTINATIONS as MOVE_DESTINATIONS,
} from "@/screens/widget/widget-list.stories";

/** Two rows on the Northern branch, for the move-back walk. */
const PAGE_FOR_MOVE = [BENCH, ROWING];
const PAGE_FOR_MOVE_ENVELOPE = { items: PAGE_FOR_MOVE, has_more: false, next_cursor: null, count: null, allowed_acts: ["create"] };

afterEach(() => {
    vi.useRealTimers();
});

const STORIES = { Loading, Empty, Error: Refused, Ready } as const;
// The fe leg and the builder both run vitest from `frontend/` (its config root).
const FACE_CSS = readFileSync(resolve(process.cwd(), "src/screens/widget/widget-face.css"), "utf8");

/** Words the wire speaks that must never reach a reader: a slug, an email, an id. */
const MACHINE = [/northern-branch/, /@example\.com/, /[0-9a-f]{8}-[0-9a-f]{4}-/, /undefined/];

describe("the worked widget list: every authored state renders", () => {
    it("exports the four required stories and the extras its entries name: §8's two, §20's four, §7's two, §17's one", () => {
        // UPPER_CASE exports are fixtures and camelCase ones helpers, not stories.
        const exported = Object.keys(stories).filter((name) => /^[A-Z][a-z]/.test(name));
        expect(exported.sort()).toEqual(
            [
                ...REQUIRED_STORY_EXPORTS,
                "HasMore",
                "LongName",
                "Archived",
                "ArchivedLoading",
                "NothingArchived",
                "RefusedRestore",
                "Selected",
                "RefusedBulk",
                "BulkPartial",
                "ImportInFlight",
            ].sort(),
        );
    });

    it.each([...REQUIRED_STORY_EXPORTS])("%s draws the head: the noun's plural, no act in it, and the control row's one chip, unpressed", (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(C.title);
        const buttons = screen.queryAllByRole("button");
        expect(buttons.map((button) => [button.textContent, button.getAttribute("aria-pressed")])).toEqual([["Archived", "false"]]);
        expect(container.querySelector("h1")?.nextElementSibling?.className).toBe("widget-controls");
    });

    it.each([...REQUIRED_STORY_EXPORTS])("%s puts no machine token in front of a reader", (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        for (const token of MACHINE) expect(container.textContent ?? "").not.toMatch(token);
    });

    it("loading is still rows under aria-busy, with one line naming what is read", () => {
        const { container } = render(<Loading />);
        const busy = container.querySelector('[aria-busy="true"]');
        expect(busy).not.toBeNull();
        expect(busy?.textContent).toBe(C.loadingList);
    });

    it("empty is the sentence alone: no door, and no act beside the control row's chip", () => {
        const { container } = render(<Empty />);
        expect(screen.getByText(C.empty)).toBeDefined();
        expect(screen.queryByRole("link")).toBeNull();
        expect(container.querySelectorAll("main > p, main > p a, main > p button")).toHaveLength(1);
        expect(container.querySelectorAll("button")).toHaveLength(1);
    });

    it("refused renders the server's fact and remedies in the one notice", () => {
        render(<Refused />);
        const alert = screen.getByRole("alert");
        expect(within(alert).getByText(/this is still not yours to do here/)).toBeDefined();
        expect(within(alert).getByText("Check the role your membership gives you here")).toBeDefined();
    });
});

describe("the populated list (the Ready story)", () => {
    it("draws one row per widget, each ONE link to its record from the route table", () => {
        const { container } = render(<Ready />);
        const rows = container.querySelectorAll("ul > li");
        expect(rows).toHaveLength(3);
        for (const row of rows) {
            const links = row.querySelectorAll("a");
            expect(links).toHaveLength(1);
            expect(links[0]?.getAttribute("href")).toMatch(/^\/example\/widgets\/[0-9a-f-]{36}$/);
        }
        expect(container.querySelector(`a[href="/example/widgets/${BENCH.id}"]`)?.textContent).toContain(BENCH.name);
    });

    it("puts the name block first, then the facts as days; a row at rest wears no pill", () => {
        const { container } = render(<Ready />);
        const [first, second] = Array.from(container.querySelectorAll("ul > li a"));
        expect(first?.textContent).toBe("Bench press #4" + "Status draft" + "Added 23 August 2026" + "Last changed 2 September 2026");
        expect(first?.querySelectorAll("[data-pill]")).toHaveLength(0);
        expect(second?.textContent).toBe("Rowing machine\u00a0Onboarding" + "Status draft" + "Added 24 August 2026" + "Last changed 20 September 2026");
    });

    it("the pill is the departure: only onboarding rows wear it, one neutral word each", () => {
        const { container } = render(<Ready />);
        const words = Array.from(container.querySelectorAll('[data-pill][data-tone="neutral"]'), (pill) => pill.textContent);
        expect(words).toEqual(["Onboarding", "Onboarding"]);
    });

    it("the pill rides the name's last character on a non-breaking space, the two held together inside the name block", () => {
        const { container } = render(<Ready />);
        const pill = container.querySelectorAll("[data-pill]")[0];
        const join = pill?.parentElement;
        expect(join?.className).toBe("widget-pill-join");
        expect(join?.parentElement?.className).toBe("widget-name");
        expect(join?.textContent).toBe("e\u00a0Onboarding");
        expect(join?.parentElement?.textContent).toBe("Rowing machine\u00a0Onboarding");
        expect(FACE_CSS).toMatch(/\.widget-pill,\n\.widget-pill-join \{[^}]*white-space: nowrap;/);
    });

    it("each row is the face's grid row, and the list is not capped at the measure", () => {
        const { container } = render(<Ready />);
        // The walk takes the bulk road, so every row the bulk verbs could take is led by its checkbox.
        expect(container.querySelector("ul")?.className).toBe("widget-rows widget-selectable");
        for (const row of container.querySelectorAll("ul > li > a")) expect(row.className).toBe("widget-row");
        expect((container.querySelector("main") as HTMLElement).style.maxWidth).toBe("");
    });
});

describe("a page that has more (the HasMore story)", () => {
    it("closes the list with ONE act, Show more, a native secondary button at the act floor", () => {
        const { container } = render(<HasMore />);
        const more = container.querySelectorAll('button[data-weight="secondary"]');
        expect(more).toHaveLength(1);
        const act = more[0] as HTMLButtonElement;
        expect(act.textContent).toBe(C.showMoreAct);
        expect(act.getAttribute("type")).toBe("button");
        expect(act.className).toBe("widget-more");
        // Not the user agent's own button: the face sheet paints it on the tokens alone.
        expect(FACE_CSS).toMatch(/\.widget-more \{[^}]*min-block-size: var\(--act-min\);[^}]*background: transparent;/);
        expect(FACE_CSS).toMatch(/\.widget-more:focus-visible \{[^}]*var\(--focus-ring\)/);
        // No sentinel: the act is the list's last word, directly after the rows.
        expect(container.querySelector("ul")?.nextElementSibling).toBe(act);
        expect(act.nextElementSibling).toBeNull();
    });

    it("draws no Show more when the page has no more", () => {
        render(<Ready />);
        expect(screen.queryByText(C.showMoreAct)).toBeNull();
    });

    it("draws no Show more when no handler can read the next page: absent, never a dead act", () => {
        const page = { items: [BENCH], has_more: true, next_cursor: "eyJrIjpbXX0.p3Qb1w", count: null };
        const { container } = render(<WidgetList state={{ kind: "ready", data: page }} />);
        expect(container.querySelectorAll("button")).toHaveLength(0);
    });

    it("pressed: Showing more… on the same button, alive; then the next page's rows under the last row", () => {
        vi.useFakeTimers();
        const { container } = render(<HasMore />);
        const act0 = container.querySelector('button[data-weight="secondary"]') as HTMLButtonElement;
        fireEvent.click(act0);
        expect(act0.textContent).toBe("Showing more…");
        expect(act0.getAttribute("aria-busy")).toBe("true");
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(container.querySelectorAll("ul > li")).toHaveLength(5);
        expect(container.querySelector('button[data-weight="secondary"]')).toBeNull();
    });
});

describe("the archive road on the list (§7, §20)", () => {
    it("the chip presses the cut: still rows under the pressed chip, then the archived rows", () => {
        vi.useFakeTimers();
        const { container } = render(<Ready />);
        const chip = screen.getByRole("button", { name: "Archived" });
        fireEvent.click(chip);
        expect(chip.getAttribute("aria-pressed")).toBe("true");
        expect(chip.textContent).toBe("Archived");
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(Array.from(container.querySelectorAll("ul > li .widget-name"), (el) => el.textContent)).toEqual(["Treadmill", "Spin bike"]);
    });

    it("the cut: the chip pressed; every row one door, no pill, and one quiet Restore beside the door, never inside it", () => {
        const { container } = render(<Archived />);
        expect(screen.getByRole("button", { name: "Archived" }).getAttribute("aria-pressed")).toBe("true");
        expect(container.querySelector("ul")?.className).toBe("widget-rows widget-cut widget-selectable");
        expect(container.querySelectorAll("[data-pill]")).toHaveLength(0);
        for (const row of container.querySelectorAll("ul > li")) {
            expect(row.querySelectorAll("a")).toHaveLength(1);
            expect(row.querySelector("a button")).toBeNull();
            const restore = row.querySelectorAll('button[data-act="restore"]');
            expect(restore).toHaveLength(1);
            expect(restore[0]?.textContent).toBe("Restore");
            expect(restore[0]?.getAttribute("data-weight")).toBe("ghost");
        }
        expect(FACE_CSS).toMatch(/\.widget-chip:focus-visible \{[^}]*var\(--focus-ring\)/);
        expect(FACE_CSS).toMatch(/\.widget-chip \{[^}]*min-block-size: var\(--act-min\);/);
    });

    it("the cut being read: the chip pressed over still rows", () => {
        const { container } = render(<ArchivedLoading />);
        expect(screen.getByRole("button", { name: "Archived" }).getAttribute("aria-pressed")).toBe("true");
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    });

    it("the empty cut: Nothing archived., no door", () => {
        const { container } = render(<NothingArchived />);
        expect(screen.getByText("Nothing archived.")).toBeDefined();
        expect(container.querySelectorAll("a")).toHaveLength(0);
        expect(container.querySelectorAll("button")).toHaveLength(1);
    });

    it("a refused restore sits directly under its row, the row drawn and its Restore alive", () => {
        const { container } = render(<RefusedRestore />);
        const alert = screen.getByRole("alert");
        expect(alert.getAttribute("data-seat")).toBe("cut-row");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't restore");
        const row = alert.closest("li");
        expect(row?.querySelector(".widget-name")?.textContent).toBe(SPIN_BIKE.name);
        expect(row?.querySelector('button[data-act="restore"]')?.textContent).toBe("Restore");
        expect(container.querySelectorAll("ul.widget-rows > li")).toHaveLength(2);
    });

    it("the last row of a one-row cut restored: focus lands on the empty line, Nothing archived.", () => {
        // The stories cannot walk this (their cut's second row is held by its policy),
        // so the screen is driven directly, as the route would drive it.
        const one = { ...ARCHIVED_PAGE, items: ARCHIVED_PAGE.items.slice(0, 1) };
        const restore = { onRestore: () => undefined };
        const { container, rerender } = render(<WidgetList state={{ kind: "ready", data: one }} cut="archived" restore={restore} />);
        const button = container.querySelector('button[data-act="restore"]') as HTMLButtonElement;
        button.focus();
        fireEvent.click(button);
        rerender(<WidgetList state={{ kind: "empty" }} cut="archived" restore={restore} />);
        const line = container.querySelector("main > p");
        expect(line?.textContent).toBe("Nothing archived.");
        expect(document.activeElement).toBe(line);
    });

    it("the last row of a longer cut restored: focus lands on the previous row's Restore", () => {
        const restore = { onRestore: () => undefined };
        const { container, rerender } = render(<WidgetList state={{ kind: "ready", data: ARCHIVED_PAGE }} cut="archived" restore={restore} />);
        const [first, last] = Array.from(container.querySelectorAll('button[data-act="restore"]')) as HTMLButtonElement[];
        last?.focus();
        fireEvent.click(last as HTMLButtonElement);
        rerender(<WidgetList state={{ kind: "ready", data: { ...ARCHIVED_PAGE, items: ARCHIVED_PAGE.items.slice(0, 1) } }} cut="archived" restore={restore} />);
        const remaining = container.querySelectorAll('button[data-act="restore"]');
        expect(remaining).toHaveLength(1);
        expect(remaining[0]).toBe(first);
        expect(document.activeElement).toBe(first);
    });

    it("a restored row leaves the cut", () => {
        vi.useFakeTimers();
        const { container } = render(<Archived />);
        fireEvent.click(container.querySelector('button[data-act="restore"]') as HTMLButtonElement);
        expect(container.querySelector('button[data-act="restore"]')?.textContent).toBe("Restoring…");
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(Array.from(container.querySelectorAll("ul > li .widget-name"), (el) => el.textContent)).toEqual(["Spin bike"]);
    });
});

describe("a name with no break in it (the LongName story)", () => {
    it("wraps anywhere inside the row rather than widening the page", () => {
        const { container } = render(<LongName />);
        expect(LONG_NAME).toHaveLength(200);
        const name = container.querySelector("ul > li a .widget-name");
        expect(name?.textContent).toBe(LONG_NAME + "\u00a0Onboarding");
        // jsdom lays nothing out: the wrap is the face stylesheet's `.widget-name { overflow-wrap: anywhere }`,
        // read here, and walked once at 500 px in a real browser.
        expect(FACE_CSS).toMatch(/\.widget-name \{[^}]*overflow-wrap: anywhere;/);
    });
});

describe("accessibility", () => {
    it.each([...REQUIRED_STORY_EXPORTS])("%s has no axe violations", async (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        // jsdom computes no colour; contrast is the rendered drive's half.
        const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
        expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
});

describe("the face stylesheet's desk grid and phone stack", () => {
    it("lays the desk row out as the name block then one column per fact, aligned across rows", () => {
        expect(FACE_CSS).toMatch(/\.widget-rows \{[^}]*grid-template-columns: minmax\(0, 1fr\) repeat\(\d+, auto\);/);
        expect(FACE_CSS).toMatch(/\.widget-row \{[^}]*grid-template-columns: subgrid;[^}]*min-block-size: var\(--act-min\);/);
        expect(FACE_CSS).toMatch(/@media \(width <= 40rem\) \{[^@]*\.widget-row \{[^}]*flex-direction: column;/);
    });

    it("a pill wraps with the name and never splits: one unbreakable word after it (§16)", () => {
        const { container } = render(<LongName />);
        const pill = container.querySelector(".widget-name [data-pill]");
        expect(pill?.className).toBe("widget-pill");
        expect(pill?.parentElement?.className).toBe("widget-pill-join");
        expect(FACE_CSS).toMatch(/\.widget-pill,\n\.widget-pill-join \{[^}]*white-space: nowrap;[^}]*overflow-wrap: normal;/);
    });
});

describe("the bulk road on the list (§7, §8, §17)", () => {
    it("a checkbox leads every row the bulk verbs could take, named Select ⟨name⟩, beside the door and never inside it", () => {
        const { container } = render(<Ready />);
        for (const row of container.querySelectorAll("ul.widget-rows > li")) {
            const box = row.querySelector('input[type="checkbox"]');
            const name = row.querySelector(".widget-name")?.textContent?.replace(/\u00a0Onboarding$/, "");
            expect(box?.getAttribute("aria-label")).toBe(`Select ${name}`);
            expect(box?.closest("a")).toBeNull();
        }
        // Nothing is checked, so the control row's seat is the chip's.
        expect(container.querySelector('[data-seat="list-select"]')).toBeNull();
    });

    it("checked rows: the bar takes the control row's seat — the count, the verbs both rows allow (table order, ghost), the × at the trail", () => {
        const { container } = render(<Selected />);
        const bar = container.querySelector('[data-seat="list-select"]') as HTMLElement;
        expect(container.querySelector("h1")?.nextElementSibling).toBe(bar);
        expect(container.querySelector(".widget-controls")).toBeNull();
        expect(bar.querySelector(".widget-count")?.textContent).toBe("2 selected");
        // At exactly two, Merge joins the bulk verbs, in the table's order.
        expect(Array.from(bar.querySelectorAll("[data-act]"), (act) => [act.textContent, act.getAttribute("data-weight")])).toEqual([
            ["Move", "ghost"],
            ["Merge", "ghost"],
            ["Archive", "ghost"],
        ]);
        const clear = within(bar).getByRole("button", { name: C.clearSelectionLabel });
        expect(bar.lastElementChild).toBe(clear);
        fireEvent.click(clear);
        expect(container.querySelector('[data-seat="list-select"]')).toBeNull();
        expect(container.querySelectorAll('input[type="checkbox"]:checked')).toHaveLength(0);
    });

    it("one press, every row done: the rows leave, the band says Archived 2 widgets. with Restore them, which brings them back", () => {
        vi.useFakeTimers();
        const { container } = render(<Selected />);
        fireEvent.click(container.querySelector('[data-seat="list-select"] [data-act="archive"]') as HTMLButtonElement);
        expect(container.querySelector('[data-seat="list-select"] [data-act="archive"]')?.textContent).toBe("Archiving…");
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        const band = container.querySelector('[data-band="bulk"]');
        expect(band?.querySelector("p")?.textContent).toBe("Archived 2 widgets.");
        expect(container.querySelectorAll("ul.widget-rows > li")).toHaveLength(1);
        expect(container.querySelector('[data-seat="list-select"]')).toBeNull();
        fireEvent.click(within(band as HTMLElement).getByRole("button", { name: C.restoreThemAct }));
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(container.querySelectorAll("ul.widget-rows > li")).toHaveLength(3);
        expect(container.querySelector('[data-band="bulk"]')).toBeNull();
    });

    it("some refused: Archived 2 of 3 widgets.; the held row stays, checked, its refusal under it, and the bar counts only it", () => {
        const { container } = render(<BulkPartial />);
        expect(container.querySelector('[data-band="bulk"] p')?.textContent).toBe("Archived 2 of 3 widgets.");
        const rows = container.querySelectorAll("ul.widget-rows > li");
        expect(rows).toHaveLength(1);
        const alert = rows[0]?.querySelector('[role="alert"]');
        expect(alert?.getAttribute("data-seat")).toBe("list-select");
        expect(alert?.querySelector("p")?.textContent).toBe("Couldn't archive");
        expect(alert?.querySelector("a")?.getAttribute("href")).toBe("/example/widgets?policy=0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f51");
        expect((rows[0]?.querySelector('input[type="checkbox"]') as HTMLInputElement).checked).toBe(true);
        expect(container.querySelector('[data-seat="list-select"] .widget-count')?.textContent).toBe("1 selected");
    });

    it("the whole batch refused: one notice under the bar, the selection kept", () => {
        const { container } = render(<RefusedBulk />);
        const bar = container.querySelector('[data-seat="list-select"]');
        const alerts = container.querySelectorAll('[role="alert"]');
        expect(alerts).toHaveLength(1);
        expect(bar?.nextElementSibling?.contains(alerts[0] as Node)).toBe(true);
        expect(container.querySelectorAll('input[type="checkbox"]:checked')).toHaveLength(2);
    });

    it("the bar's Move opens the move sheet over the checked rows, and the band's Move them back returns them", async () => {
        vi.useFakeTimers();
        const proto = HTMLDialogElement.prototype;
        const saved = { showModal: proto.showModal, close: proto.close };
        proto.showModal = function (this: HTMLDialogElement) {
            this.setAttribute("open", "");
        };
        proto.close = function (this: HTMLDialogElement) {
            this.removeAttribute("open");
        };
        try {
            const { container } = render(<Selected />);
            fireEvent.click(container.querySelector('[data-seat="list-select"] [data-act="move"]') as HTMLButtonElement);
            expect(container.querySelector("dialog h2")?.textContent).toBe("Move 2 widgets");
            fireEvent.click(screen.getByRole("radio", { name: "Eastern depot" }));
            fireEvent.click(container.querySelector('dialog [data-act="move"]') as HTMLButtonElement);
            await act(async () => {
                vi.advanceTimersByTime(LATENCY_MS);
            });
            expect(container.querySelector("dialog")).toBeNull();
            const band = container.querySelector('[data-band="bulk"]') as HTMLElement;
            expect(band.querySelector("p")?.textContent).toBe("Moved 2 widgets.");
            expect(within(band).getByRole("button", { name: C.moveThemBackAct })).toBeDefined();
            expect(ROWING.organization_name).toBe("Northern branch");
        } finally {
            proto.showModal = saved.showModal;
            proto.close = saved.close;
        }
    });

    it("Move them back: the band says the move back, lands on its act, and its next press targets where the rows are now", async () => {
        vi.useFakeTimers();
        const proto = HTMLDialogElement.prototype;
        const saved = { showModal: proto.showModal, close: proto.close };
        proto.showModal = function (this: HTMLDialogElement) {
            this.setAttribute("open", "");
        };
        proto.close = function (this: HTMLDialogElement) {
            this.removeAttribute("open");
        };
        const sent: [readonly string[], string][] = [];
        const EASTERN = "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f23";
        function Harness() {
            const [items, setItems] = useState(PAGE_FOR_MOVE);
            const [answer, setAnswer] = useState<BulkAnswer | null>(null);
            return (
                <WidgetList
                    state={{ kind: "ready", data: { ...PAGE_FOR_MOVE_ENVELOPE, items } }}
                    bulk={{
                        answer,
                        selected: items.map((row) => row.id),
                        onBulk: () => undefined,
                        move: {
                            destinations: { kind: "ready", data: MOVE_DESTINATIONS },
                            onMoveMany: async (ids, organizationId) => {
                                sent.push([ids, organizationId]);
                                setItems((now) => now.map((row) => (ids.includes(row.id) ? { ...row, organization_id: organizationId } : row)));
                                setAnswer({ verb: "move", results: ids.map((id) => ({ id, outcome: "done" as const, refusal: null })) });
                                return true;
                            },
                        },
                    }}
                />
            );
        }
        try {
            const { container } = render(<Harness />);
            fireEvent.click(container.querySelector('[data-seat="list-select"] [data-act="move"]') as HTMLButtonElement);
            fireEvent.click(screen.getByRole("radio", { name: "Eastern depot" }));
            await act(async () => {
                fireEvent.click(container.querySelector('dialog [data-act="move"]') as HTMLButtonElement);
            });
            const back = () => within(container.querySelector('[data-band="bulk"]') as HTMLElement).getByRole("button", { name: C.moveThemBackAct });
            await act(async () => {
                fireEvent.click(back());
            });
            // The move back was sent to where the rows came from…
            expect(sent[1]?.[1]).toBe(ROWING.organization_id);
            // …the band says the move back, and focus lands on its act…
            expect(container.querySelector('[data-band="bulk"] p')?.textContent).toBe("Moved 2 widgets.");
            expect(document.activeElement).toBe(back());
            // …and its next press targets the node the rows were on BEFORE the move back.
            await act(async () => {
                fireEvent.click(back());
            });
            expect(sent[2]?.[1]).toBe(EASTERN);
        } finally {
            proto.showModal = saved.showModal;
            proto.close = saved.close;
        }
    });
});

describe("the import road on the list (§5 · §17)", () => {
    it("Import at the list head, ghost, a door to the import page; the band while a run is in flight, its words a door to the page", () => {
        const { container } = render(<ImportInFlight />);
        const head = container.querySelector('[data-seat="list-head"]') as HTMLElement;
        expect(container.querySelector("h1")?.nextElementSibling).toBe(head);
        const act = head.querySelector('[data-act="import"]') as HTMLAnchorElement;
        expect([act.tagName, act.textContent, act.getAttribute("data-weight"), act.getAttribute("href")]).toEqual(["A", "Import", "ghost", "/example/widgets/import"]);
        const band = container.querySelector('[data-band="importing"]') as HTMLElement;
        expect(band.textContent).toBe("Importing widgets.csv: 5 rows.");
        expect(band.querySelector("a")?.getAttribute("href")).toBe("/example/widgets/import");
        expect(container.querySelectorAll('[data-weight="primary"]')).toHaveLength(0);
    });

    it("a list whose answer offers no create draws no Import", () => {
        const { container } = render(<WidgetList state={{ kind: "ready", data: { ...ARCHIVED_PAGE, allowed_acts: [] } }} imports={{}} />);
        expect(container.querySelector('[data-act="import"]')).toBeNull();
    });
});

describe("the selection bar's Merge, at exactly two checked rows (§7, §1)", () => {
    // jsdom implements neither showModal() nor close(): stood in for around this block.
    const proto = HTMLDialogElement.prototype;
    const saved = { showModal: proto.showModal, close: proto.close };
    beforeAll(() => {
        proto.showModal = function (this: HTMLDialogElement) {
            this.setAttribute("open", "");
        };
        proto.close = function (this: HTMLDialogElement) {
            this.removeAttribute("open");
        };
    });
    afterAll(() => {
        proto.showModal = saved.showModal;
        proto.close = saved.close;
    });

    it("Merge opens the chooser pre-filled with the two; the one pressed survives; the one confirm asks; the merge takes the other out", async () => {
        vi.useFakeTimers();
        const { container } = render(<Selected />);
        fireEvent.click(container.querySelector('[data-seat="list-select"] [data-act="merge"]') as HTMLButtonElement);
        const chooser = container.querySelector("dialog[open]") as HTMLElement;
        expect(chooser.querySelector("h2")?.textContent).toBe(`Merge ${BENCH.name} and ${ROWING.name} into…`);
        expect(Array.from(chooser.querySelectorAll(".widget-pick"), (el) => el.textContent)).toEqual([BENCH.name, ROWING.name]);
        expect(document.activeElement).toBe(chooser.querySelector(".widget-pick"));
        fireEvent.click(within(chooser).getByRole("button", { name: ROWING.name }));
        const confirm = container.querySelector("dialog[open]") as HTMLElement;
        expect(confirm.querySelector("h2")?.textContent).toBe(`Merge ${BENCH.name} into ${ROWING.name}?`);
        expect(document.activeElement).toBe(confirm.querySelector("h2"));
        const merge = confirm.querySelector('footer [data-act="merge"]') as HTMLButtonElement;
        expect([merge.textContent, merge.getAttribute("data-weight")]).toEqual(["Merge", "primary"]);
        expect(container.querySelectorAll('[data-weight="primary"]')).toHaveLength(1);
        fireEvent(confirm, new Event("cancel", { cancelable: true }));
        expect(container.querySelector("dialog[open] h2")?.textContent).toBe(`Merge ${BENCH.name} and ${ROWING.name} into…`);
    });

    it("the merge landed: the face goes to the survivor's record (the route's navigation), the selection cleared", async () => {
        const onMerged = vi.fn();
        const onMerge = vi.fn(async () => true);
        const page = { items: [BENCH, ROWING], has_more: false, next_cursor: null, count: null, allowed_acts: ["create"] };
        const { container } = render(
            <WidgetList
                state={{ kind: "ready", data: page }}
                bulk={{
                    onBulk: () => undefined,
                    selected: [BENCH.id, ROWING.id],
                    merge: { onPick: () => undefined, preview: { kind: "ready", data: { loser_id: BENCH.id, into_id: ROWING.id, repoints: [] } }, onMerge, onMerged },
                }}
            />,
        );
        fireEvent.click(container.querySelector('[data-seat="list-select"] [data-act="merge"]') as HTMLButtonElement);
        fireEvent.click(within(container.querySelector("dialog[open]") as HTMLElement).getByRole("button", { name: ROWING.name }));
        await act(async () => {
            fireEvent.click(container.querySelector('dialog[open] footer [data-act="merge"]') as HTMLButtonElement);
        });
        expect(onMerge).toHaveBeenCalledWith(BENCH, ROWING);
        expect(onMerged).toHaveBeenCalledWith(ROWING);
        expect(container.querySelector("dialog")).toBeNull();
        expect(container.querySelector('[data-seat="list-select"]')).toBeNull();
    });

    it("on a phone the bar is one row: the count never wraps, the acts give up padding first", () => {
        expect(FACE_CSS).toMatch(/\.widget-count \{[^}]*white-space: nowrap;/);
        expect(FACE_CSS).toMatch(/@media \(width <= 40rem\) \{[^@]*\.widget-select > \.widget-act \{[^}]*padding: 0 var\(--space-2\);/);
    });

    it("one row, or three, draws no Merge in the bar", () => {
        const { container } = render(<Selected />);
        const boxes = Array.from(container.querySelectorAll('input[type="checkbox"]')) as HTMLInputElement[];
        const unchecked = boxes.find((box) => !box.checked) as HTMLInputElement;
        fireEvent.click(unchecked);
        expect(container.querySelector('[data-seat="list-select"] [data-act="merge"]')).toBeNull();
        fireEvent.click(unchecked);
        fireEvent.click(boxes.find((box) => box.checked) as HTMLInputElement);
        expect(container.querySelector('[data-seat="list-select"] [data-act="merge"]')).toBeNull();
    });
});

describe("the cuts are the wire's `show`, less `all`", () => {
    // The cuts this face draws; the type below holds them equal to `Cut`, which is
    // read from the generated client, so the list and the wire cannot drift apart.
    const FACE_CUTS = ["live", "archived"] as const;

    it("the face's cuts are `Cut`, and `Cut` is the generated client's `show`", () => {
        expectTypeOf<(typeof FACE_CUTS)[number]>().toEqualTypeOf<Cut>();
    });

    it("the document's `show` for the widget list is the face's cuts and `all`, which no face draws", () => {
        const document = JSON.parse(readFileSync(resolve(process.cwd(), "openapi.json"), "utf8")) as {
            readonly paths: Readonly<Record<string, { readonly get?: { readonly parameters?: readonly { readonly name: string; readonly schema?: { readonly enum?: readonly string[] } }[] } }>>;
        };
        const show = document.paths["/api/v1/widgets/"]?.get?.parameters?.find((parameter) => parameter.name === "show")?.schema?.enum;
        expect(show, "the document publishes the list's `show` enum").toBeDefined();
        expect([...(show ?? [])].filter((value) => value !== "all").sort()).toEqual([...FACE_CUTS].sort());
    });
});

describe("the noun's own fields and the live board (the screen shape's list)", () => {
    const DUE = { ...BENCH, due_at: "2026-11-02T17:00:00.000Z", status: "active" };
    const page = { items: [DUE, ROWING], has_more: false, next_cursor: null, count: null, allowed_acts: ["create"] };

    it("rows show the noun's own fields: its status and its due day beside the name and the two dates", () => {
        const { container } = render(<WidgetList state={{ kind: "ready", data: page }} />);
        const [first, second] = Array.from(container.querySelectorAll(".widget-row"));
        const facts = Array.from(first?.querySelectorAll(".widget-fact") ?? [], (fact) => fact.textContent);
        expect(facts).toEqual(["Due at 2 November 2026", "Status active", `${C.addedLabel} 23 August 2026`, expect.stringContaining(C.changedLabel)]);
        // A row that lacks a fact keeps its column and says nothing in it.
        const blank = Array.from(second?.querySelectorAll(".widget-fact") ?? [], (fact) => fact.textContent);
        expect(blank.slice(0, 2)).toEqual(["", `Status ${ROWING.status}`]);
        expect(container.textContent).not.toMatch(/undefined|null/);
    });

    it("the face's grid holds one column per fact: the name, the noun's own, then the two dates", () => {
        const own = Object.keys(C.columns).length;
        expect(FACE_CSS).toContain(`grid-template-columns: minmax(0, 1fr) repeat(${own + 2}, auto);`);
    });

    it("data-board=live: the list says the socket feed's state on its page, and nothing without one", () => {
        const { container, rerender } = render(<WidgetList state={{ kind: "ready", data: page }} board="live" />);
        expect(container.querySelector("main")?.getAttribute("data-board")).toBe("live");
        rerender(<WidgetList state={{ kind: "ready", data: page }} />);
        expect(container.querySelector("main")?.hasAttribute("data-board")).toBe(false);
    });
});
