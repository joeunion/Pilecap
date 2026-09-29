import { render } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import WidgetRecordExamplePage from "@/app/example/widgets/[id]/page";
import WidgetImportExamplePage from "@/app/example/widgets/import/page";
import WidgetListExamplePage from "@/app/example/widgets/page";
import { WIDGET_COPY } from "@/copy/widget";
import { REQUIRED_STORY_EXPORTS } from "@/screens/state";

vi.mock("next/navigation", () => ({
    notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
    },
    // The list walk hands its router to the stories (a press that lands on another page).
    useRouter: () => ({ push: () => undefined }),
}));

afterEach(() => {
    vi.unstubAllEnvs();
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

describe.each([
    [
        "/example/widgets",
        PAGES.list,
        [...REQUIRED_STORY_EXPORTS, "HasMore", "LongName", "Archived", "ArchivedLoading", "NothingArchived", "RefusedRestore", "Selected", "RefusedBulk", "BulkPartial", "ImportInFlight"],
    ],
    [
        "/example/widgets/import",
        PAGES.import,
        [...REQUIRED_STORY_EXPORTS, "ImportChecking", "ImportPreviewed", "Importing", "Imported", "ImportRepeated", "NothingToImport", "RefusedImport"],
    ],
    [
        "/example/widgets/[id]",
        PAGES.record,
        [
            ...REQUIRED_STORY_EXPORTS,
            "Resting",
            "PopulatedAdmin",
            "PopulatedMember",
            "Archived",
            "RefusedArchive",
            "RefusedRestore",
            "ActsAfterFrame",
            "Moved",
            "Duplicated",
            "RefusedDuplicate",
            "Merged",
            "History",
            "HistoryLoading",
            "HistoryEmpty",
            "RefusedHistory",
            "Attached",
            "AttachedMember",
            "AttachLoading",
            "NothingAttached",
            "RefusedAttach",
        ],
    ],
])("%s, the dev-only walk", (_route, Page, walked) => {
    it("renders every authored story in development, labelled", async () => {
        const { container } = render(await Page());
        const labelled = Array.from(container.querySelectorAll("[data-story]"), (el) => el.getAttribute("data-story"));
        expect(labelled).toEqual(walked);
    });

    it("is a 404 in a production build", async () => {
        vi.stubEnv("NODE_ENV", "production");
        await expect(Page()).rejects.toThrow("NEXT_NOT_FOUND");
    });
});

describe("the record walk's sheet stories, one at a time", () => {
    it.each(["Stale", "RefusedUpdate", "RefusedMove", "NowhereToMove", "MergeChoosing", "RefusedMerge"])("?story=%s draws that story alone, its sheet up", async (story) => {
        const { container } = render(await PAGES.record(story));
        const labelled = Array.from(container.querySelectorAll("[data-story]"), (el) => el.getAttribute("data-story"));
        expect(labelled).toEqual([story]);
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
