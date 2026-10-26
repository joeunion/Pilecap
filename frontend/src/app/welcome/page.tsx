"use client";

/**
 * THE ONE JOURNEY: sign in, and land here.
 *
 * THE ROUTE FETCHES; THE SCREEN RENDERS (fe-conventions §4, Law 4). Everything
 * this file knows about the backend it knows through `@/api/client`, which is
 * the only module in this tree that may know a backend exists at all.
 *
 * A ROUTE POSITIONS; ONLY A COMPONENT PAINTS (§2). There is deliberately not
 * one style, class or piece of markup below — a missing ingredient stops a
 * rung; it is never a licence to inline one.
 */

import { useEffect, useRef, useState } from "react";

import { listOrganizations } from "@/api/client";
import type { OrganizationPage } from "@/api/client";
import type { SurfaceState } from "@pilecap/ui/state";
import { WELCOME_COPY } from "@/copy/welcome";
import { WelcomeScreen } from "@/screens/welcome/welcome-screen";

export default function WelcomePage() {
    const [state, setState] = useState<SurfaceState<OrganizationPage>>({ kind: "loading" });
    const [hat, setHat] = useState<string | null>(null);

    // THE ONE-SHOT, AND IT HAS NO LIVE FLAG — on purpose, and the pair is
    // fe-conventions §6.3 + §6.4. React 19 StrictMode mounts effects twice in
    // development. The ref guard stops pass 2 from starting a second read; the
    // customary `let live = true` cleanup ON TOP of that guard is the fatal
    // combination, because pass 1's cleanup then throws pass 1's own answer
    // away and the surface sits on a skeleton for ever. A ref-guarded one-shot
    // gets no live flag; an effect that legitimately re-runs keeps one.
    const read = useRef(false);
    useEffect(() => {
        if (read.current) return;
        read.current = true;

        // The hat is a parameter of the operation, read from the URL this page
        // was opened with. Read here rather than during render because there is
        // no `window` while this renders on the server, and a first render that
        // disagrees with the server's is a hydration mismatch.
        const asked = new URLSearchParams(window.location.search).get("org");
        const acting = asked === null || asked.trim() === "" ? null : asked;
        setHat(acting);

        void listOrganizations(acting).then((answer) => {
            if (answer.kind === "refused") {
                setState({ kind: "error", refusal: answer.refusal });
                return;
            }
            if (answer.data.items.length === 0) {
                setState({
                    kind: "empty",
                    nextAct: { label: WELCOME_COPY.emptyLabel, detail: WELCOME_COPY.emptyDetail },
                });
                return;
            }
            setState({ kind: "ready", data: answer.data });
        });
    }, []);

    return <WelcomeScreen state={state} hat={hat} />;
}
