// patterns: §15
/**
 * THE ONE REFUSAL RENDERER.
 *
 * It was a private function inside `src/screens/welcome/welcome-screen.tsx`
 * until a second surface needed it (design J4: the socket close-code panel
 * renders "by the one refusal renderer", and two renderers would be two
 * accounts of one event).
 *
 * IT LIVES IN `screens/` AND NOT IN `components/`, AND THE RULE DECIDES THAT,
 * NOT TASTE. House rule 51 (`js-ingredient-boundary`) excludes the REFUSAL /
 * wire-error vocabulary from its type-only clause "whatever its provenance:
 * it reaches a screen through the surface-state seam, never directly" — and
 * `components/` sits BELOW `screens/`, so a module there can reach that
 * vocabulary through neither door. A renderer whose whole subject is a
 * `Refusal` is therefore a screens-layer module by construction. (Noted as a
 * finding: `components/README.md` still says a component "may import
 * `screens/state.ts`", which rule 51 flags.)
 *
 * IT RENDERS; IT NEVER FETCHES, and it names no HTTP anywhere (fe-conventions
 * §4 Laws 1 and 4). What arrives is a `Refusal`, and the two members of that
 * union are rendered differently ON PURPOSE: the registry member shows the
 * server's own `detail`, `code` and `remedies` verbatim, and the transport
 * member shows this client's own words and NO remedies, because no response
 * existed for the server to put them in.
 *
 * THE WORDS ARE THE CALLER'S. A shared renderer that owned the label would
 * own the sentence too, and the sentence belongs to the surface: "The server
 * refused" on a landing page, "Your access here ended" on a socket that was
 * kicked. The panel owns the SHAPE.
 *
 * A REMEDY IS A DOOR OR A LABEL, NEVER A TOKEN. The server's `destination` is
 * a machine token (`route:widget-list`, `header:X-Org`); a reader cannot say it
 * back to anybody, so it is never printed. A `route:` remedy whose operation a
 * page draws is a live link to that page (the route table decides, through
 * `@/screens/remedy-door`); every other remedy is its label alone. Either way
 * the token rides in `data-destination` for the machine.
 *
 * THE SEAT. A verb's refusal sits directly under the act's row, and the panel
 * says which row with `data-seat`. The prop does that and nothing else.
 */

import { remedyDoor } from "@/screens/remedy-door";
import type { Refusal, WireRemedy } from "@/screens/state";
import { unhandledRefusal } from "@/screens/state";

/** The ONE act a panel may offer. Singular: a refusal is not a menu. */
export type RefusalAct = { readonly label: string; readonly href: string };

export type RefusalWords = {
    /** The panel's first line — what happened, in the surface's own voice. */
    readonly label: string;
    /** The heading over the server's remedies, when there are any. */
    readonly remedies: string;
};

export type RefusalPanelProps = {
    readonly refusal: Refusal;
    readonly words: RefusalWords;
    readonly act?: RefusalAct;
    /** The seat of the act this refusal answers (`record-acts`, `sheet-acts`, …). */
    readonly seat?: string;
};

export function RefusalPanel({ refusal, words, act, seat }: RefusalPanelProps) {
    switch (refusal.kind) {
        case "registry":
            return (
                <div role="alert" data-seat={seat} style={panelStyle}>
                    <p style={{ margin: `0 0 var(--space-1)`, color: "var(--ink)", fontWeight: 600 }}>{words.label}</p>
                    <p style={{ margin: `0 0 var(--space-2)`, color: "var(--ink)" }}>{refusal.refusal.detail}</p>
                    <p style={{ margin: `0 0 var(--space-2)` }}>
                        <code style={codeStyle}>{refusal.refusal.code}</code>
                    </p>
                    <Remedies remedies={refusal.refusal.remedies} heading={words.remedies} />
                    <Act act={act} />
                </div>
            );
        case "transport":
            return (
                <div role="alert" data-seat={seat} style={panelStyle}>
                    <p style={{ margin: `0 0 var(--space-1)`, color: "var(--ink)", fontWeight: 600 }}>{words.label}</p>
                    <p style={{ margin: `0 0 var(--space-2)`, color: "var(--ink)" }}>{refusal.detail}</p>
                    <p style={{ margin: 0 }}>
                        <code style={codeStyle}>{refusal.code}</code>
                    </p>
                    <Act act={act} />
                </div>
            );
    }
    return unhandledRefusal(refusal);
}

/**
 * The one act, as a LINK.
 *
 * `primitives/` ships empty on purpose — a button primitive here would be this
 * template's taste exported into every product built on it — so the act is an
 * anchor wearing the token accent that `tokens.css` already declares for every
 * link on the page. A product that fills `primitives/` renders it as its own
 * button and nothing above this line moves.
 */
function Act({ act }: { readonly act: RefusalAct | undefined }) {
    if (act === undefined) return null;
    return (
        <p style={{ margin: `var(--space-3) 0 0` }}>
            <a href={act.href} style={{ color: "var(--accent)", fontWeight: 600 }}>
                {act.label}
            </a>
        </p>
    );
}

/** The server's remedies, composed once server-side so a screen and an agent
 *  offer the same way out. Rendered, never rewritten. */
function Remedies({ remedies, heading }: { readonly remedies: WireRemedy[] | undefined; readonly heading: string }) {
    if (remedies === undefined || remedies.length === 0) return null;
    return (
        <>
            <p style={{ margin: `0 0 var(--space-1)`, fontSize: "var(--type-facts)", color: "var(--muted)" }}>{heading}</p>
            <ul style={{ margin: 0, paddingLeft: "var(--space-3)", color: "var(--ink)" }}>
                {remedies.map((remedy) => (
                    <li key={`${remedy.destination}:${remedy.label}`}>
                        <RemedyDoorView remedy={remedy} />
                    </li>
                ))}
            </ul>
        </>
    );
}

/** One remedy: a live link when the route table maps it, else the label. */
function RemedyDoorView({ remedy }: { readonly remedy: WireRemedy }) {
    const door = remedyDoor(remedy);
    if (door.kind === "link") {
        return (
            <a href={door.href} data-destination={door.destination} style={{ color: "var(--accent)" }}>
                {door.label}
            </a>
        );
    }
    return <span data-destination={door.destination}>{door.label}</span>;
}

const codeStyle = {
    fontFamily: "var(--font-mono)",
    fontSize: "var(--type-facts)",
    color: "var(--muted)",
} as const;

const panelStyle = {
    border: `1px solid var(--accent)`,
    borderLeft: `3px solid var(--accent)`,
    borderRadius: "var(--radius)",
    padding: "var(--space-3)",
    background: "var(--surface-raised)",
} as const;
