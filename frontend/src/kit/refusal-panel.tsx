// patterns: §15
/**
 * THE ONE REFUSAL RENDERER.
 *
 * It was a private function inside `src/screens/welcome/welcome-screen.tsx`
 * until a second surface needed it (design J4: the socket close-code panel
 * renders "by the one refusal renderer", and two renderers would be two
 * accounts of one event).
 *
 * IT LIVES IN `kit/` AND NOT IN `components/`, AND THE RULE DECIDES THAT,
 * NOT TASTE. House rule 51 (`js-ingredient-boundary`) excludes the REFUSAL /
 * wire-error vocabulary from its type-only clause "whatever its provenance:
 * it reaches a screen through the surface-state seam, never directly" — and
 * `components/` sits BELOW `kit/`, so a module there can reach that
 * vocabulary through neither door. A renderer whose whole subject is a
 * `Refusal` is therefore a kit-layer module by construction.
 *
 * IT RENDERS; IT NEVER FETCHES, and it names no HTTP anywhere (fe-conventions
 * §4 Laws 1 and 4). What arrives is a `Refusal`, and the two members of that
 * union are rendered differently ON PURPOSE: the registry member shows the
 * server's own `detail`, `code` and `remedies` verbatim, and the transport
 * member shows this client's own words and NO remedies, because no response
 * existed for the server to put them in.
 *
 * THE WORDS DEFAULT, AND A CALLER SAYS ONLY WHAT DIFFERS. The first line per
 * member of the union and the heading over the remedies are declared once, in
 * `@/copy/refusals` (`REFUSAL_WORDS`), and every surface that says them the
 * same way passes nothing. Two things replace the first line: an act's own
 * refused word (`refused` — the verb table's *Couldn't save*, *Couldn't move*,
 * the act whose row the panel sits under), and a surface's own voice (`words` —
 * *Your access here ended* on a socket that was kicked). The panel owns the
 * SHAPE.
 *
 * A REMEDY IS A DOOR OR A LABEL, NEVER A TOKEN. The server's `destination` is
 * a machine token (`route:widget-list`, `header:X-Org`); a reader cannot say it
 * back to anybody, so it is never printed. A `route:` remedy whose operation a
 * page draws is a live link to that page (the route table decides, through
 * `@/kit/remedy-door`); every other remedy is its label alone. Either way
 * the token rides in `data-destination` for the machine.
 *
 * THE SEAT. A verb's refusal sits directly under the act's row, and the panel
 * says which row with `data-seat`. The prop does that and nothing else.
 */

import { REFUSAL_WORDS } from "@/copy/refusals";
import { AlertPanel } from "@/primitives/alert-panel";
import { remedyDoor } from "@/kit/remedy-door";
import type { SurfaceKey } from "@/kit/routes";
import type { Refusal, WireRemedy } from "@/kit/state";
import { unhandledRefusal } from "@/kit/state";
import type { Place } from "@/kit/verbs";

/** The ONE act a panel may offer. Singular: a refusal is not a menu. */
export type RefusalAct = { readonly label: string; readonly href: string };

/** A surface's own words; each one it leaves out is `REFUSAL_WORDS`'. */
export type RefusalWords = {
    /** The panel's first line — what happened, in the surface's own voice. */
    readonly label?: string;
    /** The heading over the server's remedies, when there are any. */
    readonly remedies?: string;
};

export type RefusalPanelProps = {
    readonly refusal: Refusal;
    /** A surface's own voice, where it differs from `REFUSAL_WORDS`; absent, the defaults speak. */
    readonly words?: RefusalWords;
    /** The refused word of the act this refusal answers (the verb table's `refused`); it is the first line. */
    readonly refused?: string | undefined;
    readonly act?: RefusalAct;
    /** The place of the act this refusal answers (`record-acts`, `sheet-foot`, …). */
    readonly seat?: Place;
    /**
     * The surface the panel is drawn on, so a remedy's door is that surface's
     * row: REQUIRED, like every route-table reader's — a staff screen passes
     * `STAFF_SURFACE`, a surface's own screens their key. A panel handed no
     * surface would read the whole table, where the first row that draws an
     * operation wins.
     */
    readonly surface: SurfaceKey;
};

export function RefusalPanel({ refusal, words, refused, act, seat, surface }: RefusalPanelProps) {
    const label = words?.label ?? refused ?? (refusal.kind === "registry" ? REFUSAL_WORDS.errorLabel : REFUSAL_WORDS.transportLabel);
    switch (refusal.kind) {
        case "registry":
            return (
                <AlertPanel seat={seat}>
                    <Said label={label} fact={refusal.refusal.detail} code={refusal.refusal.code} closing={false} />
                    <Remedies remedies={refusal.refusal.remedies} heading={words?.remedies ?? REFUSAL_WORDS.remedies} surface={surface} />
                    <Act act={act} />
                </AlertPanel>
            );
        case "transport":
            return (
                <AlertPanel seat={seat}>
                    <Said label={label} fact={refusal.detail} code={refusal.code} closing />
                    <Act act={act} />
                </AlertPanel>
            );
    }
    return unhandledRefusal(refusal);
}

/*
 * THE LINES' PAINT IS INLINE, AND THAT IS THE BOOK'S RULE, NOT A GAP: this is
 * the one renderer every face draws a refusal with, and a sheet two faces want
 * belongs to no face directory (patterns.md §26), while the box is the
 * primitive's (`@/primitives/alert-panel`). Each line below is token-only.
 */

/** The label line, the fact line and the code — the server's words, verbatim, under the surface's label. */
function Said({ label, fact, code, closing }: { readonly label: string; readonly fact: string; readonly code: string; readonly closing: boolean }) {
    return (
        <>
            <p
                // paint: the one renderer's label line; no face sheet holds a renderer every face draws (§26).
                style={{ margin: "0 0 var(--space-1)", fontWeight: 600 }}
            >
                {label}
            </p>
            <p
                // paint: the one renderer's fact line; no face sheet holds a renderer every face draws (§26).
                style={{ margin: "0 0 var(--space-2)" }}
            >
                {fact}
            </p>
            <p
                // paint: the code's line closes the panel or leads to the remedies; no face sheet holds it (§26).
                style={{ margin: closing ? 0 : "0 0 var(--space-2)" }}
            >
                <code
                    // paint: the code in the mono face at the facts size; no face sheet holds it (§26).
                    style={{ fontFamily: "var(--font-mono)", fontSize: "var(--type-facts)", color: "var(--muted)" }}
                >
                    {code}
                </code>
            </p>
        </>
    );
}

/**
 * The one act, as a LINK.
 *
 * `primitives/` holds no button on purpose — a button primitive there would be this
 * template's taste exported into every product built on it — so the act is an
 * anchor wearing the token accent that `tokens.css` already declares for every
 * link on the page. A product that fills `primitives/` renders it as its own
 * button and nothing above this line moves.
 */
function Act({ act }: { readonly act: RefusalAct | undefined }) {
    if (act === undefined) return null;
    return (
        <p
            // paint: the one act's line under the panel's last; no face sheet holds a renderer every face draws (§26).
            style={{ margin: "var(--space-3) 0 0" }}
        >
            <a
                href={act.href}
                // paint: the act's weight; its colour is every link's (`tokens.css`); no face sheet holds it (§26).
                style={{ fontWeight: 600 }}
            >
                {act.label}
            </a>
        </p>
    );
}

/** The server's remedies, composed once server-side so a screen and an agent
 *  offer the same way out. Rendered, never rewritten. */
function Remedies({
    remedies,
    heading,
    surface,
}: {
    readonly remedies: WireRemedy[] | undefined;
    readonly heading: string;
    readonly surface: SurfaceKey;
}) {
    if (remedies === undefined || remedies.length === 0) return null;
    return (
        <>
            <p
                // paint: the remedies' heading at the facts size; no face sheet holds a renderer every face draws (§26).
                style={{ margin: "0 0 var(--space-1)", fontSize: "var(--type-facts)", color: "var(--muted)" }}
            >
                {heading}
            </p>
            <ul
                // paint: the remedies' list, indented one step; no face sheet holds a renderer every face draws (§26).
                style={{ margin: 0, paddingLeft: "var(--space-3)" }}
            >
                {remedies.map((remedy) => (
                    <li key={`${remedy.destination}:${remedy.label}`}>
                        <RemedyDoorView remedy={remedy} surface={surface} />
                    </li>
                ))}
            </ul>
        </>
    );
}

/** One remedy: a live link when the route table maps it, else the label. */
function RemedyDoorView({ remedy, surface }: { readonly remedy: WireRemedy; readonly surface: SurfaceKey }) {
    const door = remedyDoor(remedy, undefined, surface);
    if (door.kind === "link") {
        return (
            <a href={door.href} data-destination={door.destination}>
                {door.label}
            </a>
        );
    }
    return <span data-destination={door.destination}>{door.label}</span>;
}
