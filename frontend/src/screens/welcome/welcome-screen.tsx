// patterns: template placeholder — words owned
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
import type { Refusal, SurfaceState } from "@/screens/state";
import { unhandledState } from "@/screens/state";
import { RefusalPanel } from "@/screens/refusal-panel";
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
            <h1 style={{ fontSize: "var(--type-title)", margin: `0 0 var(--space-3)`, color: "var(--ink)" }}>{C.title}</h1>
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
                <h2 style={{ fontSize: "var(--type-label)", textTransform: "uppercase", letterSpacing: "var(--type-label-tracking)", color: "var(--muted)", margin: `0 0 var(--space-1)` }}>
                    {C.hatAsked}
                </h2>
                <p style={{ margin: `0 0 var(--space-2)`, fontFamily: "var(--font-mono)", color: "var(--ink)" }}>
                    {hat === null ? C.hatDefault : hat}
                </p>
                <p style={{ margin: 0, fontSize: "var(--type-facts)", color: "var(--muted)" }}>{C.hatNote}</p>
            </section>

            <h2 style={{ fontSize: "var(--type-section)", margin: `0 0 var(--space-2)`, color: "var(--ink)" }}>{C.organizations}</h2>
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
            return <ScreenRefusal refusal={state.refusal} />;
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
 * THE PANEL ITSELF IS `@/screens/refusal-panel`, the ONE refusal renderer
 * (design J4). This screen owns only the WORDS: which label goes over which
 * member of the union. The shape — registry shows the server's detail, code
 * and remedies verbatim; transport shows this client's own two words and no
 * code the server did not say — belongs to the panel, and a second copy of it
 * here would be a second account of one event.
 */
function ScreenRefusal({ refusal }: { readonly refusal: Refusal }) {
    return (
        <RefusalPanel
            refusal={refusal}
            words={{
                label: refusal.kind === "registry" ? C.errorLabel : C.transportLabel,
                remedies: C.remedies,
            }}
        />
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
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--type-facts)", color: "var(--muted)" }}>
                        {organization.slug}
                    </span>{" "}
                    <span style={{ fontSize: "var(--type-facts)", color: "var(--muted)" }}>
                        {C.columnDepth} {organization.depth}
                    </span>
                </li>
            ))}
        </ul>
    );
}
