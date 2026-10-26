// patterns: §10
/**
 * THE CARD — a head (its title, four words or fewer) and a body (patterns.md §10).
 *
 * A primitive: it knows no product noun, and every face draws its cards with
 * it rather than inlining the box a second time. It is drawn with the tokens
 * alone — a product's look reaches it through its tokens, never by a second
 * card beside it — and it has no foot until a card has acts, which the face
 * hands it as children.
 *
 * Its paint is inline on purpose: a primitive has no stylesheet of its own
 * (the book's §26 gives a sheet to a face, and the tokens layer declares and
 * styles nothing else), so its token-only shape lives with it.
 */

import type { ReactNode } from "react";

// road: card — A card: a head and a body, drawn with the tokens alone. · example: frontend/src/screens/widget/widget-history.tsx::HistoryCard
export function Card({ title, busy, children }: { readonly title: string; readonly busy?: boolean; readonly children: ReactNode }) {
    return (
        <section
            aria-label={title}
            aria-busy={busy === true ? "true" : undefined}
            // paint: a primitive's token-only box; it has no stylesheet (§26).
            style={{
                background: "var(--surface-raised)",
                border: "1px solid var(--faint)",
                borderRadius: "var(--radius)",
                padding: "var(--space-3)",
            }}
        >
            <h2
                // paint: a primitive's token-only head; it has no stylesheet (§26).
                style={{ fontSize: "var(--type-section)", margin: "0 0 var(--space-2)" }}
            >
                {title}
            </h2>
            {children}
        </section>
    );
}
