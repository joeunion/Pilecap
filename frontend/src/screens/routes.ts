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
 * the list or detail operation the route draws, or `null` when it draws none).
 */

export type RouteRow = {
    readonly path: string;
    readonly job: string;
    readonly primarySeat: string | null;
    readonly operation: string | null;
};

export const ROUTE_TABLE: readonly RouteRow[] = [
    {
        path: "/welcome",
        job: "Land after sign-in and show which part of the tree the acting hat can see.",
        primarySeat: null,
        operation: "organization-list",
    },
    {
        path: "/states",
        job: "Render every authored state of the one screen, for the rendered drive; a 404 in production.",
        primarySeat: null,
        operation: null,
    },
];
