import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
    FETCH_TRANSPORT_CODES,
    SOCKET_CLOSE_STATES,
    TRANSPORT_CODES,
    isWireRefusal,
    registryRefusal,
    transportFailure,
} from "@/api/refusals";
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
    it("is exactly its two declared halves, and nothing else", () => {
        // The STATE list is closed at four and the things which can go wrong
        // are an open population belonging in a vocabulary — so this list may
        // grow, and the growth must be LOUD. Set-equality against the two
        // declared halves is that loudness: a member added to neither half, or
        // a third half, reds here.
        expect([...TRANSPORT_CODES]).toEqual([...FETCH_TRANSPORT_CODES, ...SOCKET_CLOSE_STATES]);
        expect([...FETCH_TRANSPORT_CODES]).toEqual(["network_unreachable", "request_timeout"]);
        expect([...SOCKET_CLOSE_STATES]).toEqual(["socket_handshake_rejected", "socket_credential_withdrawn"]);
    });

    it("never lets a THROWN FETCH mint a close-frame code", () => {
        // The two halves answer different events. A fetch that never got a
        // response is not a socket that ended, and the day this mapper reaches
        // for a close-frame name it would be telling a person their credential
        // was withdrawn because a proxy was down.
        const closeFrameCodes = new Set<string>(SOCKET_CLOSE_STATES);
        for (const cause of [new DOMException("timed out", "TimeoutError"), new TypeError("Failed to fetch"), null]) {
            expect(closeFrameCodes.has(transportFailure(cause).code)).toBe(false);
        }
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

    it("refuses to invent a registry code when the body is not the envelope", () => {
        const refusal = registryRefusal("<html>500 Internal Server Error</html>", 500);
        expect(refusal).toEqual({ kind: "transport", code: "network_unreachable", detail: TRANSPORT_COPY.unreadable_refusal });
    });

    it("a gateway status with no envelope is the unreachable case, in its sentence", () => {
        for (const status of [502, 503, 504]) {
            expect(registryRefusal("<html>Bad Gateway</html>", status)).toEqual({ kind: "transport", code: "network_unreachable", detail: TRANSPORT_COPY.network_unreachable });
        }
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
