/**
 * THE FACE'S BOOT QUESTION — which surface is this address?
 *
 * One product has several faces on one set of records: staff at one host,
 * customers at another. The server already knows which one a request arrived
 * at (it reads the host once, in the middleware that resolves the tenant and
 * the hat), so the face ASKS rather than guessing: `GET /api/v1/surface/`
 * answers the surface's key, the screens it draws and how it chooses the
 * workspace. The face never reads its own address to decide — a second reader
 * of the host would be a second resolver, and the two would one day disagree.
 *
 * THE ANSWER IS TYPED HERE, AND THAT IS NOT A SHADOW OF A GENERATED TYPE. The
 * boot question is a plain view (the RFC 9728 metadata's precedent), not an
 * operation, so it is not in the OpenAPI document and the generated client has
 * no type for it (fe-conventions §4 Law 3 has nothing to be verbatim to). The
 * shape is the view's `SurfaceOut` in `config/api.py`; the structural check
 * below refuses a body that is not it, rather than casting past it.
 *
 * ONE PATH, ONE SHAPE CHECK, TWO ASKERS, AND NO STATE HERE. The root layout's
 * gate (`@/app/surface-gate`) asks `SURFACE` through the seam's `request` from a
 * ref-guarded one-shot, once per page load, and reads a 200 through `booted`;
 * a refusal in place of an answer (the backend unreachable, the proxy's 500, a
 * server refusal) never reaches `booted` — the gate keeps the page and the
 * surface unknown. A surface's server layout asks the same path with the
 * request's Host (`@/api/surface-server`) and reads it through `booted` too.
 * Nothing is retried behind the person's back; a reload asks again.
 */

import type { Answer } from "@/api/client";
import { registryRefusal } from "@/api/refusals";

export const SURFACE = "/api/v1/surface/" as const;

/** The three ways a surface chooses the workspace (`TENANT_RULES` in `apps/core/surfaces.py`). */
const TENANT_RULES = ["addressed", "host", "membership"] as const;

/** The server's answer to the boot question: this address's surface, its screens, its tenant rule. */
export type BootedSurface = {
    /** The surface's key, as the product declared it (`staff` when it declared none). */
    readonly surface: string;
    /** The route-table paths this surface draws, or `"*"` for every one. */
    readonly screens: "*" | readonly string[];
    readonly tenant_rule: (typeof TENANT_RULES)[number];
};

/** The answer when it is the boot question's shape; a bad 200 is refused, never cast. */
export function booted(answer: Answer<unknown>): Answer<BootedSurface> {
    if (answer.kind === "refused") return answer;
    if (!isBootedSurface(answer.data)) return { kind: "refused", refusal: registryRefusal(undefined) };
    return { kind: "ok", data: answer.data };
}

function isBootedSurface(body: unknown): body is BootedSurface {
    if (typeof body !== "object" || body === null) return false;
    const candidate = body as { surface?: unknown; screens?: unknown; tenant_rule?: unknown };
    const screens = candidate.screens;
    return (
        typeof candidate.surface === "string" &&
        candidate.surface !== "" &&
        (screens === "*" || (Array.isArray(screens) && screens.every((screen) => typeof screen === "string"))) &&
        TENANT_RULES.some((rule) => rule === candidate.tenant_rule)
    );
}
