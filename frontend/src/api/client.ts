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
 * **There is deliberately no mutation wrapper in this scaffold, and its absence
 * is declared rather than forgotten.** fe-conventions §4 requires every write
 * to go through one wrapper carrying a CSRF token, an `Idempotency-Key` and the
 * hat — and this scaffold makes no writes at all. Shipping the wrapper anyway
 * would be a reader-less declaration, which is the class this house refuses on
 * the Python side too (house rule 30's shape). The first rung that writes
 * builds it, and it will also need the server told which browser origin it is
 * (`CSRF_TRUSTED_ORIGINS`), which is the first 403 fe-conventions §4 warns
 * about.
 */

import type { paths } from "@/api/generated/schema";
import type { Refusal } from "@/api/refusals";
import { registryRefusal, transportFailure } from "@/api/refusals";

/**
 * The version segment is `config/urls.py`'s and the path is the document's,
 * taken verbatim (P16 ruling 1: rule 32 translates to the client as
 * CONSUMPTION — the client never composes a resource path of its own).
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

async function request<T>(path: string, hat: Hat): Promise<Answer<T>> {
    // The hat rides in a header the server revalidates. Built here so no call
    // site can spell the empty-string form.
    const headers: Record<string, string> = { Accept: "application/json" };
    if (hat !== null && hat.trim() !== "") {
        headers["X-Org"] = hat;
    }

    let response: Response;
    try {
        response = await fetch(path, {
            method: "GET",
            headers,
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
        return { kind: "refused", refusal: registryRefusal(body) };
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
