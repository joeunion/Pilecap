import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { ENTRY_STORY_EXTRAS, REQUIRED_STORY_EXPORTS, SURFACE_STATES, type SurfaceState } from "@/screens/state";
import * as welcomeStories from "@/screens/welcome/welcome-screen.stories";

declare global {
    interface ImportMeta {
        glob<T>(pattern: string, options: { readonly eager: true }): Record<string, T>;
    }
}

/** Every story module under `screens/`, and the screen module beside each (`x.stories.tsx` → `x.tsx`). */
const STORY_MODULES = import.meta.glob<Readonly<Record<string, unknown>>>("./**/*.stories.tsx", { eager: true });

/** A story is a PascalCase export; UPPER_CASE exports are fixtures and camelCase ones helpers. */
function storyNames(module: Readonly<Record<string, unknown>>): string[] {
    return Object.keys(module).filter((name) => /^[A-Z][a-z]/.test(name) && typeof module[name] === "function");
}

/** The sections a screen module declares in its header (`// patterns: §6, §9`); none for a placeholder or `none`. */
function declaredSections(storyPath: string): string[] {
    const source = readFileSync(resolve(process.cwd(), "src/screens", storyPath.replace(".stories.tsx", ".tsx")), "utf8");
    const line = source.split("\n").find((candidate) => /^\s*\/\/\s*patterns:/.test(candidate)) ?? "";
    return Array.from(line.matchAll(/§\d+/g), (m) => m[0]);
}

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
        // Set-equality, never `every`: the welcome screen declares no entry
        // (it is the template's placeholder), so for it a FIFTH export is as
        // wrong as three — the extra would be a state nothing else in the
        // system knows about.
        expect(declaredSections("./welcome/welcome-screen.stories.tsx")).toEqual([]);
        expect(Object.keys(welcomeStories).sort()).toEqual([...REQUIRED_STORY_EXPORTS].sort());
    });
});

describe("the stories rule (patterns.md, the preamble): the four are the floor, and every extra is an entry's", () => {
    const modules = Object.entries(STORY_MODULES);

    it("finds every story module under screens/", () => {
        expect(modules.map(([path]) => path)).toContain("./welcome/welcome-screen.stories.tsx");
        expect(modules.length).toBeGreaterThan(1);
    });

    it.each(modules.map(([path]) => path))("%s exports the four, and each extra is named by an entry its screen declares", (path) => {
        const names = storyNames(STORY_MODULES[path] ?? {});
        for (const required of REQUIRED_STORY_EXPORTS) expect(names, path).toContain(required);
        const allowed = new Set(declaredSections(path).flatMap((section) => ENTRY_STORY_EXTRAS[section] ?? []));
        const extras = names.filter((name) => !(REQUIRED_STORY_EXPORTS as readonly string[]).includes(name));
        expect(extras.filter((name) => !allowed.has(name)), `${path}: extras no declared entry names`).toEqual([]);
    });
});

describe("SurfaceState's empty", () => {
    it("is legal as a sentence alone, with no act (patterns.md §14); tsc refuses this file if nextAct is required", () => {
        const alone: SurfaceState<number> = { kind: "empty" };
        const proposing: SurfaceState<number> = { kind: "empty", nextAct: { label: "Sign in" } };
        expect(alone.kind === "empty" && alone.nextAct).toBeUndefined();
        expect(proposing.kind === "empty" && proposing.nextAct?.label).toBe("Sign in");
    });
});
