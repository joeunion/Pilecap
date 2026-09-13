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

export const TRANSPORT_COPY = {
    network_unreachable: "This page could not reach the server. Nothing was sent.",
    request_timeout: "The server did not answer in time. Nothing was sent.",
    unreadable_refusal: "The server refused this request and the reason did not arrive in a shape this page can read.",
} as const;
