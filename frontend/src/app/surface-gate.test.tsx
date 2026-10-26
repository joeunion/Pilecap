import { act, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Answer } from "@/api/client";
import type { BootedSurface } from "@/api/surface";
import { SurfaceGate, SurfaceGuard, SurfaceProvider, useSurface } from "@/app/surface-gate";
import { SURFACE_COPY } from "@/copy/refusals";
import { ROUTE_TABLE, type RouteRow } from "@pilecap/ui/routes";
import type { Refusal } from "@pilecap/ui/state";

const world = vi.hoisted(() => ({ answer: null as Promise<unknown> | null, asks: 0, asked: [] as unknown[], pathname: "/welcome" }));

// The one exchange the gate makes; `booted` (the shape check) stays real.
vi.mock("@/api/client", async (original) => ({
    ...(await original<typeof import("@/api/client")>()),
    request: (...args: unknown[]) => {
        world.asks += 1;
        world.asked = args;
        return world.answer;
    },
}));
vi.mock("next/navigation", () => ({ usePathname: () => world.pathname }));

/** The server's answer, held until the test releases it. */
function answers(answer: Answer<unknown>): () => void {
    let release: (value: Answer<unknown>) => void = () => undefined;
    world.answer = new Promise((done) => {
        release = done;
    });
    return () => release(answer);
}

const PAGE = <p data-testid="page">a page</p>;

/** A page that says what the gate handed it: the surface's key, or that it is unknown. */
function SurfaceProbe() {
    const surface = useSurface();
    return <p data-testid="probe">{surface === undefined ? "unknown" : surface.surface}</p>;
}
const STAFF: BootedSurface = { surface: "staff", screens: "*", tenant_rule: "addressed" };
const CUSTOMER: BootedSurface = { surface: "customer", screens: [], tenant_rule: "membership" };

function noindex(): Element | null {
    return document.querySelector('meta[name="robots"][content="noindex"]');
}

afterEach(() => {
    world.asks = 0;
    world.pathname = "/welcome";
});

/** Whether a row names the staff surface (or every surface). */
function onStaff(row: RouteRow): boolean {
    return row.surfaces === "*" || row.surfaces.includes("staff");
}

/** Whether a row names the customer surface (or every surface). */
function onCustomer(row: RouteRow): boolean {
    return row.surfaces === "*" || row.surfaces.includes("customer");
}

describe("the root layout's gate never holds the page", () => {
    it("renders the page before the answer arrives", () => {
        answers({ kind: "ok", data: STAFF });
        render(<SurfaceGate>{PAGE}</SurfaceGate>);
        expect(screen.getByTestId("page")).toBeTruthy();
    });

    it("asks once, under StrictMode's double mount too", async () => {
        const release = answers({ kind: "ok", data: STAFF });
        render(
            <StrictMode>
                <SurfaceGate>{PAGE}</SurfaceGate>
            </StrictMode>,
        );
        await act(async () => release());
        expect(world.asks).toBe(1);
        // The one path, and no hat: the boot question names a surface, never a person.
        expect(world.asked).toEqual(["/api/v1/surface/", null]);
    });

    // The staff face's static pages: the rows the undeclared staff surface draws.
    it.each(ROUTE_TABLE.filter((row) => !row.path.includes("[") && onStaff(row)).map((row) => [row.path] as const))(
        "on the undeclared surface, %s keeps its page after the answer",
        async (path) => {
            world.pathname = path;
            const release = answers({ kind: "ok", data: STAFF });
            render(<SurfaceGate>{PAGE}</SurfaceGate>);
            await act(async () => release());
            expect(screen.getByTestId("page")).toBeTruthy();
            expect(noindex()).toBeNull();
        },
    );

    it("on a customer surface, a staff page becomes the off-surface seat after the answer", async () => {
        const release = answers({ kind: "ok", data: CUSTOMER });
        render(<SurfaceGate>{PAGE}</SurfaceGate>);
        expect(screen.getByTestId("page")).toBeTruthy();
        await act(async () => release());
        expect(screen.queryByTestId("page")).toBeNull();
        expect(screen.getByRole("alert").textContent).toContain(SURFACE_COPY.offSurface.label);
        expect(noindex()).not.toBeNull();
    });

    // NO ANSWER KEEPS THE PAGE: the page's own operation reports what went
    // wrong, in the page's words. The three ways no answer arrives.
    it.each([
        ["the backend unreachable (a thrown fetch)", { kind: "transport", code: "network_unreachable", detail: "This page could not reach the server." }],
        [
            "the proxy's 500 with the backend down",
            { kind: "transport", code: "network_unreachable", detail: "The server refused this request and the reason did not arrive." },
        ],
        [
            "an address no surface answers at",
            { kind: "registry", refusal: { detail: "No surface answers at this address.", code: "surface_unknown_host", remedies: [] } },
        ],
    ] satisfies readonly (readonly [string, Refusal])[])("no answer — %s: the page stays, the surface unknown, no seat", async (_case, refusal) => {
        const release = answers({ kind: "refused", refusal });
        render(
            <SurfaceGate>
                {PAGE}
                <SurfaceProbe />
            </SurfaceGate>,
        );
        await act(async () => release());
        expect(screen.getByTestId("page")).toBeTruthy();
        expect(screen.getByTestId("probe").textContent).toBe("unknown");
        expect(screen.queryByRole("alert")).toBeNull();
        expect(noindex()).toBeNull();
    });

    it("a 200 that is not the answer is the one could-not-look: the refusal renderer under the surface words, and no page", async () => {
        const release = answers({ kind: "ok", data: { surface: "staff" } });
        render(<SurfaceGate>{PAGE}</SurfaceGate>);
        await act(async () => release());
        expect(screen.queryByTestId("page")).toBeNull();
        expect(screen.getByRole("alert").textContent).toContain(SURFACE_COPY.couldNotLook.label);
    });

    it("a named surface reaches the page through useSurface()", async () => {
        const release = answers({ kind: "ok", data: STAFF });
        render(
            <SurfaceGate>
                <SurfaceProbe />
            </SurfaceGate>,
        );
        expect(screen.getByTestId("probe").textContent).toBe("unknown");
        await act(async () => release());
        expect(screen.getByTestId("probe").textContent).toBe(STAFF.surface);
    });
});

describe("the guard, in a nested position", () => {
    // Every static page the customer surface does not draw — the staff face's.
    it.each(ROUTE_TABLE.filter((row) => !row.path.includes("[") && !onCustomer(row)).map((row) => [row.path] as const))(
        "on the customer surface, %s draws the off-surface seat with noindex",
        (path) => {
            world.pathname = path;
            render(
                <SurfaceProvider surface={CUSTOMER}>
                    <section>
                        <SurfaceGuard>{PAGE}</SurfaceGuard>
                    </section>
                </SurfaceProvider>,
            );
            expect(screen.queryByTestId("page")).toBeNull();
            const panel = screen.getByRole("alert").textContent ?? "";
            expect(panel).toContain(SURFACE_COPY.offSurface.label);
            expect(panel).toContain(SURFACE_COPY.offSurface.detail("customer"));
            expect(noindex()).not.toBeNull();
            // Client state, not a wire refusal: no code is drawn, borrowed or made up.
            expect(screen.getByRole("alert").querySelector("code")).toBeNull();
        },
    );

    it("on the staff surface, and before any answer, the page is drawn", () => {
        const { unmount } = render(
            <SurfaceProvider surface={STAFF}>
                <SurfaceGuard>{PAGE}</SurfaceGuard>
            </SurfaceProvider>,
        );
        expect(screen.getByTestId("page")).toBeTruthy();
        unmount();
        render(
            <SurfaceProvider surface={undefined}>
                <SurfaceGuard>{PAGE}</SurfaceGuard>
            </SurfaceProvider>,
        );
        expect(screen.getByTestId("page")).toBeTruthy();
        expect(noindex()).toBeNull();
    });
});
