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
import type { Refusal, SurfaceState } from "@pilecap/ui/state";
import { unhandledState } from "@pilecap/ui/state";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { STAFF_SURFACE } from "@pilecap/ui/routes";
import { WELCOME_COPY as C } from "@/copy/welcome";
import { StillLine } from "@pilecap/ui/still-line";
import "@/screens/welcome/welcome-face.css";

export type WelcomeScreenProps = {
    /** The four states. A missing branch below is a `tsc` error, not a habit. */
    readonly state: SurfaceState<OrganizationPage>;
    /** The hat this page ASKED FOR — `null` means it sent no header at all. */
    readonly hat: string | null;
};

export function WelcomeScreen({ state, hat }: WelcomeScreenProps) {
    return (
        <main className="welcome-page">
            <h1 className="welcome-title">{C.title}</h1>
            <p className="welcome-lede">{C.placeholder}</p>
            <p className="welcome-lede welcome-lede-last">{C.parity}</p>

            <section aria-label={C.hatAsked} className="welcome-hat">
                <h2 className="welcome-hat-label">{C.hatAsked}</h2>
                <p className="welcome-hat-value">{hat === null ? C.hatDefault : hat}</p>
                <p className="welcome-hat-note">{C.hatNote}</p>
            </section>

            <h2 className="welcome-section">{C.organizations}</h2>
            {renderState(state)}
        </main>
    );
}

function renderState(state: SurfaceState<OrganizationPage>) {
    switch (state.kind) {
        case "loading":
            return <WelcomeSkeleton />;
        case "empty":
            // This landing's empty always carries its act (the route hands one);
            // an empty without one would be a sentence the surface does not own.
            return state.nextAct === undefined ? null : (
                <NextActPrompt label={state.nextAct.label} detail={state.nextAct.detail} />
            );
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
            <p className="welcome-reading">{C.loading}</p>
            {[0, 1, 2].map((row) => (
                <StillLine key={row} />
            ))}
        </div>
    );
}

/** `empty` PROPOSES the next act. Reporting emptiness alone says nothing new. */
function NextActPrompt({ label, detail }: { readonly label: string; readonly detail: string | undefined }) {
    return (
        <div className="welcome-next">
            <p className="welcome-next-label">{label}</p>
            {detail === undefined ? null : <p className="welcome-next-detail">{detail}</p>}
        </div>
    );
}

/**
 * `error` carries the server's own `Refusal`, never a string — a component
 * holding a string can only make a sentence up, and it will.
 *
 * THE PANEL ITSELF IS `@pilecap/ui/refusal-panel`, the ONE refusal renderer
 * (design J4), and so are its words: this screen says the refusal the way
 * every surface does, so it passes none and the panel's defaults speak. The
 * shape — registry shows the server's detail, code and remedies verbatim;
 * transport shows this client's own words and no code the server did not say
 * — belongs to the panel, and a second copy of it here would be a second
 * account of one event.
 */
function ScreenRefusal({ refusal }: { readonly refusal: Refusal }) {
    return <RefusalPanel surface={STAFF_SURFACE} refusal={refusal} />;
}

function OrganizationList({ items }: { readonly items: readonly Organization[] }) {
    return (
        <ul className="welcome-rows">
            {items.map((organization) => (
                <li key={organization.id}>
                    <span className="welcome-name">{organization.name}</span>{" "}
                    <span className="welcome-slug">{organization.slug}</span>{" "}
                    <span className="welcome-depth">
                        {C.columnDepth} {organization.depth}
                    </span>
                </li>
            ))}
        </ul>
    );
}
