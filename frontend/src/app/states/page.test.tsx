import { render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OBSERVABLE_SOCKET_CLOSE_STATES, OBSERVED_FRAME, socketCloseRefusal } from "@/api/socket-close";
import { SOCKET_CLOSE_COPY } from "@/copy/refusals";
import StatesPage from "@/app/states/page";

/**
 * THE STATE WALK, tested where it is composed.
 *
 * It is the ROUTE that is under test and not the panel alone, and house rule
 * 51 is why: `api` is off the layer chain and reachable only from `app`, so a
 * test that seeds a close-frame state from the seam belongs beside the route
 * that does the same thing. That is not a workaround — it is the honest unit.
 * The walk is what the criteria name (`/states` renders both states), the walk
 * is what the verifier drives in a browser, and a panel test that hand-built
 * its own refusal would be the mirror fe-conventions §6.7 warns about: a
 * fixture built from the thing that reads it confirms whatever it is shown.
 *
 * This tier is NECESSARY AND NEVER SUFFICIENT. jsdom has no layout, no colour
 * and no hydration; the rendered check on a real browser is the other half and
 * it is the verifier's (A10.3).
 */
function walk() {
    const { container } = render(<StatesPage />);
    return container;
}

function section(container: HTMLElement, story: string): HTMLElement {
    const el = container.querySelector(`[data-story="${story}"]`);
    if (el === null) {
        throw new Error(`/states renders no section for ${story}`);
    }
    return el as HTMLElement;
}

describe("/states walks the close-frame states", () => {
    it("renders a section for every state the vocabulary says is observable", () => {
        const container = walk();
        for (const state of OBSERVABLE_SOCKET_CLOSE_STATES) {
            expect(section(container, state)).toBeDefined();
        }
    });

    it("labels each section with the close code a REAL client is handed", () => {
        // The verifier's own hook, and the thing that makes a screenshot
        // self-labelling: 1006 is the handshake rejection (no reason, no
        // server code), 4410 is the post-accept kick.
        const container = walk();
        expect(section(container, "socket_handshake_rejected").getAttribute("data-close-code")).toBe("1006");
        expect(section(container, "socket_credential_withdrawn").getAttribute("data-close-code")).toBe("4410");
    });

    it("renders a handshake rejection as the design words it", () => {
        const panel = within(section(walk(), "socket_handshake_rejected"));
        expect(panel.getByText("Couldn't connect")).toBeDefined();
        expect(panel.getByText("Sign in and try again.")).toBeDefined();
    });

    it("renders a withdrawn credential as the design words it", () => {
        const panel = within(section(walk(), "socket_credential_withdrawn"));
        expect(panel.getByText("Your access here ended")).toBeDefined();
        expect(
            panel.getByText(
                "This connection was closed because the credential behind it was withdrawn. Sign in again to continue.",
            ),
        ).toBeDefined();
    });

    it.each([...OBSERVABLE_SOCKET_CLOSE_STATES])("%s offers exactly ONE act, and it is a link", (state) => {
        const acts = [...section(walk(), state).querySelectorAll("a")];
        expect(acts).toHaveLength(1);
        const [only] = acts;
        expect(only?.textContent).toBe(SOCKET_CLOSE_COPY[state].act);
        expect(only?.getAttribute("href")).toBe("/accounts/login/?next=%2Fstates");
    });

    it.each([...OBSERVABLE_SOCKET_CLOSE_STATES])("%s renders no remedies — a close frame has no envelope", (state) => {
        expect(section(walk(), state).querySelector("ul")).toBeNull();
    });

    it.each([...OBSERVABLE_SOCKET_CLOSE_STATES])("%s renders no literal `undefined`", (state) => {
        expect(section(walk(), state).textContent ?? "").not.toContain("undefined");
    });

    it("still walks the four SurfaceStates it walked before", () => {
        // The four-state walk is its own criterion and the close-frame walk
        // must not cost it a section: an added state that quietly displaced an
        // existing one is a regression nobody would look for.
        const container = walk();
        const stories = [...container.querySelectorAll("[data-story]")].map((el) => el.getAttribute("data-story"));
        expect(stories).toEqual(["Loading", "Empty", "Error", "Ready", ...OBSERVABLE_SOCKET_CLOSE_STATES]);
    });
});

describe("no registry code is synthesised for a close frame", () => {
    it.each([...OBSERVABLE_SOCKET_CLOSE_STATES])("%s rides error(E) as a TRANSPORT refusal", (state) => {
        expect(socketCloseRefusal(OBSERVED_FRAME[state])?.kind).toBe("transport");
    });
});

describe("A10.2 — no automatic reconnect", () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it("schedules nothing when the walk renders both close states", () => {
        vi.useFakeTimers();
        walk();
        expect(vi.getTimerCount()).toBe(0);
    });
});

describe("accessibility", () => {
    it.each([...OBSERVABLE_SOCKET_CLOSE_STATES])("%s has no axe violations", async (state) => {
        const results = await axe.run(section(walk(), state), {
            // jsdom cannot compute colour, so contrast cannot be judged here at
            // all; that half belongs to the rendered census on a real browser.
            rules: { "color-contrast": { enabled: false } },
        });
        expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
});

describe("the walk is the instrument, not a product surface", () => {
    it("names every section of the walk so a screenshot can be re-taken", () => {
        // `:scope >` on purpose: a SCREEN may have sections of its own inside a
        // walk section (the welcome screen's "Acting as" block is one), and
        // those are the screen's business. What must be named is every section
        // the WALK itself emits.
        for (const el of walk().querySelectorAll(":scope > section")) {
            expect(el.getAttribute("data-story")).toBeTruthy();
        }
        expect(walk().querySelectorAll(":scope > section")).toHaveLength(
            4 + OBSERVABLE_SOCKET_CLOSE_STATES.length,
        );
    });

    it("keeps `screen` reachable for a debugging run", () => {
        render(<StatesPage />);
        expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
    });
});
