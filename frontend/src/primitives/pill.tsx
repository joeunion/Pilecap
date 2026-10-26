// patterns: §16
/**
 * THE PILL — a state word after a name (patterns.md §16): tinted, never
 * filled; one neutral tone; the label role's size and tracking.
 *
 * A primitive: it knows the word it is handed and nothing about what it
 * describes. `className` is a published prop, so a face can join the pill to
 * its name in its own sheet (the worked face's wrap rule) without restyling it.
 * Its paint is inline on purpose: a primitive has no stylesheet of its own
 * (the book's §26).
 */

// road: pill — A state word worn as a pill beside a name. · example: frontend/src/screens/widget/widget-list.tsx::NameWithPill
export function Pill({ word, className }: { readonly word: string; readonly className?: string }) {
    return (
        <span
            data-pill=""
            data-tone="neutral"
            className={className}
            // paint: a primitive's token-only word; it has no stylesheet (§26).
            style={{ fontSize: "var(--type-label)", letterSpacing: "var(--type-label-tracking)", fontWeight: 400, color: "var(--muted)" }}
        >
            {word}
        </span>
    );
}
