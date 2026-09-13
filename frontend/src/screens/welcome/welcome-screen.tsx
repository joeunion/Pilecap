/**
 * THE ONE SCREEN. A total function from `SurfaceState` to markup.
 *
 * It fetches nothing (fe-conventions §4, Law 4 — house rule 12's read/write
 * split, translated): the route hands it a state, so every one of its four
 * states can be rendered on demand, in a test, in a story and in a browser,
 * without a network.
 *
 * It also names no HTTP anywhere (Law 1). There is no status code in this file
 * and there cannot be one: what arrives is a `Refusal`, and a refusal carries
 * the server's own words.
 */

import type { Organization, OrganizationPage } from "@/api/client";
import type { Refusal, SurfaceState, WireRemedy } from "@/screens/state";
import { unhandledRefusal, unhandledState } from "@/screens/state";
import { WELCOME_COPY as C } from "@/copy/welcome";

export type WelcomeScreenProps = {
    /** The four states. A missing branch below is a `tsc` error, not a habit. */
    readonly state: SurfaceState<OrganizationPage>;
    /** The hat this page ASKED FOR — `null` means it sent no header at all. */
    readonly hat: string | null;
};

export function WelcomeScreen({ state, hat }: WelcomeScreenProps) {
    return (
        <main
            style={{
                maxWidth: "var(--measure)",
                margin: "0 auto",
                padding: "var(--space-4) var(--space-3)",
                fontFamily: "var(--font-body)",
            }}
        >
            <h1 style={{ fontSize: "1.5rem", margin: `0 0 var(--space-3)`, color: "var(--ink)" }}>{C.title}</h1>
            <p style={{ color: "var(--muted)", margin: `0 0 var(--space-2)` }}>{C.placeholder}</p>
            <p style={{ color: "var(--muted)", margin: `0 0 var(--space-4)` }}>{C.parity}</p>

            <section
                aria-label={C.hatAsked}
                style={{
                    background: "var(--surface-raised)",
                    border: `1px solid var(--faint)`,
                    borderRadius: "var(--radius)",
                    padding: "var(--space-3)",
                    marginBottom: "var(--space-4)",
                }}
            >
                <h2 style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", margin: `0 0 var(--space-1)` }}>
                    {C.hatAsked}
                </h2>
                <p style={{ margin: `0 0 var(--space-2)`, fontFamily: "var(--font-mono)", color: "var(--ink)" }}>
                    {hat === null ? C.hatDefault : hat}
                </p>
                <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>{C.hatNote}</p>
            </section>

            <h2 style={{ fontSize: "1rem", margin: `0 0 var(--space-2)`, color: "var(--ink)" }}>{C.organizations}</h2>
            {renderState(state)}
        </main>
    );
}

function renderState(state: SurfaceState<OrganizationPage>) {
    switch (state.kind) {
        case "loading":
            return <WelcomeSkeleton />;
        case "empty":
            return <NextActPrompt label={state.nextAct.label} detail={state.nextAct.detail} />;
        case "error":
            return <RefusalPanel refusal={state.refusal} />;
        case "ready":
            return <OrganizationList items={state.data.items} />;
    }
    // Unreachable while the union has four members; a fifth would land here as a
    // compile error rather than as a silently missing branch.
    return unhandledState(state);
}

/**
 * The `loading` render, DESIGNED. A page whose only "not ready yet" state is
 * absence cannot tell you it is broken — which is how a never-hydrated page
 * ships looking perfect.
 */
function WelcomeSkeleton() {
    return (
        <div aria-busy="true" aria-live="polite">
            <p style={{ color: "var(--muted)", margin: `0 0 var(--space-2)` }}>{C.loading}</p>
            {[0, 1, 2].map((row) => (
                <div
                    key={row}
                    style={{
                        height: "1.25rem",
                        marginBottom: "var(--space-2)",
                        background: "var(--faint)",
                        borderRadius: "var(--radius)",
                    }}
                />
            ))}
        </div>
    );
}

/** `empty` PROPOSES the next act. Reporting emptiness alone says nothing new. */
function NextActPrompt({ label, detail }: { readonly label: string; readonly detail: string | undefined }) {
    return (
        <div
            style={{
                border: `1px dashed var(--faint)`,
                borderRadius: "var(--radius)",
                padding: "var(--space-3)",
                background: "var(--surface-raised)",
            }}
        >
            <p style={{ margin: `0 0 var(--space-1)`, color: "var(--ink)", fontWeight: 600 }}>{label}</p>
            {detail === undefined ? null : <p style={{ margin: 0, color: "var(--muted)" }}>{detail}</p>}
        </div>
    );
}

/**
 * `error` carries the server's own `Refusal`, never a string — a component
 * holding a string can only make a sentence up, and it will.
 *
 * The two members of the union are rendered differently ON PURPOSE: the
 * registry member shows the server's `code`, `detail` and `remedies` verbatim;
 * the transport member shows this client's own two words and NO code, because
 * no response existed and inventing a registry code for it would fail open.
 */
function RefusalPanel({ refusal }: { readonly refusal: Refusal }) {
    switch (refusal.kind) {
        case "registry":
            return (
                <div role="alert" style={panelStyle}>
                    <p style={{ margin: `0 0 var(--space-1)`, color: "var(--ink)", fontWeight: 600 }}>{C.errorLabel}</p>
                    <p style={{ margin: `0 0 var(--space-2)`, color: "var(--ink)" }}>{refusal.refusal.detail}</p>
                    <p style={{ margin: `0 0 var(--space-2)`, fontFamily: "var(--font-mono)", fontSize: "0.85rem", color: "var(--muted)" }}>
                        {refusal.refusal.code}
                    </p>
                    <Remedies remedies={refusal.refusal.remedies} />
                </div>
            );
        case "transport":
            return (
                <div role="alert" style={panelStyle}>
                    <p style={{ margin: `0 0 var(--space-1)`, color: "var(--ink)", fontWeight: 600 }}>{C.transportLabel}</p>
                    <p style={{ margin: `0 0 var(--space-2)`, color: "var(--ink)" }}>{refusal.detail}</p>
                    <p style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: "0.85rem", color: "var(--muted)" }}>
                        {refusal.code}
                    </p>
                </div>
            );
    }
    return unhandledRefusal(refusal);
}

/** The server's remedies, composed once server-side so a screen and an agent
 *  offer the same way out. Rendered, never rewritten. */
function Remedies({ remedies }: { readonly remedies: WireRemedy[] | undefined }) {
    if (remedies === undefined || remedies.length === 0) return null;
    return (
        <>
            <p style={{ margin: `0 0 var(--space-1)`, fontSize: "0.85rem", color: "var(--muted)" }}>{C.remedies}</p>
            <ul style={{ margin: 0, paddingLeft: "var(--space-3)", color: "var(--ink)" }}>
                {remedies.map((remedy) => (
                    <li key={`${remedy.destination}:${remedy.label}`}>
                        {remedy.label}{" "}
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: "var(--muted)" }}>
                            {remedy.destination}
                        </span>
                    </li>
                ))}
            </ul>
        </>
    );
}

function OrganizationList({ items }: { readonly items: readonly Organization[] }) {
    return (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {items.map((organization) => (
                <li
                    key={organization.id}
                    style={{
                        background: "var(--surface-raised)",
                        border: `1px solid var(--faint)`,
                        borderRadius: "var(--radius)",
                        padding: "var(--space-2) var(--space-3)",
                        marginBottom: "var(--space-2)",
                    }}
                >
                    <span style={{ color: "var(--ink)", fontWeight: 600 }}>{organization.name}</span>{" "}
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.85rem", color: "var(--muted)" }}>
                        {organization.slug}
                    </span>{" "}
                    <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                        {C.columnDepth} {organization.depth}
                    </span>
                </li>
            ))}
        </ul>
    );
}

const panelStyle = {
    border: `1px solid var(--accent)`,
    borderLeft: `3px solid var(--accent)`,
    borderRadius: "var(--radius)",
    padding: "var(--space-3)",
    background: "var(--surface-raised)",
} as const;
