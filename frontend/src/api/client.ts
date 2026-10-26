/**
 * THE ONE DOOR TO THE BACKEND (fe-conventions §4, Law 2 — the fourth member of
 * the fence family that already holds house rules 27, 33 and 48).
 *
 * No module outside `src/api/` calls `fetch` at an API path. Not a component,
 * not a route, not a test helper, not a "quick" server action. The reason is
 * rule 27's reason: a second door does not fail loudly, it works — until the
 * day it needs the header nobody remembered to add there.
 *
 * **This is a CLIENT of the REST door, not a sixth door.** It carries the hat;
 * it never decides the hat. The server revalidates `X-Org` on every request
 * (`core.middleware.resolve_org`), and a client that "knows" its own hat has
 * just resolved authority.
 *
 * **ONE MUTATION WRAPPER, `send`, and every write goes through it** (fe-conventions
 * §4). It carries three things every time so no call site can forget one: the
 * page token (`X-CSRFToken`, read from the host's `csrftoken` cookie by
 * `readPageToken` and nothing else), an `Idempotency-Key` minted per INTENT by
 * `mintIntent` (a retry or a double press reuses it; a new intent mints a new
 * one), and the hat. An unsafe call without either is a value TypeScript cannot
 * construct: both are branded types only their one producer makes. The server
 * must know the browser origin (`CSRF_TRUSTED_ORIGINS`, derived from the bound
 * hosts); a page token the cookie did not carry is sent as no header at all,
 * and the server's own `page_token_missing` is the answer the face renders.
 *
 * **A resource path is the document's.** Each path below is a key of the
 * generated `paths`, and a `{segment}` in one is filled here, in the seam, from
 * the id a screen handed over — a screen never spells a path.
 */

import type { components, paths } from "@/api/generated/schema";
import type { Refusal } from "@/api/refusals";
import { registryRefusal, transportFailure } from "@/api/refusals";

/**
 * The version segment is `config/urls.py`'s and the path is the document's,
 * taken verbatim: rule 32 reaches the client as CONSUMPTION — the client never
 * composes a resource path of its own.
 *
 * SAME-ORIGIN ON PURPOSE. The origin lives in `next.config.ts`'s rewrite and
 * nowhere else, so the browser sends its session cookie without a CORS story
 * and this module never learns that Django is somewhere in particular.
 */
const ORGANIZATIONS = "/api/v1/organizations/" as const;

/** How long this client waits before it stops waiting. */
const TIMEOUT_MS = 10_000;

/** The generated response type, used verbatim. Never re-declared (Law 3). */
export type OrganizationPage =
    paths[typeof ORGANIZATIONS]["get"]["responses"][200]["content"]["application/json"];
export type Organization = OrganizationPage["items"][number];

const WIDGETS = "/api/v1/widgets/" as const satisfies keyof paths;
const WIDGET = "/api/v1/widgets/{widget_id}/" as const satisfies keyof paths;
const PORTAL_REQUESTS = "/api/v1/portal-requests/" as const satisfies keyof paths;
const PORTAL_REQUEST = "/api/v1/portal-requests/{request_id}/" as const satisfies keyof paths;

/** The generated response types, used verbatim (Law 3). */
export type WidgetPage = paths[typeof WIDGETS]["get"]["responses"][200]["content"]["application/json"];
export type WidgetDetail = paths[typeof WIDGET]["get"]["responses"][200]["content"]["application/json"];
export type PortalRequestPage =
    paths[typeof PORTAL_REQUESTS]["get"]["responses"][200]["content"]["application/json"];
export type PortalRequest =
    paths[typeof PORTAL_REQUEST]["get"]["responses"][200]["content"]["application/json"];
export type PortalRequestIn = components["schemas"]["PortalRequestIn"];

/** What one call answers: the data, or the reason there is none. */
export type Answer<T> =
    | { readonly kind: "ok"; readonly data: T }
    | { readonly kind: "refused"; readonly refusal: Refusal };

/**
 * The acting hat, as a PARAMETER of the operation — never session state the
 * seam remembers. A screen that forgets it must say so out loud.
 *
 * `null` means "act in the organization my membership names", and it is sent by
 * OMITTING the header entirely. Never as an empty string: `X-Org: ""` counts as
 * *sent*, and the door answers 403 `addressing_header_not_honoured` — a shrug
 * spelled as a refusal.
 */
export type Hat = string | null;

/**
 * The session facts this checkout's REST door can answer: where the server says
 * you are acting, as the organizations your resolved hat can see.
 *
 * ONE OPERATION, on purpose — this is the template's worked example, not its
 * product.
 */
export async function listOrganizations(hat: Hat): Promise<Answer<OrganizationPage>> {
    return request<OrganizationPage>(ORGANIZATIONS, hat);
}

/** The widgets the acting hat can read — the customer face's list. */
export async function listWidgets(hat: Hat): Promise<Answer<WidgetPage>> {
    return request<WidgetPage>(WIDGETS, hat);
}

/** One widget, read-only — the customer face's record. */
export async function getWidget(widgetId: string, hat: Hat): Promise<Answer<WidgetDetail>> {
    return request<WidgetDetail>(filled(WIDGET, { widget_id: widgetId }), hat);
}

/** The portal requests the acting hat can see, newest first. */
export async function listPortalRequests(hat: Hat): Promise<Answer<PortalRequestPage>> {
    return request<PortalRequestPage>(PORTAL_REQUESTS, hat);
}

/** One portal request. */
export async function getPortalRequest(requestId: string, hat: Hat): Promise<Answer<PortalRequest>> {
    return request<PortalRequest>(filled(PORTAL_REQUEST, { request_id: requestId }), hat);
}

/** Send a portal request — one intent, one key, the page's token, the hat. */
export async function submitPortalRequest(
    body: PortalRequestIn,
    hat: Hat,
    token: PageToken,
    intent: IntentKey,
): Promise<Answer<PortalRequest>> {
    return send<PortalRequest>({ path: PORTAL_REQUESTS, body, hat, token, intent });
}

/** A document path with its `{segment}`s filled from `segments`, each encoded. */
function filled(template: string, segments: Readonly<Record<string, string>>): string {
    return template.replace(/\{([^}]+)\}/g, (_whole, name: string) => encodeURIComponent(segments[name] ?? ""));
}

/** The page token: the host's `csrftoken` cookie. Only `readPageToken` makes one. */
export type PageToken = string & { readonly __brand: "PageToken" };

/** One intent's `Idempotency-Key`. Only `mintIntent` makes one. */
export type IntentKey = string & { readonly __brand: "IntentKey" };

/**
 * The page token this host's session carries — read at the moment of the write,
 * because signing in rotates it. Empty when the cookie is absent: the write is
 * then sent with no token header, and the server's own refusal answers.
 */
export function readPageToken(): PageToken {
    const found = /(?:^|;\s*)csrftoken=([^;]*)/.exec(typeof document === "undefined" ? "" : document.cookie);
    return decodeURIComponent(found?.[1] ?? "") as PageToken;
}

/**
 * A new intent's key: random, never a counter — two tabs sharing a counter
 * collide on exactly the key that must not. Mint once per intent and reuse it
 * on every retry of that intent.
 */
export function mintIntent(): IntentKey {
    if (typeof crypto.randomUUID === "function") return crypto.randomUUID() as IntentKey;
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("") as IntentKey;
}

/** An unsafe call: it cannot be spelled without its token and its intent. */
type UnsafeCall = {
    readonly path: string;
    readonly body: unknown;
    readonly hat: Hat;
    readonly token: PageToken;
    readonly intent: IntentKey;
};

/**
 * THE ONE MUTATION WRAPPER: a POST carrying the page token, the intent's key
 * and the hat, answering exactly as a read does — the data, or the refusal.
 */
async function send<T>(call: UnsafeCall): Promise<Answer<T>> {
    const headers: Record<string, string> = {
        ...hatHeaders(call.hat),
        "Content-Type": "application/json",
        "Idempotency-Key": call.intent,
    };
    if (call.token !== "") {
        headers["X-CSRFToken"] = call.token;
    }
    return exchange<T>(call.path, { method: "POST", headers, body: JSON.stringify(call.body) });
}

/** A read of a document path, carrying the hat. */
export async function request<T>(path: string, hat: Hat): Promise<Answer<T>> {
    return exchange<T>(path, { method: "GET", headers: hatHeaders(hat) });
}

/**
 * The hat as a header — OMITTED on the default hat, never sent empty. Built
 * here so no call site can spell the empty-string form.
 */
function hatHeaders(hat: Hat): Record<string, string> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (hat !== null && hat.trim() !== "") {
        headers["X-Org"] = hat;
    }
    return headers;
}

/**
 * One exchange with the backend: the answer's data, the server's refusal, or
 * the transport failure — never a thrown fetch. `url` is a same-origin path, or
 * the backend origin itself for the server-side surface ask (`@/api/surface`).
 */
export async function exchange<T>(url: string, init: RequestInit): Promise<Answer<T>> {
    let response: Response;
    try {
        response = await fetch(url, {
            ...init,
            // The browser session cookie is the credential a signed-in page
            // has. Same-origin through the proxy, so this is the default —
            // stated anyway, because the default is what a later refactor
            // silently changes.
            // rule-50: fetch's `credentials` option is a cookie-inclusion
            // policy, not a credential store — the literal is one of the three
            // mode names the platform defines (`omit`/`same-origin`/`include`)
            // and carries no secret to read off the page.
            credentials: "same-origin",
            signal: AbortSignal.timeout(TIMEOUT_MS),
        });
    } catch (cause) {
        // §6.8 — the thrown fetch nobody caught. A rejected promise with no
        // handler here is an eternal skeleton on every screen downstream, plus
        // an `unhandledRejection` in a console nobody was watching. Caught, it
        // becomes a designed state.
        return { kind: "refused", refusal: transportFailure(cause) };
    }

    if (!response.ok) {
        const body = await readJson(response);
        return { kind: "refused", refusal: registryRefusal(body, response.status) };
    }

    const body = await readJson(response);
    // A 200 whose body did not parse is not an answer. It is refused with the
    // registry's own "something went wrong" code rather than pretended into a
    // `ready` state over `undefined` — §6.7's rendered-`undefined` class.
    if (body === undefined) {
        return { kind: "refused", refusal: registryRefusal(undefined) };
    }
    return { kind: "ok", data: body as T };
}

async function readJson(response: Response): Promise<unknown> {
    try {
        return (await response.json()) as unknown;
    } catch {
        return undefined;
    }
}
