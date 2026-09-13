import { describe, expect, it } from "vitest";

import { REQUIRED_STORY_EXPORTS, SURFACE_STATES } from "@/screens/state";
import * as welcomeStories from "@/screens/welcome/welcome-screen.stories";

describe("SurfaceState is the four-state total function", () => {
    it("names exactly loading, empty, error and ready", () => {
        expect([...SURFACE_STATES]).toEqual(["loading", "empty", "error", "ready"]);
    });

    it("never says `populated`", () => {
        // The lexicon pin, as a test rather than as a comment. `populated` is
        // the word a sibling product used, and one census reads these names: a
        // screen spelling a fifth word is a screen the census cannot see.
        for (const forbidden of ["populated", "loaded", "success", "data"]) {
            expect(SURFACE_STATES as readonly string[]).not.toContain(forbidden);
        }
    });

    it("has no fifth state", () => {
        // P16 ruling 2. Transport failure is a member of `error`'s input
        // vocabulary, not a state — asserted here because a fifth member would
        // otherwise arrive quietly, one screen at a time.
        expect(SURFACE_STATES).toHaveLength(4);
    });
});

describe("REQUIRED_STORY_EXPORTS", () => {
    it("names exactly Loading, Empty, Error and Ready", () => {
        expect([...REQUIRED_STORY_EXPORTS]).toEqual(["Loading", "Empty", "Error", "Ready"]);
    });

    it("is one name per state, in the same order", () => {
        expect(REQUIRED_STORY_EXPORTS.map((name) => name.toLowerCase())).toEqual([...SURFACE_STATES]);
    });

    it("is what the welcome screen's stories actually export — set equality, both directions", () => {
        // Set-equality, never `every`: a story module with a FIFTH export is as
        // wrong as one with three, because the extra one is a state nothing
        // else in the system knows about.
        expect(Object.keys(welcomeStories).sort()).toEqual([...REQUIRED_STORY_EXPORTS].sort());
    });
});
