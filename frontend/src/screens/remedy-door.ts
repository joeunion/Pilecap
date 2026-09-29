// patterns: none — draws no face
/**
 * THE REMEDY DOOR — which page, if any, a server remedy opens.
 *
 * A refusal's remedies are the server's own (`{label, destination}`, composed
 * once in the backend), and `destination` is an opaque `<kind>:<name>` token.
 * One kind names a thing a page can open: `route:<url_name>[?<query>]`, where
 * the url name is an OPERATION's, never a screen's. Which page draws which
 * operation is the route table's answer (`@/screens/routes`, its `operation`
 * column), so this module reads that table and keeps no list of its own: a
 * hand remedy-to-route table would be a second account of one fact.
 *
 * THE ANSWER IS ONE OF TWO, and both carry the label verbatim:
 *
 * * `link`: the token is `route:`, a route-table row draws that operation, and
 *   the row's path has no dynamic segment to fill. The query rides along
 *   as the list's narrowing.
 * * `label`: everything else (another kind, an operation no page draws, a
 *   path with a `[segment]` the token cannot fill, a label that is itself a
 *   machine token, and, in a production build, a page the table marks
 *   `devOnly`, which answers 404 there). The token is kept for the machine in `data-destination`
 *   and never printed. A broken link is never drawn; an unlinked label is the
 *   honest degradation.
 *
 * Pure: no markup, no fetch, no HTTP. The panel that draws it is
 * `@/screens/refusal-panel`.
 */

import type { WireRemedy } from "@/screens/state";
import { pathFor, ROUTE_TABLE, type RouteRow } from "@/screens/routes";

export type RemedyDoor =
    | { readonly kind: "link"; readonly label: string; readonly href: string; readonly destination: string }
    | { readonly kind: "label"; readonly label: string; readonly destination: string };

const ROUTE_KIND = "route:";

export function remedyDoor(remedy: WireRemedy, table: readonly RouteRow[] = ROUTE_TABLE): RemedyDoor {
    const { label, destination } = remedy;
    const unlinked: RemedyDoor = { kind: "label", label, destination };
    if (!destination.startsWith(ROUTE_KIND) || carriesMachineToken(label)) return unlinked;

    const target = destination.slice(ROUTE_KIND.length);
    const cut = target.indexOf("?");
    const operation = cut === -1 ? target : target.slice(0, cut);
    const query = cut === -1 ? "" : target.slice(cut + 1);
    if (operation === "") return unlinked;

    const path = pathFor(operation, {}, table);
    if (path === null) return unlinked;
    const devOnly = table.find((candidate) => candidate.operation === operation)?.devOnly === true;
    if (devOnly && process.env.NODE_ENV === "production") return unlinked;

    return { kind: "link", label, href: query === "" ? path : `${path}?${query}`, destination };
}

/**
 * The machine tokens house rule 73 names (its runner's closed list): a snake
 * token, a hex or UUID id, and a kebab key. A label that carries one is not a
 * door a person can name, so it is not drawn as one. The rule itself reads copy
 * modules; this is the same grammar applied to a label that arrived on the
 * wire, where no static census can reach.
 */
const SNAKE = /(?<![\w-])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![\w-])/;
const UUID = /(?<![0-9A-Za-z-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9A-Za-z-])/;
const HEX32 = /(?<![0-9A-Za-z])[0-9a-fA-F]{32}(?![0-9A-Za-z])/;
const KEBAB = /(?<![\w-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![\w-])/g;
const JOINING = new Set(["a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to"]);
const MACHINE_SUFFIX = new Set([
    "id", "uuid", "key", "slug", "url", "uri", "code", "ref", "pk",
    "list", "detail", "create", "update", "delete",
]);

function kebabIsKey(token: string): boolean {
    const parts = token.split("-");
    if (MACHINE_SUFFIX.has(parts[parts.length - 1] ?? "")) return true;
    return parts.length >= 3 && !parts.some((part) => JOINING.has(part));
}

export function carriesMachineToken(text: string): boolean {
    if (SNAKE.test(text) || UUID.test(text) || HEX32.test(text)) return true;
    return Array.from(text.matchAll(KEBAB), (m) => m[0]).some(kebabIsKey);
}
