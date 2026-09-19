/**
 * The words for the things the server never got to say.
 *
 * Strings live in copy modules, not inline in JSX (fe-conventions §5): a
 * screen's words are reviewable as words when they sit together, and
 * untranslatable when they do not.
 *
 * **A registry refusal has NO copy here, and that is the point.** Its `detail`
 * and its `remedies` are the server's own and are rendered verbatim; a client
 * sentence beside them would be a second, drifting account of the same event.
 * The only words this file owns are the two transport members', because for
 * those the server said nothing at all.
 */

/**
 * THE CLOSE-FRAME WORDS (design J4; P-14). The socket half of the same
 * argument: a close frame carries no envelope at all — no code the registry
 * knows, no fact, no remedies — so these words are this client's own, exactly
 * as the two fetch-side transport members' are.
 *
 * ONE STATE, ONE LABEL, ONE DETAIL, ONE ACT. The design draws a panel with a
 * single act in it, and the singular is load-bearing: a close frame is not a
 * menu. `label`, then `detail`, is also how the two designed sentences are
 * SPELLED — `${label}. ${detail}` is the sentence the criteria quote, and the
 * census beside `@/api/socket-close` pins both against it verbatim.
 *
 * THERE IS NO ENTRY HERE FOR 4401 OR 4403, AND THAT IS NOT AN OVERSIGHT. No
 * client can receive either today (WATCH F12: both are sent before accept, and
 * the protocol turns that into a handshake rejection the browser reports as
 * 1006 with no reason), so a sentence for them would be words nobody reads, and
 * inventing one would be improvising a designed state — the thing a missing
 * ingredient is supposed to stop. The day the socket accepts before it closes,
 * the design writes those two sentences and they land here.
 */
export const SOCKET_CLOSE_COPY = {
    socket_handshake_rejected: {
        label: "Couldn't connect",
        detail: "Sign in and try again.",
        act: "Sign in",
    },
    socket_credential_withdrawn: {
        label: "Your access here ended",
        detail: "This connection was closed because the credential behind it was withdrawn. Sign in again to continue.",
        act: "Sign in",
    },
} as const;

export const TRANSPORT_COPY = {
    network_unreachable: "This page could not reach the server. Nothing was sent.",
    request_timeout: "The server did not answer in time. Nothing was sent.",
    unreadable_refusal: "The server refused this request and the reason did not arrive in a shape this page can read.",
    // DERIVED, NEVER RETYPED: the close-frame members' detail is the sentence
    // above, so the panel and the refusal envelope cannot drift into two
    // accounts of one event.
    socket_handshake_rejected: SOCKET_CLOSE_COPY.socket_handshake_rejected.detail,
    socket_credential_withdrawn: SOCKET_CLOSE_COPY.socket_credential_withdrawn.detail,
} as const;
