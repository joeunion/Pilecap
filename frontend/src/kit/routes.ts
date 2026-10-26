// patterns: §0
/**
 * THE ROUTE TABLE — the head of the book (patterns.md §0; house rule 71).
 *
 * The app router discovers a route from a file, so a page can land with
 * nobody having said what it is FOR. This table is where each one says it:
 * its one job, where its primary act sits, and the operation it draws. Every
 * surface that needs "which page draws this" — a nav, a remedy's link — reads
 * THIS table, never a list of its own.
 *
 * House rule 71 censuses it against `src/app/**\/page.tsx` in both directions:
 * a page with no row, and a row with no page, are both red. A row is data, not
 * copy — nothing here is rendered, so its words are the book's, not a face's.
 *
 * THE COLUMNS, each an answer (`null` is an answer, never an omission):
 * `path` · `job` (one sentence) · `primarySeat` (where the one primary act
 * sits, or `null` when the route offers none) · `operation` (the url name of
 * the list or detail operation the route draws, or `null` when it draws none) ·
 * `devOnly` (`true` when the page is a 404 in a production build, like the
 * state walks; a remedy never links to such a page in production) ·
 * `surfaces` (the keys of the surfaces whose audience the page is for, or
 * `"*"` for a page every surface draws — a surface is a host and the audience
 * it serves, and the face asks the server which one it is, `@/api/surface`).
 *
 * ONE TABLE FOR EVERY SURFACE. The face is one application whatever host it is
 * served at; which of its pages a host draws is this column, read against the
 * surface the server named. The readers below take that surface as an
 * ARGUMENT and hold none: before the answer they are handed `undefined` and
 * answer the whole table, which is what a product that declares no surface
 * draws, so the first render never waits and never differs.
 */

export type RouteRow = {
    readonly path: string;
    readonly job: string;
    readonly primarySeat: string | null;
    readonly operation: string | null;
    readonly devOnly: boolean;
    readonly surfaces: readonly string[] | "*";
};

export const ROUTE_TABLE: readonly RouteRow[] = [
    {
        path: "/welcome",
        job: "Land after sign-in and show which part of the tree the acting hat can see.",
        primarySeat: null,
        operation: "organization-list",
        devOnly: false,
        surfaces: ["staff"],
    },
    {
        path: "/states",
        job: "Render every authored state of the one screen, for the rendered drive; a 404 in production.",
        primarySeat: null,
        operation: null,
        devOnly: true,
        surfaces: ["staff"],
    },
    // golden: face begin
    {
        path: "/example/widgets",
        job: "Walk every state of the worked widget list, the example a product copies; a 404 in production.",
        primarySeat: null,
        operation: "widget-list",
        devOnly: true,
        surfaces: ["staff"],
    },
    // golden: face end
    // golden: import begin
    {
        path: "/example/widgets/import",
        job: "Walk every state of the worked widget import page — choose, check, preview, apply — the example a product copies; a 404 in production.",
        primarySeat: "import-preview",
        operation: "djb_import-detail",
        devOnly: true,
        surfaces: ["staff"],
    },
    // golden: import end
    // golden: face begin
    {
        path: "/example/widgets/[id]",
        job: "Walk every state of the worked widget record, the example a product copies; a 404 in production.",
        primarySeat: null,
        operation: "widget-detail",
        devOnly: true,
        surfaces: ["staff"],
    },
    // golden: face end
    // golden: portal begin
    // The worked customer face (`apps/example_portal`): its four pages, drawn
    // on the customer surface alone — the same four `screens` its declaration
    // answers (`apps/example_portal/surfaces.py`, held equal by its tests).
    {
        path: "/widgets",
        job: "List the widgets shared with the customer, read-only.",
        primarySeat: null,
        operation: "widget-list",
        devOnly: false,
        surfaces: ["customer"],
    },
    {
        path: "/widgets/[id]",
        job: "Read one shared widget and open a request about it.",
        primarySeat: "record-acts",
        operation: "widget-detail",
        devOnly: false,
        surfaces: ["customer"],
    },
    {
        path: "/requests",
        job: "Send a request about a widget and list the requests the customer can see.",
        primarySeat: "request-send",
        operation: "portal_request-list",
        devOnly: false,
        surfaces: ["customer"],
    },
    {
        path: "/requests/[id]",
        job: "Read one request the customer sent.",
        primarySeat: null,
        operation: "portal_request-detail",
        devOnly: false,
        surfaces: ["customer"],
    },
    // golden: portal end
];

/**
 * The key of the surface the server named for this address, or `undefined`
 * before it has answered — when every reader below answers the whole table.
 */
export type SurfaceKey = string | undefined;

/**
 * The key of the staff surface — the one every product has, declared or not.
 *
 * A staff screen passes it to every reader below, exactly as a customer
 * screen passes its own key: a screen names the surface it is drawn for, so the row
 * it reads is that surface's row wherever the table puts it. A screen that
 * passed nothing would read the whole table, where the first row that draws an
 * operation wins — right only while the staff rows happen to come first. The
 * whole-table answer (`undefined`) belongs to the root layout's gate alone,
 * before the server has named this address's surface.
 */
export const STAFF_SURFACE = "staff";

/** Is `row` drawn on `surface`? Every row is, before the surface is known. */
function onSurface(row: RouteRow, surface: SurfaceKey): boolean {
    return surface === undefined || row.surfaces === "*" || row.surfaces.includes(surface);
}

/**
 * The rows `surface` draws, in table order — what a nav on this surface lists, and nothing else.
 *
 * Derived from the table, so the count of screens a surface has is never
 * typed anywhere: a row that names the surface is on it.
 */
export function routesOn(surface: SurfaceKey, table: readonly RouteRow[] = ROUTE_TABLE): readonly RouteRow[] {
    return table.filter((row) => onSurface(row, surface));
}

/**
 * Whether `pathname` is a page of this face that `surface` does not draw — the surface guard's question.
 *
 * `true` only when a row draws `pathname` (a dynamic segment matches one path
 * segment; a static path outranks a dynamic one it also matches) and that row
 * is not on the surface. A path no row draws is the app router's own 404
 * already, and before the answer (`undefined`) nothing is refused.
 */
export function offSurface(pathname: string, surface: SurfaceKey, table: readonly RouteRow[] = ROUTE_TABLE): boolean {
    if (surface === undefined) return false;
    const row =
        table.find((candidate) => candidate.path === pathname) ??
        table.find((candidate) => pattern(candidate.path).test(pathname));
    return row !== undefined && !onSurface(row, surface);
}

/** A row's path as a matcher: each `[segment]` one path segment, a trailing slash allowed. */
function pattern(path: string): RegExp {
    const escaped = path
        .split(/\[[^\]]+\]/)
        .map((part) => part.replace(/[.*+?^${}()|\\]/g, "\\$&"))
        .join("[^/]+");
    return new RegExp(`^${escaped}/?$`);
}

/** The prefix of the dev-only walk pages (`/example/<nouns>`): a page there yields to a page of the product's own. */
const WALK_PREFIX = "/example/";

/** Do `a` and `b` draw for one audience — a surface both name, or a `"*"` row? */
function shareSurface(a: RouteRow, b: RouteRow): boolean {
    return a.surfaces === "*" || b.surfaces === "*" || a.surfaces.some((key) => b.surfaces.includes(key));
}

/**
 * The row on `surface` that draws `operation`, or `undefined` — a page of the product's own before a walk.
 *
 * The first row that draws it wins, unless that row is a walk (`/example/…`) and
 * a row outside the walks draws the same operation for an audience the walk
 * shares: then that row is the page, in either order, so a product's page and
 * the scaffold's walk beside it never race on table order.
 */
export function rowFor(operation: string, table: readonly RouteRow[] = ROUTE_TABLE, surface: SurfaceKey): RouteRow | undefined {
    const drawn = table.filter((candidate) => candidate.operation === operation && onSurface(candidate, surface));
    const first = drawn[0];
    if (first === undefined || !first.path.startsWith(WALK_PREFIX)) return first;
    return drawn.find((candidate) => !candidate.path.startsWith(WALK_PREFIX) && shareSurface(candidate, first)) ?? first;
}

/**
 * The page on `surface` that draws `operation`, its dynamic segments filled from `segments` — or `null`.
 *
 * `null` when no row on `surface` draws the operation or a segment has no
 * value. Every door a face draws to another page (a row, a crumb, a remedy) is
 * spelled here, from the table, never composed in the screen. The surface is
 * REQUIRED: every screen passes the one it is drawn for (`STAFF_SURFACE`, or a
 * surface's own key), so a door to a page that surface does not draw is never
 * drawn and the table's row order decides nothing.
 */
export function pathFor(
    operation: string,
    segments: Readonly<Record<string, string>> = {},
    table: readonly RouteRow[] = ROUTE_TABLE,
    surface: SurfaceKey,
): string | null {
    const row = rowFor(operation, table, surface);
    if (row === undefined) return null;
    let unfilled = false;
    const path = row.path.replace(/\[([^\]]+)\]/g, (_whole, name: string) => {
        const value = segments[name];
        if (value === undefined || value === "") {
            unfilled = true;
            return "";
        }
        return encodeURIComponent(value);
    });
    return unfilled ? null : path;
}
