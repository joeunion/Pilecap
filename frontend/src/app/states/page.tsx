import { notFound } from "next/navigation";

import type { SocketCloseState } from "@/api/refusals";
import { OBSERVABLE_SOCKET_CLOSE_STATES, OBSERVED_FRAME, signInAct, socketCloseRefusal } from "@/api/socket-close";
import { SocketClosePanel } from "@/screens/socket-close-panel";
import { REQUIRED_STORY_EXPORTS } from "@pilecap/ui/state";
import { Empty, Error as Refused, Loading, Ready } from "@/screens/welcome/welcome-screen.stories";

/**
 * THE STATE WALK — the instrument, not a product surface.
 *
 * fe-conventions §8 requires a SCREENSHOT PER AUTHORED `SurfaceState`, in a real
 * browser, on every route a rung touched: four states authored and one
 * screenshotted is one state proven. Two of the four are not reachable against
 * a seeded world on this operation — a signed-in session's organization tree
 * always contains the hat it is acting as, so `empty` cannot be produced by
 * seeding, and `loading` is over in milliseconds — and a state that cannot be
 * photographed cannot be accepted by an owner looking at pictures.
 *
 * So this route renders the four stories, in the real application, with the
 * real tokens and the real screen. It is **development only**: in a production
 * build it is a 404, so a product that clones this template does not ship a
 * page nobody meant to publish. It is also the only route in this tree that is
 * not part of the journey, and it exists because the alternative is a report
 * that describes rendered evidence instead of carrying it.
 *
 * IT ALSO WALKS THE CLOSE-FRAME STATES (design J4 · A10). Those are not
 * `SurfaceState`s — they are what `error(E)` carries when a SOCKET ends — and
 * they are even harder to photograph than `empty`: producing one for real needs
 * an open socket and a revoked credential. The walk is DERIVED from the
 * vocabulary (`OBSERVABLE_SOCKET_CLOSE_STATES`), never hand-listed, and each
 * panel is seeded from the close frame a real client is actually handed
 * (`OBSERVED_FRAME`) through the seam's own mapper — so a section here cannot
 * render a state the mapper would not produce. When the socket learns to accept
 * before it closes, 4401 and 4403 gain states and sections appear here
 * with nothing on this page edited.
 *
 * The verifier's hooks are the `data-story` and `data-close-code` attributes:
 * `[data-close-code="1006"]` is the handshake rejection and
 * `[data-close-code="4410"]` is the withdrawn credential.
 */
export default function StatesPage() {
    if (process.env.NODE_ENV === "production") {
        notFound();
    }

    const stories = [Loading, Empty, Refused, Ready] as const;

    return (
        <>
            {stories.map((Story, index) => (
                <section key={REQUIRED_STORY_EXPORTS[index]} data-story={REQUIRED_STORY_EXPORTS[index]}>
                    <Story />
                </section>
            ))}
            {OBSERVABLE_SOCKET_CLOSE_STATES.map((state) => (
                <SocketCloseSection key={state} state={state} />
            ))}
        </>
    );
}

/**
 * One close-frame state, seeded by the frame a real client observes for it.
 *
 * The `null` branch is not dead code and is not defensive: `socketCloseRefusal`
 * answers `null` for a close that is not an error at all, and a state in the
 * walk whose seed frame produced no refusal would be a disagreement between the
 * walk and the mapper. It renders the disagreement instead of hiding it.
 */
function SocketCloseSection({ state }: { readonly state: SocketCloseState }) {
    const frame = OBSERVED_FRAME[state];
    const refusal = socketCloseRefusal(frame);
    if (refusal === null) {
        return (
            <section data-story={state} data-close-code={frame.code}>
                <p role="alert">
                    The walk names {state}, and the seam answers with no refusal for close code {frame.code}.
                </p>
            </section>
        );
    }
    return (
        <section data-story={state} data-close-code={frame.code}>
            <SocketClosePanel state={state} refusal={refusal} act={signInAct(state, "/states")} />
        </section>
    );
}
