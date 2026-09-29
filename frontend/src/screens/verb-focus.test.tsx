/**
 * THE FOCUS ROAD — focus lands where the next act is — read as `document.activeElement`
 * after each press, over the verb face census's population (every
 * `screens/<noun>/road.ts` and the stories beside it).
 *
 * * a leaving act lands on the way back (the band's *Restore*);
 * * the way back lands on the record's name (the `h1`, `tabindex=-1`);
 * * a refusal leaves focus on the pressed act, which stays drawn and alive;
 * * a cut row's *Restore* lands on the nearest remaining act: the next row's
 *   *Restore*, else the previous row's, else the empty line;
 * * *Show more* lands on the first new row;
 * * an act that opens a sheet lands on its first field (Move: its first
 *   choice); the sheet going down lands back on the opener — after a move, on
 *   the record's name, or on the band when the row moved out of sight;
 * * *Reload* after a lost race lands on the first field the re-read changed,
 *   and a dirty form's ask lands on *Keep editing*;
 * * a batch lands on the band's act, else on the first refused row's checkbox;
 * * *Show earlier* lands on the first new History row;
 * * *Duplicate* stands the face on the copy and lands on its name;
 * * *Merge* lands on the chooser's search; a pick opens the confirm on its
 *   question; Escape returns to the chooser; the merge lands on the
 *   survivor's name; a refused merge leaves focus on *Merge*, in the confirm;
 * * *Add a note* lands on its field, and the add on the new row;
 * * an import previewed lands on its counts line, the primary the next stop.
 *
 * jsdom proves where focus IS, not what a screen reader announces; that half
 * is the rendered drive's, and this file does not claim it.
 */

import { act, cleanup, fireEvent, render } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { Road } from "@/screens/verbs";
import type { WidgetPage } from "@/screens/widget/parts";
import { WidgetList } from "@/screens/widget/widget-list";
import { ARCHIVED_PAGE, LATENCY_MS } from "@/screens/widget/widget-list.stories";

declare global {
    interface ImportMeta {
        glob<T>(pattern: string, options: { readonly eager: true }): Record<string, T>;
    }
}

type StoryModule = Readonly<Record<string, unknown>>;

const ROADS = import.meta.glob<{ ROAD: Road }>("./*/road.ts", { eager: true });
const STORY_MODULES = import.meta.glob<StoryModule>("./*/*.stories.tsx", { eager: true });

beforeEach(() => {
    vi.useFakeTimers();
});

// jsdom draws a <dialog> but implements neither showModal() nor close(); the
// sheets open one, so both are stood in for here, around this file alone.
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

/** A press whose answer is a promise the fixtures' server settles after its wait. */
async function pressAndSettle(button: Element | null) {
    const el = button as HTMLButtonElement;
    el.focus();
    fireEvent.click(el);
    await act(async () => {
        vi.advanceTimersByTime(LATENCY_MS);
    });
}

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

function nounOf(path: string): string {
    return path.split("/")[1] ?? "";
}

/** The one module of this noun that exports `name` and draws `probe`; the census says which modules owe it. */
function story(noun: string, name: string, probe: string): ComponentType {
    for (const [path, module] of Object.entries(STORY_MODULES)) {
        const Story = module[name];
        if (nounOf(path) !== noun || typeof Story !== "function") continue;
        const Component = Story as ComponentType;
        const { container, unmount } = render(<Component />);
        const found = container.querySelector(probe) !== null;
        unmount();
        if (found) return Component;
    }
    throw new Error(`${noun}: no ${name} story draws ${probe}`);
}

function press(button: Element | null) {
    const el = button as HTMLButtonElement;
    el.focus();
    fireEvent.click(el);
    act(() => {
        vi.advanceTimersByTime(LATENCY_MS);
    });
}

const archiving = Object.entries(ROADS)
    .map(([path, module]) => ({ noun: nounOf(path), road: module.ROAD }))
    .filter(({ road }) => road.verbs.includes("archive") && road.verbs.includes("restore"));

describe("the census's population", () => {
    it("finds the roads that carry the archive road", () => {
        expect(archiving.map(({ noun }) => noun)).toContain("widget");
    });
});

describe.each(archiving)("the $noun face's focus road", ({ noun, road }) => {
    it("Archive lands on the band's Restore; Restore lands on the record's name", () => {
        const Admin = story(noun, "PopulatedAdmin", `[data-seat="${road.seat}"] [data-act="archive"]`);
        const { container } = render(<Admin />);
        press(container.querySelector('[data-act="archive"]'));
        const wayBack = container.querySelector('[data-band] [data-act="restore"]');
        expect(wayBack).not.toBeNull();
        expect(document.activeElement).toBe(wayBack);
        press(wayBack);
        const name = container.querySelector("h1");
        expect(name?.getAttribute("tabindex")).toBe("-1");
        expect(document.activeElement).toBe(name);
    });

    it("a refused Archive leaves focus on Archive, drawn and alive", () => {
        const Refused = story(noun, "RefusedArchive", '[data-act="archive"]');
        const { container } = render(<Refused />);
        const archive = container.querySelector('[data-act="archive"]');
        press(archive);
        expect(container.querySelector('[role="alert"]')).not.toBeNull();
        expect(document.activeElement).toBe(archive);
        expect(archive?.isConnected).toBe(true);
    });

    it("a refused Restore under the band leaves focus on Restore", () => {
        const Refused = story(noun, "RefusedRestore", '[data-band] [data-act="restore"]');
        const { container } = render(<Refused />);
        const restore = container.querySelector('[data-band] [data-act="restore"]');
        press(restore);
        expect(document.activeElement).toBe(restore);
    });

    it("a cut row's Restore lands on the next row's Restore", () => {
        const Cut = story(noun, "Archived", "li [data-act=\"restore\"]");
        const { container } = render(<Cut />);
        const [first] = Array.from(container.querySelectorAll('li [data-act="restore"]'));
        press(first ?? null);
        const [next] = Array.from(container.querySelectorAll('li [data-act="restore"]'));
        expect(next).not.toBeUndefined();
        expect(next).not.toBe(first);
        expect(document.activeElement).toBe(next);
    });

    it("a page that has more: Show more lands on the first new row", () => {
        const More = story(noun, "HasMore", '[data-weight="secondary"]');
        const { container } = render(<More />);
        const before = container.querySelectorAll("ul > li").length;
        press(container.querySelector('[data-weight="secondary"]'));
        const rows = container.querySelectorAll("ul > li > a");
        expect(rows.length).toBeGreaterThan(before);
        expect(document.activeElement).toBe(rows[before]);
    });
});

describe("the last row restored out of the cut", () => {
    it("lands on the empty line", () => {
        const one: WidgetPage = { ...ARCHIVED_PAGE, items: ARCHIVED_PAGE.items.slice(0, 1) };
        const restore = { onRestore: () => undefined };
        const { container, rerender } = render(<WidgetList state={{ kind: "ready", data: one }} cut="archived" restore={restore} />);
        const button = container.querySelector('[data-act="restore"]') as HTMLButtonElement;
        button.focus();
        fireEvent.click(button);
        rerender(<WidgetList state={{ kind: "empty" }} cut="archived" restore={restore} />);
        const line = container.querySelector("main > p");
        expect(line?.textContent).toBe("Nothing archived.");
        expect(document.activeElement).toBe(line);
    });
});

const roads = Object.entries(ROADS).map(([path, module]) => ({ noun: nounOf(path), road: module.ROAD }));

describe.each(roads.filter(({ road }) => road.verbs.includes("update")))("the $noun face's edit road", ({ noun }) => {
    it("Edit lands on the sheet's first field; the sheet going down lands back on Edit", async () => {
        const Admin = story(noun, "PopulatedAdmin", '[data-seat="record-acts"] [data-act="update"]');
        const { container } = render(<Admin />);
        const edit = container.querySelector('[data-seat="record-acts"] [data-act="update"]');
        press(edit);
        const first = container.querySelector("dialog[open] input, dialog[open] textarea");
        expect(first).not.toBeNull();
        expect(document.activeElement).toBe(first);
        fireEvent.change(first as HTMLInputElement, { target: { value: "Rowing machine, the good one" } });
        await pressAndSettle(container.querySelector('dialog[open] [data-act="update"]'));
        expect(container.querySelector("dialog")).toBeNull();
        expect(document.activeElement).toBe(container.querySelector('[data-seat="record-acts"] [data-act="update"]'));
    });

    it("a lost race: Reload lands on the first field the re-read changed; a dirty form asks first, on Keep editing", async () => {
        const Stale = story(noun, "Stale", 'dialog [data-destination="self:reread"]');
        const { container } = render(<Stale />);
        const reload = () => container.querySelector('dialog [role="alert"]')?.parentElement?.querySelector('button[data-weight="secondary"]') ?? null;
        const [name] = Array.from(container.querySelectorAll("dialog input, dialog textarea"));
        fireEvent.change(name as HTMLInputElement, { target: { value: "A name nobody saved" } });
        press(reload());
        const keep = container.querySelector("dialog p + button");
        expect(document.activeElement).toBe(keep);
        // Discard is the ask's second act: the re-read answers, and the draft is the row.
        await pressAndSettle(keep?.nextElementSibling ?? null);
        const fields = Array.from(container.querySelectorAll("dialog input, dialog textarea")) as (HTMLInputElement | HTMLTextAreaElement)[];
        const changed = fields.find((field) => field.tagName === "TEXTAREA");
        expect(document.activeElement).toBe(changed);
        expect(container.querySelector('dialog [role="alert"]')).toBeNull();
    });
});

describe.each(roads.filter(({ road }) => road.verbs.includes("move")))("the $noun face's move road", ({ noun }) => {
    it("Move lands on the sheet's first choice; the answer lands on the record's name", async () => {
        const Admin = story(noun, "PopulatedAdmin", '[data-seat="record-acts"] [data-act="move"]');
        const { container } = render(<Admin />);
        press(container.querySelector('[data-seat="record-acts"] [data-act="move"]'));
        const choices = Array.from(container.querySelectorAll('dialog[open] input[type="radio"]'));
        expect(choices.length).toBeGreaterThan(1);
        expect(document.activeElement).toBe(choices[0]);
        fireEvent.click(choices[1] as HTMLInputElement);
        await pressAndSettle(container.querySelector('dialog[open] [data-act="move"]'));
        expect(container.querySelector("dialog")).toBeNull();
        expect(document.activeElement).toBe(container.querySelector("h1"));
    });

    it("a refused move leaves focus on Move, in the sheet, alive", async () => {
        const Refused = story(noun, "RefusedMove", 'dialog [data-act="move"]');
        const { container } = render(<Refused />);
        const move = container.querySelector('dialog [data-act="move"]');
        await pressAndSettle(move);
        expect(container.querySelectorAll('dialog [role="alert"]')).toHaveLength(1);
        expect(document.activeElement).toBe(move);
    });
});

describe.each(roads.filter(({ road }) => (road.bulk ?? []).includes("archive")))("the $noun face's bulk road", ({ noun }) => {
    it("a batch lands on the band's act; with a row refused, the refused row stays checked", () => {
        const Selected = story(noun, "Selected", '[data-seat="list-select"] [data-act="archive"]');
        const { container } = render(<Selected />);
        press(container.querySelector('[data-seat="list-select"] [data-act="archive"]'));
        const band = container.querySelector('[data-band="bulk"]');
        expect(band).not.toBeNull();
        expect(document.activeElement).toBe(band?.querySelector("button"));
    });

    it("a batch with every row refused lands on the first refused row's checkbox", () => {
        const Partial = story(noun, "BulkPartial", '[data-seat="list-select"] [data-act="archive"]');
        const { container } = render(<Partial />);
        press(container.querySelector('[data-seat="list-select"] [data-act="archive"]'));
        const first = container.querySelector('li [role="alert"]')?.closest("li")?.querySelector('input[type="checkbox"]');
        expect(first).not.toBeNull();
        expect(document.activeElement).toBe(first);
    });
});

describe.each(roads.filter(({ road }) => road.verbs.includes("history")))("the $noun face's History card", ({ noun }) => {
    it("Show earlier lands on the first new row", () => {
        const History = story(noun, "History", 'section[aria-label="History"] [data-weight="secondary"]');
        const { container } = render(<History />);
        const card = () => container.querySelector('section[aria-label="History"]');
        const before = card()?.querySelectorAll("li").length ?? 0;
        press(card()?.querySelector('[data-weight="secondary"]') ?? null);
        const rows = card()?.querySelectorAll("li") ?? [];
        expect(rows.length).toBeGreaterThan(before);
        expect(document.activeElement).toBe(rows[before]);
    });
});

describe.each(roads.filter(({ road }) => road.verbs.includes("duplicate")))("the $noun face's duplicate road", ({ noun }) => {
    it("Duplicate lands on the copy's name", () => {
        const Admin = story(noun, "PopulatedAdmin", '[data-seat="record-acts"] [data-act="duplicate"]');
        const { container } = render(<Admin />);
        const before = container.querySelector("h1")?.textContent;
        press(container.querySelector('[data-seat="record-acts"] [data-act="duplicate"]'));
        const name = container.querySelector("h1");
        expect(name?.textContent).not.toBe(before);
        expect(document.activeElement).toBe(name);
    });

    it("a refused Duplicate leaves focus on Duplicate, drawn and alive", () => {
        const Refused = story(noun, "RefusedDuplicate", '[data-seat="record-acts"] [data-act="duplicate"]');
        const { container } = render(<Refused />);
        const duplicate = container.querySelector('[data-seat="record-acts"] [data-act="duplicate"]');
        press(duplicate);
        expect(container.querySelectorAll('[role="alert"]')).toHaveLength(1);
        expect(document.activeElement).toBe(duplicate);
    });
});

describe.each(roads.filter(({ road }) => road.verbs.includes("merge")))("the $noun face's merge road", ({ noun }) => {
    it("Merge lands on the chooser's search; a pick lands on the confirm's question; Escape back to the chooser; the merge on the survivor's name", async () => {
        const Admin = story(noun, "PopulatedAdmin", '[data-seat="record-acts"] [data-act="merge"]');
        const { container } = render(<Admin />);
        press(container.querySelector('[data-seat="record-acts"] [data-act="merge"]'));
        expect(document.activeElement).toBe(container.querySelector('dialog[open] input[type="search"]'));
        const pick = () => fireEvent.click(container.querySelector("dialog[open] .widget-pick") as HTMLButtonElement);
        pick();
        expect(document.activeElement).toBe(container.querySelector("dialog[open] h2"));
        fireEvent(container.querySelector("dialog[open]") as HTMLDialogElement, new Event("cancel", { cancelable: true }));
        expect(container.querySelector('dialog[open] input[type="search"]')).not.toBeNull();
        pick();
        await pressAndSettle(container.querySelector('dialog[open] footer [data-act="merge"]'));
        expect(container.querySelector("dialog")).toBeNull();
        expect(document.activeElement).toBe(container.querySelector("h1"));
    });

    it("a refused merge leaves focus on Merge, in the confirm, alive", async () => {
        const Refused = story(noun, "RefusedMerge", 'dialog footer [data-act="merge"]');
        const { container } = render(<Refused />);
        const merge = container.querySelector('dialog footer [data-act="merge"]');
        await pressAndSettle(merge);
        expect(container.querySelectorAll('dialog [role="alert"]')).toHaveLength(1);
        expect(document.activeElement).toBe(merge);
    });
});

describe.each(roads.filter(({ road }) => road.verbs.includes("attach")))("the $noun face's attach road", ({ noun }) => {
    it("Add a note lands on its field; the add lands on the new row", async () => {
        const Attached = story(noun, "Attached", '[data-act="attach"]');
        const { container } = render(<Attached />);
        const note = Array.from(container.querySelectorAll('[data-act="attach"]')).find((el) => el.closest("section")?.querySelector("textarea") === null && el.closest("section") !== null);
        press(note ?? null);
        const field = container.querySelector("section textarea") as HTMLTextAreaElement;
        expect(document.activeElement).toBe(field);
        fireEvent.change(field, { target: { value: "A new note." } });
        await pressAndSettle(field.closest("section")?.querySelector('[data-weight="primary"]') ?? null);
        expect(document.activeElement).toBe(field.closest("section")?.querySelector("li") ?? container.querySelector("section li"));
    });
});

describe.each(roads.filter(({ road }) => road.verbs.includes("import")))("the $noun face's import road", ({ noun }) => {
    it("Import on a chosen file: Checking…, then the preview lands on the counts line", () => {
        const Choose = story(noun, "RefusedImport", '[data-act="import"]');
        const { container } = render(<Choose />);
        const field = container.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(field, { target: { files: [new File(["external_ref,name,notes"], "widgets.csv", { type: "text/csv" })] } });
        const stage = container.querySelector('[data-act="import"]') as HTMLButtonElement;
        stage.focus();
        fireEvent.click(stage);
        expect(stage.textContent).toBe("Checking…");
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        const counts = container.querySelector("[tabindex='-1']");
        expect(counts?.textContent).toMatch(/new · .* refused$/);
        expect(document.activeElement).toBe(counts);
    });
});
