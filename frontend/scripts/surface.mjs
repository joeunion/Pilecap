// Derives src/kit/surface.json — the exported names of every kit module, as a product imports them; `--check` exits 1 on drift.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const KIT = join(FRONTEND, "src/kit");
const OUT = join(KIT, "surface.json");

/** The kit's modules: every `.ts`/`.tsx` under `src/kit/` that is not a test or a story. */
function modules() {
    return readdirSync(KIT)
        .filter((name) => /\.tsx?$/.test(name) && !/\.(test|stories)\.tsx?$/.test(name))
        .sort();
}

/** The surface as the bytes `surface.json` must hold. */
export function surface() {
    const config = ts.readConfigFile(join(FRONTEND, "tsconfig.json"), ts.sys.readFile);
    const options = ts.parseJsonConfigFileContent(config.config, ts.sys, FRONTEND).options;
    const files = modules();
    const program = ts.createProgram(
        files.map((name) => join(KIT, name)),
        { ...options, noEmit: true, incremental: false },
    );
    const checker = program.getTypeChecker();
    const out = {};
    for (const name of files) {
        const source = program.getSourceFile(join(KIT, name));
        const symbol = source === undefined ? undefined : checker.getSymbolAtLocation(source);
        if (symbol === undefined) throw new Error(`surface: ${name} is not a module the compiler can read`);
        const names = checker.getExportsOfModule(symbol).map((each) => each.getName());
        out[`@pilecap/ui/${name.replace(/\.tsx?$/, "")}`] = [...new Set(names)].sort();
    }
    return `${JSON.stringify({ modules: out }, null, 2)}\n`;
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    const derived = surface();
    if (process.argv.includes("--check")) {
        let committed = "";
        try {
            committed = readFileSync(OUT, "utf8");
        } catch {
            committed = "";
        }
        if (committed !== derived) {
            process.stderr.write("surface: src/kit/surface.json differs from the kit's exports — run `pnpm run surface`\n");
            process.exit(1);
        }
    } else if (process.argv.includes("--print")) {
        process.stdout.write(derived);
    } else {
        writeFileSync(OUT, derived);
    }
}
