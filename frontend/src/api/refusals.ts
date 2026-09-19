/**
 * THE ONE MAPPER. The mirror of `config/api.py`, pointed the other way.
 *
 * Below this module there are status codes, headers and response objects.
 * Above it there are refusals, states and remedies — and nothing else
 * (fe-conventions §4, Law 1; house rule 14 read outward). One module knows
 * that a 404 is `not_found`; nothing else in this tree may learn it.
 */

import type { components } from "@/api/generated/schema";
import { TRANSPORT_COPY } from "@/copy/refusals";

/**
 * The server's own refusal envelope, VERBATIM from the generated document.
 * Never re-declared by hand — the hand-typed shadow is fe-conventions §6.7,
 * and it renders `undefined` a long way from the interface that lied.
 */
export type WireRefusal = components["schemas"]["Refusal"];
export type WireRemedy = components["schemas"]["RefusalRemedy"];

/** Every code the registry can answer with, as the document declares them. */
export type RegistryCode = WireRefusal["code"];

/**
 * THE CLOSED TRANSPORT VOCABULARY — two HALVES, and no member of either is a
 * registry code (P16 ruling 2, "no fifth state").
 *
 * The halves are `FETCH_TRANSPORT_CODES` (a request that never got an answer)
 * and `SOCKET_CLOSE_STATES` (a socket that ended without one). It is one
 * vocabulary because it is one question — *what happened instead of an answer*
 * — and P16 ruling 2 says a vocabulary may GROW where a state list may not:
 * the four `SurfaceState`s are a closed question a screen answers once, and
 * the things that can go wrong are an open population. Growing this list is
 * therefore legal and is deliberately LOUD: `refusals.test.ts` asserts the
 * membership by set-equality, so a third half cannot arrive quietly.
 *
 * A dead origin, a CORS block or an aborted connection throws BEFORE any
 * response exists: there is no code, no fact and no remedies, and the refusal
 * registry is the wrong authority for it by construction. Synthesising a
 * registry code for it would fail OPEN — a client-invented `not_found` is
 * indistinguishable from the server's, which is the UA-blue class wearing
 * refusal clothing. So transport failure gets its own vocabulary, its own copy,
 * and rides inside `error(E)` rather than earning a fifth state.
 */
export const FETCH_TRANSPORT_CODES = ["network_unreachable", "request_timeout"] as const;

/**
 * THE CLOSE-FRAME HALF — `TransportCode`-ADJACENT, which is the phrase design
 * P-14 uses and it is precise: these are transport codes, and they are minted
 * by a different event.
 *
 * A socket ends with a close frame, not with a response. There is no status,
 * no body and no envelope — so the refusal registry is the wrong authority for
 * it by exactly the argument that put a dead origin here, and a synthesised
 * registry code would fail OPEN in exactly the same way. The wire's own
 * vocabulary (the `CLOSE_*` numbers) is the SERVER's and is read from
 * `apps/realtime/schemas.py`; these two names are this CLIENT's, and
 * `@/api/socket-close` is the one module that maps between them.
 *
 * TWO MEMBERS BECAUSE A REAL CLIENT OBSERVES TWO THINGS (WATCH F12), never
 * because the server declares two codes. That is the whole content of the
 * distinction: `apps/realtime` declares four codes and a browser can be handed
 * two outcomes.
 */
export const SOCKET_CLOSE_STATES = ["socket_handshake_rejected", "socket_credential_withdrawn"] as const;
export type SocketCloseState = (typeof SOCKET_CLOSE_STATES)[number];

export const TRANSPORT_CODES = [...FETCH_TRANSPORT_CODES, ...SOCKET_CLOSE_STATES] as const;
export type TransportCode = (typeof TRANSPORT_CODES)[number];

/** `E` of `error(E)`, member one: what the server said, in the server's words. */
export type RegistryRefusal = {
    readonly kind: "registry";
    readonly refusal: WireRefusal;
};

/** `E` of `error(E)`, member two: what happened instead of an answer. */
export type TransportFailure = {
    readonly kind: "transport";
    readonly code: TransportCode;
    readonly detail: string;
};

/** The discriminated union the ruling names. Nothing else may be an `error`. */
export type Refusal = RegistryRefusal | TransportFailure;

/** Exhaustiveness over the union, as a compile error rather than as a habit. */
export function unhandledRefusal(refusal: never): never {
    throw new Error(`unhandled Refusal: ${JSON.stringify(refusal)}`);
}

/**
 * A body that came back from the door, turned into the refusal it claims to be.
 *
 * A refusal whose body is not the envelope is still a refusal — a proxy's own
 * error page, an HTML 502 — and it is mapped to the registry member with the
 * one code the document already carries for "something went wrong here"
 * (`error`), never to a transport code: a response DID exist, so calling it a
 * transport failure would be a second lie about what happened.
 */
export function registryRefusal(body: unknown): RegistryRefusal {
    if (isWireRefusal(body)) {
        return { kind: "registry", refusal: body };
    }
    return {
        kind: "registry",
        refusal: {
            code: "error",
            detail: TRANSPORT_COPY.unreadable_refusal,
        },
    };
}

/**
 * A thrown fetch, turned into the closed transport vocabulary.
 *
 * The forbidden third option is letting it reject unhandled (§6.8): the screen
 * then shimmers for ever and the only trace is an `unhandledRejection` in a
 * console nobody was watching.
 */
export function transportFailure(cause: unknown): TransportFailure {
    const code: TransportCode = isTimeout(cause) ? "request_timeout" : "network_unreachable";
    return { kind: "transport", code, detail: TRANSPORT_COPY[code] };
}

/**
 * Is this thing the document's envelope? A structural test, because what comes
 * back over a wire is `unknown` and casting it would be Law 3's `as` in
 * disguise.
 */
export function isWireRefusal(body: unknown): body is WireRefusal {
    if (typeof body !== "object" || body === null) return false;
    const candidate = body as { code?: unknown; detail?: unknown };
    return typeof candidate.code === "string" && typeof candidate.detail === "string";
}

function isTimeout(cause: unknown): boolean {
    // `AbortSignal.timeout()` rejects with a DOMException named TimeoutError;
    // an explicit abort rejects with AbortError. Both are "we stopped waiting",
    // and neither is a refusal.
    if (typeof cause !== "object" || cause === null) return false;
    const name = (cause as { name?: unknown }).name;
    return name === "TimeoutError" || name === "AbortError";
}
