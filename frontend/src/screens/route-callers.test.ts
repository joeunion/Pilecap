import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * THE ROUTE TABLE'S CALLERS, CENSUSED — every screen names the surface it is drawn for.
 *
 * `routesOn`, `offSurface` and `pathFor` — and the two that read through them,
 * `remedyDoor` and the refusal panel's remedies — answer the whole table when
 * they are handed no surface, and in the whole table the first row that draws an
 * operation wins. That answer is right for exactly one caller: the root
 * layout's gate, before the server has named this address's surface. Anywhere
 * else it is a door that depends on row order — a staff screen that passed
 * nothing drew a customer page the day a customer row was put first.
 *
 * So every call in `src/` spells its surface argument, and never as the bare
 * word `undefined`. The population is read off the tree (every call and every
 * panel, by the TypeScript parser, never a list), and the readers' own tests
 * are the one file outside it: they pin the pre-boot answer on purpose.
 */

const SRC = resolve(process.cwd(), "src");

/** Where each reader takes its surface: the index of that argument. */
const SURFACE_ARGUMENT: Readonly<Record<string, number>> = { routesOn: 0, offSurface: 1, pathFor: 3, remedyDoor: 2 };

/** The component that reads the table through its remedies; it takes the surface as a prop. */
const PANEL = "RefusalPanel";

/** The readers' own home and their unit tests — the definitions and the pinned pre-boot answer. */
const OUTSIDE = new Set(["kit/routes.ts", "kit/routes.test.ts"]);

type Call = { readonly site: string; readonly reader: string; readonly surface: string | null };

/** Every `.ts`/`.tsx` file under `src/`, the generated client aside. */
function sources(directory: string): string[] {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) return entry.name === "generated" ? [] : sources(path);
        return /\.tsx?$/.test(entry.name) ? [path] : [];
    });
}

/** Every call of the readers in `text` — a JSX or `createElement` panel included — with the surface it spells (`null` for none). */
export function readerCalls(file: string, text: string): Call[] {
    const tree = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const calls: Call[] = [];
    const line = (node: ts.Node): number => tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1;
    const visit = (node: ts.Node): void => {
        if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text in SURFACE_ARGUMENT) {
            const reader = node.expression.text;
            const argument = node.arguments[SURFACE_ARGUMENT[reader] ?? -1];
            calls.push({ site: `${file}:${line(node)}`, reader, surface: argument === undefined ? null : argument.getText(tree) });
        }
        if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(tree) === PANEL) {
            const prop = node.attributes.properties.find((each) => ts.isJsxAttribute(each) && each.name.getText(tree) === "surface");
            const value = prop !== undefined && ts.isJsxAttribute(prop) ? prop.initializer : undefined;
            const spelled =
                value !== undefined && ts.isJsxExpression(value) ? (value.expression?.getText(tree) ?? null) : (value?.getText(tree) ?? null);
            calls.push({ site: `${file}:${line(node)}`, reader: PANEL, surface: spelled });
        }
        if (ts.isCallExpression(node) && node.expression.getText(tree).endsWith("createElement") && node.arguments[0]?.getText(tree) === PANEL) {
            const props = node.arguments[1];
            const prop =
                props !== undefined && ts.isObjectLiteralExpression(props)
                    ? props.properties.find((each) => each.name?.getText(tree) === "surface")
                    : undefined;
            const spelled = prop !== undefined && ts.isPropertyAssignment(prop) ? prop.initializer.getText(tree) : null;
            calls.push({ site: `${file}:${line(node)}`, reader: PANEL, surface: spelled });
        }
        ts.forEachChild(node, visit);
    };
    visit(tree);
    return calls;
}

/** A call that leaves its surface to the table's row order. */
function unnamed(call: Call): boolean {
    return call.surface === null || call.surface === "undefined";
}

const CALLS: readonly Call[] = sources(SRC)
    .map((path) => relative(SRC, path))
    .filter((file) => !OUTSIDE.has(file))
    .flatMap((file) => readerCalls(file, readFileSync(join(SRC, file), "utf8")));

describe("every caller of the route table names its surface", () => {
    it("finds the callers at all — a silent zero is a census that stopped looking", () => {
        // The population, printed so a floor is read from a line, never typed from memory.
        const readers = [...new Set(CALLS.map((call) => call.reader))].sort();
        const per = readers.map((reader) => `${reader} ${CALLS.filter((call) => call.reader === reader).length}`).join(", ");
        console.info(`route-table callers: ${CALLS.length} calls in ${new Set(CALLS.map((call) => call.site.split(":")[0])).size} files (${per})`);
        expect(CALLS.length).toBeGreaterThanOrEqual(2);
        // Both kinds of reader are reached: a census blind to the panel would stay green.
        expect(readers).toContain(PANEL);
        expect(readers).toContain("pathFor");
    });

    it("no call leaves its surface to the table's row order", () => {
        expect(CALLS.filter(unnamed).map((call) => `${call.site} ${call.reader}`)).toEqual([]);
    });

    it("the census sees a call or a panel that passes nothing, and one that passes undefined", () => {
        const planted = readerCalls(
            "planted.tsx",
            [
                'const a = pathFor("widget-list");',
                'const b = pathFor("widget-list", {}, undefined, undefined);',
                "const c = routesOn(undefined);",
                'const d = pathFor("widget-list", {}, undefined, STAFF_SURFACE);',
                "const e = <RefusalPanel refusal={r} words={w} />;",
                "const f = <RefusalPanel refusal={r} words={w} surface={undefined} />;",
                "const g = createElement(RefusalPanel, { refusal: r, words: w });",
                "const h = <RefusalPanel refusal={r} words={w} surface={STAFF_SURFACE} />;",
                "const i = remedyDoor(remedy);",
            ].join("\n"),
        );
        expect(planted.filter(unnamed).map((call) => call.site)).toEqual([
            "planted.tsx:1",
            "planted.tsx:2",
            "planted.tsx:3",
            "planted.tsx:5",
            "planted.tsx:6",
            "planted.tsx:7",
            "planted.tsx:9",
        ]);
    });
});
