/**
 * THE BOOT QUESTION, ASKED BY A SERVER LAYOUT — for the request it is rendering.
 *
 * The one endpoint and the one resolver, a second caller: a route group's
 * server layout (a surface's own pages, `@/app/(customer)/layout`) answers a
 * real 404 off its surface, and it can only know the surface by asking the
 * server with the request's own host. So the ask goes straight to the backend
 * origin — the ONE constant the proxy's rewrite reads — carrying `Host` as the
 * browser sent it. No cookie and no hat: the boot question is unauthenticated
 * and names a surface, never a person.
 *
 * WHY `node:http` AND NOT `fetch` — measured, not taste. `Host` is a forbidden
 * request header in the fetch standard, and Node's `fetch` enforces it: a
 * caller's `Host: customer.localhost:3500` leaves as the origin's own host and
 * the server answers `surface_unknown_host` (measured on a verifier box, Node
 * 24). `X-Forwarded-Host` would arrive, but the server honours it only behind
 * the development proxy (`config/settings/local.py`), never in production. So
 * this one call is made with Node's own client, which sends the header it is
 * given — and it lives in its own module because the browser bundle, which
 * imports `@/api/surface`, cannot carry `node:http`.
 */

import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

import type { Answer } from "@/api/client";
import { registryRefusal, transportFailure } from "@/api/refusals";
import { type BootedSurface, booted, SURFACE } from "@/api/surface";

import { DJANGO_ORIGIN } from "../../next.config";

/** How long the layout waits before it stops waiting — the seam's own figure. */
const TIMEOUT_MS = 10_000;

/** Which surface `host` is, asked of the server with that `Host`; the refusal when it could not say. */
export function readSurfaceOnServer(host: string): Promise<Answer<BootedSurface>> {
    return exchangeWithHost(new URL(SURFACE, DJANGO_ORIGIN), host).then(booted);
}

/** One GET carrying `Host`, mapped exactly as the seam maps every answer. */
function exchangeWithHost(url: URL, host: string): Promise<Answer<unknown>> {
    const send = url.protocol === "https:" ? httpsRequest : httpRequest;
    return new Promise((resolve) => {
        const outgoing = send(
            url,
            { method: "GET", headers: { Accept: "application/json", Host: host }, timeout: TIMEOUT_MS },
            (incoming) => {
                const chunks: Buffer[] = [];
                incoming.on("data", (chunk: Buffer) => chunks.push(chunk));
                incoming.on("end", () => {
                    const body = parsed(Buffer.concat(chunks).toString("utf8"));
                    const status = incoming.statusCode ?? 0;
                    if (status >= 200 && status < 300 && body !== undefined) {
                        resolve({ kind: "ok", data: body });
                    } else {
                        resolve({ kind: "refused", refusal: registryRefusal(status >= 200 && status < 300 ? undefined : body) });
                    }
                });
            },
        );
        outgoing.on("timeout", () => outgoing.destroy(new DOMException("timed out", "TimeoutError")));
        outgoing.on("error", (cause) => resolve({ kind: "refused", refusal: transportFailure(cause) }));
        outgoing.end();
    });
}

function parsed(text: string): unknown {
    try {
        return JSON.parse(text) as unknown;
    } catch {
        return undefined;
    }
}
