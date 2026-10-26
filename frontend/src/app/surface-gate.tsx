"use client";

/**
 * THE FACE ASKS WHICH SURFACE IT IS — AND NEVER HOLDS A PAGE WHILE IT ASKS.
 *
 * One application serves every surface of the product (staff at one host,
 * customers at another). Which of its pages a host draws is the route table's
 * `surfaces` column read against the surface the SERVER names for this address
 * (`@/api/surface`) — never against the address the browser shows, which
 * would be a second resolver of the host.
 *
 * THE PAGE RENDERS FIRST. `SurfaceGate` renders its children at once, asks the
 * server once (a ref-guarded one-shot, fe-conventions §6.3/§6.4), and hands the
 * answer down through `SurfaceProvider`; before the answer every reader is
 * handed `undefined` and answers the whole route table — the answer a product
 * that declares no surface gets — so the prerendered page is the page it
 * always was. After the answer:
 *
 * * a page the named surface draws stays as it is;
 * * a page it does not draw is replaced by the off-surface seat
 *   (`SurfaceGuard`): the face's own words and a `noindex` meta — client
 *   state the FACE draws, answered HTTP 200, carrying no wire refusal code
 *   (the operation behind the page answers the server's own 404, and a page
 *   with no operation has no code to borrow);
 * * NO ANSWER KEEPS THE PAGE. An unreachable backend, or any refusal instead of
 *   an answer, leaves the surface unknown (`useSurface()` is `undefined`, the
 *   whole table) and the page on screen: its own operation fails on its own
 *   terms and draws its own error seat, in its own words — "the backend is
 *   down" is the page's truth to tell, and a gate that replaced every page
 *   with one seat blanked the static ones too. Unknown is never `staff`.
 * * A 200 the gate cannot read as the boot question's answer is the one
 *   could-not-look: the server answered and said something that is not a
 *   surface, so the face refuses to guess and draws the refusal renderer under
 *   `SURFACE_COPY.couldNotLook`, with no page.
 *
 * WHY THE SEAT IS NOT A 404 — two walls, and neither is taste. (1) Next refuses
 * `notFound()` thrown at root-layout level: error E192, "notFound() is not
 * allowed to use in root layout", raised by
 * `next/dist/client/components/dev-root-http-access-fallback-boundary.js`; the
 * only not-found boundary is the one the router puts INSIDE a layout's
 * `children` slot (`next/dist/client/components/layout-router.js`, the
 * `HTTPAccessFallbackBoundary` around each child segment), and in a production
 * build the root layout has only the global-error boundary above it. (2) This
 * is a client component: during the server render it cannot know the request's
 * Host, and reading the Host on the server (`headers()`) would render every
 * page under the layout per request, losing the static pages the wire serves
 * today. A REAL 404 by surface is therefore a nested SERVER layout's job, for
 * a surface's own route group. Do not move a `notFound()` in here.
 */

import { usePathname } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react";

import { type Answer, request } from "@/api/client";
import { type BootedSurface, booted, SURFACE } from "@/api/surface";
import { SURFACE_COPY } from "@/copy/refusals";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { offSurface, STAFF_SURFACE } from "@pilecap/ui/routes";
import type { Refusal } from "@pilecap/ui/state";

type Asked =
    | { readonly kind: "asking" }
    | { readonly kind: "unknown" }
    | { readonly kind: "unreadable"; readonly refusal: Refusal }
    | { readonly kind: "named"; readonly surface: BootedSurface };

const SurfaceContext = createContext<BootedSurface | undefined>(undefined);

/** Hand `surface` — the server's answer, or `undefined` before it — to every reader below. */
export function SurfaceProvider({
    surface,
    children,
}: {
    readonly surface: BootedSurface | undefined;
    readonly children: ReactNode;
}) {
    return <SurfaceContext.Provider value={surface}>{children}</SurfaceContext.Provider>;
}

/** The surface the server named for this address, or `undefined` until it has answered. */
export function useSurface(): BootedSurface | undefined {
    return useContext(SurfaceContext);
}

/** Render the page at once, ask the server once which surface this is, and hand the answer down. */
export function SurfaceGate({ children }: { readonly children: ReactNode }) {
    const [asked, setAsked] = useState<Asked>({ kind: "asking" });

    // THE ONE-SHOT, AND IT HAS NO LIVE FLAG (fe-conventions §6.3 + §6.4):
    // StrictMode mounts effects twice in development; the ref stops the second
    // ask, and a cleanup that discarded the first answer would leave the face
    // asking for ever.
    const once = useRef(false);
    useEffect(() => {
        if (once.current) return;
        once.current = true;
        void request<unknown>(SURFACE, null).then((answer) => {
            setAsked(settled(answer));
        });
    }, []);

    if (asked.kind === "unreadable") {
        return <RefusalPanel surface={STAFF_SURFACE} refusal={asked.refusal} words={SURFACE_COPY.couldNotLook} />;
    }
    return (
        <SurfaceProvider surface={asked.kind === "named" ? asked.surface : undefined}>
            <SurfaceGuard>{children}</SurfaceGuard>
        </SurfaceProvider>
    );
}

/** What the boot question's answer settles: a named surface, unknown (no answer), or a 200 that is not one. */
function settled(answer: Answer<unknown>): Asked {
    // No answer — the backend unreachable, or a refusal where the answer should
    // be — is the page's to report, through its own operation. Only a 200 is
    // read as the boot question's answer, and only a 200 can be unreadable.
    if (answer.kind === "refused") return { kind: "unknown" };
    const read = booted(answer);
    return read.kind === "refused" ? { kind: "unreadable", refusal: read.refusal } : { kind: "named", surface: read.data };
}

/** The page, or the off-surface seat when the named surface does not draw this path. */
export function SurfaceGuard({ children }: { readonly children: ReactNode }) {
    const surface = useSurface()?.surface;
    const pathname = usePathname();
    if (surface === undefined || !offSurface(pathname, surface)) return children;
    return <OffSurfaceSeat surface={surface} />;
}

/**
 * The off-surface seat: the face's words for a page this surface does not draw, kept out of the index.
 *
 * Client state, never a wire refusal: it carries the surface's KEY and no
 * refusal code — the face decided this, the server said nothing about this
 * page, and a code here would be a server's sentence the server never spoke.
 */
function OffSurfaceSeat({ surface }: { readonly surface: string }) {
    return (
        <>
            <meta name="robots" content="noindex" />
            <section role="alert">
                <h1>{SURFACE_COPY.offSurface.label}</h1>
                <p>{SURFACE_COPY.offSurface.detail(surface)}</p>
            </section>
        </>
    );
}
