/**
 * The words of the one journey. Strings live in copy modules, not inline in JSX
 * (fe-conventions §5).
 *
 * THE VOICE IS THE ELSE-BRANCH: this page is honest about being a placeholder
 * rather than dressed up as a product. It is the same register the SSO refusal
 * page and the invitation email already speak.
 */

export const WELCOME_COPY = {
    // THE HEADING ASSERTS NOTHING ABOUT THE SESSION, and the first browser
    // drive is why: it read "You are signed in" over a rendered
    // `unauthenticated` refusal. A heading is rendered in all four states, so
    // it may only say what is true in all four.
    title: "Welcome",

    /** Said once, at the top: what this page is and what a product does to it. */
    placeholder:
        "This is the template's landing page. It is shadowed, not configured — mount your own route at this path and yours wins, with no setting to change.",

    /** The parity sentence: what this page is FOR. */
    parity:
        "It shows the session facts the REST door answers, read through the generated client, so the first client of this API is a worked example rather than a description of one.",

    hatAsked: "Acting as",
    hatDefault: "the organization your membership names",
    hatNote: "The hat is sent on the request and revalidated by the server on every one. This page carries it; it never decides it.",

    loading: "Reading the session facts…",

    organizations: "What this hat can see",
    columnName: "Organization",
    columnSlug: "Slug",
    columnDepth: "Depth",

    emptyLabel: "Sign in to see where you are acting",
    emptyDetail:
        "The door answered with no organizations at all. Either this session has no place in the tree yet, or the hat it asked for covers none.",
} as const;
