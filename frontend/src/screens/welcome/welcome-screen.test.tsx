import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { REQUIRED_STORY_EXPORTS } from "@/screens/state";
import { Empty, Error as Refused, Loading, Ready } from "@/screens/welcome/welcome-screen.stories";

const STORIES = { Loading, Empty, Error: Refused, Ready } as const;

describe("every authored state renders", () => {
    it.each([...REQUIRED_STORY_EXPORTS])("%s", (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        expect(container.textContent?.length ?? 0).toBeGreaterThan(0);
    });

    it("loading is a DESIGNED render, not an absence", () => {
        // A page whose only "not ready yet" state is absence cannot tell you it
        // is broken. This is the assertion that a skeleton exists at all.
        const { container } = render(<Loading />);
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    });

    it("empty PROPOSES the next act rather than reporting emptiness", () => {
        render(<Empty />);
        expect(screen.getByText(/Sign in to see where you are acting/)).toBeDefined();
    });

    it("error renders the server's own fact, code and remedies — not a sentence this client made up", () => {
        render(<Refused />);
        expect(screen.getByText(/named a place it cannot act in/)).toBeDefined();
        expect(screen.getByText("addressing_header_not_honoured")).toBeDefined();
        expect(screen.getByText(/Check which memberships you actually hold/)).toBeDefined();
    });

    it("ready renders the rows the door answered with", () => {
        render(<Ready />);
        expect(screen.getByText("Northern branch")).toBeDefined();
        expect(screen.getByText("northern-branch")).toBeDefined();
        // Twice on purpose: once as the hat this page ASKED FOR, once as a row
        // the server ANSWERED with. The two are different facts and the screen
        // keeps them apart.
        expect(screen.getAllByText("harbour-office")).toHaveLength(2);
    });
});

describe("nothing renders the literal `undefined`", () => {
    // The shape-agnostic net from fe-conventions §6.7: a hand-typed shape that
    // disagrees with the document renders `undefined` wherever it reached for a
    // field the document does not have. This costs nothing and catches the next
    // one whatever field it reaches for.
    it.each([...REQUIRED_STORY_EXPORTS])("%s", (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        expect(container.textContent ?? "").not.toContain("undefined");
    });
});

describe("the client never resolves authority", () => {
    it("renders no role or membership vocabulary of its own", () => {
        // Criterion: the client carries the hat and never decides it. The one
        // place `membership` may appear on this surface is inside a REMEDY the
        // server composed — which is the server's word, rendered verbatim.
        const { container } = render(<Ready />);
        const text = (container.textContent ?? "").toLowerCase();
        for (const forbidden of ["owner", "administrator", "role:", "is_staff", "superuser"]) {
            expect(text).not.toContain(forbidden);
        }
    });
});

describe("accessibility", () => {
    it.each([...REQUIRED_STORY_EXPORTS])("%s has no axe violations", async (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        const results = await axe.run(container, {
            // jsdom cannot compute colour, so contrast rules cannot be judged
            // here at all. The runtime half of that question belongs to the
            // rendered census on a real browser — declared, not silently
            // skipped.
            rules: { "color-contrast": { enabled: false } },
        });
        expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
});
