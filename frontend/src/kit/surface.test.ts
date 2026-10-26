import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

/** The kit's names-only surface is derived: `pnpm run surface` writes it, and this regenerates it and diffs. */

const FRONTEND = process.cwd();
const SURFACE = resolve(FRONTEND, "src/kit/surface.json");

function derived(): string {
    return execFileSync(process.execPath, [resolve(FRONTEND, "scripts/surface.mjs"), "--print"], { cwd: FRONTEND, encoding: "utf8" });
}

describe("the kit's names-only surface", () => {
    const fresh = derived();

    it("is committed byte-identical to a fresh derivation — a hand edit or a stale file is red", () => {
        expect(existsSync(SURFACE), "src/kit/surface.json is missing — run `pnpm run surface`").toBe(true);
        expect(readFileSync(SURFACE, "utf8"), "src/kit/surface.json drifted — run `pnpm run surface`").toBe(fresh);
    });

    it("names every kit module, and every module exports something", () => {
        const modules = readdirSync(resolve(FRONTEND, "src/kit"))
            .filter((name) => /\.tsx?$/.test(name) && !/\.(test|stories)\.tsx?$/.test(name))
            .map((name) => `@pilecap/ui/${name.replace(/\.tsx?$/, "")}`)
            .sort();
        const surface = JSON.parse(fresh) as { modules: Record<string, string[]> };
        console.info(`kit surface: ${Object.keys(surface.modules).length} modules, ${Object.values(surface.modules).flat().length} names`);
        expect(Object.keys(surface.modules).sort()).toEqual(modules);
        expect(Object.entries(surface.modules).filter(([, names]) => names.length === 0)).toEqual([]);
    });
});
