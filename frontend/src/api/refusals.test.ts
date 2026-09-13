import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { TRANSPORT_CODES, isWireRefusal, registryRefusal, transportFailure } from "@/api/refusals";
import { TRANSPORT_COPY } from "@/copy/refusals";

/** The document of record, read rather than remembered. */
function registryCodes(): readonly string[] {
    // `process.cwd()` is `frontend/` — the runner's root, which is where the
    // committed document lives. Read, never remembered.
    const path = resolve(process.cwd(), "openapi.json");
    const document = JSON.parse(readFileSync(path, "utf8")) as {
        components: { schemas: { Refusal: { properties: { code: { enum: string[] } } } } };
    };
    return document.components.schemas.Refusal.properties.code.enum;
}

describe("the transport vocabulary is closed and is NOT the registry's", () => {
    it("has exactly two members", () => {
        expect([...TRANSPORT_CODES]).toEqual(["network_unreachable", "request_timeout"]);
    });

    it("shares no code with the document's refusal registry", () => {
        // THE FAIL-OPEN CLASS, ASSERTED. A client that synthesised a registry
        // code for a dead origin would be indistinguishable from the server
        // having said it — the UA-blue class in refusal clothing. The registry
        // half is READ FROM THE DOCUMENT, so the day a backend rung adds a code
        // named `request_timeout` this test says so instead of the collision
        // arriving as a rendered lie.
        const codes = new Set(registryCodes());
        for (const transport of TRANSPORT_CODES) {
            expect(codes.has(transport)).toBe(false);
        }
    });

    it("gives each member its own words, because the server said none", () => {
        for (const code of TRANSPORT_CODES) {
            expect(TRANSPORT_COPY[code].length).toBeGreaterThan(0);
        }
    });
});

describe("transportFailure", () => {
    it("calls a timeout a timeout", () => {
        const failure = transportFailure(new DOMException("timed out", "TimeoutError"));
        expect(failure).toEqual({
            kind: "transport",
            code: "request_timeout",
            detail: TRANSPORT_COPY.request_timeout,
        });
    });

    it("calls an abort a timeout too — both are `we stopped waiting`", () => {
        expect(transportFailure(new DOMException("aborted", "AbortError")).code).toBe("request_timeout");
    });

    it("calls anything else unreachable", () => {
        expect(transportFailure(new TypeError("Failed to fetch")).code).toBe("network_unreachable");
        expect(transportFailure("a string nobody expected").code).toBe("network_unreachable");
    });
});

describe("registryRefusal", () => {
    it("passes the server's own envelope through verbatim", () => {
        const wire = {
            code: "addressing_header_not_honoured",
            detail: "You are who you say you are, and this request named a place it cannot act in.",
            remedies: [{ label: "Name an organization you hold a role on", destination: "header:X-Org" }],
        };
        expect(registryRefusal(wire)).toEqual({ kind: "registry", refusal: wire });
    });

    it("refuses to invent a code when the body is not the envelope", () => {
        // A proxy's HTML 502 is still a RESPONSE, so it is a registry refusal
        // with the registry's own `error` code — never a transport failure,
        // which would be a second lie about what happened.
        const refusal = registryRefusal("<html>502 Bad Gateway</html>");
        expect(refusal.kind).toBe("registry");
        expect(refusal.refusal.code).toBe("error");
        expect(refusal.refusal.detail).toBe(TRANSPORT_COPY.unreadable_refusal);
    });
});

describe("isWireRefusal", () => {
    it("accepts the envelope and rejects everything else", () => {
        expect(isWireRefusal({ code: "not_found", detail: "no" })).toBe(true);
        expect(isWireRefusal({ code: "not_found" })).toBe(false);
        expect(isWireRefusal(null)).toBe(false);
        expect(isWireRefusal(["not_found"])).toBe(false);
    });
});
