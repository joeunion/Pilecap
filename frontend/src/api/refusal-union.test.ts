/**
 * THE REFUSAL-UNION CENSUS — what the face draws for a refusal, held to what each door can answer.
 *
 * The door's union is its operation's `x-refusal-codes`, found in the document by `x-url-name`; a family is the registry's `boundary`.
 * does-not-cover: a code a story renders only after a press (the census reads the first paint), and a code a door answers only through middleware the document does not declare.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { cleanup, render } from "@testing-library/react";
import { createElement, type ComponentType } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { TRANSPORT_CODES } from "@/api/refusals";
import { ROUTE_TABLE, type RouteRow } from "@pilecap/ui/routes";
import { walkOf } from "@pilecap/ui/state";

afterEach(cleanup);

/** jsdom draws a <dialog> but implements neither showModal() nor close(); the sheet stories open one as they render. */
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

declare global {
    interface ImportMeta {
        glob<T>(pattern: string, options: { readonly eager: true }): Record<string, T>;
    }
}

type Operation = { readonly "x-url-name"?: string; readonly responses?: Readonly<Record<string, { readonly "x-refusal-codes"?: readonly string[] }>> };
type Document = { readonly paths: Readonly<Record<string, Readonly<Record<string, Operation | unknown>>>> };

/** Every bound operation's refusal union, by its `x-url-name`. */
function unionsOf(document: Document): ReadonlyMap<string, ReadonlySet<string>> {
    const out = new Map<string, Set<string>>();
    for (const methods of Object.values(document.paths)) {
        for (const operation of Object.values(methods)) {
            if (typeof operation !== "object" || operation === null) continue;
            const { "x-url-name": name, responses = {} } = operation as Operation;
            if (name === undefined) continue;
            const codes = out.get(name) ?? new Set<string>();
            for (const response of Object.values(responses)) for (const code of response["x-refusal-codes"] ?? []) codes.add(code);
            out.set(name, codes);
        }
    }
    return out;
}

const DOCUMENT = JSON.parse(readFileSync(resolve(process.cwd(), "openapi.json"), "utf8")) as Document;
const UNIONS = unionsOf(DOCUMENT);

/** The roots a refusal is registered under. */
const REGISTRY_ROOTS = ["apps", "config"] as const;

/** The registry's `boundary` per code, read from every `register_refusal(code=…, boundary=…)` under the registry's roots. */
function registryBoundaries(): ReadonlyMap<string, string> {
    const found = new Map<string, string>();
    const files = REGISTRY_ROOTS.flatMap((root) => {
        const base = resolve(process.cwd(), "..", root);
        return (readdirSync(base, { recursive: true }) as string[])
            .filter((file) => file.endsWith(".py") && !file.split(/[\\/]/).includes("tests"))
            .map((file) => join(base, file));
    });
    for (const file of files) {
        const source = readFileSync(file, "utf8");
        for (const match of source.matchAll(/register_refusal\(\s*code="([a-z_]+)",\s*boundary="([a-z]+)"/g)) {
            found.set(match[1] ?? "", match[2] ?? "");
        }
    }
    return found;
}

const BOUNDARIES = registryBoundaries();

/**
 * Which boundary families the panel answers in whatever seat the refusal lands, with no seat designed for one code.
 * A boundary the registry grows that is not a key here reds the census (the list is closed by the registry, never by this table).
 */
const FAMILY_HANDLING: Readonly<Record<string, "panel" | "per-code">> = {
    door: "panel",
    policy: "panel",
    selector: "panel",
    service: "per-code",
};

/**
 * The service codes a door answers that the face draws in the generic panel, with no story of their own — the backlog, named.
 * A code a door gains that is neither seated by a story nor named here reds the census.
 */
const PANEL_ONLY: Readonly<Record<string, readonly string[]>> = {
    "djb_import-apply": ["conflict"],
    "djb_note-create": ["conflict", "invalid"],
    "organization-list": ["invalid"],
    // golden: archive begin
    "widget-archive": ["conflict"],
    // golden: archive end
    // golden: bulk begin
    "widget-bulk": ["conflict", "invalid"],
    // golden: bulk end
    // golden: duplicate begin
    "widget-duplicate": ["archived", "conflict", "invalid", "merged"],
    // golden: duplicate end
    // golden: face begin
    "widget-list": ["invalid"],
    // golden: face end
    // golden: merge begin
    "widget-merge": ["archived", "conflict", "invalid", "merged", "stale_version"],
    // golden: merge end
    // golden: move begin
    "widget-move": ["archived", "conflict", "invalid", "stale_version"],
    // golden: move end
    // golden: archive begin
    "widget-restore": ["conflict"],
    // golden: archive end
    // golden: version begin
    "widget-update": ["archived", "conflict", "invalid"],
    // golden: version end
};

type StoryModule = Readonly<Record<string, unknown>>;
const STORY_MODULES = import.meta.glob<StoryModule>("../screens/**/*.stories.tsx", { eager: true });
const PAGES: readonly string[] = (readdirSync(resolve(process.cwd(), "src", "app"), { recursive: true }) as string[])
    .filter((file) => file.split(/[\\/]/).pop() === "page.tsx")
    .map((file) => `../app/${file.split(/[\\/]/).join("/")}`);

/** The page file a route row names, route groups (`(customer)`) read through. */
function pageOf(row: RouteRow): string | undefined {
    return PAGES.find((file) => {
        const path = file.replace(/^\.\.\/app/, "").replace(/\/\([^)]+\)/g, "").replace(/\/page\.tsx$/, "");
        return (path === "" ? "/" : path) === row.path;
    });
}

/** The stories modules a page draws: imported directly, or beside a screen module it imports. */
function storiesOf(page: string): readonly string[] {
    const source = readFileSync(resolve(process.cwd(), "src", page.replace(/^\.\.\//, "")), "utf8");
    const out = new Set<string>();
    for (const match of source.matchAll(/from "@\/(screens\/[^"]+)"/g)) {
        const screen = (match[1] ?? "").replace(/\.stories$/, "");
        const key = `../${screen}.stories.tsx`;
        if (key in STORY_MODULES) out.add(key);
    }
    return [...out];
}

/** One stories module, and the operation its stories answer by default — the row that draws its screen. */
type Screen = { readonly module: string; readonly operation: string | null; readonly rows: readonly string[] };

function screensOf(table: readonly RouteRow[]): readonly Screen[] {
    const byModule = new Map<string, { operations: Set<string>; rows: string[] }>();
    for (const row of table) {
        const page = pageOf(row);
        if (page === undefined) continue;
        for (const stories of storiesOf(page)) {
            const entry = byModule.get(stories) ?? { operations: new Set<string>(), rows: [] };
            if (row.operation !== null) entry.operations.add(row.operation);
            entry.rows.push(row.path);
            byModule.set(stories, entry);
        }
    }
    return [...byModule].map(([module, { operations, rows }]) => ({
        module,
        operation: operations.size === 1 ? ([...operations][0] ?? null) : null,
        rows,
    }));
}

/** A registry code one story renders, and the door its story says the refusal is the answer of. */
type Rendered = { readonly story: string; readonly code: string; readonly door: string | null };

const TRANSPORT = new Set<string>(TRANSPORT_CODES);

function renderedCodes(module: StoryModule, fallback: string | null): readonly Rendered[] {
    return walkOf(module).flatMap(({ name, Story, door }) => {
        const { container, unmount } = render(createElement(Story as ComponentType));
        const codes = Array.from(container.querySelectorAll('[role="alert"] code'), (el) => el.textContent ?? "");
        unmount();
        return [...new Set(codes)].filter((code) => !TRANSPORT.has(code)).map((code) => ({ story: name, code, door: door ?? fallback }));
    });
}

/** Each rendered code its door does not answer, as `<story>: <code> at <door>`. */
function outsideUnion(rendered: readonly Rendered[], unions: ReadonlyMap<string, ReadonlySet<string>>): readonly string[] {
    return rendered
        .filter(({ code, door }) => door === null || !(unions.get(door)?.has(code) ?? false))
        .map(({ story, code, door }) => `${story}: ${code} at ${door ?? "no door (the row draws none and the story names none)"}`);
}

/** Each code a door answers that has no handling: no story seats it, its family is not the panel's, and `PANEL_ONLY` does not name it. */
function unhandled(
    doors: ReadonlySet<string>,
    seated: ReadonlySet<string>,
    unions: ReadonlyMap<string, ReadonlySet<string>>,
    boundaries: ReadonlyMap<string, string>,
    panelOnly: Readonly<Record<string, readonly string[]>>,
): readonly string[] {
    const out: string[] = [];
    for (const door of [...doors].sort()) {
        for (const code of [...(unions.get(door) ?? [])].sort()) {
            if (seated.has(`${door} ${code}`)) continue;
            const family = boundaries.get(code);
            if (family !== undefined && FAMILY_HANDLING[family] === "panel") continue;
            if ((panelOnly[door] ?? []).includes(code)) continue;
            out.push(`${door}: ${code} (${family ?? "no boundary"})`);
        }
    }
    return out;
}

/** Each non-null `operation` in a table that is no operation's `x-url-name` in the document. */
function unknownOperations(table: readonly RouteRow[], unions: ReadonlyMap<string, ReadonlySet<string>>): readonly string[] {
    return table.filter((row) => row.operation !== null && !unions.has(row.operation)).map((row) => `${row.path}: ${row.operation}`);
}

const SCREENS = screensOf(ROUTE_TABLE);
const RENDERED = new Map(SCREENS.map((screen) => [screen.module, renderedCodesLazy(screen)]));

function renderedCodesLazy(screen: Screen): () => readonly Rendered[] {
    let memo: readonly Rendered[] | undefined;
    return () => (memo ??= renderedCodes(STORY_MODULES[screen.module] ?? {}, screen.operation));
}

describe("the census reads a real population", () => {
    it("the document publishes a refusal union for every bound operation it names", () => {
        expect(UNIONS.size).toBeGreaterThan(100);
        expect([...UNIONS.values()].every((codes) => codes.size > 0)).toBe(true);
    });

    it("every code any door answers has a boundary in the registry, and every boundary is a family this census handles", () => {
        const codes = new Set([...UNIONS.values()].flatMap((set) => [...set]));
        const missing = [...codes].filter((code) => !BOUNDARIES.has(code)).sort();
        expect(missing, "codes the document names that the registry read did not find").toEqual([]);
        const families = [...new Set(BOUNDARIES.values())].sort();
        expect(families.filter((family) => !(family in FAMILY_HANDLING)), "a boundary with no handling").toEqual([]);
    });

    it("every stories module the face draws is reached from a route-table row with one operation", () => {
        expect(SCREENS.length).toBeGreaterThan(0);
        expect(Object.keys(STORY_MODULES).filter((module) => !SCREENS.some((screen) => screen.module === module))).toEqual([]);
        for (const screen of SCREENS) expect(screen.operation, `${screen.module} (rows ${screen.rows.join(", ")})`).not.toBeNull();
    });
});

describe("the route table's operation column is the document's handle", () => {
    it("every row's operation is an operation's x-url-name", () => {
        expect(unknownOperations(ROUTE_TABLE, UNIONS)).toEqual([]);
    });

    it("a planted row naming no operation is named", () => {
        const plant: RouteRow = { path: "/planted", job: "Plant.", primarySeat: null, operation: "no-such-op", devOnly: true, surfaces: ["staff"] };
        expect(unknownOperations([...ROUTE_TABLE, plant], UNIONS)).toEqual(["/planted: no-such-op"]);
    });
});

describe.each(SCREENS.map((screen) => [screen.module, screen] as const))("%s", (module, screen) => {
    it("every code a story renders is one its door answers", () => {
        const rendered = RENDERED.get(module)?.() ?? [];
        expect(rendered.length, "a stories module whose stories render no refusal at all").toBeGreaterThan(0);
        for (const { door } of rendered) if (door !== null) expect(UNIONS.has(door), `door ${door}`).toBe(true);
        expect(outsideUnion(rendered, UNIONS)).toEqual([]);
    });

    it("every code its doors answer has a handling: a story's seat, the panel by family, or named panel-only", () => {
        const rendered = RENDERED.get(module)?.() ?? [];
        const doors = new Set([screen.operation, ...rendered.map(({ door }) => door)].filter((door): door is string => door !== null));
        const seated = new Set(rendered.flatMap(({ door, code }) => (door === null ? [] : [`${door} ${code}`])));
        expect(unhandled(doors, seated, UNIONS, BOUNDARIES, PANEL_ONLY)).toEqual([]);
    });
});

describe("the panel-only backlog only shrinks", () => {
    it("every panel-only line is a code its door answers that no story seats", () => {
        const seated = new Set(SCREENS.flatMap((screen) => (RENDERED.get(screen.module)?.() ?? []).flatMap(({ door, code }) => (door === null ? [] : [`${door} ${code}`]))));
        const stale = Object.entries(PANEL_ONLY).flatMap(([door, codes]) =>
            codes.filter((code) => !(UNIONS.get(door)?.has(code) ?? false) || seated.has(`${door} ${code}`)).map((code) => `${door}: ${code}`),
        );
        expect(stale).toEqual([]);
    });
});

describe("the census names what it is planted with", () => {
    it("a story code no door answers is named, with its story and its door", () => {
        const plant: Rendered = { story: "Planted", code: "zzz_probe", door: "widget-list" };
        expect(outsideUnion([plant], UNIONS)).toEqual(["Planted: zzz_probe at widget-list"]);
    });

    it("a service code a door answers with no seat and no panel-only line is named", () => {
        const unions = new Map([["widget-archive", new Set(["archive_blocked", "forbidden"])]]);
        expect(unhandled(new Set(["widget-archive"]), new Set(), unions, BOUNDARIES, {})).toEqual(["widget-archive: archive_blocked (service)"]);
        expect(unhandled(new Set(["widget-archive"]), new Set(["widget-archive archive_blocked"]), unions, BOUNDARIES, {})).toEqual([]);
    });
});
