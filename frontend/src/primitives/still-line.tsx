// patterns: §13
/**
 * A STILL LINE — a still shape at a line's height, for a `loading` state
 * (patterns.md §13): never a shimmer, never a spinner. `tall` stands in for an
 * act at the act floor.
 *
 * A primitive: every face draws its loading shapes with it. Its paint is
 * inline on purpose — a primitive has no stylesheet of its own (the book's
 * §26) — and its height follows its one prop.
 */

// road: still_line — A still placeholder line where words are being read. · example: frontend/src/screens/widget/widget-import.tsx::WidgetImport
export function StillLine({ tall }: { readonly tall?: boolean }) {
    return (
        <div
            // paint: a primitive's token-only shape, its height from its prop; it has no stylesheet (§26).
            style={{
                blockSize: tall === true ? "var(--act-min)" : "var(--type-title)",
                margin: "0 0 var(--space-2)",
                background: "var(--faint)",
                borderRadius: "var(--radius)",
            }}
        />
    );
}
