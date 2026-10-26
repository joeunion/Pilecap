import { act, render } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import WidgetRecordExamplePage from "@/app/example/widgets/[id]/page";
import WidgetImportExamplePage from "@/app/example/widgets/import/page";
import WidgetListExamplePage from "@/app/example/widgets/page";
import { WIDGET_COPY } from "@/copy/widget";
import { REQUIRED_STORY_EXPORTS } from "@pilecap/ui/state";
import * as importStories from "@/screens/widget/widget-import.stories";
import * as listStories from "@/screens/widget/widget-list.stories";
import * as recordStories from "@/screens/widget/widget-record.stories";

vi.mock("next/navigation", () => ({
    notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
    },
    // The list walk hands its router to the stories (a press that lands on another page).
    useRouter: () => ({ push: () => undefined }),
}));

/** The browser's socket, stood in for: the list walk's board dials it, and nothing here reaches a network. */
class StandIn {
    static made: StandIn[] = [];
    onopen: (() => void) | null = null;
    onmessage: (() => void) | null = null;
    onclose: (() => void) | null = null;
    constructor(readonly url: string) {
        StandIn.made.push(this);
    }
    close(): void {}
}

beforeEach(() => {
    vi.stubGlobal("WebSocket", StandIn);
});

afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    StandIn.made = [];
});

// jsdom draws a <dialog> but implements neither showModal() nor close(): the
// sheet stories open one as they render, so both are stood in for here.
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

/** The walks, as the router calls them: the record's reads its search params (a promise), the list's none. */
const PAGES = {
    list: async () => WidgetListExamplePage(),
    import: async () => WidgetImportExamplePage(),
    record: async (story?: string) =>
        WidgetRecordExamplePage(story === undefined ? {} : { searchParams: Promise.resolve({ story }) }),
};

/**
 * A module's stories, read off its exports by their shape alone — a function
 * named in PascalCase (the fixtures are SHOUTED, the helpers camel-cased) —
 * never through the page's own reader, so the page and this census cannot
 * agree by sharing a mistake.
 */
function storiesOf(module: Readonly<Record<string, unknown>>): { readonly walked: string[]; readonly alone: string[] } {
    const names = Object.entries(module)
        .filter(([name, value]) => typeof value === "function" && /^[A-Z][a-z]/.test(name))
        .map(([name]) => name);
    const isAlone = (name: string) => (module[name] as { readonly alone?: unknown }).alone === true;
    return { walked: names.filter((name) => !isAlone(name)), alone: names.filter(isAlone) };
}

function labelled(container: HTMLElement): (string | null)[] {
    return Array.from(container.querySelectorAll("[data-story]"), (el) => el.getAttribute("data-story"));
}

describe.each([
    ["/example/widgets", PAGES.list, storiesOf(listStories)],
    ["/example/widgets/import", PAGES.import, storiesOf(importStories)],
    ["/example/widgets/[id]", PAGES.record, storiesOf(recordStories)],
])("%s, the dev-only walk", (_route, Page, { walked, alone }) => {
    it("renders every exported story not marked alone, labelled — the four first", async () => {
        const { container } = render(await Page());
        const drawn = labelled(container);
        expect([...drawn].sort()).toEqual([...walked].sort());
        expect(drawn.slice(0, REQUIRED_STORY_EXPORTS.length)).toEqual([...REQUIRED_STORY_EXPORTS]);
    });

    it("walks every exported story somewhere: the default walk and the alone ones are the module's exports", async () => {
        const { container } = render(await Page());
        const drawn = new Set(labelled(container));
        const everywhere = [...drawn, ...alone].sort();
        expect(everywhere).toEqual([...walked, ...alone].sort());
    });

    it("is a 404 in a production build", async () => {
        vi.stubEnv("NODE_ENV", "production");
        await expect(Page()).rejects.toThrow("NEXT_NOT_FOUND");
    });
});

describe("the record walk's alone stories, one at a time", () => {
    const { alone } = storiesOf(recordStories);

    it("the record's stories mark at least the sheets as alone", () => {
        expect(alone.length).toBeGreaterThan(0);
    });

    it.each(alone)("?story=%s draws that story alone, and no other", async (story) => {
        const { container } = render(await PAGES.record(story));
        expect(labelled(container)).toEqual([story]);
        expect(container.querySelectorAll("dialog[open]").length).toBeLessThanOrEqual(1);
    });

    it.each(["Stale", "RefusedUpdate", "RefusedMove", "NowhereToMove", "MergeChoosing", "RefusedMerge"])("?story=%s draws its sheet up", async (story) => {
        const { container } = render(await PAGES.record(story));
        expect(container.querySelectorAll("dialog[open]")).toHaveLength(1);
    });

    it("a story it does not know draws the whole walk, never nothing", async () => {
        const { container } = render(await PAGES.record("NoSuchStory"));
        expect(container.querySelectorAll("[data-story]").length).toBeGreaterThan(1);
        expect(container.querySelectorAll("dialog")).toHaveLength(0);
    });
});

describe("the document title", () => {
    it("names the page's noun on both routes, not the landing's", async () => {
        const list = await import("@/app/example/widgets/page");
        const record = await import("@/app/example/widgets/[id]/page");
        expect(list.metadata.title).toBe(WIDGET_COPY.title);
        expect(record.metadata.title).toBe(WIDGET_COPY.title);
        const page = await import("@/app/example/widgets/import/page");
        expect(page.metadata.title).toBe("Import widgets");
    });
});

describe("/example/widgets, the worked live board", () => {
    it("dials the tenant's socket through the kit's hook and says data-board=live once it opens", async () => {
        const { container } = render(await PAGES.list());
        const board = () => container.querySelector("[data-board]")?.getAttribute("data-board");
        expect(board()).toBe("connecting");
        expect(StandIn.made.map((socket) => new URL(socket.url).pathname)).toEqual(["/ws/events/"]);
        act(() => StandIn.made[0]?.onopen?.());
        expect(board()).toBe("live");
    });
});
