import { act, fireEvent, render } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { REQUIRED_STORY_EXPORTS } from "@/screens/state";
import * as stories from "@/screens/widget/widget-import.stories";
import {
    Empty,
    Error as Refused,
    ImportChecking,
    Imported,
    Importing,
    ImportRepeated,
    Loading,
    NothingToImport,
    Ready,
    RefusedImport,
} from "@/screens/widget/widget-import.stories";
import { LATENCY_MS } from "@/screens/widget/widget-list.stories";

afterEach(() => {
    vi.useRealTimers();
});

const STORIES = { Loading, Empty, Error: Refused, Ready } as const;
const MACHINE = [/northern-branch/, /@example\.com/, /[0-9a-f]{8}-[0-9a-f]{4}-/, /undefined/, /external_ref/];

describe("the worked widget import page: every authored state renders", () => {
    it("exports the four and the extras §5 names for the page", () => {
        const exported = Object.keys(stories).filter((name) => /^[A-Z][a-z]/.test(name));
        expect(exported.sort()).toEqual(
            [...REQUIRED_STORY_EXPORTS, "ImportChecking", "ImportPreviewed", "Importing", "Imported", "ImportRepeated", "NothingToImport", "RefusedImport"].sort(),
        );
    });

    it.each([...REQUIRED_STORY_EXPORTS])("%s: the crumb to the list, the page's title, no machine token", (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        expect(container.querySelector("h1")?.textContent).toBe("Import widgets");
        expect(container.querySelector("a.widget-crumb")?.getAttribute("href")).toBe("/example/widgets");
        for (const token of MACHINE) expect(container.textContent ?? "").not.toMatch(token);
    });

    it("choose (Empty): the file field, the columns by their words, Import the page's one primary", () => {
        const { container } = render(<Empty />);
        expect(container.querySelector('input[type="file"]')).not.toBeNull();
        expect(container.textContent).toContain("External Ref, Name, Notes");
        const primaries = container.querySelectorAll('[data-weight="primary"]');
        expect(Array.from(primaries, (el) => [el.textContent, el.getAttribute("data-act")])).toEqual([["Import", "import"]]);
    });

    it("loading: still shapes under aria-busy, no act", () => {
        const { container } = render(<Loading />);
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
        expect(container.querySelectorAll("button")).toHaveLength(0);
    });

    it("previewed (Ready): the counts line, each refused row by number with the server's sentence, Import ⟨n⟩ widgets", () => {
        const { container } = render(<Ready />);
        expect(container.querySelector(".widget-counts")?.textContent).toBe("4 new · 1 changed · 2 unchanged · 1 refused");
        expect(Array.from(container.querySelectorAll("ol li"), (li) => li.textContent)).toEqual(["Row 3: Name cannot be empty."]);
        expect(container.querySelector('[data-weight="primary"]')?.textContent).toBe("Import 5 widgets");
    });

    it("the apply: Importing… on the same button, alive; then the band Imported ⟨n⟩ widgets on ⟨day⟩., the list a door", () => {
        vi.useFakeTimers();
        const { container } = render(<Ready />);
        const apply = container.querySelector('[data-weight="primary"]') as HTMLButtonElement;
        fireEvent.click(apply);
        expect(apply.textContent).toBe("Importing…");
        expect(apply.getAttribute("aria-busy")).toBe("true");
        act(() => {
            vi.advanceTimersByTime(LATENCY_MS);
        });
        const band = container.querySelector('[data-band="imported"]') as HTMLElement;
        expect(band.textContent).toBe("Imported 5 widgets on 28 September 2026. Widgets");
        expect(band.querySelector("a")?.getAttribute("href")).toBe("/example/widgets");
        expect(container.querySelectorAll('[data-weight="primary"]')).toHaveLength(0);
    });

    it("checking and importing are still states, never spinners; imported and repeated are bands with no act", () => {
        expect(render(<ImportChecking />).container.textContent).toContain("Checking widgets.csv…");
        expect(render(<Importing />).container.querySelector('[aria-busy="true"][data-act="import"]')?.textContent).toBe("Importing…");
        const imported = render(<Imported />).container;
        expect(imported.querySelector('[data-band="imported"]')?.textContent).toContain("Imported 5 widgets on 28 September 2026.");
        const repeated = render(<ImportRepeated />).container;
        expect(repeated.querySelector('[data-band="imported"]')?.textContent).toBe("This file was imported on 28 September 2026.");
        expect(repeated.querySelectorAll("button")).toHaveLength(0);
    });

    it("a file with no rows: Nothing to import in ⟨file⟩., no primary", () => {
        const { container } = render(<NothingToImport />);
        expect(container.textContent).toContain("Nothing to import in widgets.csv.");
        expect(container.querySelectorAll('[data-weight="primary"]')).toHaveLength(0);
    });

    it("refused whole: Couldn't import under the head, the server's sentence, the file field and Import alive", () => {
        const { container } = render(<RefusedImport />);
        const alert = container.querySelector('[role="alert"]') as HTMLElement;
        expect(alert.getAttribute("data-seat")).toBe("list-head");
        expect(alert.querySelector("p")?.textContent).toBe("Couldn't import");
        expect(container.querySelector('input[type="file"]')).not.toBeNull();
        expect(container.querySelector('[data-act="import"]')).not.toBeNull();
    });

    it.each([...REQUIRED_STORY_EXPORTS])("%s has no axe violations", async (name) => {
        const Story = STORIES[name];
        const { container } = render(<Story />);
        const results = await axe.run(container, { rules: { region: { enabled: false } } });
        expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
});
