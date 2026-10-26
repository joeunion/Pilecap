import { afterEach, describe, expect, it, vi } from "vitest";

import { getWidget, listOrganizations, mintIntent, readPageToken, submitPortalRequest } from "@/api/client";
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

describe("a gateway answer with no registry body is the unreachable case", () => {
    it.each([
        ["502 with the proxy's HTML page", () => new Response("<html><body>502 Bad Gateway</body></html>", { status: 502, headers: { "Content-Type": "text/html" } })],
        ["503 with no body", () => new Response(null, { status: 503 })],
        ["504 with no body", () => new Response(null, { status: 504 })],
    ])("%s", async (_shape, answer) => {
        stubFetch(() => Promise.resolve(answer()));
        expect(await listOrganizations(null)).toEqual({
            kind: "refused",
            refusal: { kind: "transport", code: "network_unreachable", detail: TRANSPORT_COPY.network_unreachable },
        });
    });

    it("a 503 that carries the registry's envelope is the server's refusal, verbatim", async () => {
        const wire = { code: "database_unavailable", detail: "The database did not answer.", remedies: [] };
        stubFetch(() => Promise.resolve(Response.json(wire, { status: 503 })));
        expect(await listOrganizations(null)).toEqual({ kind: "refused", refusal: { kind: "registry", refusal: wire } });
    });

    it("a non-gateway answer with an unreadable body says the reason did not arrive readably", async () => {
        stubFetch(() => Promise.resolve(new Response("<html>500</html>", { status: 500 })));
        expect(await listOrganizations(null)).toEqual({
            kind: "refused",
            refusal: { kind: "transport", code: "network_unreachable", detail: TRANSPORT_COPY.unreadable_refusal },
        });
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

describe("the one mutation wrapper carries the token, the intent and the hat", () => {
    const BODY = { widget_id: "0196a000-0000-7000-8000-000000000001", note: "Send another?" };

    it("posts the body with the page token, the intent's key, and no hat header on the default hat", async () => {
        const spy = stubFetch(() => Promise.resolve(Response.json({ id: "x" }, { status: 201 })));
        vi.stubGlobal("document", { cookie: "sessionid=s; csrftoken=tok-1" });
        const intent = mintIntent();
        await submitPortalRequest(BODY, null, readPageToken(), intent);
        const [path, init] = spy.mock.calls[0] ?? [];
        expect(path).toBe("/api/v1/portal-requests/");
        expect(init?.method).toBe("POST");
        expect(init?.body).toBe(JSON.stringify(BODY));
        expect(init?.headers).toMatchObject({ "X-CSRFToken": "tok-1", "Idempotency-Key": intent });
        expect(init?.headers).not.toHaveProperty("X-Org");
    });

    it("one intent is one key on every retry; a new intent is a new key", async () => {
        const spy = stubFetch(() => Promise.resolve(Response.json({ id: "x" }, { status: 201 })));
        const intent = mintIntent();
        await submitPortalRequest(BODY, "org-1", readPageToken(), intent);
        await submitPortalRequest(BODY, "org-1", readPageToken(), intent);
        const keys = spy.mock.calls.map(([, init]) => (init?.headers as Record<string, string>)["Idempotency-Key"]);
        expect(keys[0]).toBe(keys[1]);
        expect(mintIntent()).not.toBe(intent);
        expect((spy.mock.calls[0]?.[1]?.headers as Record<string, string>)["X-Org"]).toBe("org-1");
    });

    it("sends no token header when the host carries no page token, so the server's own refusal answers", async () => {
        const spy = stubFetch(() =>
            Promise.resolve(Response.json({ detail: "No page token.", code: "page_token_missing", remedies: [] }, { status: 403 })),
        );
        vi.stubGlobal("document", { cookie: "" });
        const answer = await submitPortalRequest(BODY, null, readPageToken(), mintIntent());
        expect(spy.mock.calls[0]?.[1]?.headers).not.toHaveProperty("X-CSRFToken");
        expect(answer.kind).toBe("refused");
    });
});

describe("the reads fill the document's path, never compose their own", () => {
    it("a widget's record is its document path with the id filled in", async () => {
        const spy = stubFetch(() => Promise.resolve(Response.json({})));
        await getWidget("a b", null);
        expect(spy.mock.calls[0]?.[0]).toBe("/api/v1/widgets/a%20b/");
    });
});
