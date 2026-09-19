import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
    ABNORMAL_CLOSURE,
    OBSERVABLE_SOCKET_CLOSE_STATES,
    OBSERVED_FRAME,
    SERVER_CLOSE_CODES,
    signInAct,
    socketCloseRefusal,
    socketCloseState,
} from "@/api/socket-close";
import { SOCKET_CLOSE_STATES } from "@/api/refusals";
import { SOCKET_CLOSE_COPY } from "@/copy/refusals";

/**
 * THE CENSUS. The close-code vocabulary is `apps/realtime/schemas.py`'s and
 * nothing else — read here, never re-typed (A10.1).
 *
 * A TEST MAY READ PYTHON SOURCE; THE COMPONENT MUST NOT. The codes are not in
 * the generated client — they are a socket contract, and the OpenAPI document
 * describes the REST door — so the pin is this census rather than a generated
 * type. It is set-equality in BOTH directions: a constant added to that module
 * reds here, and a constant this tree invented reds here too.
 */
const SCHEMAS_PY = resolve(process.cwd(), "..", "apps", "realtime", "schemas.py");

function serverVocabulary(): ReadonlyMap<string, number> {
    let source: string;
    try {
        source = readFileSync(SCHEMAS_PY, "utf8");
    } catch (cause) {
        // COULD NOT LOOK, LOUDLY. A vocabulary whose authority is unreadable is
        // never a pass: this is the same cell the gate's own legs call
        // could-not-look, and it outranks a green.
        throw new Error(`the close-code vocabulary's authority is unreadable at ${SCHEMAS_PY}: ${String(cause)}`);
    }
    const found = new Map<string, number>();
    for (const line of source.split("\n")) {
        const match = /^(CLOSE_[A-Z_]+) = (\d+)$/.exec(line);
        if (match !== null) {
            found.set(String(match[1]), Number(match[2]));
        }
    }
    return found;
}

describe("the close-code vocabulary is the server's, read and never re-typed", () => {
    it("finds the constants at all — a silent zero is a census that stopped looking", () => {
        expect(serverVocabulary().size).toBeGreaterThan(0);
    });

    it("agrees with apps/realtime/schemas.py, both directions", () => {
        const server = serverVocabulary();
        const mine = new Map(Object.entries(SERVER_CLOSE_CODES).map(([name, fact]) => [name, fact.code]));
        expect(Object.fromEntries([...mine].sort())).toEqual(Object.fromEntries([...server].sort()));
    });
});

describe("what a REAL client observes (WATCH F12)", () => {
    it("says the pre-accept codes never reach a client", () => {
        // The measured fact: the middleware and the consumer close BEFORE
        // accept, which the protocol surfaces as an HTTP handshake rejection —
        // the browser reports 1006 with no reason and never sees 4401/4403.
        expect(SERVER_CLOSE_CODES.CLOSE_UNAUTHENTICATED.reachesAClient).toBe(false);
        expect(SERVER_CLOSE_CODES.CLOSE_NO_TENANT.reachesAClient).toBe(false);
    });

    it("says the post-accept kick does", () => {
        expect(SERVER_CLOSE_CODES.CLOSE_KICKED.reachesAClient).toBe(true);
    });

    it("walks exactly two states today", () => {
        expect([...OBSERVABLE_SOCKET_CLOSE_STATES]).toEqual([
            "socket_handshake_rejected",
            "socket_credential_withdrawn",
        ]);
    });

    it("designs a sentence for every state it walks, and walks every state it designs", () => {
        // The trap the criteria name: a state with no words renders nothing,
        // and words with no state are words nobody reads. Set-equality is what
        // makes the day 4401/4403 become observable LOUD rather than silent.
        expect([...OBSERVABLE_SOCKET_CLOSE_STATES].sort()).toEqual([...SOCKET_CLOSE_STATES].sort());
        expect(Object.keys(SOCKET_CLOSE_COPY).sort()).toEqual([...SOCKET_CLOSE_STATES].sort());
    });
});

describe("the two sentences, verbatim from the design", () => {
    it("says what a handshake rejection says", () => {
        const words = SOCKET_CLOSE_COPY.socket_handshake_rejected;
        expect(`${words.label}. ${words.detail}`).toBe("Couldn't connect. Sign in and try again.");
        expect(words.act).toBe("Sign in");
    });

    it("says what a withdrawn credential says", () => {
        const words = SOCKET_CLOSE_COPY.socket_credential_withdrawn;
        expect(`${words.label}. ${words.detail}`).toBe(
            "Your access here ended. This connection was closed because the credential behind it was withdrawn. Sign in again to continue.",
        );
        expect(words.act).toBe("Sign in");
    });
});

describe("socketCloseState reads the close frame a browser actually delivers", () => {
    it("calls 1006-with-no-reason a handshake rejection", () => {
        expect(socketCloseState({ code: ABNORMAL_CLOSURE, reason: "" })).toBe("socket_handshake_rejected");
    });

    it("calls 4410 a withdrawn credential", () => {
        expect(socketCloseState({ code: 4410, reason: "" })).toBe("socket_credential_withdrawn");
    });

    it("has no state for a normal close", () => {
        expect(socketCloseState({ code: 1000, reason: "" })).toBeNull();
    });

    it("has no state for the codes no client can receive today", () => {
        // Not an oversight: rendering a state for a code nobody receives is a
        // component asserting a mechanism. The day the socket accepts before it
        // closes, those codes gain a state and this expectation is the
        // thing that has to be rewritten — out loud.
        expect(socketCloseState({ code: 4401, reason: "" })).toBeNull();
        expect(socketCloseState({ code: 4403, reason: "" })).toBeNull();
    });

    it("has no state for the client-command code, which this client cannot provoke", () => {
        // 4400 is post-accept and therefore observable, but it means this
        // client sent something other than a ping, and this client has no
        // sender at all. A designed sentence for it would be improvised.
        expect(socketCloseState({ code: 4400, reason: "" })).toBeNull();
    });
});

describe("socketCloseRefusal mints a TRANSPORT-class refusal and never a registry code", () => {
    it("carries the state's own words as the detail", () => {
        for (const state of OBSERVABLE_SOCKET_CLOSE_STATES) {
            const refusal = socketCloseRefusal(OBSERVED_FRAME[state]);
            expect(refusal).toEqual({
                kind: "transport",
                code: state,
                detail: SOCKET_CLOSE_COPY[state].detail,
            });
        }
    });

    it("answers nothing at all for a close it has no state for", () => {
        expect(socketCloseRefusal({ code: 1000, reason: "" })).toBeNull();
    });

    it("shares no code with the document's refusal registry", () => {
        const path = resolve(process.cwd(), "openapi.json");
        const document = JSON.parse(readFileSync(path, "utf8")) as {
            components: { schemas: { Refusal: { properties: { code: { enum: string[] } } } } };
        };
        const registry = new Set(document.components.schemas.Refusal.properties.code.enum);
        for (const state of SOCKET_CLOSE_STATES) {
            expect(registry.has(state)).toBe(false);
        }
    });
});

describe("the one act", () => {
    it("is Sign in, back to where the person was", () => {
        expect(signInAct("socket_credential_withdrawn", "/states")).toEqual({
            label: "Sign in",
            href: "/accounts/login/?next=%2Fstates",
        });
    });
});

/**
 * A10.2 — NO AUTOMATIC RECONNECT. A retry loop in a tab is a workflow wearing a
 * hook (fe-conventions §7); the person's click is the retry.
 *
 * Two teeth, because either alone is weak. The behavioural one asserts that
 * handling a close schedules NOTHING; the source census asserts the timer APIs
 * are not spelled in these modules at all, so a timer added tomorrow reds even
 * if nothing calls it in a test.
 */
describe("no automatic reconnect", () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it("schedules no timer when a socket closes", () => {
        vi.useFakeTimers();
        for (const state of OBSERVABLE_SOCKET_CLOSE_STATES) {
            socketCloseRefusal(OBSERVED_FRAME[state]);
        }
        expect(vi.getTimerCount()).toBe(0);
    });

    it("spells no timer API in the modules that meet a close frame", () => {
        const timerApis = ["setTimeout", "setInterval", "requestAnimationFrame", "queueMicrotask"];
        for (const path of ["src/api/socket-close.ts", "src/screens/socket-close-panel.tsx", "src/screens/refusal-panel.tsx"]) {
            const source = readFileSync(resolve(process.cwd(), path), "utf8");
            for (const api of timerApis) {
                expect(source.includes(api), `${path} spells ${api}`).toBe(false);
            }
        }
    });
});
