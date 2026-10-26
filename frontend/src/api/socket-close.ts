/**
 * THE CLOSE-FRAME SEAM (design J4 · unproven ingredient P-14 · WATCH F12).
 *
 * This is the only module in the tree that knows a socket close code is a
 * number. Above it there are states, refusals and words — fe-conventions §4
 * Law 1, which is house rule 14 pointed outward, and a close code is wire
 * vocabulary exactly as a status code is.
 *
 * THE VOCABULARY IS `apps/realtime/schemas.py`'s AND IS NEVER RE-TYPED. The
 * numbers below are a MIRROR held in place by a census — `socket-close.test.ts`
 * reads that module and asserts set-equality in both directions, so a constant
 * added, removed or renumbered there reds here. They are not in the generated
 * client because the generated client is the REST document and these are the
 * socket door's contract; a test may read Python source for that, and the
 * component may not, which is why the pin lives in the test and the mirror
 * lives here.
 *
 * WHAT A REAL CLIENT OBSERVES IS NOT WHAT THE SERVER DECLARES (WATCH F12,
 * measured through uvicorn with a real `websockets` client):
 *
 *   anonymous                      -> HTTP 403 handshake rejection, no code
 *   bearer + a hat they do not hold -> HTTP 403 handshake rejection, no code
 *   token revoked on an OPEN socket -> close 4410
 *
 * `apps/realtime/middleware.py` and the consumer close BEFORE accept, and the
 * protocol surfaces a pre-accept close as a rejected handshake: the browser
 * fires `onclose` with 1006 and no reason, and 4401/4403 never reach it. So
 * this module renders states for what ARRIVES, and marks the rest
 * `reachesAClient: false` with the reason attached. A component that rendered
 * 4401 would be asserting a mechanism nobody can trigger — a criterion unable
 * to fail.
 *
 * WHEN THE SOCKET LEARNS TO ACCEPT BEFORE IT CLOSES, those two facts flip to
 * `true`, the design writes their sentences into `SOCKET_CLOSE_COPY`, and the
 * states appear in the walk below. Nothing in the panel changes: it reads the
 * vocabulary.
 */

import type { Refusal, SocketCloseState } from "@/api/refusals";
import { SOCKET_CLOSE_COPY } from "@/copy/refusals";

/**
 * RFC 6455's "abnormal closure": the connection ended without a close frame.
 * It is NOT a server code and never appears in `apps/realtime/schemas.py` —
 * it is what the browser reports on its own, and today it is the whole of what
 * a person sees when the handshake is refused.
 */
export const ABNORMAL_CLOSURE = 1006;

/** What `onclose` hands a client: a number and, usually, nothing else. */
export type CloseFrame = { readonly code: number; readonly reason: string };

type CloseCodeFact = {
    /** The number, mirrored from `apps/realtime/schemas.py` and censused. */
    readonly code: number;
    /** Does a real client ever receive it? WATCH F12. */
    readonly reachesAClient: boolean;
    /** The designed state it puts a socket-fed surface in, or `null`. */
    readonly state: SocketCloseState | null;
    /** Why there is no state, so the gap is declared rather than discovered. */
    readonly why: string;
};

export const SERVER_CLOSE_CODES = {
    CLOSE_NOT_A_COMMAND: {
        code: 4400,
        reachesAClient: true,
        state: null,
        why: "post-accept and therefore delivered, but it means this client sent something other than a ping — and this client has no sender at all. A sentence for it would be improvised.",
    },
    CLOSE_UNAUTHENTICATED: {
        code: 4401,
        reachesAClient: false,
        state: null,
        why: "sent before accept, so the protocol delivers a handshake rejection instead and the browser reports 1006 with no reason (WATCH F12).",
    },
    CLOSE_NO_TENANT: {
        code: 4403,
        reachesAClient: false,
        state: null,
        why: "sent before accept, same as 4401 (WATCH F12).",
    },
    CLOSE_KICKED: {
        code: 4410,
        reachesAClient: true,
        state: "socket_credential_withdrawn",
        why: "",
    },
    CLOSE_TOO_MANY_SOCKETS: {
        code: 4429,
        reachesAClient: false,
        state: null,
        why: "sent before accept, same as 4401 (WATCH F12).",
    },
    CLOSE_SESSION_EXPIRED: {
        code: 4419,
        reachesAClient: true,
        state: null,
        why: "post-accept and therefore delivered, but no state is designed for it yet — a sentence for it would be improvised.",
    },
} as const satisfies Record<string, CloseCodeFact>;

/**
 * THE WALK. Derived, never hand-listed: the handshake rejection (which belongs
 * to no server code) plus every server code a client can actually receive and
 * for which a state is designed.
 *
 * This is the line the criteria mean by "the census picks them up and the
 * states appear" — flipping a `reachesAClient` and giving that code a state is
 * the whole of the change, and `/states` grows a section without being edited.
 */
export const OBSERVABLE_SOCKET_CLOSE_STATES: readonly SocketCloseState[] = [
    "socket_handshake_rejected",
    ...Object.values(SERVER_CLOSE_CODES).flatMap((fact) =>
        fact.reachesAClient && fact.state !== null ? [fact.state] : [],
    ),
];

/**
 * The close frame a real client is handed for each state it walks.
 *
 * It is a total record over the state vocabulary, so a state added without a
 * frame that produces it is a compile error rather than a section of `/states`
 * that silently renders nothing. It is also what keeps the state walk driven by
 * the WIRE fact: `/states` and its test both seed from here rather than
 * hand-building a refusal that could disagree with the mapper.
 */
export const OBSERVED_FRAME: Record<SocketCloseState, CloseFrame> = {
    socket_handshake_rejected: { code: ABNORMAL_CLOSURE, reason: "" },
    socket_credential_withdrawn: { code: SERVER_CLOSE_CODES.CLOSE_KICKED.code, reason: "" },
};

/**
 * The close frame, read as one of this client's designed states — or `null`,
 * which means *this is not an error*: a normal close, a code no state is
 * designed for, or one no client can receive today.
 *
 * `null` is deliberately not a state. A surface that turned every close into a
 * refusal panel would announce a disaster every time a tab navigated away.
 */
export function socketCloseState(frame: CloseFrame): SocketCloseState | null {
    if (frame.code === ABNORMAL_CLOSURE) {
        return "socket_handshake_rejected";
    }
    const fact = Object.values(SERVER_CLOSE_CODES).find((candidate) => candidate.code === frame.code);
    return fact === undefined ? null : fact.state;
}

/**
 * The close frame, turned into the TRANSPORT-class refusal that rides
 * `error(E)` — never a registry code, because the server said nothing in an
 * envelope and a client-invented registry code is indistinguishable from one
 * the server sent (fe-conventions §3, and `refusals.ts`'s own argument).
 */
export function socketCloseRefusal(frame: CloseFrame): Refusal | null {
    const state = socketCloseState(frame);
    if (state === null) {
        return null;
    }
    return { kind: "transport", code: state, detail: SOCKET_CLOSE_COPY[state].detail };
}

/** The ONE act, and the singular is the design's: the person's click is the retry. */
export type SignInAct = { readonly label: string; readonly href: string };

/**
 * Where the one act goes. The path is the entrance chain's own
 * (`templates/account/login.html`, mounted by allauth), and `next` carries the
 * person back to where the socket died instead of to a landing page they did
 * not ask for.
 */
export function signInAct(state: SocketCloseState, returnTo: string): SignInAct {
    return {
        label: SOCKET_CLOSE_COPY[state].act,
        href: `/accounts/login/?next=${encodeURIComponent(returnTo)}`,
    };
}
