// patterns: §1
"use client";

/**
 * THE ONE DIALOG — the sheet primitive (patterns.md §1; house rule 70).
 *
 * Every floating surface in a product renders through this module and nothing
 * else draws a `<dialog>` or a `role="dialog"`: one head with the ONE dismiss,
 * a body that scrolls, and a foot that carries the sheet's acts and nothing
 * else — never Close · Cancel · Done in a foot, because the dismiss is already
 * in the head and a second one is a second way out that says less.
 *
 * WHY IT LIVES IN `primitives/`, WHICH OTHERWISE SHIPS EMPTY. A primitive
 * knows no product nouns, and the sheet's shape is not taste: it is the
 * book's §1 floor, and a rule that says "only the primitive draws a dialog"
 * needs the primitive to exist. It is drawn with the tokens alone, so a
 * product's look arrives through its tokens and its drawer, not by editing it.
 *
 * MODAL BY `showModal()`, CLOSED BY ITS OWNER. `open` is the owner's state;
 * this module mirrors it onto the element. Escape asks the owner to dismiss
 * (the browser's own close is prevented), so the state and the element never
 * disagree about whether the sheet is up.
 */

import { type ReactNode, useEffect, useId, useRef } from "react";

import { DIALOG_COPY } from "@/copy/dialog";

export type DialogProps = {
    /** Whether the sheet is up. The owner holds it; the element mirrors it. */
    readonly open: boolean;
    /** The head's words — the sheet's subject, or its act as a question. */
    readonly title: string;
    /** The ONE dismiss: the head's button and Escape both call it. */
    readonly onDismiss: () => void;
    /** The acts, and only acts. No dismiss word here (house rule 70). */
    readonly foot?: ReactNode;
    /**
     * Open with focus on the head's words: a sheet whose head is a QUESTION
     * (a confirm) lands on the question, so it is read before any act is
     * reached. Otherwise the opener places focus.
     */
    readonly focusTitle?: boolean;
    readonly children: ReactNode;
};

export function Dialog({ open, title, onDismiss, foot, focusTitle, children }: DialogProps) {
    const ref = useRef<HTMLDialogElement>(null);
    const head = useRef<HTMLHeadingElement>(null);
    const titleId = useId();

    useEffect(() => {
        const sheet = ref.current;
        if (sheet === null) return;
        if (open && !sheet.open) {
            sheet.showModal();
            if (focusTitle === true) head.current?.focus();
        }
        if (!open && sheet.open) sheet.close();
    }, [open, focusTitle]);

    return (
        <dialog
            ref={ref}
            aria-labelledby={titleId}
            onCancel={(event) => {
                event.preventDefault();
                onDismiss();
            }}
            style={{
                maxWidth: "var(--measure)",
                padding: 0,
                border: `1px solid var(--faint)`,
                borderRadius: "var(--radius)",
                background: "var(--surface-raised)",
                color: "var(--ink)",
            }}
        >
            <header
                style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "var(--space-2)",
                    padding: "var(--space-2) var(--space-3)",
                }}
            >
                <h2
                    id={titleId}
                    ref={head}
                    tabIndex={focusTitle === true ? -1 : undefined}
                    style={{ margin: 0, fontSize: "var(--type-section)" }}
                >
                    {title}
                </h2>
                <button type="button" onClick={onDismiss}>
                    {DIALOG_COPY.dismiss}
                </button>
            </header>
            <div style={{ padding: "0 var(--space-3) var(--space-3)", overflow: "auto" }}>{children}</div>
            {foot === undefined ? null : (
                <footer style={{ display: "flex", gap: "var(--space-2)", padding: "var(--space-2) var(--space-3)" }}>
                    {foot}
                </footer>
            )}
        </dialog>
    );
}
