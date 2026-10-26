// patterns: §15
/**
 * THE ALERT PANEL — the refusal notice's box (patterns.md §15): one panel,
 * `role="alert"`, a left rule in the accent, no fill, no icon.
 *
 * A primitive: it draws the box and knows nothing of what a refusal carries —
 * the one refusal renderer (`@pilecap/ui/refusal-panel`) fills it. `seat` says
 * which act's row the panel answers (`data-seat`), and nothing else. Its paint
 * is inline on purpose: a primitive has no stylesheet of its own (the book's
 * §26).
 */

import type { ReactNode } from "react";

// road: alert_panel — The refusal notice's box: one panel, role alert, its seat named. · example: frontend/src/kit/refusal-panel.tsx::RefusalPanel
export function AlertPanel({ seat, children }: { readonly seat?: string | undefined; readonly children: ReactNode }) {
    return (
        <div
            role="alert"
            data-seat={seat}
            // paint: a primitive's token-only box; it has no stylesheet (§26).
            style={{
                border: "1px solid var(--accent)",
                borderLeft: "3px solid var(--accent)",
                borderRadius: "var(--radius)",
                padding: "var(--space-3)",
                background: "var(--surface-raised)",
            }}
        >
            {children}
        </div>
    );
}
