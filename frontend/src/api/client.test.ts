import { afterEach, describe, expect, it, vi } from "vitest";

import { listOrganizations } from "@/api/client";
import { TRANSPORT_COPY } from "@/copy/refusals";

type FetchArgs = Parameters<typeof fetch>;

function stubFetch(handler: (...args: FetchArgs) => Promise<Response>) {
    const spy = vi.fn(handler);
    vi.stubGlobal("fetch", spy);
    return spy;
}

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("the one seam catches a thrown fetch", () => {
    it("turns a rejected fetch into a TransportFailure, never an unhandled rejection", () => {
        // §6.8, and it is the reason this seam exists at all: a rejected
        // promise with no handler here is an eternal skeleton on every screen
        // downstream, and the only trace is a console nobody was watching.
        stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
        return listOrganizations(null).then((answer) => {
            expect(answer).toEqual({
                kind: "refused",
                refusal: {
                    kind: "transport",
                    code: "network_unreachable",
                    detail: TRANSPORT_COPY.network_unreachable,
                },
            });
        });
    });

    it("turns a timeout into request_timeout", async () => {
        stubFetch(() => Promise.reject(new DOMException("timed out", "TimeoutError")));
        const answer = await listOrganizations(null);
        expect(answer.kind === "refused" && answer.refusal.kind === "transport" && answer.refusal.code).toBe(
            "request_timeout",
        );
    });
});

describe("the hat is carried, never decided", () => {
    function headersOf(spy: ReturnType<typeof stubFetch>): Record<string, string> {
        const init = spy.mock.calls[0]?.[1];
        return (init?.headers ?? {}) as Record<string, string>;
    }

    it("OMITS X-Org entirely on the default hat", async () => {
        // `X-Org: ""` counts as SENT and is answered 403
        // `addressing_header_not_honoured`. An empty header is not a shrug.
        const spy = stubFetch(() => Promise.resolve(Response.json({ items: [], has_more: false, next_cursor: null, count: null })));
        await listOrganizations(null);
        expect(headersOf(spy)).not.toHaveProperty("X-Org");
    });

    it("omits it for a whitespace-only hat too", async () => {
        const spy = stubFetch(() => Promise.resolve(Response.json({ items: [], has_more: false, next_cursor: null, count: null })));
        await listOrganizations("   ");
        expect(headersOf(spy)).not.toHaveProperty("X-Org");
    });

    it("sends the hat it was given, unchanged", async () => {
        const spy = stubFetch(() => Promise.resolve(Response.json({ items: [], has_more: false, next_cursor: null, count: null })));
        await listOrganizations("harbour-office");
        expect(headersOf(spy)["X-Org"]).toBe("harbour-office");
    });

    it("asks for the document's own path, composed nowhere", async () => {
        const spy = stubFetch(() => Promise.resolve(Response.json({ items: [], has_more: false, next_cursor: null, count: null })));
        await listOrganizations(null);
        expect(spy.mock.calls[0]?.[0]).toBe("/api/v1/organizations/");
    });
});

describe("a refusal comes back as the server's own words", () => {
    it("carries code, detail and remedies through untouched", async () => {
        const wire = {
            code: "addressing_header_not_honoured",
            detail: "You are who you say you are, and this request named a place it cannot act in.",
            remedies: [{ label: "Check which memberships you actually hold", destination: "self:membership" }],
        };
        stubFetch(() => Promise.resolve(Response.json(wire, { status: 403 })));
        const answer = await listOrganizations("a-hat-you-do-not-hold");
        expect(answer).toEqual({ kind: "refused", refusal: { kind: "registry", refusal: wire } });
    });

    it("does not pretend a 200 with an unreadable body is data", async () => {
        stubFetch(() => Promise.resolve(new Response("not json", { status: 200 })));
        const answer = await listOrganizations(null);
        expect(answer.kind).toBe("refused");
    });
});
