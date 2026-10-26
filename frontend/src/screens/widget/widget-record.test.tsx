import { act, fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { WIDGET_COPY as C, WIDGET_FIELD_WORDS } from "@pilecap/copy/widget";
import { REQUIRED_STORY_EXPORTS } from "@pilecap/ui/state";
import { archivedOf, BENCH, LATENCY_MS, ROWING } from "@/screens/widget/widget-list.stories";
import { historyWhat } from "@/screens/widget/widget-history";
import { WidgetRecord } from "@/screens/widget/widget-record";
import {
    ActsAfterFrame,
    ArrivedAfterMerge,
    Archived,
    AttachedMember,
    AttachLoading,
    Attached,
    Duplicated,
    Empty,
    Error as Refused,
    History,
    HistoryEmpty,
    HistoryLoading,
    Loading,
    MergeChoosing,
    Merged,
    Moved,
    NothingAttached,
    NowhereToMove,
    PopulatedAdmin,
    PopulatedMember,
    Ready,
    RefusedArchive,
    RefusedAttach,
    RefusedDuplicate,
    RefusedHistory,
    RefusedMerge,
    RefusedMove,
    RefusedRestore,
    RefusedUpdate,
    Resting,
    Stale,
} from "@/screens/widget/widget-record.stories";

afterEach(() => {
    vi.useRealTimers();
});

// jsdom draws a <dialog> but implements neither showModal() nor close(): the
// family's sheet stories open one, so both are stood in for, around this file.
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

/** The document of record, read in node (never bundled into a face): the fields' titles live here. */
const DOCUMENT = JSON.parse(readFileSync(resolve(process.cwd(), "openapi.json"), "utf8")) as {
    readonly components: { readonly schemas: Readonly<Record<string, { readonly properties?: Readonly<Record<string, { readonly title?: string }>> }>> };
};

const STORIES = { Loading, Empty, Error: Refused, Ready } as const;
// The fe leg and the builder both run vitest from `frontend/` (its config root).
const FACE_CSS = readFileSync(resolve(process.cwd(), "src/screens/widget/widget-face.css"), "utf8");
const MACHINE = [/northern-branch/, /@example\.com/, /[0-9a-f]{8}-[0-9a-f]{4}-/, /undefined/];

describe("the worked widget record: every authored state renders", () => {
    it.each([...REQUIRED_STORY_EXPORTS])("%s keeps the crumb: one link to the list, wearing its title, at the act floor", (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        const crumb = container.querySelector('main > p > a[href="/example/widgets"]');
        expect(crumb?.textContent).toBe(C.title);
        expect(crumb?.className).toBe("widget-crumb");
        expect(FACE_CSS).toMatch(/\.widget-crumb \{[^}]*min-block-size: var\(--act-min\);/);
        expect(FACE_CSS).toMatch(/\.widget-crumb:focus-visible \{[^}]*var\(--focus-ring\)/);
    });

    it.each([...REQUIRED_STORY_EXPORTS])("%s draws no act and puts no machine token in front of a reader", (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        expect(container.querySelectorAll("button")).toHaveLength(0);
        expect(container.querySelector('[data-seat="record-acts"]')).toBeNull();
        for (const token of MACHINE) expect(container.textContent ?? "").not.toMatch(token);
    });

    it("loading: a still shape at the name's height, no name, the cards' titles drawn", () => {
        const { container } = render(<Loading />);
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
        expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
        expect(screen.getByRole("heading", { name: C.aboutTitle })).toBeDefined();
        expect(screen.getByRole("heading", { name: C.detailsTitle })).toBeDefined();
    });

    it("empty: under the crumb alone, Nothing to show here., and no second door: one link to the list, no act", () => {
        const { container } = render(<Empty />);
        expect(screen.getByText("Nothing to show here.")).toBeDefined();
        expect(screen.queryByRole("heading")).toBeNull();
        const links = container.querySelectorAll("a");
        expect(links).toHaveLength(1);
        expect(links[0]?.getAttribute("href")).toBe("/example/widgets");
        expect(links[0]?.textContent).toBe(C.title);
        expect(container.querySelectorAll("button")).toHaveLength(0);
    });

    it("refused: the crumb alone over the server's own not-found fact", () => {
        render(<Refused />);
        expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
        expect(within(screen.getByRole("alert")).getByText(/There is no such row here/)).toBeDefined();
    });
});

describe("the populated record (the Ready story): the departure", () => {
    it("heads with the name (focusable for a way back) and its one pill after it", () => {
        const { container } = render(<Ready />);
        const name = screen.getByRole("heading", { level: 1 });
        expect(name.textContent).toBe(ROWING.name);
        expect(name.getAttribute("tabindex")).toBe("-1");
        const pills = container.querySelectorAll("[data-pill]");
        expect(pills).toHaveLength(1);
        expect(pills[0]?.textContent).toBe(C.onboardingLabel);
        expect(name.nextElementSibling).toBe(pills[0]);
    });

    it("main holds About (the description); the rail's Details draws no line for an absent fact", () => {
        const { container } = render(<Ready />);
        expect(within(screen.getByRole("region", { name: C.aboutTitle })).getByText(ROWING.notes)).toBeDefined();
        expect(container.querySelector("aside")?.textContent).toBe("DetailsAdded24 August 2026Last changed20 September 2026");
    });
});

describe("the lede", () => {
    it("names the scope the record lives in, by name, never its slug", () => {
        const { container } = render(<Ready />);
        expect(container.querySelector("header > p")?.textContent).toBe("Northern branch");
    });
});

describe("the archive road on the record (§20)", () => {
    it("the admin hat: the family's acts in the table's order, all ghost, Archive last in the head's acts row, under the name", () => {
        const { container } = render(<PopulatedAdmin />);
        const seat = container.querySelector('header [data-seat="record-acts"]');
        const acts = Array.from(seat?.querySelectorAll("button") ?? []);
        expect(acts.map((act) => [act.textContent, act.getAttribute("data-act"), act.getAttribute("data-weight")])).toEqual([
            ["Edit", "update", "ghost"],
            ["Move", "move", "ghost"],
            ["Duplicate", "duplicate", "ghost"],
            ["Merge", "merge", "ghost"],
            ["Archive", "archive", "ghost"],
        ]);
        for (const act of acts) expect(act.className).toBe("widget-act");
        expect(FACE_CSS).toMatch(/\.widget-act \{[^}]*min-block-size: var\(--act-min\);/);
        expect(FACE_CSS).toMatch(/\.widget-act:focus-visible \{[^}]*var\(--focus-ring\)/);
    });

    it("the member hat: the acts row is absent, not an empty element", () => {
        const { container } = render(<PopulatedMember />);
        expect(container.querySelector("[data-seat]")).toBeNull();
        expect(container.querySelectorAll("button")).toHaveLength(0);
    });

    it("a route that takes no act draws none, whatever the row allows (the Ready story): absent, never dead", () => {
        const { container } = render(<Ready />);
        expect(container.querySelectorAll("button")).toHaveLength(0);
    });

    it("pressed: the busy form on the same button, alive; then the band and its Restore", () => {
        vi.useFakeTimers();
        const { container } = render(<PopulatedAdmin />);
        const archive = container.querySelector('button[data-act="archive"]') as HTMLButtonElement;
        fireEvent.click(archive);
        expect(archive.textContent).toBe("Archiving…");
        expect(archive.getAttribute("aria-busy")).toBe("true");
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(container.querySelector('[data-seat="record-acts"]')).toBeNull();
        const band = container.querySelector('[data-band="archived"]');
        expect(band?.querySelector("p")?.textContent).toBe("Archived 27 September 2026.");
        expect(band?.querySelector('button[data-act="restore"]')?.textContent).toBe("Restore");
    });

    it("archived: the band under the head, its one act Restore; no head acts, no pill, no primary", () => {
        const { container } = render(<Archived />);
        const band = container.querySelector('[data-band="archived"]');
        expect(band?.previousElementSibling?.tagName).toBe("HEADER");
        expect(band?.textContent).toBe("Archived 27 September 2026." + "Restore");
        expect(container.querySelector("[data-seat]")).toBeNull();
        expect(container.querySelectorAll("[data-pill]")).toHaveLength(0);
        expect(container.querySelectorAll("button")).toHaveLength(1);
        expect(container.querySelectorAll('[data-weight="primary"]')).toHaveLength(0);
    });

    it("the band names the archiver when the wire does, and says the day alone when it does not", () => {
        const named = render(<WidgetRecord state={{ kind: "ready", data: archivedOf(ROWING, "2026-09-27T11:20:00.000Z", "Maria Delgado") }} />);
        expect(named.container.querySelector('[data-band="archived"] p')?.textContent).toBe("Archived 27 September 2026 by Maria Delgado.");
        named.unmount();
        const nameless = render(<WidgetRecord state={{ kind: "ready", data: { ...archivedOf(ROWING), archived_by: null } }} />);
        expect(nameless.container.querySelector('[data-band="archived"] p')?.textContent).toBe("Archived 27 September 2026.");
    });

    it("refused archive: Couldn't archive first, the server's fact, the blocker's label a live door, Archive alive", () => {
        const { container } = render(<RefusedArchive />);
        const alert = screen.getByRole("alert");
        expect(alert.getAttribute("data-seat")).toBe("record-acts");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't archive");
        expect(within(alert).getByText("This cannot be archived while something still depends on it.")).toBeDefined();
        const door = within(alert).getByRole("link");
        expect(door.textContent).toBe("Archive the widgets that name this policy, or give them another, first");
        expect(door.getAttribute("href")).toBe("/example/widgets?policy=0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f51");
        // The seat is directly under the acts row, inside the head.
        expect(alert.parentElement?.previousElementSibling?.getAttribute("data-seat")).toBe("record-acts");
        expect(container.querySelector('button[data-act="archive"]')?.textContent).toBe("Archive");
        expect(alert.textContent).not.toMatch(/try again/i);
    });

    it("refused restore: under the band, Couldn't restore first, the door the label alone (no page draws it), Restore alive", () => {
        const { container } = render(<RefusedRestore />);
        const alert = screen.getByRole("alert");
        expect(alert.getAttribute("data-seat")).toBe("band");
        expect(alert.parentElement?.previousElementSibling?.getAttribute("data-band")).toBe("archived");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't restore");
        expect(within(alert).queryByRole("link")).toBeNull();
        const door = alert.querySelector("[data-destination]");
        expect(door?.tagName).toBe("SPAN");
        expect(door?.textContent).toBe("Restore the policy this widget names first");
        expect(container.querySelector('button[data-act="restore"]')?.textContent).toBe("Restore");
    });
});

describe("the acts come from the REST read alone (the ActsAfterFrame story)", () => {
    it("a frame arrives and the acts do not move; the re-read redraws them", () => {
        vi.useFakeTimers();
        const { container } = render(<ActsAfterFrame />);
        const frames = () => container.querySelector("[data-frames]")?.getAttribute("data-frames");
        const acts = () => Array.from(container.querySelectorAll("[data-act]"), (el) => el.getAttribute("data-act"));
        expect([frames(), acts()]).toEqual(["0", ["update", "move", "duplicate", "merge", "archive"]]);
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        // The frame has landed; the face is unchanged until the re-read answers.
        expect([frames(), acts()]).toEqual(["1", ["update", "move", "duplicate", "merge", "archive"]]);
        expect(container.querySelector('[data-band="archived"]')).toBeNull();
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS * 2);
        });
        expect([frames(), acts()]).toEqual(["1", ["restore"]]);
        expect(container.querySelector('[data-band="archived"]')).not.toBeNull();
    });
});

describe("the resting record (the Resting story)", () => {
    it("wears no pill, says No description yet., and draws every present fact", () => {
        const { container } = render(<Resting />);
        expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(BENCH.name);
        expect(container.querySelectorAll("[data-pill]")).toHaveLength(0);
        expect(within(screen.getByRole("region", { name: C.aboutTitle })).getByText("No description yet.")).toBeDefined();
        expect(container.querySelector("aside")?.textContent).toBe(
            "DetailsAdded23 August 2026Last changed2 September 2026Onboarded2 September 2026",
        );
    });
});

describe("accessibility", () => {
    it.each([...REQUIRED_STORY_EXPORTS])("%s has no axe violations", async (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
        expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
});

describe("the edit sheet, versioned (§1, the Edit road)", () => {
    it("the fields' words are the generated schema's titles for the Patch, verbatim, less the version", () => {
        const patch = DOCUMENT.components.schemas.WidgetPatch?.properties ?? {};
        const titles = Object.fromEntries(
            Object.entries(patch)
                .filter(([key]) => key !== "version")
                .map(([key, property]) => [key, property.title]),
        );
        expect(WIDGET_FIELD_WORDS).toEqual(titles);
    });

    it("the lost race: the sheet up, its title the name, the fields read; Couldn't save above the foot, the server's sentence, Reload beside it, Save alive", () => {
        const { container } = render(<Stale />);
        const sheet = container.querySelector("dialog[open]") as HTMLElement;
        expect(sheet.querySelector("h2")?.textContent).toBe(ROWING.name);
        expect((sheet.querySelector("input") as HTMLInputElement).value).toBe(ROWING.name);
        const alert = within(sheet).getByRole("alert");
        expect(alert.getAttribute("data-seat")).toBe("sheet-foot");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't save");
        expect(alert.textContent).toContain("Somebody else changed this since you read it");
        expect(alert.textContent ?? "").not.toMatch(/try again/i);
        expect(within(sheet).getByRole("button", { name: C.reloadAct })).toBeDefined();
        const save = sheet.querySelector('footer [data-act="update"]');
        expect([save?.textContent, save?.getAttribute("data-weight")]).toEqual(["Save", "primary"]);
        // The foot holds the one press and nothing else: the dismiss is in the head.
        expect(Array.from(sheet.querySelectorAll("footer button"), (button) => button.textContent)).toEqual(["Save"]);
    });

    it("a clean form reloads at once — no ask — and the re-read's values are the draft", () => {
        vi.useFakeTimers();
        const { container } = render(<Stale />);
        fireEvent.click(screen.getByRole("button", { name: C.reloadAct }));
        expect(container.querySelector("dialog p + button")).toBeNull();
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect((container.querySelector("dialog textarea") as HTMLTextAreaElement).value).toBe("Belt replaced in August; the seat rail squeaks.");
        expect(container.querySelector('dialog [role="alert"]')).toBeNull();
    });

    it("a dirty form asks first: Discard your changes? · Keep editing · Discard, in place, and Keep editing keeps the draft", () => {
        const { container } = render(<Stale />);
        fireEvent.change(container.querySelector("dialog input") as HTMLInputElement, { target: { value: "Mine" } });
        fireEvent.click(screen.getByRole("button", { name: C.reloadAct }));
        expect(container.querySelector("dialog .widget-ask")?.textContent).toBe("Discard your changes?Keep editingDiscard");
        expect(container.querySelectorAll("dialog")).toHaveLength(1);
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
        expect((container.querySelector("dialog input") as HTMLInputElement).value).toBe("Mine");
    });

    it("another refusal: Couldn't save and the server's remedies, no Reload (a re-read would not answer it)", () => {
        const { container } = render(<RefusedUpdate />);
        const alert = container.querySelector('dialog [role="alert"]');
        expect(alert?.querySelector("p")?.textContent).toBe("Couldn't save");
        expect(alert?.querySelector('[data-destination="header:X-Org"]')?.tagName).toBe("SPAN");
        expect(screen.queryByRole("button", { name: C.reloadAct })).toBeNull();
    });

    it("a save that wins closes the sheet, and the record shows what was saved", async () => {
        vi.useFakeTimers();
        const { container } = render(<PopulatedAdmin />);
        fireEvent.click(container.querySelector('[data-seat="record-acts"] [data-act="update"]') as HTMLButtonElement);
        fireEvent.change(container.querySelector("dialog input") as HTMLInputElement, { target: { value: "Rowing machine, the good one" } });
        fireEvent.click(container.querySelector('dialog [data-act="update"]') as HTMLButtonElement);
        expect(container.querySelector('dialog [data-act="update"]')?.textContent).toBe("Saving…");
        await act(async () => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(container.querySelector("dialog")).toBeNull();
        expect(container.querySelector("h1")?.textContent).toBe("Rowing machine, the good one");
    });
});

describe("the move sheet (§1, the Move road)", () => {
    it("Move ⟨name⟩, one choice per destination by name, the current node marked, Move the foot's one press once a node is chosen", () => {
        const { container } = render(<PopulatedAdmin />);
        fireEvent.click(container.querySelector('[data-seat="record-acts"] [data-act="move"]') as HTMLButtonElement);
        const sheet = container.querySelector("dialog[open]") as HTMLElement;
        expect(sheet.querySelector("h2")?.textContent).toBe(`Move ${ROWING.name}`);
        const nodes = Array.from(sheet.querySelectorAll(".widget-choice"), (node) => node.textContent);
        expect(nodes).toEqual(["Northern branch", "Southern branch", "Eastern depot"]);
        // The current node is marked — its own element, `aria-current`, the mark's class — and offers no radio.
        const current = sheet.querySelector('[aria-current="true"]');
        expect(current?.textContent).toBe("Northern branch");
        expect(current?.classList.contains("widget-current")).toBe(true);
        expect(current?.querySelector("input")).toBeNull();
        expect(Array.from(sheet.querySelectorAll('input[type="radio"]'), (radio) => radio.closest("label")?.textContent)).toEqual([
            "Southern branch",
            "Eastern depot",
        ]);
        fireEvent.click(screen.getByRole("radio", { name: "Eastern depot" }));
        expect(Array.from(sheet.querySelectorAll("footer button"), (button) => [button.textContent, button.getAttribute("data-weight")])).toEqual([
            ["Move", "primary"],
        ]);
        for (const token of MACHINE) expect(sheet.textContent ?? "").not.toMatch(token);
    });

    it("the current node is marked, never chosen: not a choice at all, no choice made, the foot draws no Move", () => {
        const { container } = render(<PopulatedAdmin />);
        fireEvent.click(container.querySelector('[data-seat="record-acts"] [data-act="move"]') as HTMLButtonElement);
        const sheet = container.querySelector("dialog[open]") as HTMLElement;
        const current = sheet.querySelector('[aria-current="true"]') as HTMLElement;
        expect(current.querySelector("input")).toBeNull();
        expect(screen.queryByRole("radio", { name: "Northern branch" })).toBeNull();
        expect(sheet.querySelector("input:checked")).toBeNull();
        expect(sheet.querySelector('[data-act="move"]')).toBeNull();
        // Pressing the marked node chooses nothing.
        fireEvent.click(current);
        expect(sheet.querySelector('[data-act="move"]')).toBeNull();
        fireEvent.click(screen.getByRole("radio", { name: "Southern branch" }));
        expect(sheet.querySelector('footer [data-act="move"]')?.textContent).toBe("Move");
    });

    it("nowhere to move: the empty sheet draws no Move", () => {
        const { container } = render(<NowhereToMove />);
        expect(container.querySelector('dialog [data-act="move"]')).toBeNull();
        expect(container.querySelector("dialog footer")).toBeNull();
    });

    it("the answer: the sheet closes and the lede names the new node, by name", async () => {
        vi.useFakeTimers();
        const { container } = render(<PopulatedAdmin />);
        fireEvent.click(container.querySelector('[data-seat="record-acts"] [data-act="move"]') as HTMLButtonElement);
        fireEvent.click(screen.getByRole("radio", { name: "Southern branch" }));
        fireEvent.click(container.querySelector('dialog [data-act="move"]') as HTMLButtonElement);
        expect(container.querySelector('dialog [data-act="move"]')?.textContent).toBe("Moving…");
        await act(async () => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(container.querySelector("dialog")).toBeNull();
        expect(container.querySelector("header > p")?.textContent).toBe("Southern branch");
    });

    it("refused: Couldn't move one line above the foot, the sheet open, Move alive", () => {
        const { container } = render(<RefusedMove />);
        const alert = container.querySelector('dialog [role="alert"]');
        expect(alert?.getAttribute("data-seat")).toBe("sheet-foot");
        expect(alert?.querySelector("p")?.textContent).toBe("Couldn't move");
        expect(container.querySelector('dialog footer [data-act="move"]')?.textContent).toBe("Move");
    });

    it("nowhere to move: the sheet's one sentence, no choice", () => {
        const { container } = render(<NowhereToMove />);
        expect(container.querySelector("dialog .widget-sheet")?.textContent).toBe(C.moveNowhere);
        expect(container.querySelectorAll('dialog input[type="radio"]')).toHaveLength(0);
    });

    it("moved out of sight: the band Moved to ⟨node⟩., and no act, no pill, no sheet", () => {
        const { container } = render(<Moved />);
        expect(container.querySelector('[data-band="moved"]')?.textContent).toBe("Moved to Southern branch.");
        expect(container.querySelectorAll("button")).toHaveLength(0);
        expect(container.querySelectorAll("[data-pill]")).toHaveLength(0);
    });
});

describe("the History card (§10, the History card)", () => {
    it("the last card in main, rows newest first: what · who (a name, or no clause) · the day; Show earlier secondary at its foot", () => {
        render(<History />);
        const card = screen.getByRole("region", { name: C.historyTitle });
        expect(Array.from(card.querySelectorAll("li"), (row) => row.textContent)).toEqual([
            "Changed notes · 20 September 2026",
            "Changed name and notes · Maria Delgado · 12 September 2026",
            "Added · 24 August 2026",
        ]);
        const earlier = within(card).getByRole("button", { name: C.showEarlierAct });
        expect(earlier.getAttribute("data-weight")).toBe("secondary");
        expect(card.querySelectorAll("[data-act]")).toHaveLength(0);
    });

    it("the words: a family verb's state word, Changed ⟨fields⟩ in the reader's words, never a key", () => {
        expect(historyWhat("archive", [])).toBe("Archived");
        expect(historyWhat("update", ["name", "notes", "policy_id", "version"])).toBe("Changed name, notes and policy id");
        expect(historyWhat("update", ["version"])).toBe("Changed");
        expect(historyWhat("approve", [])).toBe("Changed");
    });

    it("loading: three still rows under the title; empty: No history yet., no door; refused: the notice inside the card", () => {
        const loading = render(<HistoryLoading />);
        const still = screen.getByRole("region", { name: C.historyTitle });
        expect(still.getAttribute("aria-busy")).toBe("true");
        loading.unmount();
        const empty = render(<HistoryEmpty />);
        expect(screen.getByRole("region", { name: C.historyTitle }).textContent).toBe(`${C.historyTitle}${C.historyEmpty}`);
        empty.unmount();
        render(<RefusedHistory />);
        const alert = within(screen.getByRole("region", { name: C.historyTitle })).getByRole("alert");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't load the history");
    });
});

describe("the duplicate road on the record (the Duplicate road)", () => {
    it("one press: Duplicating… on the same button, then the face stands on the copy — its name focused, the band naming the source as a live door", () => {
        vi.useFakeTimers();
        const { container } = render(<PopulatedAdmin />);
        const duplicate = container.querySelector('[data-seat="record-acts"] [data-act="duplicate"]') as HTMLButtonElement;
        duplicate.focus();
        fireEvent.click(duplicate);
        expect(duplicate.textContent).toBe("Duplicating…");
        expect(duplicate.getAttribute("aria-busy")).toBe("true");
        expect(container.querySelector("dialog")).toBeNull();
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        const name = container.querySelector("h1");
        expect(name?.textContent).toBe(`Copy of ${ROWING.name}`);
        expect(document.activeElement).toBe(name);
        const band = container.querySelector('[data-band="duplicated"]');
        expect(band?.textContent).toBe(`Duplicated from ${ROWING.name}.`);
        expect(band?.querySelector("a")?.getAttribute("href")).toBe(`/example/widgets/${ROWING.id}`);
        // The copy is an ordinary live noun: its own acts, Archive last (its way back).
        expect(Array.from(container.querySelectorAll('[data-seat="record-acts"] [data-act]'), (el) => el.getAttribute("data-act")).at(-1)).toBe("archive");
    });

    it("the Duplicated story: the band, no act in it, no primary", () => {
        const { container } = render(<Duplicated />);
        const band = container.querySelector('[data-band="duplicated"]') as HTMLElement;
        expect(band.querySelectorAll("button")).toHaveLength(0);
        expect(container.querySelectorAll('[data-weight="primary"]')).toHaveLength(0);
        for (const token of MACHINE) expect(band.textContent ?? "").not.toMatch(token);
    });

    it("refused: Couldn't duplicate in the head's seat, the server's sentence, Duplicate alive", () => {
        const { container } = render(<RefusedDuplicate />);
        const alert = container.querySelector('[role="alert"]') as HTMLElement;
        expect(alert.getAttribute("data-seat")).toBe("record-acts");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't duplicate");
        expect(container.querySelector('[data-seat="record-acts"] [data-act="duplicate"]')).not.toBeNull();
    });
});

describe("the merge road on the record (the Merge road)", () => {
    const openChooser = () => {
        const utils = render(<PopulatedAdmin />);
        fireEvent.click(utils.container.querySelector('[data-seat="record-acts"] [data-act="merge"]') as HTMLButtonElement);
        return utils;
    };

    it("Merge opens the chooser: Merge ⟨name⟩ into…, the search focused, the rows the server allows as survivors by name, no foot", () => {
        const { container } = openChooser();
        const sheet = container.querySelector("dialog[open]") as HTMLElement;
        expect(sheet.querySelector("h2")?.textContent).toBe(`Merge ${ROWING.name} into…`);
        expect(document.activeElement).toBe(sheet.querySelector('input[type="search"]'));
        // A row whose own answer does not offer merge, and the row itself, are not survivors.
        expect(Array.from(sheet.querySelectorAll(".widget-pick"), (el) => el.textContent)).toEqual([BENCH.name, "Rowing machine (old tag)"]);
        expect(sheet.querySelector("footer")).toBeNull();
        expect(sheet.querySelectorAll("[data-act]")).toHaveLength(0);
    });

    it("picking a survivor opens THE confirm: the question focused, the dry run's words, ONE primary Merge; Escape returns to the chooser", () => {
        const { container } = openChooser();
        fireEvent.click(screen.getByRole("button", { name: BENCH.name }));
        const confirm = container.querySelector("dialog[open]") as HTMLElement;
        const question = confirm.querySelector("h2") as HTMLElement;
        expect(question.textContent).toBe(`Merge ${ROWING.name} into ${BENCH.name}?`);
        expect(document.activeElement).toBe(question);
        expect(confirm.textContent).toContain(`3 notes and 12 entries move to ${BENCH.name}.`);
        expect(Array.from(confirm.querySelectorAll("footer button"), (el) => [el.textContent, el.getAttribute("data-act"), el.getAttribute("data-weight")])).toEqual([
            ["Merge", "merge", "primary"],
        ]);
        fireEvent(confirm, new Event("cancel", { cancelable: true }));
        expect(container.querySelector("dialog[open] h2")?.textContent).toBe(`Merge ${ROWING.name} into…`);
    });

    it("Merge in the confirm: Merging… on the same button, then the face stands on the survivor, its name focused", async () => {
        vi.useFakeTimers();
        const { container } = openChooser();
        fireEvent.click(screen.getByRole("button", { name: BENCH.name }));
        const merge = container.querySelector('dialog[open] footer [data-act="merge"]') as HTMLButtonElement;
        fireEvent.click(merge);
        expect(merge.textContent).toBe("Merging…");
        await act(async () => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(container.querySelector("dialog")).toBeNull();
        expect(container.querySelector("h1")?.textContent).toBe(BENCH.name);
        expect(document.activeElement).toBe(container.querySelector("h1"));
    });

    it("refused merge_blocked: inside the confirm, one line above its foot, Couldn't merge first, Merge alive", () => {
        const { container } = render(<RefusedMerge />);
        const confirm = container.querySelector("dialog[open]") as HTMLElement;
        const alert = confirm.querySelector('[role="alert"]') as HTMLElement;
        expect(alert.getAttribute("data-seat")).toBe("sheet-foot");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't merge");
        expect(confirm.querySelector('footer [data-act="merge"]')).not.toBeNull();
    });

    it("the chooser story opens on the chooser alone", () => {
        const { container } = render(<MergeChoosing />);
        expect(container.querySelectorAll("dialog[open]")).toHaveLength(1);
        expect(container.querySelector("dialog[open] h2")?.textContent).toBe(`Merge ${ROWING.name} into…`);
    });

    it("merged: the band Merged into ⟨survivor⟩ on ⟨day⟩., the survivor a live door; no act, no pill, no primary, no archived band", () => {
        const { container } = render(<Merged />);
        const band = container.querySelector('[data-band="merged"]') as HTMLElement;
        expect(band.textContent).toBe(`Merged into ${BENCH.name} on 27 September 2026.`);
        expect(band.querySelector("a")?.getAttribute("href")).toBe(`/example/widgets/${BENCH.id}`);
        expect(container.querySelector('[data-band="archived"]')).toBeNull();
        expect(container.querySelectorAll("[data-act]")).toHaveLength(0);
        expect(container.querySelectorAll("[data-pill]")).toHaveLength(0);
    });

    it("reached by the list's two-row Merge, the survivor's record lands focus on its name", () => {
        const { container } = render(<ArrivedAfterMerge />);
        expect(document.activeElement).toBe(container.querySelector("h1"));
    });

    it("a merged row with no survivor named says the day alone", () => {
        const merged = { ...ROWING, merged_into_id: BENCH.id, archived_at: "2026-09-27T15:10:00.000Z", allowed_acts: [] };
        const { container } = render(<WidgetRecord state={{ kind: "ready", data: merged }} />);
        expect(container.querySelector('[data-band="merged"]')?.textContent).toBe("Merged 27 September 2026.");
    });
});

describe("the attach road on the record (notes, files and tags)", () => {
    const cards = (container: HTMLElement) =>
        Array.from(container.querySelectorAll("main section[aria-label]"))
            .filter((card) => card.closest("aside") === null)
            .map((card) => card.getAttribute("aria-label"));

    it("the cards in main: About, Notes, Files — rows by their words and day, never an address; the tag row under the lede", () => {
        const { container } = render(<Attached />);
        expect(cards(container)).toEqual(["About", "Notes", "Files"]);
        const notes = container.querySelector('section[aria-label="Notes"]') as HTMLElement;
        expect(Array.from(notes.querySelectorAll("li"), (li) => li.textContent)).toEqual([
            "Squeaks at the top of the stroke. · 21 September 2026",
            "Serviced by the supplier. · 2 September 2026",
        ]);
        for (const token of MACHINE) expect(notes.textContent ?? "").not.toMatch(token);
        const files = container.querySelector('section[aria-label="Files"]') as HTMLElement;
        expect(files.querySelector("li span")?.textContent).toBe("service-report.pdf · 2 September 2026");
        expect(files.querySelector('li [data-act="archive"]')?.textContent).toBe("Archive");
        const tags = container.querySelector("header [data-tags]") as HTMLElement;
        expect(tags.previousElementSibling?.textContent).toBe(ROWING.organization_name);
        expect(within(tags).getByRole("button", { name: "Remove tag Cardio" }).textContent).toBe("×");
        expect(Array.from(container.querySelectorAll('[data-act="attach"]'), (el) => [el.textContent, el.getAttribute("data-weight")])).toEqual([
            ["Add a tag", "ghost"],
            ["Add a note", "ghost"],
            ["Add a file", "ghost"],
        ]);
        expect(container.querySelectorAll('[data-weight="primary"]')).toHaveLength(0);
    });

    it("a member: Add a note and Add a tag drawn (any reader may), Add a file absent (the files list offers no create), no file Archive", () => {
        const { container } = render(<AttachedMember />);
        expect(Array.from(container.querySelectorAll('[data-act="attach"]'), (el) => el.textContent)).toEqual(["Add a tag", "Add a note"]);
        expect(container.querySelector('section[aria-label="Files"] [data-act]')).toBeNull();
        expect(container.querySelector('[data-seat="record-acts"]')).toBeNull();
    });

    it("Add a note opens the inline field, focused; Add is its one primary; the answer lands on the new row", async () => {
        vi.useFakeTimers();
        const { container } = render(<Attached />);
        fireEvent.click(screen.getByRole("button", { name: "Add a note" }));
        const field = container.querySelector('section[aria-label="Notes"] textarea') as HTMLTextAreaElement;
        expect(document.activeElement).toBe(field);
        expect(container.querySelector('section[aria-label="Notes"] [data-weight="primary"]')).toBeNull();
        fireEvent.change(field, { target: { value: "Belt tensioned." } });
        const add = container.querySelector('section[aria-label="Notes"] [data-weight="primary"]') as HTMLButtonElement;
        expect(add.textContent).toBe("Add");
        fireEvent.click(add);
        expect(add.textContent).toBe("Adding…");
        await act(async () => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        const first = container.querySelector('section[aria-label="Notes"] li');
        expect(first?.textContent).toBe("Belt tensioned. · 28 September 2026");
        expect(document.activeElement).toBe(first);
        expect(container.querySelector('section[aria-label="Notes"] textarea')).toBeNull();
    });

    it("Add a tag opens the chooser in place: the existing tags not already on it, each one press; × takes one off", async () => {
        vi.useFakeTimers();
        const { container } = render(<Attached />);
        fireEvent.click(screen.getByRole("button", { name: "Add a tag" }));
        expect(document.activeElement).toBe(container.querySelector('header input[type="search"]'));
        expect(Array.from(container.querySelectorAll("header .widget-adding .widget-pick"), (el) => el.textContent)).toEqual(["Needs service", "Loaner"]);
        fireEvent.click(screen.getByRole("button", { name: "Loaner" }));
        await act(async () => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        expect(Array.from(container.querySelectorAll("header .widget-tag"), (el) => el.firstChild?.textContent)).toEqual(["Cardio", "Loaner"]);
        // The added tag lands focus on its own ×.
        expect(document.activeElement).toBe(screen.getByRole("button", { name: "Remove tag Loaner" }));
        fireEvent.click(screen.getByRole("button", { name: "Remove tag Cardio" }));
        expect(Array.from(container.querySelectorAll("header .widget-tag"), (el) => el.firstChild?.textContent)).toEqual(["Loaner"]);
    });

    it("loading: still rows under each card's title; empty: the empty lines, each card's add at its foot", () => {
        const loading = render(<AttachLoading />);
        expect(loading.container.querySelectorAll('main section[aria-busy="true"], main section [aria-busy="true"]').length).toBeGreaterThanOrEqual(2);
        loading.unmount();
        const { container } = render(<NothingAttached />);
        expect(container.querySelector('section[aria-label="Notes"]')?.textContent).toContain("No notes yet.");
        expect(container.querySelector('section[aria-label="Files"]')?.textContent).toContain("No files yet.");
        expect(container.querySelectorAll("header .widget-tag")).toHaveLength(0);
    });

    it("refused: Couldn't add inside the Notes card above its foot, the server's sentence, Add a note alive", () => {
        const { container } = render(<RefusedAttach />);
        const alert = container.querySelector('[role="alert"]') as HTMLElement;
        expect(alert.getAttribute("data-seat")).toBe("card-foot");
        expect(alert.closest("section")?.getAttribute("aria-label")).toBe("Notes");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't add");
        expect(screen.getByRole("button", { name: "Add a note" })).toBeTruthy();
    });

    it("an archived row keeps its notes and tags and offers no act on them", () => {
        const archived = { ...archivedOf(ROWING), tags: [{ id: "t1", name: "Cardio", slug: "cardio", tenant_id: ROWING.tenant_id, created_at: ROWING.created_at, updated_at: ROWING.updated_at }] };
        const { container } = render(
            <WidgetRecord
                state={{ kind: "ready", data: archived }}
                attach={{
                    notes: { state: { kind: "empty" }, onAdd: async () => true },
                    tags: { choices: { kind: "empty" }, onAdd: async () => true, onRemove: () => undefined },
                }}
            />,
        );
        expect(container.querySelector("header .widget-tag")?.textContent).toBe("Cardio");
        expect(container.querySelectorAll('[data-act="attach"], .widget-tag-remove')).toHaveLength(0);
    });
});
