import { describe, expect, it } from "vitest";

import { offSurface, pathFor, ROUTE_TABLE, rowFor, routesOn, type RouteRow, STAFF_SURFACE } from "@/kit/routes";

/** A page every surface draws, beside the real rows. */
const EVERYWHERE: RouteRow = {
    path: "/help",
    job: "Say how to reach a person.",
    primarySeat: null,
    operation: null,
    devOnly: false,
    surfaces: "*",
};
/** A customer-only page — the shape a product's customer face adds. */
const PORTAL: RouteRow = {
    path: "/portal/widgets",
    job: "List the widgets a customer may read.",
    primarySeat: null,
    operation: "widget-list",
    devOnly: false,
    surfaces: ["customer"],
};
/** The rows no customer page is on — the table as it stood before a customer face was drawn. */
const STAFF_ROWS: readonly RouteRow[] = ROUTE_TABLE.filter((row) => row.surfaces === "*" || !row.surfaces.includes("customer"));
const WITH_BOTH: readonly RouteRow[] = [...STAFF_ROWS, EVERYWHERE, PORTAL];
/** Every surface key a row of the table names, read off the table. */
const SURFACE_KEYS: readonly string[] = [...new Set(ROUTE_TABLE.flatMap((row) => (row.surfaces === "*" ? [] : row.surfaces)))];

/** A dynamic segment filled with a value no row path spells, so the matcher is what is tested. */
function concrete(path: string): string {
    return path.replace(/\[[^\]]+\]/g, "a-value");
}

describe("every row names its audience", () => {
    it.each(ROUTE_TABLE.map((row) => [row.path, row] as const))("%s names the surfaces it is for", (_path, row) => {
        expect(row.surfaces === "*" || row.surfaces.length > 0).toBe(true);
    });
});

describe("before the answer, every reader answers the whole table", () => {
    it("routesOn(undefined) is the whole table, in order", () => {
        expect(routesOn(undefined)).toEqual(ROUTE_TABLE);
        expect(SURFACE_KEYS.length).toBeGreaterThan(1);
        expect(routesOn(undefined, WITH_BOTH)).toEqual(WITH_BOTH);
    });

    it.each(ROUTE_TABLE.map((row) => [row.path] as const))("%s is never refused before the answer", (path) => {
        expect(offSurface(concrete(path), undefined)).toBe(false);
    });

    it.each(ROUTE_TABLE.filter((row) => row.operation !== null).map((row) => [row.operation ?? ""] as const))(
        "pathFor(%s) before the answer is the first row that draws it, a walk yielding to a product row beside it",
        (operation) => {
            const drawn = ROUTE_TABLE.filter((row) => row.operation === operation);
            const first = drawn[0];
            const audience = (row: RouteRow) => (row.surfaces === "*" ? SURFACE_KEYS : row.surfaces);
            const product = first?.path.startsWith("/example/")
                ? drawn.find((row) => !row.path.startsWith("/example/") && audience(row).some((key) => audience(first).includes(key)))
                : undefined;
            expect(pathFor(operation, { id: "a-value" }, ROUTE_TABLE, undefined)).toBe(concrete((product ?? first)?.path ?? ""));
        },
    );
});

/** A product's own staff page for the worked list's operation — the row `scaffold screen` writes beside the walk. */
const PRODUCT: RouteRow = {
    path: "/stock",
    job: "List the widgets in stock.",
    primarySeat: null,
    operation: "widget-list",
    devOnly: false,
    surfaces: ["staff"],
};
const WITH_PRODUCT: readonly RouteRow[] = [...ROUTE_TABLE, PRODUCT];

/** The staff row a reader must answer for `operation`: a page of the product's own before a walk (`/example/`). */
function staffRowOf(operation: string, table: readonly RouteRow[]): RouteRow | undefined {
    const drawn = table.filter((row) => row.operation === operation && row.surfaces !== "*" && row.surfaces.includes(STAFF_SURFACE));
    return drawn.find((row) => !row.path.startsWith("/example/")) ?? drawn[0];
}

describe.each([
    ["the tip's table", ROUTE_TABLE],
    ["the table with a product row beside the walk", WITH_PRODUCT],
] as const)("a screen that names its surface reads its own row, wherever %s puts it", (_name, table) => {
    // The table turned over puts the customer rows first: a reader handed no
    // surface would now answer a customer page to a staff screen.
    const OVER: readonly RouteRow[] = [...table].reverse();

    it.each(
        table
            .filter((row) => row.operation !== null && row.surfaces !== "*" && row.surfaces.includes(STAFF_SURFACE))
            .map((row) => [row.operation ?? "", staffRowOf(row.operation ?? "", table)?.path ?? ""] as const),
    )("pathFor(%s, STAFF_SURFACE) is %s in either order", (operation, path) => {
        expect(pathFor(operation, { id: "a-value" }, OVER, STAFF_SURFACE)).toBe(concrete(path));
        expect(pathFor(operation, { id: "a-value" }, table, STAFF_SURFACE)).toBe(concrete(path));
    });
});

describe("a page of the product's own and a walk drawing one operation on one surface", () => {
    it("prefers the product row over the walk row", () => {
        expect(pathFor("widget-list", {}, WITH_PRODUCT, STAFF_SURFACE)).toBe(PRODUCT.path);
        expect(pathFor("widget-list", {}, [...WITH_PRODUCT].reverse(), STAFF_SURFACE)).toBe(PRODUCT.path);
        expect(rowFor("widget-list", WITH_PRODUCT, STAFF_SURFACE)).toBe(PRODUCT);
    });

    it("a walk still answers where no product row shares its surface", () => {
        expect(pathFor("widget-list", {}, ROUTE_TABLE, STAFF_SURFACE)).toBe("/example/widgets");
        expect(pathFor("widget-list", {}, WITH_PRODUCT, "customer")).toBe("/widgets");
        expect(pathFor("widget-list", {}, WITH_PRODUCT, undefined)).toBe(PRODUCT.path);
    });
});

describe("each row, on each surface", () => {
    it.each(ROUTE_TABLE.map((row) => [row.path, row] as const))("%s is drawn on the surfaces it names and no other", (path, row) => {
        const named = row.surfaces === "*" ? [] : row.surfaces;
        for (const surface of named) {
            expect(routesOn(surface)).toContain(row);
            expect(offSurface(concrete(path), surface)).toBe(false);
        }
        for (const other of SURFACE_KEYS.filter((key) => !named.includes(key))) {
            expect(routesOn(other)).not.toContain(row);
            expect(offSurface(concrete(path), other)).toBe(true);
        }
    });

    it("a \"*\" row is on both surfaces", () => {
        expect(routesOn("staff", WITH_BOTH)).toContain(EVERYWHERE);
        expect(routesOn("customer", WITH_BOTH)).toContain(EVERYWHERE);
        expect(offSurface(EVERYWHERE.path, "staff", WITH_BOTH)).toBe(false);
        expect(offSurface(EVERYWHERE.path, "customer", WITH_BOTH)).toBe(false);
    });

    it("a [\"customer\"] row is absent on staff", () => {
        expect(routesOn("staff", WITH_BOTH)).not.toContain(PORTAL);
        expect(offSurface(PORTAL.path, "staff", WITH_BOTH)).toBe(true);
        expect(routesOn("customer", WITH_BOTH)).toContain(PORTAL);
        expect(offSurface(PORTAL.path, "customer", WITH_BOTH)).toBe(false);
    });

    it("two rows drawing one operation: each surface's door is its own page", () => {
        expect(pathFor("widget-list", {}, WITH_BOTH, "staff")).toBe("/example/widgets");
        expect(pathFor("widget-list", {}, WITH_BOTH, "customer")).toBe(PORTAL.path);
    });
});

describe("the tip's table on a customer surface", () => {
    it("draws only the pages whose row names it — the worked customer face's", () => {
        const named = ROUTE_TABLE.filter((row) => row.surfaces !== "*" && row.surfaces.includes("customer"));
        expect(named.length).toBeGreaterThan(0);
        expect(routesOn("customer")).toEqual(named);
    });

    it("spells no door: pathFor(organization-list) is no page", () => {
        expect(pathFor("organization-list", {}, ROUTE_TABLE, "customer")).toBeNull();
    });

    it("refuses /welcome, where staff does not", () => {
        expect(offSurface("/welcome", "customer", ROUTE_TABLE)).toBe(true);
        expect(offSurface("/welcome", "staff", ROUTE_TABLE)).toBe(false);
        expect(offSurface("/welcome", undefined, ROUTE_TABLE)).toBe(false);
    });

    it("an operation no row draws is no page on any surface", () => {
        expect(pathFor("notes-list", {}, ROUTE_TABLE, undefined)).toBeNull();
        expect(pathFor("notes-list", {}, ROUTE_TABLE, "staff")).toBeNull();
        expect(pathFor("notes-list", {}, ROUTE_TABLE, "customer")).toBeNull();
    });
});

describe("the guard's matcher", () => {
    it("a path no row draws is left to the router's own 404", () => {
        expect(offSurface("/nowhere", "customer")).toBe(false);
    });

    it("a static path outranks a dynamic one it also matches", () => {
        const table: readonly RouteRow[] = ROUTE_TABLE.map((row) =>
            row.path === "/example/widgets/[id]" ? { ...row, surfaces: ["customer"] } : row,
        );
        expect(offSurface("/example/widgets/import", "customer", table)).toBe(true);
        expect(offSurface("/example/widgets/some-id", "customer", table)).toBe(false);
        expect(offSurface("/example/widgets/some-id/", "customer", table)).toBe(false);
    });
});
